"""پشتیبان‌گیری، بازگردانی، بازنشانی و بسته‌ی تشخیصی — از جمله فایل‌هایِ رسانه (عکسِ محصول و رسید)."""

import io
import json
import sqlite3
import zipfile

import pytest

from app.core import backup, paths
from app.core.backup import BackupError


def _seed(data):
    """یه پوشه‌ی داده‌ی پرشده: تنظیماتِ رازدار، کلید، لاگِ مشتری‌دار و سه دیتابیس."""
    import os

    data.mkdir(parents=True, exist_ok=True)
    settings = {
        "user_name": "سارا",
        "api_key_encrypted": "gAAAAA" + "x" * 60,
        "telegram_bot_token_encrypted": "gAAAAAB" + "y" * 60,
        "card_to_card_number": "6037-9911-2233-4455",
    }
    (data / "settings.json").write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
    (data / "secret.key").write_bytes(b"k" * 44)
    (data / "bot.log").write_text("customer 09123456789 bought a phone" + chr(10), encoding="utf-8")
    for name in backup.DB_FILES:
        conn = sqlite3.connect(str(data / name))
        conn.execute("CREATE TABLE t (v TEXT)")
        conn.execute("INSERT INTO t (v) VALUES (?)", (f"داده‌ی {name}",))
        conn.commit()
        conn.close()
    os.utime(data / "settings.json")
    return data


def _rows(db_path, table="t"):
    conn = sqlite3.connect(str(db_path))
    try:
        return [r[0] for r in conn.execute(f"SELECT v FROM {table} ORDER BY v")]
    finally:
        conn.close()


def _count_rows(db_path, table="t"):
    conn = sqlite3.connect(str(db_path))
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        conn.close()


# ----------------------------------------------------------------- پوشه‌ی داده ----


def test_default_is_system_dir(isolated_appdata):
    assert paths.data_dir_mode() == paths.MODE_SYSTEM
    assert paths.get_app_data_dir().name == paths.APP_DIR_NAME


def test_env_override_wins(tmp_path, monkeypatch):
    target = tmp_path / "custom-data"
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(target))
    assert paths.get_app_data_dir() == target
    assert target.is_dir()
    assert paths.data_dir_mode() == paths.MODE_ENV


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


def test_backup_carries_product_photos_and_receipt_images(tmp_path):
    """عکسِ رسیدِ مشتری و عکسِ محصول *فایلِ روی دیسک*ند، نه ردیفِ دیتابیس؛ اگر پشتیبان آن‌ها
    را نبرد، بعد از بازگردانی مالک مدرکِ واریز را از دست می‌دهد."""
    data = tmp_path / "data"
    data.mkdir()
    (data / backup.MEDIA_DIRS[0]).mkdir()
    (data / backup.MEDIA_DIRS[1]).mkdir()
    (data / backup.MEDIA_DIRS[0] / "photo-1.png").write_bytes(b"png-bytes" * 20)
    (data / backup.MEDIA_DIRS[1] / "receipt-9.jpg").write_bytes(b"jpeg-bytes" * 20)
    (data / "settings.json").write_text(json.dumps({"user_name": "علی"}), encoding="utf-8")

    pack = backup.create_backup(tmp_path / "out.zip", data_dir=data)
    manifest = backup.inspect_backup(pack)
    assert "media/receipts/receipt-9.jpg" in manifest["media"]
    assert manifest["media_bytes"] > 0 and manifest["media_skipped"] == 0

    other = tmp_path / "restored"
    other.mkdir()
    backup.restore_backup(pack, data_dir=other, safety_backup=False)
    assert (other / backup.MEDIA_DIRS[1] / "receipt-9.jpg").is_file()
    assert (other / backup.MEDIA_DIRS[0] / "photo-1.png").read_bytes() == b"png-bytes" * 20


def test_restore_ignores_media_names_that_try_to_escape(tmp_path):
    """نامِ فایلِ درونِ zip هرگز مستقیم استفاده نمی‌شه؛ مسیرِ فرارکننده رد می‌شه."""
    data = tmp_path / "data"
    data.mkdir()
    (data / "settings.json").write_text(json.dumps({"user_name": "علی"}), encoding="utf-8")
    pack = backup.create_backup(tmp_path / "seed.zip", data_dir=data)
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(pack) as src_zip:
        manifest = json.loads(src_zip.read(backup.MANIFEST_NAME).decode("utf-8"))
        with zipfile.ZipFile(evil, "w") as out:
            for item in src_zip.infolist():
                if item.filename == backup.MANIFEST_NAME:
                    continue  # مانیفستِ دست‌کاری‌شده را پایین‌تر خودمان می‌نویسیم
            manifest["media"] = ["media/receipts/.." + chr(92) + "windows.png", "media/other/x.png", "media/receipts/ok.png"]
            out.writestr(backup.MANIFEST_NAME, json.dumps(manifest).encode("utf-8"))
            out.writestr("media/receipts/ok.png", b"fine")
    target = tmp_path / "restored"
    target.mkdir()
    backup.restore_backup(evil, data_dir=target, safety_backup=False)
    assert (target / "receipts" / "ok.png").is_file()
    assert not (target.parent / "windows.png").exists()
    assert not (target / "other").exists()


def test_extract_budget_stops_a_zip_that_lies_about_its_size(tmp_path):
    """سقفِ بازگردانی روی *بایت‌هایِ واقعاً بازشده* است، نه روی عددی که سرِ فایلِ زیپ نوشته:
    هدرِ دست‌کاری‌شده می‌تواند ۱ کیلوبایت اعلام کند و ۱۰ گیگابایت باز شود (zip bomb)."""
    budget = backup.Budget(1024)
    src = io.BytesIO(b"x" * 4096)
    out = io.BytesIO()
    with pytest.raises(BackupError, match="سقف"):
        budget.write(src, out)
    assert len(out.getvalue()) <= 1024  # وایمیستد، نه اینکه کلِ ۴ کیلوبایت را بنویسد
    assert budget.used > 1024

    ok = io.BytesIO()
    assert budget.__class__(1_000_000).write(io.BytesIO(b"y" * 2048), ok) == 2048
    assert ok.getvalue() == b"y" * 2048


def test_restore_cleans_half_written_files_when_the_budget_trips(tmp_path, monkeypatch):
    data = tmp_path / "live"
    data.mkdir()
    (data / "settings.json").write_text(json.dumps({"user_name": "سارا", "system_prompt": "الف" * 4000}), encoding="utf-8")
    where = tmp_path / "backups"
    zip_path = backup.create_backup(where / "b.zip", data_dir=data)

    # pre-check را با سقفِ بزرگ رد می‌کنیم ولی استخراج با سقفِ کوچک باید بایستد (مثلِ هدرِ دروغگو)
    monkeypatch.setattr(backup, "MAX_RESTORE_BYTES", 256 * 1024 * 1024)
    target = tmp_path / "restored"
    target.mkdir()
    real_budget = backup.Budget

    def tiny_budget(limit):
        return real_budget(64)  # بیشتر از ۶۴ بایت باز نشود

    monkeypatch.setattr(backup, "Budget", tiny_budget)
    with pytest.raises(BackupError):
        backup.restore_backup(zip_path, data_dir=target, safety_backup=False)
    assert list(target.rglob("*.restoring")) == []  # نیمه‌کاره‌ها نمی‌مانند
