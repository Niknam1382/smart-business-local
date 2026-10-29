"""ساعتِ کاریِ فروشگاه (R5): اعتبارسنجی + «الان باز هستیم؟». فقط برای پیامِ مناسبِ پشتیبانی استفاده می‌شه؛ فروش ۲۴ ساعته‌ست.

شکلِ تنظیمات: ``{"enabled": true, "tz": "Asia/Tehran", "days": {"sat": ["09:00-17:00"], ...}, "message": "..."}``
(کلیدِ روزها: mon..sun). منطقه‌ی زمانیِ تهران بدونِ نیاز به ``tzdata`` (ویندوز) پشتیبانی می‌شه: ایران از ۱۴۰۱ ساعتِ تابستانی نداره (UTC+3:30).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_INTERVAL = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)$")
_TEHRAN = timezone(timedelta(hours=3, minutes=30), "Asia/Tehran")


def validate(raw) -> Optional[str]:
    if not raw:
        return None
    if not isinstance(raw, dict):
        return "ساعتِ کاری نامعتبره."
    days = raw.get("days", {})
    if not isinstance(days, dict) or any(k not in DAYS for k in days):
        return "روزها باید از mon/tue/wed/thu/fri/sat/sun باشن."
    for intervals in days.values():
        if not isinstance(intervals, list) or len(intervals) > 4:
            return "هر روز حداکثر ۴ بازه داره."
        for item in intervals:
            if not isinstance(item, str) or not _INTERVAL.match(item):
                return "بازه‌ها باید مثلِ 09:00-17:00 باشن."
    if len(str(raw.get("message", ""))) > 500:
        return "پیامِ خارج از ساعتِ کاری خیلی بلنده."
    return None


def _tz(name: str):
    if name in ("Asia/Tehran", "", None):
        return _TEHRAN
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 — tzdata نصب نیست یا نام نامعتبره
        return _TEHRAN


def now_local(raw: Optional[dict], now: Optional[datetime] = None) -> datetime:
    base = now if now is not None else datetime.now(timezone.utc)
    return base.astimezone(_tz((raw or {}).get("tz", "Asia/Tehran")))


def is_open(raw: Optional[dict], now: Optional[datetime] = None) -> bool:
    """غیرفعال/نامعتبر/بدونِ بازه ⇒ همیشه «باز»."""
    if not raw or not raw.get("enabled") or validate(raw) is not None:
        return True
    local = now_local(raw, now)
    intervals = (raw.get("days") or {}).get(DAYS[local.weekday()], [])
    if not intervals:
        return False
    current = local.strftime("%H:%M")
    for item in intervals:
        start, end = item.split("-")
        if (start <= current < end) if start < end else (current >= start or current < end):
            return True
    return False
