"""Server FastAPI di Alinea.

Due modalità:
- locale (default): http://127.0.0.1:8765, impostazioni salvate in impostazioni.json
- web (ALINEA_WEB=1): per l'hosting (Render, Docker). Accesso con password (ALINEA_PASSWORD),
  chiave LlamaParse solo come segreto del server (LLAMA_CLOUD_API_KEY), impostazioni per utente
  salvate nel browser, pulizia automatica dei file caricati.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import shutil
import tempfile
import threading
import time
import traceback
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .drawing_reader import tesseract_available
from .pipeline import analyze, make_program

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
CONFIG_PATH = Path(os.environ.get("ALINEA_CONFIG", ROOT / "impostazioni.json"))
WORK = Path(tempfile.gettempdir()) / "alinea_jobs"
EXAMPLES = ROOT / "esempi"

WEB = os.environ.get("ALINEA_WEB", "") == "1"
PASSWORD = os.environ.get("ALINEA_PASSWORD", "")
SECRET = (os.environ.get("ALINEA_SECRET") or secrets.token_hex(32)).encode()
SESSION_DAYS = 7
MAX_UPLOAD_MB = int(os.environ.get("ALINEA_MAX_UPLOAD_MB", "80"))
JOB_TTL_S = int(os.environ.get("ALINEA_JOB_TTL_MIN", "120")) * 60
MAX_RUNNING = int(os.environ.get("ALINEA_MAX_RUNNING", "2"))
COOKIE = "alinea_sessione"
# in modalità web senza password l'app resta chiusa, a meno di sceglierlo esplicitamente
ALLOW_PUBLIC = os.environ.get("ALINEA_ALLOW_PUBLIC", "") == "1"
# chi può incorporare la pagina in un iframe (Hugging Face mostra lo Space dentro huggingface.co)
FRAME_ANCESTORS = os.environ.get("ALINEA_FRAME_ANCESTORS", "'self' https://huggingface.co")

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
# impostazioni che un utente può scegliere per sé (in modalità web restano nel suo browser)
USER_KEYS = ("llama_parse_mode", "reader_mode", "general_class", "probe", "stylus_diameter", "clearance",
             "circle_hits", "plane_hits", "cylinder_min_length", "tip_step", "manual_alignment")
MACHINE_KEYS = ("probe", "stylus_diameter", "clearance", "circle_hits", "plane_hits", "cylinder_min_length",
                "tip_step", "manual_alignment")

app = FastAPI(title="Alinea", docs_url=None if WEB else "/docs", redoc_url=None, openapi_url=None if WEB else "/openapi.json")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


# --------------------------------------------------------------------------- impostazioni

def _coerce(key: str, value):
    d = DEFAULTS[key]
    if isinstance(d, bool):
        return bool(value)
    if isinstance(d, (int, float)):
        try:
            return type(d)(value)
        except (TypeError, ValueError):
            return d
    return "" if value is None else str(value)


def clean_user_settings(raw: dict | None) -> dict:
    return {k: _coerce(k, v) for k, v in (raw or {}).items() if k in USER_KEYS}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if not WEB and CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    if WEB or not cfg.get("llama_api_key"):
        cfg["llama_api_key"] = os.environ.get("LLAMA_CLOUD_API_KEY", "")
    if os.environ.get("LLAMA_REGION"):
        cfg["llama_region"] = os.environ["LLAMA_REGION"]
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------- accesso con password

def _sign(exp: int) -> str:
    return hmac.new(SECRET, str(exp).encode(), hashlib.sha256).hexdigest()


def make_token() -> str:
    exp = int(time.time()) + SESSION_DAYS * 86400
    return f"{exp}.{_sign(exp)}"


def valid_token(tok: str | None) -> bool:
    if not tok or "." not in tok:
        return False
    exp_s, sig = tok.split(".", 1)
    try:
        exp = int(exp_s)
    except ValueError:
        return False
    return exp > time.time() and hmac.compare_digest(sig, _sign(exp))


AUTH_REQUIRED = bool(PASSWORD)
OPEN_PATHS = {"/login", "/api/login", "/healthz", "/static/style.css", "/favicon.ico"}
_FAILS: dict[str, list[float]] = {}


@app.middleware("http")
async def guard(request: Request, call_next):
    path = request.url.path
    if WEB and not AUTH_REQUIRED and not ALLOW_PUBLIC and path != "/healthz":
        return HTMLResponse(SETUP_PAGE, 503)
    if request.method == "POST" and path == "/api/analyze":
        size = int(request.headers.get("content-length") or 0)
        if size > MAX_UPLOAD_MB * 1024 * 1024:
            return JSONResponse({"detail": f"File troppo grandi (massimo {MAX_UPLOAD_MB} MB in totale)"}, 413)
    if AUTH_REQUIRED and path not in OPEN_PATHS and not valid_token(request.cookies.get(COOKIE)):
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Accesso richiesto"}, 401)
        return RedirectResponse("/login", 303)
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("Content-Security-Policy", f"frame-ancestors {FRAME_ANCESTORS}")
    return resp


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


@app.get("/login", response_class=HTMLResponse)
def login_page() -> str:
    if not AUTH_REQUIRED:
        return '<meta http-equiv="refresh" content="0; url=/">'
    return (STATIC / "login.html").read_text(encoding="utf-8")


@app.post("/api/login")
def login(body: dict, request: Request) -> JSONResponse:
    ip = _client_ip(request)
    now = time.time()
    fails = [t for t in _FAILS.get(ip, []) if now - t < 600]
    if len(fails) >= 8:
        raise HTTPException(429, "Troppi tentativi: riprova tra qualche minuto")
    if not AUTH_REQUIRED or hmac.compare_digest(str(body.get("password", "")).encode(), PASSWORD.encode()):
        _FAILS.pop(ip, None)
        resp = JSONResponse({"ok": True})
        _set_session(resp, request, make_token(), SESSION_DAYS * 86400)
        return resp
    fails.append(now)
    _FAILS[ip] = fails
    raise HTTPException(401, "Password errata")


@app.post("/api/logout")
def logout(request: Request) -> JSONResponse:
    resp = JSONResponse({"ok": True})
    _set_session(resp, request, "", 0)
    return resp


def _set_session(resp: JSONResponse, request: Request, value: str, max_age: int) -> None:
    """Su HTTPS il cookie è SameSite=None + Partitioned, così funziona anche dentro l'iframe di
    huggingface.co; in HTTP (uso locale) resta un normale cookie Lax."""
    https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    attrs = [f"{COOKIE}={value}", "Path=/", f"Max-Age={max_age}", "HttpOnly"]
    # il valore è "scadenza.firma_hex": nessun carattere da codificare
    attrs += ["Secure", "SameSite=None", "Partitioned"] if https else ["SameSite=Lax"]
    resp.headers.append("set-cookie", "; ".join(attrs))


SETUP_PAGE = """<!doctype html><html lang="it"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Alinea · configurazione</title>
<body style="font-family:system-ui,sans-serif;max-width:640px;margin:10vh auto;padding:0 16px;line-height:1.5">
<h1>Alinea non è ancora configurata</h1>
<p>Per sicurezza la webapp non si apre senza password. Imposta il segreto <b>ALINEA_PASSWORD</b>
nelle impostazioni del servizio (Hugging Face: <i>Settings › Variables and secrets › New secret</i>)
e riavvia. Se vuoi davvero un accesso libero, imposta la variabile <b>ALINEA_ALLOW_PUBLIC=1</b>.</p>
</body></html>"""


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


# --------------------------------------------------------------------------- pagine e impostazioni

@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/api/settings")
def get_settings() -> dict:
    cfg = load_config()
    key = cfg.get("llama_api_key", "")
    out = {k: v for k, v in cfg.items() if k != "llama_api_key"}
    out["has_llama_key"] = bool(key)
    out["llama_key_hint"] = "" if WEB else ((key[:6] + "…" + key[-4:]) if len(key) > 12 else "")
    out["tesseract"] = tesseract_available()
    out["has_example"] = (EXAMPLES / "staffa.stp").exists()
    out["web"] = WEB
    out["auth"] = AUTH_REQUIRED
    out["max_upload_mb"] = MAX_UPLOAD_MB
    return out


@app.post("/api/settings")
def post_settings(body: dict) -> dict:
    if WEB:
        raise HTTPException(403, "In modalità web le impostazioni restano nel browser; la chiave è un segreto del server")
    cfg = load_config()
    for k, v in body.items():
        if k not in DEFAULTS:
            continue
        if k == "llama_api_key" and not v:
            continue  # campo vuoto = non modificare
        cfg[k] = _coerce(k, v)
    if body.get("clear_llama_key"):
        cfg["llama_api_key"] = ""
    save_config(cfg)
    return get_settings()


# --------------------------------------------------------------------------- analisi

def _cleanup() -> None:
    now = time.time()
    with JOBS_LOCK:
        old = [k for k, j in JOBS.items() if now - j["created"] > JOB_TTL_S and j["status"] != "running"]
        for k in old:
            folder = JOBS.pop(k).get("folder")
            if folder:
                shutil.rmtree(folder, ignore_errors=True)


def _run_job(job_id: str, cad: str, drawing: str | None, user_cfg: dict) -> None:
    job = JOBS[job_id]
    try:
        cfg = load_config()
        cfg.update(user_cfg)
        res = analyze(cad, drawing, cfg, log=lambda m: job["log"].append(m))
        job["fs"] = res.pop("_fs")
        job["result"] = res
        job["status"] = "done"
    except Exception as exc:  # noqa: BLE001 - l'errore va mostrato nell'interfaccia
        job["log"].append(f"ERRORE: {exc}")
        job["error"] = str(exc)
        job["trace"] = traceback.format_exc()
        job["status"] = "error"


def _start(cad: str, drawing: str | None, part_name: str, user_cfg: dict, folder: Path | None) -> dict:
    _cleanup()
    with JOBS_LOCK:
        if sum(1 for j in JOBS.values() if j["status"] == "running") >= MAX_RUNNING:
            raise HTTPException(429, "Server occupato con altre analisi: riprova tra poco")
        job_id = uuid.uuid4().hex
        JOBS[job_id] = {"status": "running", "log": [], "cad": cad, "drawing": drawing, "part_name": part_name,
                        "created": time.time(), "folder": str(folder) if folder else None}
    threading.Thread(target=_run_job, args=(job_id, cad, drawing, user_cfg), daemon=True).start()
    return {"job_id": job_id}


def _save_upload(up: UploadFile, folder: Path) -> str:
    name = os.path.basename(up.filename or "file").replace("\\", "_") or "file"
    dest = folder / name
    with dest.open("wb") as fh:
        shutil.copyfileobj(up.file, fh)
    return str(dest)


def _parse_settings(raw: str) -> dict:
    try:
        return clean_user_settings(json.loads(raw)) if raw else {}
    except json.JSONDecodeError:
        return {}


@app.post("/api/analyze")
def post_analyze(cad: UploadFile = File(...), drawing: UploadFile | None = File(None),
                 part_name: str = Form(""), settings: str = Form("")) -> dict:
    folder = WORK / uuid.uuid4().hex
    folder.mkdir(parents=True, exist_ok=True)
    cad_path = _save_upload(cad, folder)
    dr_path = _save_upload(drawing, folder) if drawing is not None and drawing.filename else None
    try:
        return _start(cad_path, dr_path, part_name or Path(cad.filename or "PEZZO").stem,
                      _parse_settings(settings), folder)
    except HTTPException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


@app.post("/api/example")
def post_example(body: dict | None = None) -> dict:
    cad = EXAMPLES / "staffa.stp"
    if not cad.exists():
        raise HTTPException(404, "Esempio non trovato")
    dr = EXAMPLES / "staffa_disegno.pdf"
    return _start(str(cad), str(dr) if dr.exists() else None, "STAFFA-001",
                  clean_user_settings((body or {}).get("settings")), None)


def _job(job_id: str) -> dict:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Analisi non trovata (scaduta o server riavviato): ricarica i file")
    return job


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> JSONResponse:
    job = _job(job_id)
    out = {"status": job["status"], "log": job["log"], "error": job.get("error"),
           "part_name": job.get("part_name"), "has_drawing": bool(job.get("drawing")),
           "drawing_name": os.path.basename(job["drawing"]) if job.get("drawing") else None}
    if job["status"] == "done":
        out["result"] = job["result"]
    return JSONResponse(out)


@app.get("/api/jobs/{job_id}/drawing")
def get_drawing(job_id: str) -> FileResponse:
    job = _job(job_id)
    path = job.get("drawing")
    ext = os.path.splitext(path or "")[1].lower()
    types = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".tif": "image/tiff", ".tiff": "image/tiff", ".bmp": "image/bmp", ".webp": "image/webp"}
    if not path or ext not in types:
        raise HTTPException(404, "Nessun disegno visualizzabile")
    return FileResponse(path, media_type=types[ext], content_disposition_type="inline")


@app.post("/api/jobs/{job_id}/generate")
def post_generate(job_id: str, body: dict) -> dict:
    job = _job(job_id)
    if job.get("status") != "done":
        raise HTTPException(409, "Analisi non ancora conclusa")
    cfg = load_config()
    settings = {k: cfg[k] for k in MACHINE_KEYS}
    user = body.get("settings") or {}
    settings.update({k: v for k, v in clean_user_settings(user).items() if k in MACHINE_KEYS})
    settings["part_name"] = str(user.get("part_name") or job.get("part_name") or "PEZZO")[:60]
    try:
        return make_program(job["fs"], body["plan"], settings)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Generazione fallita: {exc}") from exc


def main() -> None:
    import webbrowser

    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0" if WEB else "127.0.0.1")
    port = int(os.environ.get("PORT") or os.environ.get("ALINEA_PORT") or "8765")
    url = f"http://127.0.0.1:{port}"
    if WEB:
        print(f"Alinea (modalità web) su {host}:{port} - password {'attiva' if AUTH_REQUIRED else 'NON impostata'}"
              f" - LlamaParse {'attivo' if os.environ.get('LLAMA_CLOUD_API_KEY') else 'non configurato'}"
              f" - Tesseract {'disponibile' if tesseract_available() else 'assente'}")
    else:
        print(f"Alinea in esecuzione su {url}  (chiudi questa finestra per fermarlo)")
        if not os.environ.get("ALINEA_NO_BROWSER"):
            threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="info" if WEB else "warning",
                proxy_headers=True, forwarded_allow_ips="*")
