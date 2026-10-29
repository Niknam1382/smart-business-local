"""بخش‌های مشترک آداپتورهای تلگرام و بله: مدل وضعیت + انتظار قابل‌لغو."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Optional

STATE_STOPPED = "stopped"
STATE_CONNECTING = "connecting"  # در حال اتصال یا تلاش دوباره بعد از قطعی (خطای گذرا)
STATE_CONNECTED = "connected"
STATE_ERROR = "error"  # خطای غیرقابل‌جبران بدون دخالت کاربر (مثلاً توکن نامعتبر)

# کد خطا: UI با این کد پیام دوزبانه‌ی مناسب رو انتخاب می‌کنه (متن فارسیِ
# ``error`` فقط پشتیبانِ لاگ و نمایش پیش‌فرضه).
ERR_INVALID_TOKEN = "invalid_token"
ERR_CONFLICT = "conflict"
ERR_WEBHOOK = "webhook"
ERR_BAD_PROXY = "bad_proxy"
ERR_NO_CONNECTION = "no_connection"
ERR_UNEXPECTED = "unexpected"

STOPPED = object()  # نتیجه‌ی run_until_stop وقتی توقف قبل از تموم‌شدن کار رسیده


@dataclass
class AdapterStatus:
    state: str = STATE_STOPPED
    username: Optional[str] = None
    error: Optional[str] = None  # پیام فارسی و قابل‌فهم برای کاربر غیرفنی
    error_code: Optional[str] = None  # یکی از ERR_* بالا

    @property
    def connected(self) -> bool:
        return self.state == STATE_CONNECTED


async def wait_or_stop(stop_event: asyncio.Event, seconds: float) -> bool:
    """تا ``seconds`` صبر می‌کنه؛ اگه وسطش درخواست توقف اومد فوراً True برمی‌گردونه."""
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
        return True
    except asyncio.TimeoutError:
        return False


async def run_until_stop(awaitable: Awaitable, stop_event: asyncio.Event) -> Any:
    """نتیجه‌ی ``awaitable`` رو برمی‌گردونه؛ اگه قبل از تموم‌شدنش ``stop_event`` ست
    بشه، ``awaitable`` لغو می‌شه و ``STOPPED`` برمی‌گرده. خطای خودِ ``awaitable``
    مستقیم به صدازننده می‌رسه.

    چرا لازمه: یه درخواست شبکه (به‌خصوص وقتی اینترنت/پروکسی «بی‌صدا» بسته باشه)
    می‌تونه ده‌ها ثانیه معطل بمونه؛ بدون این، دکمه‌ی «توقف» توی UI همون‌قدر
    پاسخ نمی‌داد."""
    task = asyncio.ensure_future(awaitable)
    stopper = asyncio.ensure_future(stop_event.wait())
    try:
        done, _ = await asyncio.wait({task, stopper}, return_when=asyncio.FIRST_COMPLETED)
    except asyncio.CancelledError:
        task.cancel()
        stopper.cancel()
        raise
    if task in done:  # اگه هر دو هم‌زمان تموم شدن، نتیجه‌ی واقعی ارجحه
        stopper.cancel()
        return task.result()
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass
    return STOPPED


# ---------------------------------------------------- پیام‌های غیرمتنی (رسید، عکس، فایل)

# (نام فیلد در پیام، توضیحِ فارسی). مشتریِ فروشگاه بعد از کارت‌به‌کارت تقریباً همیشه «عکسِ رسید»
# می‌فرسته؛ نادیده‌گرفتنِ بی‌صداش یعنی مشتری فکر می‌کنه پرداختش ثبت شده. پس به‌جای رد‌کردن،
# یه یادداشتِ متنی به مدل می‌دیم تا بتونه درست جواب بده (محتوای عکس رو نمی‌خونیم).
MEDIA_KINDS = (
    ("photo", "عکس"),
    ("document", "فایل"),
    ("voice", "پیام صوتی"),
    ("audio", "فایل صوتی"),
    ("video", "ویدیو"),
    ("video_note", "ویدیو"),
)


def with_media_note(text: str, media_label: str) -> str:
    """``text`` (متن یا کپشن، ممکنه خالی باشه) + یادداشتِ «مشتری فلان چیز رو فرستاد». اگه
    ``media_label`` خالی باشه، همون متن برمی‌گرده."""
    if not media_label:
        return text or ""
    note = f"[پیوست: {media_label} — محتوای فایل برای من قابل‌خوندن نیست]"
    return f"{text}\n{note}".strip() if text else note


def normalize_member_status(status, is_member=None) -> str:
    """وضعیتِ عضویتِ کاربر در کانال (N13) به شکلِ استاندارد: creator / administrator / member / left / kicked.
    ``restricted`` (محدودشده) اگه هنوز عضو باشه ``member`` و وگرنه ``left`` حساب می‌شه."""
    text = str(getattr(status, "value", status) or "").strip().lower()
    if text == "restricted":
        return "member" if is_member else "left"
    return text


_UNREACHABLE_MARKERS = ("bot was blocked by the user", "user is deactivated", "chat not found", "forbidden: bot", "403 forbidden", "blocked by the user")


def looks_unreachable(exc: BaseException) -> bool:
    """آیا خطای ارسال یعنی «مشتری دیگه قابلِ پیام‌دادن نیست»؟ (تلگرام: Forbidden/bot was blocked؛ بله: ۴۰۳). خطای شبکه نه."""
    if type(exc).__name__ == "TelegramForbiddenError":
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _UNREACHABLE_MARKERS)
