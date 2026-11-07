"""
حافظه‌ی پاسخِ مدل (قلم ۱۷ مستر‌پرامپت: «درخواست‌ها هر بار به مدل نروند»).

چرا لازم است: روی حالتِ محلی هر پیام یعنی چند ثانیه‌ی CPU/GPU روی رمِ خودِ فروشنده. خیلی
سؤال‌ها تکراری‌اند («ارسال چقدر طول می‌کشه؟»، «قیمت فلان کالا؟») و پاسخِ همان سؤال با همان
زمینه یکسان است. این حافظه آن پاسخ‌ها را برای چند دقیقه نگه می‌دارد تا هم دستگاهِ فروشنده
نفس بکشد و هم مشتری زودتر جواب بگیرد.

قراردادها:
* کلید = مدل + پرامپتِ سیستم + تاریخچه + پیامِ مشتری. پس با **هر** تغییرِ قیمت/موجودی
  (که در کاتالوگِ پرامپت است) یا سؤالِ تازه، کش خودبه‌خود بی‌اثر می‌شه — پاسخِ قدیمی هیچ‌وقت
  به مشتری داده نمی‌شه.
* فقط متنِ خالی‌ندار و بدونِ کارتِ محصول کش می‌شه (کارت‌ها دکمه و شناسه‌ی زنده دارند).
* سقفِ تعداد + حذفِ LRU؛ هیچ فایلی روی دیسک نوشته نمی‌شه (پاسخ‌ها در حافظه می‌مونند و با
  هر راه‌اندازیِ دوباره‌ی ربات پاک می‌شن).
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from typing import Hashable, Optional

MAX_ENTRIES = 200
DEFAULT_TTL_SECONDS = 900.0  # ۱۵ دقیقه


class AnswerCache:
    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS, max_entries: int = MAX_ENTRIES, clock=time.monotonic):
        self._ttl = max(0.0, float(ttl_seconds))
        self._max = max(1, int(max_entries))
        self._clock = clock
        self._entries: OrderedDict[Hashable, tuple[float, str]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    @property
    def enabled(self) -> bool:
        return self._ttl > 0

    def set_ttl(self, seconds: float) -> None:
        """سقفِ تازه از تنظیماتِ مالک؛ ۰ = خاموش (و هرچه در حافظه بود دور ریخته می‌شه)."""
        self._ttl = max(0.0, float(seconds or 0))
        if not self.enabled:
            self.clear()

    @staticmethod
    def key(model: str, system_prompt: str, history: list, user_text: str) -> str:
        digest = hashlib.sha256()
        for part in (model or "", system_prompt or "", user_text or ""):
            digest.update(part.encode("utf-8", "replace"))
            digest.update(b"\x00")
        for msg in history or []:
            role = getattr(msg, "role", "") or ""
            content = getattr(msg, "content", "") or ""
            digest.update(f"{role}\n{content}\n".encode("utf-8", "replace"))
        return digest.hexdigest()

    def get(self, key: str) -> Optional[str]:
        if not self.enabled:
            return None
        entry = self._entries.get(key)
        if entry is None:
            self.misses += 1
            return None
        stored_at, text = entry
        if self._clock() - stored_at > self._ttl:
            self._entries.pop(key, None)
            self.misses += 1
            return None
        self._entries.move_to_end(key)
        self.hits += 1
        return text

    def put(self, key: str, text: str) -> None:
        if not self.enabled or not text:
            return
        self._entries[key] = (self._clock(), text)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()

    def size(self) -> int:
        return len(self._entries)
