"""قلم ۱۶ مستر‌پرامپت: ✕ باید انتخابِ خودِ کاربر باشد (پس‌زمینه یا خروجِ کامل) و برنامه تمام‌صفحه باز شود."""

from types import SimpleNamespace

from fake_page import FakePage, find, fire
from test_main_app_flow import onboarded_state, reset_bot_manager_singleton

from app.core import window_close
from app.core.settings import AppSettings
from app.main import main


def event(name="close"):
    return SimpleNamespace(event=name)


def bound(state, **window_kw):
    """یک FakePage با منطقِ بستنِ وصل‌شده (و گزینه‌های اختیاریِ پنجره)."""
    page = FakePage()
    for key, value in window_kw.items():
        setattr(page.window, key, value)
    saves = []
    window_close.bind(page, state, save=lambda: saves.append(True))
    return page, saves


def test_the_app_boots_maximised_and_asks_before_closing():
    """main() پنجره را تمام‌صفحه باز می‌کند و ✕ را از بستنِ بی‌سؤال نجات می‌دهد."""
    reset_bot_manager_singleton()
    onboarded_state()
    page = FakePage()
    main(page)
    assert page.window.maximized is True
    assert page.window.prevent_close is True
    assert callable(page.window.on_event)


def test_ask_offers_background_and_quit_and_can_remember_the_choice():
    state = AppSettings(close_action="ask")
    page, saves = bound(state)
    page.window.on_event(event())
    assert page.overlay, "سؤالِ بستن باید باز شده باشد"
    dialog = page.overlay[0]
    assert find(dialog, "close_hide") is not None and find(dialog, "close_quit") is not None

    page.window.minimized = False
    find(dialog, "close_remember").value = True
    fire(find(dialog, "close_hide"), "on_click")
    assert page.window.minimized is True  # ربات روشن می‌مونه، فقط پنجره کوچک می‌شه
    assert state.close_action == "hide" and saves == [True]  # انتخابش هم ذخیره شد
    assert page.overlay == []

    page.window.on_event(event())  # دفعه‌ی بعد دیگر نمی‌پرسد
    assert page.overlay == []


def test_remembered_background_never_asks_again():
    state = AppSettings(close_action="hide")
    page, _saves = bound(state, minimized=False)
    page.window.on_event(event())
    assert page.overlay == [] and page.window.minimized is True


def test_quit_choice_closes_the_window():
    closed = []
    state = AppSettings(close_action="quit")
    page, _saves = bound(state, close=lambda: closed.append(True))
    page.window.on_event(event())
    assert closed == [True] and page.overlay == []


def test_other_window_events_are_ignored():
    state = AppSettings()
    page, _saves = bound(state)
    for name in ("focus", "resize", "minimize", "restore", "maximize"):
        page.window.on_event(event(name))
    assert page.overlay == []


def test_cancel_leaves_everything_as_it_was():
    state = AppSettings()
    page, _saves = bound(state)
    page.window.on_event(event())
    fire(find(page.overlay[0], "close_cancel"), "on_click")
    assert page.overlay == []
    assert getattr(page.window, "minimized", None) is not True
    assert state.close_action == "ask"


def test_apply_close_refuses_unknown_values():
    state = AppSettings(close_action="hide")
    window_close.apply_close(state, "background-forever")
    assert state.close_action == "ask"  # هر چیزِ ناشناخته = بپرس (بی‌خطرترین حالت)
    window_close.apply_close(state, "quit")
    assert state.close_action == "quit"


def test_a_real_flet_window_event_shape_triggers_the_question():
    """Flet 1.0 نوعِ رویداد را در ``type`` می‌گذارد و ``name`` چیزِ دیگری است — ✕ نباید بی‌کار بماند."""
    import flet as ft

    state = AppSettings()
    page, _saves = bound(state)
    page.window.on_event(SimpleNamespace(name="window_event", type=ft.WindowEventType.CLOSE, data=None))
    assert page.overlay, "پنجره باید سؤال بپرسد، نه اینکه بی‌صدا بماند"
    fire(find(page.overlay[0], "close_cancel"), "on_click")
