FROM python:3.10-slim-bookworm

ARG CLIPTALK_INSTALL_PROFILE=cpu

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CLIPTALK_INSTALL_PROFILE=${CLIPTALK_INSTALL_PROFILE} \
    HIGHLIGHT_HOST=0.0.0.0 \
    HIGHLIGHT_PORT=5180 \
    HIGHLIGHT_DATA_ROOT=/app/data

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-wqy-zenhei libgomp1 libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-cpu.txt requirements-gpu.txt ./
RUN python -m pip install --upgrade pip \
    && if [ "$CLIPTALK_INSTALL_PROFILE" = "cpu" ]; then \
         python -m pip install -r requirements-cpu.txt; \
       elif [ "$CLIPTALK_INSTALL_PROFILE" = "gpu" ]; then \
         python -m pip install -r requirements-gpu.txt; \
       else \
         echo "Unsupported CLIPTALK_INSTALL_PROFILE=$CLIPTALK_INSTALL_PROFILE" >&2; exit 2; \
       fi

COPY app ./app
COPY static ./static
COPY tools/prepare_speech_models.py ./tools/prepare_speech_models.py
COPY tools/container_smoke.py ./tools/container_smoke.py

RUN useradd --create-home --uid 10001 cliptalk \
    && mkdir -p /app/data \
    && chown -R cliptalk:cliptalk /app

USER cliptalk
VOLUME ["/app/data"]
EXPOSE 5180

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5180/api/health', timeout=3)" || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5180"]
