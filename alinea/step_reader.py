"""Lettore STEP (ISO 10303-21, AP203/AP214/AP242) in Python puro.

Legge la topologia B-rep (ADVANCED_FACE -> loop -> edge -> vertex) e le superfici
analitiche che servono in metrologia: piani, cilindri, coni. Non è un kernel CAD
completo: le superfici B-spline vengono contate ma non usate per la misura.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from . import geom as g
from .geom import Vec


# --------------------------------------------------------------------------- parser

class Ref(int):
    """Riferimento a un'entità: #123."""

    def __repr__(self) -> str:  # pragma: no cover - debug
        return f"#{int(self)}"


class Enum(str):
    """Valore enumerativo: .T. .F. .MILLI. ..."""


_TOKEN = re.compile(
    r"""'(?:[^']|'')*'            # stringa
    |\#\d+                        # riferimento
    |\.[A-Z_][A-Z_0-9]*\.         # enum
    |[-+]?(?:\d+\.?\d*|\.\d+)(?:[Ee][-+]?\d+)?   # numero
    |"[0-9A-Fa-f]*"               # binario
    |[A-Za-z_][A-Za-z_0-9]*       # parola chiave
    |[(),$*]
    """,
    re.VERBOSE,
)


def _parse_list(tokens: list[str], i: int):
    """tokens[i] == '(' -> (lista, indice dopo ')')"""
    assert tokens[i] == "("
    i += 1
    out = []
    while i < len(tokens):
        t = tokens[i]
        if t == ")":
            return out, i + 1
        if t == ",":
            i += 1
            continue
        if t == "(":
            val, i = _parse_list(tokens, i)
            out.append(val)
            continue
        if t[0] == "'":
            out.append(t[1:-1].replace("''", "'"))
        elif t[0] == "#":
            out.append(Ref(int(t[1:])))
        elif t[0] == "." and t[-1] == "." and len(t) > 2 and t[1].isalpha():
            out.append(Enum(t[1:-1]))
        elif t == "$":
            out.append(None)
        elif t == "*":
            out.append("*")
        elif t[0] == '"':
            out.append(t)
        elif t[0].isalpha() or t[0] == "_":
            # parametro tipizzato, es. LENGTH_MEASURE(1.0)
            if i + 1 < len(tokens) and tokens[i + 1] == "(":
                val, i = _parse_list(tokens, i + 1)
                out.append((t.upper(), val))
                continue
            out.append(Enum(t))
        else:
            out.append(float(t))
        i += 1
    raise ValueError("parentesi non bilanciate")


@dataclass
class Entity:
    id: int
    type: str                      # tipo principale (per entità complesse: il primo)
    args: list
    parts: dict[str, list] = field(default_factory=dict)  # per entità complesse


def _split_statements(data: str):
    """Divide la sezione DATA in istruzioni '#id=...;' rispettando le stringhe."""
    start = 0
    in_str = False
    i = 0
    n = len(data)
    while i < n:
        c = data[i]
        if c == "'":
            in_str = not in_str
        elif c == ";" and not in_str:
            yield data[start:i]
            start = i + 1
        i += 1


def parse_step(text: str) -> dict[int, Entity]:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    m = re.search(r"\bDATA\b[^;]*;", text)
    if not m:
        raise ValueError("File STEP non valido: sezione DATA mancante")
    end = text.find("ENDSEC", m.end())
    data = text[m.end(): end if end > 0 else len(text)]
    ents: dict[int, Entity] = {}
    for st in _split_statements(data):
        st = st.strip()
        if not st.startswith("#"):
            continue
        eq = st.find("=")
        if eq < 0:
            continue
        try:
            eid = int(st[1:eq].strip())
        except ValueError:
            continue
        body = st[eq + 1:].strip()
        tokens = _TOKEN.findall(body)
        if not tokens:
            continue
        try:
            if tokens[0] == "(":
                # entità complessa: (A(...) B(...) ...)
                parts: dict[str, list] = {}
                i = 1
                first = None
                while i < len(tokens) and tokens[i] != ")":
                    name = tokens[i].upper()
                    args, i = _parse_list(tokens, i + 1)
                    parts[name] = args
                    first = first or name
                ents[eid] = Entity(eid, first or "", [], parts)
            else:
                args, _ = _parse_list(tokens, 1)
                ents[eid] = Entity(eid, tokens[0].upper(), args)
        except (ValueError, AssertionError, IndexError):
            continue
    return ents


# --------------------------------------------------------------------------- modello

@dataclass
class Face:
    id: int
    kind: str                  # plane | cylinder | cone | other
    same_sense: bool
    origin: Vec = (0.0, 0.0, 0.0)
    axis: Vec = (0.0, 0.0, 1.0)      # normale del piano / asse del cilindro (della superficie)
    ref_dir: Vec = (1.0, 0.0, 0.0)
    radius: float = 0.0
    semi_angle: float = 0.0
    surface_type: str = ""
    loops: list[list[Vec]] = field(default_factory=list)   # polilinee chiuse; loops[0] = esterno
    points: list[Vec] = field(default_factory=list)

    @property
    def outward_normal(self) -> Vec:
        """Per i piani: normale uscente dal materiale."""
        return self.axis if self.same_sense else g.neg(self.axis)


@dataclass
class CadModel:
    name: str
    unit: str
    scale: float                    # fattore verso mm
    faces: list[Face]
    solids: int
    surface_counts: dict[str, int]
    bbox_min: Vec
    bbox_max: Vec
    warnings: list[str] = field(default_factory=list)


class StepGeometry:
    def __init__(self, ents: dict[int, Entity]):
        self.e = ents
        self.scale = 1.0
        self.unit = "mm"

    # -- utility di accesso
    def get(self, ref) -> Entity | None:
        if isinstance(ref, int):
            return self.e.get(int(ref))
        return None

    def point(self, ref) -> Vec:
        ent = self.get(ref)
        if ent is None:
            return (0.0, 0.0, 0.0)
        if ent.type == "VERTEX_POINT":
            return self.point(ent.args[1])
        c = ent.args[1]
        c = list(c) + [0.0] * (3 - len(c))
        s = self.scale
        return (float(c[0]) * s, float(c[1]) * s, float(c[2]) * s)

    def direction(self, ref, default: Vec = (0.0, 0.0, 1.0)) -> Vec:
        ent = self.get(ref)
        if ent is None:
            return default
        c = list(ent.args[1]) + [0.0] * 3
        return g.unit((float(c[0]), float(c[1]), float(c[2])))

    def placement(self, ref) -> tuple[Vec, Vec, Vec]:
        ent = self.get(ref)
        if ent is None:
            return (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)
        loc = self.point(ent.args[1])
        axis = self.direction(ent.args[2]) if len(ent.args) > 2 and ent.args[2] is not None else (0.0, 0.0, 1.0)
        if len(ent.args) > 3 and ent.args[3] is not None:
            rd = self.direction(ent.args[3], (1.0, 0.0, 0.0))
        else:
            rd = g.any_perpendicular(axis)
        # ortogonalizza ref_dir
        rd = g.unit(g.sub(rd, g.mul(axis, g.dot(rd, axis))))
        return loc, axis, rd

    # -- unità
    def detect_units(self) -> None:
        for ent in self.e.values():
            if ent.parts and "LENGTH_UNIT" in ent.parts:
                if "SI_UNIT" in ent.parts:
                    prefix, name = ent.parts["SI_UNIT"][0], ent.parts["SI_UNIT"][1]
                    if str(name).upper() == "METRE":
                        f = {"MILLI": 1.0, "CENTI": 10.0, "DECI": 100.0, None: 1000.0, "MICRO": 0.001}.get(
                            str(prefix).upper() if prefix else None, 1.0)
                        self.scale, self.unit = f, {1.0: "mm", 10.0: "cm", 1000.0: "m", 0.001: "µm"}.get(f, "mm")
                        return
                if "CONVERSION_BASED_UNIT" in ent.parts:
                    nm = str(ent.parts["CONVERSION_BASED_UNIT"][0]).upper()
                    if "INCH" in nm:
                        self.scale, self.unit = 25.4, "inch"
                        return
                    if "FOOT" in nm:
                        self.scale, self.unit = 304.8, "foot"
                        return

    # -- curve e loop
    def edge_polyline(self, edge_curve: Entity, forward: bool) -> list[Vec]:
        a = self.point(edge_curve.args[1])
        b = self.point(edge_curve.args[2])
        curve = self.get(edge_curve.args[3])
        sense = bool(edge_curve.args[4] == "T") if len(edge_curve.args) > 4 else True
        pts: list[Vec]
        # curve di superficie: prendi la curva 3D
        while curve is not None and curve.type in ("SURFACE_CURVE", "SEAM_CURVE", "INTERSECTION_CURVE"):
            curve = self.get(curve.args[1])
        if curve is not None and curve.type == "CIRCLE":
            c, ax, rd = self.placement(curve.args[1])
            r = float(curve.args[2]) * self.scale
            yd = g.cross(ax, rd)

            def ang(p: Vec) -> float:
                d = g.sub(p, c)
                return math.atan2(g.dot(d, yd), g.dot(d, rd))

            t0, t1 = ang(a), ang(b)
            if not sense:
                t0, t1 = t1, t0
            span = (t1 - t0) % (2 * math.pi)
            if span < 1e-9:
                span = 2 * math.pi
            n = max(4, int(span / (math.pi / 16)))
            pts = []
            for k in range(n + 1):
                t = t0 + span * k / n
                pts.append(g.add(c, g.add(g.mul(rd, r * math.cos(t)), g.mul(yd, r * math.sin(t)))))
            if not sense:
                pts.reverse()
        else:
            pts = [a, b]
        if not forward:
            pts = list(reversed(pts))
        return pts

    def loop_points(self, bound: Entity) -> list[Vec]:
        loop = self.get(bound.args[1])
        if loop is None:
            return []
        if loop.type == "VERTEX_LOOP":
            return [self.point(loop.args[1])]
        if loop.type == "POLY_LOOP":
            return [self.point(r) for r in loop.args[1]]
        out: list[Vec] = []
        for oe_ref in loop.args[1] if len(loop.args) > 1 else []:
            oe = self.get(oe_ref)
            if oe is None:
                continue
            ec = self.get(oe.args[3])
            if ec is None or ec.type != "EDGE_CURVE":
                continue
            fwd = oe.args[4] == "T"
            poly = self.edge_polyline(ec, fwd)
            if out and poly and g.dist(out[-1], poly[0]) < 1e-6:
                poly = poly[1:]
            out.extend(poly)
        if len(out) > 1 and g.dist(out[0], out[-1]) < 1e-6:
            out.pop()
        orient = bound.args[2] == "T" if len(bound.args) > 2 else True
        if not orient:
            out.reverse()
        return out

    # -- facce
    def faces(self) -> tuple[list[Face], dict[str, int]]:
        faces: list[Face] = []
        counts: dict[str, int] = {}
        for ent in self.e.values():
            if ent.type not in ("ADVANCED_FACE", "FACE_SURFACE"):
                continue
            bounds_refs, surf_ref, ss = ent.args[1], ent.args[2], ent.args[3]
            surf = self.get(surf_ref)
            if surf is None:
                continue
            stype = surf.type or next(iter(surf.parts), "")
            counts[stype] = counts.get(stype, 0) + 1
            f = Face(id=ent.id, kind="other", same_sense=(ss == "T"), surface_type=stype)
            if stype == "PLANE":
                f.kind = "plane"
                f.origin, f.axis, f.ref_dir = self.placement(surf.args[1])
            elif stype == "CYLINDRICAL_SURFACE":
                f.kind = "cylinder"
                f.origin, f.axis, f.ref_dir = self.placement(surf.args[1])
                f.radius = float(surf.args[2]) * self.scale
            elif stype == "CONICAL_SURFACE":
                f.kind = "cone"
                f.origin, f.axis, f.ref_dir = self.placement(surf.args[1])
                f.radius = float(surf.args[2]) * self.scale
                f.semi_angle = float(surf.args[3])
            outer: list[Vec] | None = None
            inners: list[list[Vec]] = []
            for bref in bounds_refs:
                b = self.get(bref)
                if b is None:
                    continue
                pts = self.loop_points(b)
                if not pts:
                    continue
                if b.type == "FACE_OUTER_BOUND" and outer is None:
                    outer = pts
                else:
                    inners.append(pts)
            if outer is None and inners and f.kind == "plane":
                # nessun FACE_OUTER_BOUND esplicito: il loop di area maggiore è l'esterno
                inners.sort(key=lambda lp: abs(g.polygon_area_3d(lp, f.axis)), reverse=True)
                outer = inners.pop(0)
            f.loops = ([outer] if outer else []) + inners
            f.points = [p for lp in f.loops for p in lp]
            faces.append(f)
        return faces, counts


def read_step(path: str, name: str | None = None) -> CadModel:
    with open(path, "r", encoding="latin-1", errors="replace") as fh:
        text = fh.read()
    return read_step_text(text, name or path)


def read_step_text(text: str, name: str = "pezzo") -> CadModel:
    if "ISO-10303-21" not in text[:2000]:
        raise ValueError("Il file non sembra uno STEP (manca l'intestazione ISO-10303-21)")
    ents = parse_step(text)
    sg = StepGeometry(ents)
    sg.detect_units()
    faces, counts = sg.faces()
    warnings: list[str] = []
    solids = sum(1 for e in ents.values() if e.type in ("MANIFOLD_SOLID_BREP", "BREP_WITH_VOIDS"))
    if solids > 1:
        warnings.append(f"Il file contiene {solids} solidi: vengono letti tutti nello stesso sistema di "
                        "riferimento (gli assiemi con trasformazioni non sono supportati).")
    if not faces:
        warnings.append("Nessuna faccia B-rep trovata: il file potrebbe contenere solo mesh o wireframe.")
    other = sum(v for k, v in counts.items() if k not in ("PLANE", "CYLINDRICAL_SURFACE", "CONICAL_SURFACE"))
    if other:
        warnings.append(f"{other} facce su superfici non analitiche (B-spline, tori...) non vengono misurate.")
    pts = [p for f in faces for p in f.points]
    if pts:
        mn = (min(p[0] for p in pts), min(p[1] for p in pts), min(p[2] for p in pts))
        mx = (max(p[0] for p in pts), max(p[1] for p in pts), max(p[2] for p in pts))
    else:
        mn = mx = (0.0, 0.0, 0.0)
    prod = next((e for e in ents.values() if e.type == "PRODUCT"), None)
    pname = (prod.args[0] if prod and prod.args and isinstance(prod.args[0], str) else "") or name
    return CadModel(name=pname, unit=sg.unit, scale=sg.scale, faces=faces, solids=solids,
                    surface_counts=counts, bbox_min=mn, bbox_max=mx, warnings=warnings)
