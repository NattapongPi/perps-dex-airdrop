FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends cron curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

RUN echo "3 * * * * root cd /app && python -m src.main >> /proc/1/fd/1 2>&1" \
    > /etc/cron.d/trading-bot \
    && chmod 0644 /etc/cron.d/trading-bot \
    && crontab /etc/cron.d/trading-bot

COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

CMD ["./entrypoint.sh"]
