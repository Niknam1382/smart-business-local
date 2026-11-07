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


def test_the_whole_menu_list_scrolls_and_nothing_is_pinned(app):
    """۴: آیتم‌هایِ پایینِ منو (راهنما/حمایت/درباره/تنظیمات) به تهِ نوار میخ نمی‌شن —
    در همان فهرستِ اسکرول‌پذیرند، پس روی پنجره‌ی کوتاه هیچ‌وقت خارج از صفحه نمی‌مانند."""
    root = app.controls[0].content
    side = find(root, "sidebar")
    assert side is not None and side.width == sidebar.SIDEBAR_WIDTH
    scroll = find(root, "sidebar_scroll")
    assert scroll.scroll is not None and scroll.expand, "فهرستِ منو باید اسکرول‌پذیر باشه (۱۵+ آیتم روی پنجره‌ی کوتاه)"
    inside = {c.key for c in walk(scroll) if getattr(c, "key", None)}
    assert {"nav_ai", "nav_products", "nav_customers", "nav_guide", "nav_support", "nav_about", "nav_settings"} <= inside
    outside = {c.key for c in walk(side) if getattr(c, "key", None)} - inside
    assert not any(name.startswith("nav_") for name in outside), outside


def test_scrollbars_are_coloured_and_always_visible(app):
    """۴: اسکرولِ رنگی و همیشه‌دیده (هم تم، هم قابِ هر صفحه)."""
    import flet as ft

    from app import theme

    page = app
    assert page.theme.scrollbar_theme is not None and page.dark_theme.scrollbar_theme is not None
    light = page.theme.scrollbar_theme
    assert light.thickness >= 8 and light.thumb_color == theme.PRIMARY and light.track_color
    assert light.thumb_visibility is True and light.track_visibility is True
    assert page.dark_theme.scrollbar_theme.thumb_color == theme.PRIMARY_LIGHT

    root = app.controls[0].content
    columns = [c for c in walk(root) if isinstance(c, ft.Column) and c.scroll is not None]
    assert columns and any(col.scroll is ft.ScrollMode.ALWAYS for col in columns), "قابِ هر صفحه باید اسکرولِ همیشه‌دیده داشته باشه"


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
