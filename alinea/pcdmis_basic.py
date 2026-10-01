"""Script PC-DMIS BASIC (.bas) che crea e salva il programma .PRG dentro PC-DMIS.

Il formato .PRG è binario e proprietario: nessun programma esterno lo può scrivere. Lo crea
PC-DMIS stesso eseguendo questo script, che usa l'interfaccia di automazione documentata da
Hexagon (PartPrograms.Add, Commands.Add, FeatCmd, AlignCmnd, DimensionCmd, PutText).

Per i pochi campi non documentati (asse del LEVEL, modo DCC) lo script prova a impostare il
valore e lo verifica rileggendolo; ogni comando è creato in modo protetto e alla fine compare un
rapporto con quello che non è riuscito (salvato anche in un file .log accanto al programma).
"""
from __future__ import annotations

from .geom import fmt

AXIS_PCD = {"XPLUS": "PCD_XPLUS", "XMINUS": "PCD_XMINUS", "YPLUS": "PCD_YPLUS", "YMINUS": "PCD_YMINUS",
            "ZPLUS": "PCD_ZPLUS", "ZMINUS": "PCD_ZMINUS",
            "XAXIS": "PCD_XPLUS", "YAXIS": "PCD_YPLUS", "ZAXIS": "PCD_ZPLUS"}
FORM_TYPES = {"flatness": "DIMENSION_FLATNESS", "cylindricity": "DIMENSION_CYLINDRICITY",
              "circularity": "DIMENSION_ROUNDNESS", "perpendicularity": "DIMENSION_PERPENDICULARITY",
              "parallelism": "DIMENSION_PARALLELISM", "concentricity": "DIMENSION_CONCENTRICITY"}


def _s(text: str) -> str:
    """Stringa BASIC tra virgolette (le virgolette interne raddoppiate, niente a capo)."""
    return '"' + str(text).replace('"', '""').replace("\r", " ").replace("\n", " ") + '"'


def _n(x: float) -> str:
    return fmt(float(x), 4)


def _xyz(p) -> str:
    return ", ".join(_n(c) for c in p)


HEADER = r"""' =====================================================================================
'  Alinea - script PC-DMIS che crea il programma {part}.PRG
'  Generato automaticamente. Pezzo: {part}
'
'  COME SI USA (una volta per ogni pezzo):
'   1. In PC-DMIS chiudi i programmi aperti (o salvali).
'   2. Apri l'editor degli script BASIC (menu Strumenti / Tools > Editor script BASIC
'      oppure Basic Script Editor), poi File > Apri e scegli questo file .bas
'   3. Premi Esegui (F5). Lo script chiede dove salvare il .PRG, crea il programma con
'      feature, allineamenti e dimensioni, lo salva e mostra un rapporto finale.
'   4. Prima dell'esecuzione in DCC verifica il programma con la simulazione di PC-DMIS.
'
'  Ogni comando e' creato in modo protetto: se un comando non riesce lo script continua
'  e lo elenca nel rapporto (anche nel file .log accanto al .PRG).
' =====================================================================================

Dim App As Object
Dim Part As Object
Dim Cmds As Object
Dim C As Object
Dim Ultimo As Object
Dim OK As Boolean
Dim NumOk As Long
Dim NumErr As Long
Dim Registro As String
Dim Passo As String
Dim CampoModo As Long

Sub Annota(msg As String)
  NumErr = NumErr + 1
  Registro = Registro & msg & Chr(13) & Chr(10)
End Sub

' Crea un comando dopo l'ultimo inserito; imposta C e OK
Sub Nuovo(tipo As Long, descr As String)
  OK = False
  Passo = descr
  On Error GoTo NuovoErr
  If Not (Ultimo Is Nothing) Then Cmds.InsertionPointAfter Ultimo
  Set C = Cmds.Add(tipo, True)
  If C Is Nothing Then
    Annota descr & ": comando non creato"
    Exit Sub
  End If
  Set Ultimo = C
  OK = True
  NumOk = NumOk + 1
  Exit Sub
NuovoErr:
  Annota descr & ": " & Error$
  Resume NuovoFine
NuovoFine:
End Sub

Sub Commento(testo As String)
  Nuovo SET_COMMENT, "Commento"
  If Not OK Then Exit Sub
  On Error GoTo ComErr
  C.CommentCommand.AddLine testo
  Exit Sub
ComErr:
  Annota "Commento: " & Error$
  Resume ComFine
ComFine:
End Sub

' MODE/MANUAL o MODE/DCC. Il campo del modo non e' documentato: lo cerca e verifica rileggendolo.
Sub Modo(dcc As Boolean)
  Dim f As Long, k As Long, t As String, r As Boolean, nomeModo As String
  If dcc Then nomeModo = "DCC" Else nomeModo = "MANUAL"
  Nuovo MAN_DCC_MODE, "MODE/" & nomeModo
  If Not OK Then Exit Sub
  On Error Resume Next
  If CampoModo = 0 Then
    For f = 1 To 4000
      t = ""
      t = C.GetText(f, 0)
      If Err <> 0 Then Err = 0: t = ""
      If t <> "" Then
        CampoModo = f
        Exit For
      End If
    Next f
  End If
  If CampoModo = 0 Then
    Annota "MODE: campo del modo non trovato, impostare MODE/" & nomeModo & " a mano"
    Exit Sub
  End If
  For k = 1 To 4
    r = C.SetToggleString(k, CampoModo, 0)
    t = UCase(C.GetText(CampoModo, 0))
    If dcc And InStr(t, "DCC") > 0 And InStr(t, "MAN") = 0 Then Exit Sub
    If (Not dcc) And InStr(t, "DCC") = 0 And t <> "" Then Exit Sub
  Next k
  Annota "MODE: non sono riuscito a impostare " & nomeModo & " (verificare a mano)"
End Sub

Sub Punta(nome As String)
  Nuovo SET_ACTIVE_TIP, "TIP " & nome
  If Not OK Then Exit Sub
  On Error GoTo PuntaErr
  C.ActiveTipCommand.TipID = nome
  Exit Sub
PuntaErr:
  Annota "TIP " & nome & ": " & Error$
  Resume PuntaFine
PuntaFine:
End Sub

Sub Muovi(x As Double, y As Double, z As Double)
  Dim r As Boolean
  Nuovo MOVE_POINT, "MOVE/POINT"
  If Not OK Then Exit Sub
  On Error GoTo MuoviErr
  r = C.SetToggleString(1, NORM_RELEARN, 0)
  r = C.PutText(Trim(Str(x)), THEO_X, 0)
  r = C.PutText(Trim(Str(y)), THEO_Y, 0)
  r = C.PutText(Trim(Str(z)), THEO_Z, 0)
  Exit Sub
MuoviErr:
  Annota "MOVE/POINT: " & Error$
  Resume MuoviFine
MuoviFine:
End Sub

Sub Cerchio(nm As String, x As Double, y As Double, z As Double, i As Double, j As Double, k As Double, _
            ai As Double, aj As Double, ak As Double, d As Double, interno As Boolean, punti As Long, _
            prof As Double, cilindro As Boolean, lung As Double)
  Dim F As Object, r As Boolean
  If cilindro Then
    Nuovo AUTO_CYLINDER, nm
  Else
    Nuovo AUTO_CIRCLE, nm
  End If
  If Not OK Then Exit Sub
  On Error GoTo CerErr
  Set F = C.FeatureCommand
  Passo = nm & " (ID)": F.ID = nm
  Passo = nm & " (centro)"
  r = F.PutPoint(FPOINT_CENTROID, FDATA_THEO, x, y, z)
  r = F.PutPoint(FPOINT_CENTROID, FDATA_TARG, x, y, z)
  Passo = nm & " (vettore)"
  r = F.PutVector(FVECTOR_VECTOR, FDATA_THEO, i, j, k)
  r = F.PutVector(FVECTOR_VECTOR, FDATA_TARG, i, j, k)
  r = F.PutVector(FVECTOR_ANGLE_VECTOR, FDATA_THEO, ai, aj, ak)
  Passo = nm & " (diametro)": F.TheoDiam = d
  Passo = nm & " (interno/esterno)": F.Inner = interno
  Passo = nm & " (punti)": F.NumHits = punti
  Passo = nm & " (profondita')": F.Depth = prof
  If cilindro Then
    Passo = nm & " (lunghezza)": F.TheoLength = lung
    Passo = nm & " (livelli)": F.NumRows = 2
  End If
  C.ReDraw
  Exit Sub
CerErr:
  Annota Passo & ": " & Error$
  Resume Next
End Sub

Sub Piano(nm As String, x As Double, y As Double, z As Double, i As Double, j As Double, k As Double, punti As Long)
  Dim F As Object, r As Boolean
  Nuovo AUTO_PLANE, nm
  If Not OK Then Exit Sub
  On Error GoTo PiaErr
  Set F = C.FeatureCommand
  Passo = nm & " (ID)": F.ID = nm
  Passo = nm & " (centro)"
  r = F.PutPoint(FPOINT_CENTROID, FDATA_THEO, x, y, z)
  r = F.PutPoint(FPOINT_CENTROID, FDATA_TARG, x, y, z)
  Passo = nm & " (normale)"
  r = F.PutVector(FVECTOR_VECTOR, FDATA_THEO, i, j, k)
  r = F.PutVector(FVECTOR_VECTOR, FDATA_TARG, i, j, k)
  Passo = nm & " (punti)": F.NumHits = punti
  Exit Sub
PiaErr:
  Annota Passo & ": " & Error$
  Resume Next
End Sub

' Posizione di un punto di tastatura del piano (se PC-DMIS lo accetta; altrimenti usa la sua distribuzione)
Sub PuntoPiano(nm As String, n As Long, x As Double, y As Double, z As Double, i As Double, j As Double, k As Double)
  Dim r As Boolean
  On Error GoTo PPErr
  r = C.FeatureCommand.SetHit(n, FHITDATA_CENTROID, FDATA_THEO, x, y, z)
  r = C.FeatureCommand.SetHit(n, FHITDATA_VECTOR, FDATA_THEO, i, j, k)
  Exit Sub
PPErr:
  Annota nm & " punto " & n & ": posizione non impostata (" & Error$ & "), PC-DMIS usera' la sua distribuzione"
  Resume PPFine
PPFine:
End Sub

Sub Linea(nm As String, x1 As Double, y1 As Double, z1 As Double, x2 As Double, y2 As Double, z2 As Double, _
          i As Double, j As Double, k As Double)
  Dim F As Object, r As Boolean
  Nuovo AUTO_LINE, nm
  If Not OK Then Exit Sub
  On Error GoTo LinErr
  Set F = C.FeatureCommand
  Passo = nm & " (ID)": F.ID = nm
  Passo = nm & " (estremi)"
  r = F.PutPoint(FPOINT_STARTPOINT, FDATA_THEO, x1, y1, z1)
  r = F.PutPoint(FPOINT_ENDPOINT, FDATA_THEO, x2, y2, z2)
  Passo = nm & " (normale)"
  r = F.PutVector(FVECTOR_SURFACE_VECTOR, FDATA_THEO, i, j, k)
  Passo = nm & " (punti)": F.NumHits = 2
  Exit Sub
LinErr:
  Annota Passo & ": " & Error$
  Resume Next
End Sub

Sub PuntoVettore(nm As String, x As Double, y As Double, z As Double, i As Double, j As Double, k As Double)
  Dim F As Object, r As Boolean
  Nuovo AUTO_VECTOR_FEATURE, nm
  If Not OK Then Exit Sub
  On Error GoTo PVErr
  Set F = C.FeatureCommand
  Passo = nm & " (ID)": F.ID = nm
  Passo = nm & " (punto)"
  r = F.PutPoint(FPOINT_CENTROID, FDATA_THEO, x, y, z)
  r = F.PutPoint(FPOINT_CENTROID, FDATA_TARG, x, y, z)
  Passo = nm & " (vettore)"
  r = F.PutVector(FVECTOR_VECTOR, FDATA_THEO, i, j, k)
  r = F.PutVector(FVECTOR_VECTOR, FDATA_TARG, i, j, k)
  Exit Sub
PVErr:
  Annota Passo & ": " & Error$
  Resume Next
End Sub

Sub LineaCostruita(nm As String, f1 As String, f2 As String)
  Dim r As Boolean
  Nuovo CONST_BF_LINE, nm
  If Not OK Then Exit Sub
  On Error GoTo LCErr
  r = C.PutText(nm, ID, 0)
  r = C.PutText(f1, REF_ID, 1)
  r = C.PutText(f2, REF_ID, 2)
  Exit Sub
LCErr:
  Annota nm & ": " & Error$
  Resume Next
End Sub

Sub AllineaInizio(nm As String, richiama As String)
  Dim r As Boolean
  Nuovo START_ALIGN, "ALIGNMENT/START " & nm
  If Not OK Then Exit Sub
  On Error GoTo AIErr
  r = C.PutText(nm, ID, 0)
  C.AlignmentCommand.InitID = richiama
  Exit Sub
AIErr:
  Annota "Allineamento " & nm & ": " & Error$
  Resume Next
End Sub

' LEVEL: l'asse non ha una proprieta' documentata, quindi si imposta il testo e si verifica
Sub Livella(asse As String, feat As String)
  Dim r As Boolean, k As Long, t As String
  Nuovo LEVEL_ALIGN, "ALIGNMENT/LEVEL " & asse
  If Not OK Then Exit Sub
  On Error Resume Next
  C.AlignmentCommand.FeatID = feat
  If Err <> 0 Then Annota "LEVEL feature " & feat & ": " & Error$: Err = 0
  r = C.PutText(asse, AXIS, 0)
  t = UCase(C.GetText(AXIS, 0))
  If t = asse Then Exit Sub
  For k = 1 To 6
    r = C.SetToggleString(k, AXIS, 0)
    t = UCase(C.GetText(AXIS, 0))
    If t = asse Then Exit Sub
  Next k
  Annota "LEVEL: asse " & asse & " non verificato (letto '" & t & "'), controllare a mano"
End Sub

Sub Ruota(asse As Long, attorno As Long, feat As String, descr As String)
  Nuovo ROTATE_ALIGN, "ALIGNMENT/ROTATE " & descr
  If Not OK Then Exit Sub
  On Error GoTo RuErr
  C.AlignmentCommand.AXIS = asse
  C.AlignmentCommand.AboutAxis = attorno
  C.AlignmentCommand.FeatID = feat
  Exit Sub
RuErr:
  Annota "ROTATE " & descr & ": " & Error$
  Resume Next
End Sub

Sub Trasla(asse As Long, feat As String, descr As String)
  Nuovo TRANS_ALIGN, "ALIGNMENT/TRANS " & descr
  If Not OK Then Exit Sub
  On Error GoTo TrErr
  C.AlignmentCommand.AXIS = asse
  C.AlignmentCommand.FeatID = feat
  Exit Sub
TrErr:
  Annota "TRANS " & descr & ": " & Error$
  Resume Next
End Sub

Sub AllineaFine()
  Nuovo END_ALIGN, "ALIGNMENT/END"
End Sub

' Valori di una riga di dimensione (nominale e tolleranze)
Sub Valori(nominale As Double, piu As Double, meno As Double, descr As String)
  On Error GoTo ValErr
  C.DimensionCommand.NOMINAL = nominale
  C.DimensionCommand.Plus = piu
  C.DimensionCommand.Minus = meno
  Exit Sub
ValErr:
  Annota descr & ": " & Error$
  Resume Next
End Sub

Sub DimInizio(tipo As Long, nm As String, feat As String, descr As String)
  Nuovo tipo, descr
  If Not OK Then Exit Sub
  On Error GoTo DIErr
  C.DimensionCommand.ID = nm
  C.DimensionCommand.Feat1 = feat
  Exit Sub
DIErr:
  Annota descr & ": " & Error$
  Resume Next
End Sub

Sub Diametro(nm As String, feat As String, nominale As Double, piu As Double, meno As Double)
  DimInizio DIMENSION_START_LOCATION, nm, feat, nm & " (diametro " & feat & ")"
  Nuovo DIMENSION_D_LOCATION, nm & " riga D"
  If OK Then Valori nominale, piu, meno, nm & " riga D"
  Nuovo DIMENSION_END_LOCATION, nm & " fine"
End Sub

Sub Posizione(nm As String, feat As String, ax1 As Long, nom1 As Double, ax2 As Long, nom2 As Double, _
              diam As Double, toll As Double, rif1 As String, rif2 As String, rif3 As String)
  DimInizio DIMENSION_TRUE_START_POSITION, nm, feat, nm & " (posizione " & feat & ")"
  If OK Then
    On Error Resume Next
    If rif1 <> "" Then C.DimensionCommand.Datum1 = rif1
    If rif2 <> "" Then C.DimensionCommand.DATUM2 = rif2
    If rif3 <> "" Then C.DimensionCommand.Datum3 = rif3
    If Err <> 0 Then Annota nm & " riferimenti: " & Error$: Err = 0
    On Error GoTo 0
  End If
  Nuovo ax1, nm & " asse 1"
  If OK Then Valori nom1, 0, 0, nm & " asse 1"
  Nuovo ax2, nm & " asse 2"
  If OK Then Valori nom2, 0, 0, nm & " asse 2"
  Nuovo DIMENSION_TRUE_DF_LOCATION, nm & " DF"
  If OK Then Valori diam, 0, 0, nm & " DF"
  Nuovo DIMENSION_TRUE_DIAM_LOCATION, nm & " TP"
  If OK Then Valori 0, toll, 0, nm & " TP"
  Nuovo DIMENSION_TRUE_END_POSITION, nm & " fine"
End Sub

Sub Distanza(nm As String, f1 As String, f2 As String, nominale As Double, piu As Double, meno As Double)
  DimInizio DIMENSION_3D_DISTANCE, nm, f1, nm & " (distanza " & f1 & "-" & f2 & ")"
  If Not OK Then Exit Sub
  On Error GoTo DisErr
  C.DimensionCommand.Feat2 = f2
  Valori nominale, piu, meno, nm
  Exit Sub
DisErr:
  Annota nm & ": " & Error$
  Resume Next
End Sub

Sub Forma(tipo As Long, nm As String, feat As String, rif As String, toll As Double, descr As String)
  Dim primo As String
  If rif <> "" Then primo = rif Else primo = feat
  DimInizio tipo, nm, primo, nm & " (" & descr & ")"
  If Not OK Then Exit Sub
  On Error GoTo FoErr
  If rif <> "" Then C.DimensionCommand.Feat2 = feat
  Valori 0, toll, 0, nm
  Exit Sub
FoErr:
  Annota nm & ": " & Error$
  Resume Next
End Sub

Sub Main
  Dim percorso As String, macchina As String, risp As Integer, msg As String
  Set Ultimo = Nothing
  Set App = CreateObject("PCDLRN.Application")
  percorso = InputBox("Percorso completo del programma da creare (la cartella deve esistere):", _
                      "Alinea - {part}", "C:\PCDMIS\{part}.PRG")
  If percorso = "" Then Exit Sub
  risp = MsgBox("PC-DMIS e' collegato alla macchina (online)?" & Chr(13) & _
                "Si' = CMM1   No = Offline", 36, "Alinea - {part}")
  If risp = 6 Then macchina = "CMM1" Else macchina = "Offline"
  On Error GoTo NonCreato
  Set Part = App.PartPrograms.Add(percorso, MM, macchina, {probe})
  On Error GoTo 0
  If Part Is Nothing Then GoTo NonCreato
  Set Cmds = Part.Commands
"""

FOOTER = r"""
  ' ---------------------------------------------------------------- salvataggio e rapporto
  On Error Resume Next
  Part.RefreshPart
  Part.Save
  If Err <> 0 Then
    Err = 0
    Part.SaveAs percorso
  End If
  If Err <> 0 Then Annota "Salvataggio: " & Error$: Err = 0
  Open percorso & ".alinea.log" For Output As #1
  Print #1, "Alinea - creazione di " & percorso
  Print #1, "Comandi creati: " & NumOk & "   Problemi: " & NumErr
  Print #1, Registro
  Close #1
  msg = "Programma creato: " & percorso & Chr(13) & "Comandi creati: " & NumOk & Chr(13)
  If NumErr = 0 Then
    msg = msg & "Nessun problema." & Chr(13) & "Verificare il programma con la simulazione prima del DCC."
  Else
    msg = msg & "Problemi: " & NumErr & " (dettagli in " & percorso & ".alinea.log)" & Chr(13) & Chr(13) & Left(Registro, 900)
  End If
  MsgBox msg, 64, "Alinea - {part}"
  Exit Sub
NonCreato:
  MsgBox "Non riesco a creare il programma " & percorso & Chr(13) & Error$ & Chr(13) & _
         "Controlla che la cartella esista e che il tastatore {probe_plain} sia definito.", 16, "Alinea"
End Sub
"""


def build_basic(ops: list[dict], part_name: str, probe: str) -> str:
    """Script BASIC che ricrea in PC-DMIS il programma descritto da `ops` (vedi pcdmis.generate)."""
    part = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in part_name) or "PEZZO"
    out: list[str] = [HEADER.replace("{part}", part).replace("{probe}", _s(probe))]
    body: list[str] = []
    pending_return: list[list[float]] | None = None

    def emit(line: str) -> None:
        body.append("  " + line)

    for o in ops:
        k = o["op"]
        if k == "comment":
            for ln in o["lines"]:
                emit(f"Commento {_s(ln)}")
        elif k == "mode":
            emit(f"Modo {'True' if o['mode'] == 'DCC' else 'False'}")
        elif k == "tip":
            emit(f"Punta {_s(o['tip'])}")
        elif k == "safe_path":
            for p in o["points"]:
                emit(f"Muovi {_xyz(p)}")
            pending_return = list(reversed(o["points"]))
        elif k in ("circle", "plane", "line", "point"):
            if k == "circle":
                emit(f"Cerchio {_s(o['id'])}, {_xyz(o['center'])}, {_xyz(o['vector'])}, {_xyz(o['angle_vec'])}, "
                     f"{_n(o['diam'])}, {'True' if o['inner'] else 'False'}, {int(o['hits'])}, {_n(o['depth'])}, "
                     f"{'True' if o['cylinder'] else 'False'}, {_n(o['length'])}")
            elif k == "plane":
                if pending_return and o["hits"] and abs(o["normal"][2]) > 0.9:
                    # piano orizzontale: scende sopra il primo punto di tastatura, non sopra il centro
                    zc = pending_return[-1][2]
                    h1 = o["hits"][0]
                    emit(f"Muovi {_xyz([h1[0], h1[1], zc])}")
                    pending_return = [[h1[0], h1[1], zc]] + pending_return
                emit(f"Piano {_s(o['id'])}, {_xyz(o['centroid'])}, {_xyz(o['normal'])}, {len(o['hits'])}")
                for n, h in enumerate(o["hits"], 1):
                    emit(f"PuntoPiano {_s(o['id'])}, {n}, {_xyz(h)}, {_xyz(o['normal'])}")
            elif k == "line":
                emit(f"Linea {_s(o['id'])}, {_xyz(o['start'])}, {_xyz(o['end'])}, {_xyz(o['normal'])}")
            else:
                emit(f"PuntoVettore {_s(o['id'])}, {_xyz(o['p'])}, {_xyz(o['normal'])}")
            if pending_return:
                for p in pending_return:
                    emit(f"Muovi {_xyz(p)}")
                pending_return = None
        elif k == "constr_line":
            emit(f"LineaCostruita {_s(o['id'])}, {_s(o['feats'][0])}, {_s(o['feats'][1])}")
        elif k == "align_start":
            emit(f"AllineaInizio {_s(o['id'])}, {_s(o['recall'])}")
        elif k == "align":
            if o["kind"] == "LEVEL":
                emit(f"Livella {_s(o['axis'])}, {_s(o['feat'])}")
            elif o["kind"] == "ROTATE":
                emit(f"Ruota {AXIS_PCD[o['axis']]}, {AXIS_PCD[o['about']]}, {_s(o['feat'])}, "
                     f"{_s(o['axis'] + ' TO ' + o['feat'] + ' ABOUT ' + o['about'])}")
            else:
                emit(f"Trasla {AXIS_PCD[o['axis']]}, {_s(o['feat'])}, {_s(o['axis'] + ' ' + o['feat'])}")
        elif k == "align_end":
            emit("AllineaFine")
        elif k == "dim":
            emit(f"Commento {_s(o['label'])}")
            kind = o["kind"]
            if kind == "diameter":
                emit(f"Diametro {_s(o['id'])}, {_s(o['feat'])}, {_n(o['nominal'])}, {_n(o['plus'])}, {_n(o['minus'])}")
            elif kind == "position":
                axes = list(o["axes"].items())[:2]
                types = {"X": "DIMENSION_TRUE_X_LOCATION", "Y": "DIMENSION_TRUE_Y_LOCATION",
                         "Z": "DIMENSION_TRUE_Z_LOCATION"}
                dats = (list(o.get("datums") or []) + ["", "", ""])[:3]
                emit(f"Posizione {_s(o['id'])}, {_s(o['feat'])}, {types[axes[0][0]]}, {_n(axes[0][1])}, "
                     f"{types[axes[1][0]]}, {_n(axes[1][1])}, {_n(o['diam'])}, {_n(o['tol'])}, "
                     f"{_s(dats[0])}, {_s(dats[1])}, {_s(dats[2])}")
                if o.get("modifier") in ("MMC", "LMC"):
                    emit(f"Commento {_s('Impostare il modificatore ' + o['modifier'] + ' sulla dimensione ' + o['id'])}")
            elif kind == "distance":
                emit(f"Distanza {_s(o['id'])}, {_s(o['feat'])}, {_s(o['ref'])}, {_n(o['nominal'])}, "
                     f"{_n(o['plus'])}, {_n(o['minus'])}")
            elif kind in FORM_TYPES:
                emit(f"Forma {FORM_TYPES[kind]}, {_s(o['id'])}, {_s(o['feat'])}, {_s(o.get('ref') or '')}, "
                     f"{_n(o['tol'])}, {_s(kind)}")
        # move_point/move_clearplane/clearp del testo: nello script il percorso sicuro è esplicito (safe_path)
    out.append("\n".join(body))
    out.append(FOOTER.replace("{part}", part).replace("{probe_plain}", probe))
    # PC-DMIS BASIC (Cypress Enable) vuole CRLF
    return "\r\n".join("\n".join(out).split("\n")) + "\r\n"
