"""I Torneio Chefe Carvalho — servidor v3 (from scratch)."""
from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DEFAULT_STORAGE = BASE_DIR / "storage"

def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False

def resolve_storage() -> Path:
    env = os.environ.get("DATA_DIR")
    if env:
        p = Path(env)
        if _writable(p):
            return p
    if _writable(DEFAULT_STORAGE):
        return DEFAULT_STORAGE
    fallback = Path(os.environ.get("TMPDIR") or os.environ.get("TEMP") or "/tmp") / "torneio-storage"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback

STORAGE = resolve_storage()
DB_PATH = STORAGE / "tournament.db"

# ── Config ───────────────────────────────────────────────────────────────────
SESSION_COOKIE = "staff_session"
SESSION_TTL_HOURS = 48
MAX_LOGIN_ATTEMPTS = 8
LOGIN_WINDOW_MIN = 10
_login_attempts: dict[str, list[datetime]] = {}

PHASE_LABELS = {
    "group": "Fase de grupos",
    "quarterfinal": "Quartos de final",
    "semifinal": "Meias-finais",
    "third_place": "3.º / 4.º lugar",
    "final": "Final",
}
KNOCKOUT_ORDER = ["quarterfinal", "semifinal", "third_place", "final"]

RESOURCE_CONFIG: dict[str, dict] = {
    "teams": {
        "table": "teams",
        "fields": {
            "name": "text", "short_name": "text", "group_name": "text",
            "location": "text", "coach": "text", "notes": "text", "sort_order": "int",
        },
    },
    "players": {
        "table": "players",
        "fields": {
            "team_id": "int", "name": "text", "shirt_number": "text",
            "position": "text", "goals_adjustment": "int", "is_active": "bool",
        },
    },
    "matches": {
        "table": "matches",
        "fields": {
            "game_number": "int", "phase": "text", "phase_label": "text",
            "round_order": "int", "scheduled_at": "text", "venue": "text",
            "status": "text", "home_team_id": "int?", "away_team_id": "int?",
            "home_score": "int?", "away_score": "int?", "notes": "text",
            "referees": "text", "mvp_player_id": "int?", "is_featured": "bool",
        },
    },
    "match-events": {
        "table": "match_events",
        "fields": {
            "match_id": "int", "minute": "int?", "team_id": "int?",
            "player_id": "int?", "event_type": "text", "description": "text",
            "created_at": "text",
        },
    },
    "bar-products": {
        "table": "bar_products",
        "fields": {
            "name": "text", "category": "text", "price": "float",
            "availability": "text", "sort_order": "int",
        },
    },
    "announcements": {
        "table": "announcements",
        "fields": {
            "title": "text", "message": "text", "is_urgent": "bool",
            "published_at": "text",
        },
    },
    "info-sections": {
        "table": "info_sections",
        "fields": {
            "category": "text", "title": "text", "content": "text",
            "emphasis": "text", "sort_order": "int",
        },
    },
}

# ── Helpers ───────────────────────────────────────────────────────────────────
def now_iso() -> str:
    return datetime.now().isoformat(timespec="minutes")

def parse_dt(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None

def hash_pw(pw: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 260_000)
    return f"{salt}${h.hex()}"

def verify_pw(pw: str, stored: str) -> bool:
    try:
        salt, expected = stored.split("$", 1)
    except ValueError:
        return False
    return hmac.compare_digest(hash_pw(pw, salt).split("$", 1)[1], expected)

def coerce(value, spec: str):
    nullable = spec.endswith("?")
    base = spec.rstrip("?")
    if value in (None, ""):
        return None if nullable else {"int": 0, "float": 0.0, "bool": 0}.get(base, "")
    if base == "int":
        return int(value)
    if base == "float":
        return float(str(value).replace(",", "."))
    if base == "bool":
        return 1 if value in (True, 1, "1", "true", "True", "on", "yes", "sim") else 0
    return str(value).strip()

def phase_label(phase: str) -> str:
    return PHASE_LABELS.get(phase, phase.replace("_", " ").title())

def rows(cursor) -> list[dict]:
    return [dict(r) for r in cursor.fetchall()]

# ── Database ──────────────────────────────────────────────────────────────────
def get_db() -> sqlite3.Connection:
    STORAGE.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES admin_users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS tournament_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    name TEXT NOT NULL, slogan TEXT,
    start_at TEXT, end_at TEXT,
    venue TEXT, city TEXT, organizer TEXT,
    regulation_summary TEXT, contacts TEXT, notes TEXT
);
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE, short_name TEXT,
    group_name TEXT, location TEXT, coach TEXT,
    notes TEXT, sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id INTEGER NOT NULL, name TEXT NOT NULL,
    shirt_number TEXT, position TEXT,
    goals_adjustment INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_number INTEGER NOT NULL DEFAULT 0,
    phase TEXT NOT NULL, phase_label TEXT,
    round_order INTEGER NOT NULL DEFAULT 0,
    scheduled_at TEXT, venue TEXT,
    status TEXT NOT NULL DEFAULT 'scheduled',
    home_team_id INTEGER, away_team_id INTEGER,
    home_score INTEGER, away_score INTEGER,
    notes TEXT, referees TEXT,
    mvp_player_id INTEGER, is_featured INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (home_team_id) REFERENCES teams(id) ON DELETE SET NULL,
    FOREIGN KEY (away_team_id) REFERENCES teams(id) ON DELETE SET NULL,
    FOREIGN KEY (mvp_player_id) REFERENCES players(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS match_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL, minute INTEGER,
    team_id INTEGER, player_id INTEGER,
    event_type TEXT NOT NULL, description TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE,
    FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE SET NULL,
    FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS bar_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, category TEXT,
    price REAL NOT NULL DEFAULT 0,
    availability TEXT NOT NULL DEFAULT 'available',
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL, message TEXT NOT NULL,
    is_urgent INTEGER NOT NULL DEFAULT 0,
    published_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS info_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT, title TEXT NOT NULL,
    content TEXT NOT NULL, emphasis TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0
);
"""

def seed_database(conn: sqlite3.Connection) -> None:
    """Seed runs ONCE — only when tournament_settings is empty."""
    if conn.execute("SELECT COUNT(*) FROM tournament_settings").fetchone()[0] > 0:
        return

    conn.execute("""
        INSERT INTO tournament_settings
        (id,name,slogan,start_at,end_at,venue,city,organizer,regulation_summary,contacts,notes)
        VALUES (1,?,?,?,?,?,?,?,?,?,?)
    """, (
        "I Torneio Chefe Carvalho",
        "Torneio de Futsal 24h",
        "2026-04-03T18:00", "2026-04-04T18:00",
        "Pavilhão Municipal de Santa Marta de Penaguião",
        "Santa Marta de Penaguião",
        "Secção Desportiva da A.H. Bombeiros Voluntários de Fontes",
        "Três grupos. Apuram-se os dois primeiros de cada grupo e os dois melhores terceiros para os quartos de final. Melhor marcador, fair play e melhor GR ficam fechados no fim da fase de grupos.",
        "Kosta: 919884744 | Falim: 919816302 | Corporação dos Bombeiros Voluntários de Fontes: 254810200",
        "Prémios oficiais: 1.º, 2.º, 3.º, 4.º, melhor marcador, fair play, melhor GR, equipa mais distante, MVP Final, MVP 3.º/4.º e taça bar.",
    ))

    teams = [
        (1,"B.V. Porto","Porto","Grupo A","Porto","Rui Costa","Equipa confirmada.",3),
        (2,"B.V. Santa Marta De Penaguião","Santa Marta","Grupo A","Santa Marta de Penaguião","Tiago Ribeiro","Entrada forte na prova.",2),
        (3,"B.V. Flavienses","Flavienses","Grupo B","Chaves","Bruno Pires","Bloco muito organizado.",7),
        (4,"B.V. Castelo De Paiva","Castelo De Paiva","Grupo C","Castelo de Paiva","André Silva","Equipa intensa no duelo.",9),
        (5,"B.V. Resende","Resende","Grupo C","Resende","Marco Moura","Transição rápida.",12),
        (6,"B.V. Vidago","Vidago","Grupo A","Vidago","Carlos Gomes","Boa rotação de plantel.",1),
        (7,"B.V. Alijó","Alijó","Grupo B","Alijó","Nuno Cardoso","Equipa com experiência.",5),
        (8,"B.V. Montalegre","Montalegre","Grupo B","Montalegre","Ruben Teixeira","Jogo físico e direto.",8),
        (9,"B.V. Mondim De Basto","Mondim De Basto","Grupo C","Mondim de Basto","Luis Correia","Sai bem em contra-ataque.",11),
        (10,"B.V. Provezende","Provezende","Grupo A","Provezende","Pedro Barros","Plantel equilibrado.",4),
        (11,"B.V. Entre Os Rios","Entre Os Rios","Grupo B","Entre Os Rios","Daniel Sousa","Equipa muito competitiva.",6),
        (12,"B.V. Amarante","Amarante","Grupo C","Amarante","Sergio Cunha","Uma das candidatas.",10),
    ]
    conn.executemany("INSERT INTO teams (id,name,short_name,group_name,location,coach,notes,sort_order) VALUES (?,?,?,?,?,?,?,?)", teams)

    players = [
        (1,1,"Tiago Pereira","7","Ala",0,1),(2,1,"Rui Carneiro","1","GR",0,1),
        (3,2,"Diogo Marques","10","Pivo",0,1),(4,2,"Bruno Fernandes","1","GR",0,1),
        (5,3,"Andre Costa","8","Universal",0,1),(6,3,"Vitor Leal","1","GR",0,1),
        (7,4,"Helder Sousa","9","Pivo",0,1),(8,4,"Paulo Teles","1","GR",0,1),
        (9,5,"Leandro Cruz","11","Ala",0,1),(10,5,"Joao Faria","1","GR",0,1),
        (11,6,"Miguel Pinto","10","Universal",0,1),(12,6,"Hugo Martins","1","GR",0,1),
        (13,7,"Andre Teixeira","9","Pivo",0,1),(14,7,"Rui Lima","1","GR",0,1),
        (15,8,"Ruben Melo","7","Ala",0,1),(16,8,"Fabio Pires","1","GR",0,1),
        (17,9,"Nuno Vieira","11","Ala",0,1),(18,9,"Ricardo Silva","1","GR",0,1),
        (19,10,"Pedro Alves","6","Fixo",0,1),(20,10,"Tiago Campos","1","GR",0,1),
        (21,11,"Daniel Monteiro","10","Pivo",0,1),(22,11,"Luis Magalhaes","1","GR",0,1),
        (23,12,"Sergio Rocha","9","Pivo",0,1),(24,12,"Marco Azevedo","1","GR",0,1),
    ]
    conn.executemany("INSERT INTO players (id,team_id,name,shirt_number,position,goals_adjustment,is_active) VALUES (?,?,?,?,?,?,?)", players)

    V = "Campo Principal"
    S = "scheduled"
    R = "Árbitros por definir"
    matches = [
        (1,1,"group","Grupo A",1,"2026-04-03T14:00",V,S,6,2,None,None,"Jogo 1 · Grupo A",R,None,0),
        (2,2,"group","Grupo B",2,"2026-04-03T15:00",V,S,7,11,None,None,"Jogo 2 · Grupo B",R,None,0),
        (3,3,"group","Grupo C",3,"2026-04-03T16:00",V,S,4,12,None,None,"Jogo 3 · Grupo C",R,None,0),
        (4,4,"group","Grupo A",4,"2026-04-03T17:00",V,S,1,10,None,None,"Jogo 4 · Grupo A",R,None,0),
        (5,5,"group","Grupo B",5,"2026-04-03T18:00",V,S,3,8,None,None,"Jogo 5 · Grupo B",R,None,0),
        (6,6,"group","Grupo C",6,"2026-04-03T19:00",V,S,9,5,None,None,"Jogo 6 · Grupo C",R,None,0),
        (7,7,"group","Grupo A",7,"2026-04-03T20:00",V,S,6,1,None,None,"Jogo 7 · Grupo A",R,None,0),
        (8,8,"group","Grupo B",8,"2026-04-03T21:00",V,S,7,3,None,None,"Jogo 8 · Grupo B",R,None,0),
        (9,9,"group","Grupo C",9,"2026-04-03T22:00",V,S,4,9,None,None,"Jogo 9 · Grupo C",R,None,0),
        (10,10,"group","Grupo A",10,"2026-04-03T23:00",V,S,2,10,None,None,"Jogo 10 · Grupo A",R,None,0),
        (11,11,"group","Grupo B",11,"2026-04-04T00:00",V,S,11,8,None,None,"Jogo 11 · Grupo B",R,None,0),
        (12,12,"group","Grupo C",12,"2026-04-04T01:00",V,S,12,5,None,None,"Jogo 12 · Grupo C",R,None,0),
        (13,13,"group","Grupo A",13,"2026-04-04T02:00",V,S,6,10,None,None,"Jogo 13 · Grupo A",R,None,0),
        (14,14,"group","Grupo B",14,"2026-04-04T03:00",V,S,7,8,None,None,"Jogo 14 · Grupo B",R,None,0),
        (15,15,"group","Grupo C",15,"2026-04-04T04:00",V,S,4,5,None,None,"Jogo 15 · Grupo C",R,None,0),
        (16,16,"group","Grupo A",16,"2026-04-04T05:00",V,S,2,1,None,None,"Jogo 16 · Grupo A",R,None,0),
        (17,17,"group","Grupo B",17,"2026-04-04T06:00",V,S,11,3,None,None,"Jogo 17 · Grupo B",R,None,0),
        (18,18,"group","Grupo C",18,"2026-04-04T07:00",V,S,12,9,None,None,"Jogo 18 · Grupo C",R,None,1),
        (19,19,"quarterfinal","Quartos de Final",1,"2026-04-04T09:30",V,S,None,None,None,None,"J19 · 1.º Grupo A vs 2.º melhor 3.º",R,None,0),
        (20,20,"quarterfinal","Quartos de Final",2,"2026-04-04T10:10",V,S,None,None,None,None,"J20 · 1.º Grupo B vs 1.º melhor 3.º",R,None,0),
        (21,21,"quarterfinal","Quartos de Final",3,"2026-04-04T10:50",V,S,None,None,None,None,"J21 · 1.º Grupo C vs 2.º Grupo B",R,None,0),
        (22,22,"quarterfinal","Quartos de Final",4,"2026-04-04T11:30",V,S,None,None,None,None,"J22 · 2.º Grupo A vs 2.º Grupo C",R,None,0),
        (23,23,"semifinal","Meias-finais",1,"2026-04-04T14:00",V,S,None,None,None,None,"J23 · Vencedor J19 vs Vencedor J21",R,None,0),
        (24,24,"semifinal","Meias-finais",2,"2026-04-04T14:45",V,S,None,None,None,None,"J24 · Vencedor J20 vs Vencedor J22",R,None,0),
        (25,25,"third_place","3.º / 4.º Lugar",1,"2026-04-04T17:00",V,S,None,None,None,None,"J25 · Derrotado J23 vs Derrotado J24",R,None,0),
        (26,26,"final","Final",1,"2026-04-04T17:45",V,S,None,None,None,None,"J26 · Vencedor J23 vs Vencedor J24",R,None,1),
    ]
    conn.executemany("""
        INSERT INTO matches (id,game_number,phase,phase_label,round_order,scheduled_at,venue,status,
        home_team_id,away_team_id,home_score,away_score,notes,referees,mvp_player_id,is_featured)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, matches)

    bar_products = [
        (1,"Menu Quartel 1 - Arroz Branco, Batata Frita e Bifanas","Menu Quartel",6.00,"available",1),
        (2,"Menu Quartel 2 - Arroz Branco, Batata Frita e Panados","Menu Quartel",6.00,"available",2),
        (3,"Menu Quartel 3 - Arroz Branco, Batata Frita e Filetes de Pescada","Menu Quartel",6.00,"available",3),
        (4,"Menu Quartel 4 - Arroz Branco, Batata Frita e Kebab","Menu Quartel",6.00,"available",4),
        (5,"Tosta Mista","Bar 24h",2.00,"available",10),
        (6,"Bifana no Pao","Bar 24h",3.00,"available",11),
        (7,"Folhado Misto","Bar 24h",1.50,"available",12),
        (8,"Box Kebab","Bar 24h",7.00,"available",13),
        (9,"Box Batata + Molho","Bar 24h",3.00,"available",14),
        (10,"Pizza","Bar 24h",1.50,"available",15),
        (11,"Caldo Verde","Menu da Noite",2.50,"available",20),
        (12,"Bifana no Pao","Menu da Noite",3.00,"available",21),
        (13,"Folhado Misto","Menu da Noite",1.50,"available",22),
        (14,"Tosta Mista","Menu da Noite",2.00,"available",23),
        (15,"Box de Kebab","Menu da Noite",7.00,"available",24),
        (16,"Box Batata + Molho","Menu da Noite",3.00,"available",25),
        (17,"Fatia de Pizza","Menu da Noite",1.50,"available",26),
    ]
    conn.executemany("INSERT INTO bar_products (id,name,category,price,availability,sort_order) VALUES (?,?,?,?,?,?)", bar_products)

    conn.executemany("INSERT INTO announcements (id,title,message,is_urgent,published_at) VALUES (?,?,?,?,?)", [
        (1,"Abertura do secretariado","As equipas devem confirmar presença até 30 minutos antes do primeiro jogo.",1,"2026-04-03T17:40"),
        (2,"Prémios de fase de grupos","Melhor marcador, fair play e melhor GR ficam definidos no fim da fase de grupos.",0,"2026-04-03T18:05"),
        (3,"Contactos oficiais","Kosta 919884744 | Falim 919816302 | Corporação dos Bombeiros de Fontes 254810200.",0,"2026-04-03T18:15"),
    ])

    conn.executemany("INSERT INTO info_sections (id,category,title,content,emphasis,sort_order) VALUES (?,?,?,?,?,?)", [
        (1,"Evento","Data e horário","De 3 para 4 de abril, em formato 24h.","Abertura oficial às 18:00 de sexta-feira.",1),
        (2,"Formato","Formato","Três grupos. Passam os dois primeiros de cada grupo e os dois melhores terceiros para os quartos de final.","Quartos com oito apurados: vencedores dos grupos, segundos classificados e os dois melhores 3.ºs.",2),
        (3,"Fase Final","Caminho para a final","Quartos de final com oito equipas apuradas a partir dos grupos. Meias-finais: J23 vencedor J19 vs vencedor J21 e J24 vencedor J20 vs vencedor J22.","Final: vencedor J23 vs vencedor J24. Jogo de 3.º e 4.º lugar: derrotado J23 vs derrotado J24.",3),
        (4,"Contactos","Contactos oficiais da organização","Kosta 919884744 | Falim 919816302 | Corporação dos Bombeiros de Fontes 254810200.","Usar estes contactos para dúvidas operacionais.",4),
        (5,"Prémios","Prémios oficiais","1.º, 2.º, 3.º, 4.º, melhor marcador, fair play, melhor GR, equipa mais distante, MVP Final, MVP 3.º/4.º e taça bar.","Melhor marcador, fair play e melhor GR fecham no fim da fase de grupos.",5),
    ])

    un = os.environ.get("ADMIN_USERNAME", "staff")
    pw = os.environ.get("ADMIN_PASSWORD", "chefe2026")
    conn.execute("INSERT INTO admin_users (username,password_hash,created_at) VALUES (?,?,?)", (un, hash_pw(pw), now_iso()))

def init_db() -> None:
    with get_db() as conn:
        conn.executescript(SCHEMA)
        seed_database(conn)

# ── Data layer ────────────────────────────────────────────────────────────────
def fetch_all(conn: sqlite3.Connection) -> dict:
    settings = dict(conn.execute("SELECT * FROM tournament_settings WHERE id=1").fetchone())
    teams = rows(conn.execute("SELECT * FROM teams ORDER BY sort_order,name"))
    players = rows(conn.execute("""
        SELECT p.*, t.name AS team_name FROM players p
        JOIN teams t ON t.id=p.team_id ORDER BY t.sort_order, p.name
    """))
    matches = rows(conn.execute("""
        SELECT * FROM matches ORDER BY
        CASE status WHEN 'live' THEN 0 WHEN 'scheduled' THEN 1 WHEN 'completed' THEN 2 ELSE 3 END,
        game_number, scheduled_at, id
    """))
    events = rows(conn.execute("SELECT * FROM match_events ORDER BY match_id, COALESCE(minute,999), id"))
    bar = rows(conn.execute("SELECT * FROM bar_products ORDER BY sort_order, category, name"))
    ann = rows(conn.execute("SELECT * FROM announcements ORDER BY published_at DESC, id DESC"))
    info = rows(conn.execute("SELECT * FROM info_sections ORDER BY sort_order, category, id"))
    return dict(settings=settings, teams=teams, players=players, matches=matches,
                events=events, bar_products=bar, announcements=ann, info_sections=info)

def enrich_matches(data: dict) -> list[dict]:
    tid = {t["id"]: t for t in data["teams"]}
    pid = {p["id"]: p for p in data["players"]}
    evm: dict[int, list] = {}
    for e in data["events"]:
        ec = dict(e)
        ec["player_name"] = pid.get(e["player_id"], {}).get("name")
        ec["team_name"] = tid.get(e["team_id"], {}).get("name")
        evm.setdefault(e["match_id"], []).append(ec)

    out = []
    for m in data["matches"]:
        mc = dict(m)
        mc["phase_title"] = phase_label(m["phase"])
        mc["game_label"] = f"Jogo {mc['game_number']}" if mc.get("game_number") else "Jogo por definir"
        mc["home_team"] = tid.get(m["home_team_id"])
        mc["away_team"] = tid.get(m["away_team_id"])
        mc["mvp_player"] = pid.get(m["mvp_player_id"])
        mc["timeline"] = evm.get(m["id"], [])
        mc["scorers"] = [x for x in mc["timeline"] if x["event_type"] == "goal"]
        if mc["home_team_id"] and mc["away_team_id"]:
            dh = sum(1 for x in mc["scorers"] if x["team_id"] == mc["home_team_id"])
            da = sum(1 for x in mc["scorers"] if x["team_id"] == mc["away_team_id"])
            if mc["scorers"] or mc["home_score"] is None or mc["away_score"] is None:
                mc["home_score"] = dh
                mc["away_score"] = da
        out.append(mc)
    return out

def compute_standings(teams: list[dict], matches: list[dict]) -> list[dict]:
    groups: dict[str, dict[int, dict]] = {}
    tid = {t["id"]: t for t in teams}
    for t in teams:
        g = t.get("group_name") or "Sem grupo"
        groups.setdefault(g, {})[t["id"]] = dict(
            team_id=t["id"], team_name=t["name"], short_name=t.get("short_name"),
            played=0, won=0, drawn=0, lost=0,
            goals_for=0, goals_against=0, goal_difference=0,
            points=0, position=0, qualified=False, qualification_type="",
        )
    for m in matches:
        if m["phase"] != "group" or m["status"] != "completed":
            continue
        if not m["home_team_id"] or not m["away_team_id"]:
            continue
        if m["home_score"] is None or m["away_score"] is None:
            continue
        hg = tid[m["home_team_id"]]["group_name"]
        h = groups[hg][m["home_team_id"]]
        ag = tid[m["away_team_id"]]["group_name"]
        a = groups[ag][m["away_team_id"]]
        h["played"] += 1; a["played"] += 1
        h["goals_for"] += m["home_score"]; h["goals_against"] += m["away_score"]
        a["goals_for"] += m["away_score"]; a["goals_against"] += m["home_score"]
        if m["home_score"] > m["away_score"]:
            h["won"] += 1; a["lost"] += 1; h["points"] += 3
        elif m["home_score"] < m["away_score"]:
            a["won"] += 1; h["lost"] += 1; a["points"] += 3
        else:
            h["drawn"] += 1; a["drawn"] += 1; h["points"] += 1; a["points"] += 1

    pending = any(m for m in matches if m["phase"] == "group" and m.get("home_team_id") and m.get("away_team_id") and m["status"] != "completed")
    locked = not pending
    thirds: list[dict] = []
    standings = []
    for gn, table_d in groups.items():
        tbl = list(table_d.values())
        for r in tbl:
            r["goal_difference"] = r["goals_for"] - r["goals_against"]
        tbl.sort(key=lambda r: (-r["points"], -r["goal_difference"], -r["goals_for"], r["team_name"]))
        for i, r in enumerate(tbl, 1):
            r["position"] = i
            if i <= 2:
                r["qualified"] = True; r["qualification_type"] = "direct"
            elif i == 3:
                thirds.append(r)
        standings.append(dict(group=gn, rows=tbl))
    thirds.sort(key=lambda r: (-r["points"], -r["goal_difference"], -r["goals_for"], r["team_name"]))
    best = {r["team_id"] for r in thirds[:2]}
    for s in standings:
        for r in s["rows"]:
            if r["team_id"] in best:
                r["qualified"] = True; r["qualification_type"] = "best_third"
    standings.sort(key=lambda s: s["group"])
    return standings

def compute_scorers(players: list[dict], events: list[dict]) -> list[dict]:
    g: dict[int, int] = {}
    for e in events:
        if e["event_type"] == "goal" and e["player_id"]:
            g[e["player_id"]] = g.get(e["player_id"], 0) + 1
    out = []
    for p in players:
        total = g.get(p["id"], 0) + int(p.get("goals_adjustment") or 0)
        if total <= 0:
            continue
        out.append(dict(player_id=p["id"], name=p["name"], team_id=p["team_id"],
                        team_name=p.get("team_name", ""), goals=total))
    out.sort(key=lambda x: (-x["goals"], x["name"]))
    for i, s in enumerate(out, 1):
        s["rank"] = i
    return out

def build_bracket(matches: list[dict]) -> list[dict]:
    grouped: dict[str, list] = {p: [] for p in KNOCKOUT_ORDER}
    for m in matches:
        if m["phase"] in grouped:
            grouped[m["phase"]].append(m)
    return [dict(phase=p, label=PHASE_LABELS[p], matches=sorted(grouped[p], key=lambda x: (x.get("game_number") or 999, x.get("scheduled_at") or ""))) for p in KNOCKOUT_ORDER]

def summary(matches: list[dict]) -> dict:
    live = [m for m in matches if m["status"] == "live"]
    sched = [m for m in matches if m["status"] == "scheduled"]
    comp = [m for m in matches if m["status"] == "completed"]
    nxt = None
    dated = [m for m in sched if parse_dt(m["scheduled_at"])]
    if live:
        nxt = live[0]
    elif dated:
        nxt = min(dated, key=lambda m: parse_dt(m["scheduled_at"]))
    return dict(live_count=len(live), scheduled_count=len(sched), completed_count=len(comp), next_match=nxt)

def public_payload(conn: sqlite3.Connection) -> dict:
    d = fetch_all(conn)
    em = enrich_matches(d)
    return dict(settings=d["settings"], summary=summary(em), standings=compute_standings(d["teams"], em),
                matches=em, bracket=build_bracket(em), top_scorers=compute_scorers(d["players"], d["events"]),
                bar_products=d["bar_products"], announcements=d["announcements"],
                info_sections=d["info_sections"], teams=d["teams"], updated_at=now_iso())

def admin_payload(conn: sqlite3.Connection, username: str) -> dict:
    d = fetch_all(conn)
    return dict(user=dict(username=username),
                public=public_payload(conn),
                entities=dict(settings=d["settings"], teams=d["teams"], players=d["players"],
                              matches=enrich_matches(d), match_events=d["events"],
                              bar_products=d["bar_products"], announcements=d["announcements"],
                              info_sections=d["info_sections"]))

# ── HTTP handler ──────────────────────────────────────────────────────────────
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(STATIC_DIR), **kw)

    def log_message(self, *_): pass

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "script-src 'self' 'unsafe-inline'; object-src 'none'; "
            "base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
        super().end_headers()

    # ── helpers ──
    def _ip(self) -> str:
        return self.client_address[0] if self.client_address else "0.0.0.0"

    def _rate_ok(self) -> bool:
        cutoff = datetime.now() - timedelta(minutes=LOGIN_WINDOW_MIN)
        att = [t for t in _login_attempts.get(self._ip(), []) if t >= cutoff]
        _login_attempts[self._ip()] = att
        return len(att) < MAX_LOGIN_ATTEMPTS

    def _note_fail(self):
        _login_attempts.setdefault(self._ip(), []).append(datetime.now())

    def _reset_fails(self):
        _login_attempts.pop(self._ip(), None)

    def _cookie_flags(self) -> str:
        """Return Secure flag only when behind HTTPS proxy."""
        proto = (self.headers.get("X-Forwarded-Proto") or "").lower()
        secure = "; Secure" if proto == "https" else ""
        return f"; HttpOnly{secure}; Path=/; SameSite=Lax"

    def _body_json(self) -> dict:
        n = int(self.headers.get("Content-Length", "0"))
        if n <= 0:
            return {}
        raw = self.rfile.read(n).decode("utf-8")
        return json.loads(raw) if raw else {}

    def _json(self, obj: dict, status: int = 200):
        body = json.dumps(obj, ensure_ascii=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, name: str):
        body = (STATIC_DIR / name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str, status: int = 303):
        self.send_response(status)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _static(self, rel: str):
        fp = (STATIC_DIR / rel).resolve()
        if not fp.is_file() or STATIC_DIR not in fp.parents:
            self.send_error(404); return
        ct = mimetypes.guess_type(fp.name)[0] or "application/octet-stream"
        if ct.startswith("text/") or ct in ("application/javascript", "application/json"):
            ct += "; charset=utf-8"
        body = fp.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(body)

    # ── session ──
    def _session(self) -> dict | None:
        ck = self.headers.get("Cookie", "")
        token = None
        for seg in ck.split(";"):
            k, _, v = seg.strip().partition("=")
            if k == SESSION_COOKIE:
                token = v; break
        if not token:
            return None
        with get_db() as conn:
            r = conn.execute("""
                SELECT s.token, s.expires_at, u.id AS user_id, u.username
                FROM sessions s JOIN admin_users u ON u.id=s.user_id WHERE s.token=?
            """, (token,)).fetchone()
            if not r:
                return None
            exp = parse_dt(r["expires_at"])
            if not exp or exp < datetime.now():
                conn.execute("DELETE FROM sessions WHERE token=?", (token,))
                return None
            return dict(r)

    def _require_auth(self) -> dict | None:
        s = self._session()
        if not s:
            self._json({"error": "Autenticação necessária."}, 401)
        return s

    # ── CRUD helpers ──
    def _normalize(self, fields: dict, payload: dict, create: bool) -> dict:
        out: dict = {}
        for f, spec in fields.items():
            if f in ("created_at", "published_at") and not payload.get(f):
                out[f] = now_iso(); continue
            if f not in payload:
                continue
            out[f] = coerce(payload.get(f), spec)
        return out

    def _prepare(self, conn, resource: str, payload: dict, vals: dict, *, create: bool) -> dict:
        if resource == "teams":
            if "group_name" in vals and vals["group_name"] in ("A", "B", "C"):
                vals["group_name"] = f"Grupo {vals['group_name']}"
            if create and "short_name" not in vals and vals.get("name"):
                vals["short_name"] = vals["name"]
            if create and "sort_order" not in vals:
                vals["sort_order"] = (conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 FROM teams").fetchone()[0])
        if resource == "players":
            if create and "is_active" not in vals: vals["is_active"] = 1
            if create and "goals_adjustment" not in vals: vals["goals_adjustment"] = 0
        if resource == "matches":
            phase = str(vals.get("phase") or payload.get("phase") or "group")
            if create and "game_number" not in vals:
                vals["game_number"] = conn.execute("SELECT COALESCE(MAX(game_number),0)+1 FROM matches").fetchone()[0]
            if "round_order" not in vals:
                vals["round_order"] = vals.get("game_number") or payload.get("game_number") or 0
            if "phase_label" not in vals:
                vals["phase_label"] = phase_label(phase)
            if create and "status" not in vals: vals["status"] = "scheduled"
            if create and "venue" not in vals:
                r = conn.execute("SELECT venue FROM tournament_settings WHERE id=1").fetchone()
                vals["venue"] = r["venue"] if r else ""
            if create and "is_featured" not in vals: vals["is_featured"] = 0
        if resource == "match-events":
            if not vals.get("description"):
                vals["description"] = self._event_desc(conn, vals)
        if resource == "bar-products":
            if create and "availability" not in vals: vals["availability"] = "available"
            if create and "sort_order" not in vals:
                vals["sort_order"] = conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 FROM bar_products").fetchone()[0]
        if resource == "info-sections":
            if create and "category" not in vals: vals["category"] = "Informação"
            if "emphasis" not in vals: vals["emphasis"] = ""
            if create and "sort_order" not in vals:
                vals["sort_order"] = conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 FROM info_sections").fetchone()[0]
        return vals

    def _event_desc(self, conn, vals: dict) -> str:
        pn = tn = ""
        if vals.get("player_id"):
            r = conn.execute("SELECT name, team_id FROM players WHERE id=?", (vals["player_id"],)).fetchone()
            if r:
                pn = r["name"]; vals["team_id"] = vals.get("team_id") or r["team_id"]
        if vals.get("team_id"):
            r = conn.execute("SELECT name FROM teams WHERE id=?", (vals["team_id"],)).fetchone()
            if r: tn = r["name"]
        et = str(vals.get("event_type") or "note")
        who = pn or tn or "jogador por definir"
        if et == "goal": return f"Golo de {who}."
        if et == "yellow_card": return f"Cartão amarelo para {who}."
        if et == "red_card": return f"Cartão vermelho para {who}."
        return f"Evento registado para {who}."

    def _create(self, resource: str, payload: dict):
        cfg = RESOURCE_CONFIG[resource]
        vals = self._normalize(cfg["fields"], payload, True)
        try:
            with get_db() as conn:
                vals = self._prepare(conn, resource, payload, vals, create=True)
                cols = ", ".join(vals)
                phs = ", ".join("?" for _ in vals)
                cur = conn.execute(f"INSERT INTO {cfg['table']} ({cols}) VALUES ({phs})", tuple(vals.values()))
                item = dict(conn.execute(f"SELECT * FROM {cfg['table']} WHERE id=?", (cur.lastrowid,)).fetchone())
            self._json({"ok": True, "item": item}, 201)
        except (sqlite3.IntegrityError, ValueError) as e:
            self._json({"error": str(e)}, 400)

    def _update(self, resource: str, rid: int, payload: dict):
        cfg = RESOURCE_CONFIG[resource]
        vals = self._normalize(cfg["fields"], payload, False)
        try:
            with get_db() as conn:
                vals = self._prepare(conn, resource, payload, vals, create=False)
                if not vals:
                    self._json({"error": "Sem campos para atualizar."}, 400); return
                sets = ", ".join(f"{c}=?" for c in vals)
                conn.execute(f"UPDATE {cfg['table']} SET {sets} WHERE id=?", (*vals.values(), rid))
                row = conn.execute(f"SELECT * FROM {cfg['table']} WHERE id=?", (rid,)).fetchone()
                if not row:
                    self._json({"error": "Registo não encontrado."}, 404); return
                self._json({"ok": True, "item": dict(row)})
        except (sqlite3.IntegrityError, ValueError) as e:
            self._json({"error": str(e)}, 400)

    def _delete(self, resource: str, rid: int):
        cfg = RESOURCE_CONFIG[resource]
        try:
            with get_db() as conn:
                conn.execute(f"DELETE FROM {cfg['table']} WHERE id=?", (rid,))
            self._json({"ok": True})
        except sqlite3.IntegrityError as e:
            self._json({"error": str(e)}, 400)

    def _extract_id(self, path: str):
        parts = [p for p in path.removeprefix("/api/admin/").split("/") if p]
        if len(parts) != 2:
            return None, None
        try:
            return parts[0], int(parts[1])
        except ValueError:
            return None, None

    # ── routes ──
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/": self._html("index.html"); return
        if p == "/staff-login":
            if self._session():
                self._redirect("/admin")
            else:
                self._html("admin.html")
            return
        if p == "/admin":
            if self._session():
                self._html("admin.html")
            else:
                self._redirect("/staff-login")
            return
        if p == "/static/admin.html":
            self._redirect("/staff-login")
            return
        if p.startswith("/static/"): self._static(p.removeprefix("/static/")); return
        if p == "/api/public/bootstrap":
            with get_db() as conn: self._json(public_payload(conn)); return
        if p == "/api/auth/session":
            s = self._session()
            self._json({"authenticated": bool(s), "username": s["username"] if s else None}); return
        if p == "/api/admin/bootstrap":
            s = self._require_auth()
            if not s: return
            with get_db() as conn: self._json(admin_payload(conn, s["username"])); return
        self.send_error(404)

    def do_POST(self):
        p = urlparse(self.path).path
        if p == "/api/auth/login":
            if not self._rate_ok():
                self._json({"error": "Demasiadas tentativas. Tenta mais tarde."}, 429); return
            body = self._body_json()
            un = str(body.get("username", "")).strip()
            pw = str(body.get("password", ""))
            with get_db() as conn:
                u = conn.execute("SELECT * FROM admin_users WHERE username=?", (un,)).fetchone()
                if not u or not verify_pw(pw, u["password_hash"]):
                    self._note_fail()
                    self._json({"error": "Credenciais inválidas."}, 401); return
                self._reset_fails()
                tk = secrets.token_urlsafe(32)
                exp = (datetime.now() + timedelta(hours=SESSION_TTL_HOURS)).isoformat(timespec="minutes")
                conn.execute("DELETE FROM sessions WHERE user_id=?", (u["id"],))
                conn.execute("INSERT INTO sessions (token,user_id,expires_at) VALUES (?,?,?)", (tk, u["id"], exp))
            resp = json.dumps({"ok": True, "username": un}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(resp)))
            self.send_header("Set-Cookie", f"{SESSION_COOKIE}={tk}{self._cookie_flags()}; Max-Age={SESSION_TTL_HOURS*3600}")
            self.end_headers()
            self.wfile.write(resp); return
        if p == "/api/auth/logout":
            s = self._session()
            if s:
                with get_db() as conn:
                    conn.execute("DELETE FROM sessions WHERE token=?", (s["token"],))
            resp = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(resp)))
            self.send_header("Set-Cookie", f"{SESSION_COOKIE}=deleted{self._cookie_flags()}; Max-Age=0")
            self.end_headers()
            self.wfile.write(resp); return
        if p.startswith("/api/admin/"):
            if not self._require_auth(): return
            res = p.removeprefix("/api/admin/")
            if res in RESOURCE_CONFIG:
                self._create(res, self._body_json()); return
        self.send_error(404)

    def do_PUT(self):
        p = urlparse(self.path).path
        if not p.startswith("/api/admin/"): self.send_error(404); return
        if not self._require_auth(): return
        body = self._body_json()
        if p == "/api/admin/settings":
            flds = {k: "text" for k in ("name","slogan","start_at","end_at","venue","city","organizer","regulation_summary","contacts","notes")}
            vals = self._normalize(flds, body, False)
            if not vals:
                self._json({"error": "Sem alterações."}, 400); return
            sets = ", ".join(f"{c}=?" for c in vals)
            with get_db() as conn:
                conn.execute(f"UPDATE tournament_settings SET {sets} WHERE id=1", tuple(vals.values()))
                item = dict(conn.execute("SELECT * FROM tournament_settings WHERE id=1").fetchone())
            self._json({"ok": True, "item": item}); return
        res, rid = self._extract_id(p)
        if res and rid and res in RESOURCE_CONFIG:
            self._update(res, rid, body); return
        self.send_error(404)

    def do_DELETE(self):
        p = urlparse(self.path).path
        if not p.startswith("/api/admin/"): self.send_error(404); return
        if not self._require_auth(): return
        res, rid = self._extract_id(p)
        if res and rid and res in RESOURCE_CONFIG:
            self._delete(res, rid); return
        self.send_error(404)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    init_db()
    port = int(os.environ.get("PORT", "8000"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Torneio v3 em http://127.0.0.1:{port}")
    srv.serve_forever()

if __name__ == "__main__":
    main()
