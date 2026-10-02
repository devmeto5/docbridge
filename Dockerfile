FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp LANG=C.UTF-8 OMP_THREAD_LIMIT=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer tesseract-ocr tesseract-ocr-eng tesseract-ocr-rus \
    fonts-dejavu-core fonts-liberation libseccomp2 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 converter && useradd --uid 10001 --gid 10001 --no-create-home converter
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY docbridge ./docbridge
COPY tests ./tests
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=3)"
CMD ["gunicorn", "docbridge.api:application", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "210", "--graceful-timeout", "15", "--worker-tmp-dir", "/tmp", "--limit-request-line", "2048", "--limit-request-fields", "30", "--error-logfile", "-"]
