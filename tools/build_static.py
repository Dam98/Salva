"""Costruisce la versione di Alinea che gira interamente nel browser (sito statico).

    python tools/build_static.py [cartella_uscita]      # default: dist/

Il risultato si pubblica così com'è su qualsiasi hosting statico (Hugging Face Space statico,
GitHub Pages, Netlify...) oppure si prova in locale con:  python -m http.server -d dist 8000
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "alinea"
# moduli Python che servono nel browser (il server FastAPI e __main__ restano fuori)
PY_MODULES = ["__init__", "geom", "step_reader", "cad_features", "iso_tolerances", "drawing_parser",
              "drawing_reader", "matching", "pcdmis", "control_plan", "pipeline", "browser"]
WHEELS = ["pypdf"]            # librerie pure-Python installate con micropip
EXAMPLES = ["staffa.stp", "staffa_disegno.pdf", "staffa_scansione.pdf"]


def build(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    (out / "static").mkdir(parents=True)
    (out / "py" / "alinea").mkdir(parents=True)
    (out / "esempi").mkdir()

    shutil.copy(PKG / "static" / "index.html", out / "index.html")
    for f in (PKG / "static").iterdir():
        if f.name not in ("index.html", "login.html", "mode.js") and f.is_file():
            shutil.copy(f, out / "static" / f.name)
    (out / "static" / "mode.js").write_text("window.ALINEA_BROWSER = true;\n", encoding="utf-8")

    files = []
    for m in PY_MODULES:
        shutil.copy(PKG / f"{m}.py", out / "py" / "alinea" / f"{m}.py")
        files.append(f"alinea/{m}.py")

    wheels = []
    subprocess.run([sys.executable, "-m", "pip", "download", "--no-deps", "--only-binary=:all:",
                    "--dest", str(out / "py"), *WHEELS], check=True, stdout=subprocess.DEVNULL)
    for w in sorted((out / "py").glob("*.whl")):
        wheels.append(w.name)
    (out / "py" / "manifest.json").write_text(json.dumps({"files": files, "wheels": wheels}, indent=1),
                                              encoding="utf-8")

    for e in EXAMPLES:
        shutil.copy(ROOT / "esempi" / e, out / "esempi" / e)
    shutil.copy(ROOT / "LICENSE.md", out / "LICENSE.md")
    print(f"Sito statico pronto in {out} ({len(files)} moduli Python, wheel: {', '.join(wheels)})")


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist")
