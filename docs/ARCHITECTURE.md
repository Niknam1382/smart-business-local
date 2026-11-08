# Architecture

Smart Business Local is a single-process desktop app (Flet UI) that runs a Telegram bot adapter, a **local** AI engine
(llama.cpp on a GGUF file, on the same machine) and SQLite stores on the owner's machine. There is no server and no
account. Bale is **not** a messenger any more — it survives only as the **Bale Pay** payment gateway. This document
describes how the pieces fit and — most importantly — the invariants that keep money and stock safe.

## What this release is (1.0.0)

| Cut during development — **not in this code** | What the code does instead |
|---|---|
| AI provider/API mode: `ai_providers`, failover chain, API keys, USD pricing tables, monthly cost budget, token cache | `hardware.py` + `model_catalog.py` (specs, ranking, fit badges), `downloader.py` (resumable download + SHA-256), `prompt_kit.py` (persona + fixed guardrails + live preview) |
| A separate codebase per messenger | one adapter serves both messengers: `telegram_adapter.py` takes `platform` + `api_base`, so Bale chat runs on `tapi.bale.ai` with the same menus, buttons and AI path. `bale_pay.py` stays the **payment-only** Bale client (`sendInvoice`, `createInvoiceLink`, pre-checkout, successful payment, transaction inquiry) |
| Zarinpal gateway | Card-to-card with receipt capture + instant alarms (`receipts.py`, `owner_console.build_payment_claim_alert`) |
| Portable / USB data folder (`portable.flag`, `SmartBusinessData/`) | Model storage folder is configurable (still under the user profile by default); the data folder is env → OS default only |
| Modes `faq_support`, `lead_capture`, `shop_ai` | Exactly two modes (`advisor`, `shop_buttons`) and a fixed **four-button** customer menu |

## Process layout

```
Flet UI (main thread)  ──►  BotManager  ──►  asyncio loop in a worker thread
 screens/*                  (singleton)        ├─ TelegramAdapter (aiogram polling)
                                               ├─ ConversationPipeline (debounce, flood limit, per-chat lock)
                                               │     ├─ OwnerConsole      (owner commands, before anything else)
                                               │     └─ ShopFlow (buttons) + QaAgent (read-only answers) / plain chat (advisor)
                                               ├─ BalePayClient (payment updates only: pre-checkout / successful_payment / /pay)
                                               ├─ LocalEngine (llama.cpp) runs in a thread — inference never blocks the loop
                                               └─ maintenance loop (reservation expiry, pending gateway verifications,
                                                                  handoff timeout, proxy refresh, retention)
SQLite: settings.json (encrypted secrets) · conversations.db · products.db · orders.db
Data folder: `SMART_BUSINESS_DATA_DIR` override → OS default folder (`paths.py`). Model files: `models/` inside it,
             or a folder the owner picks on the AI page. No portable mode.
```

## Modules (`app/core`)

| Module | Responsibility |
|---|---|
| `ai_engine.py`, `tool_protocol.py` | `LocalEngine` only (llama-cpp-python, lazily imported; `ChatML`-style prompt, think-block stripping, `chat_tools()` returning a `ToolTurn`, `self_test()`). `engine_readiness()` is the single "is the AI ready?" gate used by the home page, the quick-start card and the troubleshooter. There is **no** `ApiEngine` any more. |
| `hardware.py` | Reads RAM / cores / CPU model / GPU name+VRAM / free disk (each probe independent, cached, never crashes the screen). |
| `model_catalog.py` | The six pinned GGUF models (size, sha256, min/good RAM, quality & speed stars, three source URLs), `fit_state()`, `ranked_for()`, `recommend()`, `reason_for()`, `auto_context_tokens()`, `auto_threads()`. RAM is deliberately discounted to 85 %. |
| `downloader.py` | Resumable GGUF download: `.part` + `.part.meta`, HTTP `Range`, cancel, per-source fallback, **SHA-256 verification** (a mismatch is deleted and refused), atomic rename, `is_downloaded()` GGUF-magic/size check, `verify_file()`, `delete_model()`. |
| `prompt_kit.py` | Central prompt system: the owner's persona + five non-removable guardrail segments (limits / menu map / tone / privacy / safety) + live catalog & FAQ context; `owner_prompt_warnings()` and `segment_summary()` for the UI. |
| `receipts.py` | Parses a card-to-card receipt (Persian/Arabic digits, amount runs, trace code, last-4, date) and compares it with the order total — advisory only, never a decision. |
| `agent_common.py` | Shared bits of the AI reply path (`AgentReply`, display-name sanitising, order throttle limits). The early "AI ordering" agent (`store_agent.py`) was **removed before this release**. |
| `orders.py` | Orders, **stock reservation**, atomic state transitions, late-payment handling, receipt rows. |
| `products.py` | Catalog and real stock. |
| `payments.py` | `PaymentService`: available methods (card-to-card needs only a card number; Bale Pay needs both tokens *and* a running bot), payment instructions, `createInvoiceLink` → deep-link fallback, pre-checkout / successful-payment guards, transaction-id idempotency, auto-confirm, diagnostics. |
| `owner_console.py` | One-time-code owner registration, `/confirm` `/reject` `/orders` …, owner alerts, `build_payment_claim_alert()` (the receipt alarm text). |
| `bot_manager.py` | Lifecycle, adapters, maintenance loop, log redaction, `_on_payment_claim` (attention item + instant message to the owner and order-deciding admins). |
| `telegram_adapter.py`, `bale_pay.py`, `adapter_common.py` | Telegram I/O (URL-button messages, media-as-note, attachment download with allow-list/size cap/app-invented file name) and the **payment-only** Bale client (`getUpdates` filtered to payment events, `sendInvoice`, `createInvoiceLink`, `answerPreCheckoutQuery`, `inquireTransaction`). `bale_pay.py` itself never answers chat — ordinary Bale chat is served by `telegram_adapter.py` with `platform="bale"`, and today only the *owner/admin panel, broadcasts, custom buttons and channel gate* are still Telegram-scoped. |
| `proxy_pool.py` | Telegram proxy list: parsing (`socks5/socks4/http`, `host:port`, `user:pass@host:port`), health probes, ranking, cool-down and **automatic failover** (the Telegram adapter swaps its `Bot` after consecutive network errors). |
| `paths.py` | Data-folder resolution: `SMART_BUSINESS_DATA_DIR` → OS default. There is no portable mode. |
| `backup.py` | Backup / restore / factory reset / diagnostics (settings + `secret.key` + the three databases; model files are not in the zip). Databases are copied with SQLite's online-backup API and **reset/restore happen in place** (stores keep per-thread connections open, so files are never deleted or swapped). |
| `crypto.py`, `redact.py`, `settings.py` | Secret storage (Fernet; the key lives beside the data so a backup is self-contained), log scrubbing, atomic settings writes, corrupt-file quarantine, `_LEGACY_IGNORED` (API / Zarinpal / Bale-bot / portable keys dropped on load) and `_LEGACY_RENAMES`. |

## Additions (phase 1)

| Module | Responsibility |
|---|---|
| `branding.py` (`app/`) | The only place with the creator's public identity (links, e-mail, Daramet username, credit line, update public key). A repository test fails if it leaks into other source files. |
| `ui_glyphs.py` | Per-platform button glyphs: plain `−`/`+`/*Remove* on Bale, emoji on Telegram; `is_emoji_only` guards Bale labels. *(The Bale messenger branch is dead code — only the Telegram path runs; kept because old Bale chats are still readable.)* |
| `shop_text_meta.py` | Metadata for all customer messages: plain title, group, "when shown", basic/advanced level, Persian variable names with examples, display↔storage conversion (`{شماره‌ی سفارش}` ⇄ `{order_id}`), live preview, button-label limits. |
| `quick_setup.py` | One-click presets by business type (mode, order form, numbers) that never touch tokens, payments, FAQ, messages or the bio. |
| `bot_profile.py` | Creator credit in the bot bio: composition (≤ 120 UTF-16 units), safe sync rules (never erase/truncate seller text; confirmation first), Telegram per-language versions. `BotManager` runs it after connect, every 24 h and on demand. |
| `updater.py`, `update_verify.py` | GitHub *latest release* check (semver, drafts/pre-releases ignored, host-allow-listed URLs, silent failure) and Ed25519 + SHA-256 verification used by the future installer. |
| `data_probe.py` | Read-only detection of previous data (counts only) for the "continue / start fresh" prompt. |
| `support_link.py` | Builds the optional Daramet link (Toman amount + ≤ 100-char message). Used only by the About screen; a test proves no bot-facing module imports it. |
| `about_info.py` | Pre-filled GitHub issue URL (version + OS only). |

New invariants: the credit line exists **only** in the bio (never in messages/orders/payments — enforced by tests); an existing
bio is never overwritten without being shown to the owner; no release artifact may contain user data (packaging check +
repository test); update installation is impossible without a valid signature and matching hash; nothing in the app sends
user data anywhere (the only network call of the new features is the update check GET).

## The AI never touches the cart

The model has **no tool that changes anything**. Orders and the cart (add / reduce / remove / checkout / pay) are
button-only (`shop_flow.py`); the only AI tool is `suggest_products`, which shows product cards with a *Details* button (no add
button). The old "AI ordering" mode (`shop_ai`, `store_agent.py`, tools `create_order`, `update_order`, `start_payment`…) was deleted;
a saved `shop_ai` falls back to `shop_buttons` in `modes.resolve_mode`.

Invariants (each has tests — `tests/test_commerce_e2e.py::test_ai_can_never_touch_the_cart_or_orders_even_if_the_model_tries`,
`tests/test_shop_e2e.py`, `tests/test_hardening.py`):

1. A model that *tries* to call `create_order` / `add_to_cart` / `start_payment` gets an "unknown tool" result: no order, no cart change.
2. Prices/stock come from the stores. Customer text and profile names are untrusted (names are sanitised before entering the prompt).
3. Card numbers and payment links are sent **verbatim by the app**, never re-typed by the model.
4. The model cannot confirm a payment; only the owner or a verified gateway can.
5. Per-customer throttles (orders per hour, expired-unpaid per day) live in `ShopFlow` checkout.

## Reservation & order state machine

```
pending_payment ─► paid ─► confirmed        stock_quantity is decreased ONLY on confirm
        │            └───► rejected         (customer is notified)
        ├─► cancelled ─┐
        └─► expired ───┴─► paid (paid_late)  money received after cancel/expiry is recorded, never lost
```

- Sellable quantity = `stock − Σ(pending_payment not expired) − Σ(paid)`.
- `create`/`replace_items` run in `BEGIN IMMEDIATE` — concurrent customers cannot over-reserve (tested with 12 threads).
- Every transition is an atomic `UPDATE … WHERE status = <current>`; `confirm` claims the order atomically
  *before* touching stock, so double-clicks / auto+manual confirms deduct stock exactly once.
- `paid_late` orders and amount-mismatched payments are **never auto-confirmed**; the owner decides.
- An order that has an online payment link cannot be edited (the old link would stay payable): cancel and recreate.

## Payments (two methods)

- **Card-to-card — manual, always.** `_card_instruction()` renders the amount + card number + holder from settings
  (never from the model or the customer). The customer taps `pay.claim` → `register_payment_claim()` marks the order
  `paid` (**not** confirmed) and fires the alarm; `attach_receipt()` stores a text or image receipt, parses it with
  `receipts.parse_receipt()` against `order.total_irr` and fires the alarm again with the match state. The app has no
  bank access, so **nothing is auto-approved** — `confirm` stays a human action in the UI or via `/confirm`.
- **Bale Pay — the only gateway.** Requires `bale_pay_bot_token` + `bale_pay_provider_token` (`bale_pay_configured()`)
  *and* a running bot, otherwise the method is not offered at all. Primary path: `createInvoiceLink` → a URL button
  that opens Bale's payment sheet from inside Telegram (no `chat_id` needed). Fallback: the payment bot's deep link
  `https://ble.ir/<bot>?start=pay_<order>_<code>`, plus the manual `/pay <order> <code>`; `handle_pay_command()` sends
  a native `sendInvoice` to that Bale chat. `bale_pay_link_mode` chooses auto or deeplink-only.
  `pre_checkout` refuses expired orders, wrong currency, changed amounts and short stock (fast, no network, no AI).
  `successful_payment` checks the per-order random `code` (`hmac.compare_digest`), the payer identity against the
  pre-checkout payer, the currency, the amount and then **inquires the transaction** at the gateway; a failed inquiry
  leaves the payment pending verification instead of silently confirming or dropping the money. Auto-confirmation is
  additionally blocked for `paid_late` orders and amount mismatches.
- **Idempotency.** Every gateway payment is stored under its transaction id
  (`provider_payment_charge_id` → `telegram_payment_charge_id`); a missing id is refused, an id already used by another
  order is refused, and a repeated event for the same order is ignored (`_processed_charges`, `_charge_order`,
  `find_paid_by_reference`).
- Only documented Bale Bot API payment methods are used, with a hand-written JSON/HTTP client (no GPL library is
  bundled). The provider token may be the test token (`WALLET-TEST-…`); the UI detects it and warns that it is not a
  real payment.
- **Removed:** the Zarinpal client and its polling; the conversational Bale bot; the portable data folder.
- The settings screen has live *Test connection* buttons that perform a real call and show the exact error.

## Owner console

`/owner <code>` (one-time, 10 min, ~50-bit code) from the owner's personal **Telegram** chat registers it.
Commands work only from the registered chat and only when the whole message is a command; anything else from
the owner goes to the AI (so the owner can test the bot). Alerts: the card-to-card receipt alarm (`💸 باید چک کنی …`
with the amount verdict and ready-made `/confirm` / `/reject` lines), payment awaiting approval, auto-confirmed
sale (with delivery details), late payment, AI escalations. Managers holding the order-decision permission get the
same alarm (`BotManager._notify_owner_and_staff`).

## Testing strategy

Tests run real aiogram / `BalePayClient` / `BotManager` against fake servers (`tests/fake_servers.py`, `tests/fakes.py`).
The language model is replaced by a scripted engine, so every tool the "model" calls really executes; the GGUF
downloader is tested against a fake HTTP server (Range/resume/cancel/hash mismatch), and hardware detection is injected.
Concurrency invariants are tested with threads. What cannot be tested offline — real Telegram and real Bale Pay
behaviour, and real model quality on real hardware — has to be checked on each installation by walking through one
real purchase with a small amount (owner guide: `docs/SHOP_SETUP.fa.md`).


## v1.0.0 additions

```
Customer ──► Telegram adapter ──► ConversationPipeline
                                              ├─ OwnerConsole (+ /reply /close /handoffs, Reply routing)
                                              ├─ /forget · usage limits (UsageLimiter) · block list · flood limit
                                              ├─ mode = resolve_mode(settings, platform)         (modes.py)
                                              │    buttons → ShopFlow ─► FlowResult[UiMessage] ─► ui.deliver(Transport)
                                              │    ai_qa   → QaAgent (read-only; tool: suggest_products)
                                                                                            ├─ HandoffService (open session ⇒ messages go to the owner, AI silent)
                                              └─ Debouncer ─► AI
BotManager maintenance loop: reservation expiry · inventory saga recovery · handoff timeout ·
                              proxy-subscription refresh · retention purge
```

| Module | Responsibility |
|---|---|
| `migrations.py` | Versioned SQLite migrations (`PRAGMA user_version`), one transaction each, pre-upgrade backup, `SchemaTooNewError`. Stores call `migrations.prepare()` on every new connection. |
| `shop_flow.py` / `ui.py` | Platform-neutral button shop. `callback_data` is `c:<verb>:<args…>` (≤ 64 bytes). Quantities are *targets* (`set_qty`) so double taps are idempotent. Per-chat `asyncio.Lock`. Adapters only implement `Transport` (`send_ui`, `edit_ui`, `delete_message`, `answer_callback`). |
| `checkout_fields.py`, `cart.py` | Configurable checkout fields + validation; `carts` / `checkout_sessions` tables in `orders.db` (survive restarts). |
| `shop_texts.py` | Registry of every customer-facing message (fa/en), owner overrides validated against allowed placeholders; rendering never raises. |
| `product_import.py` | Bulk product import: writes the `.xlsx` template and reads `.xlsx`/`.csv` with the standard library only; per-row problems are reported, valid rows land in one transaction. |
| `handoff.py`, `working_hours.py` | Human support sessions, Reply routing (`relay_map`), inactivity timeout, Tehran working hours. |
| `usage_limits.py`, `attention.py` | Daily AI caps + kill switch; "needs attention" inbox. |
| `qa_agent.py`, `modes.py` | Read-only Q&A agent; mode registry (`resolve_mode` never raises). |
| `proxy_subscription.py` | User-supplied subscription link → validated proxy list (size/time caps), encrypted cache. |
| `headless.py` | UI-less runner with heartbeat/health check (Docker). |

### New invariants

1. **Order confirmation is a saga** (`OrderStore.confirm`): (a) atomic claim `paid → confirmed`, (b) one `products.db`
   transaction: unique `stock_ledger` row + stock decrement, (c) `inventory_applied = 1`.
   A crash between steps is repaired by `recover_inventory()` (idempotent through the ledger). Reservations count
   `confirmed AND inventory_applied = 0`, so availability is never reported higher than reality.
2. **Schema changes only through `MIGRATIONS`.** Never `ALTER TABLE` elsewhere. Data newer than the app is refused;
   older backups are upgraded on restore.
3. **The AI never mutates shop state in button modes**; unknown tool calls are rejected. Customer-controlled text
   (messages, names, form answers) is normalised and never interpolated into system prompts or format strings.
4. **Delivery content (keys/links) is never written to chat history** (and therefore never reaches the model).
5. **Support relay is owner-bound**: a blocked customer's messages never reach the owner; `/forget` cannot unblock.
6. **Broadcast recipients are re-checked at send time** (blocked / opted-out / unreachable / forgotten are skipped even if they were in the
   queue snapshot). Broadcasts use the adapters' `send_strict` — no photo→text or button→plain fallbacks and no retry inside the adapter — so
   the engine sees the real error: 429 waits `retry_after`, 403 means unreachable, network errors retry then pause the whole broadcast.
7. **`/stop` is never rate-limited and `/forget` cannot undo it** (a nameless opt-out marker survives `/forget` and retention purges).
8. **The channel gate fails open.** Any error, timeout or unknown status lets the customer through (cached briefly) and alerts the owner
   once per outage; the owner and active admins are exempt; membership is checked per messenger against that messenger's own channels.
9. **Personal messages and the Customers page share one send path** (`BotManager.send_to_customer`): block/opt-out refusal, the
   “💬 Shop:” template, role `owner` in history (mapped to a shop message for the AI), support-chat bookkeeping.
10. **A discount is applied and consumed inside the order-creation transaction** (`discounts.resolve` → `consume`), so the order total is
    the discounted amount everywhere and a code can never be over-used (`UPDATE … WHERE used_count < total_limit`). Cancel / expiry /
    rejection free the use; a late payment re-counts it. The amount to pay never drops below the gateway minimum (`MIN_FINAL_IRR`) and
    wrong codes are rate-limited per chat. Campaigns reuse the broadcast engine, so all privacy rules (invariants 6–7) still apply.
11. **The AI layer is local-only.** `build_engine_from_settings()` produces a `LocalEngine` for the selected (or imported)
     GGUF file, sized by `ai_context_tokens` / `ai_threads` / `ai_gpu_layers` (0 = automatic from the measured hardware, GPU
     layers default to 0 = CPU). There is no provider chain, no failover and no API key anywhere in the app; inference runs
     in a worker thread so the event loop, the buttons and the payment handlers never wait on the model. Chat memory lives in
     the app's database, so switching models loses nothing.
12. **Usage numbers come from the engine, and are labelled *estimated* when the engine does not report them.** No money is
     computed at all (a local model costs CPU seconds, not currency): `ai_usage` records tokens and latency per call and the
     *Usage* page derives averages, per-1000-token time and today's CPU minutes from `ai_calls` rows, never from separate
     counters. Daily caps and the kill switch throttle replies only — `usage_limits` cannot block buttons, cart, orders or
     payments, and a throttled customer still gets a plain Persian explanation.
13. **The answer cache cannot serve a stale or another customer's answer.** The *API-era* cache was removed because it was
     keyed on part of a request. The local cache that came back with the offline model (`app/core/answer_cache.py`) keys on
     **model + the whole system prompt (persona, guardrails, live catalog and this customer's display name) + the
     conversation history + the customer's own text**, lives only in RAM, expires (default 15 minutes) and never stores a
     reply that carries a product card — so a price/stock change, another customer or a different chat always misses. On a
     miss the reply is computed fresh from the current persona + guardrails + live catalog, so prices and stock shown by the
     model come from the same transaction that the buttons use.
14. **The system prompt is assembled in exactly one place** (`prompt_kit.build_system_prompt`): persona → the five fixed
     guardrail segments → read-only catalog (≤ 30 lines) → FAQ (≤ 12 items) → the sanitised display name, marked
     untrusted; both lists shrink to the model's real context window (`prompt_kit.SYSTEM_SHARE`, floors 6 lines / 3 FAQs).
     The preview in the UI is the same function's output, so what the owner sees is what the model gets; the
     guardrails have no toggle, and the app gives the model no write tools to be talked into.
15. **A model file is only ever loaded after it is verified:** pinned SHA-256 for catalog downloads, GGUF magic + size
     sanity for an already-present file, and extension/size/header checks for an imported file. `.part` files are never
     candidates, and a failed check deletes the file instead of loading it.
16. **Money is computed in exactly one formula** (`orders.order_total_irr`): `total = subtotal − discount + shipping`,
     inside the same `BEGIN IMMEDIATE` transaction that creates the order (`app/core/orders.py`). A shipping method is
     *settings*, normalised on every read (`settings.normalize_shipping_methods`: nameless rows dropped, negative costs
     clamped to 0, duplicate ids merged; the owner card caps the list at 12 methods) and resolved by `shop_flow` to a `(name, cost)` pair that is
     **frozen onto the order row** — so renaming or deleting a method never rewrites an old invoice. `free_over_irr` is
     compared against the *discounted* subtotal, shipping is offered whenever at least one method is active, and an order whose
     chosen method disappeared mid-checkout is not created: the customer is returned to the choice. The ledger's `sale`
     row always equals `total_irr`, the invoice derives its `ارسال/سایر` line from the same total, and the finance
     report keeps `gross_sales − discounts + shipping_income == sales_net` (tests in `tests/test_shipping.py`).
17. **Delivery status is not money.** `orders.fulfillment` (`'' → preparing → shipped → delivered`, forward-only with
     one allowed undo) and `tracking_code` are written only by `OrderStore.set_fulfillment`, which requires
     `status == confirmed` and touches neither `status`, `total_irr` nor stock. The customer notice on "shipped" is
     behind `notify_on_shipment` (default off) — the bot never speaks first.
18. **Search reads, never writes.** `core/search.py` fans out to `OrderStore.search` / `ProductStore.search` /
     `CustomerStore.list`, every `LIKE` parameterised with `%` and `_` escaped (so `٪` is literal text, not a wildcard),
     each group capped at 25 rows; the search screen has no callbacks that mutate anything.


## Additions (phase 6: finance and invoices)

- **`app/core/finance.py`** — ledger in `orders.db` (`ledger_entries`, `finance_categories`). Append-only via triggers; correction =
  reversal row (`reverses_id`, sign −1 in sums). Auto rows are keyed `(ref_type, ref_id, auto_key)` with a unique partial index so
  `post_order` is idempotent. Reports read orders + ledger directly (no parallel counters).
- **`app/core/invoices.py`** — `invoices` + `invoice_counters` in `orders.db`. Immutability by trigger; numbering and insert share one
  `BEGIN IMMEDIATE` transaction (gap-free); `compute_totals` keeps lines − discount + shipping = total with one rounding step for VAT.
- **`app/core/invoice_pdf.py`** — deterministic RTL PDF (fpdf2 + uharfbuzz, bundled Vazirmatn). Untrusted text is filtered to glyphs
  the font has; creation date = issue time so the file is reproducible from the snapshot (PDFs are a cache, never backed up).
- **`app/core/invoice_service.py`** — issue, cache, send. Send state lives in `invoices.sent_json`; a per-invoice lock re-checks state
  and backoff *inside* the lock so concurrent loops cannot double-send.
- **Wiring:** `OrderStore.add_confirm_listener` (after the stock saga, errors swallowed) → `BotManager._on_order_confirmed` posts the
  ledger and kicks the invoice loop; `_tick_finance` in the maintenance loop repairs anything a crash left behind.
- New invariants: the ledger never loses or edits a row; one sale invoice per order and one credit note per sale invoice; an invoice
  is never sent twice without an explicit *Resend*; money is integer rials everywhere (`round_div` is the only rounding).

## Additions (phase 7: guide, troubleshooter, low-stock alert)

- **`app/core/guide.py`** — loads `assets/guide/fa/<category>.md` (so it ships inside every PyInstaller build). One article =
  `## @id | title | keywords | group` + Markdown body; `[text](guide:id)` links; `HELP_FOR` maps each sidebar key to an article for the
  **?** button; `validate()` is the single content check (duplicate ids, broken links, missing help targets, minimum troubleshooting/FAQ
  counts) and is enforced by tests. Search normalises Arabic/Persian letters, digits and ZWNJ and requires every word (AND).
- **`app/core/troubleshoot.py`** — `run()` returns `Finding`s; every network probe is injectable, so tests never touch the internet;
  tokens never reach the output (a test greps for them). `telegram_adapter.webhook_url` is the one new adapter probe.
- **`app/core/quickstart.py`** — checklist steps derived from the real settings, never from a manual tick.
- **Low-stock (A7):** `BotManager._check_low_stock` runs in the confirm listener; `_reconcile_low_stock` (maintenance loop) closes the
  attention item once stock recovers. Dedupe is the attention inbox's own (type, ref) rule.

## Release notes for maintainers (phase 8)

- **Data:** orders.db v8 (ledger, categories, invoices, counters, payment claims, delivery status, shipping; triggers), products.db v4 (physical-only model, `cost_irr`), conversations.db v6
  (unchanged this release). All schema changes go through `MIGRATIONS`; `tests/test_migrations.py` pins the versions.
- **Dependencies added for the invoice/QR path:** `fpdf2`, `uharfbuzz` (invoice PDF), `segno` (QR). `pypdf` is test-only. PyInstaller finds the lazy
  imports through `invoice_pdf._pyinstaller_hint`; **PDF rendering inside a frozen Linux build was smoke-tested (Persian text renders, guide loads); inside the packaged Windows exe it is unverified** — the guide's
  manual checklist asks the owner to check it first, and a text invoice is the automatic fallback.
- **Cross-cutting rules** (each has a test): money is integer rials, rounded only by `finance.round_div`; the ledger and invoices are
  append-only/immutable by SQLite trigger; confirm listeners never break a confirmation and are repaired by `post_missing`/
  `process_pending`; nothing is sent twice without an explicit *Resend*; no secret reaches a log, a diagnostic file, the troubleshooter
  or the AI history; untrusted text is filtered before it reaches a PDF or a CSV.
- **Deliberately not shipped:** see `ROADMAP.md` (background/tray run, richer dashboard, full refund workflow, English guide,
  pro-forma invoices, partial credit notes).
