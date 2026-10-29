"""سبدِ خرید و نشستِ چک‌اوتِ مشتری — روی همان ``orders.db`` (جدول‌های ``carts`` و ``checkout_sessions``).

سبد *رزرو نیست* (رزرو فقط با ساختنِ سفارش). تعدادها «مقصد» هستن (``set_qty``) نه افزایشی، تا دابل‌تپ
idempotent باشه. هر دو جدول ورودیِ نامطمئن نیستن؛ ولی ردیف‌های منقضی (TTL) پاک می‌شن.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Optional

CART_TTL_SECONDS = 7 * 24 * 3600
CHECKOUT_TTL_SECONDS = 3600
MAX_QTY_PER_LINE = 99
MAX_CART_LINES = 30


class CartStore:
    def __init__(self, order_store):
        self._orders = order_store

    def _conn(self):
        return self._orders.connection()

    def get(self, platform: str, chat_id: str, now: Optional[float] = None) -> list:
        """``[(product_id, quantity), ...]`` به ترتیبِ افزودن؛ ردیف‌های منقضی نادیده گرفته می‌شن."""
        cutoff = int((time.time() if now is None else now) - CART_TTL_SECONDS)
        rows = self._conn().execute(
            "SELECT product_id, quantity FROM carts WHERE platform=? AND chat_id=? AND updated_ts>? ORDER BY updated_ts, product_id",
            (platform, str(chat_id), cutoff),
        ).fetchall()
        return [(r["product_id"], r["quantity"]) for r in rows]

    def quantity(self, platform: str, chat_id: str, product_id: int) -> int:
        row = self._conn().execute(
            "SELECT quantity FROM carts WHERE platform=? AND chat_id=? AND product_id=?", (platform, str(chat_id), product_id)
        ).fetchone()
        return int(row["quantity"]) if row else 0

    def set_qty(self, platform: str, chat_id: str, product_id: int, quantity: int) -> int:
        """تعدادِ این محصول در سبد رو «روی ``quantity``» می‌ذاره (۰ = حذف)؛ idempotent. تعدادِ نهایی رو برمی‌گردونه."""
        quantity = max(0, min(int(quantity), MAX_QTY_PER_LINE))
        conn = self._conn()
        if quantity == 0:
            conn.execute("DELETE FROM carts WHERE platform=? AND chat_id=? AND product_id=?", (platform, str(chat_id), product_id))
        else:
            if self.quantity(platform, chat_id, product_id) == 0 and len(self.get(platform, chat_id)) >= MAX_CART_LINES:
                conn.commit()
                return 0
            conn.execute(
                "INSERT INTO carts (platform, chat_id, product_id, quantity, updated_ts) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(platform, chat_id, product_id) DO UPDATE SET quantity=excluded.quantity, updated_ts=excluded.updated_ts",
                (platform, str(chat_id), product_id, quantity, int(time.time())),
            )
        conn.commit()
        return quantity

    def clear(self, platform: str, chat_id: str) -> None:
        conn = self._conn()
        conn.execute("DELETE FROM carts WHERE platform=? AND chat_id=?", (platform, str(chat_id)))
        conn.commit()

    def count(self, platform: str, chat_id: str) -> int:
        return sum(q for _pid, q in self.get(platform, chat_id))

    def purge_expired(self, now: Optional[float] = None) -> int:
        conn = self._conn()
        cur = conn.execute("DELETE FROM carts WHERE updated_ts<=?", (int((time.time() if now is None else now) - CART_TTL_SECONDS),))
        conn.commit()
        return cur.rowcount


@dataclass
class CheckoutSession:
    step: str
    data: dict = field(default_factory=dict)
    expires_ts: int = 0


class CheckoutSessionStore:
    def __init__(self, order_store):
        self._orders = order_store

    def _conn(self):
        return self._orders.connection()

    def get(self, platform: str, chat_id: str, now: Optional[float] = None) -> Optional[CheckoutSession]:
        row = self._conn().execute(
            "SELECT step, data_json, expires_ts FROM checkout_sessions WHERE platform=? AND chat_id=?", (platform, str(chat_id))
        ).fetchone()
        if row is None:
            return None
        if row["expires_ts"] <= (time.time() if now is None else now):
            self.clear(platform, chat_id)
            return None
        try:
            data = json.loads(row["data_json"])
        except ValueError:
            data = {}
        return CheckoutSession(row["step"], data if isinstance(data, dict) else {}, row["expires_ts"])

    def put(self, platform: str, chat_id: str, step: str, data: dict, ttl: int = CHECKOUT_TTL_SECONDS) -> None:
        conn = self._conn()
        conn.execute(
            "INSERT INTO checkout_sessions (platform, chat_id, step, data_json, expires_ts) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(platform, chat_id) DO UPDATE SET step=excluded.step, data_json=excluded.data_json, expires_ts=excluded.expires_ts",
            (platform, str(chat_id), step, json.dumps(data, ensure_ascii=False), int(time.time() + ttl)),
        )
        conn.commit()

    def clear(self, platform: str, chat_id: str) -> None:
        conn = self._conn()
        conn.execute("DELETE FROM checkout_sessions WHERE platform=? AND chat_id=?", (platform, str(chat_id)))
        conn.commit()
