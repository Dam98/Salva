"""Controlli statici sullo script PC-DMIS BASIC (non c'è PC-DMIS nei test: si verifica la struttura)."""
import re
from pathlib import Path

import pytest

from alinea.pipeline import analyze, make_program

EX = Path(__file__).resolve().parent.parent / "esempi"

# costanti dell'automazione PC-DMIS usate dallo script, verificate sulla documentazione Hexagon
# (OBTYPE, ENUM_FIELD_TYPES, FPOINT_TYPES, FVECTOR_TYPES, FDATA_DATASET, UNITTYPE, assi PCD_*)
DOCUMENTED = {
    "SET_COMMENT", "MAN_DCC_MODE", "SET_ACTIVE_TIP", "MOVE_POINT", "AUTO_CIRCLE", "AUTO_CYLINDER", "AUTO_PLANE",
    "AUTO_LINE", "AUTO_VECTOR_FEATURE", "CONST_BF_LINE", "START_ALIGN", "LEVEL_ALIGN", "ROTATE_ALIGN",
    "TRANS_ALIGN", "END_ALIGN", "DIMENSION_START_LOCATION", "DIMENSION_D_LOCATION", "DIMENSION_END_LOCATION",
    "DIMENSION_TRUE_START_POSITION", "DIMENSION_TRUE_X_LOCATION", "DIMENSION_TRUE_Y_LOCATION",
    "DIMENSION_TRUE_Z_LOCATION", "DIMENSION_TRUE_DF_LOCATION", "DIMENSION_TRUE_DIAM_LOCATION",
    "DIMENSION_TRUE_END_POSITION", "DIMENSION_3D_DISTANCE", "DIMENSION_FLATNESS", "DIMENSION_CYLINDRICITY",
    "DIMENSION_ROUNDNESS", "DIMENSION_PERPENDICULARITY", "DIMENSION_PARALLELISM", "DIMENSION_CONCENTRICITY",
    "NORM_RELEARN", "THEO_X", "THEO_Y", "THEO_Z", "ID", "REF_ID", "AXIS",
    "FPOINT_CENTROID", "FPOINT_STARTPOINT", "FPOINT_ENDPOINT", "FDATA_THEO", "FDATA_TARG",
    "FVECTOR_VECTOR", "FVECTOR_ANGLE_VECTOR", "FVECTOR_SURFACE_VECTOR", "FHITDATA_CENTROID", "FHITDATA_VECTOR",
    "PCD_XPLUS", "PCD_XMINUS", "PCD_YPLUS", "PCD_YMINUS", "PCD_ZPLUS", "PCD_ZMINUS", "MM",
}
KEYWORDS = {"DIM", "AS", "OBJECT", "BOOLEAN", "LONG", "STRING", "DOUBLE", "INTEGER", "SUB", "END", "IF", "THEN",
            "ELSE", "EXIT", "FOR", "TO", "NEXT", "NOT", "AND", "OR", "ON", "ERROR", "GOTO", "RESUME", "SET",
            "NOTHING", "TRUE", "FALSE", "IS", "OPEN", "OUTPUT", "PRINT", "CLOSE", "MAIN", "CHR", "LEFT", "UCASE",
            "INSTR", "TRIM", "STR", "ERR", "ERROR$", "MSGBOX", "INPUTBOX", "CREATEOBJECT"}


@pytest.fixture(scope="module")
def script():
    r = analyze(str(EX / "supporto.stp"), str(EX / "supporto_disegno.pdf"), {}, log=lambda m: None)
    return make_program(r["_fs"], r["plan"], {"part_name": "SUP-2040", "probe": "PROBE1"})["basic"]


def _logical_lines(text: str) -> list[str]:
    out, buf = [], ""
    for ln in text.split("\r\n"):
        code = _strip_comment(ln)
        if code.rstrip().endswith(" _"):
            buf += code.rstrip()[:-1] + " "
            continue
        out.append(buf + code)
        buf = ""
    return out


def _strip_comment(ln: str) -> str:
    in_s = False
    for i, ch in enumerate(ln):
        if ch == '"':
            in_s = not in_s
        elif ch == "'" and not in_s:
            return ln[:i]
    return ln


def _split_args(s: str) -> list[str]:
    args, cur, in_s = [], "", False
    for ch in s:
        if ch == '"':
            in_s = not in_s
        if ch == "," and not in_s:
            args.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        args.append(cur.strip())
    return args


def _subs(lines):
    subs, cur = {}, None
    for ln in lines:
        m = re.match(r"\s*Sub (\w+)\s*(?:\((.*)\))?\s*$", ln)
        if m:
            cur = m.group(1)
            params = [p.strip().split()[0] for p in _split_args(m.group(2) or "")]
            subs[cur] = {"params": params, "body": []}
            continue
        if re.match(r"\s*End Sub\s*$", ln):
            cur = None
            continue
        if cur:
            subs[cur]["body"].append(ln)
    return subs


def test_crlf_and_quotes(script):
    assert "\r\n" in script and "\n" not in script.replace("\r\n", "")
    for ln in script.split("\r\n"):
        assert _strip_comment(ln).count('"') % 2 == 0, ln


def test_no_unsupported_constructs(script):
    for bad in ("IIf(", "Err.Number", "Err.Clear", "CStr("):
        assert bad not in script


def test_blocks_balanced(script):
    lines = _logical_lines(script)
    subs = sum(1 for ln in lines if re.match(r"\s*Sub \w+", ln))
    assert subs == sum(1 for ln in lines if re.match(r"\s*End Sub\s*$", ln))
    fors = sum(1 for ln in lines if re.match(r"\s*For \w+ = ", ln))
    assert fors == sum(1 for ln in lines if re.match(r"\s*Next\b", ln))
    block_if = sum(1 for ln in lines if re.match(r"\s*If .* Then\s*$", ln))
    assert block_if == sum(1 for ln in lines if re.match(r"\s*End If\s*$", ln))


def test_labels_exist(script):
    for name, sub in _subs(_logical_lines(script)).items():
        labels = {m.group(1) for ln in sub["body"] for m in [re.match(r"\s*(\w+):\s*$", ln)] if m}
        for ln in sub["body"]:
            for m in re.finditer(r"\b(?:GoTo|Resume)\s+(\w+)", ln):
                if m.group(1) not in ("Next", "0"):
                    assert m.group(1) in labels, f"{name}: etichetta {m.group(1)} mancante"


def test_calls_match_signatures(script):
    lines = _logical_lines(script)
    subs = _subs(lines)
    assert "Main" in subs
    calls = 0
    for ln in subs["Main"]["body"]:
        m = re.match(r"\s{2}([A-Z]\w+)(?:\s+(.*))?$", ln)
        if not m or m.group(1) not in subs:
            continue
        args = _split_args(m.group(2) or "")
        assert len(args) == len(subs[m.group(1)]["params"]), ln
        calls += 1
    assert calls > 100


def test_constants_are_documented_and_params_do_not_shadow(script):
    lines = _logical_lines(script)
    subs = _subs(lines)
    params = {p.upper() for s in subs.values() for p in s["params"]}
    assert not params & {c.upper() for c in DOCUMENTED}, "un parametro coprirebbe una costante PC-DMIS"
    used = set()
    for ln in lines:
        code = re.sub(r'"[^"]*"', '""', ln)
        used |= set(re.findall(r"\b[A-Z][A-Z0-9_]{1,}\b", code))
    unknown = {u for u in used if "_" in u or u in ("ID", "AXIS", "MM")} - DOCUMENTED - KEYWORDS
    assert not unknown, unknown


def test_numbers_use_dot_and_moves_are_safe(script):
    body = script.split("Set Cmds = Part.Commands")[1]
    assert not re.search(r"\d,\d{4}\b", body.replace(", ", ";"))   # niente virgola decimale
    # ogni feature in DCC è preceduta da una salita al piano di sicurezza
    lines = [ln.strip() for ln in body.split("\r\n")]
    dcc = lines.index("Modo True")
    feats = [i for i, ln in enumerate(lines) if i > dcc and ln.split(" ")[0] in ("Cerchio", "Piano", "Linea", "PuntoVettore")]
    for i in feats:
        assert any(lines[j].startswith("Muovi") for j in range(max(0, i - 3), i)), lines[i]


def test_static_build_includes_every_imported_module():
    import ast
    import importlib.util

    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("build_static", root / "tools" / "build_static.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    included = set(mod.PY_MODULES)
    todo, seen = ["browser"], set()
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        tree = ast.parse((root / "alinea" / f"{name}.py").read_text(encoding="utf-8"))
        todo += [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level == 1 and n.module]
    assert seen <= included, f"moduli mancanti nella build web: {seen - included}"
