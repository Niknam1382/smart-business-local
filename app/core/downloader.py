"""
دانلودِ مدلِ GGUF با ادامه‌دادن، کنسل‌کردن و راستی‌آزماییِ sha256.

فقط کتابخونه‌ی استاندارد (urllib + hashlib) — بدونِ وابستگیِ جانبی. فایلِ نیمه‌کاره با پسوند
``.part`` و یه فایلِ کنارِ آن (``.part.meta`` که آدرس و اثرانگشتِ منبع را ثبت می‌کند) نگه داشته
می‌شه؛ پس قطعِ اینترنت، بستنِ برنامه یا کنسل‌کردنِ کاربر یعنی «ادامه بده»، نه «از اول شروع کن».
فایلِ نهایی فقط وقتی ساخته می‌شه که همهِ بایت‌ها آمده و اثرانگشتِ موردِ انتظارِ کاتالوگ را بده؛
بنابراین هیچ‌وقت مدلِ نصفه‌نیمه یا دستکاری‌شده بارگذاری نمی‌شه.
"""

from __future__ import annotations

import hashlib
import json
import errno
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

CHUNK_SIZE = 1024 * 256  # ۲۵۶ کیلوبایت در هر خوندن
USER_AGENT = "SmartBusinessLocal/1.0 (+https://github.com)"


class DownloadError(Exception):
    """خطای قابل‌نمایش (فارسی) در دانلود."""


class DownloadCancelled(Exception):
    """کاربر خودش زده «توقف»؛ فایلِ .part برایِ ادامه نگه می‌مونه."""


class IntegrityError(DownloadError):
    """فایلِ دانلودشده با اثرانگشتِ کاتالوگ نمی‌خونه (خراب یا دستکاری‌شده)."""


GGUF_MAGIC = b"GGUF"


@dataclass
class ResumeMeta:
    url: str
    sha256: str
    total: int


def _part_paths(dest: Path) -> tuple:
    part = dest.with_name(dest.name + ".part")
    return part, part.with_name(part.name + ".meta")


def _read_meta(part: Path) -> Optional[ResumeMeta]:
    meta_path = part.with_name(part.name + ".meta")
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return ResumeMeta(url=str(data.get("url", "")), sha256=str(data.get("sha256", "")), total=int(data.get("total", 0) or 0))
    except (OSError, ValueError, TypeError):
        return None


def _write_meta(part: Path, meta: ResumeMeta) -> None:
    part.with_name(part.name + ".meta").write_text(
        json.dumps({"url": meta.url, "sha256": meta.sha256, "total": meta.total}, ensure_ascii=False), encoding="utf-8"
    )


def host_allowed(host: str, allowed: set) -> bool:
    """مقایسه بر پایهی *نام*: خودِ دامنه یا زیردامنه‌اش پذیرفته می‌شه.
    ``localhost`` در برابر ``127.0.0.1`` هم رد می‌شه — چون مقایسه‌ی IP نیست."""
    name = (host or "").strip().rstrip(".").lower()
    if not name:
        return False
    return any(name == root or name.endswith("." + root) for root in allowed if root)


class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    """ریدایرکت فقط به هاستهایِ معرفیشده (منابعِ کاتالوگ و CDNهای اعلام‌شده‌ی آن‌ها) و فقط http/https.

    CDN عمداً در فهرست هست: هر دو منبعِ فایلِ GGUF را با ۳۰۲/۳۰۸ به دامنه‌ی خودش می‌فرستند،
    پس بدونِ آن **هیچ** مدلی دانلود نمی‌شد (آینه‌ها شخصِ ثالث‌ان؛ مقصدِ ناشناخته رد می‌شه)."""

    def __init__(self, allowed_hosts: set):
        super().__init__()
        self._allowed = {h.lower() for h in allowed_hosts if h}

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401, ANN001
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme not in ("http", "https") or not host_allowed(parsed.hostname or "", self._allowed):
            raise urllib.error.URLError("آدرسِ دوباره‌هدایت‌شده خارج از فهرستِ مجاز رد شد.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url: str, start: int, timeout: float, allowed_hosts: Optional[set] = None):
    headers = {"User-Agent": USER_AGENT}
    if start > 0:
        headers["Range"] = f"bytes={start}-"
    request = urllib.request.Request(url, headers=headers)
    if allowed_hosts is None:
        return urllib.request.urlopen(request, timeout=timeout)
    opener = urllib.request.build_opener(_GuardedRedirect(allowed_hosts))
    return opener.open(request, timeout=timeout)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(
    urls: list,
    dest: Path,
    expected_sha256: str = "",
    expected_size: int = 0,
    on_progress: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    timeout: float = 30.0,
    allowed_hosts: Optional[set] = None,
    use_curl_fallback: bool = False,
) -> Path:
    """فایل را از اولین منبعِ کاری دانلود می‌کند؛ ادامه می‌دهد؛ و در پایان sha256 را می‌سنجد.

    همه‌ی منبع‌ها **خودکار و پشتِ هم** امتحان می‌شوند. اگر هیچ‌کدام با روشِ اصلی جواب نداد و
    ``use_curl_fallback`` روشن بود (فقط برایِ فایل‌هایِ دارایِ هشِ مرجع، فقط ویندوز، فقط اگر ``curl.exe``
    هست)، همان منبع‌ها یک‌بار با curl امتحان می‌شوند؛ هشِ SHA-256 در پایان الزامی است.

    ``urls`` ترتیبِ اولویت است (هاستِ اصلی، بعدِ آینه). ``allowed_hosts`` دامنه‌هایِ
    اعلام‌شده‌ی اضافه است (CDNهایِ همان منابع — وگرنه ریدایرکتِ سرویسِ فایل رد می‌شود).
    ``on_progress(downloaded, total)``
    بعدِ هر قطعه صدا زده می‌شود (total ممکن است ۰ باشد). ``should_cancel()`` که True بدهد،
    دانلود متوقف می‌شود و ``.part`` برای ادامه‌ی بعدی می‌ماند.
    """
    if not urls:
        raise DownloadError("نشانیِ دانلود مشخص نیست.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part, _meta_path = _part_paths(dest)

    allowed = {urllib.parse.urlparse(u).hostname or "" for u in urls}
    allowed |= {h.strip().lower() for h in (allowed_hosts or set()) if h}
    failures: list = []
    for url in urls:
        host = urllib.parse.urlparse(url).hostname or url
        try:
            return _download_one(url, dest, part, expected_sha256, expected_size, on_progress, should_cancel, timeout, allowed)
        except DownloadCancelled:
            raise
        except IntegrityError:
            _drop(part)
            raise  # اثرانگشت از هیچ آینه‌ای درست نمی‌شه اگه خودِ فایل باطل باشه؛ ولی اول بعدی را امتحان می‌کنیم
        except DownloadError as exc:  # حجمِ اشتباه/قطعِ وسطِ راه از یک منبع؛ منبعِ بعدی را امتحان کن
            _drop_meta(part)
            failures.append(f"{host}: {exc}")
            continue
        except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
            _drop_meta(part)
            failures.append(f"{host}: {_reason(exc)}" + (f" ← {_hint(exc)}" if _hint(exc) else ""))
            if isinstance(exc, OSError) and getattr(exc, "errno", None) in (errno.ENOSPC, getattr(errno, "EDQUOT", -1)):
                raise DownloadError(
                    "جای خالیِ دیسک برایِ این مدل کافی نیست. فضا باز کن یا در تنظیماتِ هوش مصنوعی پوشه‌ی دیگری "
                    "برایِ مدل‌ها انتخاب کن و دوباره «ادامه» را بزن."
                ) from exc
            continue

    curl = _curl_path() if (use_curl_fallback and expected_sha256) else None
    if curl:
        for url in urls:
            host = urllib.parse.urlparse(url).hostname or url
            try:
                return _download_with_curl(curl, url, dest, part, expected_sha256, expected_size, on_progress, should_cancel, timeout, allowed_hosts)
            except DownloadCancelled:
                raise
            except IntegrityError:
                _drop(part)
                raise
            except DownloadError as exc:
                failures.append(f"{host} (curl): {exc}")
    raise DownloadError(failure_text(failures))


def failure_text(failures: list) -> str:
    """پیامِ نهاییِ دانلود: کدام منبع چه شد + قدمِ بعدی، بدونِ اصطلاحِ فنی."""
    lines = "\n".join("• " + item for item in failures[:12])
    return (
        "دانلود از هیچ منبعی ممکن نشد.\n" + lines + "\n"
        "چه کار کنم؟ اتصال اینترنت/VPN را عوض یا بررسی کن، ساعتِ سیستم و آنتی‌ویروس را چک کن، "
        "مطمئن شو جای خالیِ دیسک کافی است و دوباره «ادامه» را بزن. اگر باز نشد، از «لینک‌هایِ دانلودِ کمکی» "
        "فایل را با مرورگر بگیر و با «وارد کردن فایلِ مدل» به برنامه نشان بده."
    )


def _curl_path() -> Optional[str]:
    """مسیرِ ``curl.exe`` در ویندوز؛ جایِ دیگر ``None`` (پشتیبانِ دوم فقط برایِ ویندوز است)."""
    if sys.platform != "win32":
        return None
    return shutil.which("curl.exe")


def _curl_reason(code: int) -> str:
    return {
        6: "آدرسِ سرور پیدا نشد",
        7: "اتصال به سرور برقرار نشد",
        22: "سرور درخواست را نپذیرفت (فیلتر یا نبودنِ فایل)",
        28: "پاسخی نیامد",
        35: "خطای اتصالِ امن",
        60: "خطای گواهیِ امنیتی",
        23: "نوشتنِ فایل روی دیسک ممکن نشد",
    }.get(code, f"کدِ خطا {code}")


def _download_with_curl(curl: str, url: str, dest: Path, part: Path, expected_sha256: str, expected_size: int,
                        on_progress, should_cancel, timeout: float, allowed_hosts: Optional[set] = None) -> Path:
    """پشتیبانِ دوم (ویندوز): ``curl.exe`` با ادامه از ``.part``؛ پیشرفت از حجمِ ``.part``؛ SHA-256 الزامی."""
    if urllib.parse.urlparse(url).scheme != "https":
        raise DownloadError("فقط آدرسِ امن (https) پذیرفته می‌شود")
    command = [
        curl, "--proto", "=https", "--proto-redir", "=https", "-L", "-C", "-", "--fail", "--silent", "--show-error",
        "--connect-timeout", str(int(max(5, timeout))), "--retry", "2", "-A", USER_AGENT, "-o", str(part),
        "-w", "%{url_effective}", url,
    ]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=flags)
    except OSError as exc:
        raise DownloadError(f"curl اجرا نشد ({_reason(exc)})") from exc
    total = expected_size
    try:
        while proc.poll() is None:
            if should_cancel is not None and should_cancel():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    proc.kill()
                raise DownloadCancelled()
            if on_progress is not None:
                try:
                    on_progress(part.stat().st_size if part.exists() else 0, total)
                except OSError:
                    pass
            time.sleep(0.4)
    finally:
        if proc.poll() is None:
            proc.kill()
    if proc.returncode != 0:
        raise DownloadError(_curl_reason(int(proc.returncode)))
    # آدرسِ نهاییِ بعد از redirectها هم باید از میزبان‌هایِ مجاز باشد (مثلِ مسیرِ اصلی)
    final_url = ""
    try:
        out = getattr(proc, "stdout", None)
        final_url = (out.read() or b"").decode("utf-8", "replace").strip() if out is not None else ""
    except Exception:  # noqa: BLE001
        final_url = ""
    if allowed_hosts and final_url:
        final_host = (urllib.parse.urlparse(final_url).hostname or "").lower()
        if final_host and final_host not in {h.lower() for h in allowed_hosts}:
            _drop(part)
            raise DownloadError(f"آدرسِ نهاییِ دانلود ({final_host}) جزوِ منبع‌هایِ مجاز نیست")
    downloaded = part.stat().st_size if part.exists() else 0
    if on_progress is not None:
        on_progress(downloaded, total or downloaded)
    actual = sha256_file(part)
    if actual.lower() != expected_sha256.lower():
        _drop(part)
        raise IntegrityError("فایلِ دانلودشده با نسخه‌ی اصلی نمی‌خونه (اثرانگشتِ نامعتبر).")
    _drop_meta(part)
    part.replace(dest)
    return dest


def _hint(exc: Exception) -> str:
    """قدمِ بعدیِ پیشنهادی برای رایج‌ترین علت‌ها (۱٫۲٫۰)؛ به متنِ خامِ ``_reason`` اضافه می‌شود، جایگزینش نمی‌شود."""
    if isinstance(exc, urllib.error.HTTPError):
        return {
            401: "نیاز به ورود/دسترسی دارد",
            403: "دسترسی ممنوع است (احتمالاً فیلتر/تحریم؛ VPN یا منبعِ دیگر را امتحان کن)",
            404: "فایل روی این منبع پیدا نشد",
            429: "درخواست‌ها زیاد است؛ چند دقیقه بعد دوباره امتحان کن",
        }.get(exc.code, "")
    lowered = str(exc).lower()
    if isinstance(exc, TimeoutError) or "timed out" in lowered:
        return "پاسخی نیامد؛ اینترنت/VPN را بررسی کن"
    if "certificate" in lowered or "ssl" in lowered:
        return "خطای گواهیِ امنیتی؛ ساعتِ سیستم، VPN یا آنتی‌ویروس را بررسی کن"
    if "getaddrinfo" in lowered or "name or service not known" in lowered:
        return "آدرسِ سرور پیدا نشد؛ اینترنت یا VPN را بررسی کن"
    return ""


def _reason(exc: Exception) -> str:
    """علتِ خامِ پایتون را خوانا و کوتاه می‌کند — تا خطایِ آخرینِ منبع، علتِ منابعِ سالم را پنهان نکند."""
    text = str(exc).strip().strip("<>")
    text = text.removeprefix("urlopen error ")
    text = re.sub(r"\[Errno\s+\d+\]\s*", "", text)
    return (re.sub(r"\s+", " ", text).strip() or type(exc).__name__)[:90]


def _download_one(
    url: str, dest: Path, part: Path, expected_sha256: str, expected_size: int,
    on_progress, should_cancel, timeout: float, allowed_hosts: Optional[set] = None,
) -> Path:
    start = part.stat().st_size if part.exists() else 0
    meta = _read_meta(part) if start else None
    if start and (meta is None or meta.url != url or (expected_sha256 and meta.sha256 != expected_sha256)):
        start = 0  # ادامه‌ی این فایل به این منبع تعلق نداره؛ از اول
        _drop(part)

    response = _open(url, start, timeout, allowed_hosts)
    with response:
        status = getattr(response, "status", 200) or response.getcode()
        if start and status != 206:  # سرور ادامه را قبول نکرد → از صفر
            start = 0
            _drop(part)
        total = int(response.headers.get("Content-Length", 0) or 0)
        if status == 206 and total:
            total += start
        elif not total and expected_size:
            total = expected_size
        if total and start > total:  # فایلِ .part بلندتر از فایلِ واقعیه (خراب شده)
            start = 0
            _drop(part)
            response.close()
            return _download_one(url, dest, part, expected_sha256, expected_size, on_progress, should_cancel, timeout, allowed_hosts)

        # سقفِ جریانی: منتظرِ پایانِ دانلود نمی‌مانیم — آینه‌ای که Content-Length دروغ می‌گوید
        # یا اصلاً نمی‌فرستد وگرنه می‌تواند دیسکِ فروشنده را پر کند (چند گیگابایت).
        ceiling = max(total, expected_size) if (total or expected_size) else 0

        downloaded = start
        mode = "ab" if start else "wb"
        with open(part, mode) as handle:
            while True:
                if should_cancel is not None and should_cancel():
                    _write_meta(part, ResumeMeta(url=url, sha256=expected_sha256, total=total))
                    raise DownloadCancelled()
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                downloaded += len(chunk)
                if ceiling and downloaded > ceiling:
                    _drop_meta(part)
                    raise DownloadError("سرور بیش از حجمِ اعلام‌شده داده فرستاد؛ دانلود متوقف شد.")
                handle.write(chunk)
                if on_progress is not None:
                    on_progress(downloaded, total)

    if total and downloaded != total:
        _drop_meta(part)
        raise DownloadError("دانلود وسطش قطع شد؛ دوباره «ادامه» را بزن.")

    if expected_sha256:
        actual = sha256_file(part)
        if actual.lower() != expected_sha256.lower():
            _drop(part)
            raise IntegrityError(
                f"فایلِ دانلودشده با نسخه‌ی اصلی نمی‌خونه (اثرانگشتِ نامعتبر). منبع: {url.split('/')[2]}"
            )
    elif expected_size and abs(downloaded - expected_size) > expected_size * 0.05:
        _drop(part)
        raise DownloadError("حجمِ فایل با آنچه کاتالوگ وعده داده فاصله‌ی زیادی دارد؛ دانلود باطل شد.")

    _drop_meta(part)
    part.replace(dest)  # rename اتمی — فقط حالا فایل «کامل» حساب می‌شه
    return dest


def _drop(part: Path) -> None:
    try:
        part.unlink(missing_ok=True)
    except OSError:
        pass
    _drop_meta(part)


def _drop_meta(part: Path) -> None:
    try:
        part.with_name(part.name + ".meta").unlink(missing_ok=True)
    except OSError:
        pass


def partial_bytes(dest: Path) -> int:
    """چقدر از فایل دانلود شده و منتظرِ ادامه است (۰ یعنی چیزی در کار نیست)."""
    part = dest.with_name(dest.name + ".part")
    try:
        return part.stat().st_size if part.exists() else 0
    except OSError:
        return 0


def is_downloaded(dest: Path, expected_size: int = 0) -> bool:
    """فایل هست و سرآمدش امضای GGUF دارد و (اگر حجمی داده شده بود) حجمش با کاتالوگ می‌خونه."""
    try:
        if not dest.is_file():
            return False
        size = dest.stat().st_size
        if size < 1_000_000:
            return False
        if expected_size and abs(size - expected_size) > max(1_000_000, expected_size * 0.02):
            return False
        with open(dest, "rb") as handle:
            return handle.read(4) == GGUF_MAGIC
    except OSError:
        return False


def verify_file(path: Path, expected_sha256: str) -> tuple:
    """(سالم است؟, پیام). اثرانگشتِ کامل — برای دکمه‌ی «راستی‌آزمایی» در صفحه‌ی مدل‌ها."""
    if not path.is_file():
        return False, "فایل پیدا نشد."
    actual = sha256_file(path)
    if not expected_sha256:  # مدلِ تأییدنشده: هشِ مرجع نداریم؛ هشِ واقعی را نشان می‌دهیم تا با صفحه‌ی مخزن مقایسه شود
        return True, f"SHA-256: {actual}"
    if actual.lower() != expected_sha256.lower():
        return False, "اثرانگشتِ فایل با نسخه‌ی اصلی نمی‌خونه؛ باید دوباره دانلودش کنی."
    return True, ""


def delete_model(path: Path) -> bool:
    """فایل مدل (و فایل .part نیمه‌کاره‌ی احتمالی) رو حذف می‌کنه."""
    ok = True
    for candidate in (path, path.with_name(path.name + ".part"), path.with_name(path.name + ".part.meta")):
        try:
            if candidate.exists():
                candidate.unlink()
        except OSError:
            ok = False
    return ok
