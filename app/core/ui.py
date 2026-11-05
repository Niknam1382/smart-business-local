"""
مدلِ رابطِ مستقل از پلتفرم برای فروشگاهِ دکمه‌ای (R1): دکمه، پیام، نتیجه‌ی جریان، و تحویل.

``ShopFlow`` فقط ``FlowResult`` (لیستی از ``UiMessage``) برمی‌گردونه؛ آداپتورهای تلگرام/بله یه «Transport» با
چهار عملِ پایه پیاده‌سازی می‌کنن و ``deliver`` ترتیبِ ارسال/ویرایش/پاسخ به callback و fallbackها رو یک‌جا انجام می‌ده.
همین مدل برای «پیش‌نمایشِ مشتری» داخلِ برنامه هم استفاده می‌شه (بدونِ شبکه).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

CALLBACK_DATA_MAX_BYTES = 64  # محدودیتِ تلگرام و بله
_SAFE_URL = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)


@dataclass(frozen=True)
class Btn:
    """یک دکمه‌ی شیشه‌ای: یا ``data`` (callback) یا ``url``."""

    label: str
    data: str = ""
    url: str = ""

    def __post_init__(self) -> None:
        if self.data and len(self.data.encode("utf-8")) > CALLBACK_DATA_MAX_BYTES:
            raise ValueError(f"callback_data بیشتر از {CALLBACK_DATA_MAX_BYTES} بایت: {self.data!r}")


@dataclass
class UiMessage:
    text: str = ""
    rows: list = field(default_factory=list)  # list[list[Btn]] — کیبوردِ شیشه‌ای
    photo: str = ""  # مسیرِ فایلِ محلی یا URL
    edit: bool = False  # پیامِ مبدأِ callback رو ویرایش کن (نه پیامِ جدید)
    keyboard_only: bool = False  # فقط کیبوردِ شیشه‌ای رو ویرایش کن (مثلِ تغییرِ تعداد)
    menu: Optional[list] = None  # کیبوردِ پایدارِ پایینِ چت: list[list[str]]
    request_contact: str = ""  # برچسبِ دکمه‌ی «اشتراکِ شماره‌ام» (فقط تلگرام)
    remove_menu: bool = False
    document: str = ""  # مسیرِ فایلِ محلی (تحویلِ دیجیتال)
    contact: Optional[tuple] = None  # (شماره, نام) → sendContact (کارتِ تماس)
    log: bool = False  # در تاریخچه‌ی گفتگو برای مالک ثبت بشه؟ (فقط پیام‌های مهم: سفارش/پرداخت/تحویل)


@dataclass
class FlowResult:
    messages: list = field(default_factory=list)  # list[UiMessage]
    answer: str = ""  # متنِ کوتاهِ answerCallbackQuery
    alert: bool = False
    consumed: bool = True  # False = این پیام مالِ جریان نبود؛ بده به AI
    ai_text: str = ""  # اگه پر باشه، به‌جای متنِ مشتری این برای AI فرستاده می‌شه (دکمه‌ی «ask_ai»)


def safe_url(url: str) -> bool:
    """فقط http(s) — ``tel:``/``javascript:`` و … هرگز دکمه‌ی URL نمی‌شن (تلگرام کلِ پیام رو رد می‌کنه)."""
    return bool(url) and bool(_SAFE_URL.match(url.strip()))


def plain_text(msg: UiMessage) -> str:
    """نسخه‌ی متنیِ یه پیام (fallbackِ بدونِ دکمه): لینک‌های URL داخلِ متن می‌مونن تا چیزی گم نشه."""
    lines = [msg.text] if msg.text else []
    for row in msg.rows:
        for btn in row:
            if btn.url:
                lines.append(f"{btn.label}: {btn.url}")
    return "\n".join(lines).strip()


class Transport:
    """قراردادِ آداپتورها. هر متد باید خطاهای پلتفرم رو خودش مدیریت کنه (False/None برگردونه، نه exception)."""

    async def send_ui(self, chat_id: str, msg: UiMessage) -> Optional[str]:  # pragma: no cover - interface
        raise NotImplementedError

    async def edit_ui(self, chat_id: str, message_id: str, msg: UiMessage) -> bool:  # pragma: no cover
        raise NotImplementedError

    async def delete_message(self, chat_id: str, message_id: str) -> None:  # pragma: no cover
        raise NotImplementedError

    async def answer_callback(self, callback_id: str, text: str = "", alert: bool = False) -> None:  # pragma: no cover
        raise NotImplementedError


async def deliver(
    transport: Transport,
    chat_id: str,
    result: FlowResult,
    *,
    callback_id: str = "",
    source_message_id: str = "",
) -> list:
    """نتیجه‌ی جریان رو می‌فرسته: اول پاسخ به callback (spinner قطع بشه)، بعد هر پیام با ویرایش/ارسال.
    ویرایشِ ناموفق (مثلاً متن→عکس) = حذفِ پیامِ قبلی + ارسالِ پیامِ تازه. لیستِ شناسه‌ی پیام‌های ارسالی رو برمی‌گردونه."""
    if callback_id:
        try:
            await transport.answer_callback(callback_id, result.answer, result.alert)
        except Exception:  # noqa: BLE001
            logger.warning("answerCallbackQuery ناموفق بود", exc_info=True)
    sent: list = []
    editable = source_message_id
    for msg in result.messages:
        try:
            if msg.edit and editable:
                if await transport.edit_ui(chat_id, editable, msg):
                    editable = ""  # فقط اولین پیام جای پیامِ مبدأ می‌شینه
                    continue
                await transport.delete_message(chat_id, editable)
                editable = ""
            message_id = await transport.send_ui(chat_id, msg)
            if message_id:
                sent.append(message_id)
        except Exception:  # noqa: BLE001 — خرابیِ یه پیام نباید بقیه رو متوقف کنه
            logger.exception("ارسالِ یه پیامِ رابط ناموفق بود")
    return sent


class SendOnlyTransport(Transport):
    """وقتی آداپتور فقط تابعِ ساده‌ی ``send(text, buttons=...)`` داره (تست‌ها/حالتِ قدیمی): دکمه‌های callback
    حذف می‌شن و فقط متن (و لینک‌ها) فرستاده می‌شه."""

    def __init__(self, send):
        self._send = send

    async def send_ui(self, chat_id: str, msg: UiMessage) -> Optional[str]:
        text = plain_text(msg)
        if text:
            await self._send(text)
        return None

    async def edit_ui(self, chat_id: str, message_id: str, msg: UiMessage) -> bool:
        return False

    async def delete_message(self, chat_id: str, message_id: str) -> None:
        return None

    async def answer_callback(self, callback_id: str, text: str = "", alert: bool = False) -> None:
        return None
