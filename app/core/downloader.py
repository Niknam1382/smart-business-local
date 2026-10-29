"""
دانلود فایل با گزارش پیشرفت — بدون وابستگی جانبی (فقط urllib از کتابخونه‌ی
استاندارد پایتون). برای دانلود مدل‌های GGUF (چند صد مگابایت تا چند گیگابایت)
از هاگینگ‌فیس استفاده می‌شه.

فایل ابتدا با پسوند .part نوشته می‌شه و فقط در پایانِ موفق، با rename اتمی
به نام نهایی تبدیل می‌شه — یعنی یه دانلود نیمه‌کاره هیچ‌وقت به‌عنوان فایل
کامل اشتباه گرفته نمی‌شه.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

CHUNK_SIZE = 1024 * 256  # ۲۵۶ کیلوبایت در هر خوندن


class DownloadError(Exception):
    pass


class DownloadCancelled(Exception):
    pass


def download_file(
    url: str,
    dest_path: Path,
    on_progress: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    timeout: float = 30.0,
) -> Path:
    """فایل رو از url به dest_path دانلود می‌کنه.

    on_progress(downloaded_bytes, total_bytes) بعد از هر chunk صدا زده
    می‌شه؛ total_bytes ممکنه ۰ باشه اگه سرور Content-Length نداده باشه.
    should_cancel() اگه در هر لحظه True برگردونه، دانلود متوقف و
    DownloadCancelled پرتاب می‌شه (فایل .part ناقص پاک می‌شه).
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_name(dest_path.name + ".part")

    request = urllib.request.Request(url, headers={"User-Agent": "SmartBusinessLocal/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            total = int(response.headers.get("Content-Length", 0) or 0)
            downloaded = 0
            with open(tmp_path, "wb") as f:
                while True:
                    if should_cancel is not None and should_cancel():
                        raise DownloadCancelled()
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if on_progress is not None:
                        on_progress(downloaded, total)
    except DownloadCancelled:
        tmp_path.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        tmp_path.unlink(missing_ok=True)
        raise DownloadError(str(exc)) from exc

    tmp_path.replace(dest_path)  # rename اتمی — فقط حالا فایل «کامل» حساب می‌شه
    return dest_path


def is_downloaded(dest_path: Path, expected_min_bytes: int = 1_000_000) -> bool:
    """چک ساده‌ی سلامت: فایل باشه و حداقل یه اندازه‌ی معقول داشته باشه
    (جلوگیری از قبول‌کردن یه فایل خطای HTML کوچیک به‌جای مدل واقعی)."""
    try:
        return dest_path.exists() and dest_path.stat().st_size >= expected_min_bytes
    except OSError:
        return False


GGUF_MAGIC = b"GGUF"


def verify_gguf(path: Path, expected_size_bytes: int | None = None, size_tolerance: float = 0.1) -> tuple[bool, str]:
    """اعتبارسنجی واقعی فایل دانلودشده — نه فقط اینکه «یه فایلی هست».

    دو چیز رو چک می‌کنه: (۱) ۴ بایت اول باید امضای GGUF باشه (اگه یه صفحه‌ی
    خطای HTML به‌جای مدل دانلود شده باشه، همین‌جا رد می‌شه)، (۲) اگه حجم
    مورد انتظار داده شده باشه، حجم واقعی فایل نباید بیش از حد باهاش فاصله
    داشته باشه (نشونه‌ی دانلود ناقص/قطع‌شده).

    برمی‌گردونه: (سالم است؟, پیام توضیحی به فارسی در صورت مشکل)
    """
    try:
        if not path.exists():
            return False, "فایل پیدا نشد."
        with open(path, "rb") as f:
            head = f.read(4)
        if head != GGUF_MAGIC:
            return False, "فایل دانلودشده یک مدل معتبر نیست (احتمالاً دانلود قطع یا خراب شده)."
        if expected_size_bytes:
            actual = path.stat().st_size
            diff_ratio = abs(actual - expected_size_bytes) / expected_size_bytes
            if diff_ratio > size_tolerance:
                return False, (
                    f"حجم فایل با حجم مورد انتظار فاصله‌ی زیادی داره "
                    f"({actual / (1024**3):.2f} GB به‌جای حدود "
                    f"{expected_size_bytes / (1024**3):.2f} GB) — احتمالاً دانلود ناقصه."
                )
        return True, ""
    except OSError as exc:
        return False, f"خطا در خوندن فایل: {exc}"


def delete_model(path: Path) -> bool:
    """فایل مدل (و فایل .part نیمه‌کاره‌ی احتمالی) رو حذف می‌کنه."""
    ok = True
    for p in (path, path.with_name(path.name + ".part")):
        try:
            if p.exists():
                p.unlink()
        except OSError:
            ok = False
    return ok
