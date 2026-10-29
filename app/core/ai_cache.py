"""کشِ پاسخِ یکسانِ AI (N18-۷) — **حساس‌ترین لایه**؛ پیش‌فرض خاموش (``token_opt_response_cache``).

* کلید = SHA-256 از **کلِ payloadِ نهایی** (پیام‌ها شاملِ پرامپتِ ساخته‌شده/تاریخچه، پارامترها، مدل، ارائه‌دهنده). فقط درخواستِ بایت‌به‌بایت
  یکسان هیت می‌شه؛ تغییرِ هر قیمت/موجودی/متن/پرامپت/زبان/مدل/تاریخچه خودبه‌خود کلید را عوض می‌کند. کشِ معنایی/فازی ممنوع.
* فقط حافظه (RAM)، LRU با سقفِ تعداد و حجم، TTL (پیش‌فرض ۶۰ دقیقه، حداکثر ۲۴ ساعت)، با ری‌استارت پاک.
* هرگز: پاسخِ ابزار/خطا/ناقص/فیلتر، نوبتِ دارای تاریخچه، پیامِ دارای داده‌ی شخصی (``is_cacheable``).
* کمربندوتسمه: ``invalidate_all()`` با هر تغییرِ محصول/سفارش/تنظیمات/متن‌ها (قلاب‌ها در ``install_hooks``).
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import OrderedDict
from typing import Optional

MAX_ITEMS = 200
MAX_BYTES = 512 * 1024
MAX_TTL_SECONDS = 24 * 3600
_PERSONAL = re.compile(r"\d{5,}|[\w.+-]+@[\w-]+\.[\w.]+|https?://", re.I)  # شماره/ایمیل/لینک ⇒ شخصی، کش نکن


def payload_key(payload: dict) -> str:
    """کلیدِ قطعی از کلِ payload (ترتیبِ کلیدها بی‌اثر؛ هر تفاوتِ محتوا ⇒ کلیدِ دیگر)."""
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_cacheable(payload: dict, history_len: int, user_message: str, tools: bool = False) -> bool:
    """فقط پرسشِ اولِ مکالمه (بدونِ تاریخچه و بدونِ ابزار) و بدونِ داده‌ی شخصی."""
    if tools or history_len > 0 or payload.get("tools"):
        return False
    return not _PERSONAL.search(user_message or "")


class ResponseCache:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._items: "OrderedDict[str, tuple]" = OrderedDict()  # key → (expires, text, tokens_saved)
        self._bytes = 0
        self.hits = self.misses = self.tokens_saved = 0

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            item = self._items.get(key)
            if item is None or item[0] <= self._clock():
                if item is not None:
                    self._drop(key)
                self.misses += 1
                return None
            self._items.move_to_end(key)
            self.hits += 1
            self.tokens_saved += item[2]
            return item[1]

    def put(self, key: str, text: str, ttl_seconds: float, tokens_saved: int = 0) -> bool:
        if not text or len(text) > 8000:
            return False
        ttl = max(1.0, min(float(ttl_seconds), MAX_TTL_SECONDS))
        with self._lock:
            if key in self._items:
                self._drop(key)
            self._items[key] = (self._clock() + ttl, text, max(0, int(tokens_saved)))
            self._bytes += len(text.encode("utf-8")) + 64
            while len(self._items) > MAX_ITEMS or self._bytes > MAX_BYTES:
                self._drop(next(iter(self._items)))
            return True

    def _drop(self, key: str) -> None:
        item = self._items.pop(key, None)
        if item is not None:
            self._bytes -= len(item[1].encode("utf-8")) + 64

    def invalidate_all(self) -> None:
        with self._lock:
            self._items.clear()
            self._bytes = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def stats(self) -> dict:
        with self._lock:
            return {"hits": self.hits, "misses": self.misses, "items": len(self._items), "tokens_saved": self.tokens_saved}


CACHE = ResponseCache()


def invalidate_all() -> None:
    CACHE.invalidate_all()


def install_hooks() -> None:
    """قلاب‌های ابطال (یک‌بار): هر متدِ نوشتنیِ محصول/سفارش/متن‌ها کش را خالی می‌کند. idempotent."""
    import functools

    from app.core import settings as settings_module
    from app.core import shop_texts
    from app.core.orders import OrderStore
    from app.core.products import ProductStore

    def wrap(owner, names: tuple) -> None:
        for name in names:
            fn = getattr(owner, name, None)
            if fn is None or getattr(fn, "_ai_cache_hook", False):
                continue

            @functools.wraps(fn)
            def inner(*a, __fn=fn, **kw):
                result = __fn(*a, **kw)
                invalidate_all()
                return result

            inner._ai_cache_hook = True  # type: ignore[attr-defined]
            setattr(owner, name, inner)

    wrap(ProductStore, ("add", "update", "set_active", "adjust_stock", "add_keys", "apply_order_stock"))
    wrap(OrderStore, ("create", "confirm", "mark_paid", "cancel", "reject", "replace_items", "expire_stale"))
    wrap(shop_texts, ("configure",))
    wrap(settings_module, ("save_settings", "reload_into"))
