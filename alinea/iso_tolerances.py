"""Tolleranze ISO 286 (accoppiamenti) e ISO 2768 (tolleranze generali)."""
from __future__ import annotations

import re

# limiti superiori degli intervalli dimensionali (mm) - ISO 286-1
_RANGES = [3, 6, 10, 18, 30, 50, 80, 120, 180, 250, 315, 400, 500]

# gradi IT in µm
_IT = {
    4: [3, 4, 4, 5, 6, 7, 8, 10, 12, 14, 16, 18, 20],
    5: [4, 5, 6, 8, 9, 11, 13, 15, 18, 20, 23, 25, 27],
    6: [6, 8, 9, 11, 13, 16, 19, 22, 25, 29, 32, 36, 40],
    7: [10, 12, 15, 18, 21, 25, 30, 35, 40, 46, 52, 57, 63],
    8: [14, 18, 22, 27, 33, 39, 46, 54, 63, 72, 81, 89, 97],
    9: [25, 30, 36, 43, 52, 62, 74, 87, 100, 115, 130, 140, 155],
    10: [40, 48, 58, 70, 84, 100, 120, 140, 160, 185, 210, 230, 250],
    11: [60, 75, 90, 110, 130, 160, 190, 220, 250, 290, 320, 360, 400],
    12: [100, 120, 150, 180, 210, 250, 300, 350, 400, 460, 520, 570, 630],
}

# scostamento fondamentale superiore es (alberi a..h), µm
_ES = {
    "d": [-20, -30, -40, -50, -65, -80, -100, -120, -145, -170, -190, -210, -230],
    "e": [-14, -20, -25, -32, -40, -50, -60, -72, -85, -100, -110, -125, -135],
    "f": [-6, -10, -13, -16, -20, -25, -30, -36, -43, -50, -56, -62, -68],
    "g": [-2, -4, -5, -6, -7, -9, -10, -12, -14, -15, -17, -18, -20],
    "h": [0] * 13,
}
# scostamento fondamentale inferiore ei (alberi k..p), µm
_EI = {
    "k": [0, 1, 1, 1, 2, 2, 2, 3, 3, 4, 4, 4, 5],   # gradi 4..7; per gli altri gradi 0
    "m": [2, 4, 6, 7, 8, 9, 11, 13, 15, 17, 20, 21, 23],
    "n": [4, 8, 10, 12, 15, 17, 20, 23, 27, 31, 34, 37, 40],
    "p": [6, 12, 15, 18, 22, 26, 32, 37, 43, 50, 56, 62, 68],
}

_FIT_RE = re.compile(r"^(JS|js|[A-HKMNPa-hkmnp])(\d{1,2})$")


def _range_index(nominal: float) -> int | None:
    if nominal <= 0 or nominal > 500:
        return None
    for i, lim in enumerate(_RANGES):
        if nominal <= lim:
            return i
    return None


def fit_limits(nominal: float, fit: str) -> tuple[float, float] | None:
    """Scostamenti (superiore, inferiore) in mm per un accoppiamento tipo 'H7', 'g6'.

    Ritorna None se l'accoppiamento non è in tabella (in quel caso la tolleranza va
    inserita a mano nella revisione).
    """
    m = _FIT_RE.match(fit.strip())
    if not m:
        return None
    letter, grade = m.group(1), int(m.group(2))
    idx = _range_index(nominal)
    if idx is None or grade not in _IT:
        return None
    it = _IT[grade][idx]
    if letter in ("JS", "js"):
        return (it / 2000.0, -it / 2000.0)
    if letter.islower():
        if letter in _ES:
            es = _ES[letter][idx]
            return (es / 1000.0, (es - it) / 1000.0)
        if letter in _EI:
            ei = _EI[letter][idx]
            if letter == "k" and not (4 <= grade <= 7):
                ei = 0
            return ((ei + it) / 1000.0, ei / 1000.0)
        return None
    # fori: D..H ricavati per simmetria dagli alberi (EI = -es)
    low = letter.lower()
    if low in _ES:
        ei_hole = -_ES[low][idx]
        return ((ei_hole + it) / 1000.0, ei_hole / 1000.0)
    return None  # K, M, N, P fori richiedono il termine Δ: non gestiti automaticamente


# ISO 2768-1 tolleranze generali lineari (±, mm)
_G_RANGES = [(0.5, 3), (3, 6), (6, 30), (30, 120), (120, 400), (400, 1000), (1000, 2000), (2000, 4000)]
_G_TOL = {
    "f": [0.05, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5, None],
    "m": [0.1, 0.1, 0.2, 0.3, 0.5, 0.8, 1.2, 2.0],
    "c": [0.2, 0.3, 0.5, 0.8, 1.2, 2.0, 3.0, 4.0],
    "v": [None, 0.5, 1.0, 1.5, 2.5, 4.0, 6.0, 8.0],
}


def general_tolerance(nominal: float, cls: str = "m") -> float | None:
    cls = (cls or "m").lower()
    if cls not in _G_TOL:
        return None
    for i, (lo, hi) in enumerate(_G_RANGES):
        if lo <= nominal <= hi:
            return _G_TOL[cls][i]
    return None


def detect_general_class(text: str) -> str | None:
    """Cerca nel cartiglio l'indicazione tipo 'ISO 2768-mK' o 'UNI EN 22768-m'."""
    m = re.search(r"(?:ISO|UNI|EN|DIN)[\sA-Z]*2?2768\s*[-–]?\s*([fmcvFMCV])", text)
    return m.group(1).lower() if m else None


# passo grosso metrico ISO (per riconoscere i fori filettati nel CAD)
COARSE_PITCH = {1.6: 0.35, 2: 0.4, 2.5: 0.45, 3: 0.5, 4: 0.7, 5: 0.8, 6: 1.0, 8: 1.25, 10: 1.5, 12: 1.75,
                14: 2.0, 16: 2.0, 18: 2.5, 20: 2.5, 22: 2.5, 24: 3.0, 27: 3.0, 30: 3.5, 36: 4.0}
