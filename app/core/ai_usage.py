"""مصرفِ توکن و هزینه (N1): ثبتِ هر تماسِ AI، میانگین‌ها، محاسبه‌گرِ هزینه (Decimal) و بودجه.

* توکنِ واقعی از ``usage`` پاسخِ API؛ نبودش ⇒ تخمین با برچسبِ ``estimated`` (هرگز بی‌برچسب).
* هیچ قیمت/نرخِ پیش‌فرضِ ساختگی نیست؛ قیمتِ هر مدل را کاربر وارد می‌کند (دلار به‌ازای ۱ میلیون توکن). مدلِ بی‌قیمت در هزینه نمی‌آید و جدا گزارش می‌شود.
* پول فقط ``Decimal``؛ آمارِ مالی از ردیف‌های اصلیِ ``ai_calls`` محاسبه می‌شود نه شمارنده‌ی جدا (ناوردایی ۲۲).
* ردیف‌های خامِ قدیمی‌تر از ۹۰ روز در ``ai_usage_daily`` جمع و حذف می‌شوند (``prune``).
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

logger = logging.getLogger(__name__)
RAW_RETENTION_DAYS = 90
ONE_MILLION = Decimal(1_000_000)

_CTX: contextvars.ContextVar = contextvars.ContextVar("ai_call_ctx", default=("", "", "chat"))
RECORDER: Optional["UsageStore"] = None  # BotManager/برنامه تنظیم می‌کند؛ None ⇒ ثبت بی‌اثر


@contextlib.contextmanager
def bind(platform: str, chat_id: str, source: str = "chat"):
    """مشخص می‌کند تماس‌های AIِ داخلِ این بلوک (حتی از ``asyncio.to_thread``) به کدام چت/منبع تعلق دارند."""
    token = _CTX.set((str(platform), str(chat_id), source))
    try:
        yield
    finally:
        _CTX.reset(token)


def record_call(**fields) -> None:
    store = RECORDER
    if store is None:
        return
    platform, chat_id, source = _CTX.get()
    fields.setdefault("platform", platform)
    fields.setdefault("chat_id", chat_id)
    fields.setdefault("source", source)
    try:
        store.record(**fields)
    except Exception:  # noqa: BLE001 — خرابیِ آمار هرگز پاسخ‌دهی را نمی‌شکند
        logger.debug("ثبتِ مصرفِ AI ناموفق بود", exc_info=True)


def dec(value, default: Decimal = Decimal(0)) -> Decimal:
    try:
        d = Decimal(str(value).strip().replace(",", "").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٫", "0123456789.")))
    except (InvalidOperation, ValueError):
        return default
    return d if d.is_finite() and d >= 0 else default


def day_of(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


@dataclass
class Totals:
    calls: int = 0
    ok_calls: int = 0
    prompt: int = 0
    completion: int = 0
    cached: int = 0
    saved: int = 0

    @property
    def tokens(self) -> int:
        return self.prompt + self.completion


class UsageStore:
    def __init__(self, conversation_store, clock=time.time):
        self._store = conversation_store
        self._clock = clock

    def _conn(self):
        return self._store.connection()

    def record(self, *, provider_id: str = "", model: str = "", attempt: int = 1, failover_reason: str = "", prompt_tokens: int = 0,
               completion_tokens: int = 0, cached_tokens: int = 0, kind: str = "chat", source: str = "chat", latency_ms: int = 0,
               ok: bool = True, estimated: bool = False, saved_tokens: int = 0, sys_tokens: int = 0, hist_tokens: int = 0, msg_tokens: int = 0,
               platform: str = "", chat_id: str = "") -> None:
        conn = self._conn()
        conn.execute(
            """INSERT INTO ai_calls (ts, platform, chat_id, provider_id, model, attempt, failover_reason, prompt_tokens, completion_tokens,
               cached_tokens, kind, source, latency_ms, ok, estimated, saved_tokens, sys_tokens, hist_tokens, msg_tokens)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (int(self._clock()), platform, str(chat_id), provider_id, model[:120], attempt, failover_reason[:60], max(0, int(prompt_tokens)),
             max(0, int(completion_tokens)), max(0, int(cached_tokens)), kind, source, max(0, int(latency_ms)), int(ok), int(estimated),
             max(0, int(saved_tokens)), max(0, int(sys_tokens)), max(0, int(hist_tokens)), max(0, int(msg_tokens))),
        )
        conn.commit()

    # ---------- خواندن
    def by_model(self, since_ts: int = 0) -> dict:
        """``{(provider_id, model): Totals}`` از ردیف‌های خام + جمع‌بندی‌های روزانه."""
        out: dict = {}
        conn = self._conn()
        for r in conn.execute(
            """SELECT provider_id, model, COUNT(*) c, SUM(ok) o, SUM(prompt_tokens) p, SUM(completion_tokens) q, SUM(cached_tokens) k, SUM(saved_tokens) s
               FROM ai_calls WHERE ts >= ? GROUP BY provider_id, model""", (int(since_ts),)).fetchall():
            out[(r["provider_id"], r["model"])] = Totals(r["c"], r["o"] or 0, r["p"] or 0, r["q"] or 0, r["k"] or 0, r["s"] or 0)
        for r in conn.execute(
            """SELECT provider_id, model, SUM(calls) c, SUM(ok_calls) o, SUM(prompt_tokens) p, SUM(completion_tokens) q, SUM(cached_tokens) k,
               SUM(saved_tokens) s FROM ai_usage_daily WHERE day >= ? GROUP BY provider_id, model""", (day_of(since_ts) if since_ts else "0000",)).fetchall():
            t = out.setdefault((r["provider_id"], r["model"]), Totals())
            t.calls += r["c"] or 0
            t.ok_calls += r["o"] or 0
            t.prompt += r["p"] or 0
            t.completion += r["q"] or 0
            t.cached += r["k"] or 0
            t.saved += r["s"] or 0
        return out

    def totals(self, since_ts: int = 0) -> Totals:
        total = Totals()
        for t in self.by_model(since_ts).values():
            total.calls += t.calls
            total.ok_calls += t.ok_calls
            total.prompt += t.prompt
            total.completion += t.completion
            total.cached += t.cached
            total.saved += t.saved
        return total

    def daily(self, days: int = 30) -> list:
        """``[(day, calls, tokens)]`` قدیمی ← جدید، روزهای خالی هم صفر می‌آیند."""
        now = self._clock()
        start = now - (days - 1) * 86400
        conn = self._conn()
        acc: dict = {}
        for r in conn.execute(
            "SELECT date(ts,'unixepoch') d, COUNT(*) c, SUM(prompt_tokens+completion_tokens) t FROM ai_calls WHERE ts >= ? AND provider_id != 'cache' GROUP BY d",
            (int(start // 86400 * 86400),)).fetchall():
            acc[r["d"]] = [r["c"], r["t"] or 0]
        for r in conn.execute("SELECT day d, SUM(calls) c, SUM(prompt_tokens+completion_tokens) t FROM ai_usage_daily WHERE day >= ? GROUP BY d", (day_of(start),)).fetchall():
            cur = acc.setdefault(r["d"], [0, 0])
            cur[0] += r["c"] or 0
            cur[1] += r["t"] or 0
        return [(day_of(start + i * 86400), *acc.get(day_of(start + i * 86400), [0, 0])) for i in range(days)]

    def top_chats(self, since_ts: int, limit: int = 5) -> list:
        rows = self._conn().execute(
            """SELECT platform, chat_id, COUNT(*) c, SUM(prompt_tokens+completion_tokens) t FROM ai_calls
               WHERE ts >= ? AND chat_id != '' AND ok=1 GROUP BY platform, chat_id ORDER BY t DESC LIMIT ?""", (int(since_ts), limit)).fetchall()
        return [(r["platform"], r["chat_id"], r["c"], r["t"] or 0) for r in rows]

    def input_breakdown(self, since_ts: int) -> dict:
        r = self._conn().execute(
            "SELECT COUNT(*) c, AVG(sys_tokens) s, AVG(hist_tokens) h, AVG(msg_tokens) m FROM ai_calls WHERE ts >= ? AND ok=1 AND sys_tokens>0", (int(since_ts),)).fetchone()
        return {"calls": r["c"] or 0, "system": round(r["s"] or 0), "history": round(r["h"] or 0), "message": round(r["m"] or 0)}

    def activity(self, since_ts: int) -> dict:
        """مشتریِ متمایز، تعدادِ پاسخ و سهمِ تخمینی — برای پیش‌پرکردنِ «چه می‌شود اگر» از داده‌ی واقعی."""
        r = self._conn().execute(
            "SELECT COUNT(DISTINCT platform || ':' || chat_id) chats, COUNT(*) calls, SUM(estimated) est FROM ai_calls WHERE ts >= ? AND ok=1 AND chat_id != '' AND provider_id != 'cache'",
            (int(since_ts),)).fetchone()
        return {"chats": r["chats"] or 0, "calls": r["calls"] or 0, "estimated": r["est"] or 0}

    def cache_hits(self, since_ts: int) -> tuple:
        r = self._conn().execute("SELECT COUNT(*) c, COALESCE(SUM(saved_tokens),0) s FROM ai_calls WHERE ts >= ? AND provider_id = 'cache'", (int(since_ts),)).fetchone()
        return int(r["c"]), int(r["s"])

    def failovers(self, limit: int = 20) -> list:
        rows = self._conn().execute(
            "SELECT ts, provider_id, model, failover_reason FROM ai_calls WHERE failover_reason != '' ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [(r["ts"], r["provider_id"], r["model"], r["failover_reason"]) for r in rows]

    def prune(self) -> int:
        cutoff = int(self._clock() - RAW_RETENTION_DAYS * 86400)
        conn = self._conn()
        rows = conn.execute(
            """SELECT date(ts,'unixepoch') d, provider_id, model, COUNT(*) c, SUM(ok) o, SUM(prompt_tokens) p, SUM(completion_tokens) q,
               SUM(cached_tokens) k, SUM(saved_tokens) s FROM ai_calls WHERE ts < ? GROUP BY d, provider_id, model""", (cutoff,)).fetchall()
        for r in rows:
            conn.execute(
                """INSERT INTO ai_usage_daily (day, provider_id, model, calls, ok_calls, prompt_tokens, completion_tokens, cached_tokens, saved_tokens)
                   VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(day, provider_id, model) DO UPDATE SET calls=calls+excluded.calls,
                   ok_calls=ok_calls+excluded.ok_calls, prompt_tokens=prompt_tokens+excluded.prompt_tokens,
                   completion_tokens=completion_tokens+excluded.completion_tokens, cached_tokens=cached_tokens+excluded.cached_tokens,
                   saved_tokens=saved_tokens+excluded.saved_tokens""",
                (r["d"], r["provider_id"], r["model"], r["c"], r["o"] or 0, r["p"] or 0, r["q"] or 0, r["k"] or 0, r["s"] or 0))
        deleted = conn.execute("DELETE FROM ai_calls WHERE ts < ?", (cutoff,)).rowcount
        conn.commit()
        return deleted


# ------------------------------------------------------------------------------ هزینه (Decimal) ----


def model_prices(settings) -> dict:
    """``{(provider_id, model): (price_in, price_out)}`` فقط مدل‌هایی که قیمتِ کاربر دارند (دلار/۱M توکن)."""
    from app.core import ai_providers

    out = {}
    for p in ai_providers.parse_providers(settings):
        for m in p.models:
            pin, pout = dec(m.price_in), dec(m.price_out)
            if pin or pout:
                out[(p.id, m.name)] = (pin, pout)
    return out


def call_cost(prompt: int, completion: int, price_in: Decimal, price_out: Decimal) -> Decimal:
    return (Decimal(prompt) * price_in + Decimal(completion) * price_out) / ONE_MILLION


def cost_of(by_model: dict, prices: dict) -> tuple:
    """``(هزینه به دلار، توکنِ بی‌قیمت)`` — مدلِ بی‌قیمت در جمع نمی‌آید (عددِ ساختگی نمی‌سازیم)."""
    total, unpriced = Decimal(0), 0
    for key, t in by_model.items():
        if key[0] == "cache":
            continue
        price = prices.get(key)
        if price is None:
            unpriced += t.tokens
            continue
        total += call_cost(t.prompt, t.completion, *price)
    return total, unpriced


def month_start_ts(now: float) -> int:
    d = datetime.fromtimestamp(now, tz=timezone.utc)
    return int(d.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp())


def convert(usd: Decimal, settings) -> tuple:
    """``(مقدار، نماد)`` طبقِ واحدِ نمایش؛ نرخِ دلار ننوشته ⇒ دلار."""
    unit = getattr(settings, "cost_display_unit", "usd")
    rate = dec(getattr(settings, "usd_to_irr_rate", ""))
    if unit in ("toman", "irr") and rate > 0:
        toman = usd * rate
        return (toman, "تومان") if unit == "toman" else (toman * 10, "ریال")
    return usd, "$"


def fmt_money(usd: Decimal, settings) -> str:
    value, sym = convert(usd, settings)
    if sym == "$":
        return f"${value:,.4f}"
    return f"{int(value.to_integral_value()):,} {sym}"


class Budget:
    """بودجه‌ی ماهانه (دلار). ``status`` ∈ ok | warn | exceeded."""

    def __init__(self, usage: UsageStore, settings_getter, clock=time.time):
        self._usage, self._settings, self._clock = usage, settings_getter, clock

    def month_cost(self) -> Decimal:
        s = self._settings()
        return cost_of(self._usage.by_model(month_start_ts(self._clock())), model_prices(s))[0]

    def limit(self) -> Decimal:
        return dec(getattr(self._settings(), "ai_budget_monthly_usd", ""))

    def status(self) -> str:
        limit = self.limit()
        if limit <= 0:
            return "ok"
        spent = self.month_cost()
        return "exceeded" if spent >= limit else "warn" if spent >= limit * Decimal("0.8") else "ok"


def forecast_month(spent: Decimal, now: float) -> Decimal:
    """پیش‌بینیِ خطی تا آخرِ ماه از روی میانگینِ روزانه‌ی همین ماه."""
    d = datetime.fromtimestamp(now, tz=timezone.utc)
    nxt = d.replace(year=d.year + (d.month == 12), month=d.month % 12 + 1, day=1)
    days_in_month = (nxt - d.replace(day=1)).days
    elapsed = max(Decimal(d.day - 1) + Decimal(d.hour) / 24, Decimal("0.25"))
    return spent / elapsed * days_in_month


def what_if(customers_per_day: int, questions_each: int, avg_tokens: tuple, prices: tuple, days: int = 30) -> Decimal:
    """«چه می‌شود اگر»: مشتری در روز × پرسش به‌ازای هر مشتری × میانگینِ (ورودی، خروجی) ⇒ هزینه‌ی ماه (دلار)."""
    replies = int(customers_per_day) * int(questions_each) * days
    return call_cost(avg_tokens[0] * replies, avg_tokens[1] * replies, *prices)
