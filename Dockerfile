# syntax=docker/dockerfile:1.7
ARG PYTHON_IMAGE=python:3.13.13-slim-bookworm

FROM ${PYTHON_IMAGE} AS builder

ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
RUN python -m venv "$VIRTUAL_ENV"

COPY requirements.txt pyproject.toml setup.py README.md arb_bot.py ./
COPY src ./src

RUN python -m pip install --requirement requirements.txt \
    && python -m pip install --no-deps --no-build-isolation . \
    && python -m pip check \
    && flashloan-bot status --json >/tmp/runtime-status.json \
    && flashloan-bot capabilities --json >/tmp/runtime-capabilities.json

FROM ${PYTHON_IMAGE} AS runtime

ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLASHLOAN_RUNTIME_STATE_PATH=/run/flashloan-bot/runtime.json \
    FLASHLOAN_HEALTH_HOST=127.0.0.1 \
    FLASHLOAN_HEALTH_PORT=8080 \
    FLASHLOAN_HEALTH_URL=http://127.0.0.1:8080/health \
    PAPER_TRADING_ONLY=true \
    LIVE_TRADING_ENABLED=false \
    JITO_ENABLED=false \
    KAMINO_LIQUIDATION_ENABLED=false

RUN groupadd --gid 10001 flashloan \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin flashloan \
    && install --directory --owner=10001 --group=10001 --mode=0750 /run/flashloan-bot

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
USER 10001:10001

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD ["flashloan-bot-healthcheck", "--url", "http://127.0.0.1:8080/health"]

ENTRYPOINT ["flashloan-bot"]
CMD ["container"]
