# JAL-SAKSHI backend.
#
# One process, no sidecars: FastAPI, the hydraulic simulator, the detector and
# the agent loop all run in-process, and the only external dependencies are
# Supabase and an n8n webhook. There is nothing here to orchestrate.
#
# Single worker on purpose. The realtime bus and the simulator hold state in
# memory, so a second worker would serve a console that misses half its events
# and a simulator running twice. Scale by service area, not by process.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/backend

WORKDIR /app

# Dependencies first, so a code change does not re-resolve the wheel set.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend

# Non-root, and the filesystem is not written to at runtime.
RUN useradd --create-home --uid 10001 jalsakshi
USER jalsakshi

EXPOSE 8000

# Render and most PaaS supply $PORT; 8000 locally.
ENV PORT=8000 \
    APP_ENV=production \
    LOG_FORMAT=json

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",8000)}/api/v1/health').read()"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips '*'"]
