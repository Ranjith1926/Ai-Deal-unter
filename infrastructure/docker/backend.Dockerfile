# Shared image for backend API, Celery worker and Celery beat.
# Build context: repository root.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

# INSTALL_DEV=true adds test dependencies (used by the `backend-tests` compose service).
ARG INSTALL_DEV=false
COPY backend/requirements.txt backend/requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_DEV" = "true" ]; then pip install --no-cache-dir -r requirements-dev.txt; fi

COPY backend/ ./backend/
COPY workers/ ./workers/

RUN useradd --create-home appuser
USER appuser

ENV PYTHONPATH=/srv/backend:/srv/workers
WORKDIR /srv/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
