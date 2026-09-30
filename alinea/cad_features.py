"""Riconoscimento delle feature misurabili dal modello B-rep: fori, perni, piani."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import geom as g
from .geom import Vec
from .step_reader import CadModel, Face

# ordine di preferenza della direzione di accesso del tastatore (Z+ = dall'alto)
APPROACH_PREFERENCE: list[Vec] = [(0, 0, 1), (0, -1, 0), (-1, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, -1)]


@dataclass
class CylFeature:
    id: str
    internal: bool                 # True = foro, False = perno/albero
    diameter: float
    axis: Vec                      # versore dell'asse, orientato verso l'imbocco (vettore PC-DMIS)
    entry: Vec                     # centro sull'imbocco
    length: float
    through: bool
    face_ids: list[int]
    bottom: Vec = (0.0, 0.0, 0.0)  # centro all'altra estremità

    @property
    def kind(self) -> str:
        return "hole" if self.internal else "boss"


@dataclass
class PlaneFeature:
    id: str
    normal: Vec                    # uscente dal materiale
    point: Vec                     # un punto sul piano
    area: float
    face_ids: list[int]
    loops: list[list[list[Vec]]]   # per faccia: loops (esterno per primo)
    centroid: Vec = (0.0, 0.0, 0.0)
    extent: tuple[float, float] = (0.0, 0.0)   # ingombro nel piano (u, v)

    @property
    def kind(self) -> str:
        return "plane"


@dataclass
class HolePattern:
    id: str
    diameter: float
    internal: bool
    members: list[str]
    axis: Vec


@dataclass
class Distance:
    a: str
    b: str
    value: float
    kind: str        # plane-plane | axis-plane


@dataclass
class FeatureSet:
    cylinders: list[CylFeature]
    planes: list[PlaneFeature]
    patterns: list[HolePattern]
    distances: list[Distance]
    bbox_min: Vec
    bbox_max: Vec
    warnings: list[str] = field(default_factory=list)

    def by_id(self, fid: str):
        for f in self.cylinders:
            if f.id == fid:
                return f
        for f in self.planes:
            if f.id == fid:
                return f
        return None


# --------------------------------------------------------------------------- cilindri

def _axis_key(f: Face) -> tuple[Vec, Vec]:
    """Linea d'asse normalizzata: (direzione canonica, punto più vicino all'origine)."""
    d = g.unit(f.axis)
    i, s = g.nearest_axis(d)
    if s < 0:
        d = g.neg(d)
    p = f.origin
    p0 = g.sub(p, g.mul(d, g.dot(p, d)))
    return d, p0


def _plane_open_at(planes: list[Face], center: Vec, out_dir: Vec, radius: float) -> bool:
    """True se a quell'estremità c'è una faccia piana che guarda verso l'esterno del foro."""
    for pf in planes:
        n = pf.outward_normal
        if not g.same_dir(n, out_dir, 1e-3):
            continue
        if abs(g.dot(g.sub(center, pf.origin), n)) > 1e-3 * max(1.0, radius):
            continue
        # il bordo del foro deve stare su un loop della faccia
        for lp in pf.loops:
            if lp and all(abs(g.dist(p, center) - radius) < 1e-3 * max(1.0, radius) + 1e-4 for p in lp[:8]):
                return True
    return False


def _cylinders(faces: list[Face], bbox_min: Vec, bbox_max: Vec) -> list[CylFeature]:
    cyl_faces = [f for f in faces if f.kind == "cylinder"]
    planes = [f for f in faces if f.kind == "plane"]
    groups: list[list[Face]] = []
    keys: list[tuple[Vec, Vec, float, bool]] = []
    for f in cyl_faces:
        d, p0 = _axis_key(f)
        internal = not f.same_sense
        for gi, (kd, kp, kr, ki) in enumerate(keys):
            if (g.same_dir(d, kd, 1e-5) and g.dist(p0, kp) < 1e-3 and abs(kr - f.radius) < 1e-4
                    and ki == internal):
                groups[gi].append(f)
                break
        else:
            keys.append((d, p0, f.radius, internal))
            groups.append([f])

    out: list[CylFeature] = []
    for (d, p0, r, internal), grp in zip(keys, groups):
        pts = [p for f in grp for p in f.points]
        if not pts:
            continue
        ts = [g.dot(g.sub(p, p0), d) for p in pts]
        tmin, tmax = min(ts), max(ts)
        length = tmax - tmin
        if length < 1e-6:
            continue
        c_lo = g.add(p0, g.mul(d, tmin))
        c_hi = g.add(p0, g.mul(d, tmax))
        if internal:
            open_hi = _plane_open_at(planes, c_hi, d, r)
            open_lo = _plane_open_at(planes, c_lo, g.neg(d), r)
            if not (open_hi or open_lo):
                # fallback: l'estremità più vicina al bordo dell'ingombro
                open_hi = _dist_to_bbox(c_hi, d, bbox_min, bbox_max) <= _dist_to_bbox(c_lo, g.neg(d), bbox_min, bbox_max)
                open_lo = not open_hi
            through = open_hi and open_lo
        else:
            open_hi = open_lo = True
            through = True
        cands = []
        if open_hi:
            cands.append((d, c_hi, c_lo))
        if open_lo:
            cands.append((g.neg(d), c_lo, c_hi))
        cands.sort(key=lambda c: _approach_rank(c[0]))
        vec, entry, bottom = cands[0]
        out.append(CylFeature(id="", internal=internal, diameter=2 * r, axis=vec, entry=entry,
                              bottom=bottom, length=length, through=through,
                              face_ids=[f.id for f in grp]))
    return out


def _dist_to_bbox(p: Vec, d: Vec, mn: Vec, mx: Vec) -> float:
    best = math.inf
    for i in range(3):
        if abs(d[i]) < 1e-9:
            continue
        lim = mx[i] if d[i] > 0 else mn[i]
        best = min(best, (lim - p[i]) / d[i])
    return best


def _approach_rank(v: Vec) -> float:
    return min(i + (1 - g.dot(v, a)) * 10 for i, a in enumerate(APPROACH_PREFERENCE))


# --------------------------------------------------------------------------- piani

def _planes(faces: list[Face]) -> list[PlaneFeature]:
    groups: list[list[Face]] = []
    for f in faces:
        if f.kind != "plane" or not f.loops:
            continue
        n = f.outward_normal
        for grp in groups:
            n0 = grp[0].outward_normal
            if g.same_dir(n, n0, 1e-5) and abs(g.dot(g.sub(f.origin, grp[0].origin), n0)) < 1e-3:
                grp.append(f)
                break
        else:
            groups.append([f])
    out = []
    for grp in groups:
        n = g.unit(grp[0].outward_normal)
        area = 0.0
        for f in grp:
            area += abs(g.polygon_area_3d(f.loops[0], n)) - sum(abs(g.polygon_area_3d(lp, n)) for lp in f.loops[1:])
        pts = [p for f in grp for p in f.loops[0]]
        u, v = g.plane_basis(n)
        us = [g.dot(p, u) for p in pts]
        vs = [g.dot(p, v) for p in pts]
        c = g.centroid(pts)
        out.append(PlaneFeature(id="", normal=n, point=grp[0].loops[0][0], area=area,
                                face_ids=[f.id for f in grp], loops=[f.loops for f in grp],
                                centroid=c, extent=(max(us) - min(us), max(vs) - min(vs))))
    return out


def plane_candidates(pl: PlaneFeature, margin: float | None = None, grid: int = 24) -> list[tuple[float, float, Vec]]:
    """Griglia di punti (u, v, xyz) interni alla faccia, lontani dai bordi e dai fori."""
    n = pl.normal
    u, v = g.plane_basis(n)
    if margin is None:
        small = min((e for e in pl.extent if e > 0), default=1.0)
        margin = max(0.8, min(4.0, 0.12 * small))
    cands: list[tuple[float, float, Vec]] = []
    origin_off = g.dot(pl.point, n)
    for loops in pl.loops:
        polys = [[(g.dot(p, u), g.dot(p, v)) for p in lp] for lp in loops]
        outer, inners = polys[0], polys[1:]
        us = [p[0] for p in outer]
        vs = [p[1] for p in outer]
        u0, u1, v0, v1 = min(us), max(us), min(vs), max(vs)
        for i in range(grid + 1):
            for j in range(grid + 1):
                x = u0 + (u1 - u0) * i / grid
                y = v0 + (v1 - v0) * j / grid
                if not g.point_in_polygon_2d(x, y, outer):
                    continue
                if any(g.point_in_polygon_2d(x, y, ip) for ip in inners):
                    continue
                dmin = math.inf
                for poly in polys:
                    for k in range(len(poly)):
                        dmin = min(dmin, g.dist_point_segment_2d(x, y, poly[k], poly[(k + 1) % len(poly)]))
                if dmin < margin:
                    continue
                p3 = g.add(g.add(g.mul(u, x), g.mul(v, y)), g.mul(n, origin_off))
                cands.append((x, y, p3))
    return cands


def plane_sample_points(pl: PlaneFeature, count: int = 4, margin: float | None = None,
                        grid: int = 24) -> list[Vec]:
    """Punti di tastatura ben distribuiti sulla faccia (farthest point sampling)."""
    cands = plane_candidates(pl, margin, grid)
    if not cands:
        return []
    chosen = [min(cands, key=lambda c: c[0] + c[1])]
    while len(chosen) < min(count, len(cands)):
        nxt = max(cands, key=lambda c: min(math.hypot(c[0] - s[0], c[1] - s[1]) for s in chosen))
        if min(math.hypot(nxt[0] - s[0], nxt[1] - s[1]) for s in chosen) < 1e-6:
            break
        chosen.append(nxt)
    # ordina i punti attorno al baricentro (percorso più corto)
    cx = sum(c[0] for c in chosen) / len(chosen)
    cy = sum(c[1] for c in chosen) / len(chosen)
    chosen.sort(key=lambda c: math.atan2(c[1] - cy, c[0] - cx))
    return [c[2] for c in chosen]


def line_points(pl: PlaneFeature, direction: Vec, spread: float = 0.8) -> tuple[Vec, Vec] | None:
    """Due punti sul piano alla stessa altezza, distanziati lungo `direction` (per una linea 2D)."""
    cands = [c[2] for c in plane_candidates(pl)]
    if len(cands) < 2:
        return None
    h_axis = g.unit(g.cross(direction, pl.normal))
    hs = [round(g.dot(p, h_axis), 6) for p in cands]
    rows: dict[float, list[Vec]] = {}
    for h, p in zip(hs, cands):
        rows.setdefault(h, []).append(p)
    mid = (max(hs) + min(hs)) / 2

    def row_len(pts: list[Vec]) -> float:
        ts = [g.dot(p, direction) for p in pts]
        return max(ts) - min(ts)

    best_len = max(row_len(r) for r in rows.values())
    # la riga più vicina a metà altezza, purché lunga almeno ~l'80% della più lunga
    good = [h for h, r in rows.items() if row_len(r) >= spread * best_len]
    h = min(good, key=lambda x: abs(x - mid))
    r = rows[h]
    return min(r, key=lambda p: g.dot(p, direction)), max(r, key=lambda p: g.dot(p, direction))


# --------------------------------------------------------------------------- insieme

def extract_features(model: CadModel) -> FeatureSet:
    cyls = _cylinders(model.faces, model.bbox_min, model.bbox_max)
    planes = _planes(model.faces)
    warnings = list(model.warnings)

    # numerazione stabile: fori per diametro decrescente poi posizione
    cyls.sort(key=lambda c: (not c.internal, -round(c.diameter, 3), round(c.entry[2], 3) * -1,
                             round(c.entry[1], 3), round(c.entry[0], 3)))
    nh = nb = 0
    for c in cyls:
        if c.internal:
            nh += 1
            c.id = f"F{nh}"
        else:
            nb += 1
            c.id = f"P{nb}"
    planes.sort(key=lambda p: -p.area)
    for i, p in enumerate(planes, 1):
        p.id = f"S{i}"

    # pattern: stesso diametro, stessa direzione, stesso tipo
    patterns: list[HolePattern] = []
    seen: set[str] = set()
    for c in cyls:
        if c.id in seen:
            continue
        mates = [o for o in cyls if o.internal == c.internal and abs(o.diameter - c.diameter) < 1e-3
                 and g.same_dir(o.axis, c.axis, 1e-4)]
        if len(mates) > 1:
            for m in mates:
                seen.add(m.id)
            patterns.append(HolePattern(id=f"PAT{len(patterns) + 1}", diameter=c.diameter, internal=c.internal,
                                        members=[m.id for m in mates], axis=c.axis))

    # distanze candidate (per associare le quote lineari)
    dists: list[Distance] = []
    for i, a in enumerate(planes):
        for b in planes[i + 1:]:
            if g.parallel(a.normal, b.normal, 1e-5):
                d = abs(g.dot(g.sub(b.point, a.point), a.normal))
                if d > 1e-4:
                    dists.append(Distance(a.id, b.id, d, "plane-plane"))
    for c in cyls:
        for p in planes:
            if g.perpendicular(c.axis, p.normal, 1e-4):
                d = abs(g.dot(g.sub(c.entry, p.point), p.normal))
                dists.append(Distance(c.id, p.id, d, "axis-plane"))

    if not cyls and not planes:
        warnings.append("Nessuna feature misurabile riconosciuta nel CAD.")
    return FeatureSet(cylinders=cyls, planes=planes, patterns=patterns, distances=dists,
                      bbox_min=model.bbox_min, bbox_max=model.bbox_max, warnings=warnings)
