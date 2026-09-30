"""Punti di ingresso per la versione nel browser (Pyodide).

Il JavaScript scrive i file caricati nel filesystem virtuale di Pyodide e chiama queste funzioni.
Tutti gli scambi avvengono in JSON (stringhe), così non dipendono dalla conversione di oggetti
tra JavaScript e Python.
"""
from __future__ import annotations

import json
import uuid

from .drawing_reader import DrawingText, pdf_text, text_is_usable
from .pipeline import analyze_parts, make_program, read_cad

_JOBS: dict[str, object] = {}   # id analisi -> FeatureSet (serve per rigenerare il programma)


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=list)


def pdf_text_layer(path: str) -> str:
    """Testo selezionabile del PDF e se è abbastanza leggibile da evitare l'OCR."""
    try:
        pages, count = pdf_text(path)
    except Exception as exc:  # noqa: BLE001 - PDF danneggiati o cifrati
        return _dumps({"pages": [], "page_count": 0, "usable": False, "error": str(exc)})
    return _dumps({"pages": pages, "page_count": count, "usable": text_is_usable(pages),
                   "has_text": bool("".join(pages).strip())})


def run_analysis(cad_path: str, drawing_json: str, config_json: str, log=print) -> str:
    """Analisi completa. `drawing_json` è null oppure {pages, method, notes, page_count, layout}."""
    cfg = json.loads(config_json or "{}")
    d = json.loads(drawing_json) if drawing_json else None
    drawing = None
    if d:
        layout = d.get("layout")
        drawing = DrawingText(pages=d.get("pages") or [], method=d.get("method") or "nessuno",
                              notes=d.get("notes") or [], page_count=d.get("page_count") or 0,
                              layout=[[tuple(b) for b in page] for page in layout] if layout else None)
    model, fs = read_cad(cad_path, log)
    res = analyze_parts(model, fs, drawing, cfg, log)
    job = uuid.uuid4().hex
    _JOBS[job] = res.pop("_fs")
    res["job_id"] = job
    return _dumps(res)


def run_generate(job_id: str, plan_json: str, settings_json: str) -> str:
    fs = _JOBS.get(job_id)
    if fs is None:
        raise ValueError("Analisi non trovata: ricarica i file")
    return _dumps(make_program(fs, json.loads(plan_json), json.loads(settings_json or "{}")))
