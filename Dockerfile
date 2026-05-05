FROM python:3.12-slim

WORKDIR /app

# Install dependencies before copying source for better layer caching
COPY pyproject.toml .
RUN pip install --no-cache-dir \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.30.0" \
    "sqlalchemy[asyncio]>=2.0.36" \
    "asyncpg>=0.30.0" \
    "alembic>=1.14.0" \
    "jinja2>=3.1.4" \
    "python-multipart>=0.0.12" \
    "httpx>=0.28.0" \
    "watchfiles>=1.0.0" \
    "pydantic-settings>=2.7.0" \
    "markdown-it-py>=3.0.0" \
    "pyyaml>=6.0.2"

# Copy application source
COPY alembic.ini .
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY config/ ./config/

# Non-root user
RUN groupadd -r scout && \
    useradd -r -g scout -u 1000 scout && \
    chown -R scout:scout /app

USER scout
EXPOSE 3200
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 3200"]
