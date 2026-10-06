FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

COPY . .

RUN useradd --create-home --uid 1000 bot && mkdir -p /app/logs && chown -R bot /app
USER bot

CMD ["python", "bot.py"]
