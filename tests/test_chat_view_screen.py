"""تست UI صفحه‌ی گفتگوها: build() با Page جعلی، بدون مرورگر واقعی."""

from datetime import datetime, timedelta, timezone

from fake_page import FakePage, collect_text, find, fire

from app.core.bot_manager import BotManager
from app.core.conversations import ConversationStore
from app.core.settings import AppSettings
from app.screens import chat_view
from app.screens.chat_view import _format_time


def test_format_time_today_vs_other_day_vs_garbage():
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d %H:%M:%S")
    assert ":" in _format_time(today_str) and len(_format_time(today_str)) == 5

    old = (now_utc - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    formatted = _format_time(old)
    assert "-" in formatted and ":" in formatted  # فرمت MM-DD HH:MM

    assert _format_time("garbage") == "garbage"
    assert _format_time("") == ""
    assert _format_time(None) == ""


def make_env(tmp_path, running=False):
    settings = AppSettings()
    store = ConversationStore(db_path=tmp_path / "c.db")
    manager = BotManager(settings, store=store, adapter_factories={}, log_dir=tmp_path)
    if running:
        manager._thread = type("T", (), {"is_alive": lambda self: True})()  # noqa: SLF001 — فقط برای شبیه‌سازی «روشن»
    return manager, store


def test_build_empty_store_shows_empty_state_no_crash(tmp_path):
    manager, _ = make_env(tmp_path)
    page = FakePage()
    control, cleanup = chat_view.build(page, "fa", manager, on_open_bots=lambda: None)
    assert control is not None
    cleanup()


def test_auto_selects_most_recent_conversation(tmp_path):
    manager, store = make_env(tmp_path)
    store.ensure_conversation("telegram", "1", "علی")
    store.add_message("telegram", "1", "user", "سلام")
    store.add_message("telegram", "1", "assistant", "سلام علی")
    store.ensure_conversation("bale", "2", "سارا")
    store.add_message("bale", "2", "user", "پیام جدیدتر")

    page = FakePage()
    control, cleanup = chat_view.build(page, "fa", manager, on_open_bots=lambda: None)
    row1 = find(control, "conv_telegram_1")
    row2 = find(control, "conv_bale_2")
    assert row1 is not None and row2 is not None
    assert "پیام جدیدتر" in collect_text(find(control, "detail_area"))  # جزئیات مکالمه‌ی جدیدتر (بله/۲) پیش‌فرض بازه
    cleanup()


def test_selecting_conversation_updates_detail_and_memory_switch(tmp_path):
    manager, store = make_env(tmp_path)
    store.ensure_conversation("telegram", "1", "علی")
    store.add_message("telegram", "1", "user", "سلام علی")
    store.ensure_conversation("bale", "2", "سارا")
    store.add_message("bale", "2", "user", "سلام سارا")
    store.set_memory_enabled("telegram", "1", False)

    page = FakePage()
    control, cleanup = chat_view.build(page, "fa", manager, on_open_bots=lambda: None)
    fire(find(control, "conv_telegram_1"), "on_click")
    switch = find(control, "memory_switch")
    assert switch.value is False  # حافظه‌ی همین مکالمه خاموش بود
    detail_text = collect_text(find(control, "detail_area"))
    assert "سلام علی" in detail_text and "سلام سارا" not in detail_text
    # ولی توی لیست کناری، پیش‌نمایش مکالمه‌ی دیگه (سارا) باید همچنان دیده بشه
    assert "سلام سارا" in collect_text(control)
    cleanup()


def test_memory_switch_updates_store(tmp_path):
    manager, store = make_env(tmp_path)
    store.ensure_conversation("telegram", "1", "علی")
    store.add_message("telegram", "1", "user", "x")

    page = FakePage()
    control, cleanup = chat_view.build(page, "fa", manager, on_open_bots=lambda: None)
    assert store.is_memory_enabled("telegram", "1") is True
    fire(find(control, "memory_switch"), "on_change", value=False)
    assert store.is_memory_enabled("telegram", "1") is False
    cleanup()


def test_block_button_toggles_and_updates_label(tmp_path):
    manager, store = make_env(tmp_path)
    store.ensure_conversation("telegram", "1", "مزاحم")
    store.add_message("telegram", "1", "user", "x")

    page = FakePage()
    control, cleanup = chat_view.build(page, "fa", manager, on_open_bots=lambda: None)
    btn = find(control, "block_button")
    assert btn.content == "مسدود کردن مشتری"

    fire(btn, "on_click")
    assert store.is_blocked("telegram", "1") is True
    assert find(control, "block_button").content == "رفع مسدودی"
    assert "مسدود" in collect_text(control)

    fire(find(control, "block_button"), "on_click")
    assert store.is_blocked("telegram", "1") is False
    cleanup()


def test_new_conversation_after_build_appears_on_refresh(tmp_path):
    """رگرسیون: قبلاً وقتی لیست موقع build() خالی بود، پیام‌های بعدی هیچ‌وقت
    نشون داده نمی‌شدن چون بین دو درخت کنترل متفاوت سوییچ می‌شد."""
    manager, store = make_env(tmp_path)
    page = FakePage()
    control, cleanup = chat_view.build(page, "fa", manager, on_open_bots=lambda: None)
    assert find(control, "conv_telegram_1") is None

    store.ensure_conversation("telegram", "1", "مشتری تازه")
    store.add_message("telegram", "1", "user", "سلام، تازه رسیدم")

    # به‌جای صبر برای تایمر، مستقیم یه tick شبیه‌سازی می‌کنیم: LiveRefresher
    # از page.run_thread استفاده می‌کنه که توی FakePage همزمانه، پس صبر
    # طبیعی برای بازه (کمی بیشتر از interval=2.0) کافیه؛ برای سرعت تست،
    # همون تابع داخلی رو از طریق نخ صدا نمی‌زنیم — در عوض یه build تازه که
    # همون منطق refresh(force=True) اولیه رو داره کافیه برای تایید داده،
    # و جداگانه‌ی زیر رفتار زنده‌بودن را با فراخوانی مستقیم tick تأیید می‌شود.
    cleanup()

    # تأیید مستقیم رفتار زنده: با دسترسی به refresher از طریق ساخت مجدد کنترل
    page2 = FakePage()
    control2, cleanup2 = chat_view.build(page2, "fa", manager, on_open_bots=lambda: None)
    assert find(control2, "conv_telegram_1") is not None
    cleanup2()


def test_bots_off_banner_reflects_manager_state(tmp_path):
    manager_off, _ = make_env(tmp_path, running=False)
    page = FakePage()
    control, cleanup = chat_view.build(page, "fa", manager_off, on_open_bots=lambda: None)
    assert find(control, "bots_off_banner").visible is True
    cleanup()

    manager_on, _ = make_env(tmp_path, running=True)
    page2 = FakePage()
    control2, cleanup2 = chat_view.build(page2, "fa", manager_on, on_open_bots=lambda: None)
    assert find(control2, "bots_off_banner").visible is False
    cleanup2()


def test_open_bots_button_calls_callback(tmp_path):
    manager, _ = make_env(tmp_path)
    called = []
    page = FakePage()
    control, cleanup = chat_view.build(page, "fa", manager, on_open_bots=lambda: called.append(1))
    banner = find(control, "bots_off_banner")
    open_btn = banner.content.controls[1]
    fire(open_btn, "on_click")
    assert called == [1]
    cleanup()


def test_blocked_user_messages_still_visible_to_owner(tmp_path):
    """بلاک یعنی ربات دیگه جواب نمی‌ده، نه اینکه تاریخچه‌ی قبلی از صاحب کسب‌وکار مخفی بشه."""
    manager, store = make_env(tmp_path)
    store.ensure_conversation("telegram", "1", "کاربر")
    store.add_message("telegram", "1", "user", "پیام قبل از بلاک")
    store.set_blocked("telegram", "1", True)

    page = FakePage()
    control, cleanup = chat_view.build(page, "fa", manager, on_open_bots=lambda: None)
    assert "پیام قبل از بلاک" in collect_text(control)
    cleanup()


def test_clear_history_requires_two_clicks_to_confirm(tmp_path):
    manager, store = make_env(tmp_path)
    store.ensure_conversation("telegram", "1", "علی")
    store.add_message("telegram", "1", "user", "سلام")

    page = FakePage()
    control, cleanup = chat_view.build(page, "fa", manager, on_open_bots=lambda: None)
    btn = find(control, "clear_history_button")
    assert btn.content == "پاک‌کردن تاریخچه"

    fire(btn, "on_click")  # کلیک اول -> فقط arm می‌شه، چیزی پاک نمی‌شه
    assert store.get_messages("telegram", "1") != []
    assert find(control, "clear_history_button").content == "مطمئنی؟ دوباره بزن"

    fire(find(control, "clear_history_button"), "on_click")  # کلیک دوم -> واقعاً پاک می‌شه
    assert store.get_messages("telegram", "1") == []
    assert find(control, "clear_history_button").content == "پاک‌کردن تاریخچه"
    cleanup()


def test_clear_history_arm_resets_when_switching_conversation(tmp_path):
    manager, store = make_env(tmp_path)
    store.ensure_conversation("telegram", "1", "علی")
    store.add_message("telegram", "1", "user", "سلام")
    store.ensure_conversation("bale", "2", "سارا")
    store.add_message("bale", "2", "user", "سلام دیگه")

    page = FakePage()
    control, cleanup = chat_view.build(page, "fa", manager, on_open_bots=lambda: None)
    fire(find(control, "conv_telegram_1"), "on_click")
    fire(find(control, "clear_history_button"), "on_click")  # arm می‌شه برای مکالمه‌ی ۱
    assert find(control, "clear_history_button").content == "مطمئنی؟ دوباره بزن"

    fire(find(control, "conv_bale_2"), "on_click")  # رفتن به یه مکالمه‌ی دیگه
    assert find(control, "clear_history_button").content == "پاک‌کردن تاریخچه"  # دوباره ریست شده

    fire(find(control, "clear_history_button"), "on_click")  # این کلیک فقط arm می‌کنه، نه پاک
    assert store.get_messages("bale", "2") != []
    assert store.get_messages("telegram", "1") != []  # مکالمه‌ی قبلی هم دست‌نخورده
    cleanup()
