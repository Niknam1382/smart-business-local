"""N10 — صفحه‌ی راهنما، چک‌لیستِ شروعِ سریع و دکمه‌ی «؟» در پوسته‌ی برنامه."""

import pytest
from fake_page import FakePage, collect_text, find, fire
from test_main_app_flow import click_nav, onboarded_state, reset_bot_manager_singleton

from app.core import guide, quickstart, troubleshoot
from app.core.settings import AppSettings
from app.main import main
from app.screens import guide as screen
from app.screens import quickstart_card


def build(lang="fa", **kw):
    page = FakePage()
    return page, screen.build(page, lang, AppSettings(), None, **kw)


def test_home_lists_every_category_and_opens_articles():
    page, root = build()
    for cat, title in guide.CATEGORIES:
        if cat != "faq":
            assert find(root, f"gd_cat_{cat}") is not None, cat
    fire(find(root, "gd_open_bot-token"), "on_click")
    assert collect_text(find(root, "gd_title")) == guide.by_id("bot-token").title
    assert find(root, "gd_md") is not None and find(root, "gd_back") is not None
    fire(find(root, "gd_back"), "on_click")
    assert find(root, "gd_title") is None


def test_internal_links_and_related_buttons_navigate_and_external_links_open():
    page, root = build(open_article="start-quick")
    assert collect_text(find(root, "gd_title")) == guide.by_id("start-quick").title
    rel = find(root, "gd_rel_bot-token")
    assert rel is not None
    fire(rel, "on_click")
    assert collect_text(find(root, "gd_title")) == guide.by_id("bot-token").title
    md = find(root, "gd_md")
    opened = []
    page.launch_url = lambda url, *a, **k: opened.append(url)
    md.on_tap_link(type("E", (), {"data": "guide:ts-proxy"})())
    assert collect_text(find(root, "gd_title")) == guide.by_id("ts-proxy").title
    md = find(root, "gd_md")
    md.on_tap_link(type("E", (), {"data": "https://example.com/x"})())
    md.on_tap_link(type("E", (), {"data": "http://insecure.example"})())
    md.on_tap_link(type("E", (), {"data": "file:///etc/passwd"})())
    md.on_tap_link(type("E", (), {"data": "guide:no-such-article"})())
    assert opened == ["https://example.com/x"]  # فقط https؛ ناشناخته بی‌اثر
    assert collect_text(find(root, "gd_title")) == guide.by_id("ts-proxy").title


def test_unknown_open_article_falls_back_to_home():
    _page, root = build(open_article="nope")
    assert find(root, "gd_title") is None and find(root, "gd_cat_start") is not None


def test_search_results_and_empty_state_and_clearing():
    _page, root = build()
    search = find(root, "gd_search")
    fire(search, "on_change", "وب‌هوک")
    assert find(root, "gd_open_ts-webhook") is not None and find(root, "gd_cat_start") is None
    fire(search, "on_change", "xyzzy")
    assert find(root, "gd_none") is not None
    fire(search, "on_change", "")
    assert find(root, "gd_cat_start") is not None


def test_faq_tab_groups_and_fix_tab():
    _page, root = build()
    fire(find(root, "gd_tab_faq"), "on_click")
    for group, _items in guide.faq_groups():
        assert find(root, f"gd_faq_{group}") is not None
    fire(find(root, "gd_tab_fix"), "on_click")
    assert find(root, "gd_fix_run") is not None


def test_troubleshooter_renders_findings_with_links():
    findings = [troubleshoot.Finding("a", troubleshoot.OK, "اتصال", "همه‌چیز خوبه"), troubleshoot.Finding("b", troubleshoot.FAIL, "توکن", "نامعتبره", "ts-token-invalid")]
    page, root = build(probe=lambda: findings)
    fire(find(root, "gd_tab_fix"), "on_click")
    fire(find(root, "gd_fix_run"), "on_click")
    out = collect_text(find(root, "gd_fix_out"))
    assert "✅ اتصال" in out and "❌ توکن" in out and "نامعتبره" in out
    assert find(root, "gd_fix_more_a") is None  # موردِ سالم لینک ندارد
    fire(find(root, "gd_fix_more_b"), "on_click")
    assert collect_text(find(root, "gd_title")) == guide.by_id("ts-token-invalid").title


def test_troubleshooter_probe_crash_shows_one_failure_not_a_crash():
    def boom():
        raise RuntimeError("secret-token-123")

    _page, root = build(probe=boom)
    fire(find(root, "gd_tab_fix"), "on_click")
    fire(find(root, "gd_fix_run"), "on_click")
    out = collect_text(find(root, "gd_fix_out"))
    assert "اجرا نشد: RuntimeError" in out and "secret-token-123" not in out


def test_english_ui_builds_with_note():
    _page, root = build("en")
    assert "Guide" in collect_text(root) and "Persian" in collect_text(root)


# ---------------------------------------------------------------- شروعِ سریع
def settings(**kw):
    s = AppSettings()
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def test_quickstart_steps_follow_real_state():
    empty = quickstart.steps(AppSettings(), product_count=0)
    assert [s.key for s in empty] == ["bot", "ai", "product", "payment", "run"] and not any(s.done for s in empty)
    s = AppSettings()
    s.telegram_enabled = True
    s.set_telegram_token("123:abc")
    s.ai_mode = "local"
    s.card_to_card_number = "6037991234567890"
    steps = {x.key: x for x in quickstart.steps(s, product_count=2, bots_running=True)}
    assert all(x.done for x in steps.values()) and quickstart.progress(list(steps.values())) == (5, 5)
    assert not {x.key: x for x in quickstart.steps(s, product_count=0)}["product"].done
    consult = quickstart.steps(s, product_count=None)
    assert [x.key for x in consult] == ["bot", "ai", "run"]
    for step in empty:
        assert guide.by_id(step.article) is not None, step.article


def test_quickstart_card_buttons_dismiss_and_done_banner():
    page = FakePage()
    went, opened, dismissed = [], [], []
    card = quickstart_card.build(page, "fa", AppSettings(), 0, False, go=went.append, open_article=opened.append, on_dismiss=lambda: dismissed.append(1))
    assert "۰ از ۵" in collect_text(card).translate(str.maketrans("0", "۰")) or "0 از 5" in collect_text(card)
    fire(find(card, "qs_go_bot"), "on_click")
    fire(find(card, "qs_help_product"), "on_click")
    fire(find(card, "qs_dismiss"), "on_click")
    assert went == ["bots"] and opened == ["products-basics"] and dismissed == [1]
    s = settings(card_to_card_number="6037991234567890", ai_mode="local", telegram_enabled=True)
    s.set_telegram_token("123:abc")
    done = quickstart_card.build(page, "fa", s, 1, True, go=went.append, open_article=opened.append, on_dismiss=lambda: None)
    assert find(done, "qs_done") is not None and find(done, "qs_go_bot") is None


# --------------------------------------------------------- اتصال به پوسته‌ی برنامه
@pytest.fixture
def app(tmp_path):
    reset_bot_manager_singleton()
    state = onboarded_state()
    page = FakePage()
    main(page)
    return page, state


def test_every_screen_has_a_help_button_that_opens_its_article(app):
    page, _state = app
    root = page.controls[0].content
    for nav_key, article_id in guide.HELP_FOR.items():
        if find(root, f"nav_{nav_key}") is None:
            continue  # صفحه‌ای که در این حالت نیست (مثلاً فقط فروشگاه)
        click_nav(root, nav_key)
        root = page.controls[0].content
        fire(find(root, "help_button"), "on_click")
        root = page.controls[0].content
        assert collect_text(find(root, "gd_title")) == guide.by_id(article_id).title, nav_key
    assert find(root, "help_button") is None  # در خودِ راهنما دکمه‌ی «؟» نیست


def test_guide_nav_and_quickstart_dismiss_persist(app):
    page, _state = app
    root = page.controls[0].content
    assert find(root, "quickstart_card") is not None  # صفحه‌ی خانه
    fire(find(root, "qs_dismiss"), "on_click")
    root = page.controls[0].content
    from app.core import settings as settings_module

    assert settings_module.load_settings().quickstart_dismissed is True and find(root, "quickstart_card") is None  # روی دیسک ذخیره شد
    click_nav(root, "guide")
    assert find(page.controls[0].content, "gd_search") is not None


def test_quickstart_only_on_home(app):
    page, _state = app
    root = page.controls[0].content
    click_nav(root, "products")
    assert find(page.controls[0].content, "quickstart_card") is None
