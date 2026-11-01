FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY db ./db
COPY deploy/aws/entrypoint.sh /entrypoint.sh

RUN pip install --no-cache-dir "psycopg[binary]" boto3 \
    && chmod +x /entrypoint.sh

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    STAFF_UI_HOST=0.0.0.0 \
    STAFF_UI_PORT=8765 \
    LMS_DB_PORT=5432 \
    LMS_DB_SSL=require

EXPOSE 8765
ENTRYPOINT ["/entrypoint.sh"]
