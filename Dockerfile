# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --upgrade pip build \
 && python -m build --wheel --outdir /dist

FROM python:3.12-slim AS runtime
RUN apt-get update \
 && apt-get install --no-install-recommends -y git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 analyst

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CODESMELL_WORKSPACE_ROOT=/var/lib/codesmell/workspaces \
    CODESMELL_API__STORAGE_ROOT=/var/lib/codesmell/data \
    CODESMELL_API__HOST=0.0.0.0 \
    CODESMELL_API__PORT=8000

COPY --from=builder /dist/*.whl /tmp/
RUN python -m pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl
RUN mkdir -p /var/lib/codesmell/workspaces /var/lib/codesmell/data \
 && chown -R analyst:analyst /var/lib/codesmell

USER analyst
WORKDIR /home/analyst
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)" || exit 1

ENTRYPOINT ["codesmell"]
CMD ["api", "serve"]
