FROM node:22-bookworm-slim

ENV NODE_ENV=production \
    CLIPTALK_AGENT_HOST=0.0.0.0 \
    CLIPTALK_AGENT_PORT=5190 \
    HIGHLIGHT_DATA_ROOT=/app/data

WORKDIR /app/agent-service

COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --omit=dev

COPY *.mjs ./
RUN node --input-type=module -e "import('node:sqlite').then(m=>{if(!m.DatabaseSync)process.exit(1)})" \
    && node --check server.mjs

RUN useradd --create-home --uid 10001 cliptalk \
    && mkdir -p /app/data \
    && chown -R cliptalk:cliptalk /app

USER cliptalk
EXPOSE 5190

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:5190/health').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"

CMD ["node", "server.mjs"]
