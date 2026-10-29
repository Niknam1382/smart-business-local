# سیاست امنیتی | Security policy

## گزارش آسیب‌پذیری | Reporting a vulnerability

**لطفاً مشکل امنیتی رو توی issue عمومی ننویس.** از تبِ *Security → Report a vulnerability* همین مخزن
(گزارشِ خصوصی) استفاده کن. سعی می‌کنیم ظرف چند روز جواب بدیم.

**Please do not open a public issue for security problems.** Use the repository's
*Security → Report a vulnerability* (private advisory) instead.

## چی مهمه؟ | What matters most here

این برنامه روی سیستمِ صاحب فروشگاه اجرا می‌شه و با پول و اعتبارنامه کار می‌کنه؛ حساس‌ترین بخش‌ها:

- **اعتبارنامه‌ها:** توکن ربات‌ها، توکن بله‌پی، مرچنت‌کد زرین‌پال، کلید API — رمزنگاری‌شده ذخیره می‌شن
  و از لاگ پاک می‌شن (`app/core/redact.py`). هر راهی برای درز کردنشون = آسیب‌پذیری.
- **منطق پول و موجودی:** ایجنتِ هوش مصنوعی هرگز نباید بتونه قیمت/موجودی بسازه، پرداخت رو تایید کنه
  یا سفارشِ مشتری دیگه رو ببینه (همه‌چیز سمتِ برنامه اعتبارسنجی می‌شه — `app/core/store_agent.py`).
- **ثبتِ مالک (`/owner <کد>`):** کدِ یک‌بارمصرفِ ۱۰ دقیقه‌ای؛ هر دورزدنش آسیب‌پذیری‌ست.
- **تزریقِ پرامپت** از طریق پیام یا نامِ پروفایلِ مشتری.

The app runs on the shop owner's machine and handles money and credentials. Anything that leaks
credentials, lets the AI invent prices/stock or approve payments, bypasses owner registration, or
enables prompt injection that crosses those boundaries is in scope.

## مدل تهدید | Threat model (read this before trusting the app with real money)

- **کلید رمزنگاری (`secret.key`) کنارِ داده‌ها ذخیره می‌شه** تا پوشه‌ی داده (و فلشِ قابل‌حمل) خودبسنده باشه. یعنی
  رمزنگاری جلوی لو رفتنِ سهوی (مثلاً فرستادنِ `settings.json` یا پشتیبانِ «بدون اسرار» به کسی، یا یه فایلِ لاگ)
  رو می‌گیره، **نه** جلوی کسی که به پوشه‌ی داده‌ی تو دسترسی کامل داره. فلش/کامپیوتر/پشتیبانِ «با اسرار» رو مثل
  رمزِ بانکی نگه دار.
- The encryption key (`secret.key`) lives **next to the data** so the data folder (and a portable drive) stays
  self-contained. Encryption therefore protects against *accidental* disclosure (sharing `settings.json`, a
  "without secrets" backup, a log file), **not** against someone with full access to your data folder. Treat the
  drive, the computer and any "with secrets" backup like a bank password.
- بسته‌ی تشخیصی (`diagnostics`) عمداً بدونِ مکالمه/مشتری/سفارش/توکن ساخته می‌شه؛ ولی قبل از انتشارِ عمومی یه نگاهِ چشمی بنداز.
- پروکسیِ تلگرام ترافیکِ TLS رو می‌بینه نه محتواش رو؛ ولی پروکسیِ ناشناس می‌تونه ترافیک رو قطع/کند کنه یا
  متادیتا (چه کسی به تلگرام وصله) رو ببینه. فقط پروکسیِ مورد اعتماد استفاده کن.

## نسخه‌های پشتیبانی‌شده | Supported versions

فقط آخرین نسخه | Only the latest release.
