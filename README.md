<div align="center">

<img src="assets/icons/app-icon-256.png" alt="Smart Business Local icon" width="120">

# Smart Business — Local Edition
# کسب‌وکار هوشمند (نسخه‌ی محلی)

**A free, open-source shop assistant for Telegram that runs entirely on your own computer.
The AI is a local model, so there is no server to rent, no API bill, and no customer data leaving your machine.**

*دستیارِ فروشگاهِ رایگان و متن‌باز برای تلگرام، کاملاً روی سیستمِ خودت.
هوش مصنوعیِ محلی، بدون سرور، بدون هزینه‌ی API، بدونِ رفتنِ اطلاعاتِ مشتری به جایی.*

![License: MIT](https://img.shields.io/badge/license-MIT-blue)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![Platforms](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey)
![Runs from source on macOS](https://img.shields.io/badge/macOS-from%20source-orange)
![AI](https://img.shields.io/badge/AI-local%20GGUF%20only-green)
![Messenger](https://img.shields.io/badge/messenger-Telegram-2CA5E0)
![Version](https://img.shields.io/badge/version-1.0.0-informational)

[English](#english) · [فارسی](#فارسی) · [Download](#download) · [Changelog](CHANGELOG.md) · [Roadmap](docs/ROADMAP.md) · [License](LICENSE)

<!-- Once CI is green, add your own badges, e.g.
![CI](https://github.com/<you>/<repo>/actions/workflows/ci.yml/badge.svg) -->

</div>

---

## English

### What it is

Smart Business turns a Telegram bot into a **shop assistant that never fumbles an order**. Customers browse a catalog
with buttons, fill a cart, answer your checkout questions, pay and track their order; a **local AI model** answers their
free-text questions in between. Everything — products, orders, chats, tokens — stays on **your** computer, and the model
runs on it too (llama.cpp, GGUF files).

> **Design rule:** an LLM is probabilistic; money flows must not be. The AI has **no tool** to add to the cart, create an
> order, start a payment or confirm one — the app computes every price, quantity and stock level itself, and
> card-to-card confirmation is always a human decision.

*Screenshots of the model picker, the shop and the orders page will be added here; until then the in-app guide
(Persian, offline, 185 articles) explains what every screen does.*

### Highlights

| | |
|---|---|
| 🛍 **Four-button shop** | Persistent customer menu — Products · Cart · My orders · Contact support — with a paginated catalog, categories, product cards with photo and ➖/➕ quantity, step-by-step checkout and order tracking. |
| 🎛 **Two modes** | *Advisor* (the bot only talks, using your persona text) and *Shop* (the button shop). Nothing else to choose. |
| 🧠 **Local AI, one click** | The app reads your RAM/CPU/GPU/disk, ranks six GGUF models for your machine, downloads the pick with progress, pause, resume and a SHA-256 check — or imports a file you already have. |
| 📝 **Your checkout form** | Choose which fields to ask (name, phone, address, postal code, e-mail, choices, custom) — required or optional, per your shop. |
| 📥 **Bulk Excel import** | The app builds a real `.xlsx` template (name, price, stock, category, description, cost); fill it in Excel and import it back. Bad rows are reported by row number, good ones are saved in one transaction. CSV works too. |
| 🔘 **Guide & FAQ inside support** | Help and your FAQ live under the *Contact support* button, next to your custom buttons (link, text reply, contact card). |
| 🙋 **Human support** | A customer taps *talk to a human* and their messages reach you from then on; you answer by *Reply* in Telegram. Working hours and auto-close included. |
| 🌐 **Persian & English** | All 213 bot messages are editable and bilingual; the reply language can follow the customer; every date is Jalali. |
| ⏳ **Stock reservation** | An order awaiting payment holds its quantity (15 minutes by default); two customers can never reserve the last item. |
| 📦 **Delivery status** | A confirmed order gets its own track — preparing → shipped → delivered — with an optional tracking code, completely separate from the money. The customer sees it under *My orders*, and if you switch it on, a short "it has been sent" message goes out with the code. |
| 💳 **Two payment methods — both to *your* accounts** | Card-to-card (manual confirmation) and **Bale Pay** (a payment gateway). No money flows through the app and it takes no cut. |
| 🚚 **Shipping methods** | Your own list of post/courier options with a cost and an optional "free above" threshold. The final amount is items − discount + shipping, and the invoice, the ledger and the finance dashboard all agree on it. Until you add a method nothing changes: no extra question, no extra cost. |
| 🔔 **Receipt alarms** | When the customer says *I paid* and sends a receipt, the app records it, compares the amount and alerts you and your managers immediately — it never approves anything for you. Next to each order there is also a read-only payment panel: method, amount due, receipt amount, trace code, any mismatch (in red) and who confirmed, with a Jalali date. |
| 🧾 **Ledger and Persian PDF invoices** | A ledger that fills itself when you confirm orders, manual expenses, a profit dashboard, refunds you still owe, and A4/A5 Persian invoices with your logo and optional VAT. |
| 🔎 **Search across everything** | One box for orders, products and customers — by order number, product name, customer name or phone number — and every result has a button that opens that very page. It only reads the local database and changes nothing. |
| 📣 **Broadcast** | One message to everyone or a segment (buyers, new, inactive, tag, language) with a live recipient count, preview, a test to yourself, a daily cap and a safe speed. A *"send /stop to unsubscribe"* footer is on by default. |
| ✉️ **Personal messages** | Write to one customer from the *Chats* page (with quick replies). They see "Shop: …", it stays in the history and the model knows about it. |
| 📢 **Required channel** | Customers must join your Telegram channel(s) first (menu, AI chat, or both). You and your managers are exempt; if the check ever breaks, nobody is locked out and you are told. |
| 🔌 **Proxy pool** | Several proxies (one per line) with automatic failover, your own **subscription link** and automatic return to the fastest one — Telegram is often unreachable without it in Iran. |
| 🛡 **Guardrails you cannot delete** | The app appends fixed rules to every prompt (limits, menu map, tone, privacy, content boundaries) and shows you exactly what the model will read. |
| 📊 **Excel and PDF export** | Every list you can see (customers, orders, finance report, products, conversations) becomes an RTL Excel or PDF file in the `reports` folder with two buttons. |
| 📚 **Built-in guide** | An offline, searchable Persian guide (185 articles: 25 troubleshooting, 58 FAQ), a **?** button on every page and an automatic troubleshooter. |

### Download

Grab a file from this repository's **Releases** page:

| File | Use it for |
|---|---|
| `SmartBusinessLocal-<version>-windows-setup.exe` | Windows installer (per user, no admin needed) |
| `SmartBusinessLocal-<version>-windows.exe` | Windows single file — double-click and run |
| `SmartBusinessLocal-<version>-linux.tar.gz` | Linux (tar keeps the executable bit and symlinks) |
| `SHA256SUMS.txt` | Checksums to verify your download |

> The builds are **not code-signed yet**: Windows SmartScreen may say "unknown publisher" (*More info → Run
> anyway*). **There is no macOS binary** — on a Mac run it from source (`scripts/run-from-source.sh`). Verify the checksum if in doubt.
> There is no portable/USB edition — data always lives in your user profile.
> Release process: [`docs/RELEASING.md`](docs/RELEASING.md).

### Quick start

1. Create a bot in Telegram with `@BotFather` (`/newbot`), paste the token on the **Bots** page, press *Test
   connection*, then turn the bot on. If Telegram needs a proxy in your country, add one or more (one per line).
2. On the **AI** page, take the model the app already labelled *our pick* and press *Download & use*. Skip it if you
   only want the buttons — the shop works with no model at all.
3. Write the bot's persona on the **Prompt** page (12 ready-made templates, live preview of what the model reads).
4. Add products, then open **Orders → Payment settings** and at least fill in your card number for card-to-card.
5. Open **Bot experience → Customer preview** and walk through a purchase without leaving the app; then talk to your
   real bot from a second account and confirm the test order.

Shop-owner guide (Persian, step by step): [`docs/SHOP_SETUP.fa.md`](docs/SHOP_SETUP.fa.md).

### For developers

```bash
git clone <repo-url> && cd smart-business-local
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python run.py            # desktop window
python run.py --web      # in the browser
python -m pytest         # full suite — no internet, no real bots needed
```

Prefer one click? `scripts/run-from-source.bat` (Windows) or `scripts/run-from-source.sh` (macOS / Linux) create the
virtual environment, install the dependencies and start the app. Architecture and invariants:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

### How the local AI works

- **Only local.** There is no API key, no provider list, no failover and no cost budget — those screens were never
  shipped. The AI is a GGUF model that your own computer runs.
- **Six models, honest labels.** Each card shows the exact file size, answer quality and speed (five stars each,
  relative to this catalog), the licence (Apache-2.0) and whether it fits your machine: *our pick* · *good fit* ·
  *borderline* · *does not fit this machine*. Sizes run from about 1.2 GB to about 5.7 GB.
- **Hardware first.** The app reads total RAM, core count, CPU and GPU name and free disk space, and computes how much
  memory each model needs. It conservatively treats only 85 % of your RAM as usable, so it never promises a model that
  would freeze your PC mid-reply.
- **Download, resume, verify.** One click starts a background download with a progress bar, speed and time left;
  *Cancel* keeps what arrived and *Resume download* continues from the same byte — a dropped connection or a closed app
  is not a restart. Two sources are tried in order (the main host and one mirror) for users who cannot reach it.
  A finished file is checked against a pinned SHA-256; a corrupt or substituted file is refused, never loaded.
- **Your own file.** If every source is blocked, take the GGUF from a friend or a manual download and use *Import a
  model file*; the app validates that it really is a GGUF (extension, size, magic header) before accepting it.
- **CPU by default.** The official build computes on the CPU, so an NVIDIA GPU does not speed it up unless you install
  a CUDA build yourself and raise the GPU-layers setting in the advanced panel. The app asks the installed runtime
  instead of guessing from the card name, and the built-in guide has the step-by-step CUDA setup.
- **Advanced panel.** Model folder, context tokens, thread count, GPU layers, per-customer and daily reply caps and an
  emergency kill switch. Caps slow the AI down; buttons, carts, orders and payments are never blocked by them.
- **No cost, but there is time.** A local model costs electricity and CPU seconds, so the *Usage* page reports tokens,
  milliseconds per reply and time per 1,000 tokens instead of money.
- **Nothing to send.** Customer text never leaves the machine for inference. The only outbound traffic is Telegram (the
  chat itself), GitHub (version check and model download) and Bale (payment, only if you enable it).

### How payments work

- **Card-to-card (manual, always).** The customer sees your card number and the exact amount, taps *I paid* and sends a
  receipt — its text or its photo. The app stores the receipt, extracts amount / trace code / last four digits, compares
  the number with the order and raises an instant alarm to you (and to managers allowed to decide orders) plus an entry
  in the *Needs attention* inbox. **Confirming is a human action**, on the Orders page or with `/confirm 12`; the app has
  no access to your bank account and cannot approve anything.
- **Bale Pay (gateway, optional).** You create a payment bot in Bale and paste its token plus the gateway
  `provider_token` into the app. A Telegram customer taps *Pay in Bale* and goes straight into Bale's payment sheet via
  `createInvoiceLink`; if no link comes back, the same invoice is sent through the payment bot's deep link, and the
  customer can type `/pay`. A payment is auto-confirmed only after the gateway confirms it and the amount, currency,
  order payload and a transaction inquiry all match — late payments, mismatched amounts and reused transaction ids are
  never auto-approved.
- **Bale chat is optional and independent.** Bale can also carry the conversational bot (same AI, same shop, its own
  token and its own AI switch) at `tapi.bale.ai`. Chatting on Bale and paying through Bale Pay are two separate
  settings: Telegram only, Bale only, both, or neither — and Bale Pay alone works without any chat bot.
- **No Zarinpal.** Card-to-card and Bale Pay are the two methods; payment settings keys from older private builds are
  ignored quietly and nothing else is touched.

### Security & privacy

Data stays on your machine. The Telegram token, proxy addresses, the Bale payment bot token and the gateway provider
token are encrypted at rest and redacted from logs; your own card number is deliberately not encrypted because the
customer sees it anyway. The AI *suggests* and the **app validates**: the model cannot invent prices or stock, confirm
payments, or see another customer's data — the customer's name and message are marked untrusted in every prompt, and
fixed guardrails you cannot delete are appended to it. Receipt photos are downloaded only with an extension allow-list,
a size cap and a file name the app invents itself (never the name the server offers). Customers can type `/forget` to
erase their chat and personal details, and `/stop` always works. The encryption key sits next to the data so a backup is
self-contained — read the full [threat model](SECURITY.md) before trusting the app with real money, and always test with
a small amount first.

### Limitations, stated honestly

- Windows and Linux binaries are built **in GitHub CI**; no build has been smoke-run by us on real Windows hardware,
  and **there is no macOS binary** — on a Mac the app is run from source.
- **Real Telegram and real gateway behaviour is user-verified.** The automated suite runs against fake servers, so every
  installation should complete one real purchase with a small amount before taking money.
- The binaries are **unsigned** (no paid code-signing certificate), so Windows SmartScreen warns on first run.
- One-click updates install only from a release whose checksums carry a valid signature; if a build is unsigned, the app
  just opens the download page.
- The finance section is a **helper, not accounting**: no tax filing, no connection to the Iranian tax system and no
  official invoice registration. Keep working with your accountant.
- The AI is as good as the small local model you run: it can be wrong, it answers slowly on weak hardware, and it must
  never be trusted with prices that only live in its prompt.
- One shop per installation, and Telegram only — no WhatsApp, Instagram or Eitaa.

### Documentation

[`docs/SHOP_SETUP.fa.md`](docs/SHOP_SETUP.fa.md) (owner guide, Persian) ·
[`docs/PUBLISHING.md`](docs/PUBLISHING.md) (GitHub upload, release, promotion) ·
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (design & money/stock invariants) ·
[`docs/RELEASING.md`](docs/RELEASING.md) (build pipeline, signing, troubleshooting) ·
[`docs/ROADMAP.md`](docs/ROADMAP.md) ·
[`docs/BOT_FEATURES.fa.txt`](docs/BOT_FEATURES.fa.txt) (plain functional brief for AI-assisted marketing copy) ·
[`CONTRIBUTING.md`](CONTRIBUTING.md) · [`SECURITY.md`](SECURITY.md)

### Updates, the creator credit and support

- **Updates.** On start and every 24 h the app makes one plain request to GitHub's public *latest release* endpoint and
  shows a slim banner if a newer version exists. No server of ours, no telemetry, silent when GitHub is unreachable; you
  can switch it off under *About*.
- **One-click install.** The updater downloads the new release, verifies its Ed25519 signature and SHA-256, backs up
  your data, restarts into the new version and rolls back automatically if it fails to start. Your data is never
  touched.
- **Creator credit.** The app adds **one small line** to each bot's *bio* ("Made with Smart Business" plus the
  repository link). Nothing is added to messages, orders or payments; it is previewable under *Bot experience → Bot
  profile*, your own bio text is never erased, and because this is open source you can remove it by editing the code or
  the bio in BotFather — a transparent default, not a licence requirement.
- **Support.** Entirely optional and tucked away in *About*: you type an amount and a message, and the app opens a
  donation page in your browser. Everything works fully without it, and the app never sends your data or takes any cut.
- **Customers and staff.** A searchable customer book (purchases, tags, notes, CSV export) built from what Telegram
  itself sends; staff invited by QR/link/ID with roles (manager / support / viewer) run orders and stock from a button
  panel (`/admin`), with permission checks done in the app and an audit log.
- **Discounts and campaigns.** Percent or fixed codes plus automatic discounts, with limits, windows, first-order and
  per-customer rules, product/category scope and stacking; usage is counted atomically with the order and freed on
  cancel or expiry. A campaign sends a broadcast with the code, now or scheduled.
- **Backups, migrations, crash safety.** Versioned database migrations with an automatic backup, atomic settings
  writes, a corrupt `settings.json` quarantined instead of overwritten, and order confirmation that finishes itself
  after a crash without double-decrementing stock.
- **Privacy tools.** Data-retention window, `/forget`, redacted logs, a diagnostics file that contains no chats, tokens
  or orders, and an optional factory reset that asks you to type a word first.

### Run on a server (headless / Docker)

```bash
python run.py --headless --data-dir /srv/smartbiz     # bots only, no window; Ctrl+C / SIGTERM stops cleanly
python run.py --healthcheck --data-dir /srv/smartbiz  # exit code 0 = healthy (heartbeat is fresh)
docker compose up -d                                   # uses ./data as the data volume
```

Configure tokens once in the desktop app, then copy `settings.json`, `secret.key` and the `*.db` files into the data
folder (the key must travel with the settings). Headless and Docker do **not** include the model runtime: buttons, cart,
orders, payments and invoices keep working, free-text answers stay off. Exit codes: `0` stopped, `1` the bot manager
died (let Docker restart it), `2` no bot configured, `3` data written by a newer version.

### Project status

**This is the first public release (1.0.0)**: local-only AI, Telegram as the main messenger (an optional, independent Bale
chat on top of it), Bale Pay as the only gateway
besides card-to-card, a four-button customer menu and a central prompt studio. The version string lives in
`app/version.py` and a release tag must match it; see [CHANGELOG](CHANGELOG.md) for what shipped and what was cut. The
automated suite (2208 tests in 107 files) runs against fake Telegram and fake Bale-pay servers and covers the shop,
payments, receipts, fulfilment, support, migrations, backups, proxies, headless mode, report exports, injection and
abuse cases.
**Verification against real bots and a real gateway still has to be done per installation** — run one complete purchase
with a small amount before you take real money. Bugs and ideas: Issues.

---

## فارسی

### این برنامه چیه؟

«کسب‌وکار هوشمند» رباتِ تلگرامِ تو را به **دستیار فروشی تبدیل می‌کند که سفارش را خراب نمی‌کند**: مشتری با دکمه‌ها
محصولات را می‌بیند، سبد می‌چیند، به سؤال‌های فرمِ سفارش جواب می‌دهد، پرداخت می‌کند و سفارشش را پیگیری می‌کند؛ و یک
**مدلِ هوش مصنوعیِ محلی** به سؤال‌های نوشتاری جواب می‌دهد. همه‌چیز (محصولات، سفارش‌ها، گفتگوها، توکن‌ها) روی **کامپیوترِ
خودت** می‌ماند و خودِ مدل هم روی همان کامپیوتر اجرا می‌شود.

> **قاعده‌ی طراحی:** مدلِ زبانی احتمالاتی است ولی جریانِ پول نباید احتمالاتی باشد. هوش مصنوعی **هیچ ابزاری** برای
> اضافه‌کردن به سبد، ساختنِ سفارش، شروعِ پرداخت یا تأییدِ پرداخت ندارد؛ قیمت، تعداد و موجودی را همیشه خودِ برنامه
> حساب می‌کند و تأییدِ کارت‌به‌کارت همیشه کارِ یک آدم است.

*اسکرین‌شاتِ صفحه‌ی انتخابِ مدل، فروشگاه و سفارش‌ها بعداً همین‌جا اضافه می‌شود؛ تا آن موقع راهنمای داخلِ برنامه (فارسی،
آفلاین، ۱۸۵ مقاله) کارِ هر صفحه را نشان می‌دهد.*

### امکانات

| | |
|---|---|
| 🛍 **فروشگاهِ چهار دکمه‌ای** | منوی ثابتِ مشتری: محصولات · سبد خرید · سفارش‌های من · ارتباط با پشتیبانی — با کاتالوگِ صفحه‌بندی‌شده، دسته‌ها، کارتِ محصول با عکس و ➖/➕، ثبتِ سفارشِ مرحله‌ای و پیگیری. |
| 🎛 **دو حالت** | «مشاوره‌ای» (فقط گفتگو با متنِ شخصیتِ خودت) و «فروشگاهی» (همان فروشگاهِ دکمه‌ای). چیزِ سومی برای انتخاب نیست. |
| 🧠 **هوش مصنوعیِ محلی با یک کلیک** | برنامه رم/پردازنده/گرافیک/دیسک را می‌خواند، شش مدل را برای همین سیستم مرتب می‌کند و با یک کلیک، با نوارِ پیشرفت، توقف، ادامه و سنجشِ اثرانگشت دانلود می‌کند — یا فایلِ آماده‌ی خودت را می‌پذیرد. |
| 📝 **فرمِ سفارشِ خودت** | انتخاب کن چه چیزهایی پرسیده شود (نام، موبایل، آدرس، کدپستی، ایمیل، گزینه‌ای، دلخواه) و هرکدام اجباری باشد یا اختیاری. |
| 📥 **وارداتِ دسته‌ایِ اکسل** | برنامه یک قالبِ `.xlsx` واقعی می‌سازد (نام، قیمت، موجودی، دسته، توضیحات، بهای تمام‌شده)؛ در اکسل پرش کن و همان فایل را وارد کن. سطرِ خراب با شماره‌ی سطر گزارش می‌شه و سطرهایِ سالم در یک تراکنش ذخیره می‌شن. CSV هم می‌شه. |
| 🔘 **راهنما و سؤالات متداول زیرِ پشتیبانی** | راهنما و پرسش‌هایِ پرتکرار مشتری زیرِ دکمه‌ی «ارتباط با پشتیبانی» می‌مانند، کنارِ دکمه‌هایِ سفارشیِ خودت (لینک، پاسخ متنی، کارتِ تماس). |
| 🙋 **پشتیبانیِ انسانی** | مشتری «حرف زدن با پشتیبان» را می‌زند و از آن لحظه پیام‌هایش به تو می‌رسد؛ با Reply در تلگرام جواب می‌دهی؛ ساعتِ کاری و بسته‌شدنِ خودکار هم دارد. |
| 🌐 **فارسی و انگلیسی** | هر ۲۱۳ پیامِ ربات قابلِ ویرایش و دوزبانه است؛ زبانِ پاسخ می‌تواند از پیامِ مشتری انتخاب شود و همه‌ی تاریخ‌ها جلالی است. |
| ⏳ **رزروِ موجودی** | سفارشِ منتظرِ پرداخت تعدادش را (پیش‌فرض ۱۵ دقیقه) نگه می‌دارد؛ دو مشتری هیچ‌وقت آخرین کالا را هم‌زمان رزرو نمی‌کنند. |
| 📦 **وضعیتِ ارسالِ کالا** | سفارشِ تأییدشده مسیرِ جدایی دارد: آماده‌سازی ← ارسال شد ← تحویل داده شد، با کد رهگیریِ اختیاری و هیچ ارتباطی با پول. مشتری همین را در «سفارش‌های من» می‌بیند و اگر روشنش کنی، پیامِ کوتاهِ «ارسال شد» همراه کد برایش می‌رود. |
| 💳 **دو روشِ پرداخت — هر دو به حسابِ خودت** | کارت‌به‌کارت (تأییدِ دستی) و **بله‌پی** (درگاهِ پرداخت)؛ هیچ پولی از برنامه عبور نمی‌کند و سهمی هم نمی‌گیرد. |
| 🚚 **روش‌هایِ ارسال** | فهرستِ خودت از پست/پیک با هزینه و آستانهٔ اختیاریِ «ارسالِ رایگان بالای …». مبلغِ نهایی = جمعِ اقلام − تخفیف + کرایه و فاکتور، دفترِ مالی و داشبورد همه همین را می‌گویند. تا روشی نسازی هیچ‌چیز عوض نمی‌شود: نه پرسشی، نه هزینه‌ای. |
| 🔔 **آلارمِ رسید** | وقتی مشتری «پرداخت کردم» را می‌زند و رسید می‌فرستد، برنامه آن را ثبت می‌کند، مبلغ را با سفارش می‌سنجد و **فوری** تو و مدیرها را باخبر می‌کند — ولی هرگز چیزی را به‌جای تو تأیید نمی‌کند. کنارِ هر سفارش، یک کارتِ فقط‌خواندنی هم هست: روش، مبلغ، مبلغِ رسید، کد پیگیری، مقدارِ اختلاف (با قرمز) و اینکه چه کسی و چه وقت تأیید کرده. |
| 🧾 **دفتر و فاکتورِ PDFِ فارسی** | دفتری که با تأییدِ سفارش خودش پر می‌شود، هزینه‌های دستی، داشبوردِ سود، یادآوریِ پولِ پس‌دادنی و فاکتورِ فارسیِ A4/A5 با لوگوی خودت و مالیاتِ اختیاری. |
| 🔎 **جست‌وجوی سراسری** | یک کادر برای سفارش‌ها، کالاها و مشتریان — با شمارهٔ سفارش، نامِ کالا، نام یا شمارهٔ مشتری — و کنارِ هر نتیجه دکمه‌ای که همان صفحه را باز می‌کند. فقط از دیتابیسِ همین کامپیوتر می‌خواند و هیچ‌چیز را عوض نمی‌کند. |
| 📣 **پیامِ همگانی** | یک پیام برای همه یا بخشی از مشتری‌ها (خریدار، جدید، غیرفعال، برچسب، زبان) با شمارشِ زنده‌ی گیرنده‌ها، پیش‌نمایش، ارسالِ آزمایشی به خودت، سقفِ روزانه و سرعتِ امن. پانویسِ «برای توقف /stop» پیش‌فرض روشن است. |
| ✉️ **پیامِ شخصی** | از صفحه‌ی «گفتگوها» به یک مشتری پیام بده (با پاسخ‌های آماده). مشتری «💬 فروشگاه: …» می‌بیند، در تاریخچه می‌ماند و مدل هم از آن خبر دار می‌شود. |
| 📢 **عضویتِ اجباریِ کانال** | مشتری اول باید در کانال(های) تلگرامی تو عضو باشد (منو، گفتگو، یا هر دو). خودت و مدیرها معافید؛ اگر بررسی خراب شود کسی قفل نمی‌شود و خبردار می‌شوی. |
| 🔌 **استخرِ پروکسی** | چند پروکسی (هر خط یکی) با جابه‌جاییِ خودکار، **لینکِ اشتراکِ** خودت و بازگشتِ خودکار به سریع‌ترین‌شان — تلگرام در ایران بدونِ آن کار نمی‌کند. |
| 🛡 **گاردریل‌های حذف‌نشدنی** | برنامه به هر پرامپت پنج قطعه‌ی ثابت اضافه می‌کند (حدودِ کار، منو، لحن، حریم، مرزها) و پیش‌نمایشِ همان چیزی را که مدل می‌خواند به تو نشان می‌دهد. |
| 📊 **خروجیِ اکسل و PDF** | هر فهرستی که می‌بینی (مشتریان، سفارش‌ها، کارنامه‌ی مالی، محصولات، گفتگوها) با دو دکمه به فایلِ اکسل یا PDFِ راست‌به‌چپ درپوشه‌ی `reports` درمی‌آید. |
| 📚 **راهنمای داخلِ برنامه** | راهنمای آفلاین و قابلِ جستجو به فارسی (۱۸۵ مقاله؛ ۲۵ عیب‌یابی و ۵۸ پرسشِ متداول)، دکمه‌ی **؟** کنارِ هر صفحه و یک عیب‌یابِ خودکار. |

### دانلود

از بخشِ **Releases** همین مخزن فایلِ مناسب را بگیر:

| فایل | برای چی؟ |
|---|---|
| `SmartBusinessLocal-<نسخه>-windows-setup.exe` | نصب‌کننده‌ی ویندوز (برای کاربرِ فعلی، بدونِ ادمین) |
| `SmartBusinessLocal-<نسخه>-windows.exe` | ویندوز، تک‌فایل — دابل‌کلیک و اجرا |
| `SmartBusinessLocal-<نسخه>-linux.tar.gz` | لینوکس (tar چون بیتِ اجرایی و پیوندِ نمادین را نگه می‌دارد) |
| `SHA256SUMS.txt` | چک‌سام برای اطمینان از سالم‌بودنِ دانلود |

> فایل‌ها **هنوز امضایِ تجاری ندارند**: ویندوز ممکن است بگوید «ناشرِ ناشناس» (*More info ← Run anyway*).
> **باینریِ macOS وجود ندارد** — روی مک از سورس اجراش کن (`scripts/run-from-source.sh`). اگر شک داری چک‌سام را بسنج.
> نسخه‌ی «قابل‌حمل/فلش» ندارد — داده همیشه در پوشه‌ی کاربرِ همان سیستم می‌ماند. فرایندِ انتشار:
> [`docs/RELEASING.md`](docs/RELEASING.md).

### شروع سریع

۱. در تلگرام با `@BotFather` ربات بساز (دستور `/newbot`)، توکن را در صفحه‌ی **ربات‌ها** بچسبانی ← *تست اتصال* ←
   روشن‌کردنِ ربات. اگر تلگرامِ کشورت پروکسی می‌خواهد، یکی یا چندتا (هر خط یکی) بنویس.
۲. در صفحه‌ی **هوش مصنوعی** همان مدلی را که برنامه برچسبِ «پیشنهادِ ما» زده با «دانلود و استفاده» بگیر. نخواهی هم اشکالی
   ندارد؛ بدونِ مدل هم دکمه‌ها و سفارش کار می‌کنند.
۳. در صفحه‌ی **سیستم پرامپت** شخصیتِ ربات را بنویس (۱۱ قالبِ آماده دارد) و پیش‌نمایشِ متنِ نهایی را ببین.
۴. محصول اضافه کن و بعد در «سفارش‌ها ← تنظیماتِ پرداخت» حداقلِ شماره کارتت را برای کارت‌به‌کارت وارد کن.
۵. «تجربه‌ی ربات ← پیش‌نمایشِ مشتری» را باز کن، یک خرید را تا آخر امتحان کن، بعد با حسابِ دومِ خودت با رباتِ واقعی
   حرف بزن و سفارشِ آزمایشی را تأیید کن.

راهنمای صاحبِ فروشگاه (فارسی، قدم‌به‌قدم): [`docs/SHOP_SETUP.fa.md`](docs/SHOP_SETUP.fa.md).

### توسعه‌دهنده‌ها

```bash
git clone <repo-url> && cd smart-business-local
python -m venv .venv && source .venv/bin/activate     # ویندوز: .venv\Scripts\activate
pip install -r requirements-dev.txt
python run.py            # پنجره‌ی دسکتاپ
python run.py --web      # در مرورگر
python -m pytest         # کلِ تست‌ها — بدونِ اینترنت و بدونِ رباتِ واقعی
```

یک‌کلیکی؟ `scripts/run-from-source.bat` (ویندوز) یا `scripts/run-from-source.sh` (مک / لینوکس) محیطِ مجازی می‌سازند،
وابستگی‌ها را نصب می‌کنند و برنامه را بالا می‌آورند. معماری و ناوردایی‌ها:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

### هوش مصنوعیِ محلی چطور کار می‌کنه؟

- **فقط محلی.** خبری از کلیدِ API، فهرستِ سرویس‌ها، جابه‌جاییِ خودکار و بودجه‌ی هزینه نیست؛ آن صفحه‌ها هیچ‌وقت
  منتشر نشدند. هوش مصنوعی یک فایلِ مدل است که کامپیوترِ خودت اجرااش می‌کند.
- **شش مدل با برچسبِ صادق.** هر کارت حجمِ دقیقِ فایل، کیفیتِ پاسخ و سرعت (هر کدام پنج ستاره، نسبت به بقیه‌ی همین
  فهرست)، مجوز (Apache-2.0) و وضعیتِ جا شدن روی سیستمِ تو را نشان می‌دهد: «پیشنهادِ ما» · «مناسب» · «در مرز» ·
  «جا نمی‌شود». سایزها از حدودِ ۱٫۲ تا حدودِ ۵٫۷ گیگابایت است.
- **اول سخت‌افزار.** برنامه مقدارِ رم، تعدادِ هسته، نامِ پردازنده و گرافیک و فضایِ آزادِ دیسک را می‌خواند و نیازِ هر
  مدل را حساب می‌کند؛ برایِ احتیاط فقط ۸۵٪ِ رم را قابل‌استفاده می‌داند، پس مدلی را که وسطِ کار سیستم را قفل می‌کند
  هرگز «راحت» اعلام نمی‌کند.
- **دانلود، ادامه، راستی‌آزمایی.** با یک کلیک دانلود در پس‌زمینه شروع می‌شود، با درصد و سرعت و زمانِ باقی‌مانده؛ «توقف»
  آنچه آمده را نگه می‌دارد و «ادامه» از همان بایت ادامه می‌دهد — قطعیِ اینترنت یا بستنِ برنامه یعنی ادامه، نه از اول. دو
  منبع به‌ترتیب امتحان می‌شوند (سایتِ اصلی و یک آینه) چون دسترسی به آن برای خیلی از کاربرهای ایرانی سخت است. فایلِ
  تمام‌شده با اثرانگشتِ SHA-256ِ ثبت‌شده سنجیده می‌شود و فایلِ خراب یا دستکاری‌شده هرگز بارگذاری نمی‌شود.
- **فایلِ خودت.** اگر هیچ منبعی باز نشد، فایل را از دوستت یا دانلودِ دستی بگیر و با «وارد کردن فایلِ مدل» به برنامه
  نشان بده؛ برنامه اول می‌سنجد که واقعاً یک فایلِ GGUF باشد.
- **پیش‌فرض روی پردازنده.** بیلدِ رسمی محاسبه را روی CPU انجام می‌دهد، پس کارتِ گرافیکیِ NVIDIA بدونِ نصبِ نسخه‌ی CUDA
  سرعت را زیاد نمی‌کند و برنامه این را صادقانه می‌نویسد: به‌جای حدس‌زدن از نامِ کارت، از خودِ موتور می‌پرسه و راهنمایِ
  داخلِ برنامه هم قدم‌به‌قدم فعال‌کردن CUDA را توضیح می‌دهد.
- **پنلِ پیشرفته.** پوشه‌ی مدل، توکن‌هایِ زمینه، تعدادِ رشته‌ها، لایه‌های GPU، سقفِ پاسخ به هر مشتری در روز، سقفِ کلِ
  پاسخ‌ها و کلیدِ خاموشیِ اضطراری. سقف‌ها فقط مدل را محدود می‌کنند؛ دکمه‌ها، سبد، سفارش و پرداخت هرگز خاموش نمی‌شوند.
- **هزینه‌اش پول نیست، زمان است.** چون مدل محلی است قبضی ندارد؛ صفحه‌ی «مصرف» توکن، میلی‌ثانیه‌ی هر پاسخ و زمانِ هر
  هزار توکن را روی همان سیستم نشان می‌دهد.
- **چیزی برای ارسال نیست.** متنِ مشتری برای جواب‌دادن از دستگاه بیرون نمی‌رود. تنها رفت‌وآمدِ بیرونی تلگرام (خودِ چت)،
  GitHub (بررسیِ نسخه و دانلودِ مدل) و بله (فقط پرداخت، اگر روشنش کنی) است.

### پرداخت چطور کار می‌کنه؟

- **کارت‌به‌کارت (همیشه دستی).** مشتری شماره کارت و مبلغِ دقیق را می‌بیند، «پرداخت کردم» را می‌زند و رسید را می‌فرستد
  (متنِ رسید یا عکسِ آن). برنامه رسید را ثبت می‌کند، مبلغ/کدِ رهگیری/۴ رقمِ آخرِ کارت را درمی‌آورد، مبلغ را با سفارش
  مقایسه می‌کند و **فوری** تو را (و مدیرهایِ دارایِ دسترسیِ تصمیمِ سفارش) باخبر می‌کند؛ یک ردیف هم در «نیاز به توجه»
  می‌نشیند. **تأیید کردن کارِ خودت است** — در صفحه‌ی سفارش‌ها یا با `/confirm 12`؛ برنامه به حسابِ بانکیِ تو دسترسی
  ندارد.
- **بله‌پی (درگاه، اختیاری).** در بله یک رباتِ پرداخت می‌سازی و توکنِ آن را به‌همراه `provider_token` در برنامه می‌زنی.
  مشتریِ تلگرامی دکمه‌ی «پرداخت در بله» را می‌زند و با `createInvoiceLink` مستقیم واردِ پرداختِ بله می‌شود؛ اگر لینک
  ساخته نشود همان صورتحساب با لینکِ رباتِ پرداخت می‌رسد و مشتری می‌تواند دستورِ `/pay` را خودش بنویسد. پرداخت **فقط بعد
  از تأییدِ خودِ درگاه** و سنجشِ مبلغ، ارز، کدِ سفارش و استعلامِ تراکنش خودکار تأیید می‌شود؛ پرداختِ دیررس، مبلغِ
  نخوانده و تراکنشِ تکراری هرگز خودکار تأیید نمی‌شوند.
- **چتِ بله اختیاری و مستقل است.** بله می‌تواند رباتِ گفتگو را هم داشته باشد (همان هوش مصنوعی، همان فروشگاه، توکن و
  سوییچِ هوش مصنوعیِ جدا) روی `tapi.bale.ai`. «حرف زدنی با بله» و «پرداخت با بله‌پی» دو تنظیمِ جدا هستند: تلگرام تنها،
  بله تنها، هر دو، یا هیچ‌کدام — و بله‌پی به‌تنهایی بدونِ هیچ رباتِ گفتگویی کار می‌کند.
- **زرین‌پال نیست.** دو روشِ پرداخت کارت‌به‌کارت و بله‌پی‌اند؛ کلیدهایِ تنظیماتِ قدیمیِ حذف‌شده بی‌صدا رد می‌شوند و چیزِ
  دیگری دست نمی‌خورد.

### امنیت و حریمِ خصوصی

داده روی سیستمِ خودت می‌ماند. توکنِ تلگرام، آدرسِ پروکسی‌ها، توکنِ رباتِ پرداختِ بله و توکنِ درگاه روی دیسک رمزنگاری
می‌شوند و در لاگ چاپ نمی‌شوند؛ شماره کارتِ خودت عمداً رمزنگاری نمی‌شود چون مشتری همان‌طور آن را می‌بیند. هوش مصنوعی
*پیشنهاد می‌دهد* و **برنامه اعتبارسنجی می‌کند**: مدل نمی‌تواند قیمت یا موجودی بسازد، پرداختی تأیید کند یا داده‌ی یک
مشتری را به دیگری بدهد؛ نام و پیامِ مشتری در هر پرامپت «اعتمادناپذیر» علامت می‌خورد و گاردریل‌هایِ ثابت و
حذف‌نشدنی به آن اضافه می‌شود. عکسِ رسید فقط با فهرستِ پسوندهایِ مجاز، سقفِ حجم و نامی که خودِ برنامه می‌سازد دانلود
می‌شود (نامِ داده‌شده از سرور هرگز پذیرفته نمی‌شود). مشتری با `/forget` گفتگو و مشخصاتِ شخصیش را پاک می‌کند و `/stop`
همیشه کار می‌کند. کلیدِ رمزنگاری کنارِ داده است تا یک پشتیبان خودکفا باشد — قبل از سپردنِ پولِ واقعی
[مدلِ تهدید](SECURITY.md) را بخوان و همیشه اول با مبلغِ کم تست کن.

### محدودیت‌ها، صادقانه

- فایل‌هایِ آماده‌ی **ویندوز و لینوکس** در **CI گیت‌هاب** ساخته می‌شوند؛ ماشینِ توسعه‌دهنده ویندوز نیست، پس هیچ بیلدی
  روی سخت‌افزارِ واقعیِ ویندوز توسطِ ما آزمایشِ دستی نشده. برای مک باینری ساخته نمی‌شود (از سورس اجرا می‌شود).
- **رفتارِ تلگرام و درگاهِ واقعی باید توسطِ کاربر راستی‌آزمایی شود.** تست‌های خودکار روی سرورهایِ جعلی‌اند؛ پس هر نصب
  قبل از پولِ واقعی باید یک خریدِ کامل را با مبلغِ کم تا آخر برود.
- فایل‌ها **امضایِ پولیِ ناشر ندارند**، پس بارِ اول ویندوز هشدار می‌دهد.
- نصبِ خودکارِ به‌روزرسانی فقط از نسخه‌ای انجام می‌شود که امضایِ معتبر داشته باشد؛ اگر نداشت، برنامه فقط صفحه‌ی دانلود
  را باز می‌کند.
- بخشِ مالی یک **ابزارِ کمکی است نه حسابداریِ رسمی**: اظهارنامه نمی‌سازد و به سامانه‌ی مالیاتی وصل نیست؛ با حسابدارت
  کار کن.
- کیفیتِ پاسخ به مدلِ کوچکِ محلی محدود است: روی سیستمِ ضعیف کند جواب می‌دهد و ممکن است اشتباه کند؛ هیچ‌وقت به مدلی که
  قیمت‌ها فقط در متنِ پرامپتش نوشته شده اعتماد نکن.
- هر نصب فقط **یک فروشگاه** دارد و فقط تلگرام (واتساپ/اینستاگرام/ایتا ندارد).

### مستندات

[`docs/SHOP_SETUP.fa.md`](docs/SHOP_SETUP.fa.md) (راهنمای مالک) ·
[`docs/PUBLISHING.md`](docs/PUBLISHING.md) (آپلود روی GitHub، انتشار، معرفی) ·
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (طراحی و ناوردایی‌های پول/موجودی) ·
[`docs/RELEASING.md`](docs/RELEASING.md) (خطِ ساخت، امضا، عیب‌یابی) ·
[`docs/ROADMAP.md`](docs/ROADMAP.md) ·
[`docs/BOT_FEATURES.fa.txt`](docs/BOT_FEATURES.fa.txt) (توضیحاتِ عملکردیِ خام برای تولیدِ محتوا با AI) ·
[`CONTRIBUTING.md`](CONTRIBUTING.md) · [`SECURITY.md`](SECURITY.md)

### به‌روزرسانی، اعتبارِ سازنده و حمایت

- **به‌روزرسانی.** هنگامِ شروع و هر ۲۴ ساعت، برنامه یک درخواستِ ساده به صفحه‌ی عمومیِ «آخرین نسخه» می‌زند و اگر نسخه‌ی
  تازه‌تری باشد یک نوارِ باریک نشان می‌دهد. سرورِ ما، ردیابی و آمارگیری وجود ندارد؛ اگر گیت‌هاب در دسترس نباشه بی‌صدا
  رد می‌شود؛ از «درباره» خاموشش کن.
- **نصبِ یک‌کلیکی.** «نصبِ به‌روزرسانی» نسخه‌ی تازه را دانلود می‌کند، امضا و چک‌سام را می‌سنجد، از داده‌ها پشتیبان
  می‌گیرد، با نسخه‌ی تازه بالا می‌آید و اگر بالا نیاید خودش برمی‌گردد. داده‌ی تو دست نمی‌خورد.
- **اعتبارِ سازنده.** برنامه **فقط یک خطِ کوچک** به بیوگرافیِ ربات اضافه می‌کند («ساخته‌شده با کسب‌وکار هوشمند» با
  لینکِ مخزن). چیزی به پیام‌ها، سفارش‌ها و پرداخت‌ها اضافه نمی‌شود؛ در «تجربه‌ی ربات ← پروفایلِ ربات» دیده و پیش‌نمایش
  می‌شود و متنِ خودت هرگز پاک نمی‌شود. چون متن‌باز است، با فورک‌کردنِ کد یا ویرایشِ بیو در BotFather حذف‌شدنی است —
  پیش‌فرضِ شفاف، نه الزامِ مجوز.
- **حمایت.** کاملاً اختیاری و گوشه‌ی «درباره»: مبلغ و پیام را خودت می‌نویسی و برنامه صفحه‌ی حمایت را در مرورگرت باز
  می‌کند. بدونِ حمایت هم همه‌چیز کامل است؛ برنامه هیچ داده‌ای نمی‌فرستد و از پرداخت‌هایت سهمی نمی‌گیرد.
- **مشتریان و مدیران.** دفترِ مشتریِ قابلِ جستجو (خریدها، برچسب، یادداشت، خروجیِ CSV) فقط از چیزی که خودِ تلگرام
  می‌فرستد ساخته می‌شود؛ کارمندها با QR/لینک/شناسه و با نقش (مدیر / پشتیبان / ناظر) از پنلِ دکمه‌ای (`/admin`) سفارش و
  موجودی را اداره می‌کنند، با بررسیِ مجوز در خودِ برنامه و دفترِ ممیزی.
- **تخفیف و کمپین.** کدِ درصدی یا مبلغِ ثابت و تخفیفِ خودکار، با سقف، بازه‌ی زمانی، فقطِ اولین خرید، سقفِ هر مشتری،
  محدودیتِ محصول/دسته و جمع‌شدنِ چند کد؛ مصرفِ کد هم‌زمان با سفارش شمرده می‌شود و با لغو/انقضا آزاد می‌شود. کمپین یک
  پیامِ همگانی همراهِ کد است، فوری یا زمان‌بندی‌شده.
- **پشتیبان، مهاجرت و ضدِ کرش.** مهاجرتِ نسخه‌دارِ دیتابیس با پشتیبانِ خودکار، نوشتنِ اتمیکِ تنظیمات، جداکردنِ فایلِ
  تنظیماتِ خراب به‌جای پاک‌کردنش، و تأییدِ سفارشی که اگر برنامه وسطش بسته شود خودش کامل می‌شود و موجودی دوبار کم
  نمی‌شود.
- **ابزارهای حریم.** دوره‌ی نگه‌داریِ داده، `/forget`، لاگِ پاک‌سازی‌شده، فایلِ تشخیصیِ بدونِ گفتگو/توکن/سفارش و
  بازنشانیِ کارخانه که اول از تو کلمه می‌خواهد.

### اجرا روی سرور (headless / Docker)

```bash
python run.py --headless --data-dir /srv/smartbiz     # فقط ربات‌ها، بدونِ پنجره؛ با Ctrl+C یا سیگنال تمیز می‌ایستد
python run.py --healthcheck --data-dir /srv/smartbiz  # کدِ خروج ۰ = سالم (نبضِ تازه است)
docker compose up -d                                   # پوشه‌ی ./data را به‌عنوانِ داده استفاده می‌کند
```

توکن‌ها را یک‌بار در برنامه‌ی دسکتاپ تنظیم کن، بعد `settings.json`، `secret.key` و فایل‌های `*.db` را در پوشه‌ی داده
کپی کن (کلید باید همراهِ تنظیمات برود). در حالتِ headless و Docker موتورِ اجرایِ مدل نصب نیست: دکمه‌ها، سبد، سفارش،
پرداخت و فاکتور کار می‌کنند و جوابِ نوشتاری خاموش می‌ماند. کدهای خروج: `0` توقفِ عادی، `1` مدیرِ ربات‌ها از کار افتاده
(بگذار Docker دوباره بالا بیاوردش)، `2` رباتی تنظیم نشده، `3` داده با نسخه‌ی تازه‌تری ساخته شده.

### وضعیتِ پروژه

این **نخستین انتشارِ عمومی است (۱.۰.۰)**: هوش مصنوعی فقط محلی، تلگرام پیام‌رسانِ اصلی (چتِ بله اختیاری و مستقل)، بله‌پی تنها درگاهِ علاوه بر
کارت‌به‌کارت، منویِ مشتری با دقیقاً چهار دکمه و یک استودیویِ مرکزیِ پرامپت. عددِ نسخه در فایلِ `app/version.py` زندگی
می‌کند و تگِ انتشار باید همان باشد؛ چه چیزی آمد و چه چیزی حذف شد را در [CHANGELOG](CHANGELOG.md) بخوان.
مجموعه‌تستِ خودکار (۲۲۰۸ تست در ۱۰۷ فایل) روی سرورهایِ جعلیِ تلگرام و درگاهِ بله اجرا می‌شود و فروشگاه، پرداخت، رسید،
وضعیتِ ارسال، پشتیبانی، مهاجرت، پشتیبان، پروکسی، حالتِ بی‌پنجره، خروجیِ گزارش، تزریقِ پرامپت و حالت‌هایِ سوءاستفاده را پوشش می‌دهد.
**راستی‌آزمایی با رباتِ واقعی و درگاهِ واقعی هنوز باید برای هر نصب انجام شود** — قبل از پولِ واقعی، یک خریدِ کامل را با
مبلغِ کم از اول تا آخر انجام بده. باگ و ایده: بخشِ Issues.

---

## License · مجوز

MIT — see [LICENSE](LICENSE).
