"""Server web locale (FastAPI): interfaccia su http://127.0.0.1:8765"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import traceback
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .drawing_reader import tesseract_available
from .pipeline import analyze, make_program

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
CONFIG_PATH = Path(os.environ.get("ALINEA_CONFIG", ROOT / "impostazioni.json"))
WORK = Path(tempfile.gettempdir()) / "alinea_jobs"
EXAMPLES = ROOT / "esempi"

DEFAULTS = {
    "llama_api_key": "",
    "llama_region": "eu",
    "llama_parse_mode": "parse_page_with_llm",
    "reader_mode": "auto",
    "general_class": "",
    "probe": "PROBE1",
    "stylus_diameter": 2.0,
    "clearance": 20.0,
    "circle_hits": 4,
    "plane_hits": 4,
    "cylinder_min_length": 8.0,
    "tip_step": 7.5,
    "manual_alignment": True,
}

app = FastAPI(title="Alinea")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
JOBS: dict[str, dict] = {}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/api/settings")
def get_settings() -> dict:
    cfg = load_config()
    key = cfg.get("llama_api_key") or os.environ.get("LLAMA_CLOUD_API_KEY", "")
    out = {k: v for k, v in cfg.items() if k != "llama_api_key"}
    out["has_llama_key"] = bool(key)
    out["llama_key_hint"] = (key[:6] + "…" + key[-4:]) if len(key) > 12 else ""
    out["tesseract"] = tesseract_available()
    out["has_example"] = (EXAMPLES / "staffa.stp").exists()
    return out


@app.post("/api/settings")
def post_settings(body: dict) -> dict:
    cfg = load_config()
    for k, v in body.items():
        if k not in DEFAULTS:
            continue
        if k == "llama_api_key" and not v:
            continue  # campo vuoto = non modificare
        cfg[k] = type(DEFAULTS[k])(v) if DEFAULTS[k] is not None and not isinstance(DEFAULTS[k], bool) else v
    if body.get("clear_llama_key"):
        cfg["llama_api_key"] = ""
    save_config(cfg)
    return get_settings()


def _run_job(job_id: str, cad: str, drawing: str | None) -> None:
    job = JOBS[job_id]
    try:
        cfg = load_config()
        res = analyze(cad, drawing, cfg, log=lambda m: job["log"].append(m))
        job["fs"] = res.pop("_fs")
        job["result"] = res
        job["status"] = "done"
    except Exception as exc:  # noqa: BLE001 - l'errore va mostrato nell'interfaccia
        job["log"].append(f"ERRORE: {exc}")
        job["error"] = str(exc)
        job["trace"] = traceback.format_exc()
        job["status"] = "error"


def _start(cad: str, drawing: str | None, part_name: str) -> dict:
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"status": "running", "log": [], "cad": cad, "drawing": drawing, "part_name": part_name}
    threading.Thread(target=_run_job, args=(job_id, cad, drawing), daemon=True).start()
    return {"job_id": job_id}


def _save_upload(up: UploadFile, folder: Path) -> str:
    name = os.path.basename(up.filename or "file")
    dest = folder / name
    with dest.open("wb") as fh:
        shutil.copyfileobj(up.file, fh)
    return str(dest)


@app.post("/api/analyze")
def post_analyze(cad: UploadFile = File(...), drawing: UploadFile | None = File(None),
                 part_name: str = Form("")) -> dict:
    folder = WORK / uuid.uuid4().hex[:12]
    folder.mkdir(parents=True, exist_ok=True)
    cad_path = _save_upload(cad, folder)
    dr_path = _save_upload(drawing, folder) if drawing is not None and drawing.filename else None
    return _start(cad_path, dr_path, part_name or Path(cad.filename or "PEZZO").stem)


@app.post("/api/example")
def post_example() -> dict:
    cad = EXAMPLES / "staffa.stp"
    if not cad.exists():
        raise HTTPException(404, "Esempio non trovato")
    dr = EXAMPLES / "staffa_disegno.pdf"
    return _start(str(cad), str(dr) if dr.exists() else None, "STAFFA-001")


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> JSONResponse:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Analisi non trovata (il server è stato riavviato?)")
    out = {"status": job["status"], "log": job["log"], "error": job.get("error"),
           "part_name": job.get("part_name"), "has_drawing": bool(job.get("drawing"))}
    if job["status"] == "done":
        out["result"] = job["result"]
    return JSONResponse(out)


@app.get("/api/jobs/{job_id}/drawing")
def get_drawing(job_id: str) -> FileResponse:
    job = JOBS.get(job_id)
    if job is None or not job.get("drawing"):
        raise HTTPException(404, "Nessun disegno")
    return FileResponse(job["drawing"])


@app.post("/api/jobs/{job_id}/generate")
def post_generate(job_id: str, body: dict) -> dict:
    job = JOBS.get(job_id)
    if job is None or job.get("status") != "done":
        raise HTTPException(404, "Analisi non disponibile")
    cfg = load_config()
    settings = {k: cfg[k] for k in ("probe", "stylus_diameter", "clearance", "circle_hits", "plane_hits",
                                    "cylinder_min_length", "tip_step", "manual_alignment") if k in cfg}
    settings.update(body.get("settings", {}))
    settings.setdefault("part_name", job.get("part_name") or "PEZZO")
    try:
        return make_program(job["fs"], body["plan"], settings)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Generazione fallita: {exc}") from exc


def main() -> None:
    import webbrowser

    import uvicorn

    port = int(os.environ.get("ALINEA_PORT", "8765"))
    url = f"http://127.0.0.1:{port}"
    print(f"Alinea in esecuzione su {url}  (chiudi questa finestra per fermarlo)")
    if not os.environ.get("ALINEA_NO_BROWSER"):
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
