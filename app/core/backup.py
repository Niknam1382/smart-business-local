"""پشتیبان‌گیری، بازگردانی، بازنشانی کارخانه و بسته‌ی تشخیصی (diagnostics).

چرا لازمه: همه‌ی داده‌ی صاحب فروشگاه (محصولات، سفارش‌ها، مکالمه‌ها، توکن‌ها) روی یه
سیستمِ خودش‌ه و هیچ سروری نسخه‌ی دومی نداره؛ یه هارد خراب یا یه «بازنشانی» اشتباهی
یعنی از دست رفتنِ همه‌چیز. این ماژول:

* ``create_backup`` — یه زیپِ قابل‌حمل (settings + secret.key + دیتابیس‌ها + manifest).
  دیتابیس‌ها با API رسمیِ ``sqlite3.Connection.backup`` کپی می‌شن (نسخه‌ی سازگار حتی وقتی
  برنامه‌ی اصلی همزمان روی دیتابیس می‌نویسه؛ کپیِ خامِ فایل می‌تونه نصفه‌نیمه باشه).
* ``restore_backup`` — فقط اسم‌های مجاز، بدون ``..``/مسیرِ مطلق (جلوگیری از zip-slip)،
  سقفِ حجمِ بازشده (zip-bomb)، و *قبل از جایگزینی یه پشتیبانِ ایمنی* از وضعیتِ فعلی.
* ``factory_reset`` — پاک‌کردنِ داده‌ها (به‌طور پیش‌فرض بعد از یه پشتیبانِ خودکار؛ پوشه‌ی
  مدل‌های حجیم و پوشه‌ی backups دست‌نخورده می‌مونن).

نکته‌ی مهم درباره‌ی دیتابیس‌ها: فروشگاه‌های برنامه (محصولات/سفارش‌ها/مکالمه‌ها) اتصالِ
SQLite رو باز نگه می‌دارن (هر ترد یکی). **فایلِ دیتابیس هیچ‌وقت حذف یا جایگزین نمی‌شه:**
روی ویندوز حذفِ فایلِ بازِ SQLite خطا می‌ده و روی لینوکس/مک برنامه به نوشتن توی فایلِ
حذف‌شده ادامه می‌داد (داده‌ی بعد از بازنشانی با ری‌استارت گم می‌شد). به‌جاش بازنشانی =
``DELETE`` روی همه‌ی جدول‌ها (با ``secure_delete``) و بازگردانی = API رسمیِ
``sqlite3.Connection.backup`` *داخلِ* همون فایل؛ اتصال‌های باز تغییر رو درجا می‌بینن.
* ``export_diagnostics`` — یه زیپِ بی‌خطر برای ارسال به پشتیبانی/issue گیت‌هاب:
  اطلاعات سیستم، تنظیماتِ بدونِ اسرار و لاگِ پاک‌سازی‌شده.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Optional

from app.core.paths import data_dir_mode, get_app_data_dir
from app.core.redact import redact
from app.version import __version__

logger = logging.getLogger(__name__)

SETTINGS_FILE = "settings.json"
KEY_FILE = "secret.key"
DB_FILES = ("products.db", "orders.db", "conversations.db")
LOG_FILE = "bot.log"
BACKUP_DIR_NAME = "backups"
DIAGNOSTICS_DIR_NAME = "diagnostics"
MODELS_DIR_NAME = "models"
MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA = 1
APP_ID = "smart-business-local"
MAX_RESTORE_BYTES = 1024**3  # سقفِ حجمِ بازشده‌ی یه پشتیبان (۱ گیگابایت)

_ALLOWED_NAMES = frozenset({SETTINGS_FILE, KEY_FILE, MANIFEST_NAME, *DB_FILES})

# الگوهایی که حتی بعد از redact هم باید از بسته‌ی تشخیصی بیرون بمونن
_CARD_RE = re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b")
_API_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+98|0098|0)?9\d{9}(?!\d)")


class BackupError(Exception):
    """خطای قابل‌نمایش به کاربر (پیام فارسی)."""


def _data(data_dir: Optional[Path]) -> Path:
    return Path(data_dir) if data_dir is not None else get_app_data_dir()


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _strip_secret_fields(raw_json: str) -> str:
    """فیلدهای رمزنگاری‌شده (``*_encrypted``) رو خالی می‌کنه — پشتیبانِ «بدون اسرار»
    نباید چیزی داشته باشه که بدون secret.key هم به‌درد نخوره و هم گمراه‌کننده‌ست."""
    try:
        data = json.loads(raw_json)
    except ValueError:
        return raw_json
    if isinstance(data, dict):
        for key in list(data):
            if key.endswith("_encrypted"):
                data[key] = ""
    return json.dumps(data, ensure_ascii=False, indent=2)


def _sqlite_snapshot(src: Path, dst: Path) -> None:
    """کپیِ سازگارِ یه دیتابیس SQLite (حتی وقتی کس دیگه‌ای همزمان می‌نویسه)."""
    source = sqlite3.connect(str(src))
    try:
        target = sqlite3.connect(str(dst))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def create_backup(
    dest: Optional[Path] = None,
    *,
    include_secrets: bool = True,
    data_dir: Optional[Path] = None,
) -> Path:
    """زیپِ پشتیبان می‌سازه و مسیرش رو برمی‌گردونه.

    ``include_secrets=False``: بدون ``secret.key`` و با فیلدهای رمزنگاری‌شده‌ی خالی
    (توکن ربات‌ها، کلید API، …) — مناسب برای اشتراک‌گذاری. پیش‌فرض ``True`` چون
    بازگردانی روی یه سیستمِ دیگه فقط با کلید ممکنه؛ فایل رو جای امن نگه دار."""
    data = _data(data_dir)
    if dest is None:
        backups = data / BACKUP_DIR_NAME
        backups.mkdir(parents=True, exist_ok=True)
        dest = backups / f"SmartBusiness-backup-{_stamp()}.zip"
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    files: list = []
    tmp = Path(tempfile.mkdtemp(prefix="sbl-backup-"))
    try:
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            settings_path = data / SETTINGS_FILE
            if settings_path.is_file():
                raw = settings_path.read_text(encoding="utf-8")
                zf.writestr(SETTINGS_FILE, raw if include_secrets else _strip_secret_fields(raw))
                files.append(SETTINGS_FILE)
            if include_secrets and (data / KEY_FILE).is_file():
                zf.write(data / KEY_FILE, KEY_FILE)
                files.append(KEY_FILE)
            for name in DB_FILES:
                src = data / name
                if src.is_file():
                    snap = tmp / name
                    _sqlite_snapshot(src, snap)
                    zf.write(snap, name)
                    files.append(name)
            manifest = {
                "app": APP_ID,
                "schema": MANIFEST_SCHEMA,
                "app_version": __version__,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "platform": sys.platform,
                "includes_secrets": bool(include_secrets),
                "files": files,
            }
            zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
    except (OSError, sqlite3.Error, zipfile.BadZipFile) as exc:
        dest.unlink(missing_ok=True)
        raise BackupError(f"ساخت پشتیبان ناموفق بود: {exc}") from exc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return dest


def list_backups(data_dir: Optional[Path] = None) -> list:
    """پشتیبان‌های موجود (جدیدترین اول) به‌شکل لیستِ مسیر."""
    folder = _data(data_dir) / BACKUP_DIR_NAME
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)


def inspect_backup(zip_path: Path) -> dict:
    """مانیفستِ یه پشتیبان رو اعتبارسنجی و برمی‌گردونه؛ خطا → ``BackupError``."""
    zip_path = Path(zip_path)
    if not zip_path.is_file() or not zipfile.is_zipfile(zip_path):
        raise BackupError("این فایل یه پشتیبانِ معتبر (زیپ) نیست.")
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        total = 0
        for info in infos:
            name = info.filename
            if name not in _ALLOWED_NAMES:  # مسیر/اسمِ ناشناخته (از جمله ../ و مسیر مطلق)
                raise BackupError(f"فایلِ غیرمجاز داخل پشتیبان: «{name}»")
            total += info.file_size
        if total > MAX_RESTORE_BYTES:
            raise BackupError("حجمِ پشتیبان بیش‌ازحد بزرگه (بیشتر از ۱ گیگابایت).")
        if MANIFEST_NAME not in {i.filename for i in infos}:
            raise BackupError("این زیپ پشتیبانِ «کسب‌وکار هوشمند» نیست (مانیفست ندارد).")
        try:
            manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
        except ValueError as exc:
            raise BackupError("مانیفستِ پشتیبان خراب است.") from exc
    if not isinstance(manifest, dict) or manifest.get("app") != APP_ID:
        raise BackupError("این زیپ پشتیبانِ «کسب‌وکار هوشمند» نیست.")
    schema = manifest.get("schema")
    if not isinstance(schema, int) or schema > MANIFEST_SCHEMA:
        raise BackupError("این پشتیبان با نسخه‌ی جدیدتری از برنامه ساخته شده؛ برنامه رو به‌روز کن.")
    return manifest


def _wipe_db(data: Path, name: str) -> None:
    """همه‌ی ردیف‌های یه دیتابیس رو پاک می‌کنه (بدون حذفِ فایل؛ اتصال‌های باز سالم می‌مونن)."""
    path = data / name
    if not path.is_file():
        return
    try:
        conn = sqlite3.connect(str(path), timeout=15)
    except sqlite3.Error as exc:
        raise BackupError(f"باز کردنِ «{name}» ناموفق بود: {exc}") from exc
    try:
        conn.execute("PRAGMA secure_delete=ON")  # محتوای پاک‌شده با صفر بازنویسی بشه، نه فقط «آزاد»
        conn.execute("PRAGMA foreign_keys=OFF")
        tables = [
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        ]
        with conn:
            for table in tables:
                conn.execute('DELETE FROM "{}"'.format(table.replace('"', '""')))
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone():
                conn.execute("DELETE FROM sqlite_sequence")  # شماره‌ی سفارش/محصول دوباره از ۱ شروع بشه
        try:
            conn.execute("VACUUM")
        except sqlite3.Error:
            pass  # اتصالِ دیگه‌ای هم‌زمان خونده؛ مهم نیست (secure_delete کارِ اصلی رو کرده)
    except sqlite3.Error as exc:
        raise BackupError(
            f"پاک‌کردنِ «{name}» ناموفق بود؛ اول ربات‌ها رو متوقف کن و دوباره امتحان کن. ({exc})"
        ) from exc
    finally:
        conn.close()


def _check_schema_not_newer(source_file: Path, name: str) -> None:
    """پشتیبانی که با نسخه‌ی *جدیدتری* از برنامه ساخته شده رو قبل از دست‌زدن به داده‌ی فعلی رد می‌کنه."""
    from app.core import migrations  # import تنبل: جلوگیری از چرخه

    try:
        found = migrations.file_version(source_file)
        known = migrations.latest_version(name)
    except (sqlite3.Error, KeyError) as exc:
        raise BackupError(f"فایلِ «{name}» داخلِ پشتیبان خراب یا ناشناخته است: {exc}") from exc
    if found > known:
        raise BackupError(
            f"این پشتیبان با نسخه‌ی جدیدتری از برنامه ساخته شده («{name}»: نسخه‌ی اسکیما {found}، این برنامه تا {known}). "
            "برنامه رو به‌روز کن و دوباره امتحان کن؛ داده‌ی فعلی دست‌نخورده موند."
        )


def _upgrade_restored(data: Path, name: str) -> None:
    """بعد از بازگردانیِ پشتیبانِ *قدیمی‌تر*، مهاجرت‌ها رو روی فایلِ بازگردانی‌شده اجرا می‌کنه
    (اتصال‌های بازِ فروشگاه‌ها تغییر رو خودشون می‌بینن)."""
    from app.core import migrations  # import تنبل: جلوگیری از چرخه

    try:
        migrations.ensure_schema(data / name, backup_first=False)  # پشتیبانِ ایمنی قبلاً گرفته شده
    except migrations.MigrationError as exc:
        raise BackupError(f"بازگردانی انجام شد ولی ارتقای «{name}» ناموفق بود: {exc}") from exc


def _restore_db(source_file: Path, data: Path, name: str) -> None:
    """محتوای ``source_file`` رو *داخلِ* دیتابیسِ زنده می‌ریزه (API رسمیِ backup)."""
    try:
        dest = sqlite3.connect(str(data / name), timeout=15)
        try:
            source = sqlite3.connect(str(source_file))
            try:
                source.backup(dest)
            finally:
                source.close()
        finally:
            dest.close()
    except sqlite3.Error as exc:
        raise BackupError(f"بازگردانیِ «{name}» ناموفق بود؛ اول ربات‌ها رو متوقف کن. ({exc})") from exc


def restore_backup(
    zip_path: Path,
    *,
    data_dir: Optional[Path] = None,
    safety_backup: bool = True,
) -> Optional[Path]:
    """پشتیبان رو جایگزینِ داده‌ی فعلی می‌کنه. قبلش (مگر با ``safety_backup=False``) یه
    پشتیبانِ ایمنی از وضعیتِ فعلی ساخته می‌شه و مسیرش برمی‌گرده.

    ربات‌ها باید قبل از صدا زدن متوقف باشن (UI این کار رو می‌کنه) و بعدش برنامه باید
    تنظیمات/دیتابیس‌ها رو دوباره بخونه."""
    manifest = inspect_backup(zip_path)
    data = _data(data_dir)
    safety: Optional[Path] = None
    if safety_backup:
        safety = create_backup(data / BACKUP_DIR_NAME / f"before-restore-{_stamp()}.zip", data_dir=data)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            present = set(zf.namelist())
            for name in manifest.get("files", []):
                if name not in present or name not in _ALLOWED_NAMES or name == MANIFEST_NAME:
                    continue
                staging = data / f"{name}.restoring"
                with zf.open(name) as src, open(staging, "wb") as out:
                    shutil.copyfileobj(src, out)
                if name in DB_FILES:
                    try:
                        _check_schema_not_newer(staging, name)
                        _restore_db(staging, data, name)
                    finally:
                        staging.unlink(missing_ok=True)
                    _upgrade_restored(data, name)
                    continue
                os.replace(staging, data / name)
                if name == KEY_FILE:
                    try:
                        (data / name).chmod(0o600)
                    except OSError:
                        pass
    except (OSError, zipfile.BadZipFile) as exc:
        raise BackupError(f"بازگردانی ناموفق بود: {exc}") from exc
    return safety


def factory_reset(
    *,
    data_dir: Optional[Path] = None,
    keep_models: bool = True,
    make_backup: bool = True,
) -> Optional[Path]:
    """همه‌ی داده‌های کاربر (تنظیمات، کلید، محصولات، سفارش‌ها، مکالمه‌ها، لاگ) رو پاک
    می‌کنه. پیش‌فرض: اول یه پشتیبانِ کامل (با اسرار) داخل ``backups/`` می‌ذاره تا
    اشتباهِ کاربر برگشت‌پذیر باشه، و مدل‌های دانلودشده رو نگه می‌داره (چند گیگ‌ان).

    مسیرِ پشتیبانِ ساخته‌شده (یا ``None``) رو برمی‌گردونه."""
    data = _data(data_dir)
    backup_path = create_backup(data_dir=data) if make_backup else None
    for name in DB_FILES:
        _wipe_db(data, name)
    for name in (SETTINGS_FILE, KEY_FILE):
        try:
            (data / name).unlink(missing_ok=True)
        except OSError as exc:
            raise BackupError(f"نتونستم «{name}» رو پاک کنم: {exc}") from exc
    for log in data.glob(f"{LOG_FILE}*"):
        try:
            log.unlink()
        except OSError:
            pass  # لاگِ در حال استفاده روی ویندوز؛ مهم نیست
    if not keep_models:
        shutil.rmtree(data / MODELS_DIR_NAME, ignore_errors=True)
    return backup_path


def shop_data_reset(*, data_dir: Optional[Path] = None, make_backup: bool = True) -> Optional[Path]:
    """ریستِ «فقط داده‌های فروشگاه» (R10-۶): محصولات، عکس‌های محصول، کلیدهای دیجیتال، سفارش‌ها، سبد و نشستِ چک‌اوت
    پاک می‌شه؛ تنظیمات، توکن‌ها، کلید، مکالمه‌ها و مدل‌ها دست‌نخورده می‌مونن. (فایل‌های تحویلِ دیجیتالی که مالک از
    بیرونِ پوشه‌ی برنامه معرفی کرده پاک نمی‌شن.) مسیرِ پشتیبانِ ساخته‌شده (یا ``None``) رو برمی‌گردونه."""
    data = _data(data_dir)
    backup_path = create_backup(data_dir=data) if make_backup else None
    for name in ("products.db", "orders.db"):
        _wipe_db(data, name)
    shutil.rmtree(data / "product_photos", ignore_errors=True)
    return backup_path


# ------------------------------------------------------------------ تشخیص ----


def scrub(text: str) -> str:
    """لایه‌ی دومِ پاک‌سازی برای بسته‌ی تشخیصی: علاوه بر ``redact`` (توکن/UUID/پروکسی)،
    شماره کارت، کلید ``sk-…``، ایمیل و موبایل هم ***‌دار می‌شن."""
    text = redact(text)
    text = _CARD_RE.sub("****-****-****-****", text)
    text = _API_KEY_RE.sub("***", text)
    text = _EMAIL_RE.sub("***@***", text)
    return _PHONE_RE.sub("09*********", text)


def _redacted_settings(data: Path) -> str:
    path = data / SETTINGS_FILE
    if not path.is_file():
        return "{}"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "{}"
    if not isinstance(raw, dict):
        return "{}"
    clean: dict = {}
    for key, value in raw.items():
        if key.endswith("_encrypted"):
            clean[key] = "set" if value else "empty"
        elif key in ("owner_chats", "user_name", "card_to_card_number", "card_to_card_holder_name", "system_prompt"):
            clean[key] = "<hidden>" if value else ""
        else:
            clean[key] = value
    return json.dumps(clean, ensure_ascii=False, indent=2)


def export_diagnostics(dest: Optional[Path] = None, *, data_dir: Optional[Path] = None) -> Path:
    """زیپِ تشخیصی برای ارسال به پشتیبانی. شامل: info.txt، settings-redacted.json و لاگ‌ها
    (همه پاک‌سازی‌شده). هیچ دیتابیسی (مکالمه/مشتری/سفارش) داخلش نیست."""
    data = _data(data_dir)
    if dest is None:
        folder = data / DIAGNOSTICS_DIR_NAME
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"SmartBusiness-diagnostics-{_stamp()}.zip"
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        import flet

        flet_version = getattr(flet, "__version__", "?")
    except Exception:  # noqa: BLE001
        flet_version = "?"

    info = "\n".join(
        [
            f"app_version: {__version__}",
            f"python: {platform.python_version()}",
            f"platform: {platform.platform()}",
            f"frozen: {bool(getattr(sys, 'frozen', False))}",
            f"data_dir_mode: {data_dir_mode()}",
            f"flet: {flet_version}",
            f"created_at: {time.strftime('%Y-%m-%dT%H:%M:%S')}",
        ]
    )
    try:
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("info.txt", info)
            zf.writestr("settings-redacted.json", _redacted_settings(data))
            for log in sorted(data.glob(f"{LOG_FILE}*")):
                try:
                    zf.writestr(log.name, scrub(log.read_text(encoding="utf-8", errors="replace")))
                except OSError:
                    continue
    except OSError as exc:
        dest.unlink(missing_ok=True)
        raise BackupError(f"ساخت بسته‌ی تشخیصی ناموفق بود: {exc}") from exc
    return dest
