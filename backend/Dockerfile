# CareBridge AI backend (FastAPI). Build context: this folder.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/home/app/.cache/huggingface
WORKDIR /app

# Install dependencies first so code edits do not re-install them. requirements.txt is normalised to UTF-8 (see script).
COPY requirements.txt docker/normalize_requirements.py /tmp/
RUN python /tmp/normalize_requirements.py /tmp/requirements.txt /tmp/requirements.utf8.txt \
 && pip install torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install -r /tmp/requirements.utf8.txt

COPY . .
RUN useradd --system --uid 10001 --create-home app && chown -R app:app /app /home/app
USER app

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=3)"
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
