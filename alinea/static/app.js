"use strict";
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

const CHECKS = {
  diameter: "Diametro", position: "Localizzazione", distance: "Distanza", flatness: "Planarità",
  perpendicularity: "Perpendicolarità", parallelism: "Parallelismo", cylindricity: "Cilindricità",
  circularity: "Circolarità", concentricity: "Coassialità", manual: "Manuale",
};
const METHOD = { "pdf-text": "Testo PDF", llamaparse: "LlamaParse (OCR)", tesseract: "Tesseract (OCR)", nessuno: "Nessuna" };

const S = { files: { cad: null, drw: null }, job: null, res: null, plan: null, prog: null, sel: null, settings: null, timer: null };

// ------------------------------------------------------------------ util
function toast(msg, ms = 2500) {
  const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.add("hidden"), ms);
}
function esc(s) { return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
function num(x, nd = 3) {
  if (x === null || x === undefined || x === "") return "";
  const s = (+x).toFixed(nd);
  return nd > 0 ? s.replace(/\.?0+$/, "") || "0" : s;
}
function show(step) {
  ["upload", "run", "review"].forEach((s) => $("#" + s).classList.toggle("hidden", s !== step));
  $$(".steps span").forEach((e) => e.classList.toggle("on", e.dataset.step === step));
}
async function api(url, opts = {}) {
  const r = await fetch(url, opts);
  if (r.status === 401 && !url.startsWith("/api/login")) { location.href = "/login"; throw new Error("Accesso richiesto"); }
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch (e) { /* */ } throw new Error(m); }
  return r.json();
}
// ------------------------------------------------------------------ backend: server o browser
const BROWSER = window.ALINEA_BROWSER === true && !!window.AlineaBrowser;
async function pollJob(id, onLog) {
  let seen = 0;
  for (;;) {
    const j = await api(`/api/jobs/${id}`);
    for (; seen < j.log.length; seen++) onLog(j.log[seen]);
    if (j.status === "error") throw new Error(j.error || "errore");
    if (j.status === "done") {
      return { jobId: id, result: j.result, part_name: j.part_name, has_drawing: j.has_drawing,
        drawing_name: j.drawing_name || "", drawing_url: `/api/jobs/${id}/drawing` };
    }
    await new Promise((r) => setTimeout(r, 700));
  }
}
const BE = BROWSER ? {
  settings: async () => window.AlineaBrowser.settings(),
  analyze: (a, onLog) => window.AlineaBrowser.analyze(a, onLog),
  example: (settings, onLog) => window.AlineaBrowser.example(settings, onLog),
  generate: (job, plan, settings) => window.AlineaBrowser.generate(job, plan, settings),
} : {
  settings: () => api("/api/settings"),
  async analyze({ cad, drw, partName, settings }, onLog) {
    const fd = new FormData();
    fd.append("cad", cad);
    if (drw) fd.append("drawing", drw);
    fd.append("part_name", partName);
    fd.append("settings", JSON.stringify(settings));
    const { job_id } = await api("/api/analyze", { method: "POST", body: fd });
    return pollJob(job_id, onLog);
  },
  async example(settings, onLog) {
    const { job_id } = await api("/api/example", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ settings }) });
    return pollJob(job_id, onLog);
  },
  generate: (job, plan, settings) => api(`/api/jobs/${job}/generate`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ plan, settings }),
  }),
};

function download(name, text, type) {
  const blob = new Blob([text], { type });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
}

// ------------------------------------------------------------------ step 1: caricamento
function setFile(kind, file) {
  S.files[kind] = file;
  const drop = kind === "cad" ? $("#dropCad") : $("#dropDrw");
  const name = kind === "cad" ? $("#nameCad") : $("#nameDrw");
  drop.classList.toggle("has", !!file);
  name.textContent = file ? `${file.name} · ${(file.size / 1024).toFixed(0)} kB` : "Trascina qui o clicca";
  if (kind === "cad" && file) {
    if (!$("#partName").value) $("#partName").value = file.name.replace(/\.[^.]+$/, "");
    const isCad = /\.cad$/i.test(file.name);
    $("#cadWarn").classList.toggle("hidden", !isCad);
    $("#cadWarn").textContent = isCad ? "Il file .CAD è la cache interna di PC-DMIS e non è leggibile: in PC-DMIS usa File › Esporta › Modello › STEP (AP214) e carica il .stp." : "";
  }
  $("#btnRun").disabled = !S.files.cad || /\.cad$/i.test(S.files.cad.name);
}
function wireDrop(dropSel, inputSel, kind) {
  const drop = $(dropSel), input = $(inputSel);
  input.addEventListener("change", () => setFile(kind, input.files[0] || null));
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) setFile(kind, f); });
}

// impostazioni scelte dall'utente: in modalità web restano nel suo browser
const USER_KEYS = ["llama_parse_mode", "reader_mode", "general_class", "probe", "stylus_diameter", "clearance",
  "circle_hits", "plane_hits", "cylinder_min_length", "tip_step", "manual_alignment"];
const LS_KEY = "alinea_impostazioni";
function localPrefs() { try { return JSON.parse(localStorage.getItem(LS_KEY) || "{}"); } catch (e) { return {}; } }
function userSettings() {
  const out = {};
  for (const k of USER_KEYS) if (S.settings && S.settings[k] !== undefined) out[k] = S.settings[k];
  return out;
}
async function loadSettings() {
  S.settings = await BE.settings();
  if (S.settings.web) Object.assign(S.settings, localPrefs());
  const s = S.settings;
  $("#btnLogout").classList.toggle("hidden", !s.auth);
  $$(".local-only").forEach((el) => el.classList.toggle("hidden", !!s.web));
  const ocr = [];
  $$(".server-only").forEach((el) => el.classList.toggle("hidden", !!s.browser));
  if (s.browser) {
    $("#ocrState").innerHTML = '<b class="ok">Tutto nel tuo browser</b>: i file non vengono caricati su nessun server · OCR scansioni con Tesseract.js';
  } else {
    ocr.push(s.has_llama_key ? `<b class="ok">LlamaParse attivo${s.web ? " (chiave del server)" : ""}</b>` : '<b class="no">LlamaParse non configurato</b>');
    ocr.push(s.tesseract ? '<b class="ok">Tesseract disponibile</b>' : "Tesseract non installato");
    $("#ocrState").innerHTML = "OCR scansioni: " + ocr.join(" · ");
  }
  $("#btnExample").classList.toggle("hidden", !s.has_example);
}

async function startRun(fn) {
  show("run");
  $("#runLog").innerHTML = ""; $("#runTitle").textContent = "Analisi in corso…";
  $("#spinner").classList.remove("stop"); $("#btnBack").classList.add("hidden");
  const onLog = (line) => {
    const li = document.createElement("li");
    li.textContent = line;
    if (String(line).startsWith("ERRORE")) li.className = "err";
    $("#runLog").appendChild(li);
  };
  let j;
  try { j = await fn(onLog); } catch (e) { return runError(e.message); }
  S.job = j.jobId;
  S.res = j.result; S.res.part_name = j.part_name; S.res.has_drawing = j.has_drawing;
  S.res.drawing_name = j.drawing_name || ""; S.res.drawing_url = j.drawing_url;
  S.plan = JSON.parse(JSON.stringify(j.result.plan));
  S.sel = null;
  await regenerate(true);
  renderReview();
  show("review");
}
function runError(msg) {
  $("#runTitle").textContent = "Analisi non riuscita";
  $("#spinner").classList.add("stop");
  const li = document.createElement("li"); li.className = "err"; li.textContent = msg; $("#runLog").appendChild(li);
  $("#btnBack").classList.remove("hidden");
}

// ------------------------------------------------------------------ step 3: revisione
function featureOptions() {
  const cad = S.res.cad, opts = [];
  const loc = (S.prog && S.prog.local) || {};
  const p3 = (id, fb) => { const v = loc[id] || fb; return v ? `(${num(v[0], 1)}, ${num(v[1], 1)}, ${num(v[2], 1)})` : ""; };
  for (const p of cad.patterns) {
    opts.push({ v: p.members.join(","), t: `${p.members.length}× Ø${num(p.diameter)} (${p.members[0]}…${p.members.at(-1)})` });
  }
  for (const c of cad.cylinders) opts.push({ v: c.id, t: `${c.id} · ${c.kind === "hole" ? "foro" : "perno"} Ø${num(c.diameter)} ${p3(c.id, c.entry)}` });
  for (const p of cad.planes) {
    const n = p.normal; const ax = ["X", "Y", "Z"][[0, 1, 2].reduce((a, i) => (Math.abs(n[i]) > Math.abs(n[a]) ? i : a), 0)];
    const sg = n[["X", "Y", "Z"].indexOf(ax)] >= 0 ? "+" : "−";
    opts.push({ v: p.id, t: `${p.id} · piano ${ax}${sg} · ${num(p.area, 0)} mm²` });
  }
  return opts;
}
function selectHtml(opts, value, cls, allowEmpty = true) {
  let found = !value;
  let h = `<select class="${cls}">` + (allowEmpty ? `<option value="">— nessuna —</option>` : "");
  for (const o of opts) { const s = o.v === value; found = found || s; h += `<option value="${esc(o.v)}"${s ? " selected" : ""}>${esc(o.t)}</option>`; }
  if (!found) h += `<option value="${esc(value)}" selected>${esc(value)}</option>`;
  return h + "</select>";
}

function renderReview() {
  renderStats(); renderNotes(); renderDatums(); renderItems(); renderCode(); renderView(); renderDrawing();
}
function renderStats() {
  const r = S.res, st = (S.prog && S.prog.stats) || {};
  const holes = r.cad.cylinders.filter((c) => c.kind === "hole").length;
  const items = S.plan.items.filter((i) => i.enabled).length;
  const t = st.cycle_time_s || 0;
  const cells = [
    [r.part_name || r.cad.name, "pezzo"], [holes, "fori nel CAD"], [r.cad.planes.length, "piani nel CAD"],
    [r.characteristics.length, "quote lette"], [METHOD[r.drawing.method] || r.drawing.method, "lettura disegno"],
    [items, "controlli attivi"], [st.hits ?? "–", "punti tastati"], [(st.tips || []).length, "orientamenti tip"],
    [`${Math.floor(t / 60)}′${String(t % 60).padStart(2, "0")}″`, "tempo ciclo stimato"],
  ];
  $("#stats").innerHTML = cells.map(([b, s]) => `<div class="stat"><b>${esc(b)}</b><span>${esc(s)}</span></div>`).join("");
}
function renderNotes() {
  const r = S.res, notes = [];
  for (const n of r.drawing.notes) notes.push(["", n]);
  for (const n of r.cad.warnings) notes.push(["", n]);
  for (const n of S.plan.warnings || []) notes.push(["", n]);
  for (const n of (S.prog && S.prog.warnings) || []) notes.push(["", n]);
  if (r.drawing.general_class) notes.push(["info", `Tolleranze generali: ISO 2768-${r.drawing.general_class}`]);
  const nn = S.plan.items.filter((i) => i.status === "non associato").length;
  if (nn) notes.push(["", `${nn} caratteristiche non associate: scegli la feature CAD nella tabella per includerle.`]);
  notes.push(["info", "Coordinate teoriche nel sistema A/B/C calcolato dal CAD. Verificare il programma in PC-DMIS (simulazione) prima dell'esecuzione in DCC."]);
  $("#notes").innerHTML = notes.map(([c, n]) => `<div class="note ${c}">${esc(n)}</div>`).join("");
}
function renderDatums() {
  const opts = featureOptions().filter((o) => !o.v.includes(","));
  const cands = S.plan.datum_candidates || {};
  $("#datums").innerHTML = ["A", "B", "C"].map((L) => {
    const allowed = new Set(cands[L] || opts.map((o) => o.v));
    const o = opts.filter((x) => allowed.has(x.v));
    return `<label>${L} ${selectHtml(o, S.plan.datums[L] || "", "dsel", L !== "A").replace("<select", `<select data-d="${L}"`)}</label>`;
  }).join("");
  $$("#datums select").forEach((s) => s.addEventListener("change", () => {
    if (s.value) S.plan.datums[s.dataset.d] = s.value; else delete S.plan.datums[s.dataset.d];
    schedule();
  }));
}
function statusBadge(s) {
  const c = { associato: "associato", assunto: "assunto", "solo CAD": "solo", "non associato": "non" }[s] || "";
  return `<span class="badge ${c}">${esc(s)}</span>`;
}
function renderItems() {
  const opts = featureOptions();
  const tb = $("#items tbody");
  tb.innerHTML = S.plan.items.map((it, idx) => {
    const fval = it.features.join(",");
    const needRef = ["distance", "parallelism", "perpendicularity", "concentricity"].includes(it.check);
    const checkSel = `<select class="chk">${Object.entries(CHECKS).map(([k, v]) => `<option value="${k}"${k === it.check ? " selected" : ""}>${v}</option>`).join("")}</select>`;
    const notes = it.notes || [];
    const open = S.sel === it.id;
    const sub = (it.tolerance_source ? `toll.: ${it.tolerance_source}` : "")
      + (notes.length ? (open ? " · " + notes.join(" · ") : ` · ⓘ ${notes.length} ${notes.length > 1 ? "note" : "nota"}`) : "");
    return `<tr data-i="${idx}" class="${S.sel === it.id ? "sel" : ""} ${it.enabled ? "" : "off"}">
      <td><input type="checkbox" class="en" ${it.enabled ? "checked" : ""}></td>
      <td>${esc(it.id)}</td>
      <td title="${esc(notes.join("\n"))}"><div class="lbl">${esc(it.label)}</div>${it.datums && it.datums.length ? `<div class="sub">rif. ${esc(it.datums.join("|"))}${it.modifier ? " · " + esc(it.modifier) : ""}</div>` : ""}<div class="sub">${esc(sub)}</div></td>
      <td>${checkSel}</td>
      <td>${selectHtml(opts, fval, "fs")}${needRef ? `<div class="sub">rispetto a</div>${selectHtml(opts.filter((o) => !o.v.includes(",")), it.ref_feature || "", "rf")}` : ""}</td>
      <td><input class="num nom" type="number" step="0.001" value="${num(it.nominal, 4)}"></td>
      <td><input class="num up" type="number" step="0.001" value="${num(it.upper, 4)}"></td>
      <td><input class="num lo" type="number" step="0.001" value="${num(it.lower === null || it.lower === undefined ? null : -it.lower, 4)}"></td>
      <td>${statusBadge(it.status)}</td></tr>`;
  }).join("");
  $("#itemCount").textContent = `(${S.plan.items.filter((i) => i.enabled).length} attivi su ${S.plan.items.length})`;
  $$("#items tbody tr").forEach((tr) => {
    const it = S.plan.items[+tr.dataset.i];
    tr.addEventListener("click", (e) => { if (!["INPUT", "SELECT", "OPTION"].includes(e.target.tagName)) select(it.id); });
    tr.querySelector(".en").addEventListener("change", (e) => { it.enabled = e.target.checked; tr.classList.toggle("off", !it.enabled); schedule(); });
    tr.querySelector(".chk").addEventListener("change", (e) => { it.check = e.target.value; renderItems(); schedule(); });
    tr.querySelector(".fs").addEventListener("change", (e) => {
      it.features = e.target.value ? e.target.value.split(",") : [];
      if (it.features.length && it.status === "non associato") { it.status = "assunto"; it.enabled = true; }
      renderItems(); schedule();
    });
    const rf = tr.querySelector(".rf");
    if (rf) rf.addEventListener("change", (e) => { it.ref_feature = e.target.value || null; schedule(); });
    const numIn = (cls, fn) => tr.querySelector(cls).addEventListener("change", (e) => { const v = e.target.value === "" ? null : +e.target.value; fn(v); schedule(); });
    numIn(".nom", (v) => (it.nominal = v));
    numIn(".up", (v) => (it.upper = v));
    numIn(".lo", (v) => (it.lower = v === null ? null : -v));
  });
}

function select(id) {
  S.sel = S.sel === id ? null : id;
  renderItems();
  renderCode(true); renderView();
}
function selectedFeatures() {
  if (!S.sel) return new Set();
  const it = S.plan.items.find((i) => i.id === S.sel);
  if (it) return new Set([...it.features, it.ref_feature].filter(Boolean));
  return new Set([S.sel]);
}

function renderCode(scroll = false) {
  if (!S.prog) { $("#code").textContent = ""; return; }
  const lines = S.prog.program.split("\n");
  const hl = new Set();
  const B = S.prog.blocks || {};
  const mark = (k) => { const b = B[k]; if (b) for (let i = b[0]; i <= b[1]; i++) hl.add(i); };
  if (S.sel) { mark(S.sel); selectedFeatures().forEach(mark); }
  let first = null;
  $("#code").innerHTML = lines.map((l, i) => {
    const n = i + 1; const on = hl.has(n); if (on && first === null) first = n;
    let h = esc(l)
      .replace(/^(\S+)(\s*=)/, '<span class="nm">$1</span>$2')
      .replace(/\b(FEAT\/[A-Z/]+|ALIGNMENT\/[A-Z]+|DIM|MEAS\/[A-Z]+|HIT\/BASIC|TIP\/|MOVE\/[A-Z]+|CLEARP\/|MODE\/[A-Z]+|LOADPROBE\/)/g, '<span class="kw">$1</span>')
      .replace(/^(\s+COMMENT\/.*)$/, '<span class="cm">$1</span>');
    return `<span class="ln${on ? " hl" : ""}" data-n="${n}">${h || " "}</span>`;
  }).join("");
  if (scroll && first) { const el = $(`#code .ln[data-n="${first}"]`); if (el) $("#code").scrollTop = el.offsetTop - 60; }
}

function toLocal(p) {
  const f = S.prog.frame; const d = [p[0] - f.origin_cad[0], p[1] - f.origin_cad[1], p[2] - f.origin_cad[2]];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  return [dot(d, f.x), dot(d, f.y), dot(d, f.z)];
}
function vecLocal(v) { const f = S.prog.frame; const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; return [dot(v, f.x), dot(v, f.y), dot(v, f.z)]; }

function renderView() {
  const svg = $("#partView");
  if (!S.prog) { svg.innerHTML = ""; return; }
  const cad = S.res.cad;
  const polys = [];
  for (const p of cad.planes) {
    const n = vecLocal(p.normal); if (n[2] < 0.9) continue;
    for (const loop of p.outline) polys.push({ z: toLocal(p.centroid)[2], pts: loop.map(toLocal) });
  }
  polys.sort((a, b) => a.z - b.z);
  const all = cad.planes.flatMap((p) => p.outline.flat().map(toLocal));
  if (!all.length) { svg.innerHTML = ""; return; }
  const xs = all.map((p) => p[0]), ys = all.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const w = x1 - x0 || 1, h = y1 - y0 || 1, m = Math.max(w, h) * 0.08;
  const k = 100 / Math.max(w + 2 * m, h + 2 * m);
  const X = (x) => (x - x0 + m) * k, Y = (y) => (y1 - y + m) * k;
  const vbw = (w + 2 * m) * k, vbh = (h + 2 * m) * k;
  svg.setAttribute("viewBox", `0 0 ${vbw} ${vbh}`);
  const sel = selectedFeatures();
  const measured = new Set(S.plan.items.filter((i) => i.enabled).flatMap((i) => i.features));
  let s = polys.map((p) => `<polygon class="pl" points="${p.pts.map((q) => `${X(q[0]).toFixed(2)},${Y(q[1]).toFixed(2)}`).join(" ")}"/>`).join("");
  for (const c of cad.cylinders) {
    const e = toLocal(c.entry), v = vecLocal(c.axis);
    const cls = `hole${sel.has(c.id) ? " sel" : ""}${measured.has(c.id) ? "" : " off"}`;
    if (Math.abs(v[2]) > 0.9) {
      s += `<circle class="${cls}" data-f="${c.id}" cx="${X(e[0])}" cy="${Y(e[1])}" r="${(c.diameter / 2) * k}"/>`;
      s += `<text x="${X(e[0]) + (c.diameter / 2) * k + 0.8}" y="${Y(e[1]) - 0.8}">${c.id}</text>`;
    } else {
      const L = Math.max(c.length, 2);
      const b = [e[0] - v[0] * L, e[1] - v[1] * L];
      s += `<line class="${cls} side" data-f="${c.id}" x1="${X(e[0])}" y1="${Y(e[1])}" x2="${X(b[0])}" y2="${Y(b[1])}" stroke-width="${Math.max(c.diameter * k, 1)}" stroke-linecap="butt" style="stroke:var(--hole)"/>`;
      s += `<text x="${X(e[0]) + 1}" y="${Y(e[1]) - 1.5}">${c.id} (laterale)</text>`;
    }
  }
  // assi del sistema A/B/C
  s += `<line class="axis" x1="${X(0)}" y1="${Y(0)}" x2="${X(0) + 10}" y2="${Y(0)}"/><text x="${X(0) + 10.5}" y="${Y(0) + 1.5}">X</text>`;
  s += `<line class="axis y" x1="${X(0)}" y1="${Y(0)}" x2="${X(0)}" y2="${Y(0) - 10}"/><text x="${X(0) + 1}" y="${Y(0) - 10.5}">Y</text>`;
  svg.innerHTML = s;
  svg.querySelectorAll("[data-f]").forEach((el) => el.addEventListener("click", () => {
    const fid = el.dataset.f;
    const it = S.plan.items.find((i) => i.features.includes(fid) && i.enabled) || S.plan.items.find((i) => i.features.includes(fid));
    select(it ? it.id : fid);
    if (it) { const tr = $(`#items tbody tr[data-i="${S.plan.items.indexOf(it)}"]`); if (tr) tr.scrollIntoView({ block: "nearest" }); }
  }));
}

function renderDrawing() {
  const r = S.res;
  $("#drawingText").textContent = r.drawing.pages.length
    ? r.drawing.pages.map((p, i) => `--- pagina ${i + 1} ---\n${p}`).join("\n\n")
    : "Nessun testo letto dal disegno.\n\n" + r.drawing.notes.join("\n");
  const box = $("#drawingBox");
  if (!r.has_drawing) { box.innerHTML = '<p class="hint">Nessun disegno caricato.</p>'; return; }
  const url = r.drawing_url;
  const isPdf = /\.pdf$/i.test(r.drawing_name || "");
  box.innerHTML = isPdf ? `<iframe src="${url}"></iframe>` : `<img src="${url}" alt="disegno">`;
}

function schedule() { clearTimeout(S.timer); S.timer = setTimeout(() => regenerate(false), 350); }
async function regenerate(first) {
  try {
    S.prog = await BE.generate(S.job, S.plan, { ...userSettings(), part_name: $("#partName").value || S.res.part_name });
    if (!first) { renderStats(); renderNotes(); renderCode(); renderView(); }
  } catch (e) { toast(e.message, 5000); }
}

// ------------------------------------------------------------------ impostazioni
function openSettings() {
  const f = $("#formSettings"), s = S.settings || {};
  for (const el of f.elements) {
    if (!el.name) continue;
    if (el.type === "checkbox") el.checked = !!s[el.name];
    else if (el.name === "llama_api_key") el.value = "";
    else if (s[el.name] !== undefined) el.value = s[el.name];
  }
  $("#srvKey").classList.toggle("hidden", !s.web);
  $("#srvKey").innerHTML = s.browser
    ? "Versione nel browser: le scansioni sono lette con Tesseract.js direttamente nel tuo PC (LlamaParse non è disponibile senza server)."
    : s.has_llama_key
    ? "La chiave LlamaParse è configurata sul server (segreto): non serve inserirla."
    : "Chiave LlamaParse non configurata sul server: le scansioni vengono lette con Tesseract.";
  $("#keyHint").innerHTML = s.has_llama_key
    ? `Chiave salvata: <b>${esc(s.llama_key_hint || "impostata")}</b>. Lascia vuoto per mantenerla.`
    : "Gratuita (crediti mensili) su <b>cloud.llamaindex.ai</b> → API Keys.";
  $("#dlgSettings").showModal();
}
async function saveSettings(e) {
  e.preventDefault();
  const f = $("#formSettings"), body = {};
  for (const el of f.elements) {
    if (!el.name) continue;
    body[el.name] = el.type === "checkbox" ? el.checked : el.type === "number" ? +el.value : el.value;
  }
  if (S.settings && S.settings.web) {
    const keep = {};
    for (const k of USER_KEYS) if (body[k] !== undefined) keep[k] = body[k];
    try { localStorage.setItem(LS_KEY, JSON.stringify(keep)); } catch (err) { /* navigazione privata */ }
    Object.assign(S.settings, keep);
  } else {
    try { await api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); }
    catch (err) { return toast(err.message); }
  }
  $("#dlgSettings").close(); await loadSettings(); toast("Impostazioni salvate");
  if (S.job && S.res) regenerate(false);
}

// ------------------------------------------------------------------ avvio
function init() {
  wireDrop("#dropCad", "#fileCad", "cad");
  wireDrop("#dropDrw", "#fileDrw", "drw");
  $("#btnRun").addEventListener("click", () => {
    const mb = ((S.files.cad?.size || 0) + (S.files.drw?.size || 0)) / 1048576;
    const lim = (S.settings && S.settings.max_upload_mb) || 80;
    if (mb > lim) return toast(`File troppo grandi (${mb.toFixed(0)} MB, massimo ${lim} MB)`, 5000);
    runUpload();
  });
  const runUpload = () => startRun((onLog) => BE.analyze({ cad: S.files.cad, drw: S.files.drw,
    partName: $("#partName").value, settings: userSettings() }, onLog));
  $("#btnExample").addEventListener("click", () => {
    $("#partName").value = "STAFFA-001";
    startRun((onLog) => BE.example(userSettings(), onLog));
  });
  $("#btnLogout").addEventListener("click", async () => { try { await api("/api/logout", { method: "POST" }); } catch (e) { /* */ } location.href = "/login"; });
  $("#btnBack").addEventListener("click", () => show("upload"));
  $("#btnNew").addEventListener("click", () => show("upload"));
  $("#btnSettings").addEventListener("click", openSettings);
  $("#formSettings").addEventListener("submit", (e) => { if (e.submitter && e.submitter.value === "save") saveSettings(e); });
  $$(".tabs button").forEach((b) => b.addEventListener("click", () => {
    $$(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
    ["view", "drawing", "text"].forEach((t) => $("#tab-" + t).classList.toggle("hidden", t !== b.dataset.tab));
  }));
  $("#btnAdd").addEventListener("click", () => {
    const n = S.plan.items.length + 1;
    S.plan.items.push({ id: `M${n}`, label: "Nuovo controllo", check: "diameter", features: [], ref_feature: null, nominal: null,
      upper: 0.1, lower: -0.1, datums: [], modifier: null, diameter_zone: false, char_id: null, status: "assunto",
      tolerance_source: "manuale", enabled: false, notes: ["Aggiunto a mano: scegli feature e tolleranza"] });
    renderItems();
  });
  const part = () => ($("#partName").value || S.res.part_name || "PEZZO").replace(/[^\w.-]+/g, "_");
  $("#btnTxt").addEventListener("click", () => S.prog && download(`${part()}_PCDMIS.txt`, S.prog.program, "text/plain"));
  $("#btnCsv").addEventListener("click", () => S.prog && download(`${part()}_piano_controllo.csv`, S.prog.csv, "text/csv"));
  $("#btnCopy").addEventListener("click", async () => {
    if (!S.prog) return;
    try { await navigator.clipboard.writeText(S.prog.program); toast("Programma copiato negli appunti"); }
    catch (e) { toast("Copia non riuscita: usa Scarica .txt"); }
  });
  loadSettings().catch((e) => toast(e.message));
  if (BROWSER) window.AlineaBrowser.warmup();   // prepara Python mentre l'utente sceglie i file
}
init();
