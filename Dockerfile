# syntax=docker/dockerfile:1.7
# Base provenance: Docker Official Image python:3.13.13-slim-bookworm.
# Reviewed OCI index digest recorded 2026-08-01; mutable build arguments are forbidden.
FROM python:3.13.13-slim-bookworm@sha256:355bfa66770995d7e9a0da4b3473b44d0cb451f6b56f5615ad9c39e3c4eca03f AS wheelhouse
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /supply-chain
COPY requirements.lock ./
# This is the only networked dependency step.  Its output is an immutable,
# hash-verified wheelhouse consumed by every later stage with --no-index.
RUN python -m pip download --require-hashes --only-binary=:all: \
      --dest /wheelhouse --requirement requirements.lock

FROM python:3.13.13-slim-bookworm@sha256:355bfa66770995d7e9a0da4b3473b44d0cb451f6b56f5615ad9c39e3c4eca03f AS builder
ENV VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH \
    PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /build
COPY --from=wheelhouse /wheelhouse /wheelhouse
COPY requirements.lock pyproject.toml setup.py README.md arb_bot.py ./
COPY src ./src
RUN python -m venv "$VIRTUAL_ENV" \
 && python -m pip install --no-index --find-links=/wheelhouse --require-hashes -r requirements.lock \
 && python -m pip wheel --no-index --no-deps --no-build-isolation --wheel-dir=/reviewed-wheel . \
 && python -m pip install --no-index --no-deps /reviewed-wheel/*.whl \
 && python -m pip check \
 && cd /tmp && flashloan-bot status --json >/tmp/runtime-status.json

FROM python:3.13.13-slim-bookworm@sha256:355bfa66770995d7e9a0da4b3473b44d0cb451f6b56f5615ad9c39e3c4eca03f AS runtime
ENV VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    FLASHLOAN_RUNTIME_STATE_PATH=/run/flashloan-bot/runtime.json FLASHLOAN_HEALTH_HOST=127.0.0.1 \
    FLASHLOAN_HEALTH_PORT=8080 FLASHLOAN_HEALTH_URL=http://127.0.0.1:8080/health \
    PAPER_TRADING_ONLY=true LIVE_TRADING_ENABLED=false JITO_ENABLED=false KAMINO_LIQUIDATION_ENABLED=false
RUN groupadd --gid 10001 flashloan && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin flashloan \
 && install -d -o 10001 -g 10001 -m 0750 /run/flashloan-bot
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder --chown=10001:10001 /reviewed-wheel /opt/release/wheel
WORKDIR /app
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 CMD ["flashloan-bot-healthcheck", "--url", "http://127.0.0.1:8080/health"]
ENTRYPOINT ["flashloan-bot"]
CMD ["container"]
