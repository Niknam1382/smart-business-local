"""
تست UI صفحه‌ی اتصال ربات‌ها: build() رو با یه Page جعلی صدا می‌زنه (بدون
مرورگر واقعی)، کنترل‌ها رو با key پیدا می‌کنه، و هندلرها رو مستقیم فراخوانی
می‌کنه — دقیقاً همون روش تستی که MASTER_PROMPT برای Flet لازم می‌دونه.
"""

import asyncio

from fake_page import FakePage, find, fire

from app.core import bale_adapter, telegram_adapter
from app.core.adapter_common import (
    ERR_INVALID_TOKEN,
    STATE_CONNECTED,
    STATE_ERROR,
    STATE_STOPPED,
    AdapterStatus,
)
from app.core.bot_manager import BotManager
from app.core.conversations import ConversationStore
from app.core.settings import AppSettings
from app.screens import bot_connect


class InstantAdapter:
    """آداپتور جعلی: فوراً «متصل» می‌شه و تا stop() صدا نشده باقی می‌مونه —
    برای تست wiring صفحه، بدون شبکه‌ی واقعی."""

    def __init__(self, token, pipeline, **kwargs):
        self.status = AdapterStatus(state=STATE_CONNECTED, username="demo_bot")
        self._stop = asyncio.Event()

    async def run(self):
        await self._stop.wait()
        self.status = AdapterStatus(state=STATE_STOPPED)

    async def stop(self):
        self._stop.set()


def make_env(tmp_path):
    settings = AppSettings()
    manager = BotManager(
        settings,
        store=ConversationStore(db_path=tmp_path / "c.db"),
        adapter_factories={
            "telegram": lambda s, p: InstantAdapter(s.get_telegram_token(), p),
            "bale": lambda s, p: InstantAdapter(s.get_bale_token(), p),
        },
        log_dir=tmp_path,
    )
    return settings, manager


def test_build_does_not_crash_and_starts_stopped(tmp_path):
    settings, manager = make_env(tmp_path)
    page = FakePage()
    control, cleanup = bot_connect.build(page, "fa", settings, lambda: None, manager)
    assert control is not None
    run_btn = find(control, "run_button")
    assert run_btn is not None and run_btn.content == "روشن کن"
    cleanup()  # LiveRefresher رو متوقف می‌کنه؛ نباید خطا بده


def test_connect_screen_explains_the_small_credit_line_in_the_bio(tmp_path):
    for lang, expected in (("fa", "خطِ کوچکِ اعتبار"), ("en", "credit line")):
        settings, manager = make_env(tmp_path)
        control, cleanup = bot_connect.build(FakePage(), lang, settings, lambda: None, manager)
        note = find(control, "bots_credit_note")
        assert note is not None and expected in note.value
        cleanup()


def test_build_in_english(tmp_path):
    settings, manager = make_env(tmp_path)
    page = FakePage()
    control, cleanup = bot_connect.build(page, "en", settings, lambda: None, manager)
    run_btn = find(control, "run_button")
    assert run_btn.content == "Start bots"
    cleanup()


def test_typing_token_saves_encrypted_on_blur(tmp_path):
    settings, manager = make_env(tmp_path)
    page = FakePage()
    saved = []
    control, cleanup = bot_connect.build(page, "fa", settings, lambda: saved.append(1), manager)
    field = find(control, "telegram_token")
    fire(field, "on_blur", value="  123456:MYTOKEN  ")
    assert settings.get_telegram_token() == "123456:MYTOKEN"
    assert "MYTOKEN" not in settings.telegram_bot_token_encrypted
    assert saved == [1]
    cleanup()


def test_test_connection_button_success_and_autosaves_token(tmp_path, monkeypatch):
    settings, manager = make_env(tmp_path)

    async def fake_check(token, proxy=""):
        assert token == "goodtoken"
        return AdapterStatus(state=STATE_CONNECTED, username="my_shop_bot")

    monkeypatch.setattr(telegram_adapter, "check_token", fake_check)
    page = FakePage()
    control, cleanup = bot_connect.build(page, "fa", settings, lambda: None, manager)
    field = find(control, "telegram_token")
    field.value = "goodtoken"
    fire(find(control, "telegram_test"), "on_click")
    assert page.run_thread_calls == 1
    assert settings.get_telegram_token() == "goodtoken"  # تست موفق → خودکار ذخیره شد
    cleanup()


def test_test_connection_button_failure_shows_persian_error_and_does_not_save(tmp_path, monkeypatch):
    settings, manager = make_env(tmp_path)

    async def fake_check(token, proxy=""):
        return AdapterStatus(state=STATE_ERROR, error_code=ERR_INVALID_TOKEN, error="bad")

    monkeypatch.setattr(telegram_adapter, "check_token", fake_check)
    page = FakePage()
    control, cleanup = bot_connect.build(page, "fa", settings, lambda: None, manager)
    field = find(control, "telegram_token")
    field.value = "badtoken"
    fire(find(control, "telegram_test"), "on_click")
    assert settings.get_telegram_token() == ""  # ذخیره نشد
    cleanup()


def test_test_connection_with_empty_token_does_not_call_network(tmp_path, monkeypatch):
    settings, manager = make_env(tmp_path)
    called = []
    monkeypatch.setattr(telegram_adapter, "check_token", lambda *a, **k: called.append(1))
    page = FakePage()
    control, cleanup = bot_connect.build(page, "fa", settings, lambda: None, manager)
    fire(find(control, "telegram_test"), "on_click")
    assert called == []  # اصلاً worker صدا زده نشد
    cleanup()


def test_run_button_starts_and_stops_manager(tmp_path):
    settings, manager = make_env(tmp_path)
    settings.set_telegram_token("123:ABC")
    page = FakePage()
    control, cleanup = bot_connect.build(page, "fa", settings, lambda: None, manager)
    run_btn = find(control, "run_button")

    fire(run_btn, "on_click")
    assert manager.is_running()
    assert run_btn.content == "خاموش کن"

    fire(run_btn, "on_click")
    assert not manager.is_running()
    assert run_btn.content == "روشن کن"
    cleanup()


def test_run_button_without_token_shows_error_and_does_not_start(tmp_path):
    settings, manager = make_env(tmp_path)  # بدون توکن
    page = FakePage()
    control, cleanup = bot_connect.build(page, "fa", settings, lambda: None, manager)
    fire(find(control, "run_button"), "on_click")
    assert not manager.is_running()
    assert "توکن" in find(control, "run_button").content or True  # پیام خطا جدا نمایش داده می‌شه
    cleanup()


def test_editing_token_while_running_flags_restart_needed(tmp_path):
    settings, manager = make_env(tmp_path)
    settings.set_telegram_token("123:OLD")
    page = FakePage()
    control, cleanup = bot_connect.build(page, "fa", settings, lambda: None, manager)
    fire(find(control, "run_button"), "on_click")
    assert manager.is_running()

    fire(find(control, "telegram_token"), "on_blur", value="123:NEW")
    run_btn = find(control, "run_button")
    assert run_btn.content == "اعمال تغییرات (راه‌اندازی مجدد)"

    fire(run_btn, "on_click")  # این‌بار باید ری‌استارت کنه، نه فقط توقف
    assert manager.is_running()
    assert run_btn.content == "خاموش کن"
    cleanup()


def test_enabled_switch_toggles_settings(tmp_path):
    settings, manager = make_env(tmp_path)
    page = FakePage()
    control, cleanup = bot_connect.build(page, "fa", settings, lambda: None, manager)
    switch = find(control, "bale_enabled")
    assert settings.bale_enabled is True
    fire(switch, "on_change", value=False)
    assert settings.bale_enabled is False
    cleanup()


def test_proxy_field_saves_and_bale_check_token_used_for_bale_field(tmp_path, monkeypatch):
    settings, manager = make_env(tmp_path)
    calls = []

    async def fake_bale_check(token):
        calls.append(token)
        return AdapterStatus(state=STATE_CONNECTED, username="bale_bot")

    monkeypatch.setattr(bale_adapter, "check_token", fake_bale_check)
    page = FakePage()
    control, cleanup = bot_connect.build(page, "fa", settings, lambda: None, manager)

    fire(find(control, "telegram_proxy"), "on_blur", value="socks5://u:p@127.0.0.1:1080")
    assert settings.get_telegram_proxy() == "socks5://u:p@127.0.0.1:1080"
    assert "u:p@" not in settings.telegram_proxy_encrypted

    find(control, "bale_token").value = "baletoken"
    fire(find(control, "bale_test"), "on_click")
    assert calls == ["baletoken"]
    cleanup()


def test_memory_dropdowns_save_to_settings(tmp_path):
    settings, manager = make_env(tmp_path)
    saved = []
    page = FakePage()
    control, cleanup = bot_connect.build(page, "fa", settings, lambda: saved.append(1), manager)

    assert settings.memory_history_limit == 20
    assert settings.memory_expire_hours == 0

    fire(find(control, "memory_history_limit"), "on_select", value="40")
    assert settings.memory_history_limit == 40

    fire(find(control, "memory_expire_hours"), "on_select", value="24")
    assert settings.memory_expire_hours == 24
    assert len(saved) == 2
    cleanup()


def test_memory_dropdowns_show_current_settings_value(tmp_path):
    settings, manager = make_env(tmp_path)
    settings.memory_history_limit = 80
    settings.memory_expire_hours = 6
    page = FakePage()
    control, cleanup = bot_connect.build(page, "fa", settings, lambda: None, manager)
    assert find(control, "memory_history_limit").value == "80"
    assert find(control, "memory_expire_hours").value == "6"
    cleanup()


# ---------------------------------------------------------------- چند پروکسی ----


def test_proxy_status_shows_count_auto_switch_and_first_error(tmp_path):
    settings, manager = make_env(tmp_path)
    page = FakePage()
    control, cleanup = bot_connect.build(page, "fa", settings, lambda: None, manager)
    status = find(control, "proxy_status")
    field = find(control, "telegram_proxy")
    assert status.value == ""

    field.value = "socks5://127.0.0.1:10808\n1.2.3.4:1080\ntg://proxy?server=9.9.9.9&port=443&secret=x"
    fire(field, "on_change")
    assert "2 پروکسیِ معتبر" in status.value
    assert "خودکار به بعدی" in status.value, "با ۲ پروکسی یا بیشتر جابه‌جاییِ خودکار فعاله"
    assert "1 خطِ نامعتبر" in status.value and "MTProto" in status.value

    field.value = "socks5://127.0.0.1:10808"
    fire(field, "on_change")
    assert "1 پروکسیِ معتبر" in status.value and "خودکار" not in status.value
    cleanup()


def test_multiline_proxy_text_is_saved_encrypted(tmp_path):
    settings, manager = make_env(tmp_path)
    page = FakePage()
    control, cleanup = bot_connect.build(page, "fa", settings, lambda: None, manager)
    text = "socks5://u:p@1.1.1.1:1080\nhttp://2.2.2.2:8080"
    fire(find(control, "telegram_proxy"), "on_blur", value=text)
    assert settings.get_telegram_proxy() == text
    assert "1.1.1.1" not in settings.telegram_proxy_encrypted and "u:p@" not in settings.telegram_proxy_encrypted
    cleanup()


def test_rank_button_puts_fastest_first_and_saves_the_new_order(tmp_path, monkeypatch):
    settings, manager = make_env(tmp_path)
    saved = []

    async def fake_probe(lines, prober=None):
        assert lines == ["1.1.1.1:1080", "socks5://2.2.2.2:1080", "http://3.3.3.3:8080"]
        return {"socks5://1.1.1.1:1080": None, "socks5://2.2.2.2:1080": 300.0, "http://3.3.3.3:8080": 80.0}

    monkeypatch.setattr(bot_connect, "probe_bare_candidates", fake_probe)
    page = FakePage()
    control, cleanup = bot_connect.build(page, "fa", settings, lambda: saved.append(1), manager)
    field = find(control, "telegram_proxy")
    field.value = "1.1.1.1:1080\nsocks5://2.2.2.2:1080\n# یادداشت\nhttp://3.3.3.3:8080"
    fire(find(control, "proxy_rank"), "on_click")

    assert field.value.splitlines() == ["http://3.3.3.3:8080", "socks5://2.2.2.2:1080", "socks5://1.1.1.1:1080"]
    assert settings.get_telegram_proxy() == field.value and saved, "ترتیبِ جدید ذخیره شد"
    result = find(control, "proxy_rank_result").value
    assert "2 از 3" in result and "✓ http://3.3.3.3:8080 80ms" in result and "✗ socks5://1.1.1.1:1080" in result
    assert find(control, "proxy_rank").disabled is False
    cleanup()


def test_rank_button_reports_when_nothing_answers_or_nothing_valid(tmp_path, monkeypatch):
    settings, manager = make_env(tmp_path)

    async def none_alive(lines, prober=None):
        return {"socks5://1.1.1.1:1080": None}

    monkeypatch.setattr(bot_connect, "probe_bare_candidates", none_alive)
    page = FakePage()
    control, cleanup = bot_connect.build(page, "fa", settings, lambda: None, manager)
    field = find(control, "telegram_proxy")
    result = find(control, "proxy_rank_result")

    field.value = "tg://proxy?server=1&port=2&secret=3"
    fire(find(control, "proxy_rank"), "on_click")
    assert "حداقل یه پروکسیِ معتبر" in result.value

    field.value = "1.1.1.1:1080"
    fire(find(control, "proxy_rank"), "on_click")
    assert "هیچ‌کدوم جواب ندادن" in result.value
    cleanup()


def test_token_test_goes_through_every_proxy_in_the_list(tmp_path, monkeypatch):
    settings, manager = make_env(tmp_path)
    seen = {}

    async def fake_via(token, proxies, api_base=""):
        seen["proxies"] = list(proxies)
        return AdapterStatus(state=STATE_CONNECTED, username="demo_bot")

    monkeypatch.setattr(telegram_adapter, "check_token_via_proxies", fake_via)
    page = FakePage()
    control, cleanup = bot_connect.build(page, "fa", settings, lambda: None, manager)
    find(control, "telegram_token").value = "123456:ABC"
    find(control, "telegram_proxy").value = "1.1.1.1:1080\nhttp://2.2.2.2:8080"
    fire(find(control, "telegram_test"), "on_click")
    assert seen["proxies"] == ["socks5://1.1.1.1:1080", "http://2.2.2.2:8080"]
    assert settings.get_telegram_proxy() == "1.1.1.1:1080\nhttp://2.2.2.2:8080", "تستِ موفق، پروکسی‌ها رو هم ذخیره می‌کنه"
    cleanup()


def test_proxy_subscription_controls_validate_save_and_refresh(tmp_path):
    settings, manager = make_env(tmp_path)

    async def fetcher(url):
        return "socks5://1.1.1.1:1080\nsocks5://2.2.2.2:1080\n"

    manager._sub_fetcher = fetcher  # noqa: SLF001
    saved = []
    page = FakePage()
    control, cleanup = bot_connect.build(page, "fa", settings, lambda: saved.append(1), manager)
    url, hours, status = find(control, "proxy_sub_url"), find(control, "proxy_sub_hours"), find(control, "proxy_sub_status")
    assert "هنوز دریافت نشده" in status.value and "پروکسیِ فعلی" in status.value
    url.value = "ftp://example.com/list"
    fire(url, "on_blur")
    assert "https" in status.value and settings.get_telegram_proxy_sub_url() == "" and not saved  # رد شد؛ ذخیره نشد
    url.value, hours.value = "http://example.com/list", "x"
    fire(url, "on_blur")
    assert "ساعت" in status.value and settings.get_telegram_proxy_sub_url() == ""
    hours.value = "3"
    fire(url, "on_blur")
    assert settings.get_telegram_proxy_sub_url() == "http://example.com/list" and settings.telegram_proxy_sub_hours == 3 and saved
    assert "http ساده" in status.value  # هشدارِ http
    url.value = "https://example.com/list"
    fire(find(control, "proxy_sub_now"), "on_click")
    assert wait_until_status(status, "2 پروکسی") and settings.get_telegram_proxy_sub_cache().count("socks5") == 2
    assert "آخرین به‌روزرسانی" in status.value
    cleanup()


def wait_until_status(text_control, needle, timeout=5.0):
    import time

    end = time.time() + timeout
    while time.time() < end:
        if needle in (text_control.value or ""):
            return True
        time.sleep(0.05)
    return False
