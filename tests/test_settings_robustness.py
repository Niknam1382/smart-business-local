"""تنظیمات: ذخیره‌ی اتمیک، قرنطینه‌ی فایلِ خراب، و بازخوانیِ درجا."""

import json

from app.core import settings as settings_module
from app.core.paths import get_app_data_dir
from app.core.settings import AppSettings


def test_save_is_atomic_and_leaves_no_temp_file():
    s = AppSettings()
    s.user_name = "سارا"
    settings_module.save_settings(s)
    folder = get_app_data_dir()
    assert not list(folder.glob("*.tmp"))
    assert json.loads((folder / "settings.json").read_text(encoding="utf-8"))["user_name"] == "سارا"
    s.user_name = "علی"
    settings_module.save_settings(s)
    assert settings_module.load_settings().user_name == "علی"


def test_corrupt_settings_file_is_quarantined_not_silently_lost():
    folder = get_app_data_dir()
    (folder / "settings.json").write_text('{"user_name": "سارا", "telegram_bot_token_encrypted": "gAAAA', encoding="utf-8")
    loaded = settings_module.load_settings()
    assert loaded.user_name == "", "پیش‌فرض‌ها برمی‌گردن (برنامه باز می‌شه)"
    quarantined = list(folder.glob("settings.corrupt-*.json"))
    assert len(quarantined) == 1, "ولی فایلِ خراب برای بازیابی نگه داشته شد"
    assert "gAAAA" in quarantined[0].read_text(encoding="utf-8")
    assert not (folder / "settings.json").exists()


def test_non_object_json_is_quarantined_too():
    folder = get_app_data_dir()
    (folder / "settings.json").write_text("[1, 2, 3]", encoding="utf-8")
    assert settings_module.load_settings().user_name == ""
    assert len(list(folder.glob("settings.corrupt-*.json"))) == 1


def test_unknown_keys_are_ignored_for_forward_compatibility():
    folder = get_app_data_dir()
    (folder / "settings.json").write_text(json.dumps({"user_name": "سارا", "from_the_future": 1}), encoding="utf-8")
    assert settings_module.load_settings().user_name == "سارا"
    assert not list(folder.glob("settings.corrupt-*.json"))


def test_reload_into_updates_the_same_object():
    state = AppSettings()
    state.user_name = "قدیمی"
    fresh = AppSettings()
    fresh.user_name = "تازه"
    fresh.set_telegram_token("123456:ABC-token-xyz")
    settings_module.save_settings(fresh)
    same_object = state
    settings_module.reload_into(state)
    assert state is same_object and state.user_name == "تازه" and state.get_telegram_token() == "123456:ABC-token-xyz"


def test_reload_into_after_reset_gives_defaults():
    state = AppSettings()
    state.user_name = "سارا"
    state.business_mode = "store"
    settings_module.reload_into(state)  # فایلی نیست → پیش‌فرض
    assert state.user_name == "" and state.business_mode is None
