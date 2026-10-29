"""N13 — عضویتِ اجباریِ کانال (تلگرام و بله). منطقِ خالص: بدونِ flet/aiogram؛ بررسیِ واقعی را ``checker`` تزریق‌شده انجام می‌ده.

قراردادها:
* عضو = ``creator`` / ``administrator`` / ``member``؛ ``left`` / ``kicked`` = عضو نیست؛ هر چیزِ دیگر یا هر خطا = «بررسی خراب» ← **fail-open**
  (تنظیمِ اشتباه، مثلاً ربات ادمینِ کانال نیست، هرگز مشتری را قفل نمی‌کنه) + هشدارِ یک‌باره برای هر خرابی (تا بررسیِ سالمِ بعدی).
* کش: «عضو» ۱۰ دقیقه؛ «بررسی خراب» ۱ دقیقه (به API خراب فشار نیاد)؛ «عضو نیست» فقط چند ثانیه (جذبِ انفجارِ پیام‌ها).
  ``force=True`` (دکمه‌ی «عضو شدم» و ``/start``) کش را دور می‌زنه.
* کش به مجموعه‌ی کانال‌ها وابسته است؛ با تغییرِ کانال‌ها خودبه‌خود بی‌اعتبار می‌شه.
"""

from __future__ import annotations

import inspect
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from app.core.ui import safe_url

logger = logging.getLogger(__name__)

PLATFORMS = ("telegram", "bale")
SCOPE_SHOP, SCOPE_AI, SCOPE_BOTH = "shop", "ai", "both"
SCOPES = (SCOPE_SHOP, SCOPE_AI, SCOPE_BOTH)
POINT_SHOP, POINT_AI = SCOPE_SHOP, SCOPE_AI  # نقطه‌ی بررسی در پایپ‌لاین

MAX_CHANNELS = 10
MAX_TITLE = 40
MAX_LINK = 300
CACHE_TTL_SECONDS = 600.0
ERROR_TTL_SECONDS = 60.0
MISS_TTL_SECONDS = 5.0
MAX_CACHE_ENTRIES = 5000

MEMBER_STATUSES = frozenset({"creator", "administrator", "member"})
NOT_MEMBER_STATUSES = frozenset({"left", "kicked"})

JOINED_CALLBACK = "c:joined"  # callback_data دکمه‌ی «عضو شدم» (≤ ۶۴ بایت؛ الگوی c:<فعل>)

_USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
_NUMERIC = re.compile(r"^-?\d{5,20}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_LINK_REF = re.compile(
    r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|ble\.ir|bale\.ai)/@?([A-Za-z][A-Za-z0-9_]{4,31})/?(?:\?.*)?$", re.IGNORECASE
)
_AUTO_LINK = {"telegram": "https://t.me/{u}", "bale": "https://ble.ir/{u}"}


class ChannelError(ValueError):
    """پیامِ فارسیِ قابل‌نمایش به مالک."""


@dataclass(frozen=True)
class Channel:
    platform: str
    channel: str  # «@username» یا شناسه‌ی عددی
    title: str = ""
    link: str = ""

    @property
    def ref(self) -> str:
        return f"{self.platform}:{self.channel}"

    @property
    def label(self) -> str:
        return self.title or (self.channel if self.channel.startswith("@") else "کانال")

    def as_dict(self) -> dict:
        return {"platform": self.platform, "channel": self.channel, "title": self.title, "link": self.link}


def _clean(text, limit: int) -> str:
    return " ".join(_CONTROL.sub(" ", str(text or "")).split())[:limit]


def parse_channel_ref(raw) -> str:
    """«@name» / «name» / لینکِ عمومی (t.me/…، ble.ir/…) / شناسه‌ی عددی ← شکلِ استاندارد. لینکِ دعوتِ خصوصی قابلِ‌تبدیل نیست."""
    text = _CONTROL.sub("", str(raw or "")).strip()
    if not text:
        raise ChannelError("نامِ کانال را بنویس (مثلاً @mychannel).")
    if "/+" in text or "joinchat" in text.lower():
        raise ChannelError("از لینکِ دعوتِ خصوصی نمی‌شه کانال را شناخت؛ شناسه‌ی عددیِ کانال را بنویس و لینکِ دعوت را در خانه‌ی «لینک» بگذار.")
    match = _LINK_REF.match(text)
    if match:
        return "@" + match.group(1)
    bare = text[1:] if text.startswith("@") else text
    if _USERNAME.match(bare):
        return "@" + bare
    if _NUMERIC.match(text):
        return text
    raise ChannelError("نامِ کانال معتبر نیست؛ مثلِ @mychannel، لینکِ عمومیِ کانال یا شناسه‌ی عددی بنویس.")


def normalize(raw: dict) -> Channel:
    """یک ورودیِ خام (از UI/تنظیمات) ← ``Channel`` معتبر یا ``ChannelError``."""
    if not isinstance(raw, dict):
        raise ChannelError("ورودیِ کانال معتبر نیست.")
    platform = str(raw.get("platform") or "").strip().lower()
    if platform not in PLATFORMS:
        raise ChannelError("پیام‌رسان باید تلگرام یا بله باشد.")
    channel = parse_channel_ref(raw.get("channel"))
    title = _clean(raw.get("title"), MAX_TITLE)
    link = _clean(raw.get("link"), MAX_LINK).replace(" ", "")
    if not link:
        if not channel.startswith("@"):
            raise ChannelError("برای کانالِ خصوصی (شناسه‌ی عددی) لینکِ دعوت لازمه تا مشتری بتونه عضو بشه.")
        link = _AUTO_LINK[platform].format(u=channel[1:])
    if not safe_url(link):
        raise ChannelError("لینکِ کانال باید با http:// یا https:// شروع بشه.")
    return Channel(platform=platform, channel=channel, title=title, link=link)


def validate_list(items) -> list:
    """فهرستِ خام ← فهرستِ دیکشنری‌های استاندارد (برای ذخیره)؛ تکراری حذف می‌شه؛ هر خطا ``ChannelError``."""
    out, seen = [], set()
    for item in items or []:
        ch = normalize(item)
        if ch.ref in seen:
            continue
        seen.add(ch.ref)
        out.append(ch.as_dict())
    if len(out) > MAX_CHANNELS:
        raise ChannelError(f"حداکثر {MAX_CHANNELS} کانال می‌شه گذاشت.")
    return out


def load(settings) -> list:
    """کانال‌های ذخیره‌شده؛ ردیفِ خراب (مثلاً فایلِ دست‌کاری‌شده) بی‌صدا نادیده گرفته می‌شه — هرگز exception نمی‌ده."""
    out, seen = [], set()
    for item in list(getattr(settings, "required_channels", None) or [])[: MAX_CHANNELS * 2]:
        try:
            ch = normalize(item)
        except ChannelError:
            logger.debug("کانالِ نامعتبر در تنظیمات نادیده گرفته شد", exc_info=True)
            continue
        if ch.ref not in seen:
            seen.add(ch.ref)
            out.append(ch)
    return out[:MAX_CHANNELS]


def scope_covers(settings, point: str) -> bool:
    scope = getattr(settings, "required_channels_scope", SCOPE_BOTH)
    scope = scope if scope in SCOPES else SCOPE_BOTH
    return scope == SCOPE_BOTH or scope == point


@dataclass
class Verdict:
    allowed: bool = True
    missing: list = field(default_factory=list)  # list[Channel] — کانال‌هایی که مشتری قطعاً عضوشان نیست
    degraded: bool = False  # حداقل یک بررسی خراب شد و fail-open اعمال شد

    @property
    def blocked(self) -> bool:
        return not self.allowed


@dataclass
class _Entry:
    sig: tuple
    verdict: Verdict
    expires: float


Checker = Callable[[str, str, str], Awaitable[str]]  # (platform, channel, user_id) → وضعیت؛ خطا = exception


async def _call(callback, *args) -> None:
    if callback is None:
        return
    try:
        result = callback(*args)
        if inspect.isawaitable(result):
            await result
    except Exception:  # noqa: BLE001 — خرابیِ هشدار هرگز نباید بررسی را خراب کنه
        logger.debug("callbackِ دروازه‌ی کانال ناموفق بود", exc_info=True)


class ChannelGate:
    def __init__(
        self,
        get_settings: Callable[[], object],
        checker: Checker,
        *,
        clock: Callable[[], float] = time.monotonic,
        on_error: Optional[Callable] = None,
        on_recovered: Optional[Callable] = None,
        ttl: float = CACHE_TTL_SECONDS,
        error_ttl: float = ERROR_TTL_SECONDS,
        miss_ttl: float = MISS_TTL_SECONDS,
    ):
        self._get_settings = get_settings
        self._checker = checker
        self._clock = clock
        self._on_error = on_error
        self._on_recovered = on_recovered
        self._ttl, self._error_ttl, self._miss_ttl = ttl, error_ttl, miss_ttl
        self._cache: dict = {}
        self._alerted: set = set()

    # ------------------------------------------------------------------ پیکربندی ----

    def channels(self, platform: str) -> list:
        settings = self._get_settings()
        if not getattr(settings, "required_channels_enabled", False):
            return []
        return [c for c in load(settings) if c.platform == platform]

    def enabled_for(self, platform: str, point: str) -> bool:
        """آیا برای این پلتفرم و این نقطه (shop | ai) باید عضویت بررسی بشه؟"""
        return bool(self.channels(platform)) and scope_covers(self._get_settings(), point)

    def clear_cache(self) -> None:
        self._cache.clear()

    # --------------------------------------------------------------------- بررسی ----

    async def check(self, platform: str, user_id: str, *, force: bool = False) -> Verdict:
        chans = self.channels(platform)
        if not chans:
            return Verdict(True)
        sig = tuple(c.ref for c in chans)
        key = (platform, str(user_id))
        now = self._clock()
        if not force:
            entry = self._cache.get(key)
            if entry is not None and entry.sig == sig and now < entry.expires:
                return entry.verdict
        missing, degraded = [], False
        for ch in chans:
            try:
                status = str(await self._checker(platform, ch.channel, str(user_id)) or "").strip().lower()
            except Exception as exc:  # noqa: BLE001 — هر خطا = fail-open
                degraded = True
                await self._report(ch, exc)
                continue
            if status in MEMBER_STATUSES:
                await self._recovered(ch)
            elif status in NOT_MEMBER_STATUSES:
                await self._recovered(ch)
                missing.append(ch)
            else:
                degraded = True
                await self._report(ch, ValueError(f"وضعیتِ نامعلوم از پلتفرم: {status or '—'}"))
        verdict = Verdict(allowed=not missing, missing=missing, degraded=degraded)
        ttl = self._miss_ttl if missing else (self._error_ttl if degraded else self._ttl)
        self._cache[key] = _Entry(sig, verdict, now + ttl)
        self._trim(now)
        return verdict

    def _trim(self, now: float) -> None:
        if len(self._cache) <= MAX_CACHE_ENTRIES:
            return
        for key in [k for k, e in self._cache.items() if e.expires <= now]:
            self._cache.pop(key, None)
        while len(self._cache) > MAX_CACHE_ENTRIES:  # هنوز زیاد؟ قدیمی‌ترین‌ها (ترتیبِ درج)
            self._cache.pop(next(iter(self._cache)), None)

    async def _report(self, ch: Channel, exc: BaseException) -> None:
        if ch.ref in self._alerted:
            return
        self._alerted.add(ch.ref)
        await _call(self._on_error, ch, exc)

    async def _recovered(self, ch: Channel) -> None:
        if ch.ref in self._alerted:
            self._alerted.discard(ch.ref)
            await _call(self._on_recovered, ch)
