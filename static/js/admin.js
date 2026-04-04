/* admin.js — v3 clean rewrite */
const THEME_KEY = "torneio-theme";
const state = { payload: null };

const managedForms = ["team-form","player-form","match-form","event-form","bar-form","announcement-form","info-form"];
const managedTargets = ["admin-summary","teams-list","players-list","matches-list","events-list","bar-list","announcements-list","info-list"];

const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

const loginView = $("#login-view");
const adminView = $("#admin-view");
const loginForm = $("#login-form");
const logoutBtn = $("#logout-button");
const sessionBadge = $("#session-badge");
const toast = $("#toast");
const themeBtn = $("#theme-toggle");
const matchStatus = $("#match-form select[name='status']");
const matchForfeit = $("#match-form select[name='forfeit_side']");
const evMatch = $("#event-match");
const evTeam = $("#event-team");
const evPlayer = $("#event-player");
const evType = $("#event-form select[name='event_type']");
const barCategorySelect = document.querySelector('#bar-form select[name="category"]');
const barCategoryDefaults = ["Menu Quartel","Bar 24h","Menu da Noite","Bebidas com Álcool","Bebidas sem Álcool"];

/* ── helpers ──────────────────────────────────────────────────────────── */
function esc(v) { return String(v??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;"); }
function fmtDT(v) { if (!v) return "Sem data"; return new Intl.DateTimeFormat("pt-PT",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"}).format(new Date(v)); }
function evLabel(t) { return {goal:"Golo",foul:"Falta",yellow_card:"Cartão amarelo",red_card:"Cartão vermelho"}[t]||t||"Evento"; }
function statusLabel(s) { return {scheduled:"Agendado",live:"Em curso",completed:"Terminado"}[s]||s||"Agendado"; }
function normGroup(v) { return String(v||"").replace("Grupo ","") || "-"; }

function showToast(msg, err) {
    toast.textContent = `${err?"Erro:":"Info:"} ${msg}`;
    toast.style.background = err ? "rgba(122,31,24,.98)" : "rgba(22,33,45,.98)";
    toast.classList.add("is-visible");
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => toast.classList.remove("is-visible"), 2600);
}

function preferredTheme() { return matchMedia("(prefers-color-scheme:dark)").matches?"dark":"light"; }
function applyTheme(t) { const th=t||preferredTheme(); document.documentElement.setAttribute("data-theme",th); if(themeBtn) themeBtn.textContent=th==="dark"?"Modo claro":"Modo escuro"; }
function toggleTheme() { const c=document.documentElement.getAttribute("data-theme")||preferredTheme(); const n=c==="dark"?"light":"dark"; localStorage.setItem(THEME_KEY,n); applyTheme(n); }

/* ── API ───────────────────────────────────────────────────────────────── */
async function api(path, opts={}) {
    const h = new Headers(opts.headers||{});
    if (opts.body && !h.has("Content-Type")) h.set("Content-Type","application/json");
    const r = await fetch(path, { cache:"no-store", credentials:"same-origin", headers:h, ...opts });
    const raw = await r.text();
    let data = {};
    if (raw) { try { data = JSON.parse(raw); } catch(_) { data = {raw}; } }
    if (r.status === 401) { clearUI(); setAuth(false); throw new Error(data.error||"Sessão expirada."); }
    if (!r.ok) throw new Error(data.error||data.raw||`Pedido falhou (${r.status})`);
    return data;
}

/* ── auth state ────────────────────────────────────────────────────────── */
function setAuth(ok, user) {
    $("#admin-header")?.classList.toggle("is-hidden", !ok);
    loginView.classList.toggle("is-hidden", ok);
    adminView.classList.toggle("is-hidden", !ok);
    sessionBadge.textContent = ok ? `Ligado: ${user}` : "Não autenticado";
    if (ok) { $("#admin-panel-title")?.focus(); } else { loginForm.querySelector("input[name='username']")?.focus(); }
}

function clearUI() {
    state.payload = null;
    managedForms.forEach(id => { const f=document.getElementById(id); if(f){f.reset(); const h=f.querySelector("[name='record_id']"); if(h) h.value="";} });
    managedTargets.forEach(id => { const el=document.getElementById(id); if(el) el.innerHTML=""; });
    $$("#admin-view details").forEach(d => d.open=false);
    if(evTeam) evTeam.innerHTML='<option value="">Selecionar equipa</option>';
    if(evPlayer) evPlayer.innerHTML='<option value="">Selecionar jogador</option>';
}

/* ── entity helpers ────────────────────────────────────────────────────── */
function entities() { return state.payload?.entities || {teams:[],players:[],matches:[],match_events:[],bar_products:[],announcements:[],info_sections:[]}; }
function byId(col, id) { return (entities()[col]||[]).find(x => Number(x.id)===Number(id)); }
function popSelect(selId, items, fmt, blank="Selecionar") {
    const sel=document.getElementById(selId); if(!sel) return;
    sel.innerHTML = `<option value="">${blank}</option>` + items.map(i => `<option value="${i.id}">${esc(fmt(i))}</option>`).join("");
}

function populateBarCategories(selectedValue="") {
    if(!barCategorySelect) return;
    const liveCategories = [...new Set((entities().bar_products||[])
        .map(i => String(i.category||"").trim())
        .filter(Boolean))];
    const extraCategories = liveCategories
        .filter(category => !barCategoryDefaults.includes(category))
        .sort((a,b) => a.localeCompare(b, "pt-PT"));
    const categories = [...barCategoryDefaults, ...extraCategories];
    barCategorySelect.innerHTML = `<option value="">Selecionar</option>` + categories
        .map(category => `<option value="${esc(category)}">${esc(category)}</option>`)
        .join("");
    if(selectedValue) barCategorySelect.value = String(selectedValue);
}

function syncMatchForfeitState() {
    if(!matchForfeit || !matchStatus) return;
    if(matchForfeit.value) matchStatus.value = "completed";
}

function fillForm(formId, rec) {
    const f=document.getElementById(formId); if(!f||!rec) return;
    if(formId==="event-form") syncEvTeams(rec.match_id, rec.team_id, rec.player_id);
    for(const el of f.elements) {
        if(!el.name) continue;
        if(el.name==="record_id") { el.value=rec.id??""; continue; }
        el.value=rec[el.name]??"";
    }
    if(formId==="event-form") syncEvPlayers(f.querySelector("[name='team_id']")?.value, rec.player_id);
    if(formId==="match-form") syncMatchForfeitState();
}
function resetForm(formId) {
    const f=document.getElementById(formId); if(!f) return;
    f.reset(); const h=f.querySelector("[name='record_id']"); if(h) h.value="";
    if(formId==="event-form") syncEvTeams("","","");
    if(formId==="match-form") syncMatchForfeitState();
}

/* ── render ────────────────────────────────────────────────────────────── */
function renderSummary() {
    const e=entities();
    document.getElementById("admin-summary").innerHTML=[["Equipas",e.teams.length],["Jogadores",e.players.length],["Jogos",e.matches.length],["Avisos",e.announcements.length]].map(([l,v])=>`<article class="summary-card"><span>${esc(l)}</span><strong>${esc(v)}</strong></article>`).join("");
}

function renderList(targetId, items, fmt, empty) {
    const t=document.getElementById(targetId); if(!t) return;
    t.innerHTML = items.length ? items.map(fmt).join("") : `<div class="record-card"><p>${esc(empty)}</p></div>`;
}

function renderPlayersByTeam(players) {
    const target = document.getElementById("players-list");
    if (!target) return;
    if (!players.length) {
        target.innerHTML = '<div class="record-card"><p>Sem jogadores registados.</p></div>';
        return;
    }

    const grouped = [];
    const seen = new Map();
    players.forEach(player => {
        const groupName = player.team_name || "Sem equipa";
        if (!seen.has(groupName)) {
            seen.set(groupName, { name: groupName, players: [] });
            grouped.push(seen.get(groupName));
        }
        seen.get(groupName).players.push(player);
    });

    target.innerHTML = grouped.map(group => `
        <section class="player-team-group">
            <div class="player-team-group__header">
                <strong>${esc(group.name)}</strong>
                <span>${group.players.length} jogador(es)</span>
            </div>
            <div class="player-team-group__list">${group.players.map(p => `
                <article class="record-card">
                    <div class="key-line"><strong>${esc(p.name)}</strong><span>${p.shirt_number ? `#${esc(p.shirt_number)}` : "Sem número"}</span></div>
                    <p>${esc(p.position || "Sem posição definida")}</p>
                    <div class="record-actions"><button type="button" data-edit="player-form" data-col="players" data-id="${p.id}">Editar</button><button type="button" class="danger" data-del="players" data-id="${p.id}">Remover</button></div>
                </article>`).join("")}
            </div>
        </section>`).join("");
}

function renderLists() {
    const e=entities();

    renderList("teams-list", e.teams, t => `<article class="record-card"><div class="key-line"><strong>${esc(t.name)}</strong><span>Grupo ${esc(normGroup(t.group_name))}</span></div><div class="record-actions"><button type="button" data-edit="team-form" data-col="teams" data-id="${t.id}">Editar</button><button type="button" class="danger" data-del="teams" data-id="${t.id}">Remover</button></div></article>`, "Sem equipas registadas.");

    renderPlayersByTeam(e.players);

    renderList("matches-list", e.matches, m => {
        return `<article class="record-card"><div class="key-line"><strong>${esc(m.game_label||`Jogo ${m.game_number}`)}</strong><span>${esc(m.phase_title)} &middot; ${esc(statusLabel(m.status))}</span></div><p>${esc(m.home_team?.name||"A definir")} vs ${esc(m.away_team?.name||"A definir")}</p>${m.forfeit_note?`<p>${esc(m.forfeit_note)}</p>`:""}<p>${esc(fmtDT(m.scheduled_at))}</p><div class="record-actions"><button type="button" data-edit="match-form" data-col="matches" data-id="${m.id}">Editar</button><button type="button" class="danger" data-del="matches" data-id="${m.id}">Remover</button></div></article>`;
    }, "Sem jogos registados.");

    renderList("events-list", e.match_events, ev => {
        const m=byId("matches",ev.match_id), p=byId("players",ev.player_id), t=byId("teams",ev.team_id);
        return `<article class="record-card"><div class="key-line"><strong>${esc(evLabel(ev.event_type))}</strong><span>${esc(ev.minute??"-")}'</span></div><p>${esc(m?.game_label||"Jogo removido")}</p><p>${esc(p?.name||t?.name||"Sem jogador")}</p><div class="record-actions"><button type="button" data-edit="event-form" data-col="match_events" data-id="${ev.id}">Editar</button><button type="button" class="danger" data-del="match-events" data-id="${ev.id}">Remover</button></div></article>`;
    }, "Sem eventos registados.");

    renderList("bar-list", e.bar_products, i => `<article class="record-card"><div class="key-line"><strong>${esc(i.name)}</strong><span>${Number(i.price||0).toFixed(2)} €</span></div><p>${esc(i.category||"Sem tipo")}${i.availability==="unavailable"?" &middot; <em>Indisponível</em>":""}</p><div class="record-actions"><button type="button" data-edit="bar-form" data-col="bar_products" data-id="${i.id}">Editar</button><button type="button" class="danger" data-del="bar-products" data-id="${i.id}">Remover</button></div></article>`, "Sem produtos registados.");

    renderList("announcements-list", e.announcements, i => `<article class="record-card"><div class="key-line"><strong>${esc(i.title)}</strong><span>${esc(fmtDT(i.published_at))}</span></div><p>${esc(i.is_urgent?"Urgente":"Normal")}</p><p>${esc(i.message)}</p><div class="record-actions"><button type="button" data-edit="announcement-form" data-col="announcements" data-id="${i.id}">Editar</button><button type="button" class="danger" data-del="announcements" data-id="${i.id}">Remover</button></div></article>`, "Sem avisos registados.");

    renderList("info-list", e.info_sections, i => `<article class="record-card"><div class="key-line"><strong>${esc(i.title)}</strong><span>${esc(i.category||"Geral")}</span></div><p>${esc(i.content)}</p><div class="record-actions"><button type="button" data-edit="info-form" data-col="info_sections" data-id="${i.id}">Editar</button><button type="button" class="danger" data-del="info-sections" data-id="${i.id}">Remover</button></div></article>`, "Sem informações registadas.");
}

/* ── cascading selects ────────────────────────────────────────────────── */
function sortedMatches() { return [...(entities().matches||[])].sort((a,b)=>(Number(a.game_number||9999)-Number(b.game_number||9999))||String(a.scheduled_at||"").localeCompare(String(b.scheduled_at||""))); }

function populateSelects() {
    const e=entities();
    popSelect("player-team", e.teams, i=>i.name, "Selecionar equipa");
    popSelect("match-home", e.teams, i=>i.name, "Selecionar equipa");
    popSelect("match-away", e.teams, i=>i.name, "Selecionar equipa");
    popSelect("event-match", sortedMatches(), i=>`${i.game_label||`Jogo ${i.game_number}`} — ${i.home_team?.name||"A definir"} vs ${i.away_team?.name||"A definir"}`, "Selecionar jogo");
    populateBarCategories(barCategorySelect?.value || "");
    syncEvTeams(evMatch.value, evTeam.value, evPlayer.value);
}

function syncEvTeams(matchId, selTeam, selPlayer) {
    const m=byId("matches",matchId);
    const teams=m?[m.home_team,m.away_team].filter(Boolean):[];
    evTeam.innerHTML='<option value="">Selecionar equipa</option>'+teams.map(t=>`<option value="${t.id}">${esc(t.name)}</option>`).join("");
    evTeam.value=selTeam?String(selTeam):"";
    syncEvPlayers(evTeam.value, selPlayer);
}
function syncEvPlayers(teamId, selPlayer) {
    if(evType?.value === "foul") {
        evPlayer.innerHTML = '<option value="">Sem jogador</option>';
        evPlayer.value = "";
        evPlayer.disabled = true;
        evPlayer.required = false;
        return;
    }
    const players=(entities().players||[]).filter(p=>Number(p.team_id)===Number(teamId));
    evPlayer.innerHTML='<option value="">Selecionar jogador</option>'+players.map(p=>`<option value="${p.id}">${esc(p.name)}</option>`).join("");
    evPlayer.value=selPlayer?String(selPlayer):"";
    evPlayer.disabled = false;
    evPlayer.required = true;
}

/* ── CRUD ──────────────────────────────────────────────────────────────── */
function renderAll() { renderSummary(); populateSelects(); renderLists(); }

async function refreshAdmin() {
    state.payload = await api("/api/admin/bootstrap", {method:"GET"});
    setAuth(true, state.payload.user.username);
    renderAll();
    attachDynamic();
}

function formToPayload(form) {
    const p=Object.fromEntries(new FormData(form).entries());
    if("record_id" in p) { p.id=p.record_id; delete p.record_id; }
    if(p.id==="") delete p.id;
    if(form.id==="event-form" && p.event_type === "foul") delete p.player_id;
    return p;
}

function validate(formId, p) {
    if(formId==="match-form"&&p.home_team_id&&p.away_team_id&&p.home_team_id===p.away_team_id) throw new Error("Seleciona duas equipas diferentes.");
    if(formId==="event-form"&&(!p.match_id||!p.team_id||(p.event_type !== "foul" && !p.player_id))) throw new Error("Seleciona jogo e equipa; para golos e cartões também jogador.");
}

async function saveForm(e) {
    const form=e.currentTarget||e.target.closest("form");
    if(!form) { showToast("Formulário não encontrado.",true); return; }
    console.log(`[saveForm] form="${form.id}"`, formToPayload(form));
    const p=formToPayload(form);
    for(const f of form.querySelectorAll("[required]")) { if(!f.value||!f.value.trim()) { console.warn(`[saveForm] campo obrigatório vazio: ${f.name}`); f.focus(); showToast(`O campo "${f.closest("label")?.querySelector("span")?.textContent||f.name}" é obrigatório.`,true); return; } }
    validate(form.id, p);
    const id=p.id; delete p.id;
    const map={"team-form":"teams","player-form":"players","match-form":"matches","event-form":"match-events","bar-form":"bar-products","announcement-form":"announcements","info-form":"info-sections"};
    const res=map[form.id]; if(!res) { showToast("Recurso desconhecido.",true); return; }
    const btn=form.querySelector("[type='submit']");
    if(btn) { btn.disabled=true; btn.textContent="A guardar..."; }
    console.log(`[saveForm] a enviar ${id?"PUT":"POST"} /api/admin/${res}${id?"/"+id:""}`);
    try {
        await api(id?`/api/admin/${res}/${id}`:`/api/admin/${res}`, {method:id?"PUT":"POST", body:JSON.stringify(p)});
        console.log("[saveForm] sucesso");
        resetForm(form.id);
        await refreshAdmin();
        showToast("Alterações guardadas.");
    } finally { if(btn) { btn.disabled=false; btn.textContent=btn.dataset.origText||"Guardar"; } }
}

async function handleDelete(res, id) {
    if(!confirm("Remover este registo?")) return;
    await api(`/api/admin/${res}/${id}`, {method:"DELETE"});
    await refreshAdmin();
    showToast("Registo removido.");
}

function attachDynamic() {
    $$("[data-edit]").forEach(b => { b.onclick=()=>{ const rec=byId(b.dataset.col,b.dataset.id); if(!rec) return; fillForm(b.dataset.edit,rec); const d=document.getElementById(b.dataset.edit)?.closest("details"); if(d) d.open=true; document.getElementById(b.dataset.edit)?.scrollIntoView({behavior:"smooth",block:"center"}); document.getElementById(b.dataset.edit)?.querySelector("input,select,textarea")?.focus(); }; });
    $$("[data-del]").forEach(b => { b.onclick=()=>handleDelete(b.dataset.del,b.dataset.id).catch(e=>showToast(e.message,true)); });
}

function activateShortcut(id) {
    const t=document.getElementById(id); if(!t) return;
    if(t.tagName.toLowerCase()==="details") { t.open=true; t.scrollIntoView({behavior:"smooth",block:"start"}); t.querySelector("input,select,textarea,summary")?.focus(); return; }
    t.scrollIntoView({behavior:"smooth",block:"start"});
}

/* ── boot ──────────────────────────────────────────────────────────────── */
async function boot() {
    try {
        const s=await api("/api/auth/session",{method:"GET"});
        if(s.authenticated) {
            await refreshAdmin();
            if(window.location.pathname==="/staff-login" && history.replaceState) history.replaceState(null,"","/admin");
        }
        else { clearUI(); setAuth(false); }
    } catch(_) { clearUI(); setAuth(false); }
}

loginForm.addEventListener("submit", async e => {
    e.preventDefault();
    const btn=loginForm.querySelector("[type='submit']");
    if(btn){btn.disabled=true;btn.textContent="A entrar...";}
    try {
        await api("/api/auth/login",{method:"POST",body:JSON.stringify(Object.fromEntries(new FormData(loginForm).entries()))});
        await refreshAdmin();
        if(history.replaceState) history.replaceState(null,"","/admin");
    }
    catch(err) { showToast(err.message,true); }
    finally { if(btn){btn.disabled=false;btn.textContent="Entrar na área staff";} }
});

logoutBtn.addEventListener("click", async () => {
    let ok=false;
    try { await api("/api/auth/logout",{method:"POST"}); ok=true; } catch(e) { showToast(e.message,true); }
    finally {
        clearUI();
        setAuth(false);
        if(ok) window.location.replace("/staff-login");
    }
});

evMatch.addEventListener("change", () => syncEvTeams(evMatch.value,"",""));
evTeam.addEventListener("change", () => syncEvPlayers(evTeam.value,""));
evType?.addEventListener("change", () => syncEvPlayers(evTeam.value, ""));
evPlayer.addEventListener("change", () => { const p=byId("players",evPlayer.value); if(p) evTeam.value=String(p.team_id); });
matchForfeit?.addEventListener("change", syncMatchForfeitState);

themeBtn?.addEventListener("click", toggleTheme);

$$(".admin-shortcuts a[href^='#']").forEach(a => { a.addEventListener("click", e => { e.preventDefault(); const id=a.getAttribute("href")?.slice(1); if(id) activateShortcut(id); }); });
$$("[data-reset-form]").forEach(b => { b.addEventListener("click", () => { resetForm(b.dataset.resetForm); showToast("Formulário limpo."); }); });

managedForms.forEach(id => {
    const f=document.getElementById(id);
    if(!f) { console.warn(`[admin] form #${id} não encontrado`); return; }
    const btn=f.querySelector("[type='submit']");
    if(btn) btn.dataset.origText=btn.textContent;
    f.addEventListener("submit", e => {
        e.preventDefault();
        console.log(`[admin] submit disparado: ${id}`);
        saveForm(e).catch(err => { console.error(`[saveForm ${id}]`,err); showToast(err.message,true); });
    });
    console.log(`[admin] listener registado: ${id}`);
});

console.log("[admin] admin.js v4 carregado");
applyTheme(localStorage.getItem(THEME_KEY)||preferredTheme());
boot();
