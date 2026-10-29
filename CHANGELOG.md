# Changelog

All notable changes. Format based on [Keep a Changelog](https://keepachangelog.com/); versions follow `app/version.py`.

## [1.1.0] — final

Everything from 1.0.0 to here is in the alpha entries below (phases 1–7); this release adds the hardening pass and the full manual
test guide `docs/TESTING_V1_1.md`. Unsigned: `UPDATE_PUBLIC_KEY_B64` is empty, so one-click updates stay off until you add your key
(see `docs/PUBLISHING.md`). Verified by automated tests only (1808, green); a frozen Linux build was smoke-tested (Persian PDF renders,
guide loads) — **the Windows exe, real Telegram/Bale and real payment gateways are not verified yet**; follow the test guide first.

## [1.1.0-alpha.7] — Phase 7 of 1.1.0 (work in progress, not a public release)

The in-app guide, a troubleshooter, and a low-stock alert. Phase 8 (release hardening) follows.

### Added
- **Built-in guide (N10).** A *Guide* page in the sidebar: 139 Persian articles in 15 categories (start, bot and token, AI and cost,
  products, order form, payments, orders, support and admins, marketing, channel gate, finance, safety and backup, running, troubleshooting,
  FAQ) including 19 troubleshooting articles and 46 FAQ entries in 9 groups. Fully offline; search normalises Persian/Arabic letters,
  digits and half-spaces; articles link to each other. A **?** button on every page opens the article for that page. A **quick-start
  checklist** at the top of the home page ticks itself from the real state (bot token, AI, first product, payment method, bots running)
  with *Go* and *Guide* buttons, and can be hidden. Content lives in `assets/guide/fa/` (so it ships inside the packaged app); a test
  checks every link, every ? target, the minimum counts and that key claims (VAT default, limits) match the product.
- **Troubleshooter — “the bot isn't answering?”.** Runs on demand and checks: are the bots on, system clock skew (against the messenger's
  own server time), Telegram/Bale token validity, which of your proxies work, a conflicting Telegram **webhook**, AI configured, free
  disk space. Each finding gets a plain-language fix and a link to the article. No token ever appears in its output.
- **Low-stock alert (A7).** A threshold field on the Products page (default 3, 0 = off); when a confirmed order brings a physical product to
  the threshold you get one *needs attention* item (not repeated), closed automatically after you restock.

### Not built in this phase (see [ROADMAP](docs/ROADMAP.md))
Shipping methods and tracking (A1), global search (A2), run-in-background/tray (A4), richer dashboard (A5), store-rules template (A6),
refund workflow beyond the credit note (A8) and the English guide.

## [1.1.0-alpha.6] — Phase 6 of 1.1.0 (work in progress, not a public release)

Finance and invoices. Phases 7–8 follow. **A helper for running the shop — not accounting software, not a tax filing, and not
connected to the Iranian tax authority's system.**

### Added
- **Finance ledger (N19).** *Finance & invoice* page (store mode): dashboard for today / 7 days / this Jalali month / last month / all
  time — net sales, gross before discounts, discounts, refunds, cost of goods, gross and net profit, expenses by category, income by
  method, daily chart, top products and customers, awaiting-confirmation and awaiting-payment money, inventory value at cost.
  Every figure is computed from the real orders and the ledger. The ledger is **append-only** (SQLite triggers refuse edits and
  deletes); a correction is a *reversal* row. Confirming an order posts its sale, gateway fee (a percentage you set) and cost of goods
  automatically — outside the stock saga, idempotently, with a repair pass on start-up and in the maintenance loop. Manual income and
  expenses with categories, Jalali dates and a formula-safe CSV export. Optional per-product *cost*; orders whose cost is missing are
  counted and warned about instead of silently showing an inflated profit.
- **Invoices.** A sale invoice per confirmed order and a credit note (full return; optionally returns the cost of goods too).
  Immutable snapshots (seller, buyer, lines, totals; edits refused by a trigger), atomic gap-free numbering with a prefix, a start number
  and an optional Jalali-year series, optional VAT shown as *included in the price* (default 10 %, editable), uniform half-up rounding
  with lines − discount + shipping = total. A Persian right-to-left **PDF** (fpdf2 + HarfBuzz, Vazirmatn font, A4/A5, your logo and
  colour, Persian or Latin digits) that is deterministic, so it can always be rebuilt from the snapshot.
- **Sending.** Automatic (off by default) or manual, to the customer as a file on Telegram and Bale, optional copy to the owner; retries
  with backoff, one text copy as a fallback, an *attention* item and a *Resend* button when it fails; never to blocked or unreachable
  customers, never twice. Customers get a **🧾 Invoice** button under their confirmed orders (only their own).
- **Bot admins.** *Finance summary* (owner only unless the owner grants it to managers) and *Resend invoice* (owner/manager), both
  permission-checked on the server. `/forget` anonymises invoice buyer details and deletes the cached PDFs (amounts stay).
- Jalali calendar (pure Python, verified day by day against a reference over 1300–1500).

### Changed
- DB versions: orders 5 (ledger, categories, invoices, counters), products 3 (`cost_irr`). New dependencies: `fpdf2`, `uharfbuzz`
  (wheels for Windows/Linux/macOS); tests also use `pypdf`.
- Not built yet (see [ROADMAP](docs/ROADMAP.md)): pro-forma invoices, partial credit notes, VAT shown *on top of* prices, Excel export.

## [1.1.0-alpha.5] — Phase 5 of 1.1.0 (work in progress, not a public release)

Backup AIs, usage and cost, and token savers. Phases 6–8 follow.

### Added
- **Several APIs and models with automatic failover (N16).** *AI providers* page: save OpenAI-compatible providers (name, address,
  encrypted key, models with optional context size and your own prices), reorder the chain, a *Test* button per model (latency, tokens,
  tool support), live status (healthy / slow / down / disabled + a plain reason) and the last 20 switches. Every reply starts from the
  top of the chain, so the primary is used again as soon as it recovers. Each failure is handled on its own terms: timeouts/5xx/429 get
  one short retry (respecting `Retry-After`), an invalid key sidelines that provider, spent credit sidelines it for an hour, a removed
  model is disabled **for good** (only that model), a too-long context is trimmed and retried, a model without tool support switches to
  the text protocol, and a content-filter answer gets a safe generic reply without switching. A circuit breaker (3 failures → 30 s →
  2 min → … → 1 h, then one probe), a per-provider concurrency cap and one-time owner alerts (down, key, credit, model removed, all down,
  back again). Conversation memory lives in the app, so a switch loses nothing; the history is re-fitted to the new model's window.
  Old single-API settings migrate silently into provider 1. Keys never reach logs; addresses must be `https://` (localhost/LAN allowed).
- **Usage and cost (N1).** *Usage & cost* page: replies and tokens for today / 7 / 30 days / all time (real `usage` from the API,
  clearly labelled *estimated* otherwise), averages per reply, a 30-day chart, the heaviest chats, a cost calculator (per reply, per 100,
  this month, month-end forecast), *what if* estimates prefilled from your real traffic, USD/Toman/Rial display from a rate you enter,
  and a monthly budget that warns, stops the AI or switches to the local model. Models without a price are listed, never guessed.
- **Token savers (N18).** Smart history window by tokens (system prompt and latest messages always stay), output caps by question
  size with one retry when an answer is cut off, a breakdown of what each reply's input is made of with plain tips, measured savings,
  and `scripts/bench_tokens.py` (offline). An **exact-match answer cache** is available but **off by default**: the key is a hash of the
  whole final request, only first-turn questions without personal data are cached, never tool/error/partial/filtered answers, memory
  only, 60-minute lifetime, cleared on any product/order/text/settings change; mutation-style tests prove a change always misses.

### Changed
- The old engine-level cache (keyed on system prompt + message only, without history) is **gone** — it could have returned another
  customer's earlier answer. Conversations DB v6 (`ai_calls`, `ai_usage_daily`); raw rows older than 90 days are rolled into daily totals.
- Layers not built yet (tracked in [ROADMAP](docs/ROADMAP.md)): catalog retrieval for very large catalogs, rolling history summary,
  FAQ-first answers.

## [1.1.0-alpha.4] — Phase 4 of 1.1.0 (work in progress, not a public release)

Discount codes and campaigns.

### Added
- **Discount codes (N8).** *Discounts & campaigns* page: percent or fixed-amount codes with ready-made templates, optional max discount,
  minimum cart, product/category scope, total and per-customer limits, first-order-only, minimum previous orders, messenger, start/end,
  **automatic** discounts (no code to type) and *stackable* codes; per-code stats (paid orders, sales, discount given) computed from the
  orders themselves. In the bots a *🎟 Discount code* button appears under the cart only when the shop has codes; the customer types the
  code, sees the new amount, and can remove it. The discount is applied inside the order-creation transaction (the order total is the
  discounted amount everywhere: card-to-card, Bale Pay, Zarinpal); a code is counted with the order and freed on cancel/expiry/rejection
  (re-counted if a late payment arrives). The amount to pay never drops below the gateway minimum (10,000 rial) and 100 % codes are not
  allowed. Wrong codes are rate-limited (5 per hour per chat). Owners and managers can switch a code on/off from the in-chat admin panel.
- **Campaigns (N8).** An announcement (broadcast engine, so every privacy rule applies) with an optional code, sent now or scheduled;
  retried for up to 24 h when another broadcast is running; stats include sales that used the code since launch.

### Changed
- Orders DB v4 (`discount_codes`, `discount_usage`, `cart_discounts`, `discount_attempts`, `campaigns`; order columns `subtotal_irr`,
  `discount_irr`, `discount_code`). `/forget` clears the cart code and wrong-code counter but keeps the (nameless) usage rows so a
  per-customer limit cannot be bypassed. Native Bale invoices send one line with the final amount when a discount applies.

## [1.1.0-alpha.3] — Phase 3 of 1.1.0 (work in progress, not a public release)

Broadcast, personal messages and required channel membership. Phases 4–5 follow.

### Added
- **Broadcast (N7).** New *Broadcast* page: text, optional photo and link button, audience filters (messenger, buyers/never bought,
  activity, tag, language) with a live recipient count, preview, *test to myself*, a two-step start. Only people who messaged you and
  are not blocked, opted out (`/stop`) or unreachable receive it — checked when queued **and** again right before each send. The queue
  survives restarts; one broadcast at a time; daily cap (default 3); a safe speed per messenger (Telegram 20/s, Bale 5/s) that waits
  out `retry_after`, slows itself after repeated limits, flags people who blocked the bot, and pauses itself (with a message and an
  inbox item) on a network outage, repeated permanent rejections or a missing photo. Footer *“send /stop to unsubscribe”* on by default.
- **`/stop` and `/start`.** `/stop` opts out of broadcasts only (answers and order tracking keep working); `/start` opts back in.
  They work even under the flood limit, and `/forget` no longer undoes `/stop` (a nameless marker stays).
- **Personal message (N6).** *Chats* page: write to the selected customer (quick replies included); they see “💬 Shop: …”; stored with
  role *owner* and shown to the AI as a shop message; never sent to blocked or opted-out customers; counts as the answer in an open
  support chat. The *Customers* page now uses the same path (it used to bypass the block/opt-out rules).
- **Required channel membership (N13).** *Bot experience → Advanced*: list Telegram/Bale channels, scope (menu, AI chat, both), *Test
  access*. Members are cached for 10 minutes; `/start` and **“I joined”** re-check at once; you and active managers are exempt. If the
  check breaks (e.g. the bot is not a channel admin) customers are **never locked out** — you get one message and an inbox item.
- README EN↔FA parity is now enforced by tests (N20).

### Changed
- Conversations DB v5 (`broadcasts`, `broadcast_log`); migrated automatically with the usual backup. Adapters gained `send_strict`
  (no fallback, original error) and `chat_member_status`; Bale errors now carry `retry_after`.

### Notes
- Not verifiable offline: Bale's `getChatMember` (whether it accepts `@username` or needs a numeric id) and its real rate limits —
  if the check errors, the gate fails open. See [docs/TESTING_V1_1.md](docs/TESTING_V1_1.md) §8–§10.

## [1.1.0-alpha.2] — Phase 2 of 1.1.0 (work in progress, not a public release)

One-click updates, a customer book (CRM) and bot admins with roles. Phases 3–5 follow.

### Added
- **One-click update install (N14b).** The update banner gets *Install update*. Only a release whose `SHA256SUMS.txt` carries a
  valid Ed25519 signature (`SHA256SUMS.txt.sig`, verified with the key compiled into the app) **and** whose file hash matches is
  ever installed — anything else falls back to the old "open the release page" behaviour; the signature is checked *before* the
  big download. Downloads are limited to GitHub hosts (every redirect hop is re-checked), size-capped and cancellable. Right
  before hand-off the app makes a `backups/before-update-*.zip` (the update aborts if that fails) and stops the bots cleanly.
  A small helper (a copy of the app, so the real exe is free) waits for the app to exit and then: **installer edition** runs the
  new setup silently (`/SILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS`; the `.iss` now has `AppMutex`); **single exe** and
  **portable (USB)** swap only the listed files atomically with `.old` backups and roll back on any failure *or* if the new
  version dies within seconds of starting. `SmartBusinessData/`, `portable.flag` and the system data folder are never touched.
  macOS/Linux (experimental): the verified zip is downloaded to *Downloads* with replacement instructions — no automatic swap.
  After the restart a one-time notice tells you whether it worked or was rolled back.
- **Customers (N12).** New *Customers* page: everyone who ever messaged the bot, with name, @username, language, first/last
  activity, message count, purchase count/total (only paid/confirmed orders, always computed from the orders), tags and a
  private note. Search (name/username/phone/ID/tag/note), filters (buyers, no purchases, new, inactive, blocked, opted-out,
  unreachable), sorting, per-customer card (latest orders and messages, AI usage, block/unblock, *message this customer*),
  and **CSV export** (UTF-8 + BOM for Excel, formula-injection safe). Only what the platform itself sends is stored; a phone
  number is stored only if the customer shared it via the share-contact button. `/forget` and the retention setting delete
  the row; existing conversations are back-filled by a migration.
- **Bot admins (N11).** New *Admins* page (store mode): invite staff with a one-time **link + QR** (10 minutes, single use, only
  a hash is stored) or by **numeric ID** (they send `/id` to the bot; access activates with their first message, within
  7 days). Roles: **manager** (orders, chats, products), **support** (chats only), **viewer** (read-only); the owner stays the
  account linked with `/owner`. Admins get `/admin`: a button panel for waiting orders (✅/❌ with a confirmation step for
  reject), low stock and quick stock edits, enable/disable a product, today's numbers and support chats — and the old text
  commands honour the same roles. **Every permission is checked on the server per action** (a forged button from a customer does
  nothing; a role without the capability gets "⛔"). Managers receive order alerts, support/managers get support forwards.
  `confirmed_by` is recorded on each confirmed order and every admin action goes to an audit log shown in the app.
- New dependency `segno` (pure-Python QR codes).

### Changed
- Orders DB v3 (`confirmed_by`), conversations DB v4 (`customers`, `admins`, `admin_invites`, `admin_audit`). Both are
  migrated automatically (with the usual pre-migration backup).

### Notes
- Automatic installation stays **off until you put your public key into `app/branding.py`** and sign each release
  (see [docs/RELEASING.md](docs/RELEASING.md)); until then the banner behaves exactly like phase 1.
- Not verifiable in the sandbox, so please test on Windows: the real PyInstaller helper hand-off, Inno silent upgrade, the
  portable swap on a USB drive, and Bale deep links (`https://ble.ir/<bot>?start=…`; the pasted `/start admin_<token>` fallback is
  always shown). See [docs/TESTING_V1_1.md](docs/TESTING_V1_1.md) §5–§7.

## [1.1.0-alpha.1] — Phase 1 of 1.1.0 (work in progress, not a public release)

Simpler for shop owners and customers, a proper About page, a safe update notice, and a clean first start.
Phases 2–5 (one-click update install, usage meter, discounts, broadcasts, mandatory channels, guide/FAQ, …) follow.

### Added
- **About page** (sidebar → *About*): version, *Check for updates*, creator links (GitHub, Instagram, email with a copy
  button), *Report a problem* (opens a pre-filled GitHub issue with only the version and OS) and a small, collapsed,
  optional **support form** — you type the amount (Toman) and an optional message (≤ 100 characters); the app only builds
  a Daramet link and opens it in your browser. No preset amounts, no tokens, nothing is sent anywhere by the app.
- **Update notice (N14a).** On start and every 24 h the app asks GitHub's public *latest release* endpoint — a single
  plain GET, no server of ours, silent on failure, can be turned off in *About*. Semver-aware; drafts and
  pre-releases are ignored; a slim dismissible banner appears when a newer release exists. Downloads/installs are *not*
  automatic yet (Phase 2): the banner opens the release page.
- **Update signing infrastructure.** `scripts/make_signing_key.py` (one-time Ed25519 key, stored outside the repo) and
  `scripts/sign_release.py` (signs a release's `SHA256SUMS.txt` in ~30 s); `app/core/update_verify.py` verifies the
  signature and SHA-256 and refuses anything else. The release workflow now publishes `SHA256SUMS.txt` and marks tags
  such as `v1.1.0-alpha.1` as pre-releases. See [docs/RELEASING.md](docs/RELEASING.md).
- **Creator credit in the bot bio (N17)** — one small line, *only* in each bot's bio («ساخته‌شده با کسب‌وکار هوشمند ·
  github.com/…»), never in messages/orders/payments. Transparent: a locked line in *Bot experience → Bot profile* with a
  live preview. The seller's existing bio is never erased or truncated: it is shown first and the line is appended only
  after confirmation; a bio that would exceed 120 characters is reported, not cut. Telegram: default + per-language
  versions via `setMyShortDescription`. Bale: tried at runtime; if unsupported you get a copyable suggested text.
- **App icon (N9)** — blue→green rounded square with a shopping bag and a chat bubble. `scripts/make_icons.py` generates
  SVG, PNG 16–1024, `.ico`, `.icns` and Android adaptive layers into `assets/icons/`; wired into the sidebar, the window,
  the installer and the build workflow. You can save the icon from *Bot profile* to use as the bot's picture.
- **Start from zero (N2).** If the data folder already holds data, the first launch asks once: *Continue with previous data*
  or *Start fresh (backs up first)*. Settings shows the data folder with an *Open folder* button. The sample product is
  opt-in. The release packaging now verifies that no user data (settings, databases, keys, backups, models) can end up in a
  zip, and a repository test enforces it for the source tree.
- **Quick setup (N3)** — pick your kind of business (physical goods, digital, services, consulting, support) and the mode,
  order form and sensible numbers are set in one click without touching tokens, payments, FAQ, messages or the bio.

### Changed
- **Bot experience is now four tabs**: *Quick start · Shop · Messages · Advanced*. The mode list shows three modes
  (Shop, Consulting, Answers + support); *AI ordering* and *Collect requests* live under *Advanced*. Product-list size and
  max quantity moved to the *Shop* tab.
- **Messages editor (N3)** shows plain titles, a "when is it shown" line, variables with Persian names («{شماره‌ی سفارش}»)
  inserted with buttons, and a **live preview** with sample values; only ~14 important messages are listed until you
  switch on *Advanced*. Saved text keeps the old format, so nothing needs migrating. Field/button forms hide technical
  inputs (IDs are automatic; regex is under *Advanced options*).
- **Customer menu is four buttons (N5)**: 🛍 Products · 🧺 Cart · 📦 My orders · ℹ️ Help. *Place order* lives in the cart
  message; FAQ and your custom buttons are under *Help* (two shown, the rest under *More*). Old keyboards from 1.0.0 keep
  working. The cart is one row per item `[ − ] 2× name [ + ]` (the minus becomes *Remove* at 1) and ends with
  *Empty cart | Place order*. The order summary offers three options: confirm, edit, cancel.
- **Bale-safe buttons (N4):** plain `−`/`+` and a *Remove* word instead of ➖/➕/🗑 emoji on Bale (Telegram keeps its
  emoji); no emoji-only label is ever sent to Bale.
- **Rewritten customer wording (N3):** verb-led buttons ("Fix my cart", "Continue order"), every message says the next
  step, button labels ≤ 28 characters, no technical words.

### Fixed
- Link buttons in the customer preview now open (Flet 1.0 has no `Page.launch_url`; a small `open_url` helper is used).

### Tests
- 940 automated tests (was 705): fake GitHub server, signature/hash verification, bio sync rules on fake Telegram and Bale
  servers, About/support form, data-found flow, packaging checks, icon generation, metadata coverage of every message,
  label-length and forbidden-word checks.

## [1.0.0] — 2026-10-14

First stable release. A deterministic, button-driven shop on both Telegram and Bale; the AI answers questions but
never touches carts, orders or payments in the default mode.

### Added
- **Button shop (default for stores).** Persistent menu (🛍 Products · 🧺 Cart · ✅ Checkout · 📦 Track order),
  paginated catalog with categories, product cards (photo, price, stock, ➖/➕ quantity), cart with idempotent
  set-quantity buttons, step-by-step checkout, payment choice, order tracking and cancellation. Callback data is
  compact (≤ 64 bytes) and every stale/garbled button gets a friendly answer. Works identically on Telegram and Bale.
- **Working modes**: *Advisor* (chat only, never sends a keyboard) · *Button shop* · *AI ordering* (the 0.5.0 flow,
  now experimental) · *FAQ + human support* · *Lead capture*. Switchable at runtime without a restart, per platform.
- **Configurable checkout fields** (text / phone / number / choice / email / location, required or optional,
  physical / digital / both, regex, length limits) with templates; answers are stored on the order and shown in
  the owner's notifications, console and orders screen. Hostile input is normalised (digits, control/bidi chars).
- **Digital products** with automatic delivery after confirmation: text, link, file (≤ 50 MB) or **licence keys**
  (each purchase atomically consumes its own keys; re-delivery sends the *same* keys). Failed delivery is retried
  and reported to the owner. Unlimited-stock products never show fake numbers.
- **Custom menu buttons**: link, text reply, call (number + contact card — never a `tel:` URL), human support,
  open catalog/cart/orders, checkout, ask-the-AI, share contact; per-platform visibility; FAQ pages.
- **Human support hand-off** with a customer *End chat* button, owner replies by *Reply* or `/reply <ref> text`,
  `/close`, `/handoffs`, inactivity timeout and **working hours** (Tehran time, no tzdata needed).
- **Editable, bilingual bot texts** (Persian / English / auto): every customer-facing message has a key; the owner
  overrides any of them; placeholders are validated; a corrupt override can never break the bot.
- **Bot experience screen** in the app (modes, checkout fields, buttons, FAQ, texts, hours, limits, attention inbox)
  and an in-app **customer preview** that runs the real shop flow without Telegram or Bale.
- **Atomic, recoverable order confirmation (saga)** across `orders.db` and `products.db` with an idempotent stock
  ledger, crash recovery at start-up and in the maintenance loop; reservations never over-report availability.
- **Versioned schema migrations** (`PRAGMA user_version`) for all three databases, automatic pre-upgrade backup,
  refusal to open data written by a *newer* app, and migration of older backups on restore.
- **AI cost controls**: per-chat and total daily caps, an emergency kill switch, 80 % / 100 % owner alerts. Caps limit
  only AI answers — buttons, payments and tracking keep working.
- **Privacy**: customer `/forget`, optional retention (auto-delete old chats, anonymise closed orders), AI-disclosure
  line on `/start`, shop-only reset (keeps settings and tokens).
- **Attention inbox** for things that happened while the app was closed (failed deliveries, support requests with no
  owner linked, short stock after recovery, AI caps).
- **Proxy subscription** (your own link, one proxy per line; 256 KB / 10 s caps, encrypted cache, hot-swap into the
  running pool) and **automatic return to the best proxy** (hysteresis; no flip-flopping); recent switches shown in the app.
- **Headless mode** (`python run.py --headless`) with heartbeat file and `--healthcheck`, plus `Dockerfile`,
  `docker-compose.yml` and `requirements-headless.txt` (no UI, no flet).
- Abuse / injection regression suite (47 cases), cross-platform end-to-end tests on fake Telegram and Bale servers (705 automated tests in total).

### Changed
- The default mode for stores is now **Button shop**. Settings that pin `shop_mode = "shop_ai"` keep the old flow.
- Customer-facing payment/order texts moved into the text registry (default Persian wording unchanged).
- `PRAGMA user_version` replaces ad-hoc `ALTER TABLE` code.

### Removed
- Dead `BaleClient.create_invoice_link` code and its tests (Bale Pay uses `sendInvoice` since 0.5.0).

### Known limitations
- Telegram/Bale behaviour that cannot be verified offline (Bale reply keyboards, editing photo messages, real payment
  gateways) is covered by fake servers and graceful fallbacks; see `docs/TESTING_V1.md` for the manual checklist.
- Local-AI mode is not available in headless/Docker builds (use an OpenAI-compatible API there).

## [0.5.0] — 2026-10-11

### Added
- **Portable mode (run from a USB drive on any OS).** A `portable.flag` file or a `SmartBusinessData/` folder next to
  the app (up to 5 folders above the executable) moves *all* data — settings, databases, the encryption key — beside
  the app. Falls back to the OS folder if the drive is read-only. `SMART_BUSINESS_DATA_DIR` overrides everything.
- **Backup / restore / factory reset / diagnostics** (Settings → *Data & safety*): consistent SQLite snapshots
  (online-backup API), optional inclusion of secrets, safety copy before every restore, zip-slip/zip-bomb checks,
  a two-lock reset button (type RESET + automatic backup by default) and a diagnostics bundle without secrets,
  chats, customers or orders.
- **Telegram proxy pool with automatic failover:** many proxies (`socks5/socks4/http`, `host:port`,
  `user:pass@host:port`, `host:port:user:pass`), live validation with Persian error messages, a *Check & rank*
  button, per-proxy cool-down, and automatic switching after consecutive network errors without losing updates.
- **Multi-OS release pipeline:** `release.yml` builds Windows / macOS / Linux, creates portable zips (shared
  `SmartBusinessData` layout), a raw Windows `.exe`, an Inno Setup installer (experimental) and `SHA256SUMS.txt`.
- Bilingual README (English first, Persian below), updated docs, threat model in `SECURITY.md`.
- Atomic `settings.json` writes; a corrupt `settings.json` is quarantined (`settings.corrupt-*.json`) instead of
  being silently replaced by defaults.

### Changed
- **Bale Pay no longer relies on `createInvoiceLink`.** Bale customers receive a native `sendInvoice` inside the
  chat; Telegram customers receive a deep link to the Bale bot (`?start=pay_<order>_<code>`, plus a manual
  `/pay <order> <code>` fallback) and the invoice is sent when they press *Start*. Per-order random code,
  constant-time comparison, correct handling of expired / paid / switched-method orders.
- Bale Pay settings now ask for what Bale actually needs (16-digit card number or `WALLET-…` token); Persian digits
  and separators are normalised. *Test connection* sends a real 10,000-IRR test invoice to the owner's Bale chat.
- Release workflow metadata is ASCII-only; the build workflow was renamed `build-windows.yml` → `release.yml`.

### Fixed
- Broken Bale Pay links (see above).
- `flet pack` failed with `unrecognized arguments: --collect-all=llama_cpp` (the PyInstaller argument must use `=`).
- Reset/restore would have failed on Windows (open SQLite connections) or silently written to a deleted file on
  Linux/macOS; both are now performed in place.
- A racy test read stock between the atomic status claim and the stock deduction in `OrderStore.confirm`.

### Known limitations
- `OrderStore.confirm` claims the status first and deducts stock afterwards (two databases, no cross-file
  transaction). A crash in that microsecond window could leave a confirmed order with undeducted stock — see the
  hardening backlog in the master prompt.

## [0.4.0] — 2026-10-09

### Added
- **AI-managed ordering (store mode):** a tool-calling "smart admin" — customers order in natural language; no
  commands. Tools: product search, create/update/cancel order, payment start, card-payment claim, escalation.
- **Stock reservation** for orders awaiting payment (default 15 min, configurable 1–240), expiry notices,
  `expired` status, per-customer anti-hoarding limits.
- **Zarinpal** payments (v4; polling verification since the app has no public callback URL; sandbox mode).
- **Bale Pay links on both Telegram and Bale**, delivered as URL buttons + text; fallback to native `sendInvoice`;
  tolerant `createInvoiceLink` parsing; *Test connection* buttons and last real-chat errors in settings.
- **Owner console:** one-time-code owner registration, alerts (payment awaiting approval, auto-confirmed sale with
  delivery details, late payment, AI escalation) and `/confirm` `/reject` `/orders` `/order` `/stock` commands.
- Auto-confirmation of verified online payments (setting, default on); optional required phone/address.
- Receipt photos/files from customers reach the AI as an attachment note instead of being silently dropped.
- Payment settings card, order screen shows hold time / expiry / late-paid warning / delivery details.
- `ApiEngine`/`LocalEngine.chat_tools()` (native OpenAI tools with text-protocol fallback).
- Professional repository files: README (fa/en), docs, CI, issue/PR templates, security policy, license.

### Changed
- Removed the command-based purchase flow (`purchase_flow.py`) in favour of the agent.
- Local store mode uses an 8192-token context window.

### Fixed
- Concurrent confirmations of the same order could deduct stock twice (now an atomic claim).
- State transitions are atomic (a payment racing a cancel can no longer be overwritten).
- Zarinpal payments for cancelled orders were never recorded (money could be lost).
- Editing an order after an online payment link existed left the old link payable (now refused: cancel + recreate).
- Late payments are no longer auto-confirmed; amount-mismatched payments neither.
- Rejected paid orders now notify the customer; stale "payment window ended" notices after app downtime are suppressed.

### Security
- Customer profile names are sanitised before entering the system prompt; search query length capped.
- Zarinpal merchant ID and Bale Pay tokens are masked in logs.

## [0.3.0]
- Real Telegram & Bale connection: encrypted tokens, connection test, optional proxy, message merging, blocklist,
  conversations view with per-chat memory.

## [0.2.0]
- AI engine: OpenAI-compatible API and local GGUF models (llama-cpp), model catalogue and downloader.

## [0.1.0]
- App shell, onboarding, business-mode selection, settings, bilingual (fa/en) UI.
