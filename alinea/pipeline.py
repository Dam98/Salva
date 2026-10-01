"""Orchestrazione: CAD + disegno -> piano di controllo -> programma PC-DMIS."""
from __future__ import annotations

import os
from dataclasses import asdict
from typing import Callable

from . import geom as g
from .cad_features import FeatureSet, extract_features
from .control_plan import control_plan_csv
from .drawing_parser import Characteristic, parse_drawing_text
from .drawing_reader import DrawingText, read_drawing
from .matching import Plan, build_plan
from .pcdmis import Settings, generate
from .pcdmis_basic import build_basic
from .step_reader import read_step

Log = Callable[[str], None]

CAD_EXT = {".stp", ".step", ".stpz"}


def read_cad(cad_path: str, log: Log = print):
    log("Lettura del modello STEP…")
    model = read_step(cad_path)
    log(f"CAD: {len(model.faces)} facce ({model.surface_counts.get('PLANE', 0)} piani, "
        f"{model.surface_counts.get('CYLINDRICAL_SURFACE', 0)} cilindri), unità {model.unit}")
    fs = extract_features(model)
    log(f"Feature riconosciute: {sum(c.internal for c in fs.cylinders)} fori, "
        f"{sum(not c.internal for c in fs.cylinders)} perni, {len(fs.planes)} piani")
    return model, fs


def analyze(cad_path: str, drawing_path: str | None, config: dict, log: Log = print) -> dict:
    ext = os.path.splitext(cad_path)[1].lower()
    if ext == ".cad":
        raise ValueError("Il file .CAD è la cache interna di PC-DMIS (formato proprietario non documentato). "
                         "In PC-DMIS usa File > Esporta > Modello > STEP (AP214) e carica il .stp.")
    if ext not in CAD_EXT:
        raise ValueError(f"Formato CAD non supportato: {ext}. Esporta il modello in STEP (.stp/.step).")
    if ext == ".stpz":
        import gzip
        import tempfile

        with gzip.open(cad_path, "rb") as fh:
            data = fh.read()
        tmp = tempfile.NamedTemporaryFile(suffix=".stp", delete=False)
        tmp.write(data)
        tmp.close()
        cad_path = tmp.name

    model, fs = read_cad(cad_path, log)

    drawing = None
    if drawing_path:
        log("Lettura del disegno…")
        drawing = read_drawing(drawing_path, mode=config.get("reader_mode", "auto"),
                               llama_key=config.get("llama_api_key") or os.environ.get("LLAMA_CLOUD_API_KEY"),
                               llama_region=config.get("llama_region", "eu"),
                               llama_mode=config.get("llama_parse_mode", "parse_page_with_llm"), log=log)
    return analyze_parts(model, fs, drawing, config, log)


def analyze_parts(model, fs: FeatureSet, drawing: DrawingText | None, config: dict, log: Log = print) -> dict:
    """Seconda metà dell'analisi, con il testo del disegno già letto (dal server o dal browser)."""
    chars: list[Characteristic] = []
    info: dict = {"general_class": None, "datums": []}
    if drawing is None:
        drawing = DrawingText([], "nessuno", ["Nessun disegno caricato: si usa solo il CAD."])
    else:
        chars, info = parse_drawing_text(drawing.pages, config.get("general_class") or None,
                                         ocr=drawing.method in ("tesseract", "llamaparse"),
                                         layout=drawing.layout)
        log(f"Disegno ({drawing.method}): {len(chars)} caratteristiche lette")
    log("Associazione quote ↔ geometria CAD…")
    plan = build_plan(fs, chars, info.get("general_class"))
    log(f"Piano: {len(plan.items)} controlli, riferimenti "
        + ", ".join(f"{k}={v}" for k, v in sorted(plan.datums.items())))
    return {
        "cad": _cad_summary(model, fs),
        "drawing": {"method": drawing.method, "notes": drawing.notes, "pages": drawing.pages,
                    "page_count": drawing.page_count, "general_class": info.get("general_class"),
                    "datums": info.get("datums", [])},
        "characteristics": [c.to_dict() | {"label": c.label} for c in chars],
        "plan": plan.to_dict(),
        "_fs": fs,
    }


def _r(v, nd=4):
    return [round(c, nd) for c in v]


def _cad_summary(model, fs: FeatureSet) -> dict:
    return {
        "name": model.name, "unit": model.unit, "surface_counts": model.surface_counts,
        "bbox_min": _r(fs.bbox_min), "bbox_max": _r(fs.bbox_max), "warnings": fs.warnings,
        "cylinders": [{"id": c.id, "kind": c.kind, "diameter": round(c.diameter, 4), "axis": _r(c.axis),
                       "entry": _r(c.entry), "bottom": _r(c.bottom), "length": round(c.length, 3),
                       "through": c.through} for c in fs.cylinders],
        "planes": [{"id": p.id, "normal": _r(p.normal), "area": round(p.area, 1), "centroid": _r(p.centroid),
                    "extent": _r(p.extent, 2),
                    "outline": [[_r(q, 2) for q in loops[0]] for loops in p.loops]} for p in fs.planes],
        "patterns": [asdict(p) for p in fs.patterns],
    }


def make_program(fs: FeatureSet, plan_dict: dict, settings: dict) -> dict:
    plan = Plan.from_dict(plan_dict)
    known = {k: v for k, v in settings.items() if k in Settings.__dataclass_fields__}
    st = Settings(**known)
    prog = generate(fs, plan, st)
    csv_text = control_plan_csv(plan, prog.frame["names"], st.part_name)
    return {
        "program": prog.text, "csv": csv_text, "basic": build_basic(prog.ops, st.part_name, st.probe), "stats": prog.stats, "warnings": prog.warnings,
        "blocks": prog.blocks, "names": prog.frame["names"],
        "frame": {k: (_r(v) if isinstance(v, tuple) else v) for k, v in prog.frame.items() if k != "names"},
        "local": {c.id: _r(_to_local(prog.frame, c.entry), 3) for c in fs.cylinders}
        | {p.id: _r(_to_local(prog.frame, p.centroid), 3) for p in fs.planes},
    }


def _to_local(fr: dict, p):
    d = g.sub(p, fr["origin_cad"])
    return (g.dot(d, fr["x"]), g.dot(d, fr["y"]), g.dot(d, fr["z"]))
