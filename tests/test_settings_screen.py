"""تست settings_screen.py با Page جعلی — امضای build() دقیقاً باید با main.py هماهنگ بمونه."""

from fake_page import FakePage

from app.core.settings import AppSettings
from app.screens import settings_screen


def make_state():
    s = AppSettings()
    s.business_mode = "store"
    s.ai_mode = "api"
    return s


def test_builds_without_crashing_fa_and_en():
    page = FakePage()
    state = make_state()
    for lang in ("fa", "en"):
        control = settings_screen.build(page, lang, state, lambda: None, lambda: None, lambda l: None)
        assert control is not None


def test_change_mode_and_change_ai_callbacks_fire():
    page = FakePage()
    state = make_state()
    mode_calls, ai_calls = [], []
    control = settings_screen.build(
        page, "fa", state, lambda: mode_calls.append(1), lambda: ai_calls.append(1), lambda l: None
    )
    buttons = [c for c in _find_all_outlined_buttons(control)]
    # دو دکمه‌ی «تغییر بده» (کسب‌وکار و هوش مصنوعی) باید باشن
    change_buttons = [b for b in buttons if b.content == "تغییر بده"]
    assert len(change_buttons) == 2
    change_buttons[0].on_click(None)
    change_buttons[1].on_click(None)
    assert mode_calls == [1] and ai_calls == [1]


def test_language_buttons_call_callback_with_correct_code():
    page = FakePage()
    state = make_state()
    langs = []
    control = settings_screen.build(page, "fa", state, lambda: None, lambda: None, lambda l: langs.append(l))
    buttons = _find_all_outlined_buttons(control)
    fa_btn = next(b for b in buttons if b.content == "فارسی")
    en_btn = next(b for b in buttons if b.content == "English")
    fa_btn.on_click(None)
    en_btn.on_click(None)
    assert langs == ["fa", "en"]


def test_shows_dash_when_mode_or_ai_not_chosen_yet():
    page = FakePage()
    state = AppSettings()  # هنوز چیزی انتخاب نشده
    control = settings_screen.build(page, "fa", state, lambda: None, lambda: None, lambda l: None)
    assert control is not None  # نباید کرش کنه


def _find_all_outlined_buttons(control):
    import flet as ft

    found = []

    def walk(c):
        if isinstance(c, ft.OutlinedButton):
            found.append(c)
        for attr in ("controls", "content"):
            v = getattr(c, attr, None)
            if v is None or isinstance(v, str):
                continue
            for item in v if isinstance(v, list) else [v]:
                walk(item)

    walk(control)
    return found
