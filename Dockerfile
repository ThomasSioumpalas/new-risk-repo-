# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Builder: resolve and install the locked dependency set with uv, then the
# project itself, into a self-contained virtualenv.
# ---------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Install dependencies first (best layer-cache use): only pyproject.toml and
# the lockfile invalidate this layer, not application code.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project --extra postgres

# Now bring in the application and install the project itself.
COPY src/ ./src/
COPY alembic.ini ./alembic.ini
COPY migrations/ ./migrations/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra postgres

# ---------------------------------------------------------------------------
# Runtime: a slim image with no build toolchain, running as a non-root user.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ARG SEXTANT_VERSION=0.1.0

LABEL org.opencontainers.image.title="Sextant" \
      org.opencontainers.image.description="Quantitative, auditable information-security risk register" \
      org.opencontainers.image.source="https://github.com/ThomasSioumpalas/new-risk-repo-" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.version="${SEXTANT_VERSION}" \
      org.opencontainers.image.vendor="Thomas Sioumpalas"

RUN groupadd --gid 10001 sextant \
    && useradd --uid 10001 --gid sextant --no-create-home --shell /usr/sbin/nologin sextant

WORKDIR /app

# Bring in the prepared virtualenv and application code from the builder.
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/alembic.ini /app/alembic.ini
COPY --from=builder /app/migrations /app/migrations
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
# The fictional example register, so a demo database can be seeded inside the container:
#   docker compose run --rm api sextant db seed examples/halcyon
COPY examples/halcyon /app/examples/halcyon

RUN chmod +x /app/docker-entrypoint.sh \
    && chown -R sextant:sextant /app

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

USER sextant

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "sextant.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
