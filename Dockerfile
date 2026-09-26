# Linux container: everything except MT5 trading (MT5's Python API is Windows-only).
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot ./bot
ENV PYTHONUNBUFFERED=1 DATA_DIR=/app/data BATTERY_WATCH=false
CMD ["python", "-m", "bot.main"]
