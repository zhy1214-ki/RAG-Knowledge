FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/rag/backend
COPY backend/requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/real_usage_migrations ./real_usage_migrations
COPY backend/alembic.ini .
COPY scripts/real_usage_runtime.py scripts/real_rag_acceptance.py /opt/rag/scripts/
COPY deploy/real-usage /opt/rag/deploy/real-usage
RUN useradd --create-home --uid 10001 appuser && mkdir -p /data/uploads /audit && chown -R appuser:appuser /data /audit
USER appuser
EXPOSE 8000
CMD ["python", "/opt/rag/scripts/real_usage_runtime.py", "serve"]