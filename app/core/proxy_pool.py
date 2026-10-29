"""استخر پروکسی تلگرام: چند پروکسی، تستِ سلامت/سرعت و جابه‌جاییِ خودکار.

چرا لازمه: تلگرام برای خیلی از کاربرای ایرانی فقط با پروکسی/VPN در دسترسه، و پروکسی‌ها
(مخصوصاً رایگان‌ها) مدام می‌افتن. با یه پروکسیِ ثابت، با قطع‌شدنش ربات تلگرام تا دخالتِ
دستی ساکت می‌مونه. این ماژول لیستی از پروکسی‌ها نگه می‌داره، بهترین رو انتخاب می‌کنه و
وقتی یکی پشت‌سرهم شکست خورد، خودکار می‌ره سراغ بعدی (پروکسیِ خراب یه «زمان استراحت» می‌گیره
و بعدش دوباره شانس پیدا می‌کنه).

قالب‌های قابل‌قبول (هر خط یکی؛ خط‌های خالی و ``#توضیح`` نادیده گرفته می‌شن):

* ``socks5://[user:pass@]host:port``  ·  ``socks4://…``  ·  ``http://…``
  (``socks5h://`` به ``socks5://`` تبدیل می‌شه)
* ``host:port``  ·  ``user:pass@host:port``  ·  ``host:port:user:pass`` (قالبِ رایجِ فروشنده‌ها)
  — بدون scheme یعنی SOCKS5 (رایج‌ترین)؛ دکمه‌ی «بررسی» اگه SOCKS5 جواب نداد HTTP رو هم می‌ازماید.

پروکسیِ MTProto (``tg://proxy…`` / ``t.me/proxy…``) برای *ربات‌ها* کار نمی‌کنه (فقط برای
اپِ تلگرامِ کاربره) و با پیامِ روشن رد می‌شه. ``https://`` هم پشتیبانی نمی‌شه.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

SUPPORTED_SCHEMES = ("socks5", "socks4", "http")
DEFAULT_SCHEME = "socks5"
PROBE_URL = "https://api.telegram.org/"
DEFAULT_COOLDOWN_SECONDS = 60.0
MAX_COOLDOWN_SECONDS = 600.0

_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_HOST_RE = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)(\.[A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)*$")
_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*)://(.*)$")


class ProxyFormatError(ValueError):
    """پیامِ فارسیِ قابل‌نمایش به کاربر."""


def _valid_host(host: str) -> bool:
    if not host:
        return False
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return bool(_HOST_RE.match(host))


def _valid_port(port: str) -> bool:
    return port.isdigit() and 1 <= int(port) <= 65535


def _build(scheme: str, host: str, port: str, user: str = "", password: str = "") -> str:
    if not _valid_host(host):
        raise ProxyFormatError(f"آدرسِ «{host}» معتبر نیست.")
    if not _valid_port(port):
        raise ProxyFormatError(f"پورتِ «{port}» معتبر نیست (۱ تا ۶۵۵۳۵).")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"  # IPv6
    auth = f"{user}:{password}@" if user else ""
    return f"{scheme}://{auth}{host}:{port}"


def normalize_proxy(line: str) -> str:
    """یه خط → آدرسِ استانداردِ ``scheme://[user:pass@]host:port``؛ خطای قالب → ``ProxyFormatError``."""
    text = (line or "").translate(_DIGIT_MAP).strip()
    if not text:
        raise ProxyFormatError("خط خالیه.")
    lowered = text.lower()
    if lowered.startswith(("tg://proxy", "https://t.me/proxy", "http://t.me/proxy", "t.me/proxy")):
        raise ProxyFormatError(
            "پروکسیِ MTProto (لینکِ tg://proxy) برای ربات‌ها کار نمی‌کنه؛ SOCKS5 یا HTTP لازمه."
        )
    match = _SCHEME_RE.match(text)
    if match:
        scheme, rest = match.group(1).lower(), match.group(2).rstrip("/")
        if scheme == "socks5h":
            scheme = "socks5"
        if scheme == "https":
            raise ProxyFormatError("پروکسیِ https:// پشتیبانی نمی‌شه؛ از socks5:// یا http:// استفاده کن.")
        if scheme not in SUPPORTED_SCHEMES:
            raise ProxyFormatError(f"نوعِ «{scheme}» پشتیبانی نمی‌شه (فقط socks5، socks4، http).")
        user = password = ""
        hostport = rest
        if "@" in rest:
            creds, hostport = rest.rsplit("@", 1)
            user, _, password = creds.partition(":")
        host, sep, port = hostport.rpartition(":")
        if not sep:
            raise ProxyFormatError("پورت نوشته نشده (مثلاً socks5://127.0.0.1:10808).")
        return _build(scheme, host, port, user, password)

    # بدون scheme
    if "@" in text:  # user:pass@host:port
        creds, hostport = text.rsplit("@", 1)
        user, _, password = creds.partition(":")
        host, sep, port = hostport.rpartition(":")
        if not sep:
            raise ProxyFormatError("پورت نوشته نشده.")
        return _build(DEFAULT_SCHEME, host, port, user, password)
    parts = text.split(":")
    if len(parts) == 2:  # host:port
        return _build(DEFAULT_SCHEME, parts[0], parts[1])
    if len(parts) == 4:  # host:port:user:pass
        return _build(DEFAULT_SCHEME, parts[0], parts[1], parts[2], parts[3])
    raise ProxyFormatError(
        f"قالبِ «{text[:40]}» رو نفهمیدم؛ مثال: socks5://127.0.0.1:10808 یا 1.2.3.4:1080"
    )


@dataclass
class ParsedProxies:
    urls: list = field(default_factory=list)  # آدرس‌های معتبرِ یکتا، به ترتیبِ ورودی
    errors: list = field(default_factory=list)  # [(شماره خط, متنِ خط, پیام)]


def parse_proxy_text(text: str) -> ParsedProxies:
    """متنِ چندخطیِ تنظیمات → لیستِ پروکسی‌های معتبر + خطاهای هر خط."""
    result = ParsedProxies()
    seen = set()
    for number, raw in enumerate((text or "").splitlines(), start=1):
        # کامنت فقط وقتی که «#» اول خط یا بعد از فاصله باشه (رمزِ پروکسی ممکنه خودش # داشته باشه)
        line = re.sub(r"(^|\s)#.*$", "", raw).strip()
        if not line:
            continue
        try:
            url = normalize_proxy(line)
        except ProxyFormatError as exc:
            result.errors.append((number, raw.strip(), str(exc)))
            continue
        if url not in seen:
            seen.add(url)
            result.urls.append(url)
    return result


def has_explicit_scheme(line: str) -> bool:
    return bool(_SCHEME_RE.match((line or "").strip()))


def mask_credentials(url: str) -> str:
    """برای نمایش در UI/لاگ: ``socks5://user:pass@h:p`` → ``socks5://***@h:p``."""
    return re.sub(r"(://)[^/@]+@", r"\1***@", url)


def proxy_config_from_text(text: str) -> tuple:
    """متنِ تنظیمات → ``(proxy, pool)`` برای ``TelegramAdapter``:

    * ۲ پروکسیِ معتبر یا بیشتر → ``("", ProxyPool)`` (جابه‌جاییِ خودکار)
    * یک پروکسیِ معتبر → ``(آدرس, None)``
    * هیچ‌کدوم معتبر نبود ولی چیزی نوشته شده → ``(اولین خطِ خام, None)``؛ آداپتور خودش
      «آدرس پروکسی نامعتبره» رو نشون می‌ده (به‌جای اینکه بی‌صدا مستقیم وصل بشه)
    * خالی → ``("", None)`` (اتصالِ مستقیم)"""
    parsed = parse_proxy_text(text)
    if len(parsed.urls) >= 2:
        return "", ProxyPool(parsed.urls)
    if len(parsed.urls) == 1:
        return parsed.urls[0], None
    first = next(
        (ln.strip() for ln in (text or "").splitlines() if ln.strip() and not ln.strip().startswith("#")), ""
    )
    return first, None


def proxy_secrets(text: str) -> list:
    """هر چیزی از متنِ پروکسی که نباید توی لاگ بیاد (خط‌های خام + آدرس‌های استاندارد)."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return [*lines, *parse_proxy_text(text).urls]


# ----------------------------------------------------------------- استخر ----


@dataclass
class ProxyEntry:
    url: str
    fails: int = 0
    cooldown_until: float = 0.0
    latency_ms: Optional[float] = None


class ProxyPool:
    """لیستِ پروکسی‌ها با «پروکسیِ فعلی». ترد-امن نیست و لازم هم نیست؛ هر آداپتور
    استخرِ خودش رو توی حلقه‌ی asyncio خودش استفاده می‌کنه."""

    def __init__(
        self,
        urls,
        *,
        cooldown: float = DEFAULT_COOLDOWN_SECONDS,
        max_cooldown: float = MAX_COOLDOWN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        seen: list = []
        for url in urls or []:
            if url and url not in seen:
                seen.append(url)
        self._entries = [ProxyEntry(u) for u in seen]
        self._cooldown = cooldown
        self._max_cooldown = max_cooldown
        self._clock = clock
        self._current = 0

    def replace(self, urls) -> bool:
        """لیست رو (مثلاً بعد از به‌روزرسانیِ اشتراک) درجا عوض می‌کنه؛ وضعیتِ (شکست/تأخیر) پروکسی‌های باقی‌مانده حفظ می‌شه
        و پروکسیِ فعلی اگه هنوز هست فعلی می‌مونه. ``True`` اگه لیست واقعاً عوض شد."""
        wanted: list = []
        for url in urls or []:
            if url and url not in wanted:
                wanted.append(url)
        if wanted == self.urls:
            return False
        old_current = self.current()
        existing = {e.url: e for e in self._entries}
        self._entries = [existing.get(u) or ProxyEntry(u) for u in wanted]
        self._current = wanted.index(old_current) if old_current in wanted else 0
        return True

    # ---- مشاهده
    def __len__(self) -> int:
        return len(self._entries)

    @property
    def urls(self) -> list:
        return [e.url for e in self._entries]

    def entry(self, url: str) -> Optional[ProxyEntry]:
        return next((e for e in self._entries if e.url == url), None)

    def current(self) -> str:
        return self._entries[self._current].url if self._entries else ""

    def is_cooling(self, url: str) -> bool:
        entry = self.entry(url)
        return bool(entry and entry.cooldown_until > self._clock())

    # ---- انتخاب
    def pick(self) -> str:
        """پروکسیِ مناسبِ *همین الان*: فعلی (اگه استراحت نمی‌کنه)، وگرنه بعدیِ آماده؛ اگه همه
        در استراحتن، اونی که زودتر آماده می‌شه (استخر هیچ‌وقت «بن‌بست» نمی‌شه)."""
        if not self._entries:
            return ""
        now = self._clock()
        count = len(self._entries)
        for offset in range(count):
            index = (self._current + offset) % count
            if self._entries[index].cooldown_until <= now:
                self._current = index
                return self._entries[index].url
        index = min(range(count), key=lambda i: self._entries[i].cooldown_until)
        self._current = index
        return self._entries[index].url

    def report_success(self, url: str, latency_ms: Optional[float] = None) -> None:
        entry = self.entry(url)
        if entry is None:
            return
        entry.fails = 0
        entry.cooldown_until = 0.0
        if latency_ms is not None:
            entry.latency_ms = latency_ms
        self._current = self._entries.index(entry)

    def report_failure(self, url: str) -> str:
        """این پروکسی شکست خورد: استراحتش می‌دیم (هر شکستِ پشت‌سرهم طولانی‌تر) و پروکسیِ
        بعدی رو برمی‌گردونیم. با یه پروکسی فقط همون برمی‌گرده (چاره‌ی دیگه‌ای نیست)."""
        entry = self.entry(url)
        if entry is None:
            return self.pick()
        entry.fails += 1
        entry.cooldown_until = self._clock() + min(self._cooldown * entry.fails, self._max_cooldown)
        if len(self._entries) > 1:
            self._current = (self._entries.index(entry) + 1) % len(self._entries)
        return self.pick()

    # ---- رتبه‌بندی بر اساسِ نتیجه‌ی تست
    def apply_probe_results(self, results: dict) -> None:
        """``results``: آدرس → تأخیر به میلی‌ثانیه (یا ``None`` یعنی جواب نداد). سالم‌ها
        بر اساس سرعت اول می‌آن؛ ناسالم‌ها آخرِ لیست و در استراحت."""
        now = self._clock()
        for entry in self._entries:
            if entry.url not in results:
                continue
            latency = results[entry.url]
            if latency is None:
                entry.fails += 1
                entry.latency_ms = None
                entry.cooldown_until = now + self._cooldown
            else:
                entry.fails = 0
                entry.cooldown_until = 0.0
                entry.latency_ms = latency

        def key(entry: ProxyEntry):
            return (entry.latency_ms is None, entry.latency_ms if entry.latency_ms is not None else 0.0)

        self._entries.sort(key=key)  # sort پایداره: نامعلوم‌ها ترتیبِ اولیه‌شون رو نگه می‌دارن
        self._current = 0


# ---------------------------------------------------------------- تست واقعی ----


async def probe_proxy(url: str, timeout: float = 8.0, target: str = PROBE_URL) -> Optional[float]:
    """تأخیرِ رسیدن به تلگرام از طریقِ این پروکسی (میلی‌ثانیه) یا ``None`` اگه نشد. هر پاسخِ
    HTTP (حتی ۳۰۲) یعنی تونل کار می‌کنه — فقط اتصال و TLS مهمه، نه محتوا."""
    try:
        from aiohttp import ClientSession, ClientTimeout
        from aiohttp_socks import ProxyConnector

        connector = ProxyConnector.from_url(url)
        started = time.monotonic()
        async with ClientSession(connector=connector, timeout=ClientTimeout(total=timeout)) as session:
            async with session.get(target, allow_redirects=False) as response:
                await response.read()
        return (time.monotonic() - started) * 1000.0
    except Exception:  # noqa: BLE001 — هر خطایی (شبکه، TLS، رد شدن، timeout) یعنی «کار نمی‌کنه»
        return None


Prober = Callable[[str], Awaitable[Optional[float]]]


async def probe_all(urls, prober: Optional[Prober] = None, concurrency: int = 6) -> dict:
    """همه‌ی پروکسی‌ها رو هم‌زمان (با سقفِ ``concurrency``) می‌آزماید → ``{آدرس: تأخیر|None}``."""
    prober = prober or probe_proxy
    gate = asyncio.Semaphore(max(1, concurrency))

    async def one(url: str):
        async with gate:
            return url, await prober(url)

    pairs = await asyncio.gather(*(one(u) for u in urls))
    return dict(pairs)


async def probe_bare_candidates(lines, prober: Optional[Prober] = None) -> dict:
    """برای خط‌های *بدونِ scheme* اگه SOCKS5 جواب نداد HTTP هم امتحان می‌شه. خروجی:
    ``{آدرسِ نهایی (همونی که کار کرد، یا socks5 اگه هیچ‌کدوم): تأخیر|None}`` به ترتیبِ ورودی."""
    prober = prober or probe_proxy
    out: dict = {}
    for raw in lines:
        try:
            primary = normalize_proxy(raw)
        except ProxyFormatError:
            continue
        latency = await prober(primary)
        if latency is None and not has_explicit_scheme(raw) and primary.startswith("socks5://"):
            alternative = "http://" + primary[len("socks5://"):]
            alt_latency = await prober(alternative)
            if alt_latency is not None:
                out[alternative] = alt_latency
                continue
        out[primary] = latency
    return out
