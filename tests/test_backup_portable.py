"""حالت قابل‌حمل (Portable) + پشتیبان‌گیری/بازگردانی/بازنشانی/تشخیص."""

import json
import sqlite3
import sys
import zipfile

import pytest

from app.core import backup, paths
from app.core.backup import BackupError


# ----------------------------------------------------------------- پوشه‌ی داده ----


def test_default_is_system_dir(isolated_appdata):
    assert paths.data_dir_mode() == paths.MODE_SYSTEM
    assert paths.get_app_data_dir().parent == isolated_appdata or paths.get_app_data_dir().name == paths.APP_DIR_NAME
    assert not paths.is_portable()


def test_env_override_wins(tmp_path, monkeypatch):
    target = tmp_path / "custom-data"
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(target))
    assert paths.get_app_data_dir() == target
    assert target.is_dir()
    assert paths.data_dir_mode() == paths.MODE_ENV


def test_portable_flag_next_to_app(tmp_path, monkeypatch):
    anchor = tmp_path / "usb"
    anchor.mkdir()
    (anchor / paths.PORTABLE_FLAG_NAME).write_text("")
    monkeypatch.setattr(paths, "app_anchor", lambda: anchor)
    assert paths.get_app_data_dir() == anchor.resolve() / paths.PORTABLE_DIR_NAME
    assert paths.is_portable()


def test_portable_dir_found_above_exe_when_frozen(tmp_path, monkeypatch):
    """چیدمان فلش: SmartBusinessData کنارِ پوشه‌ی هر سیستم‌عامل؛ exe یه پوشه پایین‌تره."""
    drive = tmp_path / "drive"
    (drive / "SmartBusinessData").mkdir(parents=True)
    exe_dir = drive / "Windows"
    exe_dir.mkdir()
    monkeypatch.setattr(paths, "app_anchor", lambda: exe_dir)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert paths.find_portable_dir() == drive.resolve() / "SmartBusinessData"
    assert paths.is_portable()


def test_source_run_does_not_climb_parents(tmp_path, monkeypatch):
    drive = tmp_path / "drive"
    (drive / "SmartBusinessData").mkdir(parents=True)
    project = drive / "project"
    project.mkdir()
    monkeypatch.setattr(paths, "app_anchor", lambda: project)
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert paths.find_portable_dir() is None


def test_unwritable_portable_dir_falls_back_to_system(tmp_path, monkeypatch):
    anchor = tmp_path / "usb"
    anchor.mkdir()
    (anchor / paths.PORTABLE_FLAG_NAME).write_text("")
    monkeypatch.setattr(paths, "app_anchor", lambda: anchor)
    monkeypatch.setattr(paths, "_is_writable_dir", lambda p: False)
    assert paths.data_dir_mode() == paths.MODE_SYSTEM


def test_secret_key_lives_in_portable_dir(tmp_path, monkeypatch):
    """کلیدِ رمزنگاری باید همراه داده جابه‌جا بشه، وگرنه توکن‌ها روی سیستمِ دیگه باز نمی‌شن."""
    from app.core import crypto

    anchor = tmp_path / "usb"
    anchor.mkdir()
    (anchor / paths.PORTABLE_FLAG_NAME).write_text("")
    monkeypatch.setattr(paths, "app_anchor", lambda: anchor)
    token = crypto.encrypt("123456:ABCDEF-secret-token-value-xyz")
    assert (anchor / paths.PORTABLE_DIR_NAME / "secret.key").is_file()
    # «سیستمِ دیگر»: همون پوشه، بدون هیچ حالتِ قبلی
    assert crypto.decrypt(token) == "123456:ABCDEF-secret-token-value-xyz"


# ------------------------------------------------------------------ پشتیبان ----


def _seed(data):
    data.mkdir(parents=True, exist_ok=True)
    (data / "settings.json").write_text(
        json.dumps(
            {
                "user_name": "سارا",
                "api_key_encrypted": "gAAAA-secret",
                "telegram_bot_token_encrypted": "gAAAA-token",
                "language": "fa",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (data / "secret.key").write_bytes(b"k" * 44)
    for name in backup.DB_FILES:
        conn = sqlite3.connect(str(data / name))
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO t (v) VALUES (?)", (f"داده‌ی {name}",))
        conn.commit()
        conn.close()
    (data / "bot.log").write_text("2026 INFO app: hello 6037-9911-2233-4455 09123456789", encoding="utf-8")


def _count_rows(db):
    conn = sqlite3.connect(str(db))
    try:
        return conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    finally:
        conn.close()


def _rows(db):
    conn = sqlite3.connect(str(db))
    try:
        return [r[0] for r in conn.execute("SELECT v FROM t")]
    finally:
        conn.close()


def test_backup_roundtrip(tmp_path):
    data = tmp_path / "data"
    _seed(data)
    zip_path = backup.create_backup(data_dir=data)
    assert zip_path.parent == data / "backups"
    manifest = backup.inspect_backup(zip_path)
    assert manifest["includes_secrets"] is True
    assert set(manifest["files"]) == {"settings.json", "secret.key", *backup.DB_FILES}

    # خراب کردن داده، بعد بازگردانی
    for name in backup.DB_FILES:
        sqlite3.connect(str(data / name)).execute("DROP TABLE t")
    (data / "settings.json").write_text("{}", encoding="utf-8")
    safety = backup.restore_backup(zip_path, data_dir=data)
    assert safety is not None and safety.is_file()  # پشتیبانِ ایمنی از وضعیتِ قبل از بازگردانی
    assert _rows(data / "orders.db") == ["داده‌ی orders.db"]
    assert json.loads((data / "settings.json").read_text(encoding="utf-8"))["user_name"] == "سارا"
    assert (data / "secret.key").read_bytes() == b"k" * 44


def test_backup_without_secrets(tmp_path):
    data = tmp_path / "data"
    _seed(data)
    zip_path = backup.create_backup(tmp_path / "share.zip", include_secrets=False, data_dir=data)
    with zipfile.ZipFile(zip_path) as zf:
        assert "secret.key" not in zf.namelist()
        saved = json.loads(zf.read("settings.json").decode("utf-8"))
    assert saved["api_key_encrypted"] == ""
    assert saved["telegram_bot_token_encrypted"] == ""
    assert saved["user_name"] == "سارا"  # فیلدهای غیرمحرمانه می‌مونن


def test_backup_is_consistent_snapshot_of_live_db(tmp_path):
    data = tmp_path / "data"
    _seed(data)
    live = sqlite3.connect(str(data / "orders.db"))  # یه اتصالِ باز (برنامه در حال کار)
    live.execute("INSERT INTO t (v) VALUES ('live-row')")
    live.commit()
    zip_path = backup.create_backup(tmp_path / "b.zip", data_dir=data)
    live.close()
    out = tmp_path / "out"
    out.mkdir()
    backup.restore_backup(zip_path, data_dir=out, safety_backup=False)
    assert "live-row" in _rows(out / "orders.db")


def test_restore_rejects_malicious_zip(tmp_path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../escape.txt", "x")
        zf.writestr("manifest.json", json.dumps({"app": "smart-business-local", "schema": 1, "files": []}))
    with pytest.raises(BackupError):
        backup.inspect_backup(evil)
    assert not (tmp_path / "escape.txt").exists()


def test_restore_rejects_foreign_and_newer_zip(tmp_path):
    foreign = tmp_path / "foreign.zip"
    with zipfile.ZipFile(foreign, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"app": "something-else", "schema": 1, "files": []}))
    with pytest.raises(BackupError):
        backup.inspect_backup(foreign)

    newer = tmp_path / "newer.zip"
    with zipfile.ZipFile(newer, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"app": "smart-business-local", "schema": 99, "files": []}))
    with pytest.raises(BackupError):
        backup.inspect_backup(newer)

    notzip = tmp_path / "notzip.zip"
    notzip.write_text("hello")
    with pytest.raises(BackupError):
        backup.inspect_backup(notzip)


def test_restore_rejects_zip_bomb(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "MAX_RESTORE_BYTES", 100)
    data = tmp_path / "data"
    _seed(data)
    zip_path = backup.create_backup(tmp_path / "b.zip", data_dir=data)
    with pytest.raises(BackupError):
        backup.inspect_backup(zip_path)


def test_factory_reset_makes_backup_and_wipes(tmp_path):
    data = tmp_path / "data"
    _seed(data)
    (data / "models").mkdir()
    (data / "models" / "m.gguf").write_bytes(b"x" * 10)
    safety = backup.factory_reset(data_dir=data)
    assert safety is not None and safety.is_file()
    for name in ("settings.json", "secret.key", "bot.log"):
        assert not (data / name).exists(), name
    for name in backup.DB_FILES:  # فایل می‌مونه (اتصال‌های باز)، ولی خالیه
        assert _count_rows(data / name) == 0, name
    assert (data / "models" / "m.gguf").is_file()  # مدل‌ها نگه داشته می‌شن
    assert (data / "backups").is_dir()
    # و قابل‌برگشته
    backup.restore_backup(safety, data_dir=data, safety_backup=False)
    assert _rows(data / "products.db") == ["داده‌ی products.db"]


def test_factory_reset_without_backup_can_drop_models(tmp_path):
    data = tmp_path / "data"
    _seed(data)
    (data / "models").mkdir()
    (data / "models" / "m.gguf").write_bytes(b"x")
    assert backup.factory_reset(data_dir=data, make_backup=False, keep_models=False) is None
    assert not (data / "models").exists()
    assert not (data / "backups").exists()


def test_list_backups_newest_first(tmp_path):
    data = tmp_path / "data"
    _seed(data)
    first = backup.create_backup(data / "backups" / "a.zip", data_dir=data)
    second = backup.create_backup(data / "backups" / "b.zip", data_dir=data)
    import os

    os.utime(first, (1, 1))
    assert backup.list_backups(data) == [second, first]


def test_diagnostics_has_no_secrets_or_customer_data(tmp_path):
    data = tmp_path / "data"
    _seed(data)
    out = backup.export_diagnostics(data_dir=data)
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        blob = "\n".join(zf.read(n).decode("utf-8") for n in names)
    assert {"info.txt", "settings-redacted.json", "bot.log"} <= names
    assert not any(n.endswith(".db") or n == "secret.key" for n in names)
    assert "gAAAA" not in blob  # مقدار رمزنگاری‌شده هم درز نمی‌کنه
    assert "6037-9911-2233-4455" not in blob and "09123456789" not in blob
    assert "app_version" in blob


# --------------------------------- اتصال‌های باز (فروشگاه‌های برنامه) ----


def test_reset_and_restore_work_while_stores_keep_connections_open(tmp_path, monkeypatch):
    """باگِ واقعی: فروشگاه‌ها اتصالِ SQLite رو باز نگه می‌دارن. حذفِ فایل روی ویندوز خطا می‌ده و
    روی لینوکس/مک برنامه توی فایلِ پاک‌شده می‌نویسه. بازنشانی/بازگردانی باید *درجا* انجام بشه."""
    from app.core.orders import OrderStore
    from app.core.products import ProductStore

    data = tmp_path / "data"
    data.mkdir()
    products = ProductStore(db_path=data / "products.db")
    orders = OrderStore(db_path=data / "orders.db", product_store=products)
    pid = products.add("هدفون", 500_000, 5)
    first = orders.create("telegram", "1", [(pid, 1)])
    assert first == 1

    snapshot = backup.create_backup(tmp_path / "snap.zip", data_dir=data)  # اتصال‌ها هنوز بازن

    backup.factory_reset(data_dir=data, make_backup=False)
    assert products.list() == [] and orders.get(first) is None, "اتصالِ باز تغییر رو می‌بینه"
    pid2 = products.add("کیبورد", 100, 1)
    assert orders.create("telegram", "2", [(pid2, 1)]) == 1, "شمارنده‌ی سفارش دوباره از ۱"

    backup.restore_backup(snapshot, data_dir=data, safety_backup=False)
    assert [p.name for p in products.list()] == ["هدفون"]
    assert orders.get(first) is not None and orders.get(first).chat_id == "1"
    # و بعد از بازگردانی، نوشتن هنوز روی همون فایل کار می‌کنه
    pid3 = products.add("ماوس", 50, 2)
    check = sqlite3.connect(str(data / "products.db"))
    try:
        names = {r[0] for r in check.execute("SELECT name FROM products")}
    finally:
        check.close()
    assert names == {"هدفون", "ماوس"} and pid3


def test_wipe_leaves_no_customer_text_in_the_database_file(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    conn = sqlite3.connect(str(data / "conversations.db"))
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT)")
    conn.execute("INSERT INTO t (v) VALUES (?)", ("SECRET-CUSTOMER-ADDRESS-12345",))
    conn.commit()
    conn.close()
    backup.factory_reset(data_dir=data, make_backup=False)
    raw = (data / "conversations.db").read_bytes()
    assert b"SECRET-CUSTOMER-ADDRESS-12345" not in raw


def test_shop_data_reset_wipes_only_shop_data_and_keeps_settings_and_chats(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "settings.json").write_text('{"user_name": "مهدی"}', encoding="utf-8")
    from app.core.conversations import ConversationStore
    from app.core.orders import OrderStore
    from app.core.products import ProductStore

    products = ProductStore(data / "products.db")
    orders = OrderStore(data / "orders.db", product_store=products)
    conv = ConversationStore(data / "conversations.db")
    pid = products.add("کالا", 1000, 5)
    orders.create("telegram", "1", [(pid, 1)])
    orders.connection().execute("INSERT INTO carts (platform, chat_id, product_id, quantity, updated_ts) VALUES ('telegram','1',?,2,1)", (pid,))
    orders.connection().commit()
    conv.ensure_conversation("telegram", "1", "علی")
    conv.add_message("telegram", "1", "user", "سلام")
    photos = data / "product_photos"
    photos.mkdir()
    (photos / "a.jpg").write_bytes(b"x")

    safety = backup.shop_data_reset(data_dir=data)
    assert safety is not None and safety.is_file()
    assert products.list(include_inactive=True) == [] and orders.list() == []
    assert orders.connection().execute("SELECT COUNT(*) FROM carts").fetchone()[0] == 0
    assert not photos.exists()
    assert (data / "settings.json").read_text(encoding="utf-8") == '{"user_name": "مهدی"}'
    assert [m.content for m in conv.get_messages("telegram", "1")] == ["سلام"]  # مکالمه‌ها دست‌نخورده
    assert products.add("تازه", 1, 1) == 1  # شماره‌گذاری دوباره از ۱
    assert backup.shop_data_reset(data_dir=data, make_backup=False) is None
