/* public.js — v3 clean rewrite */
const THEME_KEY = "torneio-theme";

const state = { data: null, activeTab: "jogos", filter: "all", search: "", classTab: "groups", lastFocus: null };

const $ = (s, c) => (c || document).querySelector(s);
const $$ = (s, c) => [...(c || document).querySelectorAll(s)];

const tabs     = $$(".tab");
const panels   = $$(".panel");
const subtabs  = $$(".subtab");
const subpanels = $$(".subpanel");
const chips    = $$(".chip");
const searchIn = $("#match-search");
const refreshBtn = $("#refresh-btn");
const themeBtn = $("#theme-toggle");
const modal    = $("#match-modal");
const modalBody = $("#modal-content");
const announcer = $("#announcer");
let trapHandler = null;

/* ── helpers ──────────────────────────────────────────────────────────── */
function esc(v) {
    return String(v ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");
}
function preferredTheme() { return matchMedia("(prefers-color-scheme:dark)").matches ? "dark" : "light"; }
function applyTheme(t) {
    const th = t || preferredTheme();
    document.documentElement.setAttribute("data-theme", th);
    if (themeBtn) themeBtn.textContent = th === "dark" ? "Modo claro" : "Modo escuro";
}
function toggleTheme() { const c = document.documentElement.getAttribute("data-theme") || preferredTheme(); const n = c === "dark" ? "light" : "dark"; localStorage.setItem(THEME_KEY, n); applyTheme(n); }
function announce(msg) { if (announcer) announcer.textContent = msg; }

function fmtDT(v) { if (!v) return "Data por definir"; return new Intl.DateTimeFormat("pt-PT",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"}).format(new Date(v)); }
function fmtDate(v) { if (!v) return "Por definir"; return new Intl.DateTimeFormat("pt-PT",{day:"2-digit",month:"long",hour:"2-digit",minute:"2-digit"}).format(new Date(v)); }
function statusMeta(s) {
    return { live:{label:"A decorrer",icon:"[LIVE]"}, scheduled:{label:"Agendado",icon:"[AG]"}, completed:{label:"Terminado",icon:"[OK]"}, postponed:{label:"Adiado",icon:"[ADIADO]"}, suspended:{label:"Suspenso",icon:"[STOP]"} }[s] || {label:s||"Estado",icon:"[?]"};
}
function evLabel(t) { return {goal:"Golo",yellow_card:"Cartão amarelo",red_card:"Cartão vermelho",note:"Nota"}[t] || t || "Evento"; }
function teamName(t) { return t?.name || "A definir"; }
function sc(v) { return v === null || v === undefined || v === "" ? "-" : String(v); }
function statusChip(s) { const m = statusMeta(s); return `<span class="status-chip status-${s||"scheduled"}"><span aria-hidden="true">${esc(m.icon)}</span><span>${esc(m.label)}</span></span>`; }

/* ── tabs / subtabs ───────────────────────────────────────────────────── */
function setTab(tab, focus) {
    state.activeTab = tab;
    tabs.forEach(b => { const a = b.dataset.tab === tab; b.classList.toggle("is-active",a); b.setAttribute("aria-selected",a); b.tabIndex = a ? 0 : -1; if (a && focus) b.focus(); });
    panels.forEach(p => p.classList.toggle("is-active", p.dataset.panel === tab));
    announce(`Secção ${tab} selecionada.`);
}
function setSubtab(st, focus) {
    state.classTab = st;
    subtabs.forEach(b => { const a = b.dataset.st === st; b.classList.toggle("is-active",a); b.setAttribute("aria-selected",a); b.tabIndex = a ? 0 : -1; if (a && focus) b.focus(); });
    subpanels.forEach(p => p.classList.toggle("is-active", p.dataset.sp === st));
}
function arrowNav(e, list, setter, key) {
    const i = list.indexOf(e.currentTarget); if (i < 0) return;
    let n = i;
    if (e.key === "ArrowRight") n = (i+1) % list.length;
    else if (e.key === "ArrowLeft") n = (i-1+list.length) % list.length;
    else if (e.key === "Home") n = 0;
    else if (e.key === "End") n = list.length - 1;
    else return;
    e.preventDefault(); setter(list[n].dataset[key], true);
}

/* ── sort / filter ────────────────────────────────────────────────────── */
function sorted(matches) { return [...matches].sort((a,b) => (Number(a.game_number||9999)-Number(b.game_number||9999)) || String(a.scheduled_at||"").localeCompare(String(b.scheduled_at||""))); }
function groupBy(matches) {
    const m = new Map();
    matches.forEach(g => { const l = g.phase_label || g.phase_title || "Jogos"; if (!m.has(l)) m.set(l,[]); m.get(l).push(g); });
    return [...m.entries()].map(([label,items]) => ({label,items}));
}
function filtered() {
    if (!state.data) return [];
    return sorted(state.data.matches).filter(m => {
        const h = `${teamName(m.home_team)} ${teamName(m.away_team)} ${m.phase_title} ${m.phase_label||""} ${m.game_label||""}`.toLowerCase();
        const sok = !state.search || h.includes(state.search);
        const ko = m.phase !== "group";
        const fok = state.filter === "all" || m.status === state.filter || (state.filter === "knockout" && ko);
        return sok && fok;
    });
}

/* ── render ────────────────────────────────────────────────────────────── */
function renderSummary() {
    const s = state.data.settings;
    $("#event-name").textContent = s.name;
    $("#event-subtitle").textContent = `${s.slogan} — ${fmtDate(s.start_at)} até ${fmtDate(s.end_at)}`;
}

function liveCard(m) {
    return `<button class="match-card match-card--live match-card--spotlight" type="button" data-mid="${m.id}">
        <div class="match-card__meta"><span>${esc(m.game_label||`Jogo ${m.game_number||"-"}`)}</span>${statusChip(m.status)}</div>
        <div class="fixture-row__phase">${esc(m.phase_label||m.phase_title)}</div>
        <div class="match-card__row"><span class="team-name">${esc(teamName(m.home_team))}</span><span class="score">${esc(sc(m.home_score))}</span></div>
        <div class="match-card__row"><span class="team-name">${esc(teamName(m.away_team))}</span><span class="score">${esc(sc(m.away_score))}</span></div>
        <p class="status-description">${esc(fmtDT(m.scheduled_at))} — ${esc(m.venue||"Local por definir")}</p>
    </button>`;
}
function fixtureRow(m, done) {
    return `<button class="fixture-row ${done?"fixture-row--completed":""}" type="button" data-mid="${m.id}">
        <div class="fixture-row__main">
            <div class="fixture-row__top"><span class="fixture-row__label">${esc(m.game_label||`Jogo ${m.game_number||"-"}`)}</span>${done?`<strong class="fixture-row__result">${esc(sc(m.home_score))} - ${esc(sc(m.away_score))}</strong>`:statusChip(m.status)}</div>
            <div class="fixture-row__phase">${esc(m.phase_label||m.phase_title)}</div>
            <div class="fixture-row__teams"><span class="fixture-row__team">${esc(teamName(m.home_team))}</span><span class="fixture-row__team">${esc(teamName(m.away_team))}</span></div>
        </div>
        <div class="fixture-row__side"><strong>${esc(fmtDT(m.scheduled_at))}</strong><span>${esc(m.venue||"Local por definir")}</span></div>
    </button>`;
}
function renderGrouped(id, groups, empty, done) {
    const el = document.getElementById(id); if (!el) return;
    if (!groups.length) { el.innerHTML = `<div class="empty-state">${esc(empty)}</div>`; return; }
    el.innerHTML = groups.map(g => `<section class="fixture-group"><div class="fixture-group__header"><strong>${esc(g.label)}</strong><span>${g.items.length} jogo(s)</span></div><div class="fixture-group__list">${g.items.map(m => fixtureRow(m,done)).join("")}</div></section>`).join("");
}
function bindMatchBtns() { $$("[data-mid]").forEach(b => b.addEventListener("click", () => openModal(Number(b.dataset.mid), b))); }

function renderMatches() {
    const f = filtered();
    const live = f.filter(m => m.status === "live");
    const up = f.filter(m => ["scheduled","postponed","suspended"].includes(m.status)).sort((a,b) => String(a.scheduled_at||"").localeCompare(String(b.scheduled_at||"")));
    const done = [...f.filter(m => m.status === "completed")].reverse();

    $("#live-pill").textContent = live.length;
    $("#up-pill").textContent = up.length;
    $("#done-pill").textContent = done.length;

    $("#live-matches").innerHTML = live.length ? live.map(liveCard).join("") : '<div class="empty-state">Sem jogos a decorrer neste momento.</div>';
    renderGrouped("upcoming-matches", groupBy(up), "Sem próximos jogos neste filtro.", false);
    renderGrouped("completed-matches", groupBy(done), "Sem jogos terminados neste filtro.", true);
    bindMatchBtns();
}

function renderGroupStandings() {
    $("#group-standings").innerHTML = state.data.standings.map(g => `
        <article class="standing-card">
            <div class="standing-card__header"><div><span class="standing-kicker">Fase de grupos</span><h3>${esc(g.group)}</h3></div></div>
            <div class="table-wrap"><table class="standings-table"><caption class="sr-only">Tabela do ${esc(g.group)}</caption>
                <thead><tr><th>#</th><th>Equipa</th><th>PJ</th><th>V</th><th>E</th><th>D</th><th>GM</th><th>GS</th><th>DG</th><th>P</th></tr></thead>
                <tbody>${g.rows.map((r,i) => `<tr class="${r.qualified?`qualified-row ${r.qualification_type==="best_third"?"qualified-row--best-third":""}`:""}">`+
                    `<td><span class="position-badge">${i+1}</span></td><td class="team-cell">${esc(r.team_name)}</td>`+
                    `<td>${r.played}</td><td>${r.won}</td><td>${r.drawn}</td><td>${r.lost}</td>`+
                    `<td>${r.goals_for}</td><td>${r.goals_against}</td><td>${r.goal_difference}</td><td><strong>${r.points}</strong></td></tr>`).join("")}
                </tbody></table></div>
        </article>`).join("");
}

function renderKnockout() {
    const br = state.data.bracket;
    const qf = br.find(r => r.phase === "quarterfinal");
    const sf = br.find(r => r.phase === "semifinal");
    const fi = br.find(r => r.phase === "final");
    const tp = br.find(r => r.phase === "third_place");

    const mc = m => `<article class="mini-bracket__match">
        <div class="mini-bracket__meta"><span>${esc(m.game_label||`Jogo ${m.game_number||"-"}`)}</span>${statusChip(m.status)}</div>
        <div class="mini-bracket__teams">
            <div class="mini-bracket__team"><span>${esc(teamName(m.home_team))}</span><strong>${esc(sc(m.home_score))}</strong></div>
            <div class="mini-bracket__team"><span>${esc(teamName(m.away_team))}</span><strong>${esc(sc(m.away_score))}</strong></div>
        </div>
        <p class="status-description">${esc(fmtDT(m.scheduled_at))} | ${esc(m.venue||"Local por definir")}</p>
    </article>`;

    const roundHtml = (r, cls, title, id) => `<section class="mini-bracket__round ${cls}" aria-labelledby="${id}">
        <div class="mini-bracket__round-header"><h4 id="${id}">${title}</h4></div>
        <div class="mini-bracket__stack${cls.includes("final")?" mini-bracket__stack--center":""}">
            ${r?.matches?.length ? r.matches.map(mc).join("") : `<div class="empty-state">${title} por definir.</div>`}
        </div></section>`;

    $("#knockout-overview").innerHTML = `
        <section class="mini-bracket-card">
            <div class="standing-card__header"><div><span class="standing-kicker">Fase final</span><h3>Quartos até final</h3></div><span class="standing-note">Leitura rápida do caminho até ao troféu</span></div>
            <div class="mini-bracket mini-bracket--three-rounds">
                ${roundHtml(qf,"mini-bracket__round--quarters","Quartos","mq")}
                ${roundHtml(sf,"mini-bracket__round--semis","Meias-finais","ms")}
                ${roundHtml(fi,"mini-bracket__round--final","Final","mf")}
            </div>
            <section class="mini-bracket__extra" aria-labelledby="mt">
                <div class="mini-bracket__round-header"><h4 id="mt">3.º / 4.º lugar</h4></div>
                <div class="mini-bracket__stack mini-bracket__stack--single">
                    ${tp?.matches?.length ? tp.matches.map(mc).join("") : '<div class="empty-state">Jogo de 3.º/4.º ainda por definir.</div>'}
                </div>
            </section>
        </section>`;
}

function renderScorers() {
    const s = state.data.top_scorers;
    $("#top-scorers").innerHTML = s.length ? `
        <table class="standings-table scorer-table"><caption class="sr-only">Melhores marcadores</caption>
        <thead><tr><th>#</th><th>Jogador</th><th>Equipa</th><th>Golos</th></tr></thead>
        <tbody>${s.map(r => `<tr><td><span class="position-badge">${r.rank}</span></td><td class="team-cell">${esc(r.name)}</td><td>${esc(r.team_name)}</td><td><strong>${r.goals}</strong></td></tr>`).join("")}</tbody></table>`
        : '<div class="empty-state">Ainda sem golos registados.</div>';
}

function renderClassifications() { renderGroupStandings(); renderKnockout(); renderScorers(); }

function renderBar() {
    const groups = state.data.bar_products.reduce((a,i) => { const k = i.category||"Outros"; (a[k]=a[k]||[]).push(i); return a; }, {});
    $("#bar-products").innerHTML = Object.entries(groups).map(([cat,items]) => `
        <section class="bar-category"><h3>${esc(cat)}</h3><div class="bar-category__items">${items.map(i => `
            <article class="bar-item" data-stock="${esc(i.availability||"available")}"><div><strong>${esc(i.name)}</strong><p>${esc(i.availability==="unavailable"?"Indisponível":i.availability==="low"?"Quase a acabar":"Disponível")}</p></div><strong>${Number(i.price||0).toFixed(2)} €</strong></article>`).join("")}
        </div></section>`).join("");
}

function renderAnnouncements() {
    const a = state.data.announcements;
    $("#announcements").innerHTML = a.length ? a.map(i => `
        <article class="announcement-card" data-urgent="${i.is_urgent?"true":"false"}">
            <div class="info-meta"><span>${esc(fmtDT(i.published_at))}</span><span>${esc(i.is_urgent?"URGENTE":"Normal")}</span></div>
            <h3>${esc(i.title)}</h3><p>${esc(i.message)}</p>
        </article>`).join("") : '<div class="empty-state">Sem avisos publicados.</div>';
}

function renderInfo() {
    const s = state.data.settings;
    $("#settings-info").innerHTML = `
        <p><strong>Data:</strong> ${esc(fmtDate(s.start_at))} até ${esc(fmtDate(s.end_at))}</p>
        <p><strong>Local:</strong> ${esc(s.venue||"Por definir")} — ${esc(s.city||"Por definir")}</p>
        <p><strong>Organização:</strong> ${esc(s.organizer||"Por definir")}</p>
        <p><strong>Contactos:</strong> ${esc(s.contacts||"Por definir")}</p>`;
    $("#info-sections").innerHTML = state.data.info_sections.map(i => `
        <article class="info-card"><h3>${esc(i.title)}</h3><p>${esc(i.content)}</p>${i.emphasis?`<p class="status-description">${esc(i.emphasis)}</p>`:""}</article>`).join("");
}

/* ── modal ─────────────────────────────────────────────────────────────── */
function trapFocus(e) {
    if (e.key !== "Tab") return;
    const f = [...modal.querySelectorAll('button,[href],input,select,textarea,[tabindex]:not([tabindex="-1"])')].filter(el => !el.disabled);
    if (!f.length) return;
    if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length-1].focus(); }
    else if (!e.shiftKey && document.activeElement === f[f.length-1]) { e.preventDefault(); f[0].focus(); }
}
function openModal(id, trigger) {
    const m = state.data.matches.find(x => x.id === id); if (!m) return;
    state.lastFocus = trigger || document.activeElement;

    const isLive = m.status === "live";
    const isDone = m.status === "completed";
    const showScore = isLive || isDone;

    /* split events by team */
    const homeId = m.home_team_id;
    const awayId = m.away_team_id;
    const homeGoals = m.timeline.filter(e => e.event_type === "goal" && e.team_id === homeId);
    const awayGoals = m.timeline.filter(e => e.event_type === "goal" && e.team_id === awayId);

    function evIcon(t) {
        if (t === "goal") return "⚽";
        if (t === "yellow_card") return "🟨";
        if (t === "red_card") return "🟥";
        return "📋";
    }
    function goalLine(goals) {
        return goals.map(g => `<span class="md-goal">${esc(g.player_name || "?")} ${g.minute != null ? `<em>${g.minute}'</em>` : ""}</span>`).join("");
    }

    /* timeline rows — Flashscore style: home events left, away events right */
    const timeline = [...m.timeline].sort((a,b) => (a.minute ?? 999) - (b.minute ?? 999));
    const timelineHtml = timeline.length ? timeline.map(ev => {
        const isHome = ev.team_id === homeId;
        return `<div class="md-event ${isHome ? "md-event--home" : "md-event--away"}">
            ${isHome ? `<span class="md-event__text">${esc(ev.player_name || ev.team_name || "?")} <em>${esc(evLabel(ev.event_type))}</em></span>` : '<span class="md-event__text"></span>'}
            <span class="md-event__min">${evIcon(ev.event_type)} ${ev.minute != null ? ev.minute + "'" : ""}</span>
            ${!isHome ? `<span class="md-event__text">${esc(ev.player_name || ev.team_name || "?")} <em>${esc(evLabel(ev.event_type))}</em></span>` : '<span class="md-event__text"></span>'}
        </div>`;
    }).join("") : '<div class="empty-state">Sem eventos registados.</div>';

    modalBody.innerHTML = `
        <div class="md-header">
            <span class="kicker-inline">${esc(m.game_label || `Jogo ${m.game_number || "-"}`)} — ${esc(m.phase_title)}</span>
            ${statusChip(m.status)}
        </div>

        <div class="md-scoreboard ${isLive ? "md-scoreboard--live" : ""}">
            <div class="md-team md-team--home">
                <strong>${esc(teamName(m.home_team))}</strong>
                <div class="md-goalscorers">${goalLine(homeGoals)}</div>
            </div>
            <div class="md-score">
                <span class="md-score__value">${showScore ? esc(sc(m.home_score)) : "-"}</span>
                <span class="md-score__sep">:</span>
                <span class="md-score__value">${showScore ? esc(sc(m.away_score)) : "-"}</span>
            </div>
            <div class="md-team md-team--away">
                <strong>${esc(teamName(m.away_team))}</strong>
                <div class="md-goalscorers">${goalLine(awayGoals)}</div>
            </div>
        </div>

        <div class="md-info">
            <span>📅 ${esc(fmtDT(m.scheduled_at))}</span>
        </div>

        <div class="md-section">
            <h3 class="md-section__title">Cronologia do jogo</h3>
            <div class="md-timeline">${timelineHtml}</div>
        </div>`;

    modal.classList.remove("is-hidden");
    trapHandler = e => { if (e.key === "Escape") { closeModal(); return; } trapFocus(e); };
    document.addEventListener("keydown", trapHandler);
    modal.querySelector(".modal__close").focus();
    announce(`Detalhe do ${m.game_label||"jogo"} aberto.`);
}
function closeModal() {
    modal.classList.add("is-hidden");
    if (trapHandler) { document.removeEventListener("keydown", trapHandler); trapHandler = null; }
    if (state.lastFocus) state.lastFocus.focus();
    announce("Detalhe do jogo fechado.");
}

/* ── boot ──────────────────────────────────────────────────────────────── */
async function loadData() {
    const r = await fetch("/api/public/bootstrap", { cache: "no-store" });
    if (!r.ok) throw new Error("Falha ao carregar dados");
    state.data = await r.json();
    renderSummary(); renderMatches(); renderClassifications(); renderBar(); renderAnnouncements(); renderInfo();
    announce("Dados públicos atualizados.");
}

function wire() {
    tabs.forEach(b => { b.addEventListener("click", () => setTab(b.dataset.tab)); b.addEventListener("keydown", e => arrowNav(e, tabs, setTab, "tab")); });
    subtabs.forEach(b => { b.addEventListener("click", () => setSubtab(b.dataset.st)); b.addEventListener("keydown", e => arrowNav(e, subtabs, setSubtab, "st")); });
    chips.forEach(b => b.addEventListener("click", () => {
        state.filter = b.dataset.filter;
        chips.forEach(c => { const a = c === b; c.classList.toggle("is-active",a); c.setAttribute("aria-pressed",a); });
        renderMatches();
    }));
    searchIn.addEventListener("input", () => { state.search = searchIn.value.trim().toLowerCase(); renderMatches(); });
    refreshBtn.addEventListener("click", () => loadData().catch(e => announce(e.message)));
    themeBtn?.addEventListener("click", toggleTheme);
    $$("[data-close-modal]").forEach(el => el.addEventListener("click", closeModal));
}

applyTheme(localStorage.getItem(THEME_KEY) || preferredTheme());
wire();
loadData().catch(e => announce(e.message));
