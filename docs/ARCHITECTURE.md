# Architecture

Smart Business Local is a single-process desktop app (Flet UI) that runs Telegram/Bale bot adapters, an AI engine
and SQLite stores on the owner's machine. There is no server and no account. This document describes how the
pieces fit and — most importantly — the invariants that keep money and stock safe.

## Process layout

```
Flet UI (main thread)  ──►  BotManager  ──►  asyncio loop in a worker thread
 screens/*                  (singleton)        ├─ TelegramAdapter (aiogram polling)
                                               ├─ BaleAdapter     (own long-poll client)
                                               ├─ ConversationPipeline (debounce, flood limit, per-chat lock)
                                               │     ├─ OwnerConsole      (owner commands, before anything else)
                                               │     └─ StoreAgent        (store mode) / plain chat (consultant)
                                               └─ maintenance loop (reservation expiry, Zarinpal polling)
SQLite: settings.json (encrypted secrets) · conversations.db · products.db · orders.db
Data folder: OS default, or *portable* (`portable.flag` / `SmartBusinessData/` next to the app) — see `paths.py`
```

## Modules (`app/core`)

| Module | Responsibility |
|---|---|
| `ai_engine.py`, `tool_protocol.py` | `ApiEngine` (OpenAI-compatible; native tool calling with automatic fallback to a `<tool_call>` text protocol) and `LocalEngine` (llama-cpp, text protocol). `chat_tools()` returns a `ToolTurn`. |
| `store_agent.py` | The "smart admin": `StoreToolbox` (tools), prompt builder, bounded model↔tool loop. |
| `orders.py` | Orders, **stock reservation**, atomic state transitions, late-payment handling. |
| `products.py` | Catalog and real stock. |
| `payments.py` | `PaymentService`: available methods, payment instructions, Bale Pay pre-checkout/success, auto-confirm, diagnostics. |
| `zarinpal.py` | Zarinpal v4 client (`request`, `verify`). |
| `owner_console.py` | One-time-code owner registration, `/confirm` `/reject` `/orders` …, owner alerts. |
| `bot_manager.py` | Lifecycle, adapters, delivery, maintenance loop, log redaction. |
| `telegram_adapter.py`, `bale_adapter.py`, `bale_client.py` | Messenger I/O, URL-button messages, media-as-note. The Bale adapter answers `/start pay_<id>_<code>` / `/pay` itself (no AI). |
| `proxy_pool.py` | Telegram proxy list: parsing (`socks5/socks4/http`, `host:port`, `user:pass@host:port`), health probes, ranking, cool-down and **automatic failover** (the Telegram adapter swaps its `Bot` after consecutive network errors). |
| `paths.py` | Data-folder resolution: env override → **portable mode** → OS default; falls back to the OS folder if the portable folder is read-only. |
| `backup.py` | Backup / restore / factory reset / diagnostics. Databases are copied with SQLite's online-backup API and **reset/restore happen in place** (stores keep per-thread connections open, so files are never deleted or swapped). |
| `crypto.py`, `redact.py`, `settings.py` | Secret storage (Fernet; the key lives beside the data so a portable folder stays self-contained), log scrubbing, atomic settings writes, corrupt-file quarantine. |

## 1.1 additions (phase 1)

| Module | Responsibility |
|---|---|
| `branding.py` (`app/`) | The only place with the creator's public identity (links, e-mail, Daramet username, credit line, update public key). A repository test fails if it leaks into other source files. |
| `ui_glyphs.py` | Per-platform button glyphs: plain `−`/`+`/*Remove* on Bale, emoji on Telegram; `is_emoji_only` guards Bale labels. |
| `shop_text_meta.py` | Metadata for all customer messages: plain title, group, "when shown", basic/advanced level, Persian variable names with examples, display↔storage conversion (`{شماره‌ی سفارش}` ⇄ `{order_id}`), live preview, button-label limits. |
| `quick_setup.py` | One-click presets by business type (mode, order form, numbers) that never touch tokens, payments, FAQ, messages or the bio. |
| `bot_profile.py` | Creator credit in the bot bio: composition (≤ 120 UTF-16 units), safe sync rules (never erase/truncate seller text; confirmation first), Telegram per-language versions, Bale probe + graceful fallback. `BotManager` runs it after connect, every 24 h and on demand. |
| `updater.py`, `update_verify.py` | GitHub *latest release* check (semver, drafts/pre-releases ignored, host-allow-listed URLs, silent failure) and Ed25519 + SHA-256 verification used by the future installer. |
| `data_probe.py` | Read-only detection of previous data (counts only) for the "continue / start fresh" prompt. |
| `support_link.py` | Builds the optional Daramet link (Toman amount + ≤ 100-char message). Used only by the About screen; a test proves no bot-facing module imports it. |
| `about_info.py` | Pre-filled GitHub issue URL (version + OS only). |

New invariants: the credit line exists **only** in the bio (never in messages/orders/payments — enforced by tests); an existing
bio is never overwritten without being shown to the owner; no release artifact may contain user data (packaging check +
repository test); update installation is impossible without a valid signature and matching hash; nothing in the app sends
user data anywhere (the only network call of the new features is the update check GET).

## The store agent

The model never touches money or stock directly. It calls tools; the app validates every call server-side:

`search_products` · `create_order` · `update_order` · `get_my_orders` · `cancel_order` · `start_payment` ·
`report_card_payment` · `escalate_to_owner`

Invariants (each has tests — see `tests/test_store_agent.py`, `tests/test_hardening.py`):

1. `chat_id` is **never** a tool parameter — a tool can only act on the current customer's orders.
2. Prices/stock come from the stores. The system prompt is rebuilt every message (catalog, enabled payment
   methods, the customer's live orders). Customer text and profile names are untrusted (names are sanitised
   before entering the system prompt).
3. Card numbers and payment links are sent **verbatim by the app** (`outbox`), after the model's text — the
   model never re-types them.
4. The model cannot confirm a payment. Card-to-card claims only mark an order *paid, awaiting owner*.
5. Tool results are always `{"ok": bool, ...}` with Persian error text; tools never raise into the loop.
6. Loop bounds: 7 steps, 4 tool calls per step; an AI error *after* a payment message was queued still
   delivers that message.
7. Anti-hoarding: ≤ 6 orders/hour and ≤ 3 expired-unpaid orders/day per customer.

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

## Payments

- **Card-to-card** — instruction message from settings; customer claims; owner confirms (manual, always).
- **Bale Pay** — only documented Bot API methods. A **Bale customer** gets a native `sendInvoice` inside the chat.
  A **Telegram customer** gets a deep link `https://ble.ir/<bale_bot>?start=pay_<order>_<code>` (URL button *and*
  plain text, plus the manual fallback `/pay <order> <code>`); when they press *Start* in Bale the Bale adapter
  validates the per-order random `<code>` (constant-time compare, order still pending and reserved, method still
  Bale Pay) and sends the native invoice to *that* Bale chat. Pre-checkout rejects expired orders and wrong
  amounts; success → mark paid → auto-confirm (setting) → the confirmation goes to the customer's *original*
  platform. (`createInvoiceLink` was dropped: its response format is not documented and links were broken in
  practice.) The provider token is a 16-digit card number or a `WALLET-…` token.
- **Zarinpal** — `request` → `StartPay/{authority}`; with no public callback URL, `verify` is **polled** every
  ~20 s (also for recently expired/cancelled orders, so late money is recorded). Callback URL defaults to the
  bot chat link.
- The settings screen has live *Test connection* buttons that perform a real call and show the exact error.

## Owner console

`/owner <code>` (one-time, 10 min, ~50-bit code) from the owner's personal chat registers it per platform.
Commands work only from the registered chat and only when the whole message is a command; anything else from
the owner goes to the AI (so the owner can test the bot). Alerts: payment awaiting approval, auto-confirmed
sale (with delivery details), late payment, AI escalations.

## Testing strategy

Tests run real aiogram / `BaleClient` / `BotManager` against fake servers (`tests/fake_servers.py`,
`fake_zarinpal.py`, `fake_openai.py`). The language model is replaced by `ScriptedToolEngine`, so every tool the
"model" calls really executes. Concurrency invariants are tested with threads. What cannot be tested offline —
real Telegram/Bale/Zarinpal behaviour and real model quality — is covered by `docs/testing/TESTING_PHASE4.md`.


## v1.0.0 additions

```
Customer ──► Adapter (Telegram / Bale) ──► ConversationPipeline
                                              ├─ OwnerConsole (+ /reply /close /handoffs, Reply routing)
                                              ├─ /forget · usage limits (UsageLimiter) · block list · flood limit
                                              ├─ mode = resolve_mode(settings, platform)         (modes.py)
                                              │    buttons → ShopFlow ─► FlowResult[UiMessage] ─► ui.deliver(Transport)
                                              │    ai_qa   → QaAgent (read-only; tool: suggest_products)
                                              │    shop_ai → StoreAgent (0.5.0 flow, experimental)
                                              ├─ HandoffService (open session ⇒ messages go to the owner, AI silent)
                                              └─ Debouncer ─► AI
BotManager maintenance loop: reservation expiry · inventory saga recovery · digital-delivery retry · handoff timeout ·
                              proxy-subscription refresh · retention purge
```

| Module | Responsibility |
|---|---|
| `migrations.py` | Versioned SQLite migrations (`PRAGMA user_version`), one transaction each, pre-upgrade backup, `SchemaTooNewError`. Stores call `migrations.prepare()` on every new connection. |
| `shop_flow.py` / `ui.py` | Platform-neutral button shop. `callback_data` is `c:<verb>:<args…>` (≤ 64 bytes). Quantities are *targets* (`set_qty`) so double taps are idempotent. Per-chat `asyncio.Lock`. Adapters only implement `Transport` (`send_ui`, `edit_ui`, `delete_message`, `answer_callback`). |
| `checkout_fields.py`, `cart.py` | Configurable checkout fields + validation; `carts` / `checkout_sessions` tables in `orders.db` (survive restarts). |
| `shop_texts.py` | Registry of every customer-facing message (fa/en), owner overrides validated against allowed placeholders; rendering never raises. |
| `delivery.py` | Digital delivery after confirmation; idempotent via `orders.delivered_ts` (`-1` = nothing to deliver). |
| `handoff.py`, `working_hours.py` | Human support sessions, Reply routing (`relay_map`), inactivity timeout, Tehran working hours. |
| `usage_limits.py`, `attention.py` | Daily AI caps + kill switch; "needs attention" inbox. |
| `qa_agent.py`, `modes.py` | Read-only Q&A agent; mode registry (`resolve_mode` never raises). |
| `proxy_subscription.py` | User-supplied subscription link → validated proxy list (size/time caps), encrypted cache. |
| `headless.py` | UI-less runner with heartbeat/health check (Docker). |

### New invariants

1. **Order confirmation is a saga** (`OrderStore.confirm`): (a) atomic claim `paid → confirmed`, (b) one `products.db`
   transaction: unique `stock_ledger` row + stock decrement + digital-key allocation, (c) `inventory_applied = 1`.
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
11. **The AI layer is a chain, not a single call.** In API mode every reply goes through `FailoverEngine`: it always starts from the top
    of the chain, re-fits “system prompt + history + message” to each model's own window (memory lives in the app's database, so a switch
    loses nothing), classifies each failure (`ai_providers.classify`) and reacts per class, behind a per-target circuit breaker. API keys
    never reach logs or error text.
12. **Usage numbers come from the API when it sends them, otherwise they are labelled *estimated*; costs use only prices the owner
    entered (no default prices, no invented figures).** Statistics are computed from `ai_calls` rows, never from separate counters.
13. **The exact-match answer cache is off by default and keyed on a hash of the whole final request**; it never stores tool turns, errors,
    partial or filtered answers, turns with history, or messages with personal data, lives in memory only and is cleared on any
    product/order/text/settings change. The old engine-level cache (keyed on prompt + message only) was removed because it could leak
    another customer's answer.


## 1.1 additions (phase 6: finance and invoices)

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

## 1.1 additions (phase 7: guide, troubleshooter, low-stock alert)

- **`app/core/guide.py`** — loads `assets/guide/fa/<category>.md` (so it ships inside every PyInstaller build). One article =
  `## @id | title | keywords | group` + Markdown body; `[text](guide:id)` links; `HELP_FOR` maps each sidebar key to an article for the
  **?** button; `validate()` is the single content check (duplicate ids, broken links, missing help targets, minimum troubleshooting/FAQ
  counts) and is enforced by tests. Search normalises Arabic/Persian letters, digits and ZWNJ and requires every word (AND).
- **`app/core/troubleshoot.py`** — `run()` returns `Finding`s; every network probe is injectable, so tests never touch the internet;
  tokens never reach the output (a test greps for them). `telegram_adapter.webhook_url` is the one new adapter probe.
- **`app/core/quickstart.py`** — checklist steps derived from the real settings, never from a manual tick.
- **Low-stock (A7):** `BotManager._check_low_stock` runs in the confirm listener; `_reconcile_low_stock` (maintenance loop) closes the
  attention item once stock recovers. Dedupe is the attention inbox's own (type, ref) rule.

## 1.1 release notes for maintainers (phase 8)

- **Data:** orders.db v5 (ledger, categories, invoices, counters; triggers), products.db v3 (`cost_irr`), conversations.db v6
  (unchanged this release). All schema changes go through `MIGRATIONS`; `tests/test_migrations.py` pins the versions.
- **Dependencies added in 1.1:** `fpdf2`, `uharfbuzz` (invoice PDF), `segno` (QR). `pypdf` is test-only. PyInstaller finds the lazy
  imports through `invoice_pdf._pyinstaller_hint`; **PDF rendering inside a frozen Linux build was smoke-tested (Persian text renders, guide loads); inside the packaged Windows exe it is unverified** — the guide's
  manual checklist asks the owner to check it first, and a text invoice is the automatic fallback.
- **Cross-cutting rules** (each has a test): money is integer rials, rounded only by `finance.round_div`; the ledger and invoices are
  append-only/immutable by SQLite trigger; confirm listeners never break a confirmation and are repaired by `post_missing`/
  `process_pending`; nothing is sent twice without an explicit *Resend*; no secret reaches a log, a diagnostic file, the troubleshooter
  or the AI history; untrusted text is filtered before it reaches a PDF or a CSV.
- **Deliberately not in 1.1:** see `ROADMAP.md` (shipping methods, global search, background/tray run, richer dashboard, store-rules
  template, full refund workflow, English guide, pro-forma invoices, partial credit notes).
