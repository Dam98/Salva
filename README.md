# Alinea — CAD + disegno → routine di misura PC-DMIS

Alinea legge il **modello STEP** e il **disegno tecnico** (PDF vettoriale, PDF scansionato o immagine),
riconosce fori, piani e pattern con le **coordinate reali** del CAD, interpreta quote, accoppiamenti
ISO e GD&T dal disegno, li associa automaticamente e scrive il **programma PC-DMIS** (testo dei comandi)
pronto da incollare, più il **piano di controllo in CSV**.

Si usa in tre modi, con la stessa interfaccia:

| | Dove gira | OCR delle scansioni | Per chi |
|---|---|---|---|
| **Webapp nel browser** (Hugging Face) | tutto nel browser di chi la usa | Tesseract.js | chiunque abbia il link, gratis |
| **Locale** (`avvia.bat`) | sul tuo PC Windows | LlamaParse e/o Tesseract | uso quotidiano, massima precisione OCR |
| **Server** (Docker/Render) | su un server, con password | LlamaParse e/o Tesseract | team, con la tua chiave LlamaParse |

## Webapp nel browser (Hugging Face Spaces, gratis)

La versione web gira **interamente nel browser**: il codice Python di Alinea viene eseguito con
[Pyodide](https://pyodide.org) e le scansioni sono lette con [Tesseract.js](https://tesseract.projectnaptha.com).
I file STEP e i disegni **non vengono caricati su nessun server**. È pubblicata come *Space statico* di
Hugging Face (gratuito, senza carta) all'indirizzo `https://<tuonome>-alinea.static.hf.space`.

Differenze rispetto alla versione locale/server:
- niente LlamaParse (non accetta chiamate dirette da una pagina web): l'OCR delle scansioni è Tesseract.js;
- la prima apertura scarica circa 30 MB (Python, OCR, lingue); poi il browser li tiene in cache;
- niente password: non serve, perché non c'è un server che riceve i file.

**Pubblicazione** (una volta sola): la GitHub Action `.github/workflows/deploy-huggingface.yml` esegue i
test, costruisce il sito (`tools/build_static.py`) e lo carica sullo Space a ogni push.

1. Crea un account su <https://huggingface.co/join> e un token **Write** su
   <https://huggingface.co/settings/tokens>.
2. Su GitHub: **Settings → Secrets and variables → Actions → New repository secret**:
   `HF_TOKEN` = il token. (Facoltativo: variabile `HF_SPACE` = `<tuonome>/alinea`; se manca si usa
   proprio questo nome.)
3. **Actions → Deploy su Hugging Face → Run workflow**. Alla fine il log mostra l'indirizzo dell'app.

Per provarla in locale: `python tools/build_static.py` e poi `python -m http.server -d dist 8000`.

## Server con password (Docker, Render)

L'immagine Docker (`Dockerfile`, con Tesseract) gira su qualsiasi server; in modalità web chiede una
password e usa la chiave LlamaParse come segreto del server:

```
docker build -t alinea .
docker run -p 10000:10000 -e ALINEA_PASSWORD=... -e LLAMA_CLOUD_API_KEY=... -e ALINEA_SECRET=... alinea
```

Senza `ALINEA_PASSWORD` l'app resta chiusa. Su **Render.com** c'è il blueprint `render.yaml`
(*New → Blueprint*), ma Render può chiedere una carta di credito anche per il piano gratuito; gli Space
Docker di Hugging Face richiedono l'abbonamento PRO.

## Installazione locale (Windows)

1. Installa **Python 3.10 o superiore** da <https://www.python.org/downloads/>, spuntando
   *"Add python.exe to PATH"*.
2. Scarica questa cartella (`Code › Download ZIP` su GitHub, oppure `git clone`).
3. Doppio clic su **`avvia.bat`**. La prima volta crea l'ambiente e installa le librerie (serve internet,
   circa 1 minuto), poi apre il browser su <http://127.0.0.1:8765>.
   Per fermare Alinea chiudi la finestra nera.

### Lettura delle scansioni (OCR)

La maggior parte dei disegni sono scansioni: servono un OCR. Alinea ne supporta due, anche insieme.

| | LlamaParse (consigliato) | Tesseract (locale) |
|---|---|---|
| Qualità su quote e GD&T | alta (OCR + modello linguistico) | discreta, i simboli GD&T si perdono spesso |
| Costo | tier gratuito con crediti mensili | gratis |
| Privacy | il disegno viene inviato a LlamaIndex (server UE disponibile) | tutto in locale |
| Setup | chiave API | installazione del programma |

**LlamaParse:** registrati su <https://cloud.llamaindex.ai>, crea una *API Key* e incollala in
**⚙ Impostazioni** in Alinea (scegli la regione Europa se hai creato l'account su `cloud.eu.llamaindex.ai`).
Alinea invia al massimo 4 pagine per disegno, per risparmiare crediti.

**Tesseract:** installa il pacchetto di UB Mannheim da
<https://github.com/UB-Mannheim/tesseract/wiki> (durante l'installazione aggiungi la lingua *Italian*).
Alinea lo trova da solo in `C:\Program Files\Tesseract-OCR`; se l'hai installato altrove imposta la
variabile d'ambiente `TESSERACT_CMD`.

In modalità **Automatica**: PDF con testo leggibile → testo del PDF (gratis ed esatto); scansione o testo
illeggibile (font simbolici) → LlamaParse; se LlamaParse manca o fallisce → Tesseract.

## Uso

1. **Carica** lo STEP (`.stp` / `.step`) e il disegno. Il file `.CAD` di PC-DMIS non è leggibile (è la
   cache interna, in formato proprietario): in PC-DMIS usa *File › Esporta › Modello › STEP (AP214)*.
2. **Genera routine**: Alinea legge, interpreta e associa.
3. **Revisione**:
   - *Riferimenti A/B/C*: di default A = piano principale rivolto verso l'alto, B e C = piani
     perpendicolari. Cambiali se il disegno usa altri riferimenti (anche un foro come B o C).
   - *Controlli*: ogni riga è una caratteristica. Lo **stato** dice quanto fidarsi:
     `associato` (trovata una sola corrispondenza), `assunto` (scelta automatica da verificare),
     `solo CAD` (foro nel CAD non quotato nel disegno, con tolleranza generale),
     `non associato` (da collegare a mano: scegli la feature e la riga si attiva).
   - Clicca un foro nella vista o una riga: il programma evidenzia il codice relativo.
4. **Esporta**: *Scarica .txt* (programma), *Piano .csv* (si apre in Excel), oppure *Copia*.

### Portare il programma in PC-DMIS

Crea un programma nuovo in millimetri, apri la *Edit Window* in **modalità Comandi** e incolla il testo
(oppure apri il `.txt` e copia da lì). Poi, **prima di lanciare in DCC**:

- controlla che `LOADPROBE/PROBE1` sia il nome della tua configurazione tastatore
  (si imposta in ⚙ Impostazioni) e che i tip usati (`T1A0B0`, `T1A90B-90`, …) siano qualificati;
- esegui la simulazione/anteprima del percorso;
- al primo pezzo verifica le convenzioni degli angoli della testa (vedi sotto).

## Cosa genera

- Intestazione, `LOADPROBE`, `TIP`, `CLEARP` (piano di sicurezza sopra il pezzo).
- **Allineamento manuale 3-2-1** (3 punti su A, 2 su B, 1 su C), poi **ri-misura in DCC** e
  allineamento `A_DCC` (`LEVEL` / `ROTATE` / `TRANS`) nel sistema dei riferimenti.
- **Autofeature** cerchio o cilindro (se la lunghezza lo consente) per ogni foro, con centro, vettore
  e diametro reali presi dal CAD; piani con punti interni alla faccia, lontani da bordi e fori.
- Feature raggruppate per **orientamento del tastatore** (scelto dal vettore della feature) e ordinate
  per percorso più corto; `MOVE/POINT` di avvicinamento per le feature laterali.
- **Dimensioni**: diametro (con tolleranze ISO 286 calcolate da H7, g6, …), localizzazione (`TRUE
  POSITION`, con MMC/LMC), distanze, planarità, perpendicolarità, parallelismo, cilindricità,
  circolarità, coassialità.
- Stima di punti, orientamenti e tempo ciclo.

## Limiti (da sapere)

- **Sintassi PC-DMIS**: il testo segue il formato dell'Edit Window (dimensioni in formato legacy).
  Tra versioni diverse di PC-DMIS possono esserci piccole differenze: al primo utilizzo verifica che
  l'incolla crei i comandi correttamente.
- **Angoli della testa**: la corrispondenza vettore → tip (es. faccia X+ → `T1A90B-90`) segue la
  convenzione Hexagon più diffusa. Se sulla tua testa è diversa, dimmelo e la rendo configurabile.
- **Piazzamento**: il pezzo si assume posizionato come nel CAD (Z+ in alto). Le facce rivolte verso il
  basso non sono raggiungibili: vengono escluse e segnalate (serve un secondo piazzamento).
- **Anticollisione**: niente simulazione di collisione. Ci sono il piano di sicurezza e gli avvicinamenti
  sul vettore, ma la verifica del percorso resta in PC-DMIS.
- **Geometria**: sono misurate le superfici analitiche (piani, cilindri). Coni, tori e B-spline vengono
  contati ma non misurati; profili, oscillazioni, simmetria e raggi sono marcati *Manuale*.
- **Assiemi** STEP con trasformazioni tra le parti non sono supportati: esporta la singola parte.
- **Associazione quote**: è automatica ma euristica. Le righe `assunto` vanno sempre guardate.

## Struttura del codice

```
alinea/
  step_reader.py    parser STEP (ISO 10303-21) + topologia B-rep, in Python puro
  cad_features.py   fori/perni, piani, pattern, punti di tastatura, distanze candidate
  drawing_reader.py testo PDF, LlamaParse (API REST), Tesseract (con coordinate delle righe)
  drawing_parser.py quote, tolleranze, filetti, GD&T; correzioni per gli errori tipici dell'OCR
  iso_tolerances.py ISO 286 (accoppiamenti) e ISO 2768 (tolleranze generali)
  matching.py       associazione disegno ↔ CAD, scelta dei riferimenti A/B/C
  pcdmis.py         sistema di riferimento, scelta tip, scrittura del programma
  control_plan.py   piano di controllo CSV
  server.py         server FastAPI (locale e modalità web con password)
  browser.py        punti di ingresso per la versione nel browser (Pyodide)
  static/           interfaccia; browser.js + pyworker.js = backend nel browser
tools/build_static.py  costruisce il sito statico (dist/)
esempi/             staffa di prova: STEP, PDF vettoriale, PDF scansionato
tests/              test automatici (pytest)
```

Sviluppo: `pip install -r requirements.txt pytest`, poi `python -m pytest`. Per rigenerare i file di
esempio: `pip install cadquery reportlab` e `python esempi/genera_esempi.py`.

## Licenza

[PolyForm Noncommercial 1.0.0](LICENSE.md): libero per uso personale, studio, ricerca e per enti
non commerciali. **L'uso commerciale** (per esempio in un'azienda, in produzione o come servizio a
pagamento) **richiede un accordo con l'autore**: apri una issue sul repository.
