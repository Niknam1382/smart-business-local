"""
تحویلِ خودکارِ محصولاتِ دیجیتال (R4): بعد از «تأییدِ سفارش» (دستی یا خودکار) و *بعد از اعمالِ موجودی* (saga).

- ``text``/``link``: پیامِ متنی (لینک هم دکمه‌ی URL می‌شه)؛ ``file``: فایلِ محلی؛ ``keys``: کلیدهایی که saga به همین
  سفارش اختصاص داده (تحویلِ دوباره = *همان* کلیدها، هرگز کلیدِ تازه مصرف نمی‌شه).
- idempotent با ``orders.delivered_ts``: فقط بعد از ارسالِ موفقِ *همه‌ی* پیام‌ها علامت می‌خوره؛ شکست ⇒ تلاشِ مجدد.
- محتوای تحویل (کلید/لینک) هرگز در تاریخچه‌ی گفتگو (و در نتیجه در پرامپتِ AI) ثبت نمی‌شه.
"""

from __future__ import annotations

import logging
import os
from typing import Awaitable, Callable, Optional

from app.core import shop_texts
from app.core.orders import STATUS_CONFIRMED, Order
from app.core.ui import Btn, UiMessage, safe_url

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 50 * 1024 * 1024  # سقفِ ارسالِ فایل برای ربات‌ها


class DeliveryService:
    def __init__(self, product_store, order_store, get_settings: Callable[[], object]):
        self._products = product_store
        self._orders = order_store
        self._get_settings = get_settings

    def _t(self, key: str, **params) -> str:
        settings = self._get_settings()
        return shop_texts.render(settings, key, shop_texts.resolve_lang(settings), **params)

    def build_messages(self, order: Order) -> list:
        keys_by_product: dict = {}
        for pid, secret in self._products.allocated_keys(order.id):
            keys_by_product.setdefault(pid, []).append(secret)
        out: list = []
        for item in order.items:
            product = self._products.get(item.product_id) if item.product_id is not None else None
            if product is None or product.delivery_kind == "none":
                continue
            head = self._t("deliver.item", name=item.product_name)
            kind, payload = product.delivery_kind, product.delivery_payload
            if kind == "keys":
                keys = keys_by_product.get(product.id, [])
                if keys:
                    out.append(UiMessage(head + "\n" + "\n".join(self._t("deliver.key", secret=k) for k in keys)))
            elif kind == "link" and payload:
                rows = [[Btn(item.product_name[:30], url=payload)]] if safe_url(payload) else []
                out.append(UiMessage(f"{head}\n{payload}", rows))
            elif kind == "text" and payload:
                out.append(UiMessage(f"{head}\n{payload}"))
            elif kind == "file" and payload:
                if not (os.path.isfile(payload) and os.path.getsize(payload) <= MAX_FILE_BYTES):
                    raise FileNotFoundError(f"فایلِ محصولِ «{item.product_name}» پیدا نشد یا بزرگ‌تر از ۵۰ مگابایته")
                out.append(UiMessage(head, document=payload))
        if out:
            out.insert(0, UiMessage(self._t("deliver.head", order_id=order.id)))
        return out

    async def deliver(self, order: Order, send_ui: Callable[[UiMessage], Awaitable[Optional[str]]]) -> str:
        """``delivered`` | ``nothing`` | ``failed:<دلیل>`` — idempotent و بدونِ exception."""
        fresh = self._orders.get(order.id)
        if fresh is None or fresh.status != STATUS_CONFIRMED or not fresh.inventory_applied or fresh.delivered_ts != 0:
            return "nothing"
        try:
            messages = self.build_messages(fresh)
        except Exception as exc:  # noqa: BLE001
            return f"failed:{exc}"
        if not messages:
            self._orders.mark_delivered(fresh.id)
            return "nothing"
        try:
            for message in messages:
                await send_ui(message)
        except Exception as exc:  # noqa: BLE001 — ربات خاموش/قطعی شبکه؛ بعداً دوباره تلاش می‌شه
            logger.warning("تحویلِ دیجیتالِ سفارش %s ناموفق بود: %s", fresh.id, exc)
            return f"failed:{exc}"
        self._orders.mark_delivered(fresh.id)
        return "delivered"
