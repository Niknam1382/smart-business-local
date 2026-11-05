"""مصرفِ مدلِ محلی (N1): ثبتِ هر تماسِ AI (توکن و زمانِ پاسخ) و میانگین‌ها.

نسخه‌ی ۱.۰.۰: مدل روی کامپیوترِ خودِ فروشنده اجرا می‌شه، پس **هیچ هزینه‌ی دلاری/تومانی** وجود ندارد
و این ماژول فقط «چقدر کار کرد» را می‌شمارد، نه «چقدر پول» — پولِ واقعیِ فروشنده همان برق و رم است.

* توکنِ واقعی از ``usage`` پاسخِ llama.cpp؛ نبودش ⇒ تخمین با برچسبِ ``estimated`` (هرگز بی‌برچسب).
* ردیف‌های خامِ قدیمی‌تر از ۹۰ روز در ``ai_usage_daily`` جمع و حذف می‌شوند (``prune``).
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)
RAW_RETENTION_DAYS = 90
LOCAL_PROVIDER = "local"  # تنها «ارائه‌دهنده» در نسخه‌ی ۱.۰.۰: کامپیوترِ خودِ فروشنده

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


def day_of(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


@dataclass
class Totals:
    calls: int = 0
    ok_calls: int = 0
    prompt: int = 0
    completion: int = 0

    @property
    def tokens(self) -> int:
        return self.prompt + self.completion


class UsageStore:
    def __init__(self, conversation_store, clock=time.time):
        self._store = conversation_store
        self._clock = clock

    def _conn(self):
        return self._store.connection()

    def record(self, *, provider_id: str = LOCAL_PROVIDER, model: str = "", prompt_tokens: int = 0,
               completion_tokens: int = 0, kind: str = "chat", source: str = "chat", latency_ms: int = 0,
               ok: bool = True, estimated: bool = False, sys_tokens: int = 0, hist_tokens: int = 0, msg_tokens: int = 0,
               platform: str = "", chat_id: str = "") -> None:
        conn = self._conn()
        conn.execute(
            """INSERT INTO ai_calls (ts, platform, chat_id, provider_id, model, prompt_tokens, completion_tokens,
               kind, source, latency_ms, ok, estimated, sys_tokens, hist_tokens, msg_tokens)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (int(self._clock()), platform, str(chat_id), provider_id or LOCAL_PROVIDER, model[:120], max(0, int(prompt_tokens)),
             max(0, int(completion_tokens)), kind, source, max(0, int(latency_ms)), int(ok), int(estimated),
             max(0, int(sys_tokens)), max(0, int(hist_tokens)), max(0, int(msg_tokens))),
        )
        conn.commit()

    # ---------- خواندن
    def by_model(self, since_ts: int = 0) -> dict:
        """``{model: Totals}`` از ردیف‌های خام + جمع‌بندی‌های روزانه (همه روی یک مدلِ محلی)."""
        out: dict = {}
        conn = self._conn()
        for r in conn.execute(
            """SELECT model, COUNT(*) c, SUM(ok) o, SUM(prompt_tokens) p, SUM(completion_tokens) q
               FROM ai_calls WHERE ts >= ? GROUP BY model""", (int(since_ts),)).fetchall():
            out[r["model"]] = Totals(r["c"], r["o"] or 0, r["p"] or 0, r["q"] or 0)
        for r in conn.execute(
            """SELECT model, SUM(calls) c, SUM(ok_calls) o, SUM(prompt_tokens) p, SUM(completion_tokens) q
               FROM ai_usage_daily WHERE day >= ? GROUP BY model""", (day_of(since_ts) if since_ts else "0000",)).fetchall():
            t = out.setdefault(r["model"], Totals())
            t.calls += r["c"] or 0
            t.ok_calls += r["o"] or 0
            t.prompt += r["p"] or 0
            t.completion += r["q"] or 0
        return out

    def totals(self, since_ts: int = 0) -> Totals:
        total = Totals()
        for t in self.by_model(since_ts).values():
            total.calls += t.calls
            total.ok_calls += t.ok_calls
            total.prompt += t.prompt
            total.completion += t.completion
        return total

    def avg_latency_ms(self, since_ts: int = 0) -> int:
        """میانگینِ زمانِ پاسخِ مدلِ محلی (ملاکِ واقعیِ «سریع یا کند» برای فروشنده)."""
        r = self._conn().execute(
            "SELECT AVG(latency_ms) a FROM ai_calls WHERE ts >= ? AND ok=1 AND latency_ms>0", (int(since_ts),)
        ).fetchone()
        return int(r["a"] or 0)

    def daily(self, days: int = 30) -> list:
        """``[(day, calls, tokens)]`` قدیمی ← جدید، روزهای خالی هم صفر می‌آیند."""
        now = self._clock()
        start = now - (days - 1) * 86400
        conn = self._conn()
        acc: dict = {}
        for r in conn.execute(
            "SELECT date(ts,'unixepoch') d, COUNT(*) c, SUM(prompt_tokens+completion_tokens) t FROM ai_calls WHERE ts >= ? GROUP BY d",
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
        """مشتریِ متمایز، تعدادِ پاسخ و سهمِ تخمینیِ توکن — برای نمایشِ مصرف از داده‌ی واقعی."""
        r = self._conn().execute(
            "SELECT COUNT(DISTINCT platform || ':' || chat_id) chats, COUNT(*) calls, SUM(estimated) est FROM ai_calls WHERE ts >= ? AND ok=1 AND chat_id != ''",
            (int(since_ts),)).fetchone()
        return {"chats": r["chats"] or 0, "calls": r["calls"] or 0, "estimated": r["est"] or 0}

    def estimated_share(self, since_ts: int = 0) -> tuple:
        """``(تعدادِ تماس‌های با توکنِ تخمینی, تعدادِ کلِ پاسخ‌دهی‌شده)`` — صداقتِ آمار: هیچ عددی بی‌برچسب نیست."""
        r = self._conn().execute(
            "SELECT COUNT(*) c, SUM(estimated) e FROM ai_calls WHERE ts >= ? AND ok=1", (int(since_ts),)
        ).fetchone()
        return int(r["e"] or 0), int(r["c"] or 0)

    def prune(self) -> int:
        cutoff = int(self._clock() - RAW_RETENTION_DAYS * 86400)
        conn = self._conn()
        rows = conn.execute(
            """SELECT date(ts,'unixepoch') d, model, COUNT(*) c, SUM(ok) o, SUM(prompt_tokens) p, SUM(completion_tokens) q
               FROM ai_calls WHERE ts < ? GROUP BY d, model""", (cutoff,)).fetchall()
        for r in rows:
            conn.execute(
                """INSERT INTO ai_usage_daily (day, provider_id, model, calls, ok_calls, prompt_tokens, completion_tokens)
                   VALUES (?,?,?,?,?,?,?) ON CONFLICT(day, provider_id, model) DO UPDATE SET calls=calls+excluded.calls,
                   ok_calls=ok_calls+excluded.ok_calls, prompt_tokens=prompt_tokens+excluded.prompt_tokens,
                   completion_tokens=completion_tokens+excluded.completion_tokens""",
                (r["d"], LOCAL_PROVIDER, r["model"], r["c"], r["o"] or 0, r["p"] or 0, r["q"] or 0))
        deleted = conn.execute("DELETE FROM ai_calls WHERE ts < ?", (cutoff,)).rowcount
        conn.commit()
        return deleted


def month_start_ts(now: float) -> int:
    d = datetime.fromtimestamp(now, tz=timezone.utc)
    return int(d.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp())
