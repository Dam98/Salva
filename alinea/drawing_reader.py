"""Lettura del disegno tecnico: livello testo del PDF, LlamaParse (OCR cloud) o Tesseract (OCR locale).

Strategia "auto":
1. PDF con testo selezionabile e leggibile  -> pypdf (gratis, esatto)
2. scansione / immagine / testo illeggibile -> LlamaParse se c'è la chiave API
3. altrimenti                               -> Tesseract se installato
"""
from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass, field
from typing import Callable

from .drawing_parser import text_quality

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
LLAMA_BASE = {"us": "https://api.cloud.llamaindex.ai", "eu": "https://api.cloud.eu.llamaindex.ai"}

Log = Callable[[str], None]


@dataclass
class DrawingText:
    pages: list[str]
    method: str                     # pdf-text | llamaparse | tesseract | nessuno
    notes: list[str] = field(default_factory=list)
    page_count: int = 0
    # per pagina, il riquadro (x0, y0, x1, y1) di ogni riga di testo (stesso ordine delle righe), se noto
    layout: list[list[tuple[float, float, float, float]]] | None = None


class ReaderError(RuntimeError):
    pass


# --------------------------------------------------------------------------- PDF testo

def pdf_text(path: str, max_pages: int = 10) -> tuple[list[str], int]:
    from pypdf import PdfReader

    r = PdfReader(path)
    pages = []
    for i, p in enumerate(r.pages):
        if i >= max_pages:
            break
        try:
            pages.append(p.extract_text() or "")
        except Exception:  # noqa: BLE001 - pdf malformati
            pages.append("")
    return pages, len(r.pages)


def text_is_usable(pages: list[str]) -> bool:
    content = "".join(pages)
    stripped = "".join(content.split())
    if len(stripped) < 20:
        return False
    digits = sum(c.isdigit() for c in stripped)
    return text_quality(content) > 0.7 and digits >= 5


# --------------------------------------------------------------------------- LlamaParse

def llamaparse(path: str, api_key: str, region: str = "eu", log: Log = print,
               timeout_s: int = 300, language: str = "it", parse_mode: str = "parse_page_with_llm",
               max_pages: int = 4) -> list[str]:
    """Carica il file su LlamaParse e restituisce il testo (markdown) pagina per pagina."""
    import httpx

    base = LLAMA_BASE.get(region, LLAMA_BASE["eu"])
    headers = {"Authorization": f"Bearer {api_key}", "accept": "application/json"}
    with httpx.Client(timeout=60) as cli:
        with open(path, "rb") as fh:
            files = {"file": (os.path.basename(path), fh)}
            data = {
                "language": language,
                "parse_mode": parse_mode,
                "high_res_ocr": "true",
                "max_pages": str(max_pages),
                # istruzioni per l'OCR: le quote sono il contenuto importante
                "user_prompt": ("Technical engineering drawing. Transcribe every dimension, tolerance, "
                                "fit (e.g. H7), thread, diameter symbol Ø and GD&T feature control frame "
                                "(write frames as |symbol|tolerance|datum|datum|). Keep one callout per line."),
            }
            r = cli.post(f"{base}/api/v1/parsing/upload", headers=headers, files=files, data=data)
        if r.status_code == 401:
            raise ReaderError("LlamaParse: chiave API non valida (401)")
        if r.status_code >= 400:
            raise ReaderError(f"LlamaParse: caricamento rifiutato ({r.status_code}) {r.text[:200]}")
        job = r.json().get("id")
        if not job:
            raise ReaderError("LlamaParse: risposta senza id del job")
        log(f"LlamaParse: job {job} in elaborazione…")
        t0 = time.time()
        while True:
            s = cli.get(f"{base}/api/v1/parsing/job/{job}", headers=headers)
            st = (s.json().get("status") or "").upper() if s.status_code == 200 else ""
            if st in ("SUCCESS", "PARTIAL_SUCCESS"):
                break
            if st in ("ERROR", "CANCELED", "CANCELLED"):
                raise ReaderError(f"LlamaParse: il job è terminato con stato {st}")
            if time.time() - t0 > timeout_s:
                raise ReaderError("LlamaParse: tempo scaduto")
            time.sleep(2)
        res = cli.get(f"{base}/api/v1/parsing/job/{job}/result/json", headers=headers)
        if res.status_code == 200:
            pages = [p.get("md") or p.get("text") or "" for p in res.json().get("pages", [])]
            if any(p.strip() for p in pages):
                return pages
        res = cli.get(f"{base}/api/v1/parsing/job/{job}/result/markdown", headers=headers)
        if res.status_code != 200:
            raise ReaderError(f"LlamaParse: risultato non disponibile ({res.status_code})")
        md = res.json().get("markdown", "")
        return [p for p in md.split("\n---\n")] or [md]


# --------------------------------------------------------------------------- Tesseract

def tesseract_available() -> bool:
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    cmd = os.environ.get("TESSERACT_CMD")
    if cmd and os.path.exists(cmd):
        return True
    if shutil.which("tesseract"):
        return True
    return os.path.exists(r"C:\Program Files\Tesseract-OCR\tesseract.exe")


def _render_pages(path: str, max_pages: int) -> list:
    ext = os.path.splitext(path)[1].lower()
    from PIL import Image

    if ext in IMAGE_EXT:
        img = Image.open(path)
        frames = []
        try:
            for i in range(max_pages):
                img.seek(i)
                frames.append(img.convert("L").copy())
        except EOFError:
            pass
        return frames
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(path)
    out = []
    for i in range(min(len(pdf), max_pages)):
        page = pdf[i]
        w, h = page.get_size()
        scale = 3000 / max(w, h)  # ~3000 px sul lato lungo
        out.append(page.render(scale=scale).to_pil().convert("L"))
    return out


def tesseract(path: str, max_pages: int = 4, log: Log = print) -> tuple[list[str], list[list[tuple]]]:
    """OCR con Tesseract. Restituisce il testo (un frammento per riga) e il riquadro di ogni riga."""
    import pytesseract

    cmd = os.environ.get("TESSERACT_CMD")
    if not cmd and not shutil.which("tesseract"):
        win = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        if os.path.exists(win):
            cmd = win
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    langs = pytesseract.get_languages(config="")
    lang = "+".join(l for l in ("ita", "eng") if l in langs) or None
    pages, layouts = [], []
    for i, img in enumerate(_render_pages(path, max_pages), 1):
        log(f"Tesseract: pagina {i}…")
        # psm 11: testo sparso, adatto ai disegni (le quote sono sparse sul foglio)
        d = pytesseract.image_to_data(img, lang=lang, config="--psm 11", output_type=pytesseract.Output.DICT)
        frags: dict[tuple, list[int]] = {}
        for k, txt in enumerate(d["text"]):
            if txt.strip():
                frags.setdefault((d["block_num"][k], d["par_num"][k], d["line_num"][k]), []).append(k)
        rows = []
        for idx in frags.values():
            x0 = min(d["left"][k] for k in idx)
            y0 = min(d["top"][k] for k in idx)
            x1 = max(d["left"][k] + d["width"][k] for k in idx)
            y1 = max(d["top"][k] + d["height"][k] for k in idx)
            text = " ".join(d["text"][k] for k in sorted(idx, key=lambda k: d["left"][k]))
            rows.append((y0, x0, text, (x0, y0, x1, y1)))
        rows.sort()
        pages.append("\n".join(r[2] for r in rows))
        layouts.append([r[3] for r in rows])
    return pages, layouts


# --------------------------------------------------------------------------- orchestrazione

def read_drawing(path: str, mode: str = "auto", llama_key: str | None = None, llama_region: str = "eu",
                 log: Log = print, llama_mode: str = "parse_page_with_llm") -> DrawingText:
    ext = os.path.splitext(path)[1].lower()
    notes: list[str] = []
    page_count = 0
    if ext == ".pdf" and mode in ("auto", "pdf"):
        try:
            pages, page_count = pdf_text(path)
            if text_is_usable(pages):
                log(f"PDF vettoriale: testo selezionabile letto da {len(pages)} pagine")
                return DrawingText(pages, "pdf-text", notes, page_count)
            if mode == "pdf":
                notes.append("Il PDF non ha un livello di testo leggibile.")
                return DrawingText(pages, "pdf-text", notes, page_count)
            if "".join(pages).strip():
                notes.append("Il PDF ha testo ma illeggibile (font simbolici): uso l'OCR sull'immagine.")
            else:
                notes.append("Il PDF non ha livello di testo (scansione): uso l'OCR.")
            log(notes[-1])
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Lettura testo PDF fallita ({exc}); provo con l'OCR.")
    elif ext not in IMAGE_EXT and ext != ".pdf":
        raise ReaderError(f"Formato disegno non supportato: {ext} (usa PDF o immagine PNG/JPG/TIF)")

    errors = []
    if mode in ("auto", "llamaparse") and llama_key:
        try:
            log("Invio a LlamaParse (OCR)…")
            pages = llamaparse(path, llama_key, llama_region, log, parse_mode=llama_mode)
            return DrawingText(pages, "llamaparse", notes, page_count or len(pages))
        except Exception as exc:  # noqa: BLE001 - ReaderError o errori di rete di httpx
            errors.append(str(exc))
            notes.append(f"{exc}")
            log(str(exc))
    elif mode == "llamaparse":
        errors.append("Chiave LlamaParse non impostata")

    if mode in ("auto", "tesseract") and tesseract_available():
        try:
            log("OCR locale con Tesseract…")
            pages, layout = tesseract(path, log=log)
            notes.append("Letto con Tesseract (OCR locale): i simboli GD&T possono essere persi, verificare.")
            return DrawingText(pages, "tesseract", notes, page_count or len(pages), layout)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Tesseract: {exc}")
            notes.append(f"Tesseract: {exc}")

    if not llama_key and not tesseract_available():
        notes.append("Nessun OCR disponibile: imposta la chiave LlamaParse nelle Impostazioni "
                     "(gratuita su cloud.llamaindex.ai) oppure installa Tesseract.")
    return DrawingText([], "nessuno", notes, page_count)
