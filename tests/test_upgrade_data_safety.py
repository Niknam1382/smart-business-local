"""۱٫۲٫۰ — رگرسیونِ «بعد از آپدیت مدل و تنظیمات ناپدید شد».

دادهٔ ساختگیِ یک نصبِ قبلی (تنظیمات، دیتابیس‌ها، کلید، فایلِ مدل) ساخته می‌شود و مسیرهای ارتقا و شکست آزموده
می‌شوند. هیچ دادهٔ واقعی‌ای وارد تست نمی‌شود و flet لازم نیست.
"""

import hashlib
import json
import os
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

from app.core import backup, data_guard, data_probe, downloader, model_catalog, model_mover, paths, update_selfcheck
from app.core import settings as settings_module
from app.version import __version__ as VERSION

ENTRY = model_catalog.get_entry("qwen35-2b")


class _Anchor:
    def __init__(self, drive: str):
        self.drive = drive


def fake_model(folder: Path, entry=ENTRY) -> Path:
    """فایلِ GGUFِ تُنُک (sparse) با حجمِ دقیقِ کاتالوگ و امضای GGUF — بدونِ مصرفِ واقعیِ دیسک."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / entry.filename
    with open(path, "wb") as handle:
        handle.write(b"GGUF")
        handle.truncate(entry.size_bytes)
    return path


def make_db(path: Path, rows: int = 3) -> None:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY, name TEXT)")
    conn.executemany("INSERT INTO products (name) VALUES (?)", [(f"کالا {i}",) for i in range(rows)])
    conn.commit()
    conn.close()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------ تشخیصِ پوشه‌ی داده ----

def test_stray_files_do_not_count_as_user_data(tmp_path):
    folder = tmp_path / "appdata"
    (folder / "models").mkdir(parents=True)
    (folder / "bot.log").write_text("x", encoding="utf-8")
    (folder / "update_result.json").write_text("{}", encoding="utf-8")
    assert paths._has_user_data(folder) is False  # noqa: SLF001
    (folder / "settings.json").write_text("{}", encoding="utf-8")
    assert paths._has_user_data(folder) is True  # noqa: SLF001


def test_a_stray_file_in_appdata_never_hijacks_an_installed_data_dir(tmp_path, monkeypatch):
    """علتِ قطعیِ یکی از مسیرهای «تنظیمات خالی»: قبلاً هر فایلی در %APPDATA% کافی بود تا داده جابه‌جا شود."""
    appdata = tmp_path / "appdata" / paths.APP_DIR_NAME
    appdata.mkdir(parents=True)
    (appdata / "bot.log").write_text("x", encoding="utf-8")  # فقط یک لاگ، نه داده
    drive_root = tmp_path / "drive"
    install_data = drive_root / paths.APP_DIR_NAME
    install_data.mkdir(parents=True)
    (install_data / "settings.json").write_text('{"user_name": "سارا"}', encoding="utf-8")

    monkeypatch.delenv(paths.ENV_DATA_DIR, raising=False)
    monkeypatch.setattr(paths, "_system_default_dir", lambda: appdata)
    monkeypatch.setattr(paths, "app_anchor", lambda: _Anchor(str(drive_root)))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    directory, mode = paths.resolve_data_dir()
    assert directory == install_data and mode == paths.MODE_INSTALL


def test_known_data_dirs_lists_system_and_install_locations(tmp_path, monkeypatch):
    monkeypatch.delenv(paths.ENV_DATA_DIR, raising=False)
    monkeypatch.setattr(paths, "_system_default_dir", lambda: tmp_path / "a")
    found = paths.known_data_dirs()
    assert tmp_path / "a" in found and len(found) == len(set(found))


# ---------------------------------------------------------- پرسشِ «شروعِ تازه» ----

def test_an_existing_user_is_never_asked_to_start_fresh(tmp_path):
    base = tmp_path / "data"
    base.mkdir()
    (base / "settings.json").write_text(json.dumps({"user_name": "سارا", "onboarding_complete": True}), encoding="utf-8")
    footprint = data_probe.probe(base)
    assert footprint.has_data and data_guard.is_established_install(footprint)


def test_orphan_data_without_setup_still_asks(tmp_path):
    base = tmp_path / "data"
    base.mkdir()
    make_db(base / "products.db")
    footprint = data_probe.probe(base)
    assert footprint.has_data and not data_guard.is_established_install(footprint)


# --------------------------------------------------------------- وصلِ دوباره‌ی مدل ----

def test_lost_model_selection_is_adopted_from_the_models_folder_without_touching_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(tmp_path / "data"))
    model = fake_model(tmp_path / "data" / "models")
    before = (model.stat().st_size, model.stat().st_mtime_ns)
    state = settings_module.AppSettings()
    saves = []
    assert data_guard.adopt_existing_model(state, lambda: saves.append(1)) == "adopted"
    assert state.model_id == ENTRY.id and saves == [1]
    assert (model.stat().st_size, model.stat().st_mtime_ns) == before  # کپی/دانلود/حذفی در کار نیست


def test_selected_model_found_in_another_folder_fixes_the_storage_path(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(tmp_path / "data"))
    other = tmp_path / "ssd" / "my models"  # مسیرِ فاصله‌دار
    fake_model(other)
    state = settings_module.AppSettings(model_id=ENTRY.id)
    assert data_guard.adopt_existing_model(state, None, extra_dirs=[other]) == "relocated"
    assert Path(state.model_storage_path) == other


def test_user_choices_are_respected(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(tmp_path / "data"))
    fake_model(tmp_path / "data" / "models")
    declined = settings_module.AppSettings(ai_declined=True)
    assert data_guard.adopt_existing_model(declined) == "none" and not declined.model_id
    explicit = settings_module.AppSettings(model_file_path=str(tmp_path / "mine.gguf"))
    assert data_guard.adopt_existing_model(explicit) == "none" and not explicit.model_id


def test_a_half_downloaded_model_is_never_adopted(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(tmp_path / "data"))
    folder = tmp_path / "data" / "models"
    folder.mkdir(parents=True)
    (folder / (ENTRY.filename + ".part")).write_bytes(b"GGUF" + b"0" * 2048)
    assert data_guard.adopt_existing_model(settings_module.AppSettings()) == "none"


# ------------------------------------------------------ ارتقای کامل + مسیرهای شکست ----

def seed_previous_version(base: Path) -> dict:
    base.mkdir(parents=True, exist_ok=True)
    cfg = {"user_name": "سارا", "business_mode": "store", "onboarding_complete": True, "data_acknowledged": True,
           "model_id": ENTRY.id, "language": "fa", "close_action": "quit"}
    (base / "settings.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    for name in ("products.db", "orders.db", "conversations.db"):
        make_db(base / name)
    (base / "secret.key").write_bytes(b"k" * 44)
    fake_model(base / "models")
    return cfg


def snapshot(base: Path) -> dict:
    return {p.name: digest(p) for p in base.iterdir() if p.is_file() and p.name != "settings.json"}


def test_upgrade_keeps_settings_databases_key_and_model(tmp_path, monkeypatch):
    base = tmp_path / "data"
    cfg = seed_previous_version(base)
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(base))
    monkeypatch.setattr(backup, "factory_reset", lambda **kw: pytest.fail("factory_reset نباید در ارتقا صدا شود"))
    model = base / "models" / ENTRY.filename
    model_before = (model.stat().st_size, model.stat().st_mtime_ns)
    files_before = snapshot(base)

    state = settings_module.load_settings()  # شروعِ نسخه‌ی تازه
    footprint = data_probe.probe()
    assert data_guard.is_established_install(footprint)
    assert data_guard.adopt_existing_model(state) == "none"  # چیزی برای اصلاح نیست
    assert data_guard.backup_on_version_change(state, lambda: settings_module.save_settings(state), VERSION, background=False)

    after = json.loads((base / "settings.json").read_text(encoding="utf-8"))
    for key, value in cfg.items():
        assert after[key] == value, key  # تنظیمات دست‌نخورده
    assert after["last_run_version"] == VERSION
    assert {k: v for k, v in snapshot(base).items()} == files_before  # دیتابیس‌ها و کلید بایت‌به‌بایت یکی‌اند
    assert (model.stat().st_size, model.stat().st_mtime_ns) == model_before
    zips = list((base / "backups").glob("SmartBusiness-backup-*.zip"))
    assert len(zips) == 1
    with zipfile.ZipFile(zips[0]) as zf:
        assert {"settings.json", "products.db", "orders.db", "conversations.db", "secret.key"} <= set(zf.namelist())
        zf.extract("products.db", tmp_path / "x")
    assert sqlite3.connect(tmp_path / "x" / "products.db").execute("SELECT COUNT(*) FROM products").fetchone()[0] == 3


def test_backup_is_taken_while_a_database_is_open_and_in_wal_mode(tmp_path, monkeypatch):
    base = tmp_path / "data"
    seed_previous_version(base)
    live = sqlite3.connect(base / "products.db")  # اتصالِ باز، مثلِ برنامه‌ی در حال اجرا
    live.execute("PRAGMA journal_mode=WAL")
    live.execute("INSERT INTO products (name) VALUES ('تازه')")
    live.commit()
    path = backup.create_backup(data_dir=base)
    live.close()
    with zipfile.ZipFile(path) as zf:
        zf.extract("products.db", tmp_path / "y")
    assert sqlite3.connect(tmp_path / "y" / "products.db").execute("SELECT COUNT(*) FROM products").fetchone()[0] == 4


def test_failed_backup_never_blocks_startup_or_touches_data(tmp_path, monkeypatch):
    base = tmp_path / "data"
    seed_previous_version(base)
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(base))
    files_before = snapshot(base)

    def boom(**kw):
        raise backup.BackupError("دیسک پر است")

    monkeypatch.setattr(backup, "create_backup", boom)
    state = settings_module.load_settings()
    assert data_guard.backup_on_version_change(state, lambda: None, VERSION, background=False) is True
    assert snapshot(base) == files_before
    assert (base / "models" / ENTRY.filename).is_file()


def test_backup_runs_once_per_version_and_never_for_a_fresh_install(tmp_path, monkeypatch):
    base = tmp_path / "data"
    base.mkdir()
    state = settings_module.AppSettings()
    assert data_guard.backup_on_version_change(state, lambda: None, VERSION, data_dir=base, background=False) is False  # نصبِ تازه
    seed_previous_version(base)
    state = settings_module.AppSettings(onboarding_complete=True)
    assert data_guard.backup_on_version_change(state, lambda: None, VERSION, data_dir=base, background=False) is True
    assert data_guard.backup_on_version_change(state, lambda: None, VERSION, data_dir=base, background=False) is False  # همان نسخه


def test_downloader_hints_are_actionable_and_do_not_replace_the_raw_reason():
    import urllib.error

    err = urllib.error.HTTPError("https://x", 403, "Forbidden", {}, None)
    assert "VPN" in downloader._hint(err)  # noqa: SLF001
    assert "DNS" not in downloader._hint(OSError("getaddrinfo failed")) and "آدرس" in downloader._hint(OSError("getaddrinfo failed"))  # noqa: SLF001
    assert "اینترنت" in downloader._hint(TimeoutError("timed out"))  # noqa: SLF001
    assert downloader._hint(ValueError("x")) == ""  # noqa: SLF001
    assert downloader._reason(TimeoutError()) == "TimeoutError"  # noqa: SLF001  # متنِ خام دست‌نخورده


def test_update_refuses_to_start_when_the_disk_is_too_small(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from app.core import update_install

    monkeypatch.setattr(update_install.shutil, "disk_usage", lambda p: SimpleNamespace(free=100 * 1024 * 1024))
    update_install.ensure_space(tmp_path, 0)  # اندازه‌ی ناشناخته: بی‌اثر
    update_install.ensure_space(tmp_path, 10 * 1024 * 1024)  # جا هست
    with pytest.raises(update_install.InstallError) as err:
        update_install.ensure_space(tmp_path, 200 * 1024 * 1024)
    assert err.value.code == "disk"


# ------------------------------------------------------------ جابه‌جاییِ امنِ مدل ----

def _small_gguf(path: Path, extra: bytes = b"x" * 5000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"GGUF" + extra)
    return path


def test_move_copies_verifies_and_never_deletes_the_source(tmp_path, monkeypatch):
    monkeypatch.setattr(model_mover, "MARGIN_BYTES", 0)
    src = _small_gguf(tmp_path / "قدیمی" / "model.gguf")
    seen = []
    out = model_mover.move_model(src, tmp_path / "درایو جدید" / "my models", progress=lambda d, t: seen.append((d, t)))
    assert out.read_bytes() == src.read_bytes() and src.is_file()  # مبدأ سر جاشه
    assert seen and seen[-1][0] == seen[-1][1]
    assert not list((tmp_path / "درایو جدید").rglob("*.part"))
    assert model_mover.delete_source(src) is True and not src.exists() and out.is_file()  # فقط با فراخوانیِ جدا


def test_move_is_idempotent_and_same_folder_is_a_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(model_mover, "MARGIN_BYTES", 0)
    src = _small_gguf(tmp_path / "a" / "m.gguf")
    assert model_mover.move_model(src, src.parent) == src
    first = model_mover.move_model(src, tmp_path / "b")
    mtime = first.stat().st_mtime_ns
    assert model_mover.move_model(src, tmp_path / "b") == first and first.stat().st_mtime_ns == mtime


def test_move_rejects_a_missing_or_non_gguf_source(tmp_path):
    with pytest.raises(model_mover.MoveError) as err:
        model_mover.move_model(tmp_path / "nope.gguf", tmp_path / "b")
    assert err.value.code == "not_found"
    bad = tmp_path / "a" / "x.gguf"
    bad.parent.mkdir()
    bad.write_bytes(b"NOPE" + b"0" * 100)
    with pytest.raises(model_mover.MoveError) as err:
        model_mover.move_model(bad, tmp_path / "b")
    assert err.value.code == "not_gguf" and bad.is_file()


def test_move_with_too_little_space_changes_nothing(tmp_path, monkeypatch):
    src = _small_gguf(tmp_path / "a" / "m.gguf")
    monkeypatch.setattr(model_mover.shutil, "disk_usage", lambda p: type("U", (), {"free": 10})())
    with pytest.raises(model_mover.MoveError) as err:
        model_mover.move_model(src, tmp_path / "b")
    assert err.value.code == "no_space" and src.is_file() and not list((tmp_path / "b").glob("*.gguf*"))


def test_cancelled_move_leaves_no_partial_file(tmp_path, monkeypatch):
    import threading

    monkeypatch.setattr(model_mover, "MARGIN_BYTES", 0)
    src = _small_gguf(tmp_path / "a" / "m.gguf")
    flag = threading.Event()
    flag.set()
    with pytest.raises(model_mover.MoveError) as err:
        model_mover.move_model(src, tmp_path / "c", cancel=flag)
    assert err.value.code == "cancelled" and src.is_file() and not list((tmp_path / "c").glob("*.gguf*"))


def test_delete_source_only_removes_a_plain_gguf(tmp_path):
    folder = tmp_path / "d"
    folder.mkdir()
    (folder / "note.txt").write_text("x", encoding="utf-8")
    assert model_mover.delete_source(folder) is False and model_mover.delete_source(folder / "note.txt") is False
    assert (folder / "note.txt").is_file()


def test_friendly_errors_explain_the_problem_and_the_next_step():
    import errno
    import sqlite3

    from app.core.friendly_errors import friendly_error

    assert "دسترسی" in friendly_error(PermissionError("[WinError 5]"))
    assert "پیدا نشد" in friendly_error(FileNotFoundError("x"))
    assert "جای خالی" in friendly_error(OSError(errno.ENOSPC, "No space left"))
    assert "VPN" in friendly_error(TimeoutError()) and "VPN" in friendly_error(ConnectionError("x"))
    assert "مشغول" in friendly_error(sqlite3.OperationalError("database is locked"))
    assert friendly_error(ValueError("سفارش پیدا نشد")) == "سفارش پیدا نشد"  # پیامِ فارسیِ خودِ برنامه می‌ماند
    raw = friendly_error(RuntimeError("Traceback (most recent call last): KeyError 'x'"))
    assert "Traceback" not in raw and "KeyError" not in raw  # هرگز traceback/نامِ کلاس
    assert "internet" in friendly_error(ConnectionError("x"), "en")


def test_an_explicit_storage_folder_is_never_flipped_back_automatically(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(tmp_path / "data"))
    old = tmp_path / "data" / "models"
    fake_model(old)
    new = tmp_path / "ssd" / "پوشه ی جدید"
    new.mkdir(parents=True)
    state = settings_module.AppSettings(model_id=ENTRY.id, model_storage_path=str(new))
    assert data_guard.adopt_existing_model(state) == "none"
    assert Path(state.model_storage_path) == new  # انتخابِ کاربر می‌ماند


# ------------------------------------------------- خودآزمونِ آپدیت (قبل/بعد) + مخزنِ آزمایشی ----

def _data_with_rows(base: Path, products: int = 3) -> None:
    base.mkdir(parents=True, exist_ok=True)
    (base / "settings.json").write_text(json.dumps({"a": 1, "b": 2}), encoding="utf-8")
    (base / "secret.key").write_bytes(b"k" * 44)
    conn = sqlite3.connect(base / "products.db")
    conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT)")
    conn.executemany("INSERT INTO products (name) VALUES (?)", [("x",)] * products)
    conn.commit()
    conn.close()


def test_selfcheck_compares_before_and_after_an_update(tmp_path):
    base = tmp_path / "d"
    _data_with_rows(base)
    update_selfcheck.record_startup(None, base, "old-build")
    assert update_selfcheck.compare(None, base, "old-build") is None  # هنوز آپدیتی نیست
    update_selfcheck.record_startup(None, base, "new-build")  # اولین اجرای نسخه‌ی تازه
    result = update_selfcheck.compare(None, base, "new-build")
    assert result["before_version"] == "old-build" and result["now_version"] == "new-build" and result["all_ok"] is True
    assert {r["key"] for r in result["rows"]} >= {"products", "settings_keys", "secret_key"}


def test_selfcheck_flags_lost_data_and_ignores_fresh_installs(tmp_path):
    base = tmp_path / "d"
    update_selfcheck.record_startup(None, tmp_path / "nothing", "old-build")  # نصبِ تازه: هیچ‌چیز نوشته نمی‌شود
    _data_with_rows(base, products=3)
    update_selfcheck.record_startup(None, base, "old-build")
    (base / "secret.key").unlink()  # آپدیتِ «بد»: کلید و محصولات گم شدند
    (base / "products.db").unlink()
    update_selfcheck.record_startup(None, base, "new-build")
    result = update_selfcheck.compare(None, base, "new-build")
    assert result["all_ok"] is False
    assert {r["key"] for r in result["rows"] if not r["ok"]} >= {"secret_key"}


def test_selfcheck_stores_only_counts_never_content(tmp_path):
    base = tmp_path / "d"
    _data_with_rows(base)
    update_selfcheck.record_startup(None, base, "old-build")
    text = (base / update_selfcheck.FILE_CURRENT).read_text(encoding="utf-8")
    assert set(json.loads(text)) <= {"version", "taken_at", "data_dir", "settings_keys", "secret_key", "products", "orders", "backups", "model_name", "model_bytes"}


def test_update_repo_override_only_accepts_owner_slash_name(monkeypatch):
    import importlib

    from app import branding

    original = branding.GITHUB_REPO
    try:
        monkeypatch.setenv("SMART_BUSINESS_UPDATE_REPO", "someone/test-repo.v2")
        assert importlib.reload(branding).GITHUB_REPO == "someone/test-repo.v2"
        for bad in ("evil.com/x/y", "../../x", "a b/c", "noslash", "x/" + "y" * 200):
            monkeypatch.setenv("SMART_BUSINESS_UPDATE_REPO", bad)
            assert importlib.reload(branding).GITHUB_REPO == original, bad
    finally:
        monkeypatch.delenv("SMART_BUSINESS_UPDATE_REPO", raising=False)
        importlib.reload(branding)
