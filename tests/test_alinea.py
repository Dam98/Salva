from pathlib import Path

import pytest

from alinea.cad_features import extract_features, line_points
from alinea.drawing_parser import parse_drawing_text
from alinea.drawing_reader import read_drawing
from alinea.iso_tolerances import fit_limits, general_tolerance
from alinea.matching import build_plan
from alinea.pcdmis import Settings, build_frame, generate, tip_for
from alinea.pipeline import analyze, make_program
from alinea.step_reader import read_step, read_step_text

EX = Path(__file__).resolve().parent.parent / "esempi"


@pytest.fixture(scope="module")
def fs():
    return extract_features(read_step(str(EX / "staffa.stp")))


def test_step_reader_units_and_faces():
    m = read_step(str(EX / "staffa.stp"))
    assert m.unit == "mm"
    assert m.surface_counts == {"PLANE": 12, "CYLINDRICAL_SURFACE": 6}
    assert m.bbox_min == pytest.approx((0, 0, 0)) and m.bbox_max == pytest.approx((120, 80, 20))


def test_inch_units_are_converted():
    text = (EX / "staffa.stp").read_text(encoding="latin-1")
    text = text.replace("SI_UNIT(.MILLI.,.METRE.)", "CONVERSION_BASED_UNIT('INCH',#9999)", 1)
    m = read_step_text(text)
    assert m.unit == "inch"
    assert m.bbox_max[0] == pytest.approx(120 * 25.4)


def test_holes_recognized(fs):
    holes = {c.id: c for c in fs.cylinders}
    assert len(holes) == 6
    f1 = holes["F1"]
    assert f1.diameter == pytest.approx(25) and f1.through
    assert f1.entry == pytest.approx((60, 40, 20)) and f1.axis == pytest.approx((0, 0, 1))
    side = next(c for c in fs.cylinders if c.diameter == pytest.approx(8))
    assert not side.through and side.axis == pytest.approx((1, 0, 0)) and side.length == pytest.approx(30)
    assert [len(p.members) for p in fs.patterns] == [4]


def test_plane_areas(fs):
    top = next(p for p in fs.planes if p.normal == pytest.approx((0, 0, 1)) and p.area > 5000)
    assert top.area == pytest.approx(120 * 80 - 4 * 3.14159265 * 25 - 3.14159265 * 12.5 ** 2 - 240, rel=1e-3)


def test_line_points_same_height(fs):
    front = next(p for p in fs.planes if p.normal == pytest.approx((0, -1, 0)) and p.area > 1000)
    a, b = line_points(front, (1, 0, 0))
    assert a[2] == pytest.approx(b[2]) and b[0] - a[0] > 80


def test_iso_fits():
    assert fit_limits(25, "H7") == pytest.approx((0.021, 0.0))
    assert fit_limits(25, "g6") == pytest.approx((-0.007, -0.020))
    assert fit_limits(40, "k6") == pytest.approx((0.018, 0.002))
    assert fit_limits(50, "F7") == pytest.approx((0.050, 0.025))
    assert fit_limits(20, "K7") is None
    assert general_tolerance(50, "m") == 0.3


def test_parser_dims_and_gdt():
    txt = ("Ø25 H7\n|⌖|Ø0.05|A|B|C|\n4x Ø10 ±0.1\n| |Ø0.2(M)|A|B|C|\n80±0,1\n"
           "20 -0.05/-0.15\n⏥ 0.02\nM6-6H\nSCALA 1:2  REV 3\nISO 2768-f")
    chars, info = parse_drawing_text([txt])
    lab = {c.label: c for c in chars}
    assert lab["Ø25 H7"].upper == pytest.approx(0.021)
    pos = [c for c in chars if c.gdt == "position"]
    assert len(pos) == 2 and pos[0].parent == lab["Ø25 H7"].id and pos[1].modifier == "MMC"
    assert "Simbolo GD&T non leggibile" in pos[1].notes[0]
    assert lab["4× Ø10"].count == 4
    assert lab["80"].upper == pytest.approx(0.1)
    assert lab["20"].lower == pytest.approx(-0.15)
    assert any(c.kind == "thread" for c in chars)
    assert not any(c.nominal == 0.05 and c.kind == "diameter" for c in chars)  # Ø nel riquadro ≠ diametro
    assert info["general_class"] == "f"


def test_matching(fs):
    chars, info = parse_drawing_text(["Ø25 H7\n|⌖|Ø0.05|A|B|C|\n4x Ø10 ±0.1\n120 ±0.2"])
    plan = build_plan(fs, chars, info["general_class"])
    by = {i.label: i for i in plan.items}
    assert by["Ø25 H7"].features == ["F1"]
    assert sorted(by["4× Ø10"].features) == ["F2", "F3", "F4", "F5"]
    assert plan.datums["A"] == "S2"  # faccia superiore (tastabile)
    solo = [i for i in plan.items if i.status == "solo CAD"]
    assert len(solo) == 1 and solo[0].features == ["F6"]


def test_frame_and_program(fs):
    chars, info = parse_drawing_text(["Ø25 H7\n|⌖|Ø0.05|A|B|C|\nØ8 +0.1/0"])
    plan = build_plan(fs, chars, info["general_class"])
    fr = build_frame(fs, plan.datums)
    assert fr.to_local((60, 40, 20)) == pytest.approx((60, 40, 0))
    prog = generate(fs, plan, Settings(part_name="T"))
    t = prog.text
    assert "ALIGNMENT/LEVEL,ZPLUS,PLN_A" in t
    assert "ALIGNMENT/ROTATE,XPLUS,TO,LIN_B,ABOUT,ZPLUS" in t
    assert "THEO/<60.000,40.000,0.000>,<0.0000000,0.0000000,1.0000000>,25.000" in t
    assert "TIP/T1A90B-90" in t  # foro laterale su X+
    assert "TRUE POSITION OF CYLINDER CYL_F1" in t
    assert "<X,Y,Z>" not in t
    assert prog.stats["hits"] > 0 and not prog.warnings


def test_tip_mapping():
    assert tip_for((0, 0, 1))[0] == "T1A0B0"
    assert tip_for((1, 0, 0))[0] == "T1A90B-90"
    assert tip_for((-1, 0, 0))[0] == "T1A90B90"
    assert tip_for((0, 1, 0))[0] == "T1A90B0"
    assert tip_for((0, -1, 0))[0] == "T1A90B180"
    assert tip_for((0, 0, -1))[2] is False


def test_vector_pdf_end_to_end():
    d = read_drawing(str(EX / "staffa_disegno.pdf"))
    assert d.method == "pdf-text"
    r = analyze(str(EX / "staffa.stp"), str(EX / "staffa_disegno.pdf"), {}, log=lambda m: None)
    assert len(r["characteristics"]) >= 9
    assert r["drawing"]["general_class"] == "m"
    out = make_program(r["_fs"], r["plan"], {"part_name": "STAFFA-001"})
    assert "PART NAME  : STAFFA-001" in out["program"]
    assert out["csv"].startswith("﻿Pezzo;STAFFA-001")


def test_scan_without_ocr_is_reported():
    d = read_drawing(str(EX / "staffa_scansione.pdf"), llama_key=None, mode="auto")
    assert d.method in ("nessuno", "tesseract")
    if d.method == "nessuno":
        assert any("LlamaParse" in n for n in d.notes)


def test_pcdmis_cad_file_rejected(tmp_path):
    f = tmp_path / "pezzo.CAD"
    f.write_bytes(b"\xff\xff\xa6\x01\x0b\x00CPCDbc_coll")
    with pytest.raises(ValueError, match="STEP"):
        analyze(str(f), None, {}, log=lambda m: None)


def test_ocr_normalization():
    from alinea.drawing_parser import normalize, normalize_ocr

    raw = "4x O10 +0.1\nO |#|Q0.2(M)|A|BIC|\n@8 +0.1/0 PROF. 30\n{#|@0.05|A|B\\C|\n|.L]0.03|A]"
    out = normalize_ocr(normalize(raw)).split("\n")
    assert out[0] == "4x Ø10 ±0.1"
    assert out[1] == "|⌖|Ø0.2(M)|A|B|C|"
    assert out[2] == "Ø8 +0.1/0 PROF. 30"
    assert out[3] == "|⌖|Ø0.05|A|B|C|"
    assert out[4] == "|⟂|0.03|A|"


def test_spatial_gdt_linking():
    # testo OCR in ordine "sbagliato": l'aggancio usa le coordinate delle righe
    pages = ["Ø25 H7\n80 ±0.1\nØ8 +0.1/0\n|⌖|Ø0.05|A|B|C|"]
    layout = [[(500, 100, 580, 120), (100, 110, 160, 130), (800, 110, 900, 130), (500, 128, 640, 148)]]
    chars, _ = parse_drawing_text(pages, ocr=True, layout=layout)
    pos = next(c for c in chars if c.gdt == "position")
    assert next(c for c in chars if c.id == pos.parent).label == "Ø25 H7"


@pytest.mark.skipif(not __import__("alinea.drawing_reader", fromlist=["x"]).tesseract_available(),
                    reason="Tesseract non installato")
def test_scan_with_tesseract():
    r = analyze(str(EX / "staffa.stp"), str(EX / "staffa_scansione.pdf"), {"reader_mode": "tesseract"},
                log=lambda m: None)
    assert r["drawing"]["method"] == "tesseract"
    labels = [c["label"] for c in r["characteristics"]]
    assert "Ø25 H7" in labels and "4× Ø10" in labels
    items = {i["label"]: i for i in r["plan"]["items"]}
    assert items["Localizzazione Ø0.05 |A|B|C"]["features"] == ["F1"]
