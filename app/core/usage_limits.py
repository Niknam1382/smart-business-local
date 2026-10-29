"""
سقفِ مصرف/هزینه‌ی AI (R10-۳): ربات عمومی = هزینه‌ی کلیدِ API مالک؛ پس سقفِ روزانه *به‌ازای هر چت* و *کل* + کلیدِ قطعِ
اضطراری. سقف‌ها فقط **پاسخ‌های AI** رو محدود می‌کنن — دکمه‌ها، پرداخت و پیگیری همیشه کار می‌کنن.
ریستِ روزانه نیمه‌شبِ وقتِ تهران (UTC+3:30). اعلانِ یک‌باره به مالک در ۸۰٪ و ۱۰۰٪ سقفِ کل.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Awaitable, Callable, Optional

from app.core.working_hours import _TEHRAN

SYS = "_sys"  # ردیف‌های داخلی (پرچمِ اعلان) در جدولِ usage؛ از شمارش‌ها مستثنا
DEFAULT_PER_CHAT = 200
DEFAULT_TOTAL = 2000


class UsageLimiter:
    def __init__(
        self,
        conv_store,
        get_settings: Callable[[], object],
        notify_owner: Optional[Callable[[str], Awaitable[object]]] = None,
        on_cap: Optional[Callable[[str], None]] = None,
        clock: Callable[[], float] = time.time,
    ):
        self._conv = conv_store
        self._get_settings = get_settings
        self._notify = notify_owner
        self._on_cap = on_cap  # صندوقِ «نیاز به توجه»
        self._clock = clock

    def _conn(self):
        return self._conv.connection()

    def today(self) -> str:
        return datetime.fromtimestamp(self._clock(), _TEHRAN).strftime("%Y-%m-%d")

    def _caps(self) -> tuple:
        s = self._get_settings()
        per_chat = getattr(s, "max_ai_messages_per_chat_per_day", DEFAULT_PER_CHAT)
        total = getattr(s, "max_ai_messages_per_day_total", DEFAULT_TOTAL)
        return int(per_chat if per_chat is not None else DEFAULT_PER_CHAT), int(total if total is not None else DEFAULT_TOTAL)

    # --------------------------------------------------------------- شمارش ----

    def chat_calls(self, platform: str, chat_id: str) -> int:
        row = self._conn().execute(
            "SELECT ai_calls FROM usage WHERE day=? AND platform=? AND chat_id=?", (self.today(), platform, str(chat_id))
        ).fetchone()
        return int(row["ai_calls"]) if row else 0

    def total_calls(self) -> int:
        row = self._conn().execute("SELECT COALESCE(SUM(ai_calls), 0) AS n FROM usage WHERE day=? AND platform != ?", (self.today(), SYS)).fetchone()
        return int(row["n"])

    def totals(self) -> dict:
        row = self._conn().execute(
            "SELECT COALESCE(SUM(ai_calls),0) AS calls, COALESCE(SUM(tokens_est),0) AS tokens, COUNT(*) AS chats "
            "FROM usage WHERE day=? AND platform != ?", (self.today(), SYS),
        ).fetchone()
        per_chat, total = self._caps()
        return {"ai_calls": int(row["calls"]), "tokens_est": int(row["tokens"]), "chats": int(row["chats"]), "cap_per_chat": per_chat, "cap_total": total}

    def check_ai(self, platform: str, chat_id: str) -> str:
        """``ok`` | ``kill`` | ``chat`` | ``total`` — ۰ یعنی «بدونِ سقف»."""
        if getattr(self._get_settings(), "ai_kill_switch", False):
            return "kill"
        per_chat, total = self._caps()
        if per_chat > 0 and self.chat_calls(platform, chat_id) >= per_chat:
            return "chat"
        if total > 0 and self.total_calls() >= total:
            return "total"
        return "ok"

    def record_ai(self, platform: str, chat_id: str, tokens_est: int = 0) -> None:
        conn = self._conn()
        conn.execute(
            "INSERT INTO usage (day, platform, chat_id, messages, ai_calls, tokens_est) VALUES (?, ?, ?, 1, 1, ?) "
            "ON CONFLICT(day, platform, chat_id) DO UPDATE SET messages=messages+1, ai_calls=ai_calls+1, tokens_est=tokens_est+excluded.tokens_est",
            (self.today(), platform, str(chat_id), max(0, int(tokens_est))),
        )
        conn.commit()
        conn.execute("DELETE FROM usage WHERE day < date(?, '-35 day')", (self.today(),))  # نگه‌داریِ محدود
        conn.commit()

    # ---------------------------------------------------------------- اعلان ----

    def _flag(self, name: str) -> bool:
        return self._conn().execute("SELECT 1 FROM usage WHERE day=? AND platform=? AND chat_id=?", (self.today(), SYS, name)).fetchone() is not None

    def _set_flag(self, name: str) -> None:
        conn = self._conn()
        conn.execute("INSERT OR IGNORE INTO usage (day, platform, chat_id, messages, ai_calls, tokens_est) VALUES (?, ?, ?, 1, 0, 0)", (self.today(), SYS, name))
        conn.commit()

    async def maybe_alert(self) -> None:
        """اعلانِ یک‌باره (در روز) به مالک در ۸۰٪ و ۱۰۰٪ سقفِ کل."""
        _per_chat, total = self._caps()
        if total <= 0 or self._notify is None:
            return
        used = self.total_calls()
        if used >= total and not self._flag("alert100"):
            self._set_flag("alert100")
            self._set_flag("alert80")
            if self._on_cap:
                self._on_cap("100")
            await self._notify(f"🛑 سقفِ روزانه‌ی پاسخ‌های هوشمند تموم شد ({used} از {total}). تا نیمه‌شب AI جواب نمی‌ده؛ دکمه‌ها، پرداخت و پیگیری کار می‌کنن. سقف رو می‌تونی از «تنظیمات ← مصرف و محدودیت» عوض کنی.")
        elif used * 5 >= total * 4 and not self._flag("alert80"):
            self._set_flag("alert80")
            if self._on_cap:
                self._on_cap("80")
            await self._notify(f"⚠️ ۸۰٪ سقفِ روزانه‌ی پاسخ‌های هوشمند مصرف شد ({used} از {total}).")
