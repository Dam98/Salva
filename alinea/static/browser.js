/* Backend di Alinea che gira interamente nel browser: nessun file lascia il PC.
   - Python (lettore STEP, interpretazione, generatore PC-DMIS) con Pyodide in un Web Worker
   - testo dei PDF vettoriali con pypdf (in Python), scansioni con Tesseract.js e pdf.js */
"use strict";

window.AlineaBrowser = (() => {
  const SCRIPT_SRC = document.currentScript ? document.currentScript.src : location.href;
  // build "legacy": include i polyfill per i browser non recentissimi
  const PDFJS = "https://cdn.jsdelivr.net/npm/pdfjs-dist@6.3.289/legacy/build/";
  const TESSERACT = "https://cdn.jsdelivr.net/npm/tesseract.js@7.0.0/dist/tesseract.min.js";
  const MAX_OCR_PAGES = 4;
  const IMAGE_RE = /\.(png|jpe?g|bmp|webp|gif)$/i;

  const DEFAULTS = {
    llama_parse_mode: "parse_page_with_llm", reader_mode: "auto", general_class: "", probe: "PROBE1",
    stylus_diameter: 2.0, clearance: 20.0, circle_hits: 4, plane_hits: 4, cylinder_min_length: 8.0,
    tip_step: 7.5, manual_alignment: true,
  };

  // ---------------------------------------------------------------- worker Python
  let worker = null, seq = 0;
  const pending = new Map();
  function getWorker() {
    if (worker) return worker;
    worker = new Worker(new URL("pyworker.js", SCRIPT_SRC), { type: "module" });
    worker.onmessage = (ev) => {
      const { id, log, result, error } = ev.data;
      const p = pending.get(id);
      if (!p) return;
      if (log !== undefined) { p.onLog && p.onLog(log); return; }
      pending.delete(id);
      error !== undefined ? p.reject(new Error(error)) : p.resolve(result);
    };
    worker.onerror = (e) => { for (const p of pending.values()) p.reject(new Error("Errore del worker: " + e.message)); pending.clear(); };
    return worker;
  }
  function call(cmd, args, onLog, transfer = []) {
    const w = getWorker();
    const id = ++seq;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject, onLog });
      w.postMessage({ id, cmd, args }, transfer);
    });
  }

  // ---------------------------------------------------------------- librerie da CDN
  let pdfjsLib = null;
  async function pdfjs() {
    if (!pdfjsLib) {
      pdfjsLib = await import(PDFJS + "pdf.min.mjs");
      pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS + "pdf.worker.min.mjs";
    }
    return pdfjsLib;
  }
  let tessLoading = null;
  function tesseract() {
    if (window.Tesseract) return Promise.resolve(window.Tesseract);
    if (!tessLoading) {
      tessLoading = new Promise((res, rej) => {
        const s = document.createElement("script");
        s.src = TESSERACT; s.onload = () => res(window.Tesseract);
        s.onerror = () => rej(new Error("Impossibile caricare Tesseract.js (controlla la connessione)"));
        document.head.appendChild(s);
      });
    }
    return tessLoading;
  }

  // ---------------------------------------------------------------- disegno -> immagini
  function canvasOf(w, h) {
    const c = document.createElement("canvas");
    c.width = Math.max(1, Math.round(w)); c.height = Math.max(1, Math.round(h));
    return c;
  }
  async function renderPages(file, onLog) {
    if (/\.pdf$/i.test(file.name)) {
      const lib = await pdfjs();
      const doc = await lib.getDocument({ data: new Uint8Array(await file.arrayBuffer()) }).promise;
      const out = [];
      for (let i = 1; i <= Math.min(doc.numPages, MAX_OCR_PAGES); i++) {
        onLog(`Preparazione pagina ${i} per l'OCR…`);
        const page = await doc.getPage(i);
        const v1 = page.getViewport({ scale: 1 });
        const scale = 3000 / Math.max(v1.width, v1.height);   // ~3000 px sul lato lungo
        const vp = page.getViewport({ scale });
        const c = canvasOf(vp.width, vp.height);
        const ctx = c.getContext("2d");
        ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, c.width, c.height);
        await page.render({ canvasContext: ctx, viewport: vp }).promise;
        out.push(c);
      }
      if (doc.numPages > MAX_OCR_PAGES) onLog(`Il PDF ha ${doc.numPages} pagine: leggo le prime ${MAX_OCR_PAGES}`);
      return { canvases: out, pageCount: doc.numPages };
    }
    if (/\.tiff?$/i.test(file.name)) throw new Error("I file TIFF non si aprono nel browser: salvali come PDF o PNG");
    if (!IMAGE_RE.test(file.name)) throw new Error("Formato disegno non supportato: usa PDF o immagine PNG/JPG");
    const bmp = await createImageBitmap(file);
    const k = Math.min(4, 3000 / Math.max(bmp.width, bmp.height));
    const c = canvasOf(bmp.width * k, bmp.height * k);
    const ctx = c.getContext("2d");
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, c.width, c.height);
    ctx.drawImage(bmp, 0, 0, c.width, c.height);
    return { canvases: [c], pageCount: 1 };
  }

  async function ocr(canvases, onLog) {
    const T = await tesseract();
    onLog("OCR: caricamento del motore e delle lingue (italiano, inglese)…");
    let last = -1;
    const w = await T.createWorker(["ita", "eng"], 1, {
      logger: (m) => {
        if (m.status === "recognizing text") {
          const pct = Math.round((m.progress || 0) * 100);
          if (pct >= last + 25) { last = pct; onLog(`OCR: ${pct}%`); }
        }
      },
    });
    try {
      await w.setParameters({ tessedit_pageseg_mode: "11" });   // testo sparso: adatto ai disegni
      const pages = [], layout = [];
      for (let i = 0; i < canvases.length; i++) {
        onLog(`OCR: pagina ${i + 1} di ${canvases.length}…`); last = -1;
        const { data } = await w.recognize(canvases[i], {}, { blocks: true, text: true });
        const rows = [];
        for (const b of data.blocks || []) for (const p of b.paragraphs || []) for (const l of p.lines || []) {
          const t = (l.text || "").replace(/\s+/g, " ").trim();
          if (t) rows.push({ t, b: [l.bbox.x0, l.bbox.y0, l.bbox.x1, l.bbox.y1] });
        }
        rows.sort((a, b) => a.b[1] - b.b[1] || a.b[0] - b.b[0]);
        pages.push(rows.map((r) => r.t).join("\n"));
        layout.push(rows.map((r) => r.b));
      }
      return { pages, layout };
    } finally {
      await w.terminate();
    }
  }

  // ---------------------------------------------------------------- API usata dall'interfaccia
  async function readDrawing(drw, settings, onLog) {
    const mode = settings.reader_mode || "auto";
    const notes = [];
    let pageCount = 0;
    if (/\.pdf$/i.test(drw.name) && mode !== "tesseract") {
      onLog("Lettura del livello di testo del PDF…");
      const bytes = await drw.arrayBuffer();
      const t = await call("pdfText", { name: drw.name, bytes }, onLog, [bytes]);
      pageCount = t.page_count || 0;
      if (t.usable || mode === "pdf") {
        onLog(`PDF vettoriale: testo selezionabile letto da ${t.pages.length} pagine`);
        if (!t.usable) notes.push("Il PDF non ha un livello di testo leggibile.");
        return { pages: t.pages, method: "pdf-text", notes, page_count: pageCount };
      }
      notes.push(t.has_text ? "Il PDF ha testo ma illeggibile (font simbolici): uso l'OCR sull'immagine."
        : "Il PDF non ha livello di testo (scansione): uso l'OCR.");
      onLog(notes[notes.length - 1]);
    }
    const { canvases, pageCount: pc } = await renderPages(drw, onLog);
    const r = await ocr(canvases, onLog);
    notes.push("Letto con Tesseract.js (OCR nel browser): i simboli GD&T possono essere persi, verificare.");
    return { pages: r.pages, layout: r.layout, method: "tesseract", notes, page_count: pageCount || pc };
  }

  async function analyze({ cad, drw, partName, settings }, onLog) {
    const cfg = Object.assign({}, DEFAULTS, settings || {});
    await call("init", {}, onLog);
    const drawing = drw ? await readDrawing(drw, cfg, onLog) : null;
    const cadBytes = await cad.arrayBuffer();
    const res = await call("analyze", { cadName: cad.name, cadBytes, drawing, config: cfg }, onLog, [cadBytes]);
    return {
      jobId: res.job_id, result: res, part_name: partName || cad.name.replace(/\.[^.]+$/, ""),
      has_drawing: !!drw, drawing_name: drw ? drw.name : "", drawing_url: drw ? URL.createObjectURL(drw) : null,
    };
  }

  async function fetchFile(url, name) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`File di esempio non trovato (${name})`);
    return new File([await r.blob()], name);
  }

  return {
    settings() {
      return Object.assign({}, DEFAULTS, {
        web: true, browser: true, auth: false, has_llama_key: false, tesseract: true,
        has_example: true, max_upload_mb: 300,
      });
    },
    analyze,
    async example(settings, onLog) {
      const [cad, drw] = await Promise.all([fetchFile("esempi/staffa.stp", "staffa.stp"),
        fetchFile("esempi/staffa_disegno.pdf", "staffa_disegno.pdf")]);
      return analyze({ cad, drw, partName: "STAFFA-001", settings }, onLog);
    },
    generate(jobId, plan, settings) {
      return call("generate", { jobId, plan, settings });
    },
    warmup() { call("init", {}, () => {}).catch(() => {}); },
  };
})();
