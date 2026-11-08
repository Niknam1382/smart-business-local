# Roadmap · نقشه‌ی راه

## English

**Shipped in v1.0.0 (the first public release)** — Button shop (catalog, cart, configurable checkout form, tracking) · bulk Excel import
through a template the app itself builds · custom buttons & FAQ · human support hand-off with working hours · editable
bilingual bot texts · crash-safe order confirmation · versioned migrations · privacy tools (`/forget`, `/stop`,
retention) · attention inbox · proxy pool with failover and subscription link · headless / Docker · backups and
multi-OS releases · discount codes and campaigns · ledger, profit dashboard and Persian PDF invoices · offline guide
and troubleshooter · Jalali dates everywhere · the AI lost every write tool (orders and the cart are button-only).

- **Local-only AI**: hardware probe, six pinned GGUF models with quality/speed stars and fit badges, one-click
  download with progress / cancel / resume / SHA-256 verification, mirror sources, import-your-own-file, an advanced
  panel (model folder, context tokens, threads, GPU layers, reply caps, kill switch) and a *Test model* button.
- **Central prompt studio**: persona editor + 11 ready-made templates + five non-removable guardrail segments + a live
  preview of the exact text the model receives + warnings (prompt length, hardcoded prices, injection bait).
- **Telegram is the main messenger**; the Bale chat bot is an optional, independent second messenger (own token at
  `tapi.bale.ai`, own AI switch), and **Bale Pay** remains a separate gateway (`createInvoiceLink` first, payment-bot
  deep link as fallback). Every combination works: Telegram only, Bale only, both, neither.
- **Two payment methods**: card-to-card with receipt capture and an instant alarm (confirmation is always manual), and
  Bale Pay with gateway-verified auto-confirmation. Zarinpal is gone.
- **Exactly two modes** (advisor / shop) and a **four-button** customer menu; guide + FAQ live under *Contact support*.
- Removed: portable/USB mode, API providers and cost budgets, and the *API-era* answer cache
  (a local response cache for the offline model arrived later in this same release).

- **Shipping, delivery, payment status and search** — shipping methods with a cost, **off by default** (`total = items − discount + shipping`,
frozen per order so old invoices never change, with a “shipping charged” line in the ledger and on the finance
dashboard) · a delivery track for confirmed orders (preparing → shipped → delivered, tracking code included, never
touching the money) · a read-only payment-status panel on every paid order · global search across orders, products and
customers from one box · the 11th prompt template (“store rules”) · Excel and PDF export of every list · 2209 tests.

**Next release candidates**

- **Bale as a full messenger:** chat, orders, receipts and invoices already work on Bale, but the admin
  panel, broadcasts, discount campaigns and the mandatory-channel gate are still Telegram-scoped
  (`broadcast.py`, `channel_gate.py`, `custom_buttons.py`, `app/screens/admins.py`).

- **Not done on purpose (rough priority):** keep-running-in-the-background / system tray (A4), a richer home dashboard
  (A5), a full refund workflow (A8), an English version of the guide.
- **Local AI follow-ups:** a CUDA/GPU build (or an option per machine) so NVIDIA cards actually help, a per-model
  download-size estimate that accounts for the context setting, more quants in the catalog (smaller/faster), an optional
  multilingual or domain-specific model, a "which model answered?" debug line, and a benchmark script for the Persian
  answers (currently the quality stars are catalog-relative, not measured on this hardware).
- **Payments follow-ups:** a second gateway (Shaparak-backed, only with a verified API), batch reconciliation of
  card-to-card transfers, and an optional OCR of receipt photos (today the parser reads text only; images are shown to
  the owner and never read).
- Finance follow-ups: pro-forma invoices, partial credit notes, VAT on top of prices, Excel export, e-invoicing
  (not planned without a verified API).
- **macOS build (currently not shipped):** it needs a `llama-cpp-python` release with a `macosx arm64`
  wheel (the source build fails on GitHub's macOS runner); once found, add the `macos` row back to
  `.github/workflows/release.yml`.
- Code signing (Windows), an offline (LAN-only) install option for the model runtime.
- OS-keyring option for the encryption key; read-only "viewer" role already exists — add granular permissions.
- Multi-shop profiles (several shops in one installation); product variants (size/colour); inventory CSV import/export.
- Real screenshots/GIFs in the README; a translated owner guide (English).

**Later** — webhook input for integrations, a public catalog page, phone/SMS notifications, team billing.

---

## فارسی

**انجام‌شده در ۱.۰.۰ (نخستین انتشارِ عمومی)** — فروشگاهِ دکمه‌ای (کاتالوگ، سبد، فرمِ سفارشِ قابل‌تنظیم، پیگیری) · وارداتِ دسته‌ایِ اکسل با
قالبی که خودِ برنامه می‌سازد · دکمه‌های سفارشی و سؤالات متداول · پشتیبانیِ انسانی با ساعتِ کاری · متن‌های دوزبانه‌ی
قابلِ ویرایش · تأییدِ سفارشِ ضدِ کرش · مهاجرتِ نسخه‌دار · ابزارهای حریمِ خصوصی (`/forget`، `/stop`، نگه‌داریِ داده) ·
صندوقِ «نیاز به توجه» · استخرِ پروکسی با جابه‌جاییِ خودکار و لینکِ اشتراک · headless / Docker · پشتیبان‌گیری و انتشارِ
چندسیستم‌عاملی · کدِ تخفیف و کمپین · دفترِ مالی، داشبوردِ سود و فاکتورِ PDFِ فارسی · راهنمای آفلاین و عیب‌یاب ·
تاریخِ جلالی همه‌جا · و برداشتنِ هر ابزارِ نوشتنی از هوش مصنوعی (سفارش و سبد فقط با دکمه).

- **هوش مصنوعی فقط محلی:** خواندنِ سخت‌افزار، شش مدلِ GGUFِ قفل‌شده با ستاره‌ی کیفیت/سرعت و برچسبِ «جا شدن»، دانلودِ
  یک‌کلیکی با پیشرفت/توقف/ادامه/سنجشِ SHA-256، آینه‌ها، واردکردنِ فایلِ خودت و پنلِ پیشرفته (پوشه‌ی مدل، توکنِ زمینه،
  رشته‌ها، لایه‌ی GPU، سقفِ پاسخ، کلیدِ خاموشی) و دکمه‌ی «آزمایشِ مدل».
- **استودیوی مرکزیِ پرامپت:** ویرایشگرِ شخصیت + ۱۱ قالبِ آماده + پنج قطعه‌ی گاردریلِ حذف‌نشدنی + پیش‌نمایشِ همان
  متنی که مدل می‌خواند + هشدارها (بلندیِ پرامپت، قیمتِ دست‌نویس، عبارت‌هایِ پرخطرِ تزریق).
- **تلگرام پیام‌رسانِ اصلی است**؛ رباتِ گفتگوی بله به‌صورتِ یک گزینه‌ی اختیاریِ مستقل اضافه شده (توکن و سوییچِ AIِ جدا، روی `tapi.bale.ai`) و درگاهِ **بله‌پی** کاملاً از آن جدا مانده — هر ترکیبی ممکن است (اول
  `createInvoiceLink`، اگر نشد دیپ‌لینکِ رباتِ پرداخت).
- **دو روشِ پرداخت:** کارت‌به‌کارت با گرفتنِ رسید و آلارمِ فوری (تأیید همیشه دستی) و بله‌پی با تأییدِ خودکارِ
  پرداختِ تأییدشده‌ی درگاه. زرین‌پال حذف شد.
- **دقیقاً دو حالت** (مشاوره‌ای / فروشگاهی) و منویِ **چهار دکمه‌ایِ** مشتری؛ راهنما و سؤالات متداول زیرِ «ارتباط با
  پشتیبانی»اند.
- حذف‌شده‌ها: حالتِ قابل‌حمل (فلش)، ارائه‌دهنده‌های API و بودجه‌ی هزینه و **کشِ پاسخِ دورانِ API**
  (کشِ پاسخِ محلی برایِ مدلِ آفلاین در همین نسخه از نو اضافه شد).

- **ارسال، تحویل، وضعیتِ پرداخت و جست‌وجو** — روش‌هایِ ارسال با هزینه، **پیش‌فرضِ خاموش** (`مبلغ = جمعِ اقلام − تخفیف + کرایه`، منجمد روی
هر سفارش تا فاکتورهایِ قدیمی عوض نشوند، با خطِ «کرایه‌ی ارسال» در دفتر و داشبوردِ مالی) · مسیرِ «در دستِ ارسال» برای
سفارش‌های تأییدشده (آماده‌سازی ← ارسال ← تحویل، با کد رهگیری و بدونِ دست‌زدن به پول) · کارتِ فقط‌خواندنیِ «وضعیتِ
پرداخت» روی هر سفارشِ پرداخت‌شده · جست‌وجوی سراسری در سفارش/مشتری/محصول در یک کادر · یازدهمین قالبِ پرامپت
(«قوانینِ فروشگاه») · خروجِ اکسل و PDF از هر فهرست · ۲۲۰۹ تست.

**بعدی (کاندیدهای انتشارِ بعد)**

- **بله به‌عنوانِ پیام‌رسانِ کامل:** گفتگو، سفارش، رسید و فاکتور روی بله کار می‌کنند، ولی پنلِ مدیریت،
  پخشِ پیام، کمپینِ تخفیف و «اجبارِ عضویت در کانال» هنوز تلگرامی‌اند (`broadcast.py`، `channel_gate.py`،
  `custom_buttons.py`، `app/screens/admins.py`).

- **عمداً انجام نشده (تقریباً به ترتیبِ اولویت):** ادامه‌ی کار در پس‌زمینه/سینی‌سیستم (A4)، داشبوردِ غنی‌تر (A5)،
  جریانِ کاملِ بازپرداخت (A8) و نسخه‌ی انگلیسیِ راهنما.
- **ادامه‌ی هوش مصنوعیِ محلی:** بیلدِ GPU/CUDA تا کارتِ گرافیک واقعاً به کار بیاد، تخمینِ حجمِ دانلود بر پایه‌ی
  توکنِ زمینه، کوانت‌های بیشتر (سبک‌تر/سریع‌تر)، مدلِ چندزبانه یا تخصصی، خطِ عیب‌یابیِ «کدام مدل جواب داد؟» و یک
  بنچمارکِ فارسی (ستاره‌هایِ فعلی نسبیِ همان فهرست است، نه اندازه‌گیری‌شده روی سخت‌افزارِ تو).
- **ادامه‌ی پرداخت:** درگاهِ دوم (فقط با APIِ تأییدشده)، تطبیقِ دسته‌ایِ واریزهای کارت‌به‌کارت، و خواندنِ اختیاریِ
  عکسِ رسید (امروز فقط متنِ رسید خوانده می‌شه؛ عکس به مالک نشان داده می‌شه).
- ادامه‌ی بخشِ مالی: پیش‌فاکتور، فاکتورِ برگشتیِ جزئی، مالیاتِ «روی قیمت»، خروجیِ Excel؛ اتصال به سامانه‌ی مودیان فقط
  با APIِ تأییدشده.
- **بیلدِ macOS (فعلاً منتشر نمی‌شه):** اول باید نسخه‌ای از `llama-cpp-python` پیدا بشه که wheelِ
  `macosx arm64` داره (بیلد از سورس روی رانرِ مک می‌شکنه)؛ بعد ردیفِ `macos` به `.github/workflows/release.yml`
  برمی‌گرده.
- امضای کد (ویندوز)، گزینه‌ی نصبِ موتورِ اجرا بدونِ اینترنت.
- نگه‌داریِ کلیدِ رمزنگاری در keyringِ سیستم؛ نقش‌های ریزترِ دسترسی (فعلی: مدیر / پشتیبان / ناظر).
- چند فروشگاه در یک نصب؛ تنوعِ محصول (سایز/رنگ)؛ ورود/خروجِ CSVِ موجودی.
- اسکرین‌شات/GIFِ واقعی در README؛ ترجمه‌ی انگلیسیِ راهنمای مالک.

**بعدها** — وب‌هوک برای یکپارچه‌سازی، صفحه‌ی عمومیِ کاتالوگ، اعلانِ پیامکی، نسخه‌ی تیمی.
