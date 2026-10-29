"""صندوقِ «نیاز به توجه» (R10-۷): رویدادهایی که صاحب فروشگاه ممکنه وقتی برنامه بسته بوده از دست داده باشه
(پشتیبانیِ بدونِ مالکِ آنلاین، تحویلِ دیجیتالِ ناموفق، موجودیِ ناکافیِ بازیابی، رسیدنِ سقفِ AI، …). جدولِ ``attention_inbox``
در ``conversations.db``؛ نشانگرِ نوارِ کناری = ``count_open()`` (+ سفارش‌های منتظرِ تایید که جداگانه شمرده می‌شن).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

TYPES = ("support_no_owner", "delivery_failed", "inventory_short", "ai_cap", "payment_failed", "lead", "bio_confirm", "bio_too_long", "channel_check", "broadcast", "invoice_send", "low_stock", "other")
MAX_DETAIL = 300
MAX_OPEN = 200  # سقفِ ردیف‌های باز (جلوگیری از رشدِ بی‌پایان)


@dataclass
class AttentionItem:
    id: int
    type: str
    ref: str
    detail: str
    created_ts: int
    handled: bool


class AttentionInbox:
    def __init__(self, conv_store, clock: Callable[[], float] = time.time):
        self._conv = conv_store
        self._clock = clock

    def _conn(self):
        return self._conv.connection()

    def add(self, type_: str, ref: str = "", detail: str = "") -> Optional[int]:
        """رویدادِ تکراریِ باز (همان نوع+ارجاع) دوباره ثبت نمی‌شه؛ شناسه‌ی ردیف رو برمی‌گردونه."""
        type_ = type_ if type_ in TYPES else "other"
        conn = self._conn()
        dup = conn.execute("SELECT id FROM attention_inbox WHERE type=? AND ref=? AND handled=0", (type_, str(ref))).fetchone()
        if dup:
            return dup["id"]
        if self.count_open() >= MAX_OPEN:
            return None
        cur = conn.execute(
            "INSERT INTO attention_inbox (type, ref, detail, created_ts) VALUES (?, ?, ?, ?)",
            (type_, str(ref)[:80], " ".join(str(detail).split())[:MAX_DETAIL], int(self._clock())),
        )
        conn.commit()
        return cur.lastrowid

    def list_open(self, limit: int = 100) -> list:
        rows = self._conn().execute("SELECT * FROM attention_inbox WHERE handled=0 ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        return [AttentionItem(r["id"], r["type"], r["ref"], r["detail"], r["created_ts"], bool(r["handled"])) for r in rows]

    def count_open(self) -> int:
        return int(self._conn().execute("SELECT COUNT(*) AS n FROM attention_inbox WHERE handled=0").fetchone()["n"])

    def handle(self, item_id: int) -> bool:
        conn = self._conn()
        cur = conn.execute("UPDATE attention_inbox SET handled=1 WHERE id=? AND handled=0", (int(item_id),))
        conn.commit()
        return cur.rowcount == 1

    def handle_ref(self, type_: str, ref: str) -> int:
        """وقتی مشکل حل شد (مثلاً تحویل با تلاشِ مجدد انجام شد) ردیفِ باز رو می‌بنده."""
        conn = self._conn()
        cur = conn.execute("UPDATE attention_inbox SET handled=1 WHERE type=? AND ref=? AND handled=0", (type_, str(ref)))
        conn.commit()
        return cur.rowcount

    def handle_all(self) -> int:
        conn = self._conn()
        cur = conn.execute("UPDATE attention_inbox SET handled=1 WHERE handled=0")
        conn.commit()
        return cur.rowcount

    def purge_handled(self, older_than_days: int = 30) -> int:
        conn = self._conn()
        cur = conn.execute("DELETE FROM attention_inbox WHERE handled=1 AND created_ts < ?", (int(self._clock()) - older_than_days * 86400,))
        conn.commit()
        return cur.rowcount
