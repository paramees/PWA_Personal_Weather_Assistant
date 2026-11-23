FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/app/data/bot.db

WORKDIR /app

RUN groupadd --system botuser && useradd --system --gid botuser --create-home botuser

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir . && \
    mkdir -p /app/data && \
    chown -R botuser:botuser /app

USER botuser

CMD ["python", "-m", "weather_wardrobe.main"]
