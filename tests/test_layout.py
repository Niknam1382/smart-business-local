"""چیدمانِ همه‌ی صفحه‌های اصلی: اسکرولِ عمودیِ واقعی، حاشیه، و نوارِ کناریِ اسکرول‌پذیر (که آیتمِ پایین بیرون نمی‌افتد)."""

import pytest
from fake_page import FakePage, find, fire
from test_main_app_flow import click_nav, onboarded_state, reset_bot_manager_singleton

from app.main import main
from app.screens import sidebar


def walk(control):
    """همه‌ی کنترل‌های زیرِ یک ریشه (content/controls)، عمق‌اول."""
    seen = []
    stack = [control]
    while stack:
        c = stack.pop()
        if c is None or isinstance(c, (str, int, float)):
            continue
        seen.append(c)
        stack.append(getattr(c, "content", None))
        stack.extend(getattr(c, "controls", None) or [])
    return seen


@pytest.fixture
def app(tmp_path):
    reset_bot_manager_singleton()
    state = onboarded_state()
    state.business_mode = "store"
    from app.core import settings as settings_module

    settings_module.save_settings(state)
    page = FakePage()
    main(page)
    return page


def content_area(page):
    """ستونِ سمتِ راست (محتوای صفحه) — نه نوارِ کناری."""
    row = page.controls[0].content
    return row.controls[1]


def main_scrollable(area):
    """بزرگ‌ترین/اولین ستونِ اسکرول‌پذیرِ محتوا."""
    import flet as ft

    return [c for c in walk(area) if getattr(c, "scroll", None) is not None or isinstance(c, ft.ListView)]


def test_sidebar_middle_is_scrollable_and_bottom_items_are_pinned(app):
    root = app.controls[0].content
    side = find(root, "sidebar")
    assert side is not None and side.width == sidebar.SIDEBAR_WIDTH
    scroll = find(root, "sidebar_scroll")
    assert scroll.scroll is not None and scroll.expand, "فهرستِ منو باید اسکرول‌پذیر باشه (۱۵+ آیتم روی پنجره‌ی کوتاه)"
    inside = {c.key for c in walk(scroll) if getattr(c, "key", None)}
    assert "nav_ai" in inside and "nav_products" in inside and "nav_customers" in inside
    assert not {"nav_guide", "nav_about", "nav_settings"} & inside, "آیتم‌های پایین بیرون از بخشِ اسکرول و همیشه ثابت‌اند"
    pinned = {c.key for c in walk(side) if getattr(c, "key", None)}
    assert {"nav_guide", "nav_about", "nav_settings"} <= pinned


@pytest.mark.parametrize("key", ["home", "ai", "products", "orders", "finance", "discounts", "experience", "prompt", "bots", "chats", "customers",
                                 "broadcast", "admins", "usage", "guide", "about", "settings"])
def test_every_main_page_has_real_vertical_scroll_and_margins(app, key):
    root = app.controls[0].content
    if find(root, f"nav_{key}") is None:
        pytest.skip("این صفحه در این حالت نیست")
    click_nav(root, key)
    area = content_area(app)
    scrollers = main_scrollable(area)
    assert scrollers, f"صفحه‌ی «{key}» هیچ ستونِ اسکرول‌پذیری ندارد؛ محتوای بلند بیرون می‌زنه"
    assert any(getattr(c, "expand", False) for c in scrollers), f"صفحه‌ی «{key}»: ستونِ اسکرول باید expand باشه تا ارتفاعِ پنجره را بگیره"


def test_customers_and_admins_use_the_standard_frame_with_padding(app):
    for key in ("customers", "admins"):
        click_nav(app.controls[0].content, key)
        area = content_area(app)
        frames = [c for c in walk(area) if getattr(c, "padding", None) is not None and getattr(c, "expand", False)]
        assert frames, key


def test_menu_has_group_labels_and_groups_hidden_when_empty(app):
    root = app.controls[0].content
    texts = [getattr(c, "value", "") for c in walk(find(root, "sidebar_scroll"))]
    for label in ("فروشگاه", "ربات و مشتریان", "هوش مصنوعی"):
        assert label in texts
    assert fire is not None
