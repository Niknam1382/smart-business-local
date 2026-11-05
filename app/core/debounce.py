"""
ادغام پیام‌های پشت‌سرهم یک کاربر در یک پیام واحد، قبل از فرستادن به AI.

الگو (طبق تصمیم گرفته‌شده در MASTER_PROMPT، پورت‌شده از نسخه‌ی SaaS ابری
«کسب‌وکار هوشمند»): وقتی مشتری توی تلگرام/بله چند پیام کوتاه پشت‌سرهم
می‌فرسته (مثلاً «سلام» و بعد یک ثانیه بعد «قیمت گوشی X چنده؟»)، به‌جای پاسخ
جدا به هر پیام:

- اگه ۳ ثانیه (`wait_seconds`) از آخرین پیام کاربر سکوت بشه → همه‌ی پیام‌های
  جمع‌شده با هم (merge) به AI فرستاده می‌شن.
- ولی اگه کاربر بی‌وقفه پیام بده، بیشتر از ۱۰ ثانیه (`max_wait_seconds`) از
  اولین پیامِ این دسته صبر نمی‌کنیم — تا مشتری خیلی طولانی معطل جواب نمونه.

هر کلید (معمولاً (platform, chat_id)) بافر و تایمر جدای خودش رو داره، پس
مکالمه‌های همزمانِ چند مشتری با هم تداخل نمی‌کنن.

این کلاس فقط منطق ادغامه و به تلگرام/بله/AI هیچ وابستگی‌ای نداره — برای
همین می‌شه کاملاً جدا و بدون شبکه تستش کرد.
"""

from __future__ import annotations

import asyncio
import time
import traceback
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Hashable, Optional

OnFlush = Callable[[Hashable, str], Awaitable[None]]


@dataclass
class _PendingBuffer:
    parts: list[str] = field(default_factory=list)
    first_message_at: float = 0.0
    task: Optional[asyncio.Task] = None


class Debouncer:
    def __init__(
        self,
        on_flush: OnFlush,
        wait_seconds: float = 3.0,
        max_wait_seconds: float = 10.0,
    ):
        if wait_seconds <= 0 or max_wait_seconds <= 0:
            raise ValueError("wait_seconds و max_wait_seconds باید مثبت باشن")
        if max_wait_seconds < wait_seconds:
            raise ValueError("max_wait_seconds باید >= wait_seconds باشه")
        self._on_flush = on_flush
        self._wait_seconds = wait_seconds
        self._max_wait_seconds = max_wait_seconds
        self._buffers: dict[Hashable, _PendingBuffer] = {}

    def feed(self, key: Hashable, text: str) -> None:
        """یه پیام‌ی جدید رو برای این کلید به بافر اضافه می‌کنه و زمان‌بندی
        flush رو ریست می‌کنه. باید از داخل event loop صدا زده بشه."""
        now = time.monotonic()
        buf = self._buffers.get(key)
        if buf is None:
            buf = _PendingBuffer(first_message_at=now)
            self._buffers[key] = buf
        buf.parts.append(text)

        if buf.task is not None:
            buf.task.cancel()

        remaining_until_cap = (buf.first_message_at + self._max_wait_seconds) - now
        delay = min(self._wait_seconds, max(remaining_until_cap, 0.0))
        buf.task = asyncio.create_task(self._schedule_flush(key, delay))

    async def _schedule_flush(self, key: Hashable, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        await self._flush(key)

    async def _flush(self, key: Hashable) -> None:
        buf = self._buffers.pop(key, None)
        if buf is None or not buf.parts:
            return
        merged = "\n".join(buf.parts)
        try:
            await self._on_flush(key, merged)
        except Exception:
            # یه خطا توی پردازش یه مکالمه نباید کل ربات یا مکالمه‌های دیگه
            # رو متوقف کنه. لاگ دقیق‌تر (با زبان/جزئیات کاربر) وظیفه‌ی
            # adapter صدازننده‌ست.
            traceback.print_exc()

    def pending_count(self) -> int:
        return len(self._buffers)

    def is_pending(self, key: Hashable) -> bool:
        return key in self._buffers

    async def flush_now(self, key: Hashable) -> None:
        """برای shutdown تمیز: هر چیزی که توی بافره رو فوراً flush می‌کنه."""
        buf = self._buffers.get(key)
        if buf is not None and buf.task is not None:
            buf.task.cancel()
        await self._flush(key)

    def cancel(self, key: Hashable) -> bool:
        """بافرِ این کلید رو بدونِ flush دور می‌ریزه (مثلاً /forget). ``True`` اگه چیزی در انتظار بود."""
        buf = self._buffers.pop(key, None)
        if buf is None:
            return False
        if buf.task is not None:
            buf.task.cancel()
        return True

    async def cancel_all(self) -> None:
        """برای توقف کامل ربات: بدون flush، همه‌ی تایمرهای در انتظار رو لغو می‌کنه."""
        for buf in self._buffers.values():
            if buf.task is not None:
                buf.task.cancel()
        self._buffers.clear()
