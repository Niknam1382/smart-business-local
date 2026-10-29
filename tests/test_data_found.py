"""N2: تشخیصِ داده‌ی قبلی (فقط‌خواندنی)، صفحه‌ی «ادامه / شروعِ تازه»، پشتیبانِ خودکار، «بازکردنِ پوشه» و «نصبِ تازه‌ی خالی»."""

import sqlite3
import subprocess
import zipfile
from pathlib import Path

from fake_page import FakePage, collect_text, find, fire

from app.core import backup, bot_manager, data_probe, paths
from app.core import settings as settings_module
from app.core.data_probe import probe
from app.core.products import ProductStore
from app.main import main
from app.screens import common, data_safety


def data_dir() -> Path:
    return paths.get_app_data_dir()


def reset_manager():
    bot_manager._manager = None  # noqa: SLF001


def seed_previous_use(products=0):
    state = settings_module.load_settings()
    state.user_name, state.business_mode, state.ai_mode = "سارا", "store", "api"
    state.api_base_url, state.api_model_name = "https://api.example.com/v1", "gpt-4o-mini"
    state.set_api_key("sk-test")
    state.onboarding_complete = True
    state.ensure_default_prompt()
    settings_module.save_settings(state)
    store = ProductStore()
    for i in range(products):
        store.add(f"کالا {i + 1}", 1000, 5)
    return state


# ================================================================== probe ====

def test_empty_or_missing_directory_means_no_data_and_creates_nothing(tmp_path):
    assert probe(tmp_path / "nope").has_data is False
    assert not (tmp_path / "nope").exists()  # فقط‌خواندنی؛ حتی پوشه نمی‌سازد
    empty = tmp_path / "empty"
    empty.mkdir()
    assert probe(empty).has_data is False and list(empty.iterdir()) == []


def test_settings_signals_count_as_previous_use():
    base = data_dir()
    (base / "settings.json").write_text('{"user_name": "علی"}', encoding="utf-8")
    fp = probe(base)
    assert fp.has_data and fp.user_name_set and not fp.onboarding_complete
    (base / "settings.json").write_text('{"user_name": "", "onboarding_complete": true}', encoding="utf-8")
    assert probe(base).has_data
    (base / "settings.json").write_text('{"user_name": "", "language": "fa"}', encoding="utf-8")
    assert probe(base).has_data is False  # فقط تنظیمِ زبان = هنوز تازه


def test_row_counts_come_from_real_stores_without_modifying_files():
    seed_previous_use(products=3)
    base = data_dir()
    before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in base.iterdir() if p.is_file()}
    fp = probe(base)
    assert fp.products == 3 and fp.orders == 0 and fp.conversations == 0 and fp.has_data
    after = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in base.iterdir() if p.is_file()}
    assert before == after  # هیچ فایلی تغییر نکرد/ساخته نشد (مثلاً -wal)


def test_probe_never_raises_on_corrupt_inputs():
    base = data_dir()
    (base / "settings.json").write_text("{not json", encoding="utf-8")
    (base / "products.db").write_bytes(b"this is not sqlite")
    (base / "orders.db").write_bytes(b"")
    conn = sqlite3.connect(base / "conversations.db")
    conn.execute("CREATE TABLE other (x INTEGER)")
    conn.commit()
    conn.close()
    fp = probe(base)
    assert fp.has_data is False and fp.products == fp.orders == fp.conversations == 0


# ============================================================ صفحه‌ی main ====

def test_fresh_install_goes_to_welcome_and_never_asks_later():
    reset_manager()
    page = FakePage()
    main(page)
    assert find(page.controls[0].content, "name_field") is not None  # معرفی، نه «داده‌ی قبلی»
    assert settings_module.load_settings().data_acknowledged is True  # بعد از این هیچ‌وقت نمی‌پرسد


def test_previous_data_shows_the_two_choice_screen_first():
    reset_manager()
    seed_previous_use(products=2)
    page = FakePage()
    main(page)
    root = page.controls[0].content
    assert find(root, "found_continue") is not None and find(root, "found_fresh") is not None
    assert find(root, "nav_ai") is None  # هنوز وارد برنامه نشده
    text = collect_text(root)
    assert "2 محصول" in text and str(data_dir()) in text
    assert "سارا" not in text  # فقط تعداد، نه محتوا


def test_continue_keeps_everything_and_remembers_the_choice():
    reset_manager()
    seed_previous_use(products=1)
    page = FakePage()
    main(page)
    fire(find(page.controls[0].content, "found_continue"), "on_click")
    root = page.controls[0].content
    assert find(root, "nav_ai") is not None  # خانه
    assert settings_module.load_settings().data_acknowledged is True
    assert len(ProductStore().list()) == 1
    reset_manager()
    page2 = FakePage()
    main(page2)  # اجرای بعدی: دیگه نمی‌پرسه
    assert find(page2.controls[0].content, "found_continue") is None and find(page2.controls[0].content, "nav_ai") is not None


def test_fresh_start_backs_up_first_then_erases_and_starts_onboarding():
    reset_manager()
    seed_previous_use(products=2)
    page = FakePage()
    main(page)
    fire(find(page.controls[0].content, "found_fresh"), "on_click")
    root = page.controls[0].content
    assert find(root, "name_field") is not None  # برگشت به معرفی
    state = settings_module.load_settings()
    assert state.user_name == "" and state.data_acknowledged is True
    assert ProductStore().list() == []
    backups = sorted((data_dir() / "backups").glob("SmartBusiness-backup-*.zip"))
    assert len(backups) == 1
    with zipfile.ZipFile(backups[0]) as zf:
        names = zf.namelist()
    assert "settings.json" in names and "products.db" in names  # پشتیبانِ کامل از وضعیتِ قبلی
    assert backup.inspect_backup(backups[0])  # قابل‌بازگردانی/معتبر
    # اجرای بعدی: تازه و بدونِ پرسش
    reset_manager()
    page2 = FakePage()
    main(page2)
    assert find(page2.controls[0].content, "found_continue") is None


def test_fresh_start_failure_shows_error_and_keeps_data(monkeypatch):
    reset_manager()
    seed_previous_use(products=1)
    page = FakePage()
    main(page)

    def boom(**kw):
        raise backup.BackupError("دیسک پر است")

    monkeypatch.setattr(backup, "factory_reset", boom)
    fire(find(page.controls[0].content, "found_fresh"), "on_click")
    root = page.controls[0].content
    assert "دیسک پر است" in find(root, "found_status").value and find(root, "found_status").visible
    assert find(root, "found_continue").disabled is False and find(root, "found_fresh").disabled is False
    assert len(ProductStore().list()) == 1  # چیزی پاک نشد


# ============================================================ تنظیمات ====

def test_settings_data_card_shows_path_and_opens_the_folder(monkeypatch):
    opened = []
    monkeypatch.setattr(common, "open_folder", lambda path: opened.append(Path(path)) or True)
    page = FakePage()
    state = settings_module.load_settings()
    root = data_safety.build(page, "fa", state)
    assert find(root, "data_path").value == str(data_dir())
    fire(find(root, "data_open_folder"), "on_click")
    assert opened == [data_dir()]
    monkeypatch.setattr(common, "open_folder", lambda path: False)
    fire(find(root, "data_open_folder"), "on_click")
    assert "دستی" in find(root, "data_result").value


def test_open_folder_helper_validates_and_never_raises(monkeypatch, tmp_path):
    assert common.open_folder(tmp_path / "missing") is False
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, *a, **k: calls.append(cmd))
    monkeypatch.setattr("sys.platform", "linux")
    assert common.open_folder(tmp_path) is True and calls == [["xdg-open", str(tmp_path)]]

    def boom(*a, **k):
        raise OSError("no xdg-open")

    monkeypatch.setattr(subprocess, "Popen", boom)
    assert common.open_folder(tmp_path) is False


def test_data_probe_module_is_core_only_and_has_no_pii_reads():
    source = Path(data_probe.__file__).read_text(encoding="utf-8")
    assert "SELECT COUNT(*)" in source
    for forbidden in ("SELECT *", "display_name", "customer", "text FROM"):
        assert forbidden not in source


def test_bots_do_not_autostart_until_the_user_chooses_to_continue(monkeypatch):
    """N2: روی داده‌ی قبلی، رباتِ روشن‌شونده با توکن‌های قدیمی قبل از انتخابِ کاربر شروع نمی‌شه."""
    reset_manager()
    state = seed_previous_use(products=1)
    state.set_telegram_token("123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw")
    state.bot_autostart = True
    settings_module.save_settings(state)
    started = []
    monkeypatch.setattr(bot_manager.BotManager, "start", lambda self: started.append(1))
    page = FakePage()
    main(page)
    assert find(page.controls[0].content, "found_continue") is not None and started == []  # هنوز انتخاب نشده
    fire(find(page.controls[0].content, "found_continue"), "on_click")
    assert started == [1]  # بعد از «ادامه» روشن می‌شه
