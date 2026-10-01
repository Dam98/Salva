"""Script PC-DMIS BASIC (.bas) che crea e salva il programma .PRG dentro PC-DMIS.

Il formato .PRG è binario e proprietario: nessun programma esterno lo può scrivere. Lo crea
PC-DMIS stesso eseguendo questo script, che usa l'interfaccia di automazione documentata da
Hexagon (PartPrograms.Add, Commands.Add, FeatCmd, AlignCmnd, DimensionCmd, PutText).

Lo script segue lo stile del BASIC che PC-DMIS esporta da sé (Cypress Enable): un solo Sub Main,
nessun sottoprogramma, nessuna etichetta, solo funzioni dell'elenco ufficiale. Ogni comando è un
blocco protetto da "On Error Resume Next": se qualcosa non riesce, lo script prosegue e alla fine
mostra un rapporto (salvato anche in un file .log accanto al programma).
"""
from __future__ import annotations

from .geom import fmt

AXIS_PCD = {"XPLUS": "PCD_XPLUS", "XMINUS": "PCD_XMINUS", "YPLUS": "PCD_YPLUS", "YMINUS": "PCD_YMINUS",
            "ZPLUS": "PCD_ZPLUS", "ZMINUS": "PCD_ZMINUS",
            "XAXIS": "PCD_XPLUS", "YAXIS": "PCD_YPLUS", "ZAXIS": "PCD_ZPLUS"}
FORM_TYPES = {"flatness": "DIMENSION_FLATNESS", "cylindricity": "DIMENSION_CYLINDRICITY",
              "circularity": "DIMENSION_ROUNDNESS", "perpendicularity": "DIMENSION_PERPENDICULARITY",
              "parallelism": "DIMENSION_PARALLELISM"}
TP_AXES = {"X": "DIMENSION_TRUE_X_LOCATION", "Y": "DIMENSION_TRUE_Y_LOCATION", "Z": "DIMENSION_TRUE_Z_LOCATION"}


def _s(text) -> str:
    """Stringa BASIC tra virgolette (virgolette interne raddoppiate, niente a capo)."""
    return '"' + str(text).replace('"', '""').replace("\r", " ").replace("\n", " ") + '"'


def _n(x: float) -> str:
    return fmt(float(x), 4)


def _xyz(p) -> str:
    return ", ".join(_n(c) for c in p)


class _Script:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def add(self, *lines: str) -> None:
        self.lines.extend("  " + ln if ln else "" for ln in lines)

    def begin(self, obtype: str) -> None:
        """Nuovo comando: azzera l'errore e lo crea in coda al programma."""
        self.add("On Error Resume Next", "Err.Clear", f"Set DmisCommand = DmisCommands.Add({obtype}, True)")

    def check(self, descr: str) -> None:
        """Se qualcosa nel blocco non è riuscito, lo annota nel rapporto."""
        self.add("If Err.Number <> 0 Then",
                 "  NumErr = NumErr + 1",
                 f"  Registro = Registro & {_s(descr + ': ')} & Err.Description & Chr(13) & Chr(10)",
                 "Else",
                 "  NumOk = NumOk + 1",
                 "End If")


def _comment(sc: _Script, text: str) -> None:
    sc.begin("SET_COMMENT")
    sc.add(f"DmisCommand.CommentCommand.AddLine {_s(text)}")
    sc.check("Commento")


def _move(sc: _Script, p) -> None:
    sc.begin("MOVE_POINT")
    sc.add("retval = DmisCommand.SetToggleString(1, NORM_RELEARN, 0)",
           f"retval = DmisCommand.PutText({_s(_n(p[0]))}, THEO_X, 0)",
           f"retval = DmisCommand.PutText({_s(_n(p[1]))}, THEO_Y, 0)",
           f"retval = DmisCommand.PutText({_s(_n(p[2]))}, THEO_Z, 0)")
    sc.check("MOVE/POINT")


def _mode(sc: _Script, dcc: bool) -> None:
    """MODE/DCC o MODE/MANUAL. Il campo del modo non è documentato: lo cerca tra i campi del comando
    (quello che contiene MANUAL o DCC), lo commuta e verifica rileggendolo."""
    name = "DCC" if dcc else "MANUAL"
    if dcc:
        cond = 'InStr(Testo, "DCC") > 0 And InStr(Testo, "MAN") = 0'
    else:
        cond = 'InStr(Testo, "MANUAL") > 0 And InStr(Testo, "DCC") = 0'
    sc.begin("MAN_DCC_MODE")
    sc.add("If CampoModo = 0 Then",
           "  For Campo = 1 To 3000",
           "    Testo = \"\"",
           "    Testo = UCase(DmisCommand.GetText(Campo, 0))",
           "    If InStr(Testo, \"DCC\") > 0 Or InStr(Testo, \"MANUAL\") > 0 Then",
           "      CampoModo = Campo",
           "      Exit For",
           "    End If",
           "  Next Campo",
           "End If",
           "Trovato = False",
           "If CampoModo > 0 Then",
           "  For Voce = 1 To 4",
           "    retval = DmisCommand.SetToggleString(Voce, CampoModo, 0)",
           "    Testo = UCase(DmisCommand.GetText(CampoModo, 0))",
           f"    If {cond} Then",
           "      Trovato = True",
           "      Exit For",
           "    End If",
           "  Next Voce",
           "End If",
           "If Not Trovato Then",
           "  NumErr = NumErr + 1",
           f"  Registro = Registro & {_s('MODE: impostare a mano MODE/' + name)} & Chr(13) & Chr(10)",
           "End If")
    sc.check(f"MODE/{name}")


def _tip(sc: _Script, tip: str) -> None:
    sc.begin("SET_ACTIVE_TIP")
    sc.add(f"DmisCommand.ActiveTipCommand.TipID = {_s(tip)}")
    sc.check(f"TIP {tip}")


def _feature_head(sc: _Script, obtype: str, fid: str) -> None:
    sc.begin(obtype)
    sc.add("Set DmisFeat = DmisCommand.FeatureCommand", f"DmisFeat.ID = {_s(fid)}")


def _circle(sc: _Script, o: dict) -> None:
    _feature_head(sc, "AUTO_CYLINDER" if o["cylinder"] else "AUTO_CIRCLE", o["id"])
    sc.add(f"retval = DmisFeat.PutPoint(FPOINT_CENTROID, FDATA_THEO, {_xyz(o['center'])})",
           f"retval = DmisFeat.PutPoint(FPOINT_CENTROID, FDATA_TARG, {_xyz(o['center'])})",
           f"retval = DmisFeat.PutVector(FVECTOR_VECTOR, FDATA_THEO, {_xyz(o['vector'])})",
           f"retval = DmisFeat.PutVector(FVECTOR_VECTOR, FDATA_TARG, {_xyz(o['vector'])})",
           f"retval = DmisFeat.PutVector(FVECTOR_ANGLE_VECTOR, FDATA_THEO, {_xyz(o['angle_vec'])})",
           f"DmisFeat.TheoDiam = {_n(o['diam'])}",
           f"DmisFeat.Inner = {'True' if o['inner'] else 'False'}",
           f"DmisFeat.NumHits = {int(o['hits'])}",
           f"DmisFeat.Depth = {_n(o['depth'])}")
    if o["cylinder"]:
        sc.add(f"DmisFeat.TheoLength = {_n(o['length'])}", "DmisFeat.NumRows = 2")
    sc.check(o["id"])


def _plane(sc: _Script, o: dict) -> None:
    _feature_head(sc, "AUTO_PLANE", o["id"])
    sc.add(f"retval = DmisFeat.PutPoint(FPOINT_CENTROID, FDATA_THEO, {_xyz(o['centroid'])})",
           f"retval = DmisFeat.PutPoint(FPOINT_CENTROID, FDATA_TARG, {_xyz(o['centroid'])})",
           f"retval = DmisFeat.PutVector(FVECTOR_VECTOR, FDATA_THEO, {_xyz(o['normal'])})",
           f"retval = DmisFeat.PutVector(FVECTOR_VECTOR, FDATA_TARG, {_xyz(o['normal'])})",
           f"DmisFeat.NumHits = {len(o['hits'])}")
    sc.check(o["id"])
    # posizione dei punti: se PC-DMIS non la accetta usa la sua distribuzione (non è un errore grave)
    sc.add("Err.Clear")
    for n, h in enumerate(o["hits"], 1):
        sc.add(f"retval = DmisFeat.SetHit({n}, FHITDATA_CENTROID, FDATA_THEO, {_xyz(h)})",
               f"retval = DmisFeat.SetHit({n}, FHITDATA_VECTOR, FDATA_THEO, {_xyz(o['normal'])})")
    sc.add("If Err.Number <> 0 Then",
           f"  Registro = Registro & {_s(o['id'] + ': posizione dei punti non impostata, PC-DMIS usa la sua distribuzione')} & Chr(13) & Chr(10)",
           "End If")


def _line(sc: _Script, o: dict) -> None:
    _feature_head(sc, "AUTO_LINE", o["id"])
    sc.add(f"retval = DmisFeat.PutPoint(FPOINT_STARTPOINT, FDATA_THEO, {_xyz(o['start'])})",
           f"retval = DmisFeat.PutPoint(FPOINT_ENDPOINT, FDATA_THEO, {_xyz(o['end'])})",
           f"retval = DmisFeat.PutVector(FVECTOR_SURFACE_VECTOR, FDATA_THEO, {_xyz(o['normal'])})",
           "DmisFeat.NumHits = 2")
    sc.check(o["id"])


def _point(sc: _Script, o: dict) -> None:
    _feature_head(sc, "AUTO_VECTOR_FEATURE", o["id"])
    sc.add(f"retval = DmisFeat.PutPoint(FPOINT_CENTROID, FDATA_THEO, {_xyz(o['p'])})",
           f"retval = DmisFeat.PutPoint(FPOINT_CENTROID, FDATA_TARG, {_xyz(o['p'])})",
           f"retval = DmisFeat.PutVector(FVECTOR_VECTOR, FDATA_THEO, {_xyz(o['normal'])})",
           f"retval = DmisFeat.PutVector(FVECTOR_VECTOR, FDATA_TARG, {_xyz(o['normal'])})")
    sc.check(o["id"])


def _constr_line(sc: _Script, o: dict) -> None:
    sc.begin("CONST_BF_LINE")
    sc.add(f"retval = DmisCommand.PutText({_s(o['id'])}, ID, 0)",
           f"retval = DmisCommand.PutText({_s(o['feats'][0])}, REF_ID, 1)",
           f"retval = DmisCommand.PutText({_s(o['feats'][1])}, REF_ID, 2)")
    sc.check(o["id"])


def _align(sc: _Script, o: dict) -> None:
    k = o["kind"]
    if k == "LEVEL":
        # l'asse del LEVEL non ha una proprietà documentata: si scrive il testo e si verifica
        sc.begin("LEVEL_ALIGN")
        sc.add(f"DmisCommand.AlignmentCommand.FeatID = {_s(o['feat'])}",
               f"retval = DmisCommand.PutText({_s(o['axis'])}, AXIS, 0)",
               "Testo = UCase(DmisCommand.GetText(AXIS, 0))",
               "Trovato = False",
               f"If Testo = {_s(o['axis'])} Then Trovato = True",
               "If Not Trovato Then",
               "  For Voce = 1 To 6",
               "    retval = DmisCommand.SetToggleString(Voce, AXIS, 0)",
               "    Testo = UCase(DmisCommand.GetText(AXIS, 0))",
               f"    If Testo = {_s(o['axis'])} Then",
               "      Trovato = True",
               "      Exit For",
               "    End If",
               "  Next Voce",
               "End If",
               "If Not Trovato Then",
               "  NumErr = NumErr + 1",
               f"  Registro = Registro & {_s('LEVEL: impostare a mano l asse ' + o['axis'])} & Chr(13) & Chr(10)",
               "End If")
        sc.check(f"ALIGNMENT/LEVEL {o['axis']}")
    elif k == "ROTATE":
        sc.begin("ROTATE_ALIGN")
        sc.add(f"DmisCommand.AlignmentCommand.AXIS = {AXIS_PCD[o['axis']]}",
               f"DmisCommand.AlignmentCommand.AboutAxis = {AXIS_PCD[o['about']]}",
               f"DmisCommand.AlignmentCommand.FeatID = {_s(o['feat'])}")
        sc.check(f"ALIGNMENT/ROTATE {o['axis']} {o['feat']}")
    else:
        sc.begin("TRANS_ALIGN")
        sc.add(f"DmisCommand.AlignmentCommand.AXIS = {AXIS_PCD[o['axis']]}",
               f"DmisCommand.AlignmentCommand.FeatID = {_s(o['feat'])}")
        sc.check(f"ALIGNMENT/TRANS {o['axis']} {o['feat']}")


def _values(sc: _Script, nominal: float, plus: float, minus: float) -> None:
    sc.add(f"DmisCommand.DimensionCommand.NOMINAL = {_n(nominal)}",
           f"DmisCommand.DimensionCommand.Plus = {_n(plus)}",
           f"DmisCommand.DimensionCommand.Minus = {_n(minus)}")


def _dim(sc: _Script, o: dict) -> None:
    kind, did = o["kind"], o["id"]
    _comment(sc, o["label"])
    if kind == "diameter":
        sc.begin("DIMENSION_START_LOCATION")
        sc.add(f"DmisCommand.DimensionCommand.ID = {_s(did)}", f"DmisCommand.DimensionCommand.Feat1 = {_s(o['feat'])}")
        sc.check(f"{did} diametro {o['feat']}")
        sc.begin("DIMENSION_D_LOCATION")
        _values(sc, o["nominal"], o["plus"], o["minus"])
        sc.check(f"{did} riga D")
        sc.begin("DIMENSION_END_LOCATION")
        sc.check(f"{did} fine")
    elif kind == "position":
        dats = (list(o.get("datums") or []) + ["", "", ""])[:3]
        sc.begin("DIMENSION_TRUE_START_POSITION")
        sc.add(f"DmisCommand.DimensionCommand.ID = {_s(did)}", f"DmisCommand.DimensionCommand.Feat1 = {_s(o['feat'])}")
        for prop, d in zip(("Datum1", "DATUM2", "Datum3"), dats):
            if d:
                sc.add(f"DmisCommand.DimensionCommand.{prop} = {_s(d)}")
        sc.check(f"{did} posizione {o['feat']}")
        for ax, val in list(o["axes"].items())[:2]:
            sc.begin(TP_AXES[ax])
            _values(sc, val, 0, 0)
            sc.check(f"{did} asse {ax}")
        sc.begin("DIMENSION_TRUE_DF_LOCATION")
        _values(sc, o["diam"], 0, 0)
        sc.check(f"{did} DF")
        sc.begin("DIMENSION_TRUE_DIAM_LOCATION")
        _values(sc, 0, o["tol"], 0)
        sc.check(f"{did} TP")
        sc.begin("DIMENSION_TRUE_END_POSITION")
        sc.check(f"{did} fine")
        if o.get("modifier") in ("MMC", "LMC"):
            _comment(sc, f"Impostare il modificatore {o['modifier']} sulla dimensione {did}")
    elif kind == "distance":
        sc.begin("DIMENSION_3D_DISTANCE")
        sc.add(f"DmisCommand.DimensionCommand.ID = {_s(did)}",
               f"DmisCommand.DimensionCommand.Feat1 = {_s(o['feat'])}",
               f"DmisCommand.DimensionCommand.Feat2 = {_s(o['ref'])}")
        _values(sc, o["nominal"], o["plus"], o["minus"])
        sc.check(f"{did} distanza {o['feat']} {o['ref']}")
    elif kind in FORM_TYPES:
        ref = o.get("ref") or ""
        sc.begin(FORM_TYPES[kind])
        sc.add(f"DmisCommand.DimensionCommand.ID = {_s(did)}",
               f"DmisCommand.DimensionCommand.Feat1 = {_s(ref or o['feat'])}")
        if ref:
            sc.add(f"DmisCommand.DimensionCommand.Feat2 = {_s(o['feat'])}")
        _values(sc, 0, o["tol"], 0)
        sc.check(f"{did} {kind}")
    else:
        _comment(sc, f"{did}: controllo {kind} da inserire a mano")


HEADER = """' =====================================================================================
'  Alinea - script PC-DMIS che crea il programma {part}.PRG
'
'  COME SI USA:
'   1. In PC-DMIS apri l'editor degli script BASIC (Strumenti > Editor script BASIC)
'   2. File > Apri questo file .bas, poi Esegui (F5)
'   3. Rispondi alle domande (percorso del .PRG, tastatore, online/offline): lo script crea
'      feature, allineamenti e dimensioni, salva il programma e mostra un rapporto finale.
'   4. Prima dell'esecuzione in DCC verifica il programma con la simulazione di PC-DMIS.
' =====================================================================================

Sub Main
  Dim DmisApp As Object
  Dim DmisPart As Object
  Dim DmisCommands As Object
  Dim DmisCommand As Object
  Dim DmisFeat As Object
  Dim retval As Boolean
  Dim Trovato As Boolean
  Dim NumOk As Long
  Dim NumErr As Long
  Dim CampoModo As Long
  Dim Campo As Long
  Dim Voce As Long
  Dim Registro As String
  Dim Testo As String
  Dim Percorso As String
  Dim Tastatore As String
  Dim Macchina As String
  Dim Messaggio As String
  Dim Risposta As Integer

  NumOk = 0
  NumErr = 0
  CampoModo = 0
  Registro = ""
  Set DmisApp = CreateObject("PCDLRN.Application")
  Percorso = InputBox("Percorso completo del programma da creare (la cartella deve esistere):", "Alinea - {part}", CurDir & "\\{part}.PRG")
  If Percorso = "" Then Exit Sub
  Tastatore = InputBox("Nome del file tastatore (.PRB) da caricare:", "Alinea - {part}", {probe})
  If Tastatore = "" Then Exit Sub
  Risposta = MsgBox("PC-DMIS e' collegato alla macchina (online)?" & Chr(13) & "Si = CMM1     No = Offline", 36, "Alinea - {part}")
  If Risposta = 6 Then
    Macchina = "CMM1"
  Else
    Macchina = "Offline"
  End If

  On Error Resume Next
  Err.Clear
  Set DmisPart = DmisApp.PartPrograms.Add(Percorso, MM, Macchina, Tastatore)
  If Err.Number <> 0 Then
    MsgBox "Non riesco a creare il programma " & Percorso & Chr(13) & Err.Description & Chr(13) & "Controlla che la cartella esista e che il tastatore " & Tastatore & " sia definito.", 16, "Alinea"
    Exit Sub
  End If
  Set DmisCommands = DmisPart.Commands
"""

FOOTER = """
  ' ---------------------------------------------------------------- salvataggio e rapporto
  On Error Resume Next
  Err.Clear
  DmisPart.RefreshPart
  Err.Clear
  DmisPart.Save
  If Err.Number <> 0 Then
    Err.Clear
    DmisPart.SaveAs Percorso
  End If
  If Err.Number <> 0 Then
    NumErr = NumErr + 1
    Registro = Registro & "Salvataggio: " & Err.Description & Chr(13) & Chr(10)
  End If
  Err.Clear
  Open Percorso & ".alinea.log" For Output As #1
  Print #1, "Alinea - creazione di " & Percorso
  Print #1, "Comandi creati: " & NumOk & "   Problemi: " & NumErr
  Print #1, Registro
  Close #1
  Messaggio = "Programma creato: " & Percorso & Chr(13) & "Comandi creati: " & NumOk & Chr(13)
  If NumErr = 0 Then
    Messaggio = Messaggio & "Nessun problema." & Chr(13) & "Verificare il programma con la simulazione prima del DCC."
  Else
    Messaggio = Messaggio & "Problemi: " & NumErr & " (dettagli nel file " & Percorso & ".alinea.log)" & Chr(13) & Chr(13) & Left(Registro, 900)
  End If
  MsgBox Messaggio, 64, "Alinea - {part}"
End Sub
"""


def build_basic(ops: list[dict], part_name: str, probe: str) -> str:
    """Script BASIC che ricrea in PC-DMIS il programma descritto da `ops` (vedi pcdmis.generate)."""
    part = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in part_name) or "PEZZO"
    sc = _Script()
    pending_return: list | None = None

    def feature(fn, o):
        nonlocal pending_return
        fn(sc, o)
        if pending_return:
            for p in pending_return:
                _move(sc, p)
            pending_return = None

    for o in ops:
        k = o["op"]
        sc.add("")
        if k == "comment":
            for ln in o["lines"]:
                _comment(sc, ln)
        elif k == "mode":
            _mode(sc, o["mode"] == "DCC")
        elif k == "tip":
            _tip(sc, o["tip"])
        elif k == "safe_path":
            for p in o["points"]:
                _move(sc, p)
            pending_return = list(reversed(o["points"]))
        elif k == "circle":
            feature(_circle, o)
        elif k == "plane":
            if pending_return and o["hits"] and abs(o["normal"][2]) > 0.9:
                # piano orizzontale: scende sopra il primo punto di tastatura, non sopra il centro
                zc = pending_return[-1][2]
                h1 = o["hits"][0]
                _move(sc, [h1[0], h1[1], zc])
                pending_return = [[h1[0], h1[1], zc]] + pending_return
            feature(_plane, o)
        elif k == "line":
            feature(_line, o)
        elif k == "point":
            feature(_point, o)
        elif k == "constr_line":
            _constr_line(sc, o)
        elif k == "align_start":
            sc.begin("START_ALIGN")
            sc.add(f"retval = DmisCommand.PutText({_s(o['id'])}, ID, 0)",
                   f"DmisCommand.AlignmentCommand.InitID = {_s(o['recall'])}")
            sc.check(f"ALIGNMENT/START {o['id']}")
        elif k == "align":
            _align(sc, o)
        elif k == "align_end":
            sc.begin("END_ALIGN")
            sc.check("ALIGNMENT/END")
        elif k == "dim":
            _dim(sc, o)
        # move_point/move_clearplane/clearp del testo: nello script il percorso sicuro è esplicito
    body = "\n".join(sc.lines)
    text = (HEADER.replace("{part}", part).replace("{probe}", _s(probe)) + body
            + FOOTER.replace("{part}", part))
    # PC-DMIS BASIC (Cypress Enable) vuole CRLF
    return "\r\n".join(text.split("\n"))
