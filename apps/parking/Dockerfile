# BotConnector Parking — Central application (deployment artifact).
# Not installed/enabled automatically. Use for controlled testing only.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8711

# Migrate then run the local dev runner (127.0.0.1 only; not public).
CMD ["sh", "-c", "alembic upgrade head && python -m parking.api.run"]
