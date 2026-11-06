# Build native wheels separately so compilers do not enter the runtime image.
FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.lock.txt ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install -r requirements.lock.txt \
    && /opt/venv/bin/python -m pip check

FROM python:3.12-slim-bookworm AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000 \
    DATABASE_URL=sqlite:////var/data/moviemate/moviemate.db \
    SEED_DEMO_DATA=true

WORKDIR /app
RUN groupadd --gid 10001 moviemate \
    && useradd --uid 10001 --gid 10001 --create-home moviemate \
    && mkdir -p /var/data/moviemate /app/data \
    && chown moviemate:moviemate /var/data/moviemate /app/data

COPY --from=builder /opt/venv /opt/venv
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY scripts/container_start.py ./scripts/container_start.py

EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','10000')+'/api/health',timeout=4).close()"

# Starts as root only to initialize a newly mounted disk's permissions;
# container_start drops to UID 10001 before seeding or importing the app.
CMD ["python", "-m", "scripts.container_start"]
