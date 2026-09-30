# Demo di Alinea — copione (circa 8 minuti)

**Link:** <https://sarbu-alinea.static.hf.space>
**Pezzo di esempio:** supporto cuscinetto SUP-2040 (`esempi/supporto.stp`, `supporto_disegno.pdf`,
`supporto_scansione.pdf`)

## Prima di iniziare (5 minuti prima)

1. Apri il link e lancia una volta l'esempio *supporto cuscinetto · disegno scansionato*. La prima
   apertura scarica circa 30 MB (Python e OCR); poi restano in cache e la demo va veloce.
2. Tieni aperto in un'altra scheda il disegno, da mostrare come "quello che riceve il reparto":
   <https://sarbu-alinea.static.hf.space/esempi/supporto_disegno.pdf> (e la versione scansionata:
   <https://sarbu-alinea.static.hf.space/esempi/supporto_scansione.pdf>).
3. Usa Chrome o Edge aggiornati, a schermo intero; su un proiettore va bene lo zoom al 90%.

## Il pezzo

Supporto in C45, 160 × 100 × 25 mm, con perno Ø70 g6 alto 20 mm:

| Caratteristica | Cosa mostra |
|---|---|
| Ø40 H7 passante, ⌖ Ø0.02 A\|B\|C, ⟂ 0.01 A | accoppiamento ISO 286 calcolato, GD&T agganciati al foro giusto |
| sede Ø52 H7 prof. 10, cilindricità 0.01 | fori coassiali di diametro diverso, foro cieco |
| perno esterno Ø70 g6 | cerchio "OUT" (esterno) invece di un foro |
| 4× Ø11 ±0.1, ⌖ Ø0.3 (M) | pattern, modificatore MMC |
| 3× M6-6H prof. 12, ⌖ Ø0.2 | filetti riconosciuti dal preforo Ø5 del CAD |
| Ø10 sul fronte, Ø8 sul lato destro | due orientamenti diversi del tastatore (T1A90B180, T1A90B-90) |
| 160, 100, 20 ±0.05, planarità 0.02 | distanze tra piani, riferimento A |

## Copione

**1. Il problema (30 s).** "Scrivere a mano il programma PC-DMIS di un pezzo così richiede ore:
leggere il disegno, trovare ogni quota sul CAD, scegliere tastatori, allineamento, punti. Alinea lo fa
in pochi secondi partendo da STEP e disegno — anche scansionato."

**2. Carica (30 s).** Nella prima schermata fai notare la riga *"Tutto nel tuo browser: i file non
vengono caricati su nessun server"*. Scegli **Esempio: supporto cuscinetto · disegno scansionato** →
**Prova l'esempio**.

**3. Analisi (30 s).** Mentre scorre il registro: "legge il PDF, capisce che è una scansione e fa l'OCR,
poi legge la geometria reale dallo STEP: 25 facce, 12 cilindri, 13 piani".

**4. Revisione — i numeri (1 min).** In alto: fori trovati, quote lette, punti tastati, orientamenti del
tastatore, **tempo ciclo stimato**. Nella *Vista CAD* clicca il foro grande al centro: a destra si
evidenzia il blocco `CYL_F2` con le **coordinate vere** (X80 Y50) nel sistema A/B/C, e nella tabella la
riga Ø40 H7 con la tolleranza calcolata dalla ISO 286 (+0.025/0).

**5. Revisione — la fiducia (1,5 min).** Spiega i badge:
- **associato**: una sola corrispondenza possibile tra disegno e CAD;
- **assunto**: scelta automatica da guardare. Esempi: *Ø52 H7* (l'OCR ha perso il simbolo Ø, Alinea lo
  ricostruisce perché nel CAD c'è una sede Ø52), *Ø8* e *Ø10* ("PROF." sulla riga indica un foro);
- **solo CAD**: fori presenti nel modello ma non quotati, misurati con la tolleranza generale ISO 2768.

Passa il mouse su una riga con "ⓘ note" per leggere il motivo.

**6. Quello che l'OCR non ha letto (1,5 min).** Apri la scheda *Disegno* e mostra la scansione: alcune
quote (160, 100, la planarità) sono sporche e l'OCR non le legge. "Non inventa niente: quello che non
legge non lo mette." Aggiungila in 20 secondi:
**+ Aggiungi controllo** → Controllo *Distanza* → Feature *S5 · piano X−* → rispetto a *S6 · piano X+* →
Nom. `160`, +Toll `0.2`, −Toll `0.2`. Il programma si aggiorna subito con la `3D DISTANCE`.

**7. Riferimenti (30 s).** Cambia il riferimento B o C dal menu: il programma si rigenera con
l'allineamento nuovo (`ALIGNMENT/LEVEL/ROTATE/TRANS`).

**8. Il disegno vettoriale (1 min).** Torna su *← Nuovo pezzo*, scegli **supporto cuscinetto · PDF
vettoriale**: in meno di un secondo **16 caratteristiche su 16**, tutte associate. "Con i PDF esportati dal
CAD la lettura è esatta; con le scansioni si rivede in un minuto."

**9. Export (30 s).** **Scarica .txt** (programma da incollare in PC-DMIS, Edit Window in modalità
comandi) e **Piano .csv** (piano di controllo con nominali, limiti, riferimenti; si apre in Excel).

**10. Chiusura (30 s).** "Prima dell'esecuzione in DCC il programma si verifica in simulazione in
PC-DMIS. Per le scansioni difficili c'è la versione da installare sul PC con OCR LlamaParse, molto più
precisa sui simboli GD&T."

## Risultati attesi (per non essere colti di sorpresa)

| Esempio | Quote lette | Note |
|---|---|---|
| supporto · PDF vettoriale | 16 / 16 | tutte associate; "20" e planarità marcate *assunto* |
| supporto · scansione | 11 / 16 | mancano 160, 100, cilindricità, planarità e ⌖ Ø0.2 degli M6 |
| staffa · PDF vettoriale | 10 / 10 | la quota 20 richiede di girare il pezzo (faccia d'appoggio): avviso giallo |
| staffa · scansione | 10 / 10 | |

Tempo di analisi nel browser: circa 1 s per il vettoriale, 5-10 s per la scansione (dopo la prima apertura).

## Domande probabili

- **"I file finiscono su un server?"** No: nella versione web tutto gira nel browser. Il sito fornisce solo
  il programma, non riceve i file.
- **"Funziona con il .CAD di PC-DMIS?"** No, è un formato interno non documentato: da PC-DMIS si esporta
  lo STEP (File › Esporta › Modello › STEP AP214).
- **"È affidabile al 100%?"** No, ed è dichiarato: ogni associazione ha uno stato, le assunzioni si vedono,
  e il programma va verificato in simulazione. Il tempo risparmiato è nella stesura, non nel controllo.
- **"E l'anticollisione?"** Piano di sicurezza e avvicinamenti sul vettore sì, simulazione di collisione no:
  quella resta in PC-DMIS.
- **"Se il disegno ha più fogli?"** Legge fino a 4 pagine.
