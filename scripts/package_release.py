#!/usr/bin/env python3
"""بسته‌بندیِ خروجیِ ساخت برای انتشار (توی CI و روی سیستمِ خودت یکسان کار می‌کنه).

از نسخه‌ی ۱.۰.۰ **دیگر هیچ نسخه‌ی «قابل‌حمل/فلش» ساخته نمی‌شه** (حذف‌شده توسط مالکِ محصول):
نه ``portable.flag``، نه پوشه‌ی ``SmartBusinessData/``، نه ``README-PORTABLE.txt``. داده‌ی کاربر
فقط در پوشه‌ی استانداردِ سیستم‌عامل نگه داشته می‌شه (``app/core/paths.py``).

برای هر ``--os`` این فایل‌ها توی ``--out`` ساخته می‌شن:

* ``windows`` → ``SmartBusinessLocal-<v>-windows.exe`` — تک‌فایلِ خام (دابل‌کلیک و اجرا)
              + ``SmartBusinessLocal-<v>-windows-setup.exe`` — نصب‌کننده‌ی Inno Setup؛
                اگر ورک‌فلو/کاربر *قبل* از این اسکریپت ساخته باشه، همین‌جا فقط پیدا و در
                ``SHA256SUMS.txt`` ثبت می‌شه (مسیرش را با ``--installer`` هم می‌شه داد).
* ``macos``   → ``SmartBusinessLocal-<v>-macos.zip`` — باندلِ ``SmartBusinessLocal.app``.
                زیپ می‌مونید چون macOS فقط همین قالب را برای باندل می‌شناسد و ``_add_tree``/
                ``_add_symlink`` عمداً symlinkها را *دنبال نمی‌کنند*: باندلِ مک پر از symlink است
                و دنبال‌کردنشان هم حجم را چند برابر می‌کند هم باندل را می‌شکند.
* ``linux``   → ``SmartBusinessLocal-<v>-linux.tar.gz`` — قالبِ POSIX. دلیلِ انتخاب:
                بیتِ اجرایی و symlink در tar بخشی از *ساختارِ فایل* است (هر ابزارِ باز‌کردنی آن را
                برمی‌گرداند)، ولی در zip فقط یک bit در ``external_attr`` است که ابزارهای غیرِ GNU
                (``python -m zipfile -e``، بعضی GUIها) آن را نادیده می‌گیرند و فایلِ اجراشدنیِ
                ۰o644 تحویل کاربر می‌شود. tar.gz همان چیزی است که در ``docs/RELEASING.md`` هم
                به کاربر گفته می‌شود: ``tar -xzf``.
* برای هر سه: ``SHA256SUMS.txt`` (نام فایل با ``--sums-name`` عوض می‌شه تا CI بتواند
  سه فهرست را به یک فهرستِ نهاییِ Release تبدیل کند).

قاعده‌ی سخت: بسته **نباید** داده‌ی کاربر داشته باشه (نصبِ تازه = کاملاً خالی) و هیچ مدلِ GGUF
داخلِ نصب‌کننده نمی‌آید — مدل‌ها در زمانِ اجرا توسط خودِ برنامه دانلود می‌شن.

استفاده::

    python scripts/package_release.py --os linux --dist dist --out release
    python scripts/package_release.py --os windows --dist dist --out release --installer release/SmartBusinessLocal-1.0.0-windows-setup.exe
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.version import __version__  # noqa: E402

APP_NAME = "SmartBusinessLocal"
OS_NAMES = ("windows", "macos", "linux")

# قالبِ تحویلِ هر سیستم‌عامل (توضیحِ «چرا» در docstring همین فایل است)
ARCHIVE_FORMAT = {"windows": "exe", "macos": "zip", "linux": "tar.gz"}
SETUP_SUFFIX = "-windows-setup.exe"

# --------------------------------------------- N2: بسته‌ی انتشار = خالی از داده‌ی کاربر -------------

# فایل‌ها/پوشه‌هایی که فقط در پوشه‌ی داده‌ی کاربر معنی دارن؛ هرکدام در درختِ بسته = شکستِ ساخت.
USER_DATA_BASENAMES = frozenset(
    {"secret.key", "bot.log", "products.db", "orders.db", "conversations.db", "heartbeat.json", "settings.json", "update_result.json"}
)
USER_DATA_SUFFIXES = (".db", ".db-wal", ".db-shm", ".db-journal", ".sqlite", ".sqlite3", ".gguf", ".part", ".part.meta")
USER_DATA_DIR_SEGMENTS = frozenset(
    {"backups", "diagnostics", "product_photos", "receipts", "models", "invoices", "exports", "logs"}
)


def user_data_violations(names) -> list:
    """فهرستِ مسیرهای «شبیه داده‌ی کاربر» بینِ نامِ ورودی‌های یک زیپ/tar/درخت.

    از ۱.۰.۰ ``receipts/`` (تصاویرِ رسیدِ هر سفارش) هم ممنوع است — قبلاً فقط دیتابیس چک می‌شد و
    رسیدها که الان فایلِ JPEG/PNG کنارِ دیتابیس می‌نشینن می‌تونستن مسافری باشند.
    """
    bad = []
    for raw in names:
        name = raw.replace("\\", "/")
        is_dir = name.endswith("/")
        parts = [p for p in name.split("/") if p]
        if not parts:
            continue
        ancestors, last = parts[:-1], parts[-1]
        lowered = last.lower()
        if lowered in USER_DATA_BASENAMES or lowered.endswith(USER_DATA_SUFFIXES):
            bad.append(raw)
        elif any(seg.lower() in USER_DATA_DIR_SEGMENTS for seg in list(ancestors) + ([last] if is_dir else [])):
            bad.append(raw)
    return bad


def verify_zip_has_no_user_data(zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        bad = user_data_violations(zf.namelist())
    if bad:
        raise SystemExit(f"❌ «{zip_path.name}» فایلِ داده‌ی کاربر دارد (باید کاملاً خالی باشد): {bad[:5]}")


def verify_tar_has_no_user_data(tar_path: Path) -> None:
    with tarfile.open(tar_path, "r:gz") as tf:
        names = [m.name + ("/" if m.isdir() else "") for m in tf.getmembers()]
    bad = user_data_violations(names)
    if bad:
        raise SystemExit(f"❌ «{tar_path.name}» فایلِ داده‌ی کاربر دارد (باید کاملاً خالی باشد): {bad[:5]}")


def verify_tree_has_no_user_data(root: Path) -> None:
    """درختِ ورودیِ بسته (مثلاً ``app/`` یا ``dist/``) — چیزی که داخلِ exe/installer می‌ره.
    یک ``.gguf`` اینجا یعنی مدلِ AI داخلِ نصب‌کننده می‌رفت: هرگز مجاز نیست."""
    names = [p.relative_to(root).as_posix() + ("/" if p.is_dir() else "") for p in root.rglob("*") if "__pycache__" not in p.parts]
    bad = user_data_violations(names)
    if bad:
        raise SystemExit(f"❌ در «{root}» فایلِ داده‌ی کاربر/مدل هست و داخلِ بسته می‌رفت: {bad[:5]}")


# ------------------------------------------------------------------ پیدا کردنِ خروجیِ ساخت ---------


def find_artifact(os_name: str, dist: Path) -> Path:
    """خروجیِ ``flet pack`` برای این سیستم‌عامل (فایلِ تکی یا پوشه‌ی ``.app``)."""
    candidates = {
        "windows": [dist / f"{APP_NAME}.exe"],
        "macos": [dist / f"{APP_NAME}.app", dist / APP_NAME],
        "linux": [dist / APP_NAME, dist / f"{APP_NAME}.AppImage"],
    }[os_name]
    for path in candidates:
        if path.exists():
            return path
    listing = ", ".join(sorted(p.name for p in dist.iterdir())) if dist.is_dir() else "(پوشه‌ی dist وجود نداره)"
    raise SystemExit(f"خروجیِ ساخت برای {os_name} پیدا نشد؛ داخلِ {dist}: {listing}")


def find_windows_installer(out_dir: Path, version: str, explicit: Path = None) -> Path:
    """نصب‌کننده‌ی Inno Setup (اختیاری). ``.iss`` آن را در همان ``--out`` می‌نویسد
    (``OutputDir=..\\release``) و نامش دقیقاً ``SmartBusinessLocal-<v>-windows-setup.exe`` است."""
    expected = f"{APP_NAME}-{version}{SETUP_SUFFIX}"
    if explicit is not None:
        if Path(explicit).is_file():
            return Path(explicit)
        raise SystemExit(f"نصب‌کننده‌ای که با --installer داده شد پیدا نشد: {explicit}")
    for candidate in (out_dir / expected, ROOT / "release" / expected, ROOT / "installer" / "Output" / expected):
        if candidate.is_file():
            return candidate
    return None


# --------------------------------------------------------------- بیتِ اجرایی / symlink --------------

# روی ویندوز st_mode هیچ‌وقت بیتِ اجرایی ندارد (همه‌چیز ۰o666)، پس «اجرایی بودن» را از
# جادویِ ابتدای فایل / مسیرِ باندلِ مک تشخیص می‌دهیم — وگرنه باینریِ لینوکس/مک بدونِ +x می‌رفت.
_EXEC_MAGICS = (b"\x7fELF", b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\x1f\x8b\x00\x00")


def is_executable_payload(path: Path, arcname: str = "") -> bool:
    if stat.S_IMODE(path.stat().st_mode) & 0o111:
        return True
    if "/Contents/MacOS/" in f"/{arcname}" or arcname.endswith((".sh", ".command", ".bin")):
        return True
    if path.suffix.lower() in (".dll", ".exe"):
        return False
    try:
        with open(path, "rb") as handle:
            head = handle.read(8)
    except OSError:
        return False
    return head.startswith((b"#!/", b"#! ")) or any(head.startswith(magic) for magic in _EXEC_MAGICS)


def effective_mode(path: Path, arcname: str = "") -> int:
    """مجوزی که در باندل ثبت می‌شه؛ روی میزبانِ ویندوزی ۰o755 می‌سازیم چون آن‌جا بیتِ اجرایی وجود ندارد."""
    base = stat.S_IMODE(path.stat().st_mode)
    if is_executable_payload(path, arcname):
        return base | 0o111 if base & 0o111 else 0o755
    return base if base else 0o644


def _add_file(zf: zipfile.ZipFile, source: Path, arcname: str) -> None:
    """یه فایل با حفظِ دسترسیِ اجرایی (برای لینوکس/مک حیاتیه)."""
    mode = effective_mode(source, arcname)
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


def _add_entry(tf: tarfile.TarFile, source: Path, arcname: str) -> None:
    """یک ورودی به tar: symlinkها *دنبال نمی‌شن* (باندل/درختِ PyInstaller می‌تونن symlink داشته باشن)
    و بیتِ اجرایی صریحاً نوشته می‌شه، نه از رویِ شانسِ میزبان."""
    if source.is_symlink():
        info = tf.gettarinfo(arcname=arcname)
        info.name = arcname
        info.type = tarfile.SYMTYPE
        info.linkname = os.readlink(source)
        info.mode = 0o777
        tf.addfile(info)
        return
    if source.is_dir():
        info = tarfile.TarInfo(arcname)
        info.type = tarfile.DIRTYPE
        info.mode = stat.S_IMODE(source.stat().st_mode) or 0o755
        tf.addfile(info)
        return
    info = tarfile.TarInfo(arcname)
    info.type = tarfile.REGTYPE
    info.size = source.stat().st_size
    info.mode = effective_mode(source, arcname)
    info.mtime = int(source.stat().st_mtime)
    with open(source, "rb") as handle:
        tf.addfile(info, handle)


def _add_tree_tar(tf: tarfile.TarFile, source: Path, arc_root: str) -> None:
    for current, dirs, files in os.walk(source, followlinks=False):
        current_path = Path(current)
        rel = current_path.relative_to(source).as_posix()
        base = arc_root if rel == "." else f"{arc_root}/{rel}"
        for name in list(dirs):
            full = current_path / name
            if full.is_symlink():
                _add_entry(tf, full, f"{base}/{name}")
                dirs.remove(name)
            else:
                _add_entry(tf, full, f"{base}/{name}")
        for name in files:
            _add_entry(tf, current_path / name, f"{base}/{name}")


# ------------------------------------------------------------------------ سازنده‌های بسته ----------


def archive_basename(os_name: str, version: str) -> str:
    """نامِ فایلِ تحویلِ هر سیستم‌عامل (جز نصب‌کننده‌ی ویندوز)."""
    if os_name == "windows":
        return f"{APP_NAME}-{version}-windows.exe"
    if os_name == "macos":
        return f"{APP_NAME}-{version}-macos.zip"
    return f"{APP_NAME}-{version}-linux.tar.gz"


def build_zip(artifact: Path, version: str, out_dir: Path, os_name: str = "macos") -> Path:
    """باندلِ ``.app`` (یا هر فایل) را در زیپ می‌بره، با symlinkها و بیت‌های اجراییِ اصلی."""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{APP_NAME}-{version}-{os_name}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        if artifact.is_dir():
            _add_tree(zf, artifact, artifact.name)
        else:
            _add_file(zf, artifact, artifact.name)
    verify_zip_has_no_user_data(target)
    return target


def build_tar_gz(artifact: Path, version: str, out_dir: Path, os_name: str = "linux") -> Path:
    """تک‌فایل/درختِ لینوکس در tar.gz — مجوزها و symlinkها بخشی از خودِ قالب‌اند."""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{APP_NAME}-{version}-{os_name}.tar.gz"
    with tarfile.open(target, "w:gz") as tf:
        if artifact.is_dir():
            _add_tree_tar(tf, artifact, artifact.name)
        else:
            _add_entry(tf, artifact, artifact.name)
    verify_tar_has_no_user_data(target)
    return target


def build_windows_single_exe(artifact: Path, version: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{APP_NAME}-{version}-windows.exe"
    shutil.copy2(artifact, target)
    return target


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_sha256sums(files: list, out_dir: Path, name: str = "SHA256SUMS.txt") -> Path:
    """قالبِ استانداردِ ``sha256sum -c``: «هش  نامِ‌فایل» (دو فاصله = حالتِ باینری)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / name
    lines = [f"{sha256_of(path)}  {path.name}" for path in sorted(files, key=lambda p: p.name)]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def build(os_name: str, dist: Path, out_dir: Path, version: str, installer: Path = None, sums_name: str = "SHA256SUMS.txt") -> list:
    """همه‌ی فایل‌های تحویلِ یک سیستم‌عامل + فهرستِ هشِ آن‌ها."""
    if os_name not in OS_NAMES:
        raise SystemExit(f"سیستم‌عاملِ ناشناخته: {os_name} (مجاز: {', '.join(OS_NAMES)})")
    for source_dir in ("app", "assets"):
        if (ROOT / source_dir).is_dir():
            verify_tree_has_no_user_data(ROOT / source_dir)  # قبل از هر بسته‌بندی

    artifact = find_artifact(os_name, dist)
    verify_tree_has_no_user_data(artifact if artifact.is_dir() else artifact.parent)  # مدل/داده در dist؟

    created = []
    if os_name == "windows":
        created.append(build_windows_single_exe(artifact, version, out_dir))
        setup = find_windows_installer(out_dir, version, installer)
        if setup is not None:
            created.append(setup)
        else:
            print("⚠️ نصب‌کننده‌ی Inno Setup پیدا نشد؛ فقط تک‌فایل منتشر می‌شه "
                  f"(انتظار: {APP_NAME}-{version}{SETUP_SUFFIX} در {out_dir})")
    elif os_name == "macos":
        created.append(build_zip(artifact, version, out_dir, "macos"))
    else:
        created.append(build_tar_gz(artifact, version, out_dir, "linux"))

    created.append(write_sha256sums(created, out_dir, sums_name))
    return created


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="بسته‌بندیِ خروجیِ ساخت برای انتشار (۱.۰.۰، بدونِ نسخه‌ی قابل‌حمل)")
    parser.add_argument("--os", dest="os_name", required=True, choices=list(OS_NAMES))
    parser.add_argument("--dist", default="dist", type=Path)
    parser.add_argument("--out", default="release", type=Path)
    parser.add_argument("--version", default=__version__)
    parser.add_argument("--installer", default=None, type=Path, help="مسیرِ نصب‌کننده‌ی ساخته‌شده‌ی Inno Setup (اختیاری)")
    parser.add_argument("--sums-name", default="SHA256SUMS.txt", help="نامِ فایلِ هش (CI آن را per-OS می‌کند و بعد یکی می‌سازد)")
    args = parser.parse_args(argv)

    for path in build(args.os_name, args.dist, args.out, args.version, args.installer, args.sums_name):
        print(f"ساخته شد: {path} ({path.stat().st_size:,} بایت)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
