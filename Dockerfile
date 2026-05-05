# ── Build stage ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml .
RUN pip install --no-cache-dir hatchling && \
    pip install --no-cache-dir --target /build/deps .

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim

# Non-root user
RUN groupadd -r scout && useradd -r -g scout -u 1000 scout

WORKDIR /app

# Copy installed deps
COPY --from=builder /build/deps /usr/local/lib/python3.12/site-packages

# Copy application
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY config/ ./config/
COPY alembic.ini .

# Owned by non-root user
RUN chown -R scout:scout /app

USER scout

EXPOSE 3200

# Run Alembic migrations then start uvicorn
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 3200"]
