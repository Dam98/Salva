"""Controlli statici sullo script PC-DMIS BASIC (Cypress Enable).

Non c'è PC-DMIS nei test: si verifica lo script contro la documentazione Hexagon del linguaggio
(elenco ufficiale di funzioni/istruzioni/parole riservate) e dell'automazione (costanti usate).
"""
import re
from pathlib import Path

import pytest

from alinea.pipeline import analyze, make_program

EX = Path(__file__).resolve().parent.parent / "esempi"

# "Functions, Statements, Reserved words - Quick Reference" (PC-DMIS BASIC, Hexagon)
RESERVED = set("""Abs Access Alias And Any App AppActivate Asc Atn As Base Beep Begin Binary ByVal Call Case ChDir
ChDrive Choose Chr Const Cos CurDir CDbl CInt CLng CSng CStr CVar CVDate Close CreateObject Date Day Declare Dim
Dir Do Loop Dialog DDEInitiate DDEExecute DateSerial DateValue Double Else ElseIf End EndIf EOF Eqv Erase Err
Error Exit Exp Explicit False FileCopy FileLen Fix For Next Format Function Get GetAttr GoTo Global GetObject Hex
Hour If Then Imp Input InputBox InStr Int Integer Is IsEmpty IsNull IsNumeric IsDate Kill LBound LCase Left Len
Let LOF Log Long LTrim Line Mid Minute MkDir Mod Month MsgBox Name Not Now Oct On Open OKButton Object Option
Optional Or Print Private Put Randomize Rem ReDim RmDir Rnd Return Rtrim Seek SendKeys Set SetAttr Second Select
Shell Sin Sqr Stop Str Sng Single Space Static Step String Sub StringComp Tan Text TextBox Time Timer TimeSerial
TimeValue Then Type Trim True To UBound UCase Until Val Variant VarType Write While Weekday Wend With Xor Year
Boolean Byte Currency""".split())
RESERVED_UP = {w.upper() for w in RESERVED}

# costanti dell'automazione PC-DMIS usate dallo script, verificate sulla documentazione Hexagon
# (OBTYPE, ENUM_FIELD_TYPES, FPOINT_TYPES, FVECTOR_TYPES, FDATA_DATASET, FHITDATA_TYPES, UNITTYPE, PCD_*)
DOCUMENTED = {
    "SET_COMMENT", "MAN_DCC_MODE", "SET_ACTIVE_TIP", "MOVE_POINT", "AUTO_CIRCLE", "AUTO_CYLINDER", "AUTO_PLANE",
    "AUTO_LINE", "AUTO_VECTOR_FEATURE", "CONST_BF_LINE", "START_ALIGN", "LEVEL_ALIGN", "ROTATE_ALIGN",
    "TRANS_ALIGN", "END_ALIGN", "DIMENSION_START_LOCATION", "DIMENSION_D_LOCATION", "DIMENSION_END_LOCATION",
    "DIMENSION_TRUE_START_POSITION", "DIMENSION_TRUE_X_LOCATION", "DIMENSION_TRUE_Y_LOCATION",
    "DIMENSION_TRUE_Z_LOCATION", "DIMENSION_TRUE_DF_LOCATION", "DIMENSION_TRUE_DIAM_LOCATION",
    "DIMENSION_TRUE_END_POSITION", "DIMENSION_3D_DISTANCE", "DIMENSION_FLATNESS", "DIMENSION_CYLINDRICITY",
    "DIMENSION_ROUNDNESS", "DIMENSION_PERPENDICULARITY", "DIMENSION_PARALLELISM",
    "NORM_RELEARN", "THEO_X", "THEO_Y", "THEO_Z", "ID", "REF_ID", "AXIS",
    "FPOINT_CENTROID", "FPOINT_STARTPOINT", "FPOINT_ENDPOINT", "FDATA_THEO", "FDATA_TARG",
    "FVECTOR_VECTOR", "FVECTOR_ANGLE_VECTOR", "FVECTOR_SURFACE_VECTOR", "FHITDATA_CENTROID", "FHITDATA_VECTOR",
    "PCD_XPLUS", "PCD_XMINUS", "PCD_YPLUS", "PCD_YMINUS", "PCD_ZPLUS", "PCD_ZMINUS", "MM",
}


@pytest.fixture(scope="module")
def script():
    r = analyze(str(EX / "supporto.stp"), str(EX / "supporto_disegno.pdf"), {}, log=lambda m: None)
    return make_program(r["_fs"], r["plan"], {"part_name": "SUP-2040", "probe": "PROBE1"})["basic"]


def _strip_comment(ln: str) -> str:
    in_s = False
    for i, ch in enumerate(ln):
        if ch == '"':
            in_s = not in_s
        elif ch == "'" and not in_s:
            return ln[:i]
    return ln


def _code(script: str) -> list[str]:
    """Righe di codice senza commenti né stringhe (le stringhe diventano "")."""
    return [re.sub(r'"[^"]*"', '""', _strip_comment(ln)) for ln in script.split("\r\n")]


def test_crlf_and_quotes(script):
    assert "\r\n" in script and "\n" not in script.replace("\r\n", "")
    for ln in script.split("\r\n"):
        assert _strip_comment(ln).count('"') % 2 == 0, ln


def test_only_main_no_labels_no_goto(script):
    code = _code(script)
    assert sum(1 for ln in code if re.match(r"\s*Sub\s", ln)) == 1
    assert sum(1 for ln in code if re.match(r"\s*End Sub\s*$", ln)) == 1
    for ln in code:
        assert not re.match(r"\s*\w+:\s*$", ln), f"etichetta: {ln}"
        # solo "On Error Resume Next" (documentato); niente salti a etichette
        assert not re.search(r"\b(GoTo|Gosub)\b", ln.replace("On Error Resume Next", ""), re.I), ln
        assert "Resume" not in ln.replace("On Error Resume Next", ""), ln
        assert " _" not in ln.rstrip()[-2:], "continuazione di riga non necessaria"


def test_no_undocumented_builtins(script):
    code = "\n".join(_code(script))
    for bad in ("Error$", "IIf(", "CStr(", "Nothing"):
        assert bad not in code, bad
    # ogni funzione chiamata senza oggetto davanti deve essere nell'elenco ufficiale
    for name in re.findall(r"(?<![\w.])([A-Za-z]\w*)\s*\(", code):
        assert name in RESERVED or name.upper() in RESERVED_UP, f"funzione non documentata: {name}"


def test_blocks_balanced(script):
    code = _code(script)
    block_if = sum(1 for ln in code if re.match(r"\s*If .* Then\s*$", ln))
    assert block_if == sum(1 for ln in code if re.match(r"\s*End If\s*$", ln))
    assert sum(1 for ln in code if re.match(r"\s*For \w+ = ", ln)) == sum(1 for ln in code if re.match(r"\s*Next\b", ln))


def test_variables_declared_and_not_reserved(script):
    code = _code(script)
    declared = {m.group(1).upper() for ln in code for m in [re.match(r"\s*Dim (\w+) As \w+", ln)] if m}
    assert declared
    clash = {d for d in declared if d in RESERVED_UP or d in DOCUMENTED}
    assert not clash, f"variabili con nome riservato o costante PC-DMIS: {clash}"
    for ln in code:
        m = re.match(r"\s*(?:Set\s+|For\s+)?(\w+)\s*=", ln)
        if m and m.group(1).upper() not in ("IF",):
            assert m.group(1).upper() in declared, f"variabile non dichiarata: {ln}"


def test_constants_are_documented(script):
    used = set()
    for ln in _code(script):
        used |= set(re.findall(r"(?<![\w.])([A-Z][A-Z0-9_]+)\b", ln))
    unknown = {u for u in used if ("_" in u or u in ("ID", "AXIS", "MM"))} - DOCUMENTED - RESERVED_UP
    assert not unknown, unknown


def test_numbers_and_safe_moves(script):
    body = script.split("Set DmisCommands = DmisPart.Commands")[1]
    assert not re.search(r"\d,\d{4}\b", body.replace(", ", ";"))      # niente virgola decimale
    adds = re.findall(r"Set DmisCommand = DmisCommands\.Add\((\w+), True\)", body)
    dcc = next(i for i, a in enumerate(adds) if a == "MAN_DCC_MODE" and i > 10)
    feats = ("AUTO_CIRCLE", "AUTO_CYLINDER", "AUTO_PLANE", "AUTO_LINE", "AUTO_VECTOR_FEATURE")
    for i, a in enumerate(adds):
        if i > dcc and a in feats:
            assert "MOVE_POINT" in adds[max(0, i - 3):i], f"feature {i} senza avvicinamento sicuro"


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
