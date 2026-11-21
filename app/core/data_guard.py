"""محافظِ داده‌ی کاربر هنگامِ ارتقا (نسخه ۱٫۲٫۰).

علتِ گزارش‌شده‌ی «بعد از آپدیت مدل و تنظیمات ناپدید شد»:

* ``data_acknowledged`` برای هر کاربرِ قدیمی ``False`` است؛ پس بعد از آپدیت صفحه‌ی «داده‌ی قبلی پیدا شد»
  می‌آمد و دکمه‌ی «شروعِ تازه» (``backup.factory_reset``) فقط یک کلیک با پاک‌شدنِ تنظیمات و کلید فاصله داشت.
* با خالی‌شدنِ تنظیماتِ ``model_id``، فایلِ مدلِ سالمِ روی دیسک دیگر انتخاب نبود و «گم‌شده» به نظر می‌رسید.

این ماژول فقط stdlib است (flet را import نمی‌کند) تا بی‌پنجره تست شود. هیچ چیزی را پاک نمی‌کند.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable, Optional

from app.core import downloader, model_catalog, paths

logger = logging.getLogger(__name__)

_MIN_GGUF_BYTES = 1_000_000


def is_established_install(footprint) -> bool:
    """کاربری که قبلاً معرفی را تمام کرده/نامش را داده «نصبِ تازه» نیست؛ ارتقا نباید ازش چیزی بپرسد."""
    return bool(getattr(footprint, "onboarding_complete", False) or getattr(footprint, "user_name_set", False))


def _model_dirs(settings, extra_dirs=()) -> list:
    dirs: list = []
    try:
        dirs.append(Path(settings.get_model_storage_dir()))
    except Exception:  # noqa: BLE001
        pass
    for base in paths.known_data_dirs():
        dirs.append(base / "models")
    dirs.extend(Path(d) for d in extra_dirs)
    unique: list = []
    for item in dirs:
        if item not in unique:
            unique.append(item)
    return [d for d in unique if _is_dir(d)]


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _gguf_files(folder: Path) -> list:
    out: list = []
    try:
        for item in folder.glob("*.gguf"):
            if item.is_file() and not item.is_symlink() and item.stat().st_size >= _MIN_GGUF_BYTES:
                out.append(item)
    except OSError:
        pass
    return out


def adopt_existing_model(settings, save: Optional[Callable[[], None]] = None, extra_dirs=()) -> str:
    """مدلِ موجود روی دیسک را دوباره به تنظیمات وصل می‌کند؛ هرگز دانلود/کپی/حذف نمی‌کند.

    برمی‌گرداند: ``"adopted"`` (انتخابِ خالی بود و مدلِ موجود انتخاب شد)، ``"relocated"`` (مدلِ انتخاب‌شده در پوشه‌ی
    دیگری پیدا شد و مسیرِ ذخیره اصلاح شد) یا ``"none"``."""
    dirs = _model_dirs(settings, extra_dirs)
    if not dirs:
        return "none"
    model_id = (getattr(settings, "model_id", "") or "").strip()
    explicit = (getattr(settings, "model_file_path", "") or "").strip()

    if explicit:
        return "none"  # فایلِ واردشده‌ی خودِ کاربر؛ همان را دست نمی‌زنیم

    if model_id:
        entry = model_catalog.get_entry(model_id)
        if entry is None:
            return "none"
        current = Path(settings.get_model_storage_dir())
        if downloader.is_downloaded(current / entry.filename, entry.expected_size):
            return "none"
        if (getattr(settings, "model_storage_path", "") or "").strip():
            return "none"  # پوشه را خودِ کاربر انتخاب کرده؛ بی‌اجازه برنمی‌گردانیمش (انتقال/نگه‌داشتن در تنظیمات است)
        for folder in dirs:
            if folder != current and downloader.is_downloaded(folder / entry.filename, entry.expected_size):
                settings.model_storage_path = str(folder)
                _save(save)
                return "relocated"
        return "none"

    if getattr(settings, "ai_declined", False):
        return "none"

    best = None  # (quality, size, folder, entry)
    for folder in dirs:
        for entry in model_catalog.entries():
            if downloader.is_downloaded(folder / entry.filename, entry.expected_size):
                key = (entry.quality, entry.size_bytes)
                if best is None or key > best[0]:
                    best = (key, folder, entry)
    if best is not None:
        _key, folder, entry = best
        settings.model_id = entry.id
        if folder != Path(settings.get_model_storage_dir()):
            settings.model_storage_path = str(folder)
        _save(save)
        return "adopted"

    # فایلِ GGUFِ غیرکاتالوگ: فقط اگر دقیقاً یکی باشد (حدسِ مبهم نمی‌زنیم)
    candidates: list = []
    for folder in dirs:
        for item in _gguf_files(folder):
            if downloader.is_downloaded(item) and item not in candidates:
                candidates.append(item)
    if len(candidates) == 1:
        settings.model_file_path = str(candidates[0])
        _save(save)
        return "adopted"
    return "none"


def _save(save: Optional[Callable[[], None]]) -> None:
    if save is None:
        return
    try:
        save()
    except Exception:  # noqa: BLE001 — ذخیره‌نشدنِ این اصلاح، برنامه را نشکند
        logger.warning("ذخیره‌ی اصلاحِ مسیرِ مدل شکست خورد", exc_info=True)


def backup_on_version_change(settings, save: Callable[[], None], version: str, *, data_dir: Optional[Path] = None, background: bool = True) -> bool:
    """اولین اجرای هر نسخه‌ی تازه روی داده‌ی موجود، یک پشتیبانِ کاملِ (سازگار با SQLite) ``backups/`` می‌سازد.

    فقط برای نصبِ موجود (``settings.json`` وجود داشته باشد). ``True`` یعنی پشتیبان شروع شد."""
    from app.core import backup

    previous = (getattr(settings, "last_run_version", "") or "").strip()
    if previous == version:
        return False
    base = Path(data_dir) if data_dir is not None else paths.get_app_data_dir()
    existing = (base / "settings.json").is_file() and bool(previous or getattr(settings, "onboarding_complete", False))
    settings.last_run_version = version
    _save(save)
    if not existing:
        return False

    def work() -> None:
        try:
            backup.create_backup(data_dir=base)
        except Exception:  # noqa: BLE001 — شکستِ پشتیبان مانعِ اجرا نیست؛ فقط لاگ
            logger.warning("پشتیبانِ خودکارِ تغییرِ نسخه ساخته نشد", exc_info=True)

    if background:
        threading.Thread(target=work, name="smart-business-version-backup", daemon=True).start()
    else:
        work()
    return True
