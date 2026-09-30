"""Interpretazione del testo di un disegno tecnico: quote, tolleranze, accoppiamenti, GD&T.

Il testo arriva dal livello testo del PDF, da LlamaParse (OCR) o da Tesseract, quindi
viene prima normalizzato per assorbire le confusioni tipiche dell'OCR (ø/Ø/⌀, virgola
decimale, '+/-', ecc.).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .iso_tolerances import detect_general_class, fit_limits

GDT_SYMBOLS = {
    "position": ["⌖", "⊕", "POSITION", "POSIZIONE", "LOCALIZZAZIONE", "TRUE POSITION"],
    "flatness": ["⏥", "FLATNESS", "PLANARITA", "PLANARITÀ"],
    "perpendicularity": ["⟂", "⊥", "PERPENDICULARITY", "PERPENDICOLARITA", "PERPENDICOLARITÀ"],
    "parallelism": ["∥", "//", "PARALLELISM", "PARALLELISMO"],
    "angularity": ["∠", "ANGULARITY", "INCLINAZIONE"],
    "circularity": ["○", "◯", "CIRCULARITY", "ROUNDNESS", "CIRCOLARITA", "CIRCOLARITÀ", "RotONDITA"],
    "cylindricity": ["⌭", "CYLINDRICITY", "CILINDRICITA", "CILINDRICITÀ"],
    "concentricity": ["◎", "⌾", "CONCENTRICITY", "CONCENTRICITA", "CONCENTRICITÀ", "COASSIALITA", "COASSIALITÀ"],
    "symmetry": ["⌯", "SYMMETRY", "SIMMETRIA"],
    "profile_surface": ["⌓", "SURFACE PROFILE", "PROFILO DI SUPERFICIE"],
    "profile_line": ["⌒", "LINE PROFILE", "PROFILO DI LINEA"],
    "runout": ["↗", "RUNOUT", "OSCILLAZIONE"],
    "total_runout": ["⌰", "TOTAL RUNOUT", "OSCILLAZIONE TOTALE"],
}
GDT_LABELS = {
    "position": "Localizzazione", "flatness": "Planarità", "perpendicularity": "Perpendicolarità",
    "parallelism": "Parallelismo", "angularity": "Inclinazione", "circularity": "Circolarità",
    "cylindricity": "Cilindricità", "concentricity": "Coassialità", "symmetry": "Simmetria",
    "profile_surface": "Profilo superficie", "profile_line": "Profilo linea", "runout": "Oscillazione",
    "total_runout": "Oscillazione totale", "unknown": "GD&T (tipo da verificare)",
}
# tipologie che richiedono riferimenti
GDT_NEEDS_DATUM = {"position", "perpendicularity", "parallelism", "angularity", "concentricity", "symmetry",
                   "runout", "total_runout"}


@dataclass
class Characteristic:
    id: str
    kind: str                     # diameter | linear | radius | thread | gdt
    nominal: float | None = None
    upper: float | None = None    # scostamento superiore (mm)
    lower: float | None = None    # scostamento inferiore (mm)
    count: int = 1
    fit: str | None = None
    thread: str | None = None
    gdt: str | None = None        # tipo GD&T
    gdt_value: float | None = None
    gdt_diameter_zone: bool = False
    modifier: str | None = None   # MMC | LMC
    datums: list[str] = field(default_factory=list)
    parent: str | None = None     # caratteristica dimensionale a cui è agganciato il GD&T
    source: str = ""
    page: int = 1
    line: int = 0
    tolerance_source: str = "disegno"   # disegno | ISO 286 | generale | mancante
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def label(self) -> str:
        if self.kind == "gdt":
            z = "Ø" if self.gdt_diameter_zone else ""
            d = "|".join(self.datums)
            return f"{GDT_LABELS.get(self.gdt or '', self.gdt)} {z}{self.gdt_value}" + (f" |{d}" if d else "")
        if self.kind == "thread":
            return f"{self.count}× {self.thread}" if self.count > 1 else str(self.thread)
        pre = {"diameter": "Ø", "radius": "R"}.get(self.kind, "")
        s = f"{pre}{_n(self.nominal)}"
        if self.fit:
            s += f" {self.fit}"
        if self.count > 1:
            s = f"{self.count}× {s}"
        return s


def _n(x: float | None) -> str:
    if x is None:
        return "?"
    return f"{x:.3f}".rstrip("0").rstrip(".")


# --------------------------------------------------------------------------- normalizzazione

_DIAM_CHARS = "Ø⌀∅øΦφ"


def normalize(text: str) -> str:
    t = text.replace("\r", "")
    for c in _DIAM_CHARS:
        t = t.replace(c, "Ø")
    t = re.sub(r"\b(?:DIA|DIAM|Diam|diam)\.?\s*(?=\d)", "Ø", t)
    t = t.replace("±", "±").replace("+/-", "±").replace("+-", "±").replace("-/+", "±")
    t = t.replace("−", "-").replace("–", "-").replace("—", "-")
    t = t.replace("×", "x").replace("Ⓜ", "(M)").replace("Ⓛ", "(L)").replace("Ⓢ", "(S)")
    # virgola decimale -> punto (solo tra cifre)
    t = re.sub(r"(?<=\d),(?=\d)", ".", t)
    # "Ø 25" -> "Ø25"
    t = re.sub(r"Ø\s+(?=\d)", "Ø", t)
    # LaTeX che a volte LlamaParse produce: $\pm$, ^{+0.021}_{0}
    t = t.replace("\\pm", "±").replace("$", "")
    t = re.sub(r"\^\{\s*([+-]?\d+(?:\.\d+)?)\s*\}\s*_\{\s*([+-]?\d+(?:\.\d+)?)\s*\}", r" \1/\2 ", t)
    t = re.sub(r"_\{\s*([+-]?\d+(?:\.\d+)?)\s*\}\s*\^\{\s*([+-]?\d+(?:\.\d+)?)\s*\}", r" \2/\1 ", t)
    return t


_FCF_SYMBOL_OCR = [
    (r"#|\+|⊕|Φ|ф|\$", "⌖"),
    (r"\.?L|⊥|_L|1L", "⟂"),
    (r"//|ll|11|\\\\", "∥"),
    (r"◎|@@|©", "◎"),
]


_OCR_SYM = {"+": "⌖", "#": "⌖", "⊕": "⌖", "L": "⟂", ".L": "⟂", "⊥": "⟂", "//": "∥"}
# riga che finisce come un riquadro di tolleranza: valore, eventuale (M), poi riferimenti separati
_FCF_TAIL = re.compile(r"\d(?:\.\d+)?\s*(?:\(M\)|\(L\))?\s*[|Il1\]\[]\s*[A-H](?:\s*[|Il1\]\[]\s*[A-H]){0,2}"
                       r"\s*[|Il1\]\[]?\s*$")


def normalize_ocr(text: str) -> str:
    """Correzioni per le confusioni tipiche dell'OCR sui disegni (Tesseract nativo e Tesseract.js).

    Il testo deve essere già passato da `normalize`, salvo il simbolo "$" che l'OCR usa spesso al posto
    di Ø e che `normalize` eliminerebbe: per questo va applicato `ocr_pre` prima di `normalize`.
    """
    out = []
    for line in text.split("\n"):
        l = line
        fcf = len(re.findall(r"[|\[\]{}]", l)) >= 2 or _FCF_TAIL.search(l)
        if fcf:
            # parentesi/graffe/backslash come separatori dei riquadri di tolleranza
            l = re.sub(r"[\[\]{}\\]", "|", l)
            # separatori letti come I, l o 1 attorno alle lettere dei riferimenti: "0.2(M)IAIBICI"
            for _ in range(4):
                l = re.sub(r"(?<=[\d)|])\s*[Il1]\s*(?=[A-H](?![a-z]))", "|", l)
                l = re.sub(r"(?<=\|[A-H])\s*[Il1](?=\s*[A-H]|\s*$)", "|", l)
            # simbolo in apertura: "O I+1Q0.2" / "|#1@0.05" / "|L10.03"
            l = re.sub(r"^\s*[O0o]?\s*[I|]\s*(\.?L|[+#⊕⊥]|//)\s*[1I|](?=\s*[Ø@Qo$O]?\d)",
                       lambda m: f"|{_OCR_SYM.get(m.group(1), m.group(1))}|", l)
            l = re.sub(r"\|\s*(\.?L|[+#⊕⊥]|//)\s*1(?=\s*[Ø@Qo$O]?\d)",
                       lambda m: f"|{_OCR_SYM.get(m.group(1), m.group(1))}|", l)
            # simbolo perso e "|" letto come 1: "|10.02|" -> "| |0.02|"
            l = re.sub(r"\|\s*1(0\.\d+)\s*\|", r"| |\1|", l)
            for pat, sym in _FCF_SYMBOL_OCR:
                l = re.sub(rf"\|\s*(?:{pat})\s*\|", f"|{sym}|", l)
            l = re.sub(r"^\s*[O0o]\s+(?=\|)", "", l)  # cerchietto del richiamo letto come "O"
        # Ø letto come @ O Q o
        l = re.sub(r"(?<![A-Za-z0-9.])[@OQo](?=\d)", "Ø", l)
        # ± perso: "120 +0.2" senza secondo scostamento -> ±
        l = re.sub(r"(?<=\d)\s+\+\s*(\d+(?:[.,]\d+)?)(?![\d.,])(?!\s*(?:/|[-+]?\s*\d))", r" ±\1", l)
        out.append(l)
    return "\n".join(out)


def merge_layout_lines(pages: list[str], layout: list[list[tuple]]) -> tuple[list[str], list[list[tuple]]]:
    """Unisce i frammenti OCR che stanno sulla stessa riga visiva, vicini in orizzontale
    (es. "4x" e "Ø10 ±0.1" riconosciuti separati)."""
    out_pages, out_layout = [], []
    for pno, page in enumerate(pages):
        lines = page.split("\n")
        boxes = layout[pno] if pno < len(layout) else []
        if len(boxes) != len(lines):
            out_pages.append(page)
            out_layout.append(boxes)
            continue
        rows = [[t, list(b)] for t, b in zip(lines, boxes)]
        merged = True
        while merged:
            merged = False
            rows.sort(key=lambda r: (r[1][1], r[1][0]))
            for i in range(len(rows)):
                for j in range(len(rows)):
                    if i == j:
                        continue
                    a, b = rows[i][1], rows[j][1]
                    h = min(a[3] - a[1], b[3] - b[1])
                    overlap = min(a[3], b[3]) - max(a[1], b[1])
                    gap = b[0] - a[2]
                    if h > 0 and overlap >= 0.5 * h and -0.3 * h <= gap <= 2.0 * h:
                        rows[i][0] = f"{rows[i][0]} {rows[j][0]}"
                        rows[i][1] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                        rows.pop(j)
                        merged = True
                        break
                if merged:
                    break
        rows.sort(key=lambda r: (r[1][1], r[1][0]))
        out_pages.append("\n".join(r[0] for r in rows))
        out_layout.append([tuple(r[1]) for r in rows])
    return out_pages, out_layout


def ocr_pre(text: str) -> str:
    """Passo da fare prima di `normalize` sul testo OCR: "$10" è quasi sempre "Ø10"."""
    return re.sub(r"(?<![A-Za-z0-9.\\])\$(?=\d)", "Ø", text)


# --------------------------------------------------------------------------- pattern

NUM = r"\d+(?:\.\d+)?"
COUNT = rf"(?:(?P<count>\d{{1,3}})\s*(?:x|X|FORI|fori|HOLES|holes|N\.?)\s*)?"
TOL = (rf"(?:\s*±\s*(?P<pm>{NUM})"
       rf"|\s*\(?\s*(?P<up>[+-]\s*{NUM}|0)\s*(?:/|\s)\s*(?P<lo>[+-]\s*{NUM}|0)\s*\)?)?")
FIT = r"(?:\s*(?P<fit>(?:JS|js|[A-HKMNPa-hkmnp])\d{1,2})\b)?"

RE_DIAM = re.compile(COUNT + rf"Ø(?P<nom>{NUM})" + FIT + TOL)
RE_THREAD = re.compile(COUNT + rf"\b(?P<th>M(?P<tnom>\d{{1,2}}(?:\.\d)?)(?:\s*x\s*(?P<pitch>{NUM}))?)"
                       rf"(?:\s*-\s*(?P<tcl>\d[gGhH]))?\b")
RE_RADIUS = re.compile(rf"(?<![A-Za-z])R(?P<nom>{NUM})" + TOL)
RE_LINEAR = re.compile(rf"(?<![\w.Ø/+-])(?P<nom>{NUM})" + FIT +
                       rf"(?:\s*±\s*(?P<pm>{NUM})"
                       rf"|\s*\(?\s*(?P<up>[+-]\s*{NUM}|0)\s*(?:/|\s)\s*(?P<lo>[+-]\s*{NUM}|0)\s*\)?)")
RE_DATUM_TAG = re.compile(r"(?:DATUM|RIF(?:ERIMENTO)?\.?)\s*([A-H])\b")


def _gdt_regex() -> re.Pattern:
    alts = []
    for key, syms in GDT_SYMBOLS.items():
        for s in sorted(syms, key=len, reverse=True):
            alts.append((key, re.escape(s)))
    body = "|".join(f"(?P<g_{i}>{a})" for i, (_, a) in enumerate(alts))
    return re.compile(
        rf"(?:{body})\s*[|\]\[:\s]*\s*(?P<zone>Ø)?\s*(?P<val>{NUM})(?P<mod>\s*(?:\(M\)|\(L\)|\(S\))|\s?[ML](?=\W|$))?"
        rf"(?P<dat>(?:[|\]\[,\s]+[A-H](?![a-z])(?:\s*-\s*[A-H])?(?:\s*\(M\))?){{0,3}})",
    ), [k for k, _ in alts]


RE_GDT, _GDT_KEYS = _gdt_regex()

# riquadro di tolleranza con simbolo non leggibile (font simbolico, OCR): "| |Ø0.05|A|B|"
RE_FCF_UNKNOWN = re.compile(
    rf"\|\s*(?P<sym>[^|Ø\d.]{{0,3}}|\d{{1,2}})\s*\|\s*(?P<zone>Ø)?\s*(?P<val>{NUM})\s*(?P<mod>\(M\)|\(L\))?\s*"
    rf"(?P<dat>(?:\|\s*[A-H](?:\s*-\s*[A-H])?\s*(?:\(M\))?\s*){{0,3}})\|?")

# parole da ignorare (cartiglio): una quota lineare su queste righe è quasi sempre rumore
_TITLE_WORDS = re.compile(r"(SCALA|SCALE|DATA|DATE|REV|FOGLIO|SHEET|PESO|WEIGHT|DISEGN|DRAWN|CODICE|"
                          r"MATERIAL|APPROV|FORMATO|A[0-4]\b|ISO\s*\d|UNI|EN\s*\d|DIN)", re.I)


def _f(s: str | None) -> float | None:
    if s is None:
        return None
    s = s.replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return None


def _tol_from_match(m: re.Match) -> tuple[float | None, float | None]:
    gd = m.groupdict()
    if gd.get("pm"):
        v = _f(gd["pm"])
        return v, -v if v is not None else None
    if gd.get("up") is not None and gd.get("lo") is not None:
        a, b = _f(gd["up"]), _f(gd["lo"])
        if a is None or b is None:
            return None, None
        return max(a, b), min(a, b)
    return None, None


def parse_drawing_text(pages: list[str], general_class: str | None = None, ocr: bool = False,
                       layout: list[list[tuple]] | None = None) -> tuple[list[Characteristic], dict]:
    """Estrae le caratteristiche dal testo (una stringa per pagina).

    `ocr=True` applica anche le correzioni per le confusioni tipiche dell'OCR.
    """
    if ocr and layout:
        pages, layout = merge_layout_lines(pages, layout)
    if ocr:
        pages = [normalize_ocr(normalize(ocr_pre(p))) for p in pages]
    full = "\n".join(pages)
    gclass = general_class or detect_general_class(normalize(full))
    chars: list[Characteristic] = []
    datums_seen: set[str] = set()
    seen_keys: set[tuple] = set()

    def add(ch: Characteristic, key: tuple) -> Characteristic | None:
        if key in seen_keys:
            # stessa quota ripetuta (es. vista e sezione): conta una volta sola
            return None
        seen_keys.add(key)
        ch.id = f"C{len(chars) + 1}"
        chars.append(ch)
        return ch

    boxes: dict[str, tuple] = {}          # id caratteristica -> riquadro della sua riga (se noto)
    pending_links: list[tuple[Characteristic, tuple]] = []

    for pno, page in enumerate(pages, 1):
        text = normalize(page)
        page_layout = layout[pno - 1] if layout and pno - 1 < len(layout) else None
        prev_line_dim: Characteristic | None = None
        for lno, line in enumerate(text.split("\n"), 1):
            if not line.strip():
                continue
            # 1) riquadri GD&T per primi: il loro "Ø0.1" non è un diametro
            gdt_matches = [m for m in RE_GDT.finditer(line)
                           if 0 < float(m.group("val")) <= 5]
            consumed: list[tuple[int, int]] = [m.span() for m in gdt_matches]
            unknown_fcf = [m for m in RE_FCF_UNKNOWN.finditer(line)
                           if 0 < float(m.group("val")) <= 5
                           and all(m.end() <= a or m.start() >= b for a, b in consumed)]
            consumed += [m.span() for m in unknown_fcf]
            dims_in_line: list[tuple[int, Characteristic]] = []

            def free(a: int, b: int) -> bool:
                return all(b <= x or a >= y for x, y in consumed)

            # 2) filetti
            for m in RE_THREAD.finditer(line):
                if not free(*m.span()):
                    continue
                cnt = int(m.group("count") or 1)
                th = m.group("th").replace(" ", "") + (f"-{m.group('tcl')}" if m.group("tcl") else "")
                ch = Characteristic(id="", kind="thread", nominal=float(m.group("tnom")), count=cnt,
                                    thread=th, source=m.group(0).strip(), page=pno, line=lno,
                                    tolerance_source="filetto")
                if add(ch, ("th", th, cnt, pno, lno)):
                    dims_in_line.append((m.start(), ch))
                consumed.append(m.span())

            # 3) diametri
            for m in RE_DIAM.finditer(line):
                if not free(*m.span()):
                    continue
                nom = float(m.group("nom"))
                if nom <= 0 or nom > 3000:
                    continue
                up, lo = _tol_from_match(m)
                ch = Characteristic(id="", kind="diameter", nominal=nom, count=int(m.group("count") or 1),
                                    fit=m.group("fit"), upper=up, lower=lo, source=m.group(0).strip(),
                                    page=pno, line=lno)
                _complete_tolerance(ch, gclass)
                if add(ch, ("d", nom, ch.fit, up, lo, ch.count, pno, lno, m.start())):
                    dims_in_line.append((m.start(), ch))
                consumed.append(m.span())

            # 4) raggi con tolleranza
            for m in RE_RADIUS.finditer(line):
                if not free(*m.span()):
                    continue
                up, lo = _tol_from_match(m)
                if up is None:
                    continue
                ch = Characteristic(id="", kind="radius", nominal=float(m.group("nom")), upper=up, lower=lo,
                                    source=m.group(0).strip(), page=pno, line=lno)
                if add(ch, ("r", ch.nominal, up, lo, pno, lno)):
                    dims_in_line.append((m.start(), ch))
                consumed.append(m.span())

            # 5) quote lineari con tolleranza esplicita (non nel cartiglio)
            if not _TITLE_WORDS.search(line):
                for m in RE_LINEAR.finditer(line):
                    if not free(*m.span()):
                        continue
                    nom = float(m.group("nom"))
                    up, lo = _tol_from_match(m)
                    if up is None or nom <= 0 or nom > 5000:
                        continue
                    ch = Characteristic(id="", kind="linear", nominal=nom, upper=up, lower=lo,
                                        fit=m.group("fit"), source=m.group(0).strip(), page=pno, line=lno)
                    if add(ch, ("l", nom, up, lo, pno, lno, m.start())):
                        dims_in_line.append((m.start(), ch))
                    consumed.append(m.span())

            # 6) GD&T: aggancio alla quota che lo precede sulla riga (o alla riga sopra)
            dims_in_line.sort(key=lambda t: t[0])
            line_box = page_layout[lno - 1] if page_layout and lno - 1 < len(page_layout) else None
            if line_box:
                for _, c in dims_in_line:
                    boxes[c.id] = (pno, line_box)
            for m in gdt_matches:
                key = next((_GDT_KEYS[i] for i in range(len(_GDT_KEYS)) if m.group(f"g_{i}")), None)
                if key is None:
                    continue
                val = float(m.group("val"))
                dats = re.findall(r"[A-H]", m.group("dat") or "")
                mod = (m.group("mod") or "").upper()
                modifier = "MMC" if "M" in mod else ("LMC" if "L" in mod else None)
                ch = Characteristic(id="", kind="gdt", gdt=key, gdt_value=val,
                                    gdt_diameter_zone=bool(m.group("zone")), modifier=modifier,
                                    datums=dats, source=m.group(0).strip(), page=pno, line=lno)
                before = [c for pos, c in dims_in_line if pos < m.start()]
                parent = before[-1] if before else (prev_line_dim if not dims_in_line and not line_box else None)
                if parent is not None and key != "flatness" and parent.kind in ("diameter", "thread"):
                    ch.parent = parent.id
                    if ocr and not before:
                        ch.notes.append("Aggancio alla quota dedotto dall'ordine del testo OCR: verificare")
                elif not before and line_box and key != "flatness":
                    pending_links.append((ch, (pno, line_box)))
                if key in GDT_NEEDS_DATUM and not dats:
                    ch.notes.append("Riferimenti non letti nel riquadro: verificare")
                datums_seen.update(dats)
                add(ch, ("g", key, val, tuple(dats), pno, lno, m.start()))

            for m in unknown_fcf:
                dats = re.findall(r"[A-H]", m.group("dat") or "")
                zone = bool(m.group("zone"))
                # Ø + riferimenti: quasi sempre una localizzazione; altrimenti tipo da scegliere
                sym = (m.group("sym") or "").strip()
                key = "position" if zone and dats else ("flatness" if not dats and not sym.isalnum() else None)
                ch = Characteristic(id="", kind="gdt", gdt=key or "unknown", gdt_value=float(m.group("val")),
                                    gdt_diameter_zone=zone, modifier="MMC" if m.group("mod") == "(M)" else None,
                                    datums=dats, source=m.group(0).strip(), page=pno, line=lno)
                ch.notes.append("Simbolo GD&T non leggibile (font simbolico/OCR): "
                                + (f"assunto {GDT_LABELS[key]}" if key else "scegliere il tipo di controllo"))
                before = [c for pos, c in dims_in_line if pos < m.start()]
                parent = before[-1] if before else (prev_line_dim if not dims_in_line and not line_box else None)
                if parent is not None and key != "flatness" and parent.kind in ("diameter", "thread"):
                    ch.parent = parent.id
                elif not before and line_box and key != "flatness":
                    pending_links.append((ch, (pno, line_box)))
                datums_seen.update(dats)
                add(ch, ("g?", val_key(m), tuple(dats), pno, lno, m.start()))

            if dims_in_line:
                prev_line_dim = dims_in_line[-1][1]
            elif not gdt_matches and not unknown_fcf:
                prev_line_dim = None

            for m in RE_DATUM_TAG.finditer(line):
                datums_seen.add(m.group(1))

    # aggancio spaziale (OCR con coordinate): la quota subito sopra il riquadro, allineata a sinistra
    by_id = {c.id: c for c in chars}
    for ch, (pno, fb) in pending_links:
        h = max(1.0, fb[3] - fb[1])
        best = None
        for cid, (cp, db) in boxes.items():
            c = by_id.get(cid)
            if cp != pno or c is None or c.kind not in ("diameter", "thread"):
                continue
            dy = fb[1] - db[3]            # distanza verticale sotto la quota
            dx = abs(fb[0] - db[0])
            if -0.6 * h <= dy <= 3.0 * h and dx <= 8 * h:
                score = abs(dy) + 0.3 * dx
                if best is None or score < best[0]:
                    best = (score, c)
        if best:
            ch.parent = best[1].id

    # rinumera dopo eventuali rimozioni
    idmap = {}
    for i, ch in enumerate(chars, 1):
        idmap[ch.id] = f"C{i}"
        ch.id = f"C{i}"
    for ch in chars:
        if ch.parent:
            ch.parent = idmap.get(ch.parent)

    info = {"general_class": gclass, "datums": sorted(datums_seen), "chars_found": len(chars)}
    return chars, info


def val_key(m: re.Match) -> float:
    return float(m.group("val"))


def _complete_tolerance(ch: Characteristic, gclass: str | None) -> None:
    if ch.upper is not None:
        ch.tolerance_source = "disegno"
        return
    if ch.fit and ch.nominal:
        lim = fit_limits(ch.nominal, ch.fit)
        if lim:
            ch.upper, ch.lower = lim
            ch.tolerance_source = "ISO 286"
            return
        ch.notes.append(f"Accoppiamento {ch.fit} non in tabella: inserire gli scostamenti")
        ch.tolerance_source = "mancante"
        return
    from .iso_tolerances import general_tolerance
    t = general_tolerance(ch.nominal or 0, gclass or "m")
    if t is not None:
        ch.upper, ch.lower = t, -t
        ch.tolerance_source = f"generale ISO 2768-{gclass or 'm'}" + ("" if gclass else " (assunta)")
    else:
        ch.tolerance_source = "mancante"


def text_quality(text: str) -> float:
    """Frazione di caratteri "utili" (cifre, lettere, simboli di quotatura) sul totale non-spazio."""
    s = re.sub(r"\s+", "", text)
    if not s:
        return 0.0
    good = sum(1 for c in s if c.isalnum() or c in "Ø±.,+-/()°")
    return good / len(s)
