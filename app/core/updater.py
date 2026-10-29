"""تشخیصِ نسخه‌ی تازه از GitHub Releases (N14a) — بدونِ سرورِ اختصاصی، بی‌صدا در شکست.

- هنگامِ شروع و هر ۲۴ ساعتِ اجرا (وقتی اینترنت هست) ``GET /repos/<GITHUB_REPO>/releases/latest``؛ مقایسه‌ی semver؛
  draft/prerelease نادیده؛ شکست/مسدودیِ GitHub = بدونِ پیام (فقط «بررسیِ الان» در «درباره» خطا نشون می‌ده).
- آدرس‌هایی که از پاسخ می‌آیند فقط وقتی باز/دانلود می‌شن که https و روی میزبانِ GitHub باشن.
- هیچ تله‌متری/پینگی نیست؛ تنها درخواست همین GET به GitHub است.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import urlparse

from app import branding
from app.version import __version__

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 24 * 3600  # بررسیِ دوره‌ای هر ۲۴ ساعتِ اجرا
MIN_GAP_SECONDS = 3600  # حتی با ری‌استارتِ پیاپی، بیشتر از ساعتی یک‌بار GitHub را نمی‌زنیم (سقفِ API بدونِ توکن)
FETCH_TIMEOUT = 10.0
MAX_RESPONSE_BYTES = 2_000_000
SUMS_ASSET = "SHA256SUMS.txt"
SIG_ASSET = "SHA256SUMS.txt.sig"
GITHUB_HOSTS = ("github.com", "api.github.com", "objects.githubusercontent.com", "githubusercontent.com")

STATUS_UPDATE = "update"
STATUS_CURRENT = "current"
STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"

_SEMVER = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")


# ------------------------------------------------------------------ semver ----

def parse_version(text: str) -> Optional[tuple]:
    """کلیدِ قابل‌مقایسه (طبقِ semver): نسخه‌ی پایدار از prerelease‌ِ همان عدد بزرگ‌تر است؛ ورودیِ نامعتبر ⇒ ``None``."""
    match = _SEMVER.match((text or "").strip())
    if not match:
        return None
    major, minor, patch, pre = match.group(1), match.group(2), match.group(3) or "0", match.group(4)
    core = (int(major), int(minor), int(patch))
    if pre is None:
        return core, (1,)
    ids = tuple((0, int(i)) if i.isdigit() else (1, i) for i in pre.split("."))
    return core, (0, ids)


def is_newer(candidate: str, current: str) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    return a is not None and b is not None and a > b


def clean_version(text: str) -> str:
    return (text or "").strip().lstrip("vV")


# ----------------------------------------------------------------- مدل‌ها ----

@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int = 0


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    tag: str
    html_url: str
    notes: str = ""
    published: str = ""
    assets: tuple = ()

    def asset(self, name: str) -> Optional[Asset]:
        return next((a for a in self.assets if a.name == name), None)

    @property
    def signed(self) -> bool:
        """هر دو فایلِ SHA256SUMS.txt و .sig پیوست شده‌اند؟ (نبودِ امضا = فقط دانلودِ دستی)"""
        return self.asset(SUMS_ASSET) is not None and self.asset(SIG_ASSET) is not None


@dataclass
class CheckResult:
    status: str
    info: Optional[UpdateInfo] = None
    message: str = ""
    dismissed: bool = False
    extra: dict = field(default_factory=dict)


def safe_release_url(url: str, allowed_hosts: tuple = GITHUB_HOSTS) -> bool:
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        return False
    return any(host == h or host.endswith("." + h) for h in allowed_hosts)


def parse_release(payload, allowed_hosts: tuple = GITHUB_HOSTS) -> Optional[UpdateInfo]:
    """JSONِ پاسخِ ``releases/latest`` → ``UpdateInfo``؛ draft/prerelease/خراب ⇒ ``None``. هرگز exception نمی‌ده."""
    if not isinstance(payload, dict) or payload.get("draft") or payload.get("prerelease"):
        return None
    tag = str(payload.get("tag_name") or "").strip()
    version = clean_version(tag)
    parsed = parse_version(version)
    if parsed is None or parsed[1][0] == 0:  # نامعتبر یا prerelease (حتی اگه GitHub نشانه نذاشته باشه)
        return None
    html_url = str(payload.get("html_url") or "")
    if not safe_release_url(html_url, allowed_hosts):
        html_url = branding.github_releases_url()
    assets = []
    raw_assets = payload.get("assets")
    for item in raw_assets if isinstance(raw_assets, list) else []:
        if not isinstance(item, dict):
            continue
        name, url = str(item.get("name") or ""), str(item.get("browser_download_url") or "")
        if name and "/" not in name and "\\" not in name and safe_release_url(url, allowed_hosts):
            size = item.get("size")
            assets.append(Asset(name, url, size if isinstance(size, int) and size >= 0 else 0))
    return UpdateInfo(
        version=version,
        tag=tag,
        html_url=html_url,
        notes=str(payload.get("body") or "")[:4000],
        published=str(payload.get("published_at") or ""),
        assets=tuple(assets),
    )


# --------------------------------------------------------------- شبکه (stdlib) ----

def default_fetcher(url: str, timeout: float = FETCH_TIMEOUT) -> Optional[bytes]:
    """GET ساده؛ هر خطایی (آفلاین، فیلتر، ۴۰۳ سقفِ API، …) ⇒ ``None``. حجمِ پاسخ محدود است."""
    request = urllib.request.Request(
        url, headers={"User-Agent": f"SmartBusinessLocal/{__version__}", "Accept": "application/vnd.github+json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — آدرس از branding یا میزبانِ GitHub
            data = response.read(MAX_RESPONSE_BYTES + 1)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return data if len(data) <= MAX_RESPONSE_BYTES else None


# ----------------------------------------------------------------- بررسی‌گر ----

class UpdateChecker:
    """بررسیِ نسخه‌ی تازه. ``get_settings``/``save_settings`` برای خاموش‌کردن، «بعداً» و زمانِ آخرین بررسی."""

    def __init__(
        self,
        get_settings: Callable[[], object],
        save_settings: Callable[[], None],
        *,
        current_version: str = __version__,
        api_url: Optional[str] = None,
        fetcher: Optional[Callable[[str, float], Optional[bytes]]] = None,
        allowed_hosts: tuple = GITHUB_HOSTS,
        clock: Callable[[], float] = time.time,
    ):
        self._get = get_settings
        self._save = save_settings
        self.current_version = current_version
        self.api_url = api_url or branding.github_latest_release_api()
        self._fetch = fetcher or default_fetcher
        self._hosts = allowed_hosts
        self._clock = clock
        self._lock = threading.Lock()
        self.last: Optional[CheckResult] = None

    # -- وضعیت
    def pending(self) -> Optional[UpdateInfo]:
        """نسخه‌ی تازه‌ای که باید در بنر بیاد (نه «بعداً»‌شده، نه خاموش)."""
        last, settings = self.last, self._get()
        if last is None or last.status != STATUS_UPDATE or last.info is None:
            return None
        if getattr(settings, "update_dismissed_version", "") == last.info.version:
            return None
        return last.info

    def dismiss(self, version: str) -> None:
        settings = self._get()
        settings.update_dismissed_version = clean_version(version)
        self._save()

    def due(self) -> bool:
        settings = self._get()
        if not getattr(settings, "update_check_enabled", True):
            return False
        return self._clock() - float(getattr(settings, "update_last_check_ts", 0) or 0) >= MIN_GAP_SECONDS

    # -- بررسی
    def check(self, force: bool = False) -> CheckResult:
        """هرگز exception نمی‌ده. ``force`` = «بررسیِ الان» (حتی با خاموش بودنِ بررسیِ خودکار و بدونِ فاصله‌ی حداقلی)."""
        with self._lock:
            if not force and not self.due():
                return self.last or CheckResult(STATUS_SKIPPED)
            result = self._check_once()
            settings = self._get()
            try:
                settings.update_last_check_ts = int(self._clock())
                self._save()
            except Exception:  # noqa: BLE001 — خرابیِ ذخیره نباید بررسی را بشکند
                logger.warning("ذخیره‌ی زمانِ بررسیِ به‌روزرسانی ناموفق بود", exc_info=True)
            if result.status != STATUS_ERROR:
                self.last = result
            return result

    def _check_once(self) -> CheckResult:
        try:
            raw = self._fetch(self.api_url, FETCH_TIMEOUT)
            if raw is None:
                return CheckResult(STATUS_ERROR, message="no_response")
            payload = json.loads(raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else raw)
        except (ValueError, TypeError):
            return CheckResult(STATUS_ERROR, message="bad_response")
        except Exception:  # noqa: BLE001
            logger.debug("بررسیِ به‌روزرسانی ناموفق", exc_info=True)
            return CheckResult(STATUS_ERROR, message="error")
        info = parse_release(payload, self._hosts)
        if info is None or not is_newer(info.version, self.current_version):
            return CheckResult(STATUS_CURRENT)
        dismissed = getattr(self._get(), "update_dismissed_version", "") == info.version
        return CheckResult(STATUS_UPDATE, info=info, dismissed=dismissed)


def run_periodic(checker: UpdateChecker, on_result: Callable[[CheckResult], None], stop: threading.Event, interval: float = CHECK_INTERVAL_SECONDS) -> None:
    """حلقه‌ی پس‌زمینه: یک‌بار هنگامِ شروع، بعد هر ``interval`` ثانیه تا ``stop``. بی‌صدا؛ هرگز نمی‌ترکد."""
    while not stop.is_set():
        try:
            result = checker.check()
            if result.status in (STATUS_UPDATE, STATUS_CURRENT):
                on_result(result)
        except Exception:  # noqa: BLE001
            logger.debug("حلقه‌ی بررسیِ به‌روزرسانی خطا داد", exc_info=True)
        if stop.wait(interval):
            return
