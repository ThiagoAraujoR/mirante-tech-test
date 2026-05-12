FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --upgrade pip wheel \
    && pip wheel --wheel-dir=/wheels '.[dev]'

# ---------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /wheels /wheels
RUN pip install /wheels/*.whl && rm -rf /wheels

COPY pyproject.toml langgraph.json ./
COPY src ./src
COPY sql ./sql
COPY eval ./eval
COPY examples ./examples
COPY scripts ./scripts
COPY tests ./tests

EXPOSE 2024

CMD ["langgraph", "dev", "--host", "0.0.0.0", "--port", "2024", "--no-browser", "--allow-blocking"]
