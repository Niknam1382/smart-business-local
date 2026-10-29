<div align="center">

<img src="assets/icons/app-icon-256.png" alt="Smart Business Local icon" width="120">

# Smart Business — Local Edition
# کسب‌وکار هوشمند (نسخه‌ی محلی)

**A free, open-source AI assistant for online shops and independent consultants on Telegram & Bale —
it runs entirely on your own computer: no server, no account, no commission.**

*دستیار هوشمندِ رایگان و متن‌باز برای فروشگاه‌های آنلاین و مشاوران مستقل روی تلگرام و بله —
کاملاً روی سیستم خودت؛ بدون سرور، بدون حساب کاربری، بدون کمیسیون.*

![License: MIT](https://img.shields.io/badge/license-MIT-blue)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![Platforms](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)
![Messengers](https://img.shields.io/badge/messengers-Telegram%20%7C%20Bale-2CA5E0)
![Tests](https://img.shields.io/badge/tests-940%20passing-brightgreen)

[English](#english) · [فارسی](#فارسی) · [Changelog](CHANGELOG.md) · [Roadmap](docs/ROADMAP.md) · [License](LICENSE)

<!-- After publishing, add your own badges, e.g.
![CI](https://github.com/<you>/<repo>/actions/workflows/ci.yml/badge.svg) -->

</div>

---

## English

### What it is

Smart Business turns your Telegram or Bale bot into a **shop assistant that never fumbles an order**. Customers
browse a catalog with buttons, fill a cart, answer your checkout questions, pay and track the order; the AI answers
their questions in between. Everything — products, orders, chats, tokens — stays on **your** machine, and you can run
it from a **USB drive**, as a **desktop app**, or **headless in Docker**.

> **Design rule:** an LLM is probabilistic, money flows must not be. In the default *Button shop* mode the AI never
> creates or edits carts, orders or payments — the app validates every price, quantity and stock level itself.

### Highlights

| | |
|---|---|
| 🛍 **Button shop** | Persistent menu, paginated catalog with categories, product cards with photo and ➖/➕ quantity, cart, step-by-step checkout, payment choice, order tracking — identical on Telegram and Bale. |
| 🎛 **Working modes** | *Advisor* (chat only) · *Button shop* · *AI ordering* (experimental) · *FAQ + human support* · *Lead capture*; switch any time, per platform. |
| 📝 **Your checkout form** | Choose which fields to ask (name, phone, address, postal code, e-mail, choices, custom) — physical and digital goods ask different things. |
| 💾 **Digital products** | Auto-delivery after confirmation: text, link, file or **licence keys** (one key per purchase, never reused). |
| 🔘 **Custom buttons & FAQ** | Link, call (number + contact card), text reply, human support, ask-the-AI… in your menu. |
| 🙋 **Human support** | A customer taps *Support*, you answer by *Reply* inside Telegram/Bale; working hours and auto-close included. |
| 🌐 **Persian & English** | Every bot message is editable and bilingual; language can follow the customer. |
| ⏳ **Stock reservation** | An order awaiting payment holds its quantity (default 15 min); two customers can never reserve the last item. |
| 💳 **Three payment methods — all to *your* accounts** | Card-to-card, **Bale Pay**, **Zarinpal**. No money flows through the app. |
| 🔔 **Owner console** | Alerts in your own chat; `/confirm 12`, `/reject 12`, `/reply`, `/close`, `/handoffs`. |
| 🛡 **Safe by construction** | Crash-safe order confirmation, versioned migrations with auto-backup, AI cost caps and a kill switch, `/forget`, optional data retention. |
| 🔌 **Proxies** | Pool with automatic failover, your own **subscription link**, automatic return to the fastest proxy. |
| 🤖 **Your choice of AI** | Any OpenAI-compatible API or a local GGUF model (offline). |
| 🧳 **Portable · 🐳 Docker** | USB edition for Windows/macOS/Linux; `python run.py --headless` or `docker compose up -d` for servers. |
| 📣 **Broadcast** | One message to everyone or a segment (buyers, new, inactive, tag, language) with a live recipient count, preview, a test to yourself, a daily cap and a safe speed that obeys Telegram/Bale limits. A *“send /stop to unsubscribe”* footer is on by default; blocked and opted-out people are never messaged. |
| ✉️ **Personal messages** | Write to one customer from the *Chats* page (with quick replies). They see “💬 Shop: …”, it is kept in the history and the AI knows about it. |
| 📢 **Required channel** | Customers must join your Telegram/Bale channel(s) first (menu, AI chat, or both). You and your managers are exempt; if the check ever breaks, nobody is locked out and you are told. |

### Download

Grab a file from this repository's **Releases** page:

| File | Use it for |
|---|---|
| `SmartBusinessLocal-<version>-windows-setup.exe` | Windows installer (per user, no admin needed) |
| `SmartBusinessLocal-<version>-windows.exe` | Windows single file — double-click and run |
| `SmartBusinessLocal-<version>-windows-portable.zip` | USB edition for Windows |
| `SmartBusinessLocal-<version>-macos-portable.zip` | USB edition for macOS *(experimental)* |
| `SmartBusinessLocal-<version>-linux-portable.zip` | USB edition for Linux *(experimental)* |
| `SHA256SUMS.txt` | Checksums to verify your download |

> The builds are **not code-signed yet**: Windows SmartScreen may say "unknown publisher" (*More info → Run
> anyway*), and on macOS you right-click the app → *Open* the first time. Verify the checksum if in doubt.
> Release process: [`docs/RELEASING.md`](docs/RELEASING.md).

### Quick start

1. Create a bot — Telegram: `@BotFather`; Bale: the Bale *BotFather*. Copy the token.
2. Run the app and follow the welcome steps. On the **Bots** page paste the token → *Test connection* → turn the
   bot on. If Telegram needs a proxy in your country, paste one or more (one per line) or a subscription link.
3. Choose your AI (API key or a local model), add products (physical or digital), set up payment.
4. Open **Bot experience** → *Customer preview* and walk through a purchase without leaving the app; then talk to
   your real bot.

Shop-owner guide (Persian, step by step): [`docs/SHOP_SETUP.fa.md`](docs/SHOP_SETUP.fa.md).

**Developers**

```bash
git clone <repo-url> && cd smart-business-local
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python run.py            # desktop window
python run.py --web      # in the browser
python -m pytest         # full suite — no internet, no real bots needed
```

Prefer one click? `scripts/run-from-source.bat` (Windows) or `scripts/run-from-source.sh` (macOS / Linux) create the
virtual environment, install the dependencies and start the app.

### Run on a server (headless / Docker)

```bash
python run.py --headless --data-dir /srv/smartbiz     # bots only, no window; Ctrl+C / SIGTERM stops cleanly
python run.py --healthcheck --data-dir /srv/smartbiz  # exit code 0 = healthy (heartbeat is fresh)
docker compose up -d                                   # uses ./data as the data volume
```

Configure tokens once in the desktop app, then copy `settings.json`, `secret.key` and the `*.db` files into the data
folder (the key must travel with the settings). Headless builds use an OpenAI-compatible API; the offline model needs
the desktop app. Exit codes: `0` stopped, `1` bot manager died (let Docker restart it), `2` no bot configured,
`3` data written by a newer version.

### Run from a USB drive (portable mode)

Download the `*-portable.zip` for your OS and extract it to the drive. It contains a `portable.flag` file and a
`SmartBusinessData/` folder, so **everything** (settings, databases, the encryption key) lives on the drive.
Extract the zips of several OSes into the **same folder** and one drive runs on all of them with one shared
data folder. Details: `README-PORTABLE.txt` inside the zip.

Already installed? Create an empty file named `portable.flag` next to the program, or set
`SMART_BUSINESS_DATA_DIR` to any folder. Never run the same drive on two computers at once, and keep the drive
safe — it holds your bot tokens.

### How payments work

- **Card-to-card:** the customer taps *I paid* (optionally sends a reference); *you* confirm — always manual.
- **Bale Pay:** Bale customers get a native invoice inside the chat. Telegram customers get a link to your Bale
  bot; pressing *Start* there sends the invoice. Only documented Bale Bot API methods are used.
- **Zarinpal:** payment link; the app polls for verification (it has no public callback URL).

### Security & privacy

Data stays on your machine. Bot tokens, the Bale Pay token, proxy lists and the Zarinpal merchant ID are encrypted
and masked in logs. The AI *decides*, the **app validates**: the model cannot invent prices or stock, confirm
payments, or see another customer's orders; customer messages, names and form answers are treated as untrusted
(an abuse/injection regression suite guards this). Customers can type `/forget` to erase their chat and personal
details (if they had sent `/stop`, only a nameless opt-out marker stays so that `/stop` keeps working). The encryption key sits next to the data (so a portable folder is self-contained) — read the
[threat model](SECURITY.md) before trusting the app with real money, and always test with a small amount first.

### Documentation

[`docs/SHOP_SETUP.fa.md`](docs/SHOP_SETUP.fa.md) (owner guide, Persian) ·
[`docs/TESTING_V1.md`](docs/TESTING_V1.md) (what to test on real bots before going public) ·
[`docs/TESTING_V1_1.md`](docs/TESTING_V1_1.md) (phase-1 checklist for 1.1.0) ·
[`docs/PUBLISHING.md`](docs/PUBLISHING.md) (GitHub upload, release, promotion) ·
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (design & money/stock invariants) ·
[`docs/RELEASING.md`](docs/RELEASING.md) · [`docs/ROADMAP.md`](docs/ROADMAP.md) ·
[`docs/testing/`](docs/testing/) (older phase checklists) ·
[`CONTRIBUTING.md`](CONTRIBUTING.md) · [`SECURITY.md`](SECURITY.md)

### Updates, the creator credit and support — what the app does and doesn't do

- **Updates.** On start and every 24 h the app makes one plain request to GitHub's public *latest release* endpoint and shows
  a slim banner if a newer version exists. No server of ours, no telemetry, silent when GitHub is unreachable; switch it off
  under *About*. Installing an update will only ever happen from a release whose checksums carry a valid signature
  (arrives in a later phase); until then the banner just opens the release page.
- **Creator credit.** The app adds **one small line** to each bot's *bio* («Made with Smart Business · github.com/…»). Nothing
  is added to messages, orders or payments. It is visible and previewable under *Bot experience → Bot profile*; your own
  bio text is never erased (it is shown to you first). Being open source, it can of course be removed by forking the code or
  editing the bio in BotFather — this is a transparent default, not a licence requirement.
- **Support.** Entirely optional and tucked away in *About*: you type an amount and a message, the app opens a Daramet page
  in your browser. Everything works fully without it, and the app never sends your data or takes any cut of payments.
- **One-click updates (phase 2).** *Install update* downloads the new release, verifies its Ed25519 signature and SHA-256,
  backs up your data, restarts into the new version and rolls back automatically if it fails to start. Your data is never touched.
- **Customers.** A searchable customer book (purchases, tags, notes, CSV export) built from what the messengers themselves send.
- **Bot admins.** Invite staff by QR/link or ID with roles (manager / support / viewer); they run orders and stock from a button
  panel inside Telegram/Bale (`/admin`), with server-side permission checks and an audit log.
- **Discount codes and campaigns.** Percent or fixed codes (plus automatic discounts) with limits, windows, first-order and
  per-customer rules, product/category scope and stacking; usage is counted atomically with the order, freed on cancel/expiry, and the
  paid amount is never below the gateway minimum. Campaigns send a broadcast with the code, now or scheduled.
- **Backup AIs and cost control.** Save several OpenAI-compatible APIs with several models each (plus the local model as the last
  resort); if one fails the bot switches automatically — keys invalid, credit spent, a model removed, timeouts — without losing the
  conversation memory, and returns to the primary by itself. A *Usage & cost* page shows tokens (real from the API, estimated when
  not), a cost calculator from prices you enter, a monthly budget and what-if estimates. Token savers (smart history window, output
  caps, an optional exact-match answer cache that is off by default) are measured, never guessed (`scripts/bench_tokens.py`).
- **Finance and invoices.** A ledger that fills itself when you confirm orders (sales, gateway fees, cost of goods), manual
  expenses, a dashboard with profit, and Persian PDF invoices (A4/A5, your logo, optional VAT) that the bot can send to the customer
  automatically or on a button. It is a helper for running the shop — **not accounting software and not connected to the tax
  system**; keep working with your accountant.
- **A built-in guide.** A searchable offline guide (139 articles incl. 19 troubleshooting steps and 46 FAQ entries, in Persian), a **?**
  button on every page, a quick-start checklist on the home page and a “the bot isn't answering?” troubleshooter that checks your
  token, proxies, webhook conflict, clock and AI setup.
- **A clean start.** The app starts empty. If its data folder already contains data it asks you once whether to continue or to
  start fresh (a full backup is made first).

### Project status

**v1.1.0 is in progress** (this snapshot: `1.1.0-alpha.5`, phase 5 of 8 — see [CHANGELOG](CHANGELOG.md) and the new
[`docs/TESTING_V1_1.md`](docs/TESTING_V1_1.md)). **v1.0.0** was feature-complete for the first public release. 1,528 automated tests run against fake Telegram /
Bale / Zarinpal / OpenAI servers (both messengers end to end, the shop, payments, delivery, support, migrations,
backups, proxies, headless mode, abuse cases). **Verification against real bots and real gateways still has to be done
per installation** — follow [`docs/TESTING_V1.md`](docs/TESTING_V1.md). Bugs and ideas: Issues.

---

## فارسی

### این برنامه چیه؟

«کسب‌وکار هوشمند» ربات تلگرام یا بله‌ت رو به **دستیار فروشی تبدیل می‌کنه که سفارش رو خراب نمی‌کنه**: مشتری با دکمه
محصولات رو می‌بینه، سبد می‌چینه، به سؤال‌های فرم سفارشِ تو جواب می‌ده، پرداخت می‌کنه و سفارشش رو پیگیری می‌کنه؛ هوش
مصنوعی فقط به سؤال‌هاش جواب می‌ده. همه‌چیز (محصولات، سفارش‌ها، گفتگوها، توکن‌ها) روی **سیستمِ خودت** می‌مونه و
می‌تونی از **روی فلش**، به‌صورت **برنامه‌ی دسکتاپ** یا **headless روی سرور/Docker** اجراش کنی.

> **قاعده‌ی طراحی:** مدل زبانی احتمالاتیه ولی جریانِ پول نباید باشه. در حالتِ پیش‌فرضِ «فروشگاهِ دکمه‌ای» هوش مصنوعی
> هیچ‌وقت سبد/سفارش/پرداخت رو نمی‌سازه یا عوض نمی‌کنه — قیمت، تعداد و موجودی همیشه توسطِ خودِ برنامه چک می‌شه.

### امکانات

| | |
|---|---|
| 🛍 **فروشگاهِ دکمه‌ای** | منوی ثابت، کاتالوگِ صفحه‌بندی‌شده با دسته‌ها، کارتِ محصول با عکس و ➖/➕، سبد، ثبتِ سفارشِ مرحله‌ای، انتخابِ روشِ پرداخت و پیگیری — روی تلگرام و بله یکسان. |
| 🎛 **حالت‌های کاری** | مشاور (فقط گفتگو) · فروشگاهِ دکمه‌ای · سفارش با AI (آزمایشی) · پاسخ‌گویی + پشتیبانیِ انسانی · جمع‌آوریِ سرنخ؛ هر لحظه و برای هر پلتفرم قابل‌تغییر. |
| 📝 **فرمِ سفارشِ خودت** | انتخاب کن چه چیزهایی پرسیده بشه (نام، موبایل، آدرس، کدپستی، ایمیل، گزینه‌ای، دلخواه) — کالای فیزیکی و دیجیتال سؤال‌های متفاوت دارن. |
| 💾 **محصولِ دیجیتال** | تحویلِ خودکار بعد از تأیید: متن، لینک، فایل یا **کلید/لایسنس** (هر خرید یک کلید، بدونِ تکرار). |
| 🔘 **دکمه‌های سفارشی و سؤالات متداول** | لینک، تماس (شماره + کارتِ تماس)، پاسخ متنی، پشتیبانیِ انسانی، پرسش از AI … توی منوی خودت. |
| 🙋 **پشتیبانیِ انسانی** | مشتری «پشتیبانی» رو می‌زنه و تو همون‌جا توی تلگرام/بله با Reply جواب می‌دی؛ ساعتِ کاری و بسته‌شدنِ خودکار هم داره. |
| 🌐 **فارسی و انگلیسی** | همه‌ی پیام‌های ربات قابل‌ویرایش و دوزبانه‌ست؛ زبان می‌تونه از روی مشتری انتخاب بشه. |
| ⏳ **رزروِ موجودی** | سفارشِ منتظرِ پرداخت تعدادش رو (پیش‌فرض ۱۵ دقیقه) نگه می‌داره؛ دو مشتری هیچ‌وقت آخرین کالا رو هم‌زمان رزرو نمی‌کنن. |
| 💳 **سه روش پرداخت — همه به حسابِ خودت** | کارت‌به‌کارت، **بله‌پی**، **زرین‌پال**. هیچ پولی از برنامه عبور نمی‌کنه. |
| 🔔 **کنسولِ مالک** | اعلان توی چتِ خودت؛ `/confirm 12`، `/reject 12`، `/reply`، `/close`، `/handoffs`. |
| 🛡 **امن از پایه** | تأییدِ سفارشِ ضدِ کرش، مهاجرتِ نسخه‌دارِ دیتابیس با پشتیبانِ خودکار، سقفِ هزینه‌ی AI و کلیدِ قطعِ اضطراری، `/forget`، نگه‌داریِ محدودِ داده. |
| 🔌 **پروکسی** | استخر با جابه‌جاییِ خودکار، **لینکِ اشتراکِ** خودت، بازگشتِ خودکار به سریع‌ترین پروکسی. |
| 🤖 **هوش مصنوعیِ دلخواه** | هر API سازگار با OpenAI یا مدلِ GGUF محلی (آفلاین). |
| 🧳 **قابل‌حمل · 🐳 Docker** | نسخه‌ی فلش برای ویندوز/مک/لینوکس؛ `python run.py --headless` یا `docker compose up -d` برای سرور. |
| 📣 **پیامِ همگانی** | یک پیام برای همه یا بخشی از مشتری‌ها (خریدار، جدید، غیرفعال، برچسب، زبان) با شمارشِ زنده‌ی گیرنده‌ها، پیش‌نمایش، ارسالِ آزمایشی به خودت، سقفِ روزانه و سرعتِ امنی که محدودیتِ تلگرام/بله رو رعایت می‌کنه. پانویسِ «برای توقف /stop» به‌صورتِ پیش‌فرض روشنه؛ به بلاک‌شده و لغوکرده هرگز پیام نمی‌ره. |
| ✉️ **پیامِ شخصی** | از صفحه‌ی «گفتگوها» به یک مشتری پیام بده (با پاسخ‌های آماده). مشتری «💬 فروشگاه: …» می‌بینه، در تاریخچه می‌مونه و AI هم ازش خبر داره. |
| 📢 **عضویتِ اجباریِ کانال** | مشتری اول باید در کانال(های) تلگرام/بله عضو بشه (منو، گفتگو با AI، یا هر دو). خودت و مدیرها معافید؛ اگه بررسی خراب بشه کسی قفل نمی‌شه و خبردار می‌شی. |

### دانلود

از بخش **Releases** همین مخزن یکی از فایل‌ها رو بگیر:

| فایل | برای چی؟ |
|---|---|
| `SmartBusinessLocal-<نسخه>-windows-setup.exe` | نصب‌کننده‌ی ویندوز (برای کاربر فعلی، بدونِ نیاز به ادمین) |
| `SmartBusinessLocal-<نسخه>-windows.exe` | ویندوز، تک‌فایل — دابل‌کلیک و اجرا |
| `SmartBusinessLocal-<نسخه>-windows-portable.zip` | نسخه‌ی فلش برای ویندوز |
| `SmartBusinessLocal-<نسخه>-macos-portable.zip` | نسخه‌ی فلش برای مک *(آزمایشی)* |
| `SmartBusinessLocal-<نسخه>-linux-portable.zip` | نسخه‌ی فلش برای لینوکس *(آزمایشی)* |
| `SHA256SUMS.txt` | چک‌سام برای اطمینان از سالم‌بودنِ دانلود |

> فایل‌ها **هنوز امضای دیجیتال ندارن**: ویندوز ممکنه «Unknown publisher» بگه (*More info ← Run anyway*) و روی مک بار اول
> باید روی برنامه راست‌کلیک ← *Open* بزنی. اگه شک داری چک‌سام رو تطبیق بده. فرایندِ انتشار: [`docs/RELEASING.md`](docs/RELEASING.md).

### شروع سریع

۱. ربات بساز — تلگرام: `@BotFather`؛ بله: *BotFather* بله. توکن رو کپی کن.
۲. برنامه رو باز کن و مراحلِ خوش‌آمد رو برو. توی صفحه‌ی **ربات‌ها** توکن رو بچسبون ← *تست اتصال* ← ربات رو روشن کن. اگه تلگرام
   توی کشورت پروکسی می‌خواد، یکی یا چندتا (هر خط یکی) یا لینکِ اشتراک بذار.
۳. هوش مصنوعی رو انتخاب کن (کلید API یا مدلِ محلی)، محصولات رو اضافه کن (فیزیکی یا دیجیتال) و پرداخت رو تنظیم کن.
۴. «تجربه‌ی ربات» ← *پیش‌نمایشِ مشتری* رو باز کن و بدونِ خروج از برنامه یک خریدِ کامل رو امتحان کن؛ بعد با رباتِ واقعی حرف بزن.

راهنمای صاحبِ فروشگاه (فارسی، قدم‌به‌قدم): [`docs/SHOP_SETUP.fa.md`](docs/SHOP_SETUP.fa.md).

**توسعه‌دهنده‌ها**

```bash
git clone <repo-url> && cd smart-business-local
python -m venv .venv && source .venv/bin/activate     # ویندوز: .venv\Scripts\activate
pip install -r requirements-dev.txt
python run.py            # پنجره‌ی دسکتاپ
python run.py --web      # در مرورگر
python -m pytest         # کلِ تست‌ها — بدونِ اینترنت و بدونِ رباتِ واقعی
```

یک‌کلیکی؟ `scripts/run-from-source.bat` (ویندوز) یا `scripts/run-from-source.sh` (مک/لینوکس) محیطِ مجازی می‌سازن، وابستگی‌ها رو
نصب می‌کنن و برنامه رو بالا میارن.

### اجرا روی سرور (headless / Docker)

```bash
python run.py --headless --data-dir /srv/smartbiz     # فقط ربات‌ها، بدونِ پنجره؛ Ctrl+C / SIGTERM تمیز متوقفش می‌کنه
python run.py --healthcheck --data-dir /srv/smartbiz  # کدِ خروج ۰ = سالم (heartbeat تازه است)
docker compose up -d                                   # پوشه‌ی ./data رو به‌عنوان داده استفاده می‌کنه
```

توکن‌ها رو یک‌بار توی برنامه‌ی دسکتاپ تنظیم کن، بعد `settings.json`، `secret.key` و فایل‌های `*.db` رو توی پوشه‌ی داده کپی کن
(کلید باید همراهِ تنظیمات بره). حالتِ headless با API سازگار با OpenAI کار می‌کنه؛ مدلِ آفلاین نیاز به برنامه‌ی دسکتاپ داره.
کدهای خروج: `0` توقفِ عادی، `1` مدیرِ ربات‌ها مُرد (بذار Docker دوباره بالا بیاره)، `2` رباتی تنظیم نیست، `3` داده با نسخه‌ی جدیدتری ساخته شده.

### اجرا از روی فلش (حالت قابل‌حمل)

فایلِ `*-portable.zip` مخصوصِ سیستم‌عاملت رو دانلود و روی فلش استخراج کن. داخلش یه فایل `portable.flag` و یه پوشه‌ی
`SmartBusinessData/` هست؛ پس **همه‌چیز** (تنظیمات، دیتابیس‌ها، کلیدِ رمزنگاری) روی فلش می‌مونه. zipِ چند سیستم‌عامل رو توی **همون پوشه**
استخراج کن تا یک فلش روی همه‌شون با یک پوشه‌ی داده‌ی مشترک کار کنه. جزئیات: `README-PORTABLE.txt` داخلِ zip.

قبلاً نصب کردی؟ یه فایلِ خالی به اسم `portable.flag` کنارِ برنامه بساز یا `SMART_BUSINESS_DATA_DIR` رو روی هر پوشه‌ای بذار.
هیچ‌وقت یک فلش رو هم‌زمان روی دو کامپیوتر اجرا نکن و فلش رو امن نگه دار — توکن‌های رباتت روشه.

### پرداخت چطور کار می‌کنه؟

- **کارت‌به‌کارت:** مشتری «پرداخت کردم» رو می‌زنه (اگه خواست شماره‌ی پیگیری هم می‌فرسته) و *تو* تأیید می‌کنی — همیشه دستی.
- **بله‌پی:** مشتریِ بله فاکتورِ بومی توی همون چت می‌گیره. مشتریِ تلگرام لینکی به رباتِ بله‌ی تو می‌گیره؛ با زدنِ *Start* همون‌جا فاکتور میاد.
  فقط متدهای مستندِ Bot API بله استفاده می‌شه.
- **زرین‌پال:** لینکِ پرداخت؛ برنامه خودش وضعیت رو پیگیری می‌کنه (آدرسِ عمومیِ callback نداره).

### امنیت و حریم خصوصی

داده روی سیستمِ خودته. توکن‌های ربات، توکنِ بله‌پی، لیستِ پروکسی و merchant-id زرین‌پال رمزنگاری می‌شن و توی لاگ مخفی‌ان. هوش
مصنوعی *تصمیم می‌گیره*، **برنامه اعتبارسنجی می‌کنه**: مدل نمی‌تونه قیمت یا موجودی بسازه، پرداخت تأیید کنه یا سفارشِ مشتریِ دیگه رو ببینه؛
پیام‌ها، نام‌ها و پاسخ‌های فرم همیشه «نامطمئن» حساب می‌شن (یک مجموعه‌تستِ سوءاستفاده/تزریق نگهبانشه). مشتری با `/forget` گفتگو و
مشخصاتِ شخصیش رو پاک می‌کنه (اگه قبلاً `/stop` زده باشه فقط یک «علامتِ لغوِ بی‌نام» می‌مونه تا `/stop` معتبر بمونه). کلیدِ رمزنگاری کنارِ داده‌ست (تا پوشه‌ی قابل‌حمل خودکفا باشه) — قبل از سپردنِ پولِ واقعی
[مدلِ تهدید](SECURITY.md) رو بخون و همیشه اول با مبلغِ کم تست کن.

### مستندات

[`docs/SHOP_SETUP.fa.md`](docs/SHOP_SETUP.fa.md) (راهنمای مالک) ·
[`docs/TESTING_V1.md`](docs/TESTING_V1.md) (قبل از عمومی‌شدن روی رباتِ واقعی چی تست کنی) ·
[`docs/TESTING_V1_1.md`](docs/TESTING_V1_1.md) (چک‌لیستِ فازِ ۱ از ۱.۱.۰) ·
[`docs/PUBLISHING.md`](docs/PUBLISHING.md) (آپلود روی GitHub، انتشار، معرفی) ·
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (طراحی و ناوردایی‌های پول/موجودی) ·
[`docs/RELEASING.md`](docs/RELEASING.md) · [`docs/ROADMAP.md`](docs/ROADMAP.md) ·
[`docs/testing/`](docs/testing/) (چک‌لیست‌های فازهای قبلی) ·
[`CONTRIBUTING.md`](CONTRIBUTING.md) · [`SECURITY.md`](SECURITY.md)

### به‌روزرسانی، اعتبارِ سازنده و حمایت — برنامه دقیقاً چه می‌کنه و چه نمی‌کنه

- **به‌روزرسانی.** هنگامِ شروع و هر ۲۴ ساعت، برنامه یک درخواستِ ساده به صفحه‌ی عمومیِ «آخرین نسخه»ی GitHub می‌زنه و اگه نسخه‌ی
  تازه‌تری باشه یک نوارِ باریک نشون می‌ده. سرورِ اختصاصی، ردیابی و آمارگیری نیست؛ اگه GitHub در دسترس نباشه بی‌صدا رد می‌شه؛ از
  «درباره» خاموشش کن. نصبِ یک‌کلیکی فقط از نسخه‌ای انجام می‌شه که امضای معتبر داشته باشه؛ بدونِ آن، نوار فقط صفحه‌ی نسخه رو باز می‌کنه.
- **اعتبارِ سازنده.** برنامه **فقط یک خطِ کوچک** («ساخته‌شده با کسب‌وکار هوشمند · github.com/…») به *بیوگرافیِ* هر ربات اضافه می‌کنه.
  هیچ‌چیز در پیام‌ها، سفارش‌ها و پرداخت‌ها اضافه نمی‌شه. در «تجربه‌ی ربات ← پروفایلِ ربات» دیده و پیش‌نمایش می‌شه و متنِ خودت هرگز
  پاک نمی‌شه (اول بهت نشون داده می‌شه). چون متن‌بازه، با فورکِ کد یا ویرایشِ بیو در BotFather می‌شه حذفش کرد — این یک پیش‌فرضِ
  شفافه، نه الزامِ مجوز.
- **حمایت.** کاملاً اختیاری و گوشه‌ی «درباره»: مبلغ و پیام رو خودت می‌نویسی و برنامه صفحه‌ی دارمت رو در مرورگرت باز می‌کنه.
  بدونِ حمایت هم همه‌چیز کامله؛ برنامه هیچ داده‌ای نمی‌فرسته و از پرداخت‌های تو سهمی برنمی‌داره.
- **نصبِ یک‌کلیکیِ به‌روزرسانی (فازِ ۲).** «نصبِ به‌روزرسانی» نسخه‌ی تازه رو دانلود می‌کنه، امضای Ed25519 و SHA-256 رو بررسی می‌کنه،
  از داده‌هات پشتیبان می‌گیره، با نسخه‌ی جدید دوباره باز می‌شه و اگه بالا نیومد خودش برمی‌گرده. داده‌ی تو هرگز دست نمی‌خوره.
- **مشتریان.** دفترِ مشتری‌های قابل‌جست‌وجو (خریدها، برچسب، یادداشت، خروجیِ CSV) فقط از چیزی که خودِ پیام‌رسان می‌فرسته.
- **مدیرانِ ربات.** کارمندانت رو با QR/لینک یا شناسه و با نقش (مدیر / پشتیبان / ناظر) اضافه کن؛ از پنلِ دکمه‌ای داخلِ تلگرام/بله
  (`/admin`) سفارش و موجودی رو اداره می‌کنن؛ مجوزها سمتِ سرور کنترل می‌شه و لاگِ ممیزی داره.
- **کدِ تخفیف و کمپین.** کدِ درصدی یا مبلغِ ثابت (و تخفیفِ خودکار) با سقف، بازه‌ی زمانی، فقط اولین خرید، سقفِ هر مشتری، محدودیت به محصول/دسته
  و قابلیتِ جمع‌شدن؛ مصرفِ کد همزمان با ساختِ سفارش شمرده می‌شه، با لغو/انقضا آزاد می‌شه و مبلغِ پرداختی هرگز زیرِ حداقلِ درگاه نمی‌آد.
  کمپین یک پیامِ همگانی همراهِ کد است، فوری یا زمان‌بندی‌شده.
- **AIِ پشتیبان و کنترلِ هزینه.** چند API سازگار با OpenAI با چند مدل ذخیره کن (و مدلِ محلی به‌عنوان آخرین پناه)؛ اگه یکی از کار بیفته
  (کلیدِ نامعتبر، اعتبارِ تمام‌شده، مدلِ حذف‌شده، timeout) ربات خودکار سراغِ بعدی می‌ره، بدونِ از دست رفتنِ حافظه‌ی گفتگو، و خودش به اصلی
  برمی‌گرده. صفحه‌ی «مصرف و هزینه»: توکنِ واقعی (یا تخمینیِ برچسب‌دار)، محاسبه‌گرِ هزینه از قیمت‌هایی که خودت وارد می‌کنی، بودجه‌ی ماهانه و
  «چه می‌شود اگر». صرفه‌جوییِ توکن (پنجره‌ی هوشمندِ تاریخچه، سقفِ خروجی، کشِ پاسخِ یکسانِ پیش‌فرض‌خاموش) اندازه‌گیری می‌شه، نه حدس
  (`scripts/bench_tokens.py`).
- **مالی و فاکتور.** دفتری که با تأییدِ سفارش خودش پر می‌شه (فروش، کارمزدِ درگاه، بهای کالا)، هزینه‌های دستی، داشبوردِ سود و
  فاکتورِ PDFِ فارسی (A4/A5، لوگوی خودت، مالیاتِ اختیاری) که ربات می‌تونه خودکار یا با یک دکمه برای مشتری بفرسته. این بخش یک ابزارِ
  کمکی برای اداره‌ی فروشگاهه — **نرم‌افزارِ حسابداری نیست و به سامانه‌ی مالیاتی وصل نیست**؛ با حسابدارت کار کن.
- **راهنمای داخلِ برنامه.** یک راهنمای آفلاین و قابلِ جستجو (۱۳۹ مقاله از جمله ۱۹ مورد عیب‌یابی و ۴۶ پرسش‌وپاسخ)، دکمه‌ی **؟** کنارِ هر صفحه،
  چک‌لیستِ شروعِ سریع در صفحه‌ی خانه و یک عیب‌یابِ «ربات جواب نمی‌ده؟» که توکن، پروکسی، تداخلِ webhook، ساعت و تنظیمِ هوش مصنوعی را می‌سنجه.
- **شروعِ تمیز.** برنامه خالی شروع می‌شه. اگه پوشه‌ی داده از قبل داده داشته باشه، یک‌بار می‌پرسه ادامه بدی یا از اول شروع کنی (قبلش
  پشتیبانِ کامل گرفته می‌شه).

### وضعیت پروژه

**نسخه‌ی ۱.۱.۰ در دست ساخت است** (این نسخه: `1.1.0-alpha.5`، فازِ ۵ از ۸ — [CHANGELOG](CHANGELOG.md) و
[`docs/TESTING_V1_1.md`](docs/TESTING_V1_1.md) رو ببین). **نسخه‌ی ۱.۰.۰** برای انتشارِ عمومیِ اول کامل بود. بیش از ۱۵۰۰ تستِ خودکار روی سرورهای جعلیِ تلگرام/بله/زرین‌پال/OpenAI اجرا می‌شه
(هر دو پیام‌رسان سرتاسری، فروشگاه، پرداخت، تحویل، پشتیبانی، مهاجرت، پشتیبان‌گیری، پروکسی، حالتِ headless، سوءاستفاده).
**راستی‌آزمایی روی رباتِ واقعی و درگاهِ واقعی هنوز باید برای هر نصب انجام بشه** — طبقِ [`docs/TESTING_V1.md`](docs/TESTING_V1.md).
باگ و ایده: بخش Issues.

---

## License · مجوز

[MIT](LICENSE) © 2026 Mohammad Mahdi
