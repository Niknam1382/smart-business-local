# کسب‌وکار هوشمند — حالتِ headless (فقط ربات‌ها، بدونِ UI). ساخت: docker build -t smart-business .
#
# نسخه‌ی ۱.۰.۰: هیچ کلیدِ API، هیچ callbackِ پرداخت و هیچ پورتی لازم نیست — ربات‌ها با polling به
# تلگرام/بله وصل می‌شن و «بله» فقط دروازه‌ی پرداخت است (app/core/bale_pay.py). تنها متغیرِ محیطیِ
# موردنیاز SMART_BUSINESS_DATA_DIR است (اینجا /data).
# هوشِ مصنوعی محلی است (GGUF + llama.cpp)؛ پس llama-cpp-python در requirements-headless.txt هست و
# libgomp1 هم لازم می‌شه. روی ماشینِ کوچک مدل جا نمی‌شه و برنامه صادقانه چاپ می‌کنه که AI خاموش است.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SMART_BUSINESS_DATA_DIR=/data

# libgomp1: wheelهای آماده‌ی llama-cpp-python با OpenMP لینک می‌شن؛ بدونِ آن import llama_cpp خطا می‌دهد.
# فونتِ سیستم لازم نیست: fpdf2/uharfbuzz با fontTools خودِ Vazirmatn را از assets/fonts می‌خونن.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-headless.txt .
# اگر ایندکسِ wheelهای آماده (--extra-index-url داخلِ فایل) برای این پایتون/معماری نسخه‌ی آماده نداشته باشد،
# pip سورس را کامپایل می‌کند و به g++ و cmake نیاز می‌شه؛ در آن حالت موقتاً اضافه کن:
#   RUN apt-get install -y --no-install-recommends build-essential cmake
RUN pip install --no-cache-dir -r requirements-headless.txt

COPY app ./app
COPY run.py .
# فونتِ Vazirmatn: app/core/invoice_pdf.py مسیرش را نسبی به assets/fonts پیدا می‌کنه؛ بدونِ آن
# فاکتورِ PDFِ فارسی در کانتینر می‌شکنه (بقیه‌ی assets فقط UI هستند و در .dockerignore کنار گذاشته شدن).
COPY assets/fonts ./assets/fonts

# کاربرِ غیرِ root
RUN useradd --create-home --uid 10001 bot
# داده (تنظیمات، دیتابیس‌ها، secret.key، پشتیبان‌ها، رسیدِ پرداخت، فاکتورها و **مدل‌های GGUF**)
# فقط در این volume می‌نویسه — پوشه‌ی models/ می‌تونه ۲ تا ۶+ گیگ بشه، پس volume را روی دیسکِ پرظرفیت بذار
# (یا با model_storage_path در settings.json آن را به دیسکِ دیگری ببر). با docker compose خودش وصل می‌شه.
RUN mkdir -p /data/models && chown -R bot:bot /data /app
VOLUME ["/data"]

USER bot

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
  CMD python run.py --healthcheck || exit 1

CMD ["python", "run.py", "--headless"]
