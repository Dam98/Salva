# Alinea - immagine per l'hosting web (Render, Docker)
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ALINEA_WEB=1 \
    ALINEA_NO_BROWSER=1 \
    OMP_THREAD_LIMIT=1 \
    PORT=10000

# OCR locale (ripiego quando LlamaParse non è configurato o non risponde)
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-ita tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/*

# utente con UID 1000 (richiesto da Hugging Face Spaces, buona pratica ovunque)
RUN useradd --create-home --uid 1000 alinea
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=alinea alinea ./alinea
COPY --chown=alinea esempi/staffa.stp esempi/staffa_disegno.pdf esempi/staffa_scansione.pdf ./esempi/
USER alinea

EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/healthz')"
CMD ["python", "-m", "alinea"]
