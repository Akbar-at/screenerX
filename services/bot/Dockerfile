FROM python:3.13-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 MPLBACKEND=Agg
COPY requirements.txt requirements-bot.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-bot.txt
COPY screenerx ./screenerx
COPY config.json valuation-config.json core-config.json ./
EXPOSE 8080
CMD ["python", "-m", "screenerx.telegram_bot", "serve", "--host", "0.0.0.0", "--port", "8080"]
