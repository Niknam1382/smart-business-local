# کسب‌وکار هوشمند — حالتِ headless (فقط ربات‌ها). ساخت: docker build -t smart-business .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SMART_BUSINESS_DATA_DIR=/data

WORKDIR /app
COPY requirements-headless.txt .
RUN pip install --no-cache-dir -r requirements-headless.txt

COPY app ./app
COPY run.py .

# داده (تنظیمات، توکن‌های رمزنگاری‌شده، دیتابیس‌ها، secret.key) فقط در این volume؛ با docker compose خودش وصل می‌شه
VOLUME ["/data"]

# کاربرِ غیرِ root
RUN useradd --create-home --uid 10001 bot && mkdir -p /data && chown bot /data
USER bot

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
  CMD python run.py --healthcheck || exit 1

CMD ["python", "run.py", "--headless"]
