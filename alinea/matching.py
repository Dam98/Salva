"""Associazione automatica: caratteristiche del disegno <-> geometria CAD, e scelta dei riferimenti."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from . import geom as g
from .cad_features import CylFeature, FeatureSet, PlaneFeature
from .drawing_parser import GDT_LABELS, Characteristic
from .iso_tolerances import COARSE_PITCH, general_tolerance

# tipi di controllo che il generatore sa scrivere
CHECKS = ["diameter", "position", "distance", "flatness", "perpendicularity", "parallelism",
          "cylindricity", "circularity", "concentricity", "manual"]


@dataclass
class PlanItem:
    id: str
    label: str
    check: str                           # uno di CHECKS
    features: list[str] = field(default_factory=list)   # feature CAD misurate
    ref_feature: str | None = None       # seconda feature (distanza, parallelismo, coassialità)
    nominal: float | None = None
    upper: float | None = None
    lower: float | None = None
    datums: list[str] = field(default_factory=list)
    modifier: str | None = None
    diameter_zone: bool = False
    char_id: str | None = None           # caratteristica del disegno di origine
    status: str = "associato"            # associato | assunto | solo CAD | non associato
    tolerance_source: str = "disegno"
    enabled: bool = True
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Plan:
    items: list[PlanItem]
    datums: dict[str, str]               # lettera -> id feature CAD
    datum_candidates: dict[str, list[str]]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"items": [i.to_dict() for i in self.items], "datums": self.datums,
                "datum_candidates": self.datum_candidates, "warnings": self.warnings}

    @staticmethod
    def from_dict(d: dict) -> "Plan":
        return Plan(items=[PlanItem(**i) for i in d.get("items", [])], datums=dict(d.get("datums", {})),
                    datum_candidates=d.get("datum_candidates", {}), warnings=list(d.get("warnings", [])))


# --------------------------------------------------------------------------- riferimenti

def choose_datums(fs: FeatureSet) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Riferimenti di default A/B/C: piano principale + due piani perpendicolari (3-2-1)."""
    planes = sorted(fs.planes, key=lambda p: -p.area)
    cand_a = [p.id for p in planes if p.normal[2] > -0.5]  # la faccia appoggiata sul piano non è tastabile
    if not planes:
        return {}, {"A": [], "B": [], "C": []}
    maxa = planes[0].area
    top = [p for p in planes if p.area >= 0.9 * maxa]
    a = max(top, key=lambda p: (p.normal[2], p.area))
    datums = {"A": a.id}

    def rank(p: PlaneFeature, pref: g.Vec) -> tuple:
        return (round(p.area / maxa, 1), g.dot(p.normal, pref), p.area)

    perp_a = [p for p in planes if g.perpendicular(p.normal, a.normal, 1e-3)]
    if perp_a:
        b = max(perp_a, key=lambda p: rank(p, (0, -1, 0)))
        datums["B"] = b.id
        perp_ab = [p for p in perp_a if g.perpendicular(p.normal, b.normal, 1e-3)]
        if perp_ab:
            c = max(perp_ab, key=lambda p: rank(p, (-1, 0, 0)))
            datums["C"] = c.id
    holes_par_a = [c.id for c in fs.cylinders if g.parallel(c.axis, a.normal, 1e-3)]
    cands = {
        "A": cand_a or [p.id for p in planes],
        "B": [p.id for p in perp_a] + holes_par_a,
        "C": [p.id for p in perp_a] + holes_par_a,
    }
    return datums, cands


# --------------------------------------------------------------------------- associazione

def _hole_groups(fs: FeatureSet) -> list[list[CylFeature]]:
    groups: list[list[CylFeature]] = []
    for c in fs.cylinders:
        for grp in groups:
            h = grp[0]
            if h.internal == c.internal and abs(h.diameter - c.diameter) < 1e-3 and g.same_dir(h.axis, c.axis, 1e-4):
                grp.append(c)
                break
        else:
            groups.append([c])
    return groups


def _tol_span(ch: Characteristic) -> tuple[float, float]:
    up = ch.upper if ch.upper is not None else 0.0
    lo = ch.lower if ch.lower is not None else 0.0
    return up, lo


def _diam_score(ch: Characteristic, d: float) -> float | None:
    nom = ch.nominal or 0.0
    up, lo = _tol_span(ch)
    slack = max(0.02, 0.002 * nom)
    if nom + lo - slack <= d <= nom + up + slack:
        return abs(d - (nom + (up + lo) / 2))
    return None


def _thread_score(ch: Characteristic, d: float) -> float | None:
    nom = ch.nominal or 0.0
    pitch = COARSE_PITCH.get(nom) or COARSE_PITCH.get(int(nom), nom * 0.15)
    if ch.thread and "x" in ch.thread:
        try:
            pitch = float(ch.thread.split("x")[1].split("-")[0])
        except ValueError:
            pass
    options = [nom, nom - pitch, nom - 1.0825 * pitch]
    best = min(abs(d - o) for o in options)
    return best if best < 0.25 else None


def build_plan(fs: FeatureSet, chars: list[Characteristic], general_class: str | None = None) -> Plan:
    datums, cands = choose_datums(fs)
    items: list[PlanItem] = []
    warnings: list[str] = []
    groups = _hole_groups(fs)
    used_groups: set[int] = set()
    char_feats: dict[str, list[str]] = {}

    def new_id() -> str:
        return f"M{len(items) + 1}"

    # 1) diametri e filetti -> gruppi di cilindri
    dim_chars = [c for c in chars if c.kind in ("diameter", "thread")]
    dim_chars.sort(key=lambda c: (-c.count, -(c.nominal or 0)))
    for ch in dim_chars:
        scorer = _thread_score if ch.kind == "thread" else _diam_score
        best = None
        for gi, grp in enumerate(groups):
            s = scorer(ch, grp[0].diameter)
            if s is None:
                continue
            penalty = 0.0 if len(grp) == ch.count else (0.5 if len(grp) > ch.count else 2.0)
            penalty += 5.0 if gi in used_groups else 0.0
            key = s + penalty
            if best is None or key < best[0]:
                best = (key, gi)
        if best is None:
            items.append(PlanItem(id=new_id(), label=ch.label, check="diameter" if ch.kind == "diameter" else "position",
                                  nominal=ch.nominal, upper=ch.upper, lower=ch.lower, char_id=ch.id,
                                  status="non associato", enabled=False, tolerance_source=ch.tolerance_source,
                                  notes=ch.notes + ["Nessuna geometria CAD compatibile: associare a mano"]))
            continue
        gi = best[1]
        grp = groups[gi]
        used_groups.add(gi)
        feats = [c.id for c in grp]
        char_feats[ch.id] = feats
        notes = list(ch.notes)
        if len(grp) != ch.count:
            notes.append(f"Il disegno indica {ch.count}×, nel CAD ce ne sono {len(grp)}: associati tutti")
        if ch.kind == "thread":
            items.append(PlanItem(id=new_id(), label=ch.label + " (posizione)", check="position", features=feats,
                                  nominal=grp[0].diameter, char_id=ch.id, status="associato",
                                  tolerance_source="filetto", datums=[k for k in ("A", "B", "C") if k in datums],
                                  upper=0.2, lower=0.0, notes=notes + [
                                      "Filetto: misurata la posizione del foro; il filetto va verificato con "
                                      "tampone passa/non passa. Tolleranza di posizione assunta Ø0.2"]))
        else:
            items.append(PlanItem(id=new_id(), label=ch.label, check="diameter", features=feats,
                                  nominal=ch.nominal, upper=ch.upper, lower=ch.lower, char_id=ch.id,
                                  status="associato" if ch.tolerance_source != "mancante" else "assunto",
                                  tolerance_source=ch.tolerance_source, notes=notes))

    # 2) GD&T
    for ch in [c for c in chars if c.kind == "gdt"]:
        feats = char_feats.get(ch.parent or "", [])
        status = "associato"
        notes = list(ch.notes)
        check = ch.gdt if ch.gdt in CHECKS else "manual"
        if ch.gdt == "unknown":
            status = "assunto"
        if ch.gdt in ("profile_surface", "profile_line", "runout", "total_runout", "symmetry", "angularity"):
            check = "manual"
            notes.append(f"{GDT_LABELS.get(ch.gdt or '', ch.gdt)}: da programmare manualmente in PC-DMIS")
        if check == "concentricity":
            pass
        if not feats:
            if ch.gdt == "flatness" and "A" in datums:
                feats = [datums["A"]]
                status = "assunto"
                notes.append("Planarità senza quota di aggancio: assegnata al riferimento A")
            elif ch.gdt in ("perpendicularity", "parallelism") and fs.cylinders:
                # tipico: perpendicolarità del foro principale rispetto ad A
                big = max(fs.cylinders, key=lambda c: c.diameter)
                feats = [big.id]
                status = "assunto"
                notes.append(f"Nessuna quota di aggancio letta: assegnata al foro più grande ({big.id})")
            else:
                status = "non associato"
                notes.append("Feature di aggancio non determinata: sceglierla nella revisione")
        ref = None
        if check in ("perpendicularity", "parallelism", "concentricity") and ch.datums:
            ref = datums.get(ch.datums[0])
        items.append(PlanItem(id=new_id(), label=ch.label, check=check, features=feats, ref_feature=ref,
                              nominal=0.0, upper=ch.gdt_value, lower=0.0, datums=ch.datums,
                              modifier=ch.modifier, diameter_zone=ch.gdt_diameter_zone, char_id=ch.id,
                              status=status, enabled=(status != "non associato" and check != "manual"),
                              tolerance_source="disegno", notes=notes))

    # 3) quote lineari -> distanze piano/piano o asse/piano
    datum_ids = set(datums.values())
    char_feats_all = {f for fl in char_feats.values() for f in fl}
    for ch in [c for c in chars if c.kind in ("linear", "radius")]:
        if ch.kind == "radius":
            items.append(PlanItem(id=new_id(), label=ch.label, check="manual", nominal=ch.nominal, upper=ch.upper,
                                  lower=ch.lower, char_id=ch.id, status="non associato", enabled=False,
                                  notes=["Raggi: da misurare con scansione/arco, non generati automaticamente"]))
            continue
        # una quota senza Ø ma con accoppiamento può essere un diametro (es. albero "25 g6")
        if ch.fit:
            grp_match = [grp for grp in groups if _diam_score(ch, grp[0].diameter) is not None]
            if grp_match:
                feats = [c.id for c in grp_match[0]]
                items.append(PlanItem(id=new_id(), label="Ø" + ch.label, check="diameter", features=feats,
                                      nominal=ch.nominal, upper=ch.upper, lower=ch.lower, char_id=ch.id,
                                      status="assunto", tolerance_source=ch.tolerance_source,
                                      notes=["Quota con accoppiamento senza simbolo Ø: interpretata come diametro"]))
                continue
        up, lo = _tol_span(ch)
        nom = ch.nominal or 0.0
        slack = max(0.005, 0.25 * (up - lo))
        # il CAD può essere modellato al nominale oppure a metà tolleranza
        cands_d = [d for d in fs.distances
                   if nom + lo - slack <= d.value <= nom + up + slack or abs(d.value - nom) < 0.005]
        if not cands_d:
            # nessuna distanza: forse è un diametro con il simbolo Ø perso dall'OCR ("8 +0.1/0 PROF. 30")
            grp_match = [grp for grp in groups if _diam_score(ch, grp[0].diameter) is not None
                         and not any(c.id in char_feats_all for c in grp)]
            if grp_match:
                feats = [c.id for c in grp_match[0]]
                char_feats_all.update(feats)
                items.append(PlanItem(id=new_id(), label="Ø" + ch.label, check="diameter", features=feats,
                                      nominal=nom, upper=up, lower=lo, char_id=ch.id, status="assunto",
                                      tolerance_source=ch.tolerance_source,
                                      notes=["Quota senza simbolo Ø uguale al diametro di un foro del CAD: "
                                             "interpretata come diametro"]))
                continue
            items.append(PlanItem(id=new_id(), label=ch.label, check="distance", nominal=nom, upper=up, lower=lo,
                                  char_id=ch.id, status="non associato", enabled=False,
                                  notes=["Nessuna distanza CAD corrispondente: associare a mano"]))
            continue

        def unreachable(fid: str) -> bool:
            f = fs.by_id(fid)
            v = f.normal if isinstance(f, PlaneFeature) else f.axis
            return v[2] < -0.5  # rivolta verso il basso: il pezzo ci appoggia sopra

        def drank(d):
            return (-(d.a in datum_ids) - (d.b in datum_ids), d.kind != "plane-plane",
                    unreachable(d.a) + unreachable(d.b), abs(d.value - nom))

        cands_d.sort(key=drank)
        best = cands_d[0]
        notes = []
        if unreachable(best.a) or unreachable(best.b):
            notes.append("Una delle due facce è rivolta verso il basso: serve riposizionare il pezzo")
        same = [d for d in cands_d if abs(d.value - best.value) < 1e-3 and drank(d)[:2] == drank(best)[:2]]
        if len(same) > 1:
            notes.append(f"Ambigua: {len(same)} coppie di feature a questa distanza; scelta {best.a}–{best.b}")
        items.append(PlanItem(id=new_id(), label=ch.label, check="distance", features=[best.a], ref_feature=best.b,
                              nominal=nom, upper=up, lower=lo, char_id=ch.id,
                              status="associato" if len(same) == 1 else "assunto", notes=notes))

    # 4) fori del CAD non quotati nel disegno: diametro con tolleranza generale
    assigned = {f for it in items for f in it.features}
    for grp in groups:
        if any(c.id in assigned for c in grp):
            continue
        d = grp[0].diameter
        t = general_tolerance(d, general_class or "m") or 0.1
        label = (f"{len(grp)}× " if len(grp) > 1 else "") + f"Ø{d:.3f}".rstrip("0").rstrip(".")
        items.append(PlanItem(id=new_id(), label=label, check="diameter", features=[c.id for c in grp], nominal=d,
                              upper=t, lower=-t, status="solo CAD",
                              tolerance_source=f"generale ISO 2768-{general_class or 'm'}",
                              notes=["Foro presente nel CAD ma non trovato nel disegno"]))

    if not chars:
        warnings.append("Nessuna quota letta dal disegno: il programma misura la geometria del CAD con "
                        "tolleranze generali.")
    return Plan(items=items, datums=datums, datum_candidates=cands, warnings=warnings)
