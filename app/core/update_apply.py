"""اعمالِ به‌روزرسانی *بعد از خروجِ برنامه* (N14b) — «helper».

برنامه فایلِ تازه را دانلود و اعتبارسنجی و در یک پوشه‌ی موقت آماده می‌کند، یک «پلان» (JSON) می‌نویسد، یک کپی از خودش را
به‌صورتِ ``--apply-update <plan.json>`` اجرا می‌کند و می‌بنده. این ماژول همان کارِ helper است. فقط stdlib (و psutil اگه باشه)؛
هرگز flet را import نمی‌کند تا سریع بالا بیاد و کاملاً تست‌پذیر باشه (``tests/test_update_apply.py``).

مراحل (برای هر سه نوعِ نصب):

۱. صبر تا پایانِ پردازشِ برنامه (و bootloaderِ PyInstaller)؛ اگه نبست ⇒ هیچ‌کاری نمی‌کنیم (شکست، برنامه سر جاشه).
۲. بازبینیِ SHA256 فایل‌های آماده‌شده (در برابرِ دست‌کاریِ پوشه‌ی موقت)؛ ناجور ⇒ بدونِ تغییر + بازکردنِ نسخه‌ی قبلی.
۳. نصب:
   * ``windows_setup``: ``setup.exe /SILENT /NORESTART /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS`` (نصب‌کننده خودش rollback دارد)؛
   * ``windows_exe`` / ``portable``: هر فایل = کپی به ``<dst>.new`` ← ``<dst>`` به ``<dst>.old`` ← ``.new`` به ``<dst>`` (جایگزینیِ اتمیک)؛
     هر شکستی ⇒ برگشتِ کامل از ``.old``. **فقط فایل‌های فهرستِ پلان لمس می‌شن**؛ ``SmartBusinessData/``، ``portable.flag`` و پوشه‌ی
     داده‌ی سیستم هرگز (پلان آن‌ها را نمی‌شناسد و مسیرهای خارج از ``target_dir`` رد می‌شن).
۴. بازکردنِ نسخه‌ی تازه و «تستِ سلامت»: اگه ظرفِ چند ثانیه با کدِ خروجِ ناصفر بسته شد ⇒ rollback و بازکردنِ نسخه‌ی قبلی.
۵. نوشتنِ ``update_result.json`` (برای پیامِ یک‌باره‌ی برنامه در اجرای بعدی).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable, Optional

PLAN_VERSION = 1
KIND_WINDOWS_SETUP = "windows_setup"
KIND_WINDOWS_EXE = "windows_exe"
KIND_PORTABLE = "portable"
KINDS = (KIND_WINDOWS_SETUP, KIND_WINDOWS_EXE, KIND_PORTABLE)

STATUS_OK = "ok"
STATUS_ROLLED_BACK = "rolled_back"
STATUS_FAILED = "failed"

NEW_SUFFIX = ".new"
OLD_SUFFIX = ".old"
DEFAULT_WAIT_SECONDS = 90.0
DEFAULT_HEALTH_SECONDS = 10.0
SETUP_TIMEOUT_SECONDS = 600.0
SETUP_FLAGS = ("/SILENT", "/SP-", "/NORESTART", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS")

# متغیرهای محیطیِ bootloaderِ PyInstaller (حالتِ onefile): اگه به یک کپیِ دیگر از همان exe ارث برسن، فرزند پوشه‌ی موقتِ پدر را
# (که با خروجِ پدر پاک می‌شه) دوباره استفاده می‌کند و می‌ترکد.
_PYI_ENV_KEYS = ("_MEIPASS2", "_PYI_APPLICATION_HOME_DIR", "_PYI_ARCHIVE_FILE", "_PYI_PARENT_PROCESS_LEVEL", "_PYI_SPLASH_IPC")


class PlanError(Exception):
    """پلانِ به‌روزرسانی نامعتبر است."""


class SwapError(Exception):
    """جایگزینیِ فایل‌ها ناموفق بود (همه‌چیز به حالتِ قبل برگشته)."""


# --------------------------------------------------------------- ابزارهای کوچک ----

def sha256_of(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_rel(rel: str) -> str:
    """مسیرِ نسبیِ امن (پوشه‌ها با ``/``)؛ مطلق، ``..``، درایو، مسیرِ خالی و کاراکترِ کنترلی ⇒ ``PlanError``."""
    text = str(rel or "").replace("\\", "/")
    if not text or any(ord(ch) < 32 for ch in text):
        raise PlanError("مسیرِ فایل نامعتبر است")
    if text.startswith("/") or PureWindowsPath(text).drive or PureWindowsPath(text).root:
        raise PlanError("مسیرِ مطلق مجاز نیست")
    parts = PurePosixPath(text).parts
    if not parts or any(part in ("..", "") for part in parts):
        raise PlanError("مسیرِ فایل نامعتبر است")
    return "/".join(parts)


def _inside(base: Path, rel: str) -> Path:
    path = (base / safe_rel(rel)).resolve()
    root = base.resolve()
    if path != root and root not in path.parents:
        raise PlanError("مسیر از پوشه‌ی مجاز بیرون می‌زند")
    return path


def clean_env(base: Optional[dict] = None) -> dict:
    env = dict(os.environ if base is None else base)
    for key in _PYI_ENV_KEYS:
        env.pop(key, None)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def start_process(argv, *, cwd=None):
    """اجرای مستقل از پردازشِ فعلی (بدونِ پنجره‌ی کنسول؛ با خروجِ ما نمی‌میرد)."""
    kwargs: dict = {
        "cwd": str(cwd) if cwd else None,
        "env": clean_env(),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        )
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen([str(a) for a in argv], **kwargs)


def _win_pid_alive(pid: int) -> bool:  # pragma: no cover — فقط ویندوز و بدونِ psutil
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x00100000, False, int(pid))  # SYNCHRONIZE
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT = هنوز زنده
    finally:
        kernel32.CloseHandle(handle)


def pid_alive(pid: int) -> bool:
    try:
        import psutil
    except ImportError:  # pragma: no cover — psutil جزوِ وابستگی‌های برنامه است
        psutil = None
    if psutil is not None:
        try:
            if not psutil.pid_exists(pid):
                return False
            return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
        except psutil.Error:
            return False
    if sys.platform == "win32":  # pragma: no cover
        return _win_pid_alive(pid)
    try:  # pragma: no cover
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait_for_exit(pids, *, timeout: float, is_alive: Callable[[int], bool] = pid_alive, sleep=time.sleep, clock=time.monotonic, poll: float = 0.25) -> bool:
    """تا مُردنِ همه‌ی ``pids`` صبر می‌کنه؛ ``False`` اگه تا ``timeout`` نمردن."""
    deadline = clock() + timeout
    pending = [int(p) for p in pids if int(p) > 0 and int(p) != os.getpid()]
    while pending:
        pending = [p for p in pending if is_alive(p)]
        if not pending:
            return True
        if clock() >= deadline:
            return False
        sleep(poll)
    return True


def _retry(fn, *, tries: int, delay: float, sleep) -> None:
    """روی ویندوز آنتی‌ویروس/ایندکسر چند لحظه فایل را قفل می‌کنه (PermissionError) ⇒ چند بار با فاصله تلاش."""
    for attempt in range(max(1, tries)):
        try:
            return fn()
        except PermissionError:
            if attempt + 1 >= tries:
                raise
            sleep(delay)


# ------------------------------------------------------------------ جایگزینی ----

@dataclass
class SwapRecord:
    dst: Path
    backup: Optional[Path] = None  # نسخه‌ی قبلی (اگه dst از قبل بود)
    tmp: Optional[Path] = None  # «.new» نیمه‌کاره
    installed: bool = False


def rollback(records, *, sleep=time.sleep, tries: int = 20, delay: float = 0.5) -> None:
    """برگشتِ کامل: به ترتیبِ معکوس. هرگز exception نمی‌ده (هر مورد جداگانه تلاش می‌شه)."""
    for rec in reversed(list(records)):
        try:
            if rec.tmp is not None and rec.tmp.exists():
                rec.tmp.unlink()
        except OSError:
            pass
        try:
            if rec.backup is not None and rec.backup.exists():
                _retry(lambda r=rec: os.replace(r.backup, r.dst), tries=tries, delay=delay, sleep=sleep)
            elif rec.installed and rec.backup is None and rec.dst.exists():
                _retry(lambda r=rec: r.dst.unlink(), tries=tries, delay=delay, sleep=sleep)  # فایلِ کاملاً تازه بود
        except OSError:
            pass


def commit(records) -> None:
    """نسخه‌های «.old» را پاک می‌کند (فقط بعد از موفقیت)."""
    for rec in records:
        if rec.backup is not None:
            try:
                rec.backup.unlink()
            except OSError:
                pass


def swap_files(pairs, *, sleep=time.sleep, tries: int = 20, delay: float = 0.5) -> list:
    """``pairs`` = ``[(src, dst)]``. هر شکست ⇒ rollbackِ کامل و ``SwapError``."""
    records: list = []
    try:
        for src, dst in pairs:
            src, dst = Path(src), Path(dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            rec = SwapRecord(dst=dst, tmp=dst.with_name(dst.name + NEW_SUFFIX))
            records.append(rec)
            _retry(lambda s=src, r=rec: shutil.copy2(s, r.tmp), tries=tries, delay=delay, sleep=sleep)
            if dst.exists():
                backup = dst.with_name(dst.name + OLD_SUFFIX)
                if backup.exists():
                    _retry(lambda b=backup: b.unlink(), tries=tries, delay=delay, sleep=sleep)  # مانده‌ی اجرای ناموفقِ قبلی
                _retry(lambda d=dst, b=backup: os.replace(d, b), tries=tries, delay=delay, sleep=sleep)
                rec.backup = backup
            _retry(lambda r=rec: os.replace(r.tmp, r.dst), tries=tries, delay=delay, sleep=sleep)
            rec.tmp = None
            rec.installed = True
        return records
    except BaseException as exc:
        rollback(records, sleep=sleep, tries=tries, delay=delay)
        raise SwapError(str(exc)) from exc


# -------------------------------------------------------------------- پلان ----

def load_plan(path) -> dict:
    try:
        plan = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PlanError(f"پلان خوانده نشد: {exc}") from exc
    return validate_plan(plan)


def validate_plan(plan) -> dict:
    if not isinstance(plan, dict) or plan.get("plan_version") != PLAN_VERSION:
        raise PlanError("نسخه‌ی پلان پشتیبانی نمی‌شه")
    kind = plan.get("kind")
    if kind not in KINDS:
        raise PlanError("نوعِ نصب ناشناخته است")
    for key in ("current_exe", "src_dir"):
        if not isinstance(plan.get(key), str) or not os.path.isabs(plan[key]):
            raise PlanError(f"«{key}» باید مسیرِ مطلق باشد")
    if not isinstance(plan.get("wait_pids"), list):
        raise PlanError("wait_pids باید فهرست باشد")
    if kind == KIND_WINDOWS_SETUP:
        safe_rel(plan.get("setup_file"))
        if len(str(plan.get("setup_sha256") or "")) != 64:
            raise PlanError("هشِ نصب‌کننده نامعتبر است")
    else:
        if not isinstance(plan.get("target_dir"), str) or not os.path.isabs(plan["target_dir"]):
            raise PlanError("target_dir باید مسیرِ مطلق باشد")
        files = plan.get("files")
        if not isinstance(files, list) or not files:
            raise PlanError("فهرستِ فایل‌ها خالی است")
        for item in files:
            if not isinstance(item, dict) or len(str(item.get("sha256") or "")) != 64:
                raise PlanError("ورودیِ فایل نامعتبر است")
            safe_rel(item.get("src"))
            safe_rel(item.get("dst"))
        safe_rel_or_abs_exe = plan.get("relaunch_exe")
        if not isinstance(safe_rel_or_abs_exe, str) or not os.path.isabs(safe_rel_or_abs_exe):
            raise PlanError("relaunch_exe باید مسیرِ مطلق باشد")
    return plan


def verify_staged(plan: dict) -> None:
    """SHA256 همه‌ی فایل‌های آماده‌شده را دوباره می‌سنجد (پوشه‌ی موقت بین «تأیید» و «نصب» دست‌کاری نشده باشه)."""
    src_dir = Path(plan["src_dir"])
    if plan["kind"] == KIND_WINDOWS_SETUP:
        items = [(plan["setup_file"], plan["setup_sha256"])]
    else:
        items = [(f["src"], f["sha256"]) for f in plan["files"]]
    for rel, expected in items:
        path = _inside(src_dir, rel)
        if not path.is_file():
            raise PlanError(f"فایلِ آماده‌شده نیست: {rel}")
        if sha256_of(path) != str(expected).lower():
            raise PlanError(f"SHA256 فایلِ آماده‌شده نمی‌خونه: {rel}")


def build_pairs(plan: dict) -> list:
    src_dir, target_dir = Path(plan["src_dir"]), Path(plan["target_dir"])
    return [(_inside(src_dir, f["src"]), _inside(target_dir, f["dst"])) for f in plan["files"]]


# ----------------------------------------------------------- اجرای کامل ----

def health_check(proc, *, seconds: float, clock=time.monotonic, sleep=time.sleep, poll: float = 0.25) -> bool:
    """نسخه‌ی تازه تا ``seconds`` زنده بماند ⇒ سالم. زودتر با کدِ خروجِ ناصفر بسته شد ⇒ ناسالم. (بستنِ عادیِ کاربر، کدِ ۰ = سالم.)"""
    deadline = clock() + seconds
    while clock() < deadline:
        code = proc.poll()
        if code is not None:
            return code == 0
        sleep(poll)
    return True


def _wait_proc(proc, *, timeout: float, clock=time.monotonic, sleep=time.sleep, poll: float = 0.25):
    deadline = clock() + timeout
    while clock() < deadline:
        code = proc.poll()
        if code is not None:
            return code
        sleep(poll)
    return None


def write_result(path, **fields) -> None:
    if not path:
        return
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps({**fields, "ts": int(time.time())}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        pass


def apply_plan(plan: dict, *, is_alive: Callable[[int], bool] = pid_alive, spawn=start_process, sleep=time.sleep, clock=time.monotonic, log: Callable[[str], None] = lambda _m: None) -> str:
    """پلان را اعمال می‌کنه و یکی از ``STATUS_*`` را برمی‌گردونه. در پایان همیشه یک نسخه از برنامه (جدید یا قبلی) باز است
    (مگر اینکه خودِ برنامه هنوز بسته نشده باشه)."""
    kind = plan["kind"]
    current_exe = Path(plan["current_exe"])
    health = float(plan.get("health_seconds", DEFAULT_HEALTH_SECONDS))
    base = {"from": plan.get("version_from", ""), "to": plan.get("version_to", "")}
    result_file = plan.get("result_file", "")

    written: dict = {}

    def record(status: str, detail: str = "") -> None:
        """نتیجه را **قبل از بازکردنِ هر نسخه‌ای** می‌نویسه تا همان نسخه‌ای که بالا می‌آد در شروعش پیامِ «انجام شد/برگشت» را بخونه
        (اگه آخر کار نوشته می‌شد، پیام تا اجرای بعدی دیده نمی‌شد)."""
        write_result(result_file, status=status, detail=detail, **base)
        written.update(status=status, detail=detail)

    def finish(status: str, detail: str = "") -> str:
        if written.get("status") != status or written.get("detail") != detail:
            record(status, detail)
        log(f"پایان: {status} {detail}".strip())
        return status

    def reopen_old() -> None:
        try:
            spawn([current_exe], cwd=current_exe.parent)
            log("نسخه‌ی قبلی دوباره باز شد")
        except Exception as exc:  # noqa: BLE001
            log(f"بازکردنِ نسخه‌ی قبلی ناموفق بود: {exc}")

    log(f"شروع: {kind} {base['from']} → {base['to']}")
    if not wait_for_exit(plan["wait_pids"], timeout=float(plan.get("wait_seconds", DEFAULT_WAIT_SECONDS)), is_alive=is_alive, sleep=sleep, clock=clock):
        return finish(STATUS_FAILED, "app_did_not_exit")  # برنامه هنوز باز است؛ دست نمی‌زنیم

    try:
        verify_staged(plan)
    except (PlanError, OSError) as exc:
        log(f"بازبینیِ فایل‌ها رد شد: {exc}")
        record(STATUS_FAILED, "staged_mismatch")
        reopen_old()
        return finish(STATUS_FAILED, "staged_mismatch")

    if kind == KIND_WINDOWS_SETUP:
        setup = _inside(Path(plan["src_dir"]), plan["setup_file"])
        argv = [setup, *SETUP_FLAGS, f"/LOG={Path(plan['src_dir']) / 'setup.log'}"]
        try:
            proc = spawn(argv, cwd=setup.parent)
        except Exception as exc:  # noqa: BLE001
            log(f"اجرای نصب‌کننده ناموفق بود: {exc}")
            record(STATUS_FAILED, "setup_spawn")
            reopen_old()
            return finish(STATUS_FAILED, "setup_spawn")
        code = _wait_proc(proc, timeout=float(plan.get("setup_timeout", SETUP_TIMEOUT_SECONDS)), clock=clock, sleep=sleep)
        if code != 0:  # نصب‌کننده خودش rollback می‌کند؛ نسخه‌ی قبلی سر جاشه
            log(f"نصب‌کننده با کدِ {code} تمام شد")
            record(STATUS_FAILED, f"setup_exit_{code}")
            reopen_old()
            return finish(STATUS_FAILED, f"setup_exit_{code}")
        record(STATUS_OK)
        try:
            spawn([current_exe], cwd=current_exe.parent)
        except Exception as exc:  # noqa: BLE001
            log(f"بازکردنِ نسخه‌ی نصب‌شده ناموفق بود: {exc}")
            return finish(STATUS_OK, "installed_but_not_reopened")
        return finish(STATUS_OK)

    try:
        records = swap_files(build_pairs(plan), sleep=sleep)
    except (SwapError, PlanError, OSError) as exc:
        log(f"جایگزینیِ فایل‌ها ناموفق بود و برگشت داده شد: {exc}")
        record(STATUS_FAILED, "swap_failed")
        reopen_old()
        return finish(STATUS_FAILED, "swap_failed")
    log(f"{len(records)} فایل جایگزین شد")
    record(STATUS_OK)  # موقت: نسخه‌ی تازه همین را در شروعش می‌خونه؛ اگه سالم نبود پایین‌تر با «برگشت» عوض می‌شه

    relaunch = Path(plan["relaunch_exe"])
    try:
        proc = spawn([relaunch], cwd=relaunch.parent)
        healthy = health_check(proc, seconds=health, clock=clock, sleep=sleep)
    except Exception as exc:  # noqa: BLE001
        log(f"بازکردنِ نسخه‌ی تازه ناموفق بود: {exc}")
        healthy = False
    if healthy:
        commit(records)
        return finish(STATUS_OK)
    log("نسخه‌ی تازه درست بالا نیامد؛ برگشت به نسخه‌ی قبلی")
    rollback(records, sleep=sleep)
    record(STATUS_ROLLED_BACK, "unhealthy")
    reopen_old()
    return finish(STATUS_ROLLED_BACK, "unhealthy")


def main(plan_path: str, **hooks) -> int:
    """نقطه‌ی ورودِ ``run.py --apply-update``. کدِ خروج: ۰ موفق، ۱ ناموفق/برگشت، ۲ پلانِ نامعتبر.
    ``hooks`` (``is_alive``/``spawn``/``sleep``/``clock``) فقط برای تست است."""
    try:
        plan = load_plan(plan_path)
    except PlanError:
        return 2
    log_path = plan.get("log")

    def log(message: str) -> None:
        if not log_path:
            return
        try:
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(f"{time.strftime('%H:%M:%S')} {message}\n")
        except OSError:
            pass

    try:
        status = apply_plan(plan, log=log, **hooks)
    except Exception as exc:  # noqa: BLE001 — helper هرگز بی‌صدا نمی‌ترکد
        log(f"خطای پیش‌بینی‌نشده: {exc!r}")
        return 1
    return 0 if status == STATUS_OK else 1
