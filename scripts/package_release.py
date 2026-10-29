#!/usr/bin/env python3
"""بسته‌بندیِ خروجیِ ساخت برای انتشار (توی CI و روی سیستمِ خودت یکسان کار می‌کنه).

برای هر سیستم‌عامل این فایل‌ها رو توی ``--out`` می‌سازه:

* ``SmartBusinessLocal-<نسخه>-<os>-portable.zip`` — **نسخه‌ی قابل‌حمل (فلش)**. چیدمانِ داخلش:

      SmartBusinessLocal-Portable/
        portable.flag            ← حالتِ قابل‌حمل رو روشن می‌کنه (app/core/paths.py)
        README-PORTABLE.txt
        SmartBusinessData/       ← همه‌ی داده‌ها (تنظیمات، دیتابیس، کلید) اینجا ذخیره می‌شه
        Windows/ یا macOS/ یا Linux/
          SmartBusinessLocal(.exe|.app)

  برنامه از داخلِ پوشه‌ی سیستم‌عامل اجرا می‌شه و ``portable.flag`` رو یه پوشه بالاتر پیدا می‌کنه؛
  پس zipِ چند سیستم‌عامل رو می‌شه توی *همون* پوشه باز کرد و همه یه ``SmartBusinessData`` مشترک دارن.
* ``SmartBusinessLocal-<نسخه>-windows.exe`` — فقط ویندوز: فایلِ تکیِ خام (دابل‌کلیک و اجرا).

استفاده::

    python scripts/package_release.py --os windows --dist dist --out release
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.paths import PORTABLE_DIR_NAME, PORTABLE_FLAG_NAME  # noqa: E402
from app.version import __version__  # noqa: E402

APP_NAME = "SmartBusinessLocal"
PORTABLE_ROOT = f"{APP_NAME}-Portable"
OS_FOLDERS = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}

README_PORTABLE = """\
Smart Business Local - Portable edition / نسخه‌ی قابل‌حمل
==========================================================

ENGLISH
-------
1. Copy this whole folder to your USB drive (or anywhere you like).
2. Open the folder for your system (Windows / macOS / Linux) and start the app.
3. ALL your data (settings, products, orders, chats and the encryption key) is stored in the
   "SmartBusinessData" folder next to the system folders - not on the computer. Plug the drive into
   any computer and you continue with the same data.

Tips
- Several systems on one drive? Extract each system's portable zip into the SAME folder; they all
  share one SmartBusinessData folder.
- Never run the app on two computers at the same time with the same drive.
- Close the app before you unplug the drive.
- Keep the drive safe: it contains your bot tokens and encryption key. Make a backup from
  Settings > Data & safety.
- If the drive is read-only, the app falls back to the computer's normal data folder.
- macOS: the first time, right-click the app and choose Open (it is not notarized yet).
- Linux: if the file does not start, run: chmod +x SmartBusinessLocal

فارسی
-----
۱. کل این پوشه را روی فلش (یا هر جای دیگر) کپی کن.
۲. پوشه‌ی سیستم‌عاملِ خودت (Windows / macOS / Linux) را باز کن و برنامه را اجرا کن.
۳. همه‌ی اطلاعاتت (تنظیمات، محصولات، سفارش‌ها، مکالمه‌ها و کلید رمزنگاری) توی پوشه‌ی «SmartBusinessData»
   کنارِ پوشه‌های سیستم‌عامل ذخیره می‌شه، نه روی کامپیوتر. فلش را به هر کامپیوتری بزنی با همان اطلاعات
   ادامه می‌دهی.

نکته‌ها
- برای چند سیستم‌عامل روی یک فلش: zipِ قابل‌حملِ هر سیستم را توی «همین پوشه» باز کن؛ همه از یک
  SmartBusinessData مشترک استفاده می‌کنند.
- هرگز با یک فلش، برنامه را هم‌زمان روی دو کامپیوتر اجرا نکن.
- پیش از جدا کردنِ فلش، برنامه را ببند.
- فلش را جای امن نگه دار: توکن ربات‌ها و کلید رمزنگاری رویش است. از «تنظیمات ← داده و ایمنی» پشتیبان بگیر.
- اگر فلش قفل (فقط‌خواندنی) باشد، برنامه به پوشه‌ی معمولیِ داده‌ی کامپیوتر برمی‌گردد.
- مک: بار اول روی برنامه راست‌کلیک کن و Open را بزن (هنوز notarize نشده).
- لینوکس: اگر اجرا نشد: chmod +x SmartBusinessLocal
"""


# --- N2: بسته‌ی انتشار هرگز نباید داده‌ی کاربر داشته باشه (نصبِ تازه = کاملاً خالی) ---
USER_DATA_BASENAMES = frozenset({"secret.key", "bot.log", "products.db", "orders.db", "conversations.db", "heartbeat.json"})
USER_DATA_SUFFIXES = (".db", ".db-wal", ".db-shm", ".db-journal", ".sqlite", ".sqlite3", ".gguf")
USER_DATA_DIR_SEGMENTS = frozenset({"backups", "diagnostics", "product_photos"})


def user_data_violations(names) -> list:
    """فهرستِ مسیرهای «شبیه داده‌ی کاربر» بینِ نامِ ورودی‌های یک زیپ/درخت. خودِ پوشه‌ی خالیِ ``SmartBusinessData/`` مجاز است
    (قابل‌حمل باید با همین پوشه‌ی خالی بیاید) ولی هر چیزی داخلش نه."""
    bad = []
    for raw in names:
        name = raw.replace("\\", "/")
        is_dir = name.endswith("/")
        parts = [p for p in name.split("/") if p]
        if not parts:
            continue
        ancestors, last = parts[:-1], parts[-1]
        if "SmartBusinessData" in ancestors:
            bad.append(raw)  # هر چیزی داخلِ پوشه‌ی داده
        elif is_dir:
            if last in USER_DATA_DIR_SEGMENTS or any(seg in USER_DATA_DIR_SEGMENTS for seg in ancestors):
                bad.append(raw)
        elif last.lower() in USER_DATA_BASENAMES or last.lower().endswith(USER_DATA_SUFFIXES) or any(seg in USER_DATA_DIR_SEGMENTS for seg in ancestors):
            bad.append(raw)
    return bad


def verify_zip_has_no_user_data(zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        bad = user_data_violations(zf.namelist())
    if bad:
        raise SystemExit(f"❌ «{zip_path.name}» فایلِ داده‌ی کاربر دارد (باید کاملاً خالی باشد): {bad[:5]}")


def verify_tree_has_no_user_data(root: Path) -> None:
    """درختِ ورودیِ ساخت (مثلاً ``app/``) — چیزی که داخلِ exe/installer بسته می‌شه."""
    names = [p.relative_to(root).as_posix() + ("/" if p.is_dir() else "") for p in root.rglob("*") if "__pycache__" not in p.parts]
    bad = user_data_violations(names)
    if bad:
        raise SystemExit(f"❌ در «{root}» فایلِ داده‌ی کاربر هست و داخلِ بسته می‌رفت: {bad[:5]}")


def find_artifact(os_name: str, dist: Path) -> Path:
    """خروجیِ flet pack برای این سیستم‌عامل (فایل یا پوشه‌ی .app)."""
    candidates = {
        "windows": [dist / f"{APP_NAME}.exe"],
        "macos": [dist / f"{APP_NAME}.app", dist / APP_NAME],
        "linux": [dist / APP_NAME],
    }[os_name]
    for path in candidates:
        if path.exists():
            return path
    listing = ", ".join(sorted(p.name for p in dist.iterdir())) if dist.is_dir() else "(پوشه‌ی dist وجود نداره)"
    raise SystemExit(f"خروجیِ ساخت برای {os_name} پیدا نشد؛ داخلِ {dist}: {listing}")


def _add_file(zf: zipfile.ZipFile, source: Path, arcname: str) -> None:
    """یه فایل با حفظِ دسترسیِ اجرایی (برای لینوکس/مک حیاتیه)."""
    mode = source.stat().st_mode
    info = zipfile.ZipInfo.from_file(source, arcname)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (mode & 0xFFFF) << 16
    with open(source, "rb") as handle:
        zf.writestr(info, handle.read())


def _add_symlink(zf: zipfile.ZipFile, source: Path, arcname: str) -> None:
    info = zipfile.ZipInfo(arcname)
    info.create_system = 3  # unix
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    zf.writestr(info, os.readlink(source))


def _add_tree(zf: zipfile.ZipFile, source: Path, arc_root: str) -> None:
    """پوشه (مثلاً SmartBusinessLocal.app) رو بدونِ دنبال‌کردنِ symlinkها اضافه می‌کنه — bundleهای مک
    پر از symlink‌ان و دنبال‌کردنشون هم حجم رو چند برابر می‌کنه هم bundle رو خراب."""
    for current, dirs, files in os.walk(source, followlinks=False):
        current_path = Path(current)
        rel = current_path.relative_to(source).as_posix()
        base = arc_root if rel == "." else f"{arc_root}/{rel}"
        for name in list(dirs):
            full = current_path / name
            if full.is_symlink():
                _add_symlink(zf, full, f"{base}/{name}")
                dirs.remove(name)
        for name in files:
            full = current_path / name
            arc = f"{base}/{name}"
            if full.is_symlink():
                _add_symlink(zf, full, arc)
            else:
                _add_file(zf, full, arc)


def build_portable_zip(os_name: str, artifact: Path, version: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{APP_NAME}-{version}-{os_name}-portable.zip"
    folder = OS_FOLDERS[os_name]
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{PORTABLE_ROOT}/{PORTABLE_FLAG_NAME}", "")
        zf.writestr(f"{PORTABLE_ROOT}/README-PORTABLE.txt", README_PORTABLE)
        zf.writestr(f"{PORTABLE_ROOT}/{PORTABLE_DIR_NAME}/", "")
        if artifact.is_dir():
            _add_tree(zf, artifact, f"{PORTABLE_ROOT}/{folder}/{artifact.name}")
        else:
            _add_file(zf, artifact, f"{PORTABLE_ROOT}/{folder}/{artifact.name}")
    return target


def build_raw_asset(os_name: str, artifact: Path, version: str, out_dir: Path):
    """فقط ویندوز: فایلِ تکیِ خام برای دابل‌کلیک. (مک/لینوکس فقط zip دارن تا دسترسیِ اجرایی نپره.)"""
    if os_name != "windows":
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{APP_NAME}-{version}-windows.exe"
    shutil.copy2(artifact, target)
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="بسته‌بندیِ خروجیِ ساخت برای انتشار")
    parser.add_argument("--os", dest="os_name", required=True, choices=sorted(OS_FOLDERS))
    parser.add_argument("--dist", default="dist", type=Path)
    parser.add_argument("--out", default="release", type=Path)
    parser.add_argument("--version", default=__version__)
    args = parser.parse_args(argv)

    artifact = find_artifact(args.os_name, args.dist)
    for source_dir in ("app", "assets"):
        if (ROOT / source_dir).is_dir():
            verify_tree_has_no_user_data(ROOT / source_dir)  # قبل از هر بسته‌بندی
    created = [build_portable_zip(args.os_name, artifact, args.version, args.out)]
    for path in created:
        if path.suffix == ".zip":
            verify_zip_has_no_user_data(path)
    raw = build_raw_asset(args.os_name, artifact, args.version, args.out)
    if raw is not None:
        created.append(raw)
    for path in created:
        print(f"ساخته شد: {path} ({path.stat().st_size:,} بایت)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
