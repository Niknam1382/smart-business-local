"""نصبِ یک‌کلیکیِ به‌روزرسانی (N14b): تشخیصِ نوعِ نصب، دانلودِ محافظت‌شده، اعتبارسنجی، پشتیبان و تحویل به helper.

اصلِ امنیتی: **هیچ فایلی بدونِ امضای معتبر نصب نمی‌شه.** ``SHA256SUMS.txt`` با کلیدِ عمومیِ داخلِ برنامه
(``update_verify.configured_public_key()``) امضا-بررسی می‌شه، بعد هشِ فایلِ دانلودشده با آن مقایسه می‌شه. نبودِ کلید/امضا/فایلِ
مناسب ⇒ حالتِ «دستی» (باز کردنِ صفحه‌ی نسخه در مرورگر)؛ هیچ خطایی بی‌صدا به «نصب» تبدیل نمی‌شه.

حالت‌ها (``Availability.mode``):

* ``auto``     — ویندوز (نصب‌کننده / exe تکی / قابل‌حمل): دانلود ← تأیید ← پشتیبان ← تحویل به helper ← خروجِ برنامه.
* ``download`` — macOS/لینوکس (آزمایشی): فقط دانلود و تأییدِ زیپِ قابل‌حمل در پوشه‌ی Downloads + راهنمای جایگزینی.
* ``manual``   — بدونِ کلید/امضا/فایل، اجرا از سورس، یا headless.

پوشه‌ی داده (``SmartBusinessData/`` یا پوشه‌ی داده‌ی سیستم) در هیچ مرحله‌ای جابه‌جا یا بازنویسی نمی‌شه؛ تنها نوشته‌ی ما در آن
یک پشتیبانِ ``backups/before-update-*.zip`` و (بعد از نصب) فایلِ کوچکِ ``update_result.json`` است.
"""

from __future__ import annotations

import http.client
import io
import json
import logging
import os
import shutil
import stat
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from app.core import backup as backup_mod
from app.core import paths, update_apply, update_verify
from app.core.updater import SIG_ASSET, SUMS_ASSET, Asset, UpdateInfo, clean_version, safe_release_url
from app.version import __version__

logger = logging.getLogger(__name__)

APP_FILE_PREFIX = "SmartBusinessLocal"
PORTABLE_ROOT = "SmartBusinessLocal-Portable"
OS_FOLDERS = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}
WINDOWS_EXE_NAME = "SmartBusinessLocal.exe"

KIND_WINDOWS_SETUP = update_apply.KIND_WINDOWS_SETUP
KIND_WINDOWS_EXE = update_apply.KIND_WINDOWS_EXE
KIND_PORTABLE = update_apply.KIND_PORTABLE
KIND_MANUAL = "manual"

MODE_AUTO = "auto"
MODE_DOWNLOAD = "download"
MODE_MANUAL = "manual"

REASON_OK = "ok"
REASON_NO_KEY = "no_key"
REASON_UNSIGNED = "unsigned"
REASON_NO_ASSET = "no_asset"
REASON_PLATFORM = "platform"
REASON_SOURCE = "source"
REASON_HEADLESS = "headless"
REASON_NOT_WRITABLE = "not_writable"

PHASE_SIGNATURE = "signature"
PHASE_DOWNLOAD = "download"
PHASE_VERIFY = "verify"
PHASE_PREPARE = "prepare"
PHASE_BACKUP = "backup"
PHASE_HANDOFF = "handoff"

MAX_ASSET_BYTES = 800 * 1024 * 1024
MAX_SUMS_BYTES = 256 * 1024
MAX_SIG_BYTES = 4096
MAX_UNPACK_BYTES = 2 * 1024**3
MAX_UNPACK_FILES = 5000
CHUNK_BYTES = 256 * 1024
DOWNLOAD_TIMEOUT = 30.0
KEEP_UPDATE_BACKUPS = 3
STALE_STAGING_SECONDS = 3600
STAGING_PREFIX = "sbl-update-"
RESULT_FILE = "update_result.json"
BACKUP_PREFIX = "before-update-"


class InstallError(Exception):
    """شکستِ نصب؛ ``code`` برای پیامِ کاربر (کلیدِ i18n ``update.error.<code>``) و ``detail`` فقط برای لاگ."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


# --------------------------------------------------------------- تشخیصِ نوعِ نصب ----

@dataclass(frozen=True)
class InstallTarget:
    kind: str
    os_name: str
    exe_path: str = ""
    reason: str = REASON_OK  # برای kind=manual: چرا خودکار نیست


def os_name_for(platform: Optional[str] = None) -> str:
    platform = platform or sys.platform
    if platform.startswith("win"):
        return "windows"
    if platform == "darwin":
        return "macos"
    return "linux"


def _writable(folder: Path) -> bool:
    try:
        return folder.is_dir() and os.access(folder, os.W_OK)
    except OSError:
        return False


def detect_target(
    *,
    frozen: Optional[bool] = None,
    platform: Optional[str] = None,
    exe_path: Optional[str] = None,
    portable_dir: Optional[Path] = None,
    headless: bool = False,
    exists: Callable[[Path], bool] = lambda p: p.exists(),
    writable: Callable[[Path], bool] = _writable,
) -> InstallTarget:
    """نوعِ نصبِ *همین اجرا* را تشخیص می‌دهد. پارامترها برای تست قابلِ تزریق‌اند."""
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    os_name = os_name_for(platform)
    exe = str(exe_path if exe_path is not None else sys.executable)
    if headless:
        return InstallTarget(KIND_MANUAL, os_name, exe, REASON_HEADLESS)
    if not frozen:
        return InstallTarget(KIND_MANUAL, os_name, exe, REASON_SOURCE)
    if os_name != "windows":
        return InstallTarget(KIND_MANUAL, os_name, exe, REASON_PLATFORM)
    exe_dir = Path(exe).parent
    if portable_dir is None:
        portable_dir = paths.find_portable_dir()
    if portable_dir is not None:
        kind = KIND_PORTABLE
    elif exists(exe_dir / "unins000.exe"):
        kind = KIND_WINDOWS_SETUP
    else:
        kind = KIND_WINDOWS_EXE
    if kind != KIND_WINDOWS_SETUP and not writable(exe_dir):
        return InstallTarget(KIND_MANUAL, os_name, exe, REASON_NOT_WRITABLE)
    return InstallTarget(kind, os_name, exe)


def asset_name_for(kind: str, version: str, os_name: str) -> str:
    """نامِ دقیقِ فایلِ مناسبِ این نوعِ نصب (همان نام‌هایی که ``scripts/package_release.py`` و ``.iss`` می‌سازند)."""
    version = clean_version(version)
    if kind == KIND_WINDOWS_SETUP:
        return f"{APP_FILE_PREFIX}-{version}-windows-setup.exe"
    if kind == KIND_WINDOWS_EXE:
        return f"{APP_FILE_PREFIX}-{version}-windows.exe"
    if kind in (KIND_PORTABLE, KIND_MANUAL):
        return f"{APP_FILE_PREFIX}-{version}-{os_name}-portable.zip"
    return ""


@dataclass(frozen=True)
class Availability:
    mode: str
    kind: str
    reason: str = REASON_OK
    asset: Optional[Asset] = None


def assess(info: UpdateInfo, target: InstallTarget, public_key: Optional[str] = None) -> Availability:
    """برای این نسخه‌ی منتشرشده و این نوعِ نصب، چه کاری ممکنه؟"""
    key = update_verify.configured_public_key() if public_key is None else public_key
    if target.kind == KIND_MANUAL and target.reason in (REASON_SOURCE, REASON_HEADLESS, REASON_NOT_WRITABLE):
        return Availability(MODE_MANUAL, target.kind, target.reason)
    if not key:
        return Availability(MODE_MANUAL, target.kind, REASON_NO_KEY)
    if not info.signed:
        return Availability(MODE_MANUAL, target.kind, REASON_UNSIGNED)
    asset = info.asset(asset_name_for(target.kind, info.version, target.os_name))
    if asset is None:
        return Availability(MODE_MANUAL, target.kind, REASON_NO_ASSET)
    if target.kind == KIND_MANUAL:  # macOS/لینوکسِ باینری: دانلودِ تأییدشده، بدونِ نصبِ خودکار
        return Availability(MODE_DOWNLOAD, target.kind, REASON_PLATFORM, asset)
    return Availability(MODE_AUTO, target.kind, REASON_OK, asset)


# --------------------------------------------------------------------- دانلود ----

class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    """هر redirect هم باید https و روی میزبان‌های مجازِ GitHub باشد (جلوگیری از انحرافِ دانلود به سایتِ دیگر)."""

    def __init__(self, url_ok: Callable[[str], bool]):
        super().__init__()
        self._url_ok = url_ok

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        if not self._url_ok(newurl):
            raise urllib.error.URLError("redirect به آدرسِ نامجاز")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url: str, *, url_ok, timeout: float, opener=None):
    if not url_ok(url):
        raise InstallError("unsafe_url", url)
    opener = opener or urllib.request.build_opener(_GuardedRedirect(url_ok))
    request = urllib.request.Request(url, headers={"User-Agent": f"SmartBusinessLocal/{__version__}", "Accept": "application/octet-stream"})
    try:
        return opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as exc:  # قبل از URLError (زیرکلاسِ آن)
        raise InstallError("network", f"http_{exc.code}") from exc
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as exc:
        raise InstallError("network", str(exc)) from exc


def stream_to(
    url: str,
    sink: Callable[[bytes], None],
    *,
    max_bytes: int,
    expected_size: int = 0,
    progress: Optional[Callable[[int, int], None]] = None,
    cancel: Optional[threading.Event] = None,
    url_ok: Callable[[str], bool] = safe_release_url,
    timeout: float = DOWNLOAD_TIMEOUT,
    opener=None,
) -> int:
    """جریانِ دانلود با سقفِ حجم، لغو، و مقایسه‌ی اندازه (Content-Length و اندازه‌ی اعلامیِ API). تعدادِ بایت‌ها را برمی‌گردونه."""
    with _open(url, url_ok=url_ok, timeout=timeout, opener=opener) as response:
        header = (response.headers.get("Content-Length") or "").strip()
        declared = int(header) if header.isdigit() else 0
        total = declared or expected_size
        if (declared and declared > max_bytes) or (expected_size and expected_size > max_bytes):
            raise InstallError("too_large", f"{declared or expected_size}")
        done = 0
        while True:
            if cancel is not None and cancel.is_set():
                raise InstallError("cancelled")
            try:
                chunk = response.read(CHUNK_BYTES)
            except (OSError, http.client.HTTPException) as exc:
                raise InstallError("network", str(exc)) from exc
            if not chunk:
                break
            done += len(chunk)
            if done > max_bytes:
                raise InstallError("too_large", str(done))
            sink(chunk)
            if progress is not None:
                progress(done, total)
    if declared and done != declared:
        raise InstallError("size_mismatch", f"{done}/{declared}")
    if expected_size and done != expected_size:
        raise InstallError("size_mismatch", f"{done}/{expected_size}")
    return done


def download_bytes(url: str, *, max_bytes: int, **kwargs) -> bytes:
    buffer = io.BytesIO()
    stream_to(url, buffer.write, max_bytes=max_bytes, **kwargs)
    return buffer.getvalue()


def download_file(url: str, dest: Path, *, max_bytes: int = MAX_ASSET_BYTES, **kwargs) -> int:
    """به ``dest.part`` می‌نویسه و فقط بعد از دانلودِ کامل به ``dest`` تغییرِ نام می‌ده؛ هر شکستی ⇒ ``.part`` پاک می‌شه."""
    dest = Path(dest)
    part = dest.with_name(dest.name + ".part")
    try:
        with open(part, "wb") as handle:
            size = stream_to(url, handle.write, max_bytes=max_bytes, **kwargs)
        os.replace(part, dest)
        return size
    except InstallError:
        _unlink(part)
        raise
    except OSError as exc:
        _unlink(part)
        raise InstallError("disk", str(exc)) from exc


def _unlink(path: Path) -> None:
    try:
        Path(path).unlink()
    except OSError:
        pass


# ------------------------------------------------------------- بازکردنِ زیپِ قابل‌حمل ----

def extract_portable_tree(zip_path: Path, os_name: str, dest: Path) -> list:
    """فقط پوشه‌ی ``SmartBusinessLocal-Portable/<OS>/`` از زیپِ قابل‌حمل را در ``dest`` باز می‌کنه (بدونِ پیشوند).

    ``SmartBusinessData/``، ``portable.flag`` و READMEها عمداً باز *نمی‌شن* (هرگز لمس نمی‌شن). zip-slip، لینکِ نمادین، سقفِ
    حجم و تعدادِ فایل بررسی می‌شه. خروجی: ``[(rel_posix, sha256)]``."""
    folder = OS_FOLDERS.get(os_name)
    if not folder:
        raise InstallError("unpack", "os")
    prefix = f"{PORTABLE_ROOT}/{folder}/"
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    manifest: list = []
    total = 0
    try:
        with zipfile.ZipFile(zip_path) as archive:
            for member in archive.infolist():
                name = member.filename.replace("\\", "/")
                if not name.startswith(prefix) or member.is_dir():
                    continue
                if stat.S_ISLNK(member.external_attr >> 16):
                    raise InstallError("unpack", "symlink")
                try:
                    rel = update_apply.safe_rel(name[len(prefix):])
                except update_apply.PlanError as exc:
                    raise InstallError("unpack", "path") from exc
                total += member.file_size
                if total > MAX_UNPACK_BYTES or len(manifest) >= MAX_UNPACK_FILES:
                    raise InstallError("unpack", "too_big")
                target = dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, open(target, "wb") as out:
                    shutil.copyfileobj(source, out)
                manifest.append((rel, update_apply.sha256_of(target)))
    except zipfile.BadZipFile as exc:
        raise InstallError("unpack", "bad_zip") from exc
    except OSError as exc:
        raise InstallError("disk", str(exc)) from exc
    if not manifest:
        raise InstallError("unpack", "empty")
    return manifest


# ----------------------------------------------------------------- پلان و helper ----

def _wait_pids() -> list:
    """پردازشِ خودمان + (اگه PyInstaller onefile باشه) پردازشِ bootloaderِ پدر که تا آخر فایلِ exe را قفل نگه می‌داره."""
    pids = [os.getpid()]
    try:
        import psutil

        parent = psutil.Process(os.getpid()).parent()
        if parent is not None and getattr(sys, "frozen", False) and os.path.normcase(parent.exe()) == os.path.normcase(sys.executable):
            pids.append(parent.pid)
    except Exception:  # noqa: BLE001 — فقط یک بهینه‌سازی است
        pass
    return pids


def launch_helper(plan_path: Path, *, exe: Optional[str] = None, spawn=update_apply.start_process, copy=shutil.copy2) -> None:
    """یک کپی از exe را کنارِ پلان می‌گذاره و با ``--apply-update`` اجرا می‌کنه (تا خودِ exeِ اصلی بعد از خروج آزاد باشه)."""
    exe_path = Path(exe or sys.executable)
    helper_dir = Path(plan_path).parent / "helper"
    helper_dir.mkdir(parents=True, exist_ok=True)
    helper_exe = helper_dir / exe_path.name
    copy(exe_path, helper_exe)
    spawn([helper_exe, "--apply-update", str(plan_path)], cwd=helper_dir)


def prune_update_backups(data_dir: Optional[Path] = None, keep: int = KEEP_UPDATE_BACKUPS) -> None:
    folder = (Path(data_dir) if data_dir is not None else paths.get_app_data_dir()) / backup_mod.BACKUP_DIR_NAME
    try:
        old = sorted(folder.glob(f"{BACKUP_PREFIX}*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)[keep:]
    except OSError:
        return
    for path in old:
        _unlink(path)


def cleanup_stale_staging(temp_root: Optional[Path] = None, older_than: float = STALE_STAGING_SECONDS) -> int:
    """پوشه‌های موقتِ ``sbl-update-*`` قدیمی (اجراهای ناتمام) را پاک می‌کنه؛ تعدادِ پاک‌شده را برمی‌گردونه."""
    root = Path(temp_root or tempfile.gettempdir())
    removed = 0
    try:
        candidates = list(root.glob(f"{STAGING_PREFIX}*"))
    except OSError:
        return 0
    for folder in candidates:
        try:
            if folder.is_dir() and time.time() - folder.stat().st_mtime > older_than:
                shutil.rmtree(folder, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


def consume_update_result(data_dir: Optional[Path] = None, current_version: str = __version__) -> Optional[dict]:
    """نتیجه‌ی آخرین به‌روزرسانی را (یک‌بار) می‌خونه و فایل را پاک می‌کنه. ``None`` اگه چیزی نبود یا به این نسخه ربط نداشت."""
    path = (Path(data_dir) if data_dir is not None else paths.get_app_data_dir()) / RESULT_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    finally:
        _unlink(path)
    if not isinstance(data, dict) or data.get("status") not in (update_apply.STATUS_OK, update_apply.STATUS_ROLLED_BACK, update_apply.STATUS_FAILED):
        return None
    if data["status"] == update_apply.STATUS_OK and clean_version(str(data.get("to", ""))) != clean_version(current_version):
        return None  # مثلاً کاربر نسخه‌ی قدیمی را دستی باز کرده؛ پیامِ «انجام شد» گمراه‌کننده می‌شد
    return {"status": data["status"], "from": str(data.get("from", "")), "to": str(data.get("to", "")), "detail": str(data.get("detail", ""))}


# --------------------------------------------------------------- هماهنگ‌کننده ----

@dataclass(frozen=True)
class InstallResult:
    status: str  # "restart" (helper راه افتاد؛ برنامه باید بسته بشه) | "downloaded" (فایلِ تأییدشده ذخیره شد)
    path: str = ""
    backup: str = ""


Progress = Callable[[str, Optional[float]], None]


class UpdateInstaller:
    """یک نصبِ هم‌زمان؛ دومین ``install`` تا پایانِ اولی ``InstallError("busy")`` می‌گیره (قفل در برابرِ دوکلیک)."""

    def __init__(
        self,
        *,
        target: Optional[InstallTarget] = None,
        public_key: Optional[str] = None,
        data_dir: Optional[Path] = None,
        temp_root: Optional[Path] = None,
        downloads_dir: Optional[Path] = None,
        url_ok: Callable[[str], bool] = safe_release_url,
        opener=None,
        spawn_helper: Callable[[Path], None] = launch_helper,
        backup_fn: Callable[..., Path] = backup_mod.create_backup,
        wait_pids: Callable[[], list] = _wait_pids,
        headless: bool = False,
    ):
        self._target = target
        self._headless = headless
        self._key = update_verify.configured_public_key() if public_key is None else public_key
        self._data_dir = Path(data_dir) if data_dir is not None else None
        self._temp_root = Path(temp_root) if temp_root is not None else None
        self._downloads_dir = Path(downloads_dir) if downloads_dir is not None else None
        self._url_ok = url_ok
        self._opener = opener
        self._spawn_helper = spawn_helper
        self._backup_fn = backup_fn
        self._wait_pids = wait_pids
        self._lock = threading.Lock()
        self._cancel = threading.Event()

    # ---- وضعیت
    @property
    def target(self) -> InstallTarget:
        if self._target is None:
            self._target = detect_target(headless=self._headless)
        return self._target

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    def availability(self, info: UpdateInfo) -> Availability:
        return assess(info, self.target, self._key)

    def cancel(self) -> None:
        self._cancel.set()

    # ---- مراحل
    def _data(self) -> Path:
        return self._data_dir if self._data_dir is not None else paths.get_app_data_dir()

    def _http(self, **extra) -> dict:
        return {"url_ok": self._url_ok, "opener": self._opener, "cancel": self._cancel, **extra}

    def _fetch_verified(self, info: UpdateInfo, av: Availability, dest: Path, progress: Progress) -> str:
        """امضا ← دانلودِ فایل ← هش. خروجی: SHA256ی که با امضا تأیید شد."""
        sums_asset, sig_asset = info.asset(SUMS_ASSET), info.asset(SIG_ASSET)
        if sums_asset is None or sig_asset is None or av.asset is None:
            raise InstallError("unsupported", "assets")
        progress(PHASE_SIGNATURE, None)
        sums = download_bytes(sums_asset.url, max_bytes=MAX_SUMS_BYTES, **self._http())
        sig = download_bytes(sig_asset.url, max_bytes=MAX_SIG_BYTES, **self._http()).decode("ascii", "ignore")
        if not update_verify.verify_signature(sums, sig, self._key):  # قبل از دانلودِ فایلِ بزرگ شکست بخور
            raise InstallError("verify", "signature")
        progress(PHASE_DOWNLOAD, 0.0)

        def on_bytes(done: int, total: int) -> None:
            progress(PHASE_DOWNLOAD, (done / total) if total else None)

        download_file(av.asset.url, dest, expected_size=av.asset.size, progress=on_bytes, **self._http())
        progress(PHASE_VERIFY, None)
        try:
            update_verify.verify_asset(dest, av.asset.name, sums, sig, self._key)
        except update_verify.VerifyError as exc:
            _unlink(dest)
            raise InstallError("verify", str(exc)) from exc
        return update_verify.sha256_file(dest)

    def _downloads_target(self) -> Path:
        if self._downloads_dir is not None:
            return self._downloads_dir
        home = Path.home()
        return home / "Downloads" if (home / "Downloads").is_dir() else home

    def _make_backup(self, progress: Progress) -> str:
        progress(PHASE_BACKUP, None)
        try:
            data = self._data()
            folder = data / backup_mod.BACKUP_DIR_NAME
            folder.mkdir(parents=True, exist_ok=True)
            dest = folder / f"{BACKUP_PREFIX}{time.strftime('%Y%m%d-%H%M%S')}.zip"
            created = self._backup_fn(dest, data_dir=data)
            prune_update_backups(data)
            return str(created)
        except Exception as exc:  # noqa: BLE001 — بدونِ پشتیبان، نصب نمی‌کنیم
            raise InstallError("backup", str(exc)) from exc

    def _build_plan(self, info: UpdateInfo, av: Availability, staging: Path, sha: str) -> dict:
        target = self.target
        exe = Path(target.exe_path)
        plan: dict = {
            "plan_version": update_apply.PLAN_VERSION,
            "kind": av.kind,
            "version_from": __version__,
            "version_to": clean_version(info.version),
            "current_exe": str(exe),
            "src_dir": str(staging),
            "wait_pids": self._wait_pids(),
            "wait_seconds": update_apply.DEFAULT_WAIT_SECONDS,
            "health_seconds": update_apply.DEFAULT_HEALTH_SECONDS,
            "result_file": str(self._data() / RESULT_FILE),
            "log": str(staging / "update.log"),
        }
        assert av.asset is not None
        if av.kind == KIND_WINDOWS_SETUP:
            plan.update(setup_file=av.asset.name, setup_sha256=sha)
        elif av.kind == KIND_WINDOWS_EXE:
            plan.update(
                target_dir=str(exe.parent),
                relaunch_exe=str(exe),
                files=[{"src": av.asset.name, "dst": exe.name, "sha256": sha}],
            )
        else:  # KIND_PORTABLE
            manifest = extract_portable_tree(staging / av.asset.name, target.os_name, staging / "tree")
            if WINDOWS_EXE_NAME not in dict(manifest):
                raise InstallError("unpack", "no_exe")
            # اگه کاربر نامِ exe را عوض کرده باشه، نسخه‌ی تازه همان نام را می‌گیره (دو exe کنارِ هم نمی‌مونه)
            rename = {WINDOWS_EXE_NAME: exe.name}
            plan.update(
                src_dir=str(staging / "tree"),
                target_dir=str(exe.parent),
                relaunch_exe=str(exe),
                files=[{"src": rel, "dst": rename.get(rel, rel), "sha256": digest} for rel, digest in manifest],
            )
        return plan

    def install(self, info: UpdateInfo, on_progress: Optional[Progress] = None, before_handoff: Optional[Callable[[], None]] = None) -> InstallResult:
        """نصب را کامل انجام می‌ده (blocking؛ در thread صدا بزن). موفقیت ⇒ ``InstallResult``؛ شکست ⇒ ``InstallError``.

        ``restart``: helper راه افتاده؛ تماس‌گیرنده باید *فوراً* برنامه را ببنده. ``before_handoff`` (مثلاً توقفِ ربات‌ها) بعد از
        پشتیبان و درست قبل از راه‌اندازیِ helper صدا زده می‌شه."""
        progress: Progress = on_progress or (lambda _phase, _frac: None)
        av = self.availability(info)
        if av.mode == MODE_MANUAL or av.asset is None:
            raise InstallError("unsupported", av.reason)
        if not self._lock.acquire(blocking=False):
            raise InstallError("busy")
        self._cancel.clear()
        staging: Optional[Path] = None
        handed_off = False
        try:
            staging = Path(tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=str(self._temp_root) if self._temp_root else None))
            sha = self._fetch_verified(info, av, staging / av.asset.name, progress)
            if av.mode == MODE_DOWNLOAD:
                folder = self._downloads_target()
                folder.mkdir(parents=True, exist_ok=True)
                final = folder / av.asset.name
                shutil.move(str(staging / av.asset.name), str(final))
                return InstallResult("downloaded", path=str(final))
            progress(PHASE_PREPARE, None)
            plan = self._build_plan(info, av, staging, sha)
            backup_path = self._make_backup(progress)
            if self._cancel.is_set():
                raise InstallError("cancelled")
            if before_handoff is not None:
                try:
                    before_handoff()
                except Exception:  # noqa: BLE001 — توقفِ ربات‌ها نباید نصبِ تأییدشده را بشکنه
                    logger.warning("before_handoff ناموفق بود", exc_info=True)
            progress(PHASE_HANDOFF, None)
            plan_path = staging / "plan.json"
            plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                self._spawn_helper(plan_path)
            except OSError as exc:
                raise InstallError("launch", str(exc)) from exc
            handed_off = True
            return InstallResult("restart", backup=backup_path)
        except InstallError:
            raise
        except OSError as exc:
            raise InstallError("disk", str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            logger.warning("نصبِ به‌روزرسانی با خطای پیش‌بینی‌نشده شکست خورد", exc_info=True)
            raise InstallError("unexpected", repr(exc)) from exc
        finally:
            if staging is not None and not handed_off:  # در حالتِ موفقِ restart، helper هنوز به این پوشه نیاز داره
                shutil.rmtree(staging, ignore_errors=True)
            self._lock.release()
