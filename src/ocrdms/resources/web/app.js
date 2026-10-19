/* OCRDMS Weboberfläche – ohne Build-Schritt, ohne externe Bibliotheken. */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const ICONS = {
  home: '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
  camera: '<path d="M4 8a2 2 0 0 1 2-2h1.5l1.4-2h6.2l1.4 2H18a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/><circle cx="12" cy="13" r="3.5"/>',
  upload: '<path d="M12 16V4m0 0-4.5 4.5M12 4l4.5 4.5"/><path d="M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4"/>',
  log: '<path d="M5 4h14v16H5z"/><path d="M8 8h8M8 12h8M8 16h5"/>',
  tag: '<path d="M3 12V4a1 1 0 0 1 1-1h8l9 9-9 9z"/><circle cx="7.5" cy="7.5" r="1.5"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  play: '<path d="M7 4v16l13-8z"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="1"/>',
  rotl: '<path d="M4 4v6h6"/><path d="M4.5 10A8 8 0 1 1 6 16.5"/>',
  rotr: '<path d="M20 4v6h-6"/><path d="M19.5 10A8 8 0 1 0 18 16.5"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  left: '<path d="M15 5l-7 7 7 7"/>',
  right: '<path d="M9 5l7 7-7 7"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/>',
  check: '<path d="M5 12.5 10 17l9-10"/>',
  folder: '<path d="M3 6a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/>',
  logout: '<path d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6"/>',
};
const icon = (name) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;

const ROUTES = [
  { path: "", label: "Übersicht", icon: "home", view: viewOverview },
  { path: "scan", label: "Scannen", icon: "camera", view: viewScan },
  { path: "upload", label: "Hochladen", icon: "upload", view: viewUpload },
  { path: "log", label: "Protokoll", icon: "log", view: viewLog, desktop: true },
  { path: "tags", label: "Tags", icon: "tag", view: viewTags },
  { path: "settings", label: "Einstellungen", icon: "settings", view: viewSettings },
];

const state = { status: null, docs: [], version: "", wasBusy: false, scanPages: [], logLast: 0, cleanup: null };

// Laufende Scan-Sitzung im Browser merken: Handys beenden die Seite gern, während die Kamera offen ist.
Object.defineProperty(state, "scanId", {
  get() { try { return localStorage.getItem("ocrdms_scan"); } catch { return this._scanId || null; } },
  set(v) {
    this._scanId = v;
    try { v ? localStorage.setItem("ocrdms_scan", v) : localStorage.removeItem("ocrdms_scan"); } catch {}
  },
});

// ------------------------------------------------------------------ Hilfsfunktionen
class ApiError extends Error {}

async function api(method, url, body, isForm = false) {
  const opts = { method, headers: {}, credentials: "same-origin" };
  if (body !== undefined) {
    if (isForm) opts.body = body;
    else { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  }
  const r = await fetch(url, opts);
  if (r.status === 401 && !url.startsWith("/api/auth")) { renderAuth(); throw new ApiError("Nicht angemeldet"); }
  const data = r.headers.get("content-type")?.includes("json") ? await r.json() : null;
  if (!r.ok) throw new ApiError(data?.detail || `Fehler ${r.status}`);
  return data;
}

let toastTimer;
function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "show" + (err ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = ""), err ? 6000 : 3000);
}

function fmtCountdown(sec) {
  if (sec == null) return "";
  const m = Math.floor(sec / 60), s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function fmtDate(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-");
  return `${d}.${m}.${y}`;
}

function currentRoute() {
  const p = location.hash.replace(/^#\/?/, "");
  return ROUTES.find((r) => r.path === p) || ROUTES[0];
}

// ------------------------------------------------------------------ Login / Einrichtung
async function boot() {
  try {
    const a = await api("GET", "/api/auth");
    state.version = a.version;
    if (a.setup_required || !a.logged_in) return renderAuth(a.setup_required);
    renderShell();
  } catch (e) {
    $("#app").innerHTML = `<div class="login-wrap"><div class="card login"><div class="alert err">Server nicht erreichbar: ${esc(e.message)}</div></div></div>`;
  }
}

async function renderAuth(setup) {
  if (setup === undefined) {
    try { setup = (await api("GET", "/api/auth")).setup_required; } catch { setup = false; }
  }
  stopPolling();
  $("#app").innerHTML = `
    <div class="login-wrap"><form class="card login" id="auth-form">
      <div class="brand"><img src="/static/icon.svg" alt="">OCRDMS</div>
      ${setup ? `<div class="alert info">Willkommen! Bitte lege ein Passwort für den Zugang fest (mindestens 8 Zeichen).</div>` : ""}
      <label class="field"><span>Passwort</span><input type="password" id="pw1" autocomplete="${setup ? "new-password" : "current-password"}" required autofocus></label>
      ${setup ? `<label class="field"><span>Passwort wiederholen</span><input type="password" id="pw2" autocomplete="new-password" required></label>` : ""}
      <div id="auth-err" class="alert err hidden"></div>
      <button class="btn primary" style="width:100%">${setup ? "Passwort festlegen" : "Anmelden"}</button>
    </form></div>`;
  $("#auth-form").onsubmit = async (ev) => {
    ev.preventDefault();
    const pw = $("#pw1").value, err = $("#auth-err");
    err.classList.add("hidden");
    if (setup && pw !== $("#pw2").value) { err.textContent = "Die Passwörter stimmen nicht überein."; err.classList.remove("hidden"); return; }
    const btn = $("button", ev.target);
    btn.disabled = true;
    try {
      await api("POST", setup ? "/api/auth/setup" : "/api/auth/login", { password: pw });
      renderShell();
    } catch (e) {
      err.textContent = e.message; err.classList.remove("hidden");
    } finally { btn.disabled = false; }
  };
}

// ------------------------------------------------------------------ Rahmen & Navigation
function renderShell() {
  $("#app").innerHTML = `
    <header class="topbar">
      <a class="brand" href="#/"><img src="/static/icon.svg" alt="">OCRDMS</a>
      <nav class="nav">${ROUTES.map((r) => `<a href="#/${r.path}" data-path="${r.path}" class="${r.desktop ? "hide-mobile" : ""}">${icon(r.icon)}<span>${r.label}</span>${r.path === "" ? '<span class="badge hidden" id="nav-review"></span>' : ""}</a>`).join("")}</nav>
      <div class="spacer"></div>
      <span id="hdr-state"></span>
    </header>
    <main id="view"></main>`;
  window.onhashchange = route;
  route();
  startPolling();
}

function route() {
  if (state.cleanup) { state.cleanup(); state.cleanup = null; }
  const r = currentRoute();
  $$(".nav a").forEach((a) => a.classList.toggle("active", a.dataset.path === r.path));
  const view = $("#view");
  view.innerHTML = "";
  r.view(view);
  window.scrollTo(0, 0);
}

// ------------------------------------------------------------------ Statusabfrage
let pollTimer = null;
function startPolling() { stopPolling(); poll(); pollTimer = setInterval(poll, 2000); }
function stopPolling() { clearInterval(pollTimer); pollTimer = null; }

async function poll() {
  if (document.hidden) return;
  let s;
  try { s = await api("GET", "/api/status"); } catch { return; }
  state.status = s;
  const hdr = $("#hdr-state");
  if (hdr) hdr.innerHTML = statePill(s);
  const nb = $("#nav-review");
  if (nb) { nb.textContent = s.review; nb.classList.toggle("hidden", !s.review); }
  if (state.wasBusy && !s.busy) refreshDocs();
  state.wasBusy = s.busy;
  updateOverviewStatus();
}

function statePill(s) {
  if (s.busy) return `<span class="pill busy">Verarbeitung läuft</span>`;
  if (s.last_error) return `<span class="pill err">Fehler</span>`;
  if (!s.auto_run) return `<span class="pill paused">Automatik pausiert</span>`;
  return `<span class="pill ok">Bereit</span>`;
}

// ------------------------------------------------------------------ Update
async function startUpdate(version) {
  if (!confirm(`OCRDMS auf Version ${version} aktualisieren?

OCRDMS wird dabei kurz beendet und startet danach automatisch neu.`)) return;
  try { await api("POST", "/api/update/install"); }
  catch (e) { return toast(e.message, true); }
  stopPolling();
  $("#app").innerHTML = `<div class="login-wrap"><div class="card login" style="text-align:center">
    <div class="brand"><img src="/static/icon.svg" alt="">OCRDMS</div>
    <div class="spinner" style="margin:0 auto 1rem"></div>
    <h2 id="upd-title">Update wird geladen …</h2>
    <p class="muted small" id="upd-text">Bitte dieses Fenster geöffnet lassen. Die Seite lädt nach dem Update automatisch neu.</p>
  </div></div>`;
  const old = state.version, started = Date.now();
  const tick = async () => {
    try {
      const h = await fetch("/api/health", { cache: "no-store" }).then((r) => r.json());
      if (h.version && h.version !== old) return location.reload();
      const u = await fetch("/api/update", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
      if (u?.state === "downloading") $("#upd-title").textContent = `Update wird geladen … ${u.progress}%`;
      else if (u?.state === "installing") $("#upd-title").textContent = "Update wird installiert …";
      else if (u?.state === "error") { $("#upd-title").textContent = "Update fehlgeschlagen"; $("#upd-text").textContent = u.error; return; }
    } catch { $("#upd-title").textContent = "Update wird installiert …"; }  // Server gerade beendet
    if (Date.now() - started > 15 * 60 * 1000) { $("#upd-text").textContent = "Das dauert ungewöhnlich lange. Bitte Seite manuell neu laden."; return; }
    setTimeout(tick, 2000);
  };
  setTimeout(tick, 1500);
}

// ------------------------------------------------------------------ Übersicht
function viewOverview(el) {
  el.innerHTML = `
    <div id="update-box"></div>
    <div id="err-box"></div>
    <div class="card">
      <div class="card-head">
        <h2>Verarbeitung</h2><span id="ov-pill"></span><div class="spacer"></div>
        <div class="btn-row">
          <button class="btn primary" id="btn-run">${icon("play")}Jetzt verarbeiten</button>
          <button class="btn hidden" id="btn-cancel">${icon("stop")}Abbrechen</button>
          <button class="btn" id="btn-auto"></button>
        </div>
      </div>
      <div id="ov-progress" class="hidden" style="margin-bottom:1rem">
        <div class="small" id="ov-progress-text" style="margin-bottom:.35rem"></div>
        <div class="progress"><div id="ov-progress-bar" style="width:0"></div></div>
      </div>
      <div class="grid grid-3">
        <div class="stat"><span class="value" id="ov-pending">–</span><span class="label">Dateien im Eingang</span></div>
        <div class="stat"><span class="value" id="ov-review">–</span><span class="label">zur Prüfung (Ordner „_Pruefen“)</span></div>
        <div class="stat"><span class="value" id="ov-next">–</span><span class="label">bis zur nächsten Prüfung</span></div>
      </div>
    </div>
    <div class="card">
      <div class="card-head"><h2>Abgelegte Dokumente</h2><div class="spacer"></div>
        <input type="search" id="doc-filter" placeholder="Suchen …" style="max-width:260px">
      </div>
      <div class="doc-list" id="doc-list"><div class="empty"><div class="spinner"></div></div></div>
    </div>`;
  $("#btn-run").onclick = async () => { await api("POST", "/api/run"); toast("Verarbeitung gestartet"); poll(); };
  $("#btn-cancel").onclick = async () => { await api("POST", "/api/cancel"); toast("Wird nach der aktuellen Seite abgebrochen …"); };
  $("#btn-auto").onclick = async () => { await api("POST", "/api/auto", { on: !state.status?.auto_run }); poll(); };
  $("#doc-filter").oninput = renderDocs;
  updateOverviewStatus();
  refreshDocs();
}

function updateOverviewStatus() {
  const s = state.status;
  if (!s || !$("#ov-pill")) return;
  $("#ov-pill").innerHTML = statePill(s);
  $("#btn-run").disabled = s.busy;
  $("#btn-cancel").classList.toggle("hidden", !s.busy);
  $("#btn-auto").innerHTML = s.auto_run ? `${icon("stop")}Automatik pausieren` : `${icon("play")}Automatik einschalten`;
  $("#ov-pending").textContent = s.pending;
  $("#ov-review").textContent = s.review;
  $("#ov-next").textContent = s.busy ? "läuft" : s.auto_run ? fmtCountdown(s.next_run_in) : "aus";
  const p = s.progress, box = $("#ov-progress");
  box.classList.toggle("hidden", !s.busy);
  if (p) {
    $("#ov-progress-text").textContent = p.file ? `${p.file} – ${p.stage} ${p.current}/${p.total}` : p.stage + " …";
    const bar = $("#ov-progress-bar");
    bar.parentElement.classList.toggle("indeterminate", !p.total);
    bar.style.width = p.total ? `${Math.round((p.current / p.total) * 100)}%` : "30%";
  }
  $("#err-box").innerHTML = s.last_error && !s.busy ? `<div class="alert err">${esc(s.last_error)}</div>` : "";
  const u = s.update, ub = $("#update-box");
  if (u?.available && u.state === "idle") {
    if (!$("#btn-update-ov")) {
      ub.innerHTML = `<div class="alert info" style="display:flex;gap:1rem;align-items:center;flex-wrap:wrap">
        <span style="flex:1">Neue Version <b>${esc(u.latest)}</b> verfügbar (installiert: ${esc(state.version)}).</span>
        <a class="btn small" href="#/settings">Details</a>
        <button class="btn small primary" id="btn-update-ov">Jetzt aktualisieren</button></div>`;
      $("#btn-update-ov").onclick = () => startUpdate(u.latest);
    }
  } else ub.innerHTML = "";
}

async function refreshDocs() {
  try { state.docs = await api("GET", "/api/documents"); } catch { return; }
  renderDocs();
}

function renderDocs() {
  const list = $("#doc-list");
  if (!list) return;
  const q = ($("#doc-filter")?.value || "").toLowerCase().trim();
  const docs = state.docs.filter((d) => !q || JSON.stringify(d.metadaten).toLowerCase().includes(q) || d.datei.toLowerCase().includes(q));
  if (!docs.length) {
    list.innerHTML = `<div class="empty">${q ? "Keine Treffer." : "Noch keine Dokumente verarbeitet.<br>Lege PDFs in den Eingangsordner, lade sie hoch oder scanne mit dem Handy."}</div>`;
    return;
  }
  const scopes = ["Privat", "Geschäftlich"];
  list.innerHTML = docs.map((d) => {
    const m = d.metadaten, url = `/api/files/pdf?path=${encodeURIComponent(d.pfad)}`;
    return `<a class="doc" href="${url}" target="_blank" rel="noopener">
      <img loading="lazy" src="/api/files/thumb?width=112&path=${encodeURIComponent(d.pfad)}" alt="">
      <div style="min-width:0">
        <div class="title">${esc(m.titel)}</div>
        <div class="meta">${esc(m.dokumenttyp)}${m.korrespondent ? " · " + esc(m.korrespondent) : ""}${m.datum ? " · " + fmtDate(m.datum) : ""}</div>
        <div>${m.tags.map((t) => `<span class="chip ${scopes.includes(t) ? "scope" : ""}">${esc(t)}</span>`).join("")}</div>
      </div>
      <div class="right">${d.pruefen ? '<div class="flag">Trennung prüfen</div>' : ""}
        <div>${d.seiten_im_original.length} S.</div>
        <div class="hide-mobile">${esc((d.verarbeitet_am || "").replace("T", " ").slice(0, 16))}</div></div>
    </a>`;
  }).join("");
}

// ------------------------------------------------------------------ Handy-Scan
const MODE_LABELS = { auto: "Automatisch", sw: "Schwarz/Weiß", grau: "Graustufen", farbe: "Farbe" };

function viewScan(el) {
  el.innerHTML = `
    <div class="card">
      <h1>Dokument scannen</h1>
      <p class="muted small" style="margin-top:0">Fotografiere jede Seite einzeln – möglichst von oben, auf dunklem Untergrund. Ränder werden automatisch erkannt und das Bild begradigt.</p>
      <div class="capture-row">
        <button class="btn primary big" id="btn-cam">${icon("camera")}<span id="cam-label">Seite fotografieren</span></button>
        <button class="btn big" id="btn-gal">${icon("image")}Aus Galerie</button>
      </div>
      <input type="file" id="in-cam" accept="image/*" capture="environment" class="hidden">
      <input type="file" id="in-gal" accept="image/*" multiple class="hidden">
      <div class="scan-pages" id="scan-pages"></div>
      <div id="scan-finish" class="hidden">
        <label class="field"><span>Bildmodus für neue Seiten</span>
          <select id="scan-mode">${Object.entries(MODE_LABELS).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></label>
        <label class="check"><input type="checkbox" id="scan-single" checked><span><b>Ist ein einzelnes Dokument</b><br><span class="muted small">Nicht trennen – alle Seiten gehören zusammen. Abwählen, wenn du mehrere Dokumente hintereinander fotografiert hast.</span></span></label>
        <label class="field"><span>Name (optional)</span><input type="text" id="scan-name" placeholder="wird sonst automatisch vergeben"></label>
        <div class="btn-row">
          <button class="btn primary big" id="btn-finish" style="flex:1">${icon("check")}Fertig – an OCRDMS senden</button>
          <button class="btn danger" id="btn-discard">${icon("trash")}Verwerfen</button>
        </div>
      </div>
    </div>`;
  const pick = (inp) => { inp.value = ""; inp.click(); };
  $("#btn-cam").onclick = () => pick($("#in-cam"));
  $("#btn-gal").onclick = () => pick($("#in-gal"));
  $("#in-cam").onchange = (e) => addPhotos(e.target.files);
  $("#in-gal").onchange = (e) => addPhotos(e.target.files);
  $("#btn-finish").onclick = finishScan;
  $("#btn-discard").onclick = async () => {
    if (!confirm("Alle fotografierten Seiten verwerfen?")) return;
    if (state.scanId) await api("DELETE", `/api/scan/${state.scanId}`).catch(() => {});
    state.scanId = null; state.scanPages = [];
    renderScanPages();
  };
  if (state.scanId) {
    api("GET", `/api/scan/${state.scanId}`).then((s) => { state.scanPages = s.pages; renderScanPages(); })
      .catch(() => { state.scanId = null; state.scanPages = []; renderScanPages(); });
  } else renderScanPages();
}

async function shrinkPhoto(file, maxSide = 3200) {
  // Große Handyfotos vor dem Hochladen verkleinern – spart Zeit im WLAN. Fällt bei Problemen auf das Original zurück.
  try {
    const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
    const f = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
    if (f === 1 && file.size < 4e6) return file;
    const c = document.createElement("canvas");
    c.width = Math.round(bmp.width * f); c.height = Math.round(bmp.height * f);
    c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
    const blob = await new Promise((res) => c.toBlob(res, "image/jpeg", 0.9));
    return blob || file;
  } catch { return file; }
}

async function addPhotos(files) {
  if (!files?.length) return;
  try {
    if (!state.scanId) state.scanId = (await api("POST", "/api/scan")).id;
  } catch (e) { return toast(e.message, true); }
  const mode = $("#scan-mode")?.value || "auto";
  for (const file of files) {
    const tmpId = "tmp" + Math.random();
    state.scanPages.push({ id: tmpId, busy: true, thumb: URL.createObjectURL(file) });
    renderScanPages();
    try {
      const fd = new FormData();
      fd.append("file", await shrinkPhoto(file), "foto.jpg");
      fd.append("mode", mode);
      const page = await api("POST", `/api/scan/${state.scanId}/photo`, fd, true);
      const i = state.scanPages.findIndex((p) => p.id === tmpId);
      state.scanPages[i] = page;
      if (!page.detected) toast("Blattränder nicht sicher erkannt – Bild wurde unverändert übernommen.");
    } catch (e) {
      state.scanPages = state.scanPages.filter((p) => p.id !== tmpId);
      toast(e.message, true);
    }
    renderScanPages();
  }
}

function renderScanPages() {
  const grid = $("#scan-pages");
  if (!grid) return;
  const pages = state.scanPages;
  $("#scan-finish").classList.toggle("hidden", !pages.length);
  $("#cam-label").textContent = pages.length ? "Weitere Seite fotografieren" : "Seite fotografieren";
  grid.innerHTML = pages.map((p, i) => `
    <div class="scan-page ${p.busy ? "busy" : ""}" data-id="${esc(p.id)}">
      <div class="img-wrap"><img src="${esc(p.thumb)}" alt="Seite ${i + 1}">
        <span class="num">${i + 1}</span>
        ${p.busy ? '<span class="nodetect" style="background:var(--primary)">wird aufbereitet …</span>' : !p.detected ? '<span class="nodetect">Ränder nicht erkannt</span>' : ""}
      </div>
      ${p.busy ? "" : `
      <select data-act="mode" class="small" style="min-height:32px;padding:.2rem .4rem">
        ${Object.entries(MODE_LABELS).map(([k, v]) => `<option value="${k}" ${p.mode === k ? "selected" : ""}>${v}</option>`).join("")}
        <option value="original">Originalfoto</option>
      </select>
      <div class="tools">
        <button class="btn ghost icon" data-act="left" title="nach vorne" ${i === 0 ? "disabled" : ""}>${icon("left")}</button>
        <button class="btn ghost icon" data-act="rotl" title="links drehen">${icon("rotl")}</button>
        <button class="btn ghost icon" data-act="rotr" title="rechts drehen">${icon("rotr")}</button>
        <button class="btn ghost icon danger" data-act="del" title="löschen">${icon("trash")}</button>
        <button class="btn ghost icon" data-act="right" title="nach hinten" ${i === pages.length - 1 ? "disabled" : ""}>${icon("right")}</button>
      </div>`}
    </div>`).join("");
  $$(".scan-page", grid).forEach((card) => {
    const id = card.dataset.id;
    $$("[data-act]", card).forEach((b) => {
      const ev = b.tagName === "SELECT" ? "onchange" : "onclick";
      b[ev] = () => scanAction(id, b.dataset.act, b.value);
    });
    $("img", card).onclick = () => { const p = pages.find((x) => x.id === id); if (p?.full) window.open(p.full, "_blank"); };
  });
}

async function scanAction(id, act, value) {
  const sid = state.scanId, pages = state.scanPages, i = pages.findIndex((p) => p.id === id);
  try {
    if (act === "left" || act === "right") {
      const j = act === "left" ? i - 1 : i + 1;
      [pages[i], pages[j]] = [pages[j], pages[i]];
      renderScanPages();
      await api("POST", `/api/scan/${sid}/order`, { order: pages.map((p) => p.id) });
      return;
    }
    if (act === "del") {
      await api("DELETE", `/api/scan/${sid}/page/${id}`);
      pages.splice(i, 1);
      return renderScanPages();
    }
    pages[i] = { ...pages[i], busy: true };
    renderScanPages();
    if (act === "rotl" || act === "rotr") pages[i] = await api("POST", `/api/scan/${sid}/page/${id}/rotate?cw=${act === "rotr"}`);
    if (act === "mode") pages[i] = await api("POST", `/api/scan/${sid}/page/${id}/mode`,
      value === "original" ? { mode: "auto", original: true } : { mode: value });
  } catch (e) {
    toast(e.message, true);
    if (pages[i]) pages[i].busy = false;
  }
  renderScanPages();
}

async function finishScan() {
  if (!state.scanId || !state.scanPages.length) return;
  if (state.scanPages.some((p) => p.busy)) return toast("Bitte warten, bis alle Seiten aufbereitet sind.");
  const btn = $("#btn-finish");
  btn.disabled = true;
  try {
    const r = await api("POST", `/api/scan/${state.scanId}/finish`, { single: $("#scan-single").checked, name: $("#scan-name").value });
    state.scanId = null; state.scanPages = [];
    $("#scan-name").value = "";
    renderScanPages();
    toast(`Gespeichert als „${r.saved}“ – Verarbeitung läuft.`);
  } catch (e) { toast(e.message, true); }
  btn.disabled = false;
}

// ------------------------------------------------------------------ Hochladen
function viewUpload(el) {
  el.innerHTML = `
    <div class="card">
      <h1>Dateien hochladen</h1>
      <p class="muted small" style="margin-top:0">PDFs werden in den Eingangsordner gelegt und sofort verarbeitet. Mehrere Bilder einer Auswahl werden zu einer PDF zusammengefasst.</p>
      <div class="dropzone" id="drop">${icon("upload")}<div><b>Dateien hierher ziehen</b> oder klicken zum Auswählen</div><div class="muted small">PDF, JPG, PNG, TIFF</div></div>
      <input type="file" id="up-files" multiple accept=".pdf,image/*" class="hidden">
      <label class="check" style="margin-top:1rem"><input type="checkbox" id="up-single"><span><b>Jede Datei ist genau ein Dokument</b><br><span class="muted small">Nicht trennen. Für Stapel mit mehreren Dokumenten nicht anhaken.</span></span></label>
      <div id="up-progress" class="hidden"><div class="small" id="up-text"></div><div class="progress"><div id="up-bar" style="width:0"></div></div></div>
    </div>`;
  const drop = $("#drop"), inp = $("#up-files");
  drop.onclick = () => inp.click();
  inp.onchange = () => uploadFiles(inp.files);
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); uploadFiles(e.dataTransfer.files); };
}

function uploadFiles(files) {
  if (!files?.length) return;
  const fd = new FormData();
  for (const f of files) fd.append("files", f, f.name);
  fd.append("single", $("#up-single").checked ? "true" : "false");
  const box = $("#up-progress"), bar = $("#up-bar"), txt = $("#up-text");
  box.classList.remove("hidden");
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/upload");
  xhr.upload.onprogress = (e) => {
    const pct = e.lengthComputable ? Math.round((e.loaded / e.total) * 100) : 0;
    bar.style.width = pct + "%";
    txt.textContent = `Lade ${files.length} Datei(en) hoch … ${pct}%`;
  };
  xhr.onload = () => {
    let data = {};
    try { data = JSON.parse(xhr.responseText); } catch {}
    if (xhr.status === 401) return renderAuth();
    if (xhr.status >= 400) { toast(data.detail || "Upload fehlgeschlagen", true); txt.textContent = "Fehlgeschlagen."; return; }
    txt.textContent = `Hochgeladen: ${data.saved.join(", ")} – Verarbeitung gestartet.`;
    toast("Hochgeladen – Verarbeitung läuft");
    $("#up-files").value = "";
  };
  xhr.onerror = () => toast("Verbindung unterbrochen", true);
  xhr.send(fd);
}

// ------------------------------------------------------------------ Protokoll
function viewLog(el) {
  el.innerHTML = `<div class="card"><div class="card-head"><h2>Protokoll</h2><div class="spacer"></div>
    <label class="check" style="margin:0"><input type="checkbox" id="log-follow" checked><span>automatisch scrollen</span></label></div>
    <div class="log" id="log"></div></div>`;
  state.logLast = 0;
  const box = $("#log");
  const load = async () => {
    let lines;
    try { lines = await api("GET", `/api/log?since=${state.logLast}`); } catch { return; }
    if (!lines.length) return;
    state.logLast = lines[lines.length - 1].id;
    box.insertAdjacentHTML("beforeend", lines.map((l) => `<div class="${l.level}"><span class="t">${esc(l.time)}</span>  ${esc(l.text)}</div>`).join(""));
    if ($("#log-follow")?.checked) box.scrollTop = box.scrollHeight;
  };
  load();
  const t = setInterval(load, 2000);
  state.cleanup = () => clearInterval(t);
}

// ------------------------------------------------------------------ Tags & Dokumenttypen
async function viewTags(el) {
  el.innerHTML = `<div class="card"><div class="spinner"></div></div>`;
  let tax;
  try { tax = await api("GET", "/api/taxonomy"); } catch (e) { return; }
  const render = (t) => {
    el.innerHTML = `
      <div class="alert info small">Das Sprachmodell darf nur Tags und Dokumenttypen aus diesen Listen vergeben. Eine kurze Beschreibung je Tag verbessert die Trefferquote deutlich.
        „${esc(t.scope_tags[0])}“ und „${esc(t.scope_tags[1])}“ sind Bereichs-Tags: davon wird immer genau einer vergeben.</div>
      <div class="grid grid-2" style="grid-template-columns: minmax(0,2fr) minmax(0,1fr)">
        <div class="card"><div class="card-head"><h2>Tags</h2><div class="spacer"></div><button class="btn small" id="add-tag">+ Tag</button></div>
          <table class="tag-table"><tbody id="tag-rows">${t.tags.map((x) => tagRow(x, t.tag_descriptions[x] || "")).join("")}</tbody></table></div>
        <div class="card"><div class="card-head"><h2>Dokumenttypen</h2><div class="spacer"></div><button class="btn small" id="add-type">+ Typ</button></div>
          <div class="type-list" id="type-rows">${t.document_types.map(typeRow).join("")}</div></div>
      </div>
      <div class="btn-row"><button class="btn primary" id="tax-save">Speichern</button><div style="flex:1"></div><button class="btn" id="tax-reset">Standardliste wiederherstellen</button></div>`;
    $("#add-tag").onclick = () => { $("#tag-rows").insertAdjacentHTML("beforeend", tagRow("", "")); $("#tag-rows tr:last-child input").focus(); bindRemove(); };
    $("#add-type").onclick = () => { $("#type-rows").insertAdjacentHTML("beforeend", typeRow("")); $("#type-rows .row:last-child input").focus(); bindRemove(); };
    $("#tax-save").onclick = saveTax;
    $("#tax-reset").onclick = async () => {
      if (!confirm("Standardliste laden? Nicht gespeicherte Änderungen gehen verloren.")) return;
      render(await api("GET", "/api/taxonomy/defaults"));
      toast("Standardliste geladen – zum Übernehmen „Speichern“ klicken.");
    };
    bindRemove();
  };
  const bindRemove = () => $$("[data-remove]", el).forEach((b) => (b.onclick = () => b.closest("tr, .row").remove()));
  const saveTax = async () => {
    const tags = [], descs = {};
    $$("#tag-rows tr").forEach((tr) => {
      const [n, d] = $$("input", tr).map((i) => i.value.trim());
      if (n) { tags.push(n); if (d) descs[n] = d; }
    });
    const types = $$("#type-rows input").map((i) => i.value.trim()).filter(Boolean);
    try {
      await api("PUT", "/api/taxonomy", { tags, document_types: types, tag_descriptions: descs });
      toast("Gespeichert");
    } catch (e) { toast(e.message, true); }
  };
  render(tax);
}
const tagRow = (n, d) => `<tr><td><input type="text" value="${esc(n)}" placeholder="Tag"></td><td><input type="text" value="${esc(d)}" placeholder="Beschreibung für das Modell"></td><td><button class="btn ghost icon danger" data-remove title="entfernen">${icon("trash")}</button></td></tr>`;
const typeRow = (n) => `<div class="row"><input type="text" value="${esc(n)}" placeholder="Dokumenttyp"><button class="btn ghost icon danger" data-remove title="entfernen">${icon("trash")}</button></div>`;

// ------------------------------------------------------------------ Einstellungen
async function viewSettings(el) {
  el.innerHTML = `<div class="card"><div class="spinner"></div></div>`;
  let s, srv;
  try { [s, srv] = await Promise.all([api("GET", "/api/settings"), api("GET", "/api/server")]); } catch { return; }
  const lanIps = srv.ips.filter((i) => !i.startsWith("127."));
  const proto = srv.running_https ? "https" : "http";
  el.innerHTML = `
    <form id="set-form">
    <div class="card"><h2>Ordner</h2>
      <p class="muted small">Pfade auf dem Server. Netzlaufwerke bitte als UNC-Pfad angeben (z. B. <code>\\\\nas\\scans</code>), wenn OCRDMS als Dienst läuft.</p>
      <div class="grid grid-2">
        <label class="field"><span>Eingang (wird überwacht)</span><input type="text" name="input_dir" value="${esc(s.input_dir)}"><small>Unterordner „Einzeldokument“: Dateien dort werden nicht getrennt.</small></label>
        <label class="field"><span>Verarbeitet</span><input type="text" name="output_dir" value="${esc(s.output_dir)}"></label>
        <label class="field"><span>Originale (Archiv)</span><input type="text" name="archive_dir" value="${esc(s.archive_dir)}"></label>
        <label class="field"><span>Fehler</span><input type="text" name="error_dir" value="${esc(s.error_dir)}"></label>
      </div></div>
    <div class="card"><h2>Automatik</h2>
      <label class="check"><input type="checkbox" name="auto_run" ${s.auto_run ? "checked" : ""}><span>Eingang automatisch in festen Abständen verarbeiten</span></label>
      <label class="field" style="max-width:260px"><span>Intervall (Minuten)</span><input type="number" name="interval_minutes" min="1" max="1440" value="${s.interval_minutes}"></label></div>
    <div class="card"><h2>Ollama (Sprachmodell)</h2>
      <div class="grid grid-2">
        <label class="field"><span>Adresse</span><input type="url" name="ollama_url" value="${esc(s.ollama_url)}"></label>
        <label class="field"><span>Modell</span><div class="inline"><input type="text" name="model" list="model-list" value="${esc(s.model)}"><button type="button" class="btn" id="btn-test">Testen</button></div>
          <datalist id="model-list"></datalist></label>
      </div>
      <div id="ollama-status" class="small"></div></div>
    <div class="card"><h2>OCR und Trennung</h2>
      <div class="grid grid-2">
        <label class="field"><span>OCR-Auflösung (dpi)</span><input type="number" name="ocr_dpi" min="150" max="600" step="50" value="${s.ocr_dpi}"></label>
        <div></div>
        <label class="field"><span>Prüfmodus</span><select name="review_mode">
          <option value="auto" ${s.review_mode === "auto" ? "selected" : ""}>Alles automatisch ablegen</option>
          <option value="pruefen" ${s.review_mode === "pruefen" ? "selected" : ""}>Unsichere Trennungen in „_Pruefen“ legen</option></select></label>
        <label class="field"><span>Als unsicher gilt unter (%)</span><input type="number" name="review_confidence" min="0" max="100" value="${s.review_confidence}"></label>
      </div>
      <label class="check"><input type="checkbox" name="remove_blank_pages" ${s.remove_blank_pages ? "checked" : ""}><span>Leere Seiten (z. B. Rückseiten beim Duplex-Scan) entfernen</span></label></div>
    <div class="btn-row" style="margin-bottom:1.5rem"><button class="btn primary">Einstellungen speichern</button></div>
    </form>

    <div class="card"><h2>Netzwerk</h2>
      ${srv.restart_needed ? `<div class="alert warn">Geänderte Netzwerk-Einstellungen werden erst nach einem Neustart von OCRDMS wirksam.</div>` : ""}
      <p class="small">Erreichbar im Netz unter:<br>${lanIps.concat(srv.names.filter((n) => n !== "localhost")).map((h) => `<code>${proto}://${esc(h)}:${srv.running_port}</code>`).join(" ")}</p>
      <form id="srv-form" class="grid grid-2">
        <label class="field"><span>Port</span><input type="number" name="port" min="1" max="65535" value="${srv.port}"></label>
        <label class="check" style="align-self:center"><input type="checkbox" name="https" ${srv.https ? "checked" : ""}><span>HTTPS verwenden (für die Handy-Kamera empfohlen)</span></label>
        <div><button class="btn">Netzwerk speichern</button></div>
      </form>
      ${srv.running_https ? `
      <h3 style="margin-top:1rem">Zertifikatswarnung auf Handy/PC vermeiden</h3>
      <p class="small muted" style="margin-top:0">OCRDMS verwendet ein eigenes Zertifikat. Installiere einmalig das Stammzertifikat auf jedem Gerät, dann verschwindet die Warnung.</p>
      <p><a class="btn small" href="/OCRDMS-CA.crt" download>Stammzertifikat herunterladen</a></p>
      <ol class="steps small">
        <li><b>Android:</b> Datei öffnen → Einstellungen → Sicherheit → Weitere Einstellungen → Verschlüsselung &amp; Anmeldedaten → Zertifikat installieren → <i>CA-Zertifikat</i>.</li>
        <li><b>iPhone/iPad:</b> In Safari herunterladen → Einstellungen → „Profil geladen“ → Installieren. Danach Allgemein → Info → Zertifikatsvertrauenseinstellungen → „OCRDMS lokale CA“ aktivieren.</li>
        <li><b>Windows:</b> Datei doppelklicken → Zertifikat installieren → Lokaler Computer → Speicher „Vertrauenswürdige Stammzertifizierungsstellen“.</li>
      </ol>` : ""}
    </div>

    <div class="card"><h2>Updates</h2>
      <p class="small" style="margin-top:0">Installierte Version: <b>${esc(state.version)}</b> <span id="upd-info" class="muted"></span></p>
      <div class="btn-row" style="margin-bottom:1rem">
        <button type="button" class="btn" id="btn-upd-check">${icon("refresh")}Nach Updates suchen</button>
        <button type="button" class="btn primary hidden" id="btn-upd-install">Update installieren</button>
      </div>
      <div id="upd-notes" class="small hidden" style="white-space:pre-wrap;background:var(--surface-2);border:1px solid var(--border);border-radius:8px;padding:.6rem .8rem;margin-bottom:1rem;max-height:220px;overflow:auto"></div>
      <form id="upd-form">
        <label class="check"><input type="checkbox" name="update_check" ${s.update_check ? "checked" : ""}><span>Regelmäßig automatisch nach Updates suchen</span></label>
        <div class="grid grid-2">
          <label class="field"><span>GitHub-Repository</span><input type="text" name="github_repo" value="${esc(s.github_repo)}" placeholder="Besitzer/Name"></label>
          <label class="field"><span>GitHub-Token ${s.github_token_set ? '<span class="chip scope">gespeichert</span>' : ""}</span>
            <input type="password" name="github_token" autocomplete="off" placeholder="${s.github_token_set ? "unverändert lassen" : "nur für private Repositories"}">
            <small>Fein abgestufter Token mit Leserecht „Contents: Read-only“ nur für dieses Repository.</small></label>
        </div>
        <div class="btn-row"><button class="btn">Speichern</button>
          ${s.github_token_set ? '<button type="button" class="btn danger" id="btn-token-clear">Token entfernen</button>' : ""}</div>
      </form>
    </div>

    <div class="card"><h2>Passwort ändern</h2>
      <form id="pw-form" class="grid grid-3">
        <label class="field"><span>Bisheriges Passwort</span><input type="password" name="old" autocomplete="current-password" required></label>
        <label class="field"><span>Neues Passwort</span><input type="password" name="new" autocomplete="new-password" minlength="8" required></label>
        <div style="align-self:end;margin-bottom:.85rem"><button class="btn">Ändern</button></div>
      </form>
      <button class="btn" id="btn-logout">${icon("logout")}Abmelden</button>
      <p class="muted small" style="margin-bottom:0">OCRDMS ${esc(state.version)}</p>
    </div>`;

  const testOllama = async () => {
    const f = $("#set-form"), out = $("#ollama-status");
    out.innerHTML = '<span class="spinner small"></span> Verbinde …';
    const r = await api("POST", "/api/ollama/test", { url: f.ollama_url.value, model: f.model.value }).catch((e) => ({ ok: false, error: e.message }));
    if (!r.ok) { out.innerHTML = `<span style="color:var(--danger)">❌ ${esc(r.error)}</span>`; return; }
    $("#model-list").innerHTML = r.models.map((m) => `<option value="${esc(m)}">`).join("");
    out.innerHTML = r.model_installed
      ? `<span style="color:var(--ok)">✅ Verbunden – Modell ist verfügbar (${r.models.length} Modelle installiert).</span>`
      : `<span style="color:var(--warn)">⚠ Verbunden, aber Modell „${esc(f.model.value)}“ ist nicht installiert. Verfügbar: ${esc(r.models.join(", ") || "–")}</span>`;
  };
  $("#btn-test").onclick = testOllama;
  testOllama();

  $("#set-form").onsubmit = async (ev) => {
    ev.preventDefault();
    const f = ev.target, body = {};
    for (const el of f.elements) {
      if (!el.name) continue;
      body[el.name] = el.type === "checkbox" ? el.checked : el.type === "number" ? Number(el.value) : el.value.trim();
    }
    try { await api("PUT", "/api/settings", body); toast("Einstellungen gespeichert"); poll(); }
    catch (e) { toast(e.message, true); }
  };
  $("#srv-form").onsubmit = async (ev) => {
    ev.preventDefault();
    const f = ev.target;
    try {
      const r = await api("PUT", "/api/server", { port: Number(f.port.value), https: f.https.checked });
      toast(r.restart_needed ? "Gespeichert – wirksam nach Neustart von OCRDMS" : "Gespeichert");
      viewSettings(el);
    } catch (e) { toast(e.message, true); }
  };
  $("#pw-form").onsubmit = async (ev) => {
    ev.preventDefault();
    const f = ev.target;
    try { await api("POST", "/api/auth/password", { old: f.old.value, new: f.new.value }); toast("Passwort geändert"); f.reset(); }
    catch (e) { toast(e.message, true); }
  };
  $("#btn-logout").onclick = async () => { await api("POST", "/api/auth/logout"); renderAuth(false); };

  const showUpdate = (u) => {
    const info = $("#upd-info"), btn = $("#btn-upd-install"), notes = $("#upd-notes");
    if (!info) return;
    if (u.error) info.innerHTML = `– <span style="color:var(--danger)">${esc(u.error)}</span>`;
    else if (u.available) info.innerHTML = `– <span style="color:var(--ok)">Version <b>${esc(u.latest)}</b> verfügbar</span>`;
    else if (u.latest) info.textContent = `– aktuell (neueste: ${u.latest})`;
    else info.textContent = "";
    btn.classList.toggle("hidden", !(u.available && u.frozen));
    btn.onclick = () => startUpdate(u.latest);
    notes.classList.toggle("hidden", !(u.available && u.notes));
    notes.textContent = u.notes || "";
    if (u.available && !u.frozen) info.innerHTML += ' <span class="muted">(Installation nur in der installierten Version möglich)</span>';
  };
  api("GET", "/api/update").then(showUpdate).catch(() => {});
  $("#btn-upd-check").onclick = async (ev) => {
    ev.target.disabled = true;
    try { showUpdate(await api("POST", "/api/update/check")); } catch (e) { toast(e.message, true); }
    ev.target.disabled = false;
  };
  $("#upd-form").onsubmit = async (ev) => {
    ev.preventDefault();
    const f = ev.target;
    try {
      await api("PUT", "/api/settings", { update_check: f.update_check.checked, github_repo: f.github_repo.value.trim(), github_token: f.github_token.value.trim() });
      toast("Gespeichert");
      viewSettings(el);
    } catch (e) { toast(e.message, true); }
  };
  const clearBtn = $("#btn-token-clear");
  if (clearBtn) clearBtn.onclick = async () => {
    if (!confirm("Gespeicherten GitHub-Token entfernen?")) return;
    await api("PUT", "/api/settings", { github_token_clear: true });
    toast("Token entfernt");
    viewSettings(el);
  };
}

document.addEventListener("visibilitychange", () => { if (!document.hidden && pollTimer) poll(); });
boot();
