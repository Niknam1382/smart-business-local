"""کارتِ «داده و ایمنی»: پشتیبان، بازگردانی، فایل تشخیصی و بازنشانیِ دو-قفله (بدون مرورگر واقعی)."""

import asyncio
import sqlite3
import zipfile

import pytest
from fake_page import FakePage, find, fire

from app.core import backup, paths
from app.core import settings as settings_module
from app.core.settings import AppSettings
from app.screens import data_safety, settings_screen


class FakeManager:
    def __init__(self, running=True):
        self.running = running
        self.stopped = 0

    def is_running(self):
        return self.running

    def stop(self, timeout=10):
        self.running = False
        self.stopped += 1


def seed(data):
    s = AppSettings()
    s.user_name = "سارا"
    s.business_mode = "store"
    s.ai_mode = "api"
    s.set_telegram_token("123456:ABC-token-xyz")
    settings_module.save_settings(s)
    for name in backup.DB_FILES:
        conn = sqlite3.connect(str(data / name))
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO t (v) VALUES ('row')")
        conn.commit()
        conn.close()
    return s


def make(manager=None, with_callback=True):
    data = paths.get_app_data_dir()
    state = seed(data)
    page = FakePage()
    events = []
    control = data_safety.build(
        page,
        "fa",
        state,
        on_data_changed=(lambda kind, message="": events.append((kind, message))) if with_callback else None,
        manager=manager,
    )
    return data, state, page, control, events


def result_text(control):
    return find(control, "data_result").value


def test_shows_data_location_and_mode():
    data, state, page, control, _ = make()
    assert find(control, "data_path").value == str(data)
    assert "استاندارد" in find(control, "data_mode").value


def test_portable_mode_is_explained(tmp_path, monkeypatch):
    anchor = tmp_path / "usb"
    anchor.mkdir()
    (anchor / paths.PORTABLE_FLAG_NAME).write_text("")
    monkeypatch.setattr(paths, "app_anchor", lambda: anchor)
    _, _, _, control, _ = make()
    assert "قابل‌حمل روشنه" in find(control, "data_mode").value
    assert find(control, "data_path").value == str(anchor.resolve() / paths.PORTABLE_DIR_NAME)


def test_backup_button_creates_zip_with_secrets_by_default_and_lists_it():
    data, state, page, control, _ = make()
    fire(find(control, "backup_now"), "on_click")
    [zip_path] = list((data / "backups").glob("*.zip"))
    assert str(zip_path) in result_text(control)
    assert backup.inspect_backup(zip_path)["includes_secrets"] is True
    assert [o.text for o in find(control, "restore_pick").options] == [zip_path.name], "فهرستِ بازگردانی نو شد"


def test_backup_without_secrets_when_switch_is_off():
    data, state, page, control, _ = make()
    find(control, "backup_secrets").value = False
    fire(find(control, "backup_now"), "on_click")
    [zip_path] = list((data / "backups").glob("*.zip"))
    with zipfile.ZipFile(zip_path) as zf:
        assert "secret.key" not in zf.namelist()


def test_restore_requires_a_choice():
    _, _, _, control, events = make()
    fire(find(control, "restore_btn"), "on_click")
    assert "اول یه پشتیبان انتخاب کن" in result_text(control) and events == []


def test_restore_replaces_data_stops_bots_and_reports_safety_copy():
    manager = FakeManager(running=True)
    data, state, page, control, events = make(manager=manager)
    fire(find(control, "backup_now"), "on_click")
    [snapshot] = list((data / "backups").glob("*.zip"))

    state.user_name = "تغییر کرده"
    settings_module.save_settings(state)
    find(control, "restore_pick").value = str(snapshot)
    fire(find(control, "restore_btn"), "on_click")

    assert manager.stopped == 1, "ربات‌ها قبل از بازگردانی خاموش می‌شن"
    assert state.user_name == "سارا", "state درجا از پشتیبان نو شد"
    [(kind, message)] = events
    assert kind == "restore" and "before-restore-" in message and "ربات‌ها خاموش شدن" in message
    assert list((data / "backups").glob("before-restore-*.zip")), "پشتیبانِ ایمنی ساخته شد"


def test_restore_without_callback_shows_message_inline():
    data, state, page, control, _ = make(with_callback=False)
    fire(find(control, "backup_now"), "on_click")
    find(control, "restore_pick").value = str(next((data / "backups").glob("*.zip")))
    fire(find(control, "restore_btn"), "on_click")
    assert "بازگردانی شد" in result_text(control)


def test_restore_rejects_a_foreign_zip_with_a_clear_message(tmp_path):
    data, state, page, control, events = make()
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("hello.txt", "x")
    (data / "backups").mkdir(exist_ok=True)
    target = data / "backups" / "bad.zip"
    target.write_bytes(bad.read_bytes())
    find(control, "restore_pick").value = str(target)
    fire(find(control, "restore_btn"), "on_click")
    assert "غیرمجاز" in result_text(control) or "پشتیبانِ" in result_text(control)
    assert events == [] and state.user_name == "سارا", "داده دست‌نخورده موند"


def test_restore_from_file_picker_unsupported_platform_is_harmless(monkeypatch):
    import flet as ft

    class Picker:
        async def pick_files(self, **kwargs):
            raise ft.FletUnsupportedPlatformException("web")

    monkeypatch.setattr(data_safety, "get_or_create_file_picker", lambda page: Picker())
    _, _, _, control, events = make()
    asyncio.run(find(control, "restore_file").on_click(None))
    assert events == []


def test_restore_from_file_picker_restores_the_chosen_zip(monkeypatch, tmp_path):
    from types import SimpleNamespace

    data, state, page, control, events = make()
    snapshot = backup.create_backup(tmp_path / "usb-backup.zip", data_dir=data)
    state.user_name = "عوض شد"
    settings_module.save_settings(state)

    class Picker:
        async def pick_files(self, **kwargs):
            assert kwargs["allowed_extensions"] == ["zip"]
            return [SimpleNamespace(path=str(snapshot))]

    monkeypatch.setattr(data_safety, "get_or_create_file_picker", lambda page: Picker())
    asyncio.run(find(control, "restore_file").on_click(None))
    assert state.user_name == "سارا" and events and events[0][0] == "restore"


def test_diagnostics_button_creates_a_safe_bundle():
    data, state, page, control, _ = make()
    fire(find(control, "diagnostics_btn"), "on_click")
    [zip_path] = list((data / "diagnostics").glob("*.zip"))
    assert str(zip_path) in result_text(control)
    with zipfile.ZipFile(zip_path) as zf:
        blob = "\n".join(zf.read(n).decode("utf-8") for n in zf.namelist())
    assert "ABC-token-xyz" not in blob and "secret.key" not in zf.namelist()


def test_reset_button_is_locked_until_the_word_is_typed():
    _, _, _, control, _ = make()
    button, confirm = find(control, "reset_btn"), find(control, "reset_confirm")
    assert button.disabled is True
    fire(confirm, "on_change", value="نه")
    assert button.disabled is True
    fire(confirm, "on_change", value="  RESET ")
    assert button.disabled is False
    fire(confirm, "on_change", value="ریست")
    assert button.disabled is False
    fire(confirm, "on_change", value="rese")
    assert button.disabled is True


def test_locked_reset_button_does_nothing_even_if_clicked():
    data, state, page, control, events = make(manager=FakeManager())
    fire(find(control, "reset_btn"), "on_click")
    assert events == [] and state.user_name == "سارا" and (data / "settings.json").exists()


def test_reset_wipes_everything_after_a_backup_and_routes_back_to_welcome():
    manager = FakeManager(running=True)
    data, state, page, control, events = make(manager=manager)
    fire(find(control, "reset_confirm"), "on_change", value="RESET")
    fire(find(control, "reset_btn"), "on_click")

    assert manager.stopped == 1
    assert state.user_name == "" and state.business_mode is None and state.get_telegram_token() == ""
    assert not (data / "settings.json").exists() and not (data / "secret.key").exists()
    [(kind, message)] = events
    assert kind == "reset" and "backups" in message
    [safety] = list((data / "backups").glob("*.zip"))
    # پشتیبانِ قبل از پاک‌کردن واقعاً قابل‌برگشته
    backup.restore_backup(safety, data_dir=data, safety_backup=False)
    settings_module.reload_into(state)
    assert state.user_name == "سارا" and state.get_telegram_token() == "123456:ABC-token-xyz"
    assert find(control, "reset_confirm").value == "" and find(control, "reset_btn").disabled is True


def test_reset_without_backup_and_with_models_removed():
    data, state, page, control, events = make()
    (data / "models").mkdir()
    (data / "models" / "m.gguf").write_bytes(b"x")
    find(control, "reset_backup").value = False
    find(control, "reset_models").value = True
    fire(find(control, "reset_confirm"), "on_change", value="reset")
    fire(find(control, "reset_btn"), "on_click")
    assert not (data / "backups").exists() and not (data / "models").exists()
    assert events[0][0] == "reset" and "—" in events[0][1]


def test_settings_screen_includes_the_card_only_when_wired():
    state = AppSettings()
    state.business_mode, state.ai_mode = "store", "api"
    page = FakePage()
    plain = settings_screen.build(page, "fa", state, lambda: None, lambda: None, lambda l: None)
    assert find(plain, "reset_btn") is None
    wired = settings_screen.build(
        page, "fa", state, lambda: None, lambda: None, lambda l: None, on_data_changed=lambda k, m="": None
    )
    assert find(wired, "reset_btn") is not None and find(wired, "backup_now") is not None


def test_notice_is_shown_after_a_restore_rebuild():
    state = AppSettings()
    page = FakePage()
    control = data_safety.build(page, "fa", state, on_data_changed=lambda k, m="": None, notice="بازگردانی شد ✓")
    assert result_text(control) == "بازگردانی شد ✓"


@pytest.mark.parametrize("lang", ["fa", "en"])
def test_builds_in_both_languages(lang):
    state = AppSettings()
    control = data_safety.build(FakePage(), lang, state, on_data_changed=lambda k, m="": None)
    assert control is not None and find(control, "backup_now") is not None
