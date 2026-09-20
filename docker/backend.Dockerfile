# Backend image: FastAPI app + Celery worker (same image, different command)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# `data` is mounted as a volume; make sure the app user can write to it.
RUN mkdir -p /app/data && chmod -R 777 /app/data

EXPOSE 8000

# Apply migrations, seed reference data, then start the API server.
CMD ["sh", "-c", "python -m app.database.init_db --with-migrations && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
