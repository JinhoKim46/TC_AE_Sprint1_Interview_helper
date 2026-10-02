# Interview Helper as a local, long-running Streamlit service. See docs/06-docker.md.

# ---- Build stage: resolve and install dependencies with uv -------------------------------------
# Exact tag (patch release + Debian release), so a rebuild months later gets the same Python and OS
# instead of whatever `3.12-slim` points to that day. Bump it on purpose, in both stages.
FROM python:3.12.14-slim-bookworm AS builder

# Pinned to the uv version that wrote uv.lock, so `--locked` behaves the same as on the dev machine.
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/

# Bytecode compiled at build time = faster first start. Copy mode because the cache mount below is a
# different filesystem, where uv's default hard links would fail.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, project second: the dependency layer is reused as long as pyproject.toml and
# uv.lock don't change, so editing app code rebuilds in seconds.
COPY pyproject.toml uv.lock .python-version README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY src ./src
COPY app ./app
COPY samples ./samples
# Upload size, telemetry off, terse error pages. The CMD below overrides only the bind address.
COPY .streamlit ./.streamlit
COPY docs/rubric.json docs/01-interviewer-guideline.md ./docs/
# Installs the project itself in editable mode: it runs from /app/src, so config.PROJECT_ROOT
# (two levels above config.py) is /app and finds docs/, samples/ and data/ exactly as in a checkout.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# ---- Runtime stage: just Python, the venv and the app ------------------------------------------
FROM python:3.12.14-slim-bookworm

# The container user gets the same UID/GID as the host user who owns ./data (default 1000, the first
# user on most Linux machines). A bind mount keeps host ownership, so with matching ids the app can
# write the DB without chmod 777 or running as root. Override with APP_UID/APP_GID (see compose.yaml).
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home --shell /usr/sbin/nologin app

WORKDIR /app
# Same path as in the builder: the venv's scripts and the editable install point at /app.
COPY --from=builder /app /app
RUN mkdir -p /app/data && chown app:app /app/data

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1

USER app
EXPOSE 8501

# python/urllib because slim images have no curl. Streamlit answers "ok" on this path once it serves.
# The only healthcheck definition: compose.yaml inherits it, so the two can't drift apart.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4).read() == b'ok' else 1)"]

# 0.0.0.0 so the published port reaches it (flags beat .streamlit/config.toml, whose 127.0.0.1 is
# meant for running on the host); headless = no browser launch, no email prompt.
CMD ["streamlit", "run", "app/main.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
