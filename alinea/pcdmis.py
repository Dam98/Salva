"""Generatore del programma PC-DMIS (testo dei comandi dell'Edit Window).

Struttura del programma:
  intestazione -> allineamento manuale 3-2-1 -> allineamento DCC -> feature raggruppate per
  orientamento del tastatore -> dimensioni.

Tutte le coordinate teoriche sono espresse nel sistema di riferimento dei datum (A/B/C),
calcolato dal CAD. Il pezzo si assume posizionato sulla macchina come nel CAD (Z+ in alto).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import geom as g
from .cad_features import CylFeature, FeatureSet, PlaneFeature, line_points, plane_sample_points
from .geom import Vec, fmt, fmt_vec
from .matching import Plan, PlanItem


@dataclass
class Settings:
    part_name: str = "PEZZO"
    revision: str = "A"
    probe: str = "PROBE1"
    stylus_diameter: float = 2.0
    clearance: float = 20.0          # distanza del piano di sicurezza sopra il pezzo
    safe_distance: float = 15.0      # distanza di avvicinamento per le feature laterali
    circle_hits: int = 4
    circle_hits_large: int = 8       # per diametri >= 30
    cylinder_min_length: float = 8.0
    plane_hits: int = 4
    tip_step: float = 7.5            # passo di indicizzazione della testa (HH-AS8: 7.5°)
    manual_alignment: bool = True
    units: str = "MM"


@dataclass
class Program:
    text: str
    stats: dict
    warnings: list[str]
    blocks: dict[str, tuple[int, int]]      # id feature/item -> righe (inizio, fine) 1-based
    frame: dict


# --------------------------------------------------------------------------- sistema di riferimento

@dataclass
class DatumFrame:
    origin: Vec
    ex: Vec
    ey: Vec
    ez: Vec
    commands: list[str] = field(default_factory=list)   # righe ALIGNMENT/... (con nomi segnaposto)
    notes: list[str] = field(default_factory=list)
    line_dir: Vec | None = None   # direzione in cui vanno presi i punti della linea di rotazione
    line_plane: str | None = None

    def to_local(self, p: Vec) -> Vec:
        d = g.sub(p, self.origin)
        return (g.dot(d, self.ex), g.dot(d, self.ey), g.dot(d, self.ez))

    def vec(self, v: Vec) -> Vec:
        return (g.dot(v, self.ex), g.dot(v, self.ey), g.dot(v, self.ez))


def _axes_from(k: int, ek: Vec, m: int, em: Vec) -> tuple[Vec, Vec, Vec]:
    E: list[Vec | None] = [None, None, None]
    E[k] = ek
    E[m] = em
    t = 3 - k - m
    E[t] = g.cross(E[(t + 1) % 3], E[(t + 2) % 3])  # type: ignore[arg-type]
    return E[0], E[1], E[2]  # type: ignore[return-value]


def build_frame(fs: FeatureSet, datums: dict[str, str]) -> DatumFrame:
    notes: list[str] = []
    A = fs.by_id(datums.get("A", ""))
    B = fs.by_id(datums.get("B", ""))
    C = fs.by_id(datums.get("C", ""))
    if not isinstance(A, PlaneFeature):
        planes = sorted(fs.planes, key=lambda p: -p.area)
        if not planes:
            return DatumFrame((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), [], ["Nessun piano: uso il sistema CAD"])
        A = planes[0]
        notes.append(f"Riferimento A non valido: uso il piano {A.id}")
    nA = A.normal
    k, sk = g.nearest_axis(nA)
    ek = g.mul(nA, sk)                    # asse macchina k allineato alla normale di A
    lvl = f"ALIGNMENT/LEVEL,{g.axis_label(k, sk)},{{A}}"
    cmds = [lvl]

    def inplane(v: Vec) -> Vec:
        return g.unit(g.sub(v, g.mul(nA, g.dot(v, nA))))

    line_dir = None
    line_plane = None
    rot_feat = None
    if isinstance(B, PlaneFeature) and g.perpendicular(B.normal, nA, 1e-2):
        line_dir = inplane(g.cross(nA, B.normal))
        rot_feat, line_plane = "{B}", B.id
    elif isinstance(B, CylFeature) and isinstance(C, CylFeature):
        line_dir = inplane(g.sub(C.entry, B.entry))
        rot_feat = "{BC}"
    elif isinstance(B, CylFeature) and isinstance(C, PlaneFeature) and g.perpendicular(C.normal, nA, 1e-2):
        line_dir = inplane(g.cross(nA, C.normal))
        rot_feat, line_plane = "{C}", C.id
    if line_dir is None:
        # nessun secondario valido: asse macchina più vicino nel piano di A
        m, _ = g.nearest_axis((1, 1, 1), exclude=[k])
        line_dir = inplane(g.AXES[m])
        notes.append("Riferimento secondario mancante: la rotazione resta quella del CAD (da verificare)")
        rot_feat = None
    m, sm = g.nearest_axis(line_dir, exclude=[k])
    if rot_feat != "{BC}":
        # per una linea tastata scegliamo noi l'ordine dei punti: verso positivo dell'asse
        line_dir = g.mul(line_dir, sm)
        sm = 1
    em = g.mul(line_dir, sm)
    if rot_feat:
        cmds.append(f"ALIGNMENT/ROTATE,{g.axis_label(m, sm)},TO,{rot_feat},ABOUT,{g.axis_label(k, 1)}")
    ex, ey, ez = _axes_from(k, ek, m, em)
    E = (ex, ey, ez)

    # origine: A fissa la coordinata k; B e C le altre due
    rows: list[Vec] = [ek]
    rhs: list[float] = [g.dot(ek, A.point)]
    trans: list[str] = []
    for tag, F in (("{B}", B), ("{C}", C)):
        if isinstance(F, PlaneFeature) and g.perpendicular(F.normal, nA, 1e-2):
            i, _ = g.nearest_axis(F.normal, exclude=[k])
            if any(abs(g.dot(r, E[i])) > 0.99 for r in rows):
                continue
            rows.append(E[i])
            rhs.append(g.dot(E[i], F.point))
            trans.append(f"ALIGNMENT/TRANS,{g.AXIS_NAMES[i]}AXIS,{tag}")
        elif isinstance(F, CylFeature):
            for i in range(3):
                if i == k or any(abs(g.dot(r, E[i])) > 0.99 for r in rows):
                    continue
                rows.append(E[i])
                rhs.append(g.dot(E[i], F.entry))
                trans.append(f"ALIGNMENT/TRANS,{g.AXIS_NAMES[i]}AXIS,{tag}")
    for i in range(3):
        if len(rows) >= 3:
            break
        if i != k and not any(abs(g.dot(r, E[i])) > 0.99 for r in rows):
            rows.append(E[i])
            rhs.append(g.dot(E[i], fs.bbox_min))
            notes.append(f"Origine {g.AXIS_NAMES[i]} non vincolata dai riferimenti: presa sull'ingombro CAD")
    O = g.solve3(rows, rhs) or fs.bbox_min
    cmds += trans
    cmds.append(f"ALIGNMENT/TRANS,{g.AXIS_NAMES[k]}AXIS,{{A}}")
    return DatumFrame(O, ex, ey, ez, cmds, notes, line_dir, line_plane)


# --------------------------------------------------------------------------- tastatore

def tip_for(v: Vec, step: float = 7.5) -> tuple[str, Vec, bool]:
    """Nome del tip (T1AxBy), vettore stelo e raggiungibilità, dato il vettore della feature."""
    v = g.unit(v)
    a = math.degrees(math.acos(max(-1.0, min(1.0, v[2]))))
    b = math.degrees(math.atan2(-v[0], v[1])) if a > 1e-6 else 0.0
    a_r = round(a / step) * step
    b_r = round(b / step) * step
    if abs(b_r + 180) < 1e-9:
        b_r = 180.0
    if a_r < 1e-9:
        b_r = 0.0
    reachable = a_r <= 105.0
    ar, br = math.radians(a_r), math.radians(b_r)
    shank = (-math.sin(ar) * math.sin(br), math.sin(ar) * math.cos(br), math.cos(ar))
    name = f"T1A{_ang(a_r)}B{_ang(b_r)}"
    return name, shank, reachable


def _ang(x: float) -> str:
    return str(int(x)) if abs(x - round(x)) < 1e-9 else f"{x:.1f}"


# --------------------------------------------------------------------------- emissione

class Writer:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def cmd(self, label: str, text: str) -> None:
        self.lines.append(f"{label:<11}={text}" if label else f"{'':<12}{text}")

    def raw(self, text: str = "") -> None:
        self.lines.append(text)

    def sub(self, text: str, indent: int = 12) -> None:
        self.lines.append(" " * indent + text)

    @property
    def n(self) -> int:
        return len(self.lines)


def _dim_row(ax: str, nom: float | None, plus: float | None, minus: float | None, meas: float | None,
             bonus: bool = False) -> str:
    cols = [f"{ax:<2}"]
    for v in (nom, plus, minus):
        cols.append(f"{fmt(v):>11}" if v is not None else " " * 11)
    if bonus:
        cols.append(" " * 11)
    m = meas if meas is not None else nom
    cols.append(f"{fmt(m):>11}" if m is not None else " " * 11)
    cols.append(f"{fmt(0.0):>11}")
    if plus is not None:
        cols.append(f"{fmt(0.0):>11} ----#----")
    return "".join(cols)


def generate(fs: FeatureSet, plan: Plan, st: Settings) -> Program:
    warnings: list[str] = []
    frame = build_frame(fs, plan.datums)
    warnings += frame.notes
    W = Writer()
    blocks: dict[str, tuple[int, int]] = {}
    stats = {"features": 0, "hits": 0, "tips": [], "tip_changes": 0, "dimensions": 0}

    items = [i for i in plan.items if i.enabled and i.check != "manual" and i.features]
    needed: list[str] = []
    for it in items:
        for f in it.features + ([it.ref_feature] if it.ref_feature else []):
            if f and f not in needed:
                needed.append(f)
    # le feature che richiedono la forma del cilindro
    need_cyl = {f for it in items if it.check in ("cylindricity", "perpendicularity", "parallelism")
                for f in it.features}

    # nomi PC-DMIS
    names: dict[str, str] = {}
    datum_of = {fid: letter for letter, fid in plan.datums.items()}
    for fid in needed + list(plan.datums.values()):
        F = fs.by_id(fid)
        if F is None:
            continue
        if isinstance(F, PlaneFeature):
            names[fid] = f"PLN_{datum_of[fid]}" if fid in datum_of else f"PLN_{fid}"
        elif isinstance(F, CylFeature):
            use_cyl = F.length >= st.cylinder_min_length or fid in need_cyl
            base = "CYL" if use_cyl else "CIR"
            names[fid] = f"{base}_{datum_of[fid]}" if fid in datum_of else f"{base}_{fid}"

    # ---------------------------------------------------------------- intestazione
    W.raw(f"PART NAME  : {st.part_name}")
    W.raw(f"REV NUMBER : {st.revision}")
    W.raw("SER NUMBER : ")
    W.raw("STATS COUNT : 1")
    W.raw("")
    W.cmd("STARTUP", "ALIGNMENT/START,RECALL:USE_PART_SETUP,LIST=YES")
    W.sub("ALIGNMENT/END")
    W.sub(f"MODE/{'MANUAL' if st.manual_alignment else 'DCC'}")
    W.sub("FORMAT/TEXT,OPTIONS, ,HEADINGS,SYMBOLS, ;NOM,TOL,MEAS,DEV,OUTTOL, , ")
    W.sub(f"LOADPROBE/{st.probe}")
    W.sub("TIP/T1A0B0, SHANKIJK=0, 0, 1, ANGLE=0")
    W.sub("COMMENT/OPER,NO,FULL SCREEN=NO,AUTO-CONTINUE=NO,")
    W.sub(f"Programma generato da Alinea per {st.part_name}.")
    W.sub("Posizionare il pezzo come nel CAD (riferimento A verso l'alto).")

    top = max(frame.to_local(p)[2] for p in _bbox_corners(fs))
    clear_z = top + st.clearance

    # ---------------------------------------------------------------- allineamenti
    dat_feats = {k: fs.by_id(v) for k, v in plan.datums.items()}
    A = dat_feats.get("A")
    if not isinstance(A, PlaneFeature):
        A = next((p for p in sorted(fs.planes, key=lambda p: -p.area)), None)

    def emit_alignment(suffix: str, manual: bool) -> str:
        nm: dict[str, str] = {}
        hits_plane = 3 if manual else st.plane_hits
        if isinstance(A, PlaneFeature):
            nm["{A}"] = f"PLN_A{suffix}"
            _emit_plane(W, nm["{A}"], A, frame, hits_plane, stats)
            names.setdefault(A.id, nm["{A}"])
        for letter in ("B", "C"):
            F = dat_feats.get(letter)
            tag = "{" + letter + "}"
            if isinstance(F, PlaneFeature):
                if F.id == frame.line_plane:
                    nm[tag] = f"LIN_{letter}{suffix}"
                    _emit_line(W, nm[tag], F, frame, stats)
                else:
                    nm[tag] = f"PNT_{letter}{suffix}"
                    _emit_point(W, nm[tag], F, frame, stats)
            elif isinstance(F, CylFeature):
                nm[tag] = f"CIR_{letter}{suffix}"
                _emit_circle(W, nm[tag], F, frame, st, stats, cylinder=False)
        if "{BC}" in " ".join(frame.commands):
            nm["{BC}"] = f"LIN_BC{suffix}"
            W.cmd(nm["{BC}"], "FEAT/LINE,CARTESIAN,UNBOUNDED,NO")
            b, c = dat_feats["B"], dat_feats["C"]
            W.sub(f"THEO/<{fmt_vec(frame.to_local(b.entry))}>,<{fmt_vec(frame.vec(frame.line_dir))}>")
            W.sub(f"ACTL/<{fmt_vec(frame.to_local(b.entry))}>,<{fmt_vec(frame.vec(frame.line_dir))}>")
            W.sub(f"CONSTR/LINE,BF,2D,{nm['{B}']},{nm['{C}']},,")
            W.sub("OUTLIER_REMOVAL/OFF,3")
            W.sub("FILTER/OFF,WAVELENGTH=0")
        label = "A_MAN" if manual else "A_DCC"
        recall = "STARTUP" if manual or not st.manual_alignment else "A_MAN"
        W.cmd(label, f"ALIGNMENT/START,RECALL:{recall},LIST=YES")
        for c in frame.commands:
            line = c
            for tag, n in nm.items():
                line = line.replace(tag, n)
            if "{" in line:
                continue
            W.sub(line, 14)
        W.sub("ALIGNMENT/END")
        return label

    start = W.n + 1
    if st.manual_alignment:
        W.sub("COMMENT/OPER,NO,FULL SCREEN=NO,AUTO-CONTINUE=NO,")
        W.sub("Allineamento manuale: prendere i punti nell'ordine indicato (3 su A, 2 su B, 1 su C).")
        emit_alignment("_MAN", manual=True)
        W.sub("MODE/DCC")
    W.sub(f"CLEARP/{g.axis_label(2, 1)},{fmt(clear_z)},{g.axis_label(2, 1)},0,ON")
    W.sub("MOVE/CLEARPLANE")
    emit_alignment("", manual=False)
    blocks["ALIGN"] = (start, W.n)
    for letter, fid in plan.datums.items():
        F = fs.by_id(fid)
        if isinstance(F, PlaneFeature) and letter == "A":
            names[fid] = "PLN_A"
        elif isinstance(F, CylFeature):
            names[fid] = f"CIR_{letter}"

    # ---------------------------------------------------------------- feature
    to_measure = [f for f in needed if names.get(f) and names[f] not in ("PLN_A",)
                  and not (isinstance(fs.by_id(f), CylFeature) and f in plan.datums.values())]
    plan_feats = []
    for fid in to_measure:
        F = fs.by_id(fid)
        vec = frame.vec(F.axis if isinstance(F, CylFeature) else F.normal)
        tip, shank, ok = tip_for(vec, st.tip_step)
        if not ok:
            warnings.append(f"{fid}: faccia con vettore {fmt_vec(vec, 2)} non raggiungibile dalla testa "
                            "(il pezzo ci appoggia sopra): serve un secondo piazzamento, feature esclusa")
            names.pop(fid, None)
            continue
        pos = frame.to_local(F.entry if isinstance(F, CylFeature) else F.centroid)
        plan_feats.append((tip, shank, pos, fid, F))
    # raggruppa per tip (A0B0 per primo), poi percorso nearest-neighbour
    tips_order: list[str] = []
    for t in sorted({p[0] for p in plan_feats}, key=lambda t: (t != "T1A0B0", t)):
        tips_order.append(t)
    current_tip = "T1A0B0"
    last = (0.0, 0.0, clear_z)
    for t in tips_order:
        grp = [p for p in plan_feats if p[0] == t]
        ordered = []
        while grp:
            nxt = min(grp, key=lambda p: g.dist(p[2], last))
            grp.remove(nxt)
            ordered.append(nxt)
            last = nxt[2]
        if t != current_tip:
            W.sub("MOVE/CLEARPLANE")
            W.sub(f"TIP/{t}, SHANKIJK={', '.join(fmt(c, 3).rstrip('0').rstrip('.') or '0' for c in ordered[0][1])}, ANGLE=0")
            stats["tip_changes"] += 1
            current_tip = t
        for tip, shank, pos, fid, F in ordered:
            s0 = W.n + 1
            side = abs(frame.vec(F.axis if isinstance(F, CylFeature) else F.normal)[2]) < 0.9
            if side:
                app = g.add(pos, g.mul(frame.vec(F.axis if isinstance(F, CylFeature) else F.normal), st.safe_distance))
                W.sub(f"MOVE/POINT,NORMAL,<{fmt_vec(app)}>")
            if isinstance(F, CylFeature):
                if F.diameter <= st.stylus_diameter + 0.5 and F.internal:
                    warnings.append(f"{fid}: Ø{F.diameter:.2f} troppo piccolo per il tastatore Ø{st.stylus_diameter}")
                _emit_circle(W, names[fid], F, frame, st, stats, cylinder=names[fid].startswith("CYL"))
            else:
                _emit_plane(W, names[fid], F, frame, st.plane_hits, stats)
            if side:
                W.sub(f"MOVE/POINT,NORMAL,<{fmt_vec(app)}>")
            blocks[fid] = (s0, W.n)
    stats["tips"] = ["T1A0B0"] + [t for t in tips_order if t != "T1A0B0"]
    W.sub("MOVE/CLEARPLANE")
    if current_tip != "T1A0B0":
        W.sub("TIP/T1A0B0, SHANKIJK=0, 0, 1, ANGLE=0")
        stats["tip_changes"] += 1

    # ---------------------------------------------------------------- dimensioni
    W.raw("")
    ndim = 0
    for it in items:
        s0 = W.n + 1
        missing = [f for f in it.features + ([it.ref_feature] if it.ref_feature else []) if f not in names]
        if missing:
            warnings.append(f"{it.id} {it.label}: feature {', '.join(missing)} non misurate, dimensione saltata")
            continue
        for fid in it.features:
            F = fs.by_id(fid)
            ndim += 1
            _emit_dim(W, f"D{ndim:03d}", it, F, names[fid], names.get(it.ref_feature or ""), fs, frame, plan)
        blocks[it.id] = (s0, W.n)
    stats["dimensions"] = ndim
    stats["cycle_time_s"] = int(stats["hits"] * 2.2 + stats["tip_changes"] * 7 + stats["features"] * 3 + 20)
    W.raw("")
    W.sub("COMMENT/REPT,")
    W.sub(f"Fine programma {st.part_name}")
    text = "\n".join(W.lines) + "\n"
    frame_info = {"origin_cad": frame.origin, "x": frame.ex, "y": frame.ey, "z": frame.ez,
                  "commands": frame.commands, "names": names}
    return Program(text=text, stats=stats, warnings=warnings, blocks=blocks, frame=frame_info)


def _bbox_corners(fs: FeatureSet) -> list[Vec]:
    a, b = fs.bbox_min, fs.bbox_max
    return [(x, y, z) for x in (a[0], b[0]) for y in (a[1], b[1]) for z in (a[2], b[2])]


# --------------------------------------------------------------------------- feature

def _hit(W: Writer, p: Vec, n: Vec) -> None:
    W.sub(f"HIT/BASIC,NORMAL,<{fmt_vec(p)}>,<{fmt_vec(n, 7)}>,<{fmt_vec(p)}>,USE THEO=YES", 14)


def _emit_plane(W: Writer, name: str, F: PlaneFeature, fr: DatumFrame, hits: int, stats: dict) -> None:
    pts = plane_sample_points(F, count=hits) or [F.centroid]
    n = fr.vec(F.normal)
    loc = [fr.to_local(p) for p in pts]
    c = g.centroid(loc)
    W.cmd(name, "FEAT/PLANE,CARTESIAN,OUTLINE,NO")
    W.sub(f"THEO/<{fmt_vec(c)}>,<{fmt_vec(n, 7)}>")
    W.sub(f"ACTL/<{fmt_vec(c)}>,<{fmt_vec(n, 7)}>")
    W.sub(f"MEAS/PLANE,{len(loc)}")
    for p in loc:
        _hit(W, p, n)
    W.sub("ENDMEAS/")
    stats["hits"] += len(loc)
    stats["features"] += 1


def _emit_line(W: Writer, name: str, F: PlaneFeature, fr: DatumFrame, stats: dict) -> None:
    """Linea di 2 punti sul piano secondario, presi nel verso positivo dell'asse di rotazione."""
    d = fr.line_dir or (1, 0, 0)
    pp = line_points(F, d)
    if pp is None:
        pp = (F.centroid, g.add(F.centroid, g.mul(d, 10.0)))
    n = fr.vec(F.normal)
    l1, l2 = fr.to_local(pp[0]), fr.to_local(pp[1])
    W.cmd(name, "FEAT/LINE,CARTESIAN,UNBOUNDED,NO")
    W.sub(f"THEO/<{fmt_vec(l1)}>,<{fmt_vec(g.unit(g.sub(l2, l1)), 7)}>")
    W.sub(f"ACTL/<{fmt_vec(l1)}>,<{fmt_vec(g.unit(g.sub(l2, l1)), 7)}>")
    W.sub(f"MEAS/LINE,2,{g.axis_label(2, 1)}")
    _hit(W, l1, n)
    _hit(W, l2, n)
    W.sub("ENDMEAS/")
    stats["hits"] += 2
    stats["features"] += 1


def _emit_point(W: Writer, name: str, F: PlaneFeature, fr: DatumFrame, stats: dict) -> None:
    cands = plane_sample_points(F, count=9) or [F.centroid]
    c = F.centroid
    p = min(cands, key=lambda q: g.dist(q, c))
    n = fr.vec(F.normal)
    lp = fr.to_local(p)
    W.cmd(name, "FEAT/POINT,CARTESIAN")
    W.sub(f"THEO/<{fmt_vec(lp)}>,<{fmt_vec(n, 7)}>")
    W.sub(f"ACTL/<{fmt_vec(lp)}>,<{fmt_vec(n, 7)}>")
    W.sub("MEAS/POINT,1,WORKPLANE")
    _hit(W, lp, n)
    W.sub("ENDMEAS/")
    stats["hits"] += 1
    stats["features"] += 1


def _emit_circle(W: Writer, name: str, F: CylFeature, fr: DatumFrame, st: Settings, stats: dict,
                 cylinder: bool) -> None:
    c = fr.to_local(F.entry)
    v = fr.vec(F.axis)
    d = F.diameter
    hits = st.circle_hits_large if d >= 30 else st.circle_hits
    io = "IN" if F.internal else "OUT"
    ang_vec = g.plane_basis(v)[0]
    depth = min(2.0, max(0.5, F.length * 0.2))
    if cylinder:
        L = F.length
        end_off = depth
        W.cmd(name, f"FEAT/CONTACT/CYLINDER/DEFAULT,CARTESIAN,{io},LEAST_SQR")
        W.sub(f"THEO/<{fmt_vec(c)}>,<{fmt_vec(v, 7)}>,{fmt(d)},{fmt(L)}")
        W.sub(f"ACTL/<{fmt_vec(c)}>,<{fmt_vec(v, 7)}>,{fmt(d)},{fmt(L)}")
        W.sub(f"TARG/<{fmt_vec(c)}>,<{fmt_vec(v, 7)}>")
        W.sub("START ANG=0,END ANG=360")
        W.sub(f"ANGLE VEC=<{fmt_vec(ang_vec, 7)}>")
        W.sub("DIRECTION=CCW")
        W.sub("SHOW FEATURE PARAMETERS=NO")
        W.sub("SHOW CONTACT PARAMETERS=YES")
        W.sub(f"NUMHITS={hits},LEVELS=2,DEPTH={fmt(depth)},END OFFSET={fmt(end_off)},PITCH=0", 14)
        W.sub("SAMPLE METHOD=SAMPLE_HITS", 14)
        W.sub("SAMPLE HITS=0,SPACER=0", 14)
        W.sub("AVOIDANCE MOVE=NO,DISTANCE=10", 14)
        W.sub("FIND HOLE=DISABLED,ONERROR=NO,READ POS=NO", 14)
        W.sub("SHOW HITS=NO")
        stats["hits"] += hits * 2
    else:
        W.cmd(name, f"FEAT/CONTACT/CIRCLE/DEFAULT,CARTESIAN,{io},LEAST_SQR")
        W.sub(f"THEO/<{fmt_vec(c)}>,<{fmt_vec(v, 7)}>,{fmt(d)}")
        W.sub(f"ACTL/<{fmt_vec(c)}>,<{fmt_vec(v, 7)}>,{fmt(d)}")
        W.sub(f"TARG/<{fmt_vec(c)}>,<{fmt_vec(v, 7)}>")
        W.sub("START ANG=0,END ANG=360")
        W.sub(f"ANGLE VEC=<{fmt_vec(ang_vec, 7)}>")
        W.sub("DIRECTION=CCW")
        W.sub("SHOW FEATURE PARAMETERS=NO")
        W.sub("SHOW CONTACT PARAMETERS=YES")
        W.sub(f"NUMHITS={hits},DEPTH={fmt(depth)},PITCH=0", 14)
        W.sub("SAMPLE METHOD=SAMPLE_HITS", 14)
        W.sub("SAMPLE HITS=0,SPACER=0", 14)
        W.sub("AVOIDANCE MOVE=NO,DISTANCE=10", 14)
        W.sub("FIND HOLE=DISABLED,ONERROR=NO,READ POS=NO", 14)
        W.sub("SHOW HITS=NO")
        stats["hits"] += hits
    stats["features"] += 1


def _ftype(name: str) -> str:
    return {"PLN": "PLANE", "CIR": "CIRCLE", "CYL": "CYLINDER", "LIN": "LINE", "PNT": "POINT"}[name[:3]]


# --------------------------------------------------------------------------- dimensioni

HEAD = "AX    NOMINAL       +TOL       -TOL       MEAS        DEV     OUTTOL"
HEAD_TP = "AX    NOMINAL       +TOL       -TOL      BONUS       MEAS        DEV     OUTTOL"
OPTS = "GRAPH=OFF  TEXT=OFF  MULT=10.00  OUTPUT=BOTH"


def _emit_dim(W: Writer, dn: str, it: PlanItem, F, fname: str, rname: str | None, fs: FeatureSet,
              fr: DatumFrame, plan: Plan) -> None:
    up = it.upper if it.upper is not None else 0.0
    lo = it.lower if it.lower is not None else 0.0
    W.raw(f"{'':<12}COMMENT/REPT,")
    W.raw(f"{'':<12}{it.id} {it.label}")
    if it.check == "diameter":
        W.raw(f"DIM {dn}= LOCATION OF {_ftype(fname)} {fname}  UNITS={_u()} ,$")
        W.raw(f"{OPTS}  HALF ANGLE=NO")
        W.raw(HEAD)
        W.raw(_dim_row("D", it.nominal if it.nominal is not None else F.diameter, up, -lo, None))
        if fname.startswith("CYL"):
            W.raw(_dim_row("L", F.length, None, None, None))
        W.raw(f"END OF DIMENSION {dn}")
    elif it.check == "position":
        ax = _inplane_axes(fr, F)
        loc = fr.to_local(F.entry)
        W.raw(f"DIM {dn}= TRUE POSITION OF {_ftype(fname)} {fname}  UNITS={_u()} ,$")
        mod = {"MMC": "MMC", "LMC": "LMC"}.get(it.modifier or "", "RFS")
        W.raw(f"{OPTS}  FIT TO DATUMS=YES  DEV PERPEN CENTERLINE=ON  DISPLAY=DIAMETER")
        W.raw(HEAD_TP)
        for i in ax:
            W.raw(_dim_row("XYZ"[i], loc[i], None, None, None, bonus=True))
        W.raw(_dim_row("DF", F.diameter, None, None, None, bonus=True))
        W.raw(f"{'TP':<2}{mod:>11}{fmt(up):>11}{'':>11}{fmt(0.0):>11}{fmt(0.0):>11}{fmt(0.0):>11}"
              f"{fmt(0.0):>11} ----#----")
        W.raw(f"END OF DIMENSION {dn}")
        if it.datums:
            W.raw(f"{'':<12}COMMENT/REPT,")
            W.raw(f"{'':<12}Riferimenti {'|'.join(it.datums)}: coordinate teoriche nel sistema A_DCC")
    elif it.check == "distance" and rname:
        W.raw(f"DIM {dn}= 3D DISTANCE FROM {_ftype(fname)} {fname} TO {_ftype(rname)} {rname},NO_RADIUS  "
              f"UNITS={_u()},$")
        W.raw(OPTS)
        W.raw(HEAD)
        W.raw(_dim_row("M", it.nominal, up, -lo, None))
        W.raw(f"END OF DIMENSION {dn}")
    elif it.check in ("flatness", "cylindricity", "circularity"):
        what = {"flatness": "FLATNESS", "cylindricity": "CYLINDRICITY", "circularity": "ROUNDNESS"}[it.check]
        W.raw(f"DIM {dn}= {what} OF {_ftype(fname)} {fname}  UNITS={_u()} ,$")
        W.raw(OPTS)
        W.raw(HEAD)
        W.raw(_dim_row("M", 0.0, up, 0.0, None))
        W.raw(f"END OF DIMENSION {dn}")
    elif it.check in ("perpendicularity", "parallelism", "concentricity"):
        ref = rname or "PLN_A"
        what = {"perpendicularity": "PERPENDICULARITY", "parallelism": "PARALLELISM",
                "concentricity": "CONCENTRICITY"}[it.check]
        W.raw(f"DIM {dn}= {what} FROM {_ftype(ref)} {ref} TO {_ftype(fname)} {fname}  UNITS={_u()} ,$")
        W.raw(OPTS)
        W.raw(HEAD)
        W.raw(_dim_row("M", 0.0, up, 0.0, None))
        W.raw(f"END OF DIMENSION {dn}")
    else:
        W.raw(f"{'':<12}COMMENT/REPT,")
        W.raw(f"{'':<12}{it.label}: controllo da completare manualmente")


def _inplane_axes(fr: DatumFrame, F: CylFeature) -> list[int]:
    v = fr.vec(F.axis)
    k, _ = g.nearest_axis(v)
    return [i for i in range(3) if i != k]


def _u() -> str:
    return "MM"
