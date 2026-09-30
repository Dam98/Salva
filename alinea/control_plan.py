"""Piano di controllo in CSV (separatore ';' per Excel in italiano)."""
from __future__ import annotations

import csv
import io

from .matching import Plan

CHECK_LABELS = {
    "diameter": "Diametro", "position": "Localizzazione", "distance": "Distanza", "flatness": "Planarità",
    "perpendicularity": "Perpendicolarità", "parallelism": "Parallelismo", "cylindricity": "Cilindricità",
    "circularity": "Circolarità", "concentricity": "Coassialità", "manual": "Manuale",
}


def _num(x: float | None) -> str:
    return "" if x is None else f"{x:.4f}".rstrip("0").rstrip(".").replace(".", ",")


def control_plan_csv(plan: Plan, names: dict[str, str], part: str) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(["Pezzo", part])
    w.writerow(["Riferimenti"] + [f"{k}={names.get(v, v)}" for k, v in sorted(plan.datums.items())])
    w.writerow([])
    w.writerow(["N.", "Caratteristica", "Controllo", "Nominale", "Toll. sup.", "Toll. inf.", "Min", "Max",
                "Riferimenti", "Feature CAD", "Feature PC-DMIS", "Origine tolleranza", "Associazione",
                "Incluso", "Note"])
    for it in plan.items:
        nom = it.nominal
        mn = mx = None
        if nom is not None and it.upper is not None:
            mx = nom + it.upper
            mn = nom + (it.lower or 0.0)
        w.writerow([it.id, it.label, CHECK_LABELS.get(it.check, it.check), _num(nom), _num(it.upper),
                    _num(it.lower), _num(mn), _num(mx), "|".join(it.datums), " ".join(it.features),
                    " ".join(names.get(f, "") for f in it.features), it.tolerance_source, it.status,
                    "sì" if it.enabled else "no", " / ".join(it.notes)])
    return "﻿" + buf.getvalue()  # BOM: Excel riconosce l'UTF-8
