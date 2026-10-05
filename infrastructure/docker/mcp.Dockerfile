# Build context: repository root.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY mcp-server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp-server/ ./

RUN useradd --create-home appuser
USER appuser

# Runs over stdio by default; attach with `docker compose run --rm -i mcp-server`.
CMD ["python", "-m", "dh_mcp.server"]
