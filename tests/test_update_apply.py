"""helperِ به‌روزرسانی (N14b): جایگزینیِ امن با rollback، تستِ سلامت و دست‌نخورده ماندنِ داده‌ی کاربر."""

import hashlib
import json
import os
import subprocess
import sys

import pytest

from app.core import update_apply as ua


class Clock:
    """ساعتِ جعلی: sleep فقط زمان را جلو می‌بره (تست‌ها واقعاً منتظر نمی‌مونن)."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Proc:
    def __init__(self, code=None):
        self.code = code

    def poll(self):
        return self.code


class Spawner:
    def __init__(self, *procs):
        self.calls = []
        self.procs = list(procs)

    def __call__(self, argv, *, cwd=None):
        self.calls.append([str(a) for a in argv])
        proc = self.procs.pop(0) if self.procs else Proc(None)
        if isinstance(proc, Exception):
            raise proc
        return proc


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class WatchingSpawner(Spawner):
    """هر بار که برنامه‌ای بالا می‌آد، وضعیتِ فایلِ نتیجه را همان لحظه ثبت می‌کنه."""

    def __init__(self, result_file, *procs):
        super().__init__(*procs)
        self.result_file = result_file
        self.seen = []

    def __call__(self, argv, *, cwd=None):
        try:
            self.seen.append(json.loads(open(self.result_file, encoding="utf-8").read())["status"])
        except (OSError, ValueError, KeyError):
            self.seen.append(None)
        return super().__call__(argv, cwd=cwd)


def run(plan, *procs, alive=lambda pid: False):
    clock = Clock()
    spawn = WatchingSpawner(plan.get("result_file", ""), *procs)
    status = ua.apply_plan(plan, is_alive=alive, spawn=spawn, sleep=clock.sleep, clock=clock)
    return status, spawn


def exe_plan(tmp_path, old=b"OLD-EXE", new=b"NEW-EXE"):
    app = tmp_path / "app"
    app.mkdir()
    exe = app / "SmartBusinessLocal.exe"
    exe.write_bytes(old)
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "SmartBusinessLocal-1.2.0-windows.exe").write_bytes(new)
    plan = {
        "plan_version": ua.PLAN_VERSION,
        "kind": ua.KIND_WINDOWS_EXE,
        "version_from": "1.1.0",
        "version_to": "1.2.0",
        "current_exe": str(exe),
        "relaunch_exe": str(exe),
        "src_dir": str(stage),
        "target_dir": str(app),
        "wait_pids": [999_999],
        "files": [{"src": "SmartBusinessLocal-1.2.0-windows.exe", "dst": "SmartBusinessLocal.exe", "sha256": sha(new)}],
        "result_file": str(tmp_path / "data" / "update_result.json"),
        "health_seconds": 10,
    }
    return plan, exe


def result_of(plan):
    return json.loads(open(plan["result_file"], encoding="utf-8").read())


# --------------------------------------------------------------- مسیر و پلان ----

@pytest.mark.parametrize("rel,expected", [("a.exe", "a.exe"), ("lib\\x.dll", "lib/x.dll"), ("a/b/c.txt", "a/b/c.txt"), ("a//b", "a/b")])
def test_safe_rel_normalizes_nested_paths(rel, expected):
    assert ua.safe_rel(rel) == expected


@pytest.mark.parametrize("rel", ["", "../evil", "a/../../evil", "/etc/passwd", "C:\\Windows\\x.dll", "C:x", "\\\\server\\share\\x", "a\x00b", "./", None])
def test_safe_rel_rejects_escapes(rel):
    with pytest.raises(ua.PlanError):
        ua.safe_rel(rel)


def test_validate_plan_accepts_good_and_rejects_bad(tmp_path):
    plan, _ = exe_plan(tmp_path)
    assert ua.validate_plan(plan) is plan
    for mutate in (
        lambda p: p.update(plan_version=99),
        lambda p: p.update(kind="rm -rf"),
        lambda p: p.update(current_exe="relative/app.exe"),
        lambda p: p.update(wait_pids="1"),
        lambda p: p.update(files=[]),
        lambda p: p["files"][0].update(dst="../SmartBusinessData/settings.json"),
        lambda p: p["files"][0].update(sha256="abc"),
        lambda p: p.update(relaunch_exe="x.exe"),
    ):
        bad = json.loads(json.dumps(plan))
        mutate(bad)
        with pytest.raises(ua.PlanError):
            ua.validate_plan(bad)


def test_load_plan_errors_are_plan_errors(tmp_path):
    with pytest.raises(ua.PlanError):
        ua.load_plan(tmp_path / "missing.json")
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ua.PlanError):
        ua.load_plan(tmp_path / "bad.json")


def test_clean_env_removes_pyinstaller_vars_and_resets():
    env = ua.clean_env({"_MEIPASS2": "/tmp/_MEI1", "_PYI_APPLICATION_HOME_DIR": "x", "KEEP": "1"})
    assert "_MEIPASS2" not in env and "_PYI_APPLICATION_HOME_DIR" not in env
    assert env["KEEP"] == "1" and env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_start_process_runs_a_detached_child_and_returns_a_handle():
    proc = ua.start_process([sys.executable, "-c", "raise SystemExit(0)"])
    assert proc.wait(timeout=30) == 0


# --------------------------------------------------------------------- انتظار ----

def test_wait_for_exit_polls_until_all_gone():
    clock, seen = Clock(), {"n": 0}

    def alive(pid):
        seen["n"] += 1
        return seen["n"] < 4

    assert ua.wait_for_exit([123], timeout=30, is_alive=alive, sleep=clock.sleep, clock=clock) is True
    assert clock.now > 0


def test_wait_for_exit_times_out_and_ignores_own_pid():
    clock = Clock()
    assert ua.wait_for_exit([123], timeout=5, is_alive=lambda p: True, sleep=clock.sleep, clock=clock) is False
    assert ua.wait_for_exit([os.getpid(), 0, -1], timeout=5, is_alive=lambda p: True, sleep=clock.sleep, clock=clock) is True


def test_pid_alive_knows_self_and_a_dead_process():
    assert ua.pid_alive(os.getpid()) is True
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    assert ua.pid_alive(child.pid) is False


# ----------------------------------------------------------------- جایگزینی ----

def test_swap_keeps_old_until_commit_and_commit_cleans_up(tmp_path):
    src, dst = tmp_path / "src.bin", tmp_path / "dst.bin"
    src.write_bytes(b"new")
    dst.write_bytes(b"old")
    records = ua.swap_files([(src, dst)], sleep=lambda s: None)
    assert dst.read_bytes() == b"new" and (tmp_path / "dst.bin.old").read_bytes() == b"old"
    assert not (tmp_path / "dst.bin.new").exists()
    ua.commit(records)
    assert not (tmp_path / "dst.bin.old").exists() and dst.read_bytes() == b"new"


def test_swap_failure_rolls_back_every_file_and_removes_new_ones(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"A-new")
    b.write_bytes(b"B-new")
    existing = tmp_path / "t" / "existing.bin"
    existing.parent.mkdir()
    existing.write_bytes(b"E-old")
    fresh = tmp_path / "t" / "sub" / "fresh.bin"
    with pytest.raises(ua.SwapError):
        ua.swap_files([(a, fresh), (b, existing), (tmp_path / "missing", tmp_path / "t" / "other.bin")], sleep=lambda s: None)
    assert existing.read_bytes() == b"E-old"  # برگشت از .old
    assert not fresh.exists() and not (tmp_path / "t" / "other.bin").exists()
    assert sorted(p.name for p in existing.parent.iterdir() if p.is_file()) == ["existing.bin"]  # نه .old نه .new


def test_swap_clears_a_stale_old_file_from_a_previous_failed_run(tmp_path):
    src, dst = tmp_path / "s", tmp_path / "d"
    src.write_bytes(b"new")
    dst.write_bytes(b"current")
    (tmp_path / "d.old").write_bytes(b"stale")
    ua.swap_files([(src, dst)], sleep=lambda s: None)
    assert (tmp_path / "d.old").read_bytes() == b"current"


def test_swap_retries_when_a_file_is_briefly_locked(tmp_path, monkeypatch):
    src, dst = tmp_path / "s", tmp_path / "d"
    src.write_bytes(b"new")
    dst.write_bytes(b"old")
    real, state, slept = os.replace, {"n": 0}, []

    def flaky(a, b):
        state["n"] += 1
        if state["n"] <= 2:
            raise PermissionError("locked by antivirus")
        return real(a, b)

    monkeypatch.setattr(ua.os, "replace", flaky)
    ua.swap_files([(src, dst)], sleep=slept.append, delay=0.25)
    assert dst.read_bytes() == b"new" and slept == [0.25, 0.25]


def test_swap_gives_up_after_the_retries_and_restores(tmp_path, monkeypatch):
    src, dst = tmp_path / "s", tmp_path / "d"
    src.write_bytes(b"new")
    dst.write_bytes(b"old")
    real = os.replace
    monkeypatch.setattr(ua.os, "replace", lambda a, b: (_ for _ in ()).throw(PermissionError("locked")) if str(a).endswith(".new") else real(a, b))
    with pytest.raises(ua.SwapError):
        ua.swap_files([(src, dst)], sleep=lambda s: None, tries=3)
    monkeypatch.undo()
    assert dst.read_bytes() == b"old"


# ------------------------------------------------------------ اعمالِ کامل (exe) ----

def test_exe_update_replaces_reopens_and_commits(tmp_path):
    plan, exe = exe_plan(tmp_path)
    status, spawn = run(plan, Proc(None))  # نسخه‌ی تازه تا آخرِ تستِ سلامت زنده می‌مونه
    assert status == ua.STATUS_OK
    assert exe.read_bytes() == b"NEW-EXE" and not (exe.parent / "SmartBusinessLocal.exe.old").exists()
    assert spawn.calls == [[str(exe)]]
    assert result_of(plan)["status"] == "ok" and result_of(plan)["to"] == "1.2.0"


def test_a_clean_exit_inside_the_health_window_still_counts_as_healthy(tmp_path):
    plan, exe = exe_plan(tmp_path)
    status, _ = run(plan, Proc(0))  # کاربر فوراً بسته (کدِ ۰)
    assert status == ua.STATUS_OK and exe.read_bytes() == b"NEW-EXE"


def test_unhealthy_new_version_rolls_back_and_reopens_the_old_one(tmp_path):
    plan, exe = exe_plan(tmp_path)
    status, spawn = run(plan, Proc(1))  # نسخه‌ی تازه فوراً با خطا می‌ترکه
    assert status == ua.STATUS_ROLLED_BACK
    assert exe.read_bytes() == b"OLD-EXE" and not (exe.parent / "SmartBusinessLocal.exe.old").exists()
    assert len(spawn.calls) == 2  # یک‌بار نسخه‌ی تازه، یک‌بار نسخه‌ی قبلی
    assert result_of(plan)["status"] == "rolled_back"


def test_spawn_failure_of_the_new_version_also_rolls_back(tmp_path):
    plan, exe = exe_plan(tmp_path)
    status, _ = run(plan, OSError("cannot start"))
    assert status == ua.STATUS_ROLLED_BACK and exe.read_bytes() == b"OLD-EXE"


def test_swap_failure_leaves_the_old_version_and_reopens_it(tmp_path, monkeypatch):
    plan, exe = exe_plan(tmp_path)

    def boom(pairs, **_kw):
        raise ua.SwapError("disk full")

    monkeypatch.setattr(ua, "swap_files", boom)
    status, spawn = run(plan)
    assert status == ua.STATUS_FAILED and exe.read_bytes() == b"OLD-EXE"
    assert spawn.calls == [[str(exe)]]
    assert result_of(plan)["detail"] == "swap_failed"


def test_missing_staged_file_aborts_before_touching_anything(tmp_path):
    plan, exe = exe_plan(tmp_path)
    plan["files"].append({"src": "ghost.dll", "dst": "ghost.dll", "sha256": sha(b"x")})  # فایلِ آماده‌شده وجود نداره
    status, spawn = run(plan)
    assert status == ua.STATUS_FAILED and exe.read_bytes() == b"OLD-EXE"
    assert spawn.calls == [[str(exe)]]
    assert result_of(plan)["detail"] == "staged_mismatch"


def test_tampered_staged_file_is_never_installed(tmp_path):
    plan, exe = exe_plan(tmp_path)
    (tmp_path / "stage" / "SmartBusinessLocal-1.2.0-windows.exe").write_bytes(b"EVIL")
    status, spawn = run(plan)
    assert status == ua.STATUS_FAILED and exe.read_bytes() == b"OLD-EXE"
    assert spawn.calls == [[str(exe)]]  # فقط نسخه‌ی قبلی دوباره باز شد


def test_app_that_does_not_exit_is_left_alone(tmp_path):
    plan, exe = exe_plan(tmp_path)
    plan["wait_seconds"] = 3
    status, spawn = run(plan, alive=lambda pid: True)
    assert status == ua.STATUS_FAILED and spawn.calls == [] and exe.read_bytes() == b"OLD-EXE"
    assert result_of(plan)["detail"] == "app_did_not_exit"


def test_failed_reopen_of_the_old_version_does_not_crash_the_helper(tmp_path):
    plan, exe = exe_plan(tmp_path)
    (tmp_path / "stage" / "SmartBusinessLocal-1.2.0-windows.exe").write_bytes(b"EVIL")
    status, _ = run(plan, OSError("no exe"))
    assert status == ua.STATUS_FAILED


# --------------------------------------------------------------- قابل‌حمل (USB) ----

def test_portable_update_touches_only_the_listed_files_and_never_the_data(tmp_path):
    root = tmp_path / "SmartBusinessLocal-Portable"
    (root / "SmartBusinessData").mkdir(parents=True)
    (root / "Windows").mkdir()
    (root / "macOS").mkdir()
    sentinels = {
        root / "portable.flag": b"",
        root / "README-PORTABLE.txt": b"readme",
        root / "SmartBusinessData" / "settings.json": b'{"user_name": "x"}',
        root / "SmartBusinessData" / "conversations.db": b"SQLite format 3",
        root / "macOS" / "SmartBusinessLocal": b"mac-binary",
    }
    for path, data in sentinels.items():
        path.write_bytes(data)
    exe = root / "Windows" / "SmartBusinessLocal.exe"
    exe.write_bytes(b"OLD")
    tree = tmp_path / "stage" / "tree"
    (tree / "extra").mkdir(parents=True)
    (tree / "SmartBusinessLocal.exe").write_bytes(b"NEW")
    (tree / "extra" / "lib.dll").write_bytes(b"DLL")
    plan = {
        "plan_version": 1, "kind": ua.KIND_PORTABLE, "version_from": "1.1.0", "version_to": "1.2.0",
        "current_exe": str(exe), "relaunch_exe": str(exe), "src_dir": str(tree), "target_dir": str(root / "Windows"),
        "wait_pids": [], "result_file": str(tmp_path / "res.json"),
        "files": [
            {"src": "SmartBusinessLocal.exe", "dst": "SmartBusinessLocal.exe", "sha256": sha(b"NEW")},
            {"src": "extra/lib.dll", "dst": "extra/lib.dll", "sha256": sha(b"DLL")},
        ],
    }
    status, spawn = run(plan, Proc(None))
    assert status == ua.STATUS_OK
    assert exe.read_bytes() == b"NEW" and (root / "Windows" / "extra" / "lib.dll").read_bytes() == b"DLL"
    for path, data in sentinels.items():
        assert path.read_bytes() == data, path  # داده و پرچمِ قابل‌حمل و پوشه‌ی سیستم‌عاملِ دیگر دست‌نخورده
    assert sorted(p.name for p in (root / "Windows").rglob("*") if p.is_file()) == ["SmartBusinessLocal.exe", "lib.dll"]
    assert spawn.calls == [[str(exe)]]


def test_plan_cannot_write_outside_the_target_dir(tmp_path):
    plan, _ = exe_plan(tmp_path)
    plan["files"][0]["dst"] = "../SmartBusinessData/settings.json"
    with pytest.raises(ua.PlanError):
        ua.validate_plan(plan)
    plan["files"][0]["dst"] = "ok.exe"
    plan["files"][0]["src"] = "../../etc/passwd"
    with pytest.raises(ua.PlanError):
        ua.validate_plan(plan)


# ----------------------------------------------------- نصب‌کننده‌ی ویندوز (Inno) ----

def setup_plan(tmp_path, content=b"SETUP"):
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "SmartBusinessLocal-1.2.0-windows-setup.exe").write_bytes(content)
    exe = tmp_path / "Programs" / "SmartBusinessLocal.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"OLD")
    return {
        "plan_version": 1, "kind": ua.KIND_WINDOWS_SETUP, "version_from": "1.1.0", "version_to": "1.2.0",
        "current_exe": str(exe), "src_dir": str(stage), "wait_pids": [],
        "setup_file": "SmartBusinessLocal-1.2.0-windows-setup.exe", "setup_sha256": sha(content),
        "result_file": str(tmp_path / "res.json"),
    }, exe


def test_setup_runs_silently_then_reopens_the_installed_app(tmp_path):
    plan, exe = setup_plan(tmp_path)
    status, spawn = run(plan, Proc(0), Proc(None))
    assert status == ua.STATUS_OK
    setup_call, reopen_call = spawn.calls
    assert setup_call[0].endswith("SmartBusinessLocal-1.2.0-windows-setup.exe")
    for flag in ("/SILENT", "/SP-", "/NORESTART", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"):
        assert flag in setup_call
    assert any(a.startswith("/LOG=") for a in setup_call)
    assert reopen_call == [str(exe)]


def test_failed_setup_reopens_the_untouched_old_app(tmp_path):
    plan, exe = setup_plan(tmp_path)
    status, spawn = run(plan, Proc(5))
    assert status == ua.STATUS_FAILED and result_of(plan)["detail"] == "setup_exit_5"
    assert spawn.calls[-1] == [str(exe)] and exe.read_bytes() == b"OLD"


def test_setup_that_never_finishes_times_out_and_reopens_old(tmp_path):
    plan, exe = setup_plan(tmp_path)
    plan["setup_timeout"] = 20
    status, spawn = run(plan, Proc(None))
    assert status == ua.STATUS_FAILED and spawn.calls[-1] == [str(exe)]


def test_tampered_setup_is_never_executed(tmp_path):
    plan, exe = setup_plan(tmp_path)
    (tmp_path / "stage" / plan["setup_file"]).write_bytes(b"EVIL-SETUP")
    status, spawn = run(plan)
    assert status == ua.STATUS_FAILED
    assert spawn.calls == [[str(exe)]]  # نصب‌کننده‌ی دست‌کاری‌شده اجرا نشد


def test_setup_spawn_error_reopens_old(tmp_path):
    plan, exe = setup_plan(tmp_path)
    status, spawn = run(plan, OSError("blocked by AV"), Proc(None))
    assert status == ua.STATUS_FAILED and spawn.calls[-1] == [str(exe)]


# ------------------------------------------------------------------------ main ----

def test_main_returns_codes_and_writes_a_log(tmp_path):
    plan, exe = exe_plan(tmp_path)
    plan["log"] = str(tmp_path / "update.log")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    clock, spawn = Clock(), Spawner(Proc(None))
    code = ua.main(str(plan_path), is_alive=lambda p: False, spawn=spawn, sleep=clock.sleep, clock=clock)
    assert code == 0 and exe.read_bytes() == b"NEW-EXE"
    assert "OK" in (tmp_path / "update.log").read_text(encoding="utf-8").upper() or "ok" in (tmp_path / "update.log").read_text(encoding="utf-8")


def test_main_exit_codes_for_failure_and_invalid_plan(tmp_path):
    assert ua.main(str(tmp_path / "nope.json")) == 2
    plan, exe = exe_plan(tmp_path)
    (tmp_path / "stage" / "SmartBusinessLocal-1.2.0-windows.exe").write_bytes(b"EVIL")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    clock = Clock()
    assert ua.main(str(plan_path), is_alive=lambda p: False, spawn=Spawner(), sleep=clock.sleep, clock=clock) == 1


def test_main_never_raises_on_unexpected_errors(tmp_path):
    plan, _ = exe_plan(tmp_path)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    def boom(_pid):
        raise RuntimeError("psutil exploded")

    assert ua.main(str(plan_path), is_alive=boom) == 1


def test_run_py_apply_update_flag_runs_the_helper_without_flet(tmp_path):
    """``python run.py --apply-update <پلانِ نامعتبر>`` بدونِ import کردنِ flet با کدِ ۲ تموم می‌شه."""
    result = subprocess.run([sys.executable, "run.py", "--apply-update", str(tmp_path / "nope.json")], capture_output=True, text=True, timeout=60)
    assert result.returncode == 2


# ------------------------------------------- نتیجه پیش از بازکردنِ برنامه نوشته می‌شه ----

def test_result_is_on_disk_before_each_app_is_started(tmp_path):
    """پیامِ «انجام شد/برگشت» را همان نسخه‌ای می‌خونه که بالا می‌آد؛ پس فایل باید قبل از spawn نوشته شده باشه."""
    plan, _exe = exe_plan(tmp_path)
    status, spawn = run(plan, Proc(None))
    assert status == ua.STATUS_OK and spawn.seen == ["ok"]

    (tmp_path / "b").mkdir()
    plan, _exe = exe_plan(tmp_path / "b")
    status, spawn = run(plan, Proc(1))  # نسخه‌ی تازه می‌ترکه ← نسخه‌ی قدیمی با «برگشت» بالا می‌آد
    assert status == ua.STATUS_ROLLED_BACK and spawn.seen == ["ok", "rolled_back"]
    assert result_of(plan)["status"] == "rolled_back"

    (tmp_path / "c").mkdir()
    plan, _exe = exe_plan(tmp_path / "c")
    (tmp_path / "c" / "stage" / "SmartBusinessLocal-1.2.0-windows.exe").write_bytes(b"EVIL")
    status, spawn = run(plan)
    assert status == ua.STATUS_FAILED and spawn.seen == ["failed"]


def test_setup_result_is_written_before_the_installed_app_is_reopened(tmp_path):
    plan, _exe = setup_plan(tmp_path)
    status, spawn = run(plan, Proc(0), Proc(None))
    assert status == ua.STATUS_OK and spawn.seen == [None, "ok"]  # خودِ نصب‌کننده هنوز نتیجه‌ای ندارد؛ برنامه‌ی بازشده دارد
    (tmp_path / "b").mkdir()
    plan, _exe = setup_plan(tmp_path / "b")
    status, spawn = run(plan, Proc(3))
    assert status == ua.STATUS_FAILED and spawn.seen == [None, "failed"]


def test_a_healthy_update_does_not_rewrite_the_result_after_the_app_consumed_it(tmp_path):
    plan, _exe = exe_plan(tmp_path)
    clock = Clock()

    class ConsumingSpawner(Spawner):
        def __call__(self, argv, *, cwd=None):
            proc = super().__call__(argv, cwd=cwd)
            import os as _os

            _os.remove(plan["result_file"])  # برنامه‌ی تازه پیام را خوند و پاک کرد
            return proc

    status = ua.apply_plan(plan, is_alive=lambda p: False, spawn=ConsumingSpawner(Proc(None)), sleep=clock.sleep, clock=clock)
    assert status == ua.STATUS_OK
    assert not os.path.exists(plan["result_file"])  # پیامِ مصرف‌شده دوباره ساخته نمی‌شه (بار بعد تکراری نشون داده نشه)
