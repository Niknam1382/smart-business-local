"""نشانِ کوچکِ سازنده در بیوگرافیِ (About) رباتِ هر فروشنده (N17) — فقط همین یک جا، کاملاً شفاف.

تصمیمِ مالک: نه متنِ بزرگ در پیام‌ها، نه چیزی در سفارش/پرداخت/راهنما. فقط یک خطِ کوچکِ اعتبار «ساخته‌شده با کسب‌وکار
هوشمند · github.com/…» (از branding.py) که فروشنده *داخلِ برنامه* نمی‌تونه حذفش کنه ولی می‌تونه چیزِ دیگه‌ای کنارش بنویسه.

صداقت: در نرم‌افزارِ متن‌باز قفلِ ۱۰۰٪ ممکن نیست (فورکِ کد یا ویرایش با BotFather). این «الزامِ مجوز» نیست؛ فقط یک رفتارِ
شفافِ برنامه است که در UI، راهنما و README نوشته شده.

قواعدِ ایمنی:
* **متنِ موجودِ فروشنده هرگز بدونِ نمایش به او پاک یا کوتاه نمی‌شه.** بارِ اولِ اتصال اگه بیوگرافیِ فعلی غیرخالی بود،
  اول به فروشنده نشون داده می‌شه (``needs_confirm``) و فقط بعد از تأیید، خطِ اعتبار *به انتهایش اضافه* می‌شه.
* متنی که با خطِ اعتبار از ۱۲۰ کاراکتر بیشتر بشه کوتاه نمی‌شه؛ گزارشِ ``too_long`` می‌ده و چیزی نمی‌نویسه.
* تلگرام برای هر ``language_code`` توضیحِ جدا نگه می‌داره؛ پیش‌فرض + هر زبانِ دارای توضیحِ جدا همگام می‌شن.
* بله: ``setMyShortDescription`` در مستنداتِ بله تأیید نشده؛ برنامه موقعِ اجرا امتحان می‌کنه و اگه پشتیبانی نشد، «بیوگرافیِ
  پیشنهادی» با دکمه‌ی کپی نشون می‌ده (بدونِ خطا).
"""

from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass, field
from typing import Optional, Protocol

from app import branding

logger = logging.getLogger(__name__)

SHORT_MAX = 120  # سقفِ ``setMyShortDescription`` در Bot API (تلگرام)
DEFAULT_LANGS = ("", "fa", "en")  # "" = پیش‌فرض (برای زبان‌هایی که توضیحِ جدا ندارن)
_BIDI = set("\u200e\u200f\u061c\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")

STATUS_OK = "ok"  # همه‌چیز از قبل درست بود
STATUS_UPDATED = "updated"
STATUS_NEEDS_CONFIRM = "needs_confirm"
STATUS_TOO_LONG = "too_long"
STATUS_UNSUPPORTED = "unsupported"
STATUS_FLOOD = "flood"
STATUS_ERROR = "error"


class BioError(ValueError):
    pass


class BioTooLong(BioError):
    def __init__(self, over: int, limit: int):
        super().__init__(f"{over} واحد بیشتر از سقفِ {limit}")
        self.over = over
        self.limit = limit


class ProfileError(Exception):
    """خطای عمومیِ شبکه/API (نه پشتیبانی‌نشدن، نه flood)."""


class ProfileUnsupported(ProfileError):
    """پلتفرم این متد را ندارد (مثلاً ۴۰۴ در بله)."""


class ProfileFlood(ProfileError):
    def __init__(self, retry_after: float = 0.0):
        super().__init__(f"flood؛ {retry_after:g} ثانیه بعد دوباره")
        self.retry_after = retry_after


# ------------------------------------------------------------------ متن ----

def utf16_len(text: str) -> int:
    """طولِ محافظه‌کارانه (UTF-16) تا ایموجی‌ها کمتر از واقع شمرده نشن."""
    return len(text.encode("utf-16-le")) // 2


def clean(text: Optional[str]) -> str:
    """متنِ فروشنده: NFC، بدونِ کاراکترِ کنترلی/bidi، خطوط به یک فاصله تبدیل می‌شن (نیم‌فاصله حفظ می‌شه)."""
    value = unicodedata.normalize("NFC", str(text or ""))
    value = "".join(" " if ch in "\n\r\t" else ch for ch in value)
    value = "".join(ch for ch in value if ch not in _BIDI and unicodedata.category(ch) != "Cc")
    return " ".join(value.split())


def credit(lang: str = "fa") -> str:
    return branding.credit_for(lang)


def known_credits() -> tuple:
    return (branding.CREDIT_FA, branding.CREDIT_EN)


def has_credit(text: Optional[str]) -> bool:
    value = clean(text)
    return any(value.endswith(c) for c in known_credits())


def strip_credit(text: Optional[str]) -> str:
    """متنِ فروشنده بدونِ خطِ اعتبار (و جداکننده‌اش). اگه خطِ اعتبار نداشته باشه همان متنِ تمیزشده."""
    value = clean(text)
    for c in known_credits():
        if value.endswith(c):
            value = value[: -len(c)].rstrip()
            sep = branding.CREDIT_SEPARATOR.strip()
            if sep and value.endswith(sep):
                value = value[: -len(sep)].rstrip()
            break
    return value


def seller_limit(lang: str = "fa") -> int:
    """حداکثرِ طولِ سهمِ فروشنده (UTF-16) کنارِ خطِ اعتبار."""
    return SHORT_MAX - utf16_len(credit(lang)) - utf16_len(branding.CREDIT_SEPARATOR)


def compose(seller_text: Optional[str], lang: str = "fa") -> str:
    """``متنِ فروشنده + " · " + اعتبار``؛ بدونِ متنِ فروشنده فقط خطِ اعتبار. بیشتر از ۱۲۰ ⇒ ``BioTooLong`` (هرگز کوتاه نمی‌شه)."""
    seller = strip_credit(seller_text)
    line = credit(lang)
    if not seller:
        return line
    text = seller + branding.CREDIT_SEPARATOR + line
    size = utf16_len(text)
    if size > SHORT_MAX:
        raise BioTooLong(size - SHORT_MAX, SHORT_MAX)
    return text


def counter(seller_text: Optional[str], lang: str = "fa") -> str:
    """شمارنده‌ی زنده‌ی ویرایشگر: «۲۳/۶۲» (ارقامِ لاتین)."""
    return f"{utf16_len(clean(seller_text))}/{seller_limit(lang)}"


def suggested_bio(seller_text: Optional[str], lang: str = "fa") -> str:
    """برای پلتفرمی که تنظیمِ خودکار نداره (بله): متنی که فروشنده خودش در BotFather بچسبونه. هرگز exception نمی‌ده؛
    اگه متن بلند باشه فقط خطِ اعتبار (و هشدار در UI) برمی‌گردونه."""
    try:
        return compose(seller_text, lang)
    except BioError:
        return credit(lang)


# --------------------------------------------------------------- همگام‌سازی ----

class ProfileClient(Protocol):
    async def get_short_description(self, language_code: str) -> str: ...

    async def set_short_description(self, text: str, language_code: str) -> None: ...


@dataclass
class SyncReport:
    status: str
    platform: str = ""
    updated: list = field(default_factory=list)  # کدِ زبان‌هایی که نوشته شدن ("" = پیش‌فرض)
    existing: dict = field(default_factory=dict)  # needs_confirm: {کدِ زبان: متنِ فعلیِ ربات}
    adopted_text: Optional[str] = None  # متنِ فروشنده‌ای که از ربات خوانده شد (برای ذخیره در تنظیمات)
    detail: str = ""
    over: int = 0

    @property
    def existing_default(self) -> str:
        return self.existing.get("", "")


def _credit_lang(code: str, default_lang: str) -> str:
    if code == "en":
        return "en"
    if code == "fa":
        return "fa"
    return "en" if default_lang == "en" else "fa"


async def sync_profile(
    client: ProfileClient,
    *,
    seller_text: str,
    confirmed: bool,
    default_lang: str = "fa",
    languages: tuple = DEFAULT_LANGS,
    platform: str = "",
) -> SyncReport:
    """بیوگرافیِ ربات را با خطِ اعتبار همگام می‌کنه (قواعدِ ایمنی در docstringِ ماژول). هرگز exception نمی‌ده."""
    seller_text = clean(seller_text)
    current: dict = {}
    try:
        for code in languages:
            current[code] = clean(await client.get_short_description(code))
    except ProfileUnsupported:
        return SyncReport(STATUS_UNSUPPORTED, platform)
    except ProfileFlood as exc:
        return SyncReport(STATUS_FLOOD, platform, detail=str(exc))
    except ProfileError as exc:
        return SyncReport(STATUS_ERROR, platform, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.debug("خواندنِ بیوگرافیِ ربات ناموفق", exc_info=True)
        return SyncReport(STATUS_ERROR, platform, detail=f"{type(exc).__name__}: {exc}")

    default_cur = current.get("", "")
    dedicated = {c: t for c, t in current.items() if c and t and t != default_cur}  # زبانِ دارای توضیحِ جدا
    unlabeled = {c: t for c, t in {"": default_cur, **dedicated}.items() if t and not has_credit(t)}
    if unlabeled and not seller_text and not confirmed:
        # متنِ موجودیِ فروشنده هست و هنوز ندیده؛ هیچ‌چیز نوشته نمی‌شه
        return SyncReport(STATUS_NEEDS_CONFIRM, platform, existing={c: t for c, t in {"": default_cur, **dedicated}.items() if t})

    plan: list = []
    problems: list = []
    over = 0
    adopted: Optional[str] = None

    # ---- پیش‌فرض
    lang0 = _credit_lang("", default_lang)
    try:
        if seller_text:
            desired = compose(seller_text, lang0)
        elif not default_cur:
            desired = credit(lang0)
        else:
            adopted = strip_credit(default_cur)
            desired = compose(adopted, lang0)
        if desired != default_cur:
            plan.append(("", desired))
    except BioTooLong as exc:
        problems.append("")
        over = max(over, exc.over)
        adopted = None

    # ---- زبان‌هایی که توضیحِ جدا دارن: فقط مطمئن می‌شیم خطِ اعتبار آخرشه؛ متنِ فروشنده دست‌نخورده
    for code, text in dedicated.items():
        lang_c = _credit_lang(code, default_lang)
        try:
            desired = compose(strip_credit(text), lang_c)
        except BioTooLong as exc:
            problems.append(code)
            over = max(over, exc.over)
            continue
        if desired != text:
            plan.append((code, desired))

    updated: list = []
    try:
        for code, text in plan:
            await client.set_short_description(text, code)
            updated.append(code)
    except ProfileUnsupported:
        return SyncReport(STATUS_UNSUPPORTED, platform, updated=updated)
    except ProfileFlood as exc:
        return SyncReport(STATUS_FLOOD, platform, updated=updated, detail=str(exc))
    except ProfileError as exc:
        return SyncReport(STATUS_ERROR, platform, updated=updated, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.debug("نوشتنِ بیوگرافیِ ربات ناموفق", exc_info=True)
        return SyncReport(STATUS_ERROR, platform, updated=updated, detail=f"{type(exc).__name__}: {exc}")

    if problems:
        return SyncReport(STATUS_TOO_LONG, platform, updated=updated, detail=",".join(c or "default" for c in problems), over=over)
    return SyncReport(STATUS_UPDATED if updated else STATUS_OK, platform, updated=updated, adopted_text=adopted)


# ------------------------------------------------------------- کلاینت‌ها ----

class TelegramProfileClient:
    """روی ``aiogram.Bot`` (``get/set_my_short_description``، تأییدشده با aiogram 3.31)."""

    def __init__(self, bot, timeout: int = 15):
        self._bot = bot
        self._timeout = timeout

    async def get_short_description(self, language_code: str) -> str:
        from aiogram.exceptions import AiogramError, TelegramRetryAfter

        try:
            result = await self._bot.get_my_short_description(language_code=language_code or None, request_timeout=self._timeout)
        except TelegramRetryAfter as exc:
            raise ProfileFlood(float(getattr(exc, "retry_after", 0) or 0)) from exc
        except AiogramError as exc:
            raise ProfileError(f"{type(exc).__name__}: {exc}") from exc
        return str(getattr(result, "short_description", "") or "")

    async def set_short_description(self, text: str, language_code: str) -> None:
        from aiogram.exceptions import AiogramError, TelegramRetryAfter

        try:
            await self._bot.set_my_short_description(short_description=text, language_code=language_code or None, request_timeout=self._timeout)
        except TelegramRetryAfter as exc:
            raise ProfileFlood(float(getattr(exc, "retry_after", 0) or 0)) from exc
        except AiogramError as exc:
            raise ProfileError(f"{type(exc).__name__}: {exc}") from exc


_UNSUPPORTED_CODES = {404, 405, 501}


class BaleProfileClient:
    """روی ``BaleClient``؛ بله زبان‌های جدا ندارد (فقط پیش‌فرض) و پشتیبانی‌اش تأیید نشده ⇒ ۴۰۴ = ``ProfileUnsupported``."""

    def __init__(self, client):
        self._client = client

    @staticmethod
    def _convert(exc) -> ProfileError:
        code = getattr(exc, "error_code", None)
        message = str(exc).lower()
        if code in _UNSUPPORTED_CODES or "method not found" in message or "unknown method" in message or "not found" in message:
            return ProfileUnsupported(str(exc))
        if code == 429:
            return ProfileFlood(0.0)
        return ProfileError(str(exc))

    async def get_short_description(self, language_code: str) -> str:
        from app.core.bale_client import BaleApiError

        try:
            return await self._client.get_my_short_description()
        except BaleApiError as exc:
            raise self._convert(exc) from exc

    async def set_short_description(self, text: str, language_code: str) -> None:
        from app.core.bale_client import BaleApiError

        try:
            await self._client.set_my_short_description(text)
        except BaleApiError as exc:
            raise self._convert(exc) from exc
