"""قلم ۱۶ مستر‌پرامپت: ✕ باید انتخابِ خودِ کاربر باشد (پس‌زمینه یا خروجِ کامل) و برنامه تمام‌صفحه باز شود."""

import asyncio
import inspect
from types import SimpleNamespace

import flet as ft
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


# ═══════════ شکلِ واقعیِ API در Flet 1.0 (همان چیزی که باگِ ✕ را می‌گیرد) ═══════════


class RealShapePage:
    """همان چیزی که Flet 1.0.1 واقعاً می‌دهد: ``Window.close`` و ``destroy`` async هستند،
    ``run_task`` فقط coroutine-function می‌پذیرد و دایالوگ با show_dialog/pop_dialog کار می‌کند.
    FakePageِ ساده این‌ها را ندارد — به‌همین دلیل باگِ «✕ هیچ کاری نمی‌کند» از تست‌ها رد شد."""

    def __init__(self):
        self.calls = []
        self.dialogs = []
        self.updates = 0
        self.theme_mode = ft.ThemeMode.LIGHT  # theme.text_secondary(page) این را می‌خواند
        self.window = SimpleNamespace(
            prevent_close=False, on_event=None, minimized=False, maximized=False,
            close=self._close, destroy=self._destroy,
        )

    async def _close(self):
        self.calls.append("close")

    async def _destroy(self):
        self.calls.append("destroy")

    def run_task(self, handler, *args, **kw):
        if not inspect.iscoroutinefunction(handler):
            raise TypeError("handler must be a coroutine function")
        self.calls.append("scheduled")
        self._pending = handler(*args, **kw)
        return self._pending

    def show_dialog(self, dialog):
        self.dialogs.append(dialog)

    def pop_dialog(self):
        return self.dialogs.pop() if self.dialogs else None

    def update(self):
        self.updates += 1


def drain(page):
    """هر coroutineِ زمان‌بندی‌شده را واقعاً اجرا می‌کند (مثلِ loopِ Flet)."""
    pending = getattr(page, "_pending", None)
    if pending is not None:
        page._pending = None
        asyncio.run(pending)


def test_the_library_really_makes_window_close_async():
    """اگر Flet روزی این‌ها را sync کند، این تست می‌گوید کِی فرضِ کدِ ما عوض شده است."""
    assert inspect.iscoroutinefunction(ft.Window.close)
    assert inspect.iscoroutinefunction(ft.Window.destroy)
    assert hasattr(ft.Page, "run_task") and hasattr(ft.Page, "show_dialog") and hasattr(ft.Page, "pop_dialog")
    assert not hasattr(ft.Page, "open") and not hasattr(ft.Page, "close")  # مسیرِ قدیمیِ کد


def test_quit_on_a_real_shape_page_actually_closes_the_window():
    state = AppSettings(close_action="quit")
    page = RealShapePage()
    window_close.bind(page, state)
    page.window.on_event(event("close"))
    drain(page)
    assert page.calls == ["scheduled", "close"]


def test_the_ask_dialog_is_opened_with_the_real_dialog_api_and_its_buttons_work():
    state = AppSettings(close_action="ask")
    page = RealShapePage()
    window_close.bind(page, state)
    page.window.on_event(event("close"))
    assert len(page.dialogs) == 1 and page.dialogs[0].key == "close_dialog"
    buttons = {b.key: b for b in page.dialogs[0].actions}
    fire(buttons["close_quit"], "on_click")
    drain(page)
    assert page.dialogs == []  # با pop_dialog بسته شد
    assert page.calls == ["scheduled", "close"]
    page.window.on_event(event("close"))
    fire({b.key: b for b in page.dialogs[0].actions}["close_hide"], "on_click")
    assert page.window.minimized is True and page.dialogs == []


def test_background_choice_never_schedules_an_exit():
    state = AppSettings(close_action="hide")
    page = RealShapePage()
    window_close.bind(page, state)
    page.window.on_event(event("close"))
    assert page.window.minimized is True and page.calls == []
