"""
اشتراکِ پروکسی (R6-الف): لینکی که *کاربر خودش* می‌ده و متنِ «هر خط یک پروکسی» برمی‌گردونه. برنامه هرگز لیستِ
پروکسیِ عمومیِ رایگان داخلش نداره (امنیتِ کاربر)؛ فقط همین لینکِ خودِ کاربر.

- ``https://`` توصیه می‌شه؛ ``http://`` با هشدار (محتوا می‌تونه دست‌کاری بشه). هر scheme دیگه رد می‌شه.
- timeout ۱۰ ثانیه، سقفِ حجم ۲۵۶KB، حداکثر ۳ ریدایرکت (که باید http(s) بمونن).
- نتیجه جدا از لیستِ دستیِ کاربر در کش ذخیره می‌شه (credential داره ⇒ رمزنگاری)؛ شکستِ دریافت *هرگز* کش رو پاک نمی‌کنه.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Optional
from urllib.parse import urlparse

from app.core.proxy_pool import ParsedProxies, parse_proxy_text

MAX_BYTES = 256 * 1024
TIMEOUT_SECONDS = 10.0
MAX_REDIRECTS = 3
MAX_URL_LEN = 2000

Fetcher = Callable[[str], Awaitable[str]]


class SubscriptionError(Exception):
    """خطای قابل‌نمایش (فارسی) — لینک نامعتبر، شبکه، حجمِ زیاد یا خالی‌بودنِ لیست."""


def validate_url(url: str) -> tuple:
    """``(آدرسِ تمیز, هشدار)``؛ آدرسِ نامعتبر ⇒ ``SubscriptionError``."""
    clean = (url or "").strip()
    if not clean or len(clean) > MAX_URL_LEN or any(ch.isspace() for ch in clean) or any(ord(ch) < 32 for ch in clean):
        raise SubscriptionError("لینکِ اشتراک نامعتبره.")
    parsed = urlparse(clean)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or not parsed.hostname:
        raise SubscriptionError("لینکِ اشتراک باید با https:// (یا http://) شروع بشه.")
    warning = "" if parsed.scheme == "https" else "⚠️ این لینک http ساده‌ست؛ هر کسی روی مسیر می‌تونه لیست رو دست‌کاری کنه — اگه می‌شه https بگیر."
    return clean, warning


async def _default_fetch(url: str) -> str:
    import aiohttp

    timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, allow_redirects=True, max_redirects=MAX_REDIRECTS) as response:
                if response.status != 200:
                    raise SubscriptionError(f"سرور اشتراک خطا داد (HTTP {response.status}).")
                final = str(response.url)
                if not final.lower().startswith(("http://", "https://")):
                    raise SubscriptionError("ریدایرکتِ نامعتبر.")
                body = bytearray()
                async for chunk in response.content.iter_chunked(8192):
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise SubscriptionError("حجمِ پاسخ از ۲۵۶ کیلوبایت بیشتره؛ این لیست پروکسی نیست.")
    except SubscriptionError:
        raise
    except Exception as exc:  # noqa: BLE001 — timeout/DNS/TLS/ریدایرکتِ زیاد
        raise SubscriptionError(f"دریافتِ اشتراک ممکن نشد ({type(exc).__name__}).") from exc
    try:
        return bytes(body).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SubscriptionError("پاسخِ اشتراک متنِ UTF-8 نیست.") from exc


async def fetch_proxies(url: str, fetcher: Optional[Fetcher] = None) -> ParsedProxies:
    """لینک رو می‌گیره و لیستِ پروکسی‌های معتبر رو برمی‌گردونه؛ لیستِ خالی/بی‌اعتبار ⇒ ``SubscriptionError``."""
    clean, _warning = validate_url(url)
    text = await (fetcher or _default_fetch)(clean)
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise SubscriptionError("حجمِ پاسخ از ۲۵۶ کیلوبایت بیشتره؛ این لیست پروکسی نیست.")
    parsed = parse_proxy_text(text)
    if not parsed.urls:
        raise SubscriptionError("هیچ پروکسیِ معتبری توی پاسخِ اشتراک نبود.")
    return parsed


def combine(manual_text: str, cache_text: str) -> str:
    """استخر = لیستِ دستیِ کاربر + کشِ اشتراک (دستی‌ها اول؛ تکراری‌ها در parse حذف می‌شن)."""
    parts = [p for p in ((manual_text or "").strip(), (cache_text or "").strip()) if p]
    return "\n".join(parts)
