FROM python:3.10-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HIGHLIGHT_HOST=0.0.0.0 \
    HIGHLIGHT_PORT=5180 \
    HIGHLIGHT_DATA_ROOT=/app/data

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgomp1 libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-speech-common.txt requirements-audiovisual.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements-audiovisual.txt

COPY app ./app
COPY static ./static
COPY tools/prepare_speech_models.py ./tools/prepare_speech_models.py

RUN useradd --create-home --uid 10001 cliptalk \
    && mkdir -p /app/data \
    && chown -R cliptalk:cliptalk /app

USER cliptalk
VOLUME ["/app/data"]
EXPOSE 5180

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5180/api/health', timeout=3)" || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5180"]
