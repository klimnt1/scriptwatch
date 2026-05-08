FROM python:3.11-slim
WORKDIR /app
ENV DATA_DIR=/app/data \
    DATABASE_URL=sqlite:////app/data/scriptwatch.db \
    SCRIPT_STORE_DIR=/app/data/script-store \
    ADMIN_USERNAME=admin \
    ADMIN_PASSWORD= \
    ADMIN_TOKEN= \
    BASE_URL= \
    NTFY_URL= \
    NTFY_TOKEN= \
    DISCORD_WEBHOOK_URL= \
    MISSED_RUN_GRACE_MINUTES=15 \
    JOB_RETENTION_DAYS=30
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8080
CMD ["gunicorn", "wsgi:app", "-c", "gunicorn.conf.py"]
