FROM node:22-bookworm-slim AS motion-renderer-dependencies

WORKDIR /renderer
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --omit=dev

FROM python:3.10-slim-bookworm

ARG CLIPTALK_INSTALL_PROFILE=cpu

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CLIPTALK_INSTALL_PROFILE=${CLIPTALK_INSTALL_PROFILE} \
    HIGHLIGHT_HOST=0.0.0.0 \
    HIGHLIGHT_PORT=5180 \
    HIGHLIGHT_DATA_ROOT=/app/data \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ffmpeg fonts-wqy-zenhei libgomp1 libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=motion-renderer-dependencies /usr/local/bin/node /usr/local/bin/node
COPY --from=motion-renderer-dependencies /renderer/node_modules ./node_modules
RUN node node_modules/playwright/cli.js install-deps chromium \
    && node node_modules/playwright/cli.js install chromium \
    && chmod -R a+rX /ms-playwright \
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

# Keep the large TalkNet installation layer independent from frequently edited
# application and UI files. The installer only needs this minimal application
# configuration surface.
COPY app/__init__.py app/config.py app/security.py ./app/
COPY tools/setup.py tools/install_talknet.py tools/talknet_worker.py tools/requirements-talknet.txt ./tools/

# Model assets live outside /app/data so a new or existing data volume cannot
# hide the default installation. Nothing is downloaded when the page opens.
RUN python tools/install_talknet.py --profile "$CLIPTALK_INSTALL_PROFILE" --data-root /opt/cliptalk-models
ENV HIGHLIGHT_TALKNET_PYTHON=/opt/cliptalk-models/models/talknet/venv/bin/python \
    HIGHLIGHT_TALKNET_REPOSITORY=/opt/cliptalk-models/models/talknet/repository \
    HIGHLIGHT_TALKNET_CHECKPOINT=/opt/cliptalk-models/models/talknet/pretrain_TalkSet.model \
    HIGHLIGHT_TALKNET_DEVICE=auto

COPY app ./app
COPY static ./static
COPY skills ./skills
COPY fonts/SourceHanSansSC-Bold.otf ./fonts/SourceHanSansSC-Bold.otf
COPY tools/prepare_speech_models.py ./tools/prepare_speech_models.py
COPY tools/container_smoke.py ./tools/container_smoke.py
COPY tools/render_html_motion.mjs ./tools/render_html_motion.mjs

RUN useradd --create-home --uid 10001 cliptalk \
    && mkdir -p /app/data \
    && chown -R cliptalk:cliptalk /app

USER cliptalk
VOLUME ["/app/data"]
EXPOSE 5180

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5180/api/health', timeout=3)" || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5180"]
