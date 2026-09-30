/* Worker (modulo ES) che esegue il codice Python di Alinea nel browser con Pyodide.
   Messaggi in ingresso: {id, cmd, args}; in uscita: {id, log} durante il lavoro e {id, result} o {id, error}.
   Pyodide >= 314 funziona solo in worker di tipo "module". */
import { loadPyodide } from "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs";

const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/";
const PY_BASE = new URL("../py/", import.meta.url).href;

let pyodide = null;
let ready = null;

async function init(report) {
  report("Avvio dell'ambiente Python nel browser (solo la prima volta scarica ~15 MB)…");
  pyodide = await loadPyodide({ indexURL: PYODIDE_URL });
  const manifest = await (await fetch(PY_BASE + "manifest.json")).json();
  await pyodide.loadPackage("micropip");
  const micropip = pyodide.pyimport("micropip");
  for (const whl of manifest.wheels) await micropip.install(PY_BASE + whl);
  pyodide.FS.mkdirTree("/home/pyodide/alinea");
  pyodide.FS.mkdirTree("/work");
  for (const f of manifest.files) {
    const src = await (await fetch(PY_BASE + f)).text();
    pyodide.FS.writeFile("/home/pyodide/" + f, src);
  }
  pyodide.runPython("import sys; sys.path.insert(0, '/home/pyodide'); import alinea.browser as B");
  report("Ambiente Python pronto");
}

function writeFile(name, bytes) {
  const safe = String(name || "file").replace(/[\/\\]/g, "_");
  const dir = "/work/" + Math.random().toString(36).slice(2);
  pyodide.FS.mkdirTree(dir);
  const path = `${dir}/${safe}`;
  pyodide.FS.writeFile(path, new Uint8Array(bytes));
  return path;
}

self.onmessage = async (ev) => {
  const { id, cmd, args } = ev.data;
  const report = (m) => self.postMessage({ id, log: m });
  try {
    if (!ready) ready = init(report);
    await ready;
    const B = pyodide.globals.get("B");
    let out;
    if (cmd === "init") {
      out = { ok: true };
    } else if (cmd === "pdfText") {
      const p = writeFile(args.name, args.bytes);
      out = JSON.parse(B.pdf_text_layer(p));
    } else if (cmd === "analyze") {
      const p = writeFile(args.cadName, args.cadBytes);
      const log = (m) => report(String(m));
      out = JSON.parse(B.run_analysis(p, args.drawing ? JSON.stringify(args.drawing) : "", JSON.stringify(args.config || {}), log));
    } else if (cmd === "generate") {
      out = JSON.parse(B.run_generate(args.jobId, JSON.stringify(args.plan), JSON.stringify(args.settings || {})));
    } else {
      throw new Error("comando sconosciuto: " + cmd);
    }
    self.postMessage({ id, result: out });
  } catch (e) {
    // gli errori Python arrivano come PythonError: mostra solo l'ultima riga (il messaggio)
    const msg = String(e && e.message ? e.message : e).trim().split("\n").filter(Boolean).pop();
    self.postMessage({ id, error: msg || "errore" });
  }
};
