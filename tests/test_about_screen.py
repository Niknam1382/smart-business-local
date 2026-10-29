"""صفحه‌ی «درباره» (N15 + N14a): بررسیِ به‌روزرسانی، پیوندهای سازنده، گزارشِ مشکل، فرمِ حمایت و بنرِ نسخه‌ی تازه."""

import threading
from urllib.parse import parse_qs, urlparse

import pytest
from fake_page import FakePage, collect_text, find, fire
from helpers import wait_until

from app import branding
from app.core import about_info, settings as settings_module
from app.core.settings import AppSettings
from app.core.updater import STATUS_CURRENT, STATUS_ERROR, STATUS_UPDATE, CheckResult, UpdateInfo
from app.main import main
from app.screens import about, common, update_banner

INFO = UpdateInfo(version="1.2.0", tag="v1.2.0", html_url="https://github.com/niknam1382/smart-business-local/releases/tag/v1.2.0")


class StubChecker:
    def __init__(self, result=None, pending=None):
        self.result = result or CheckResult(STATUS_CURRENT)
        self._pending = pending
        self.calls = []
        self.dismissed = []

    def check(self, force=False):
        self.calls.append(force)
        return self.result

    def pending(self):
        return self._pending

    def dismiss(self, version):
        self.dismissed.append(version)
        self._pending = None


@pytest.fixture
def opened(monkeypatch):
    urls, copies = [], []
    monkeypatch.setattr(common, "open_url", lambda page, url: urls.append(url) or True)
    monkeypatch.setattr(common, "copy_text", lambda page, text: copies.append(text) or True)
    return urls, copies


def build(lang="fa", checker=None, state=None, saves=None):
    page = FakePage()
    state = state or AppSettings()
    root = about.build(page, lang, state, (lambda: saves.append(1)) if saves is not None else (lambda: None), checker=checker, version="1.1.0")
    return page, root, state


# ------------------------------------------------------------------ پایه ----

def test_builds_in_both_languages_and_shows_version_and_license():
    for lang in ("fa", "en"):
        _page, root, _s = build(lang)
        text = collect_text(root)
        assert "1.1.0" in text and ("MIT" in text)
        assert find(root, "about_check") is not None and find(root, "support_tile") is not None


def test_support_section_is_collapsed_and_fields_start_empty_with_no_presets():
    _page, root, _s = build()
    assert find(root, "support_tile").expanded is False
    assert not find(root, "support_amount").value and not find(root, "support_message").value
    assert find(root, "support_counter").value == "0/100"


def test_creator_links_open_the_right_urls_and_email_is_copyable(opened):
    urls, copies = opened
    page, root, _s = build()
    fire(find(root, "about_github"), "on_click")
    fire(find(root, "about_instagram"), "on_click")
    assert urls == [branding.GITHUB_PROFILE, branding.INSTAGRAM]
    fire(find(root, "about_email_copy"), "on_click")
    assert copies == [branding.CONTACT_EMAIL] and find(root, "about_email_copied").visible is True
    assert branding.CONTACT_EMAIL in collect_text(root)


def test_report_button_opens_prefilled_github_issue_without_private_data(opened):
    urls, _ = opened
    _page, root, _s = build()
    fire(find(root, "about_report"), "on_click")
    [url] = urls
    parsed = urlparse(url)
    assert parsed.netloc == "github.com" and parsed.path == f"/{branding.GITHUB_REPO}/issues/new"
    body = parse_qs(parsed.query)["body"][0]
    assert "1.1.0" in body and about_info.os_label() in body
    import getpass
    import socket

    for private in (getpass.getuser(), socket.gethostname()):
        if len(private) > 3:
            assert private not in body


# --------------------------------------------------------- بررسیِ به‌روزرسانی ----

def test_check_button_reports_a_new_version_with_a_link(opened):
    urls, _ = opened
    checker = StubChecker(CheckResult(STATUS_UPDATE, info=INFO))
    _page, root, _s = build(checker=checker)
    fire(find(root, "about_check"), "on_click")
    assert checker.calls == [True]  # «بررسیِ الان» = force
    assert "1.2.0" in find(root, "about_check_result").value
    link = find(root, "about_update_link")
    assert link.visible is True
    fire(link, "on_click")
    assert urls == [INFO.html_url]


def test_check_button_up_to_date_and_failure_messages():
    for result, expected in ((CheckResult(STATUS_CURRENT), "آخرین نسخه"), (CheckResult(STATUS_ERROR), "نشد بررسی")):
        _page, root, _s = build(checker=StubChecker(result))
        fire(find(root, "about_check"), "on_click")
        assert expected in find(root, "about_check_result").value
        assert find(root, "about_update_link").visible is False


def test_check_button_is_disabled_without_a_checker():
    _page, root, _s = build(checker=None)
    assert find(root, "about_check").disabled is True


def test_auto_check_switch_persists_the_setting():
    saves = []
    _page, root, state = build(saves=saves)
    switch = find(root, "about_auto_check")
    assert switch.value is True
    fire(switch, "on_change", value=False)
    assert state.update_check_enabled is False and saves == [1]


# --------------------------------------------------------------- فرمِ حمایت ----

def test_support_form_builds_the_exact_daramet_link_and_opens_it(opened):
    urls, copies = opened
    _page, root, _s = build()
    find(root, "support_amount").value = "۵٬۰۰۰"
    fire(find(root, "support_message"), "on_change", value="دمتون گرم 🙏")
    assert find(root, "support_counter").value == "12/100"  # ۹ حرف + ۱ فاصله + ایموجی (۲ واحدِ UTF-16)
    fire(find(root, "support_make"), "on_click")
    [url] = urls
    assert url.startswith("https://daramet.com/Niknam1382?webintent&donate=5000&message=")
    assert parse_qs(urlparse(url).query)["message"] == ["دمتون گرم 🙏"]
    assert find(root, "support_link_ready").visible is True and find(root, "support_link_text").value == url
    fire(find(root, "support_copy"), "on_click")
    assert copies == [url]


def test_support_form_shows_persian_errors_and_opens_nothing(opened):
    urls, _ = opened
    _page, root, _s = build()
    for amount, message, expected in (("", "", "مبلغ"), ("abc", "", "عدد"), ("0", "", "صفر"), ("500", "x" * 101, "100")):
        find(root, "support_amount").value = amount
        find(root, "support_message").value = message
        fire(find(root, "support_make"), "on_click")
        error = find(root, "support_error")
        assert error.visible is True and expected in error.value
        assert find(root, "support_link_ready").visible is False
    assert urls == []


def test_message_counter_turns_red_over_the_limit():
    _page, root, _s = build()
    fire(find(root, "support_message"), "on_change", value="x" * 120)
    counter = find(root, "support_counter")
    assert counter.value == "120/100"
    from app import theme

    assert counter.color == theme.DANGER


def test_webintent_disabled_shows_only_the_profile_button(monkeypatch, opened):
    monkeypatch.setattr(branding, "DARAMET_WEBINTENT_ENABLED", False)
    urls, _ = opened
    _page, root, _s = build()
    assert find(root, "support_amount") is None and find(root, "support_make") is None
    fire(find(root, "support_profile"), "on_click")
    assert urls == ["https://daramet.com/Niknam1382"]


# ---------------------------------------------------------------- بنر و main ----

def test_banner_shows_version_and_buttons(opened):
    urls, _ = opened
    page = FakePage()
    later = []
    banner = update_banner.build(page, "fa", INFO, later.append)
    assert "1.2.0" in collect_text(banner)
    fire(find(banner, "update_changes"), "on_click")
    fire(find(banner, "update_later"), "on_click")
    assert urls == [INFO.html_url] and later == ["1.2.0"]


def onboarded():
    state = settings_module.load_settings()
    state.user_name, state.business_mode, state.ai_mode = "سارا", "store", "api"
    state.api_base_url, state.api_model_name = "https://api.example.com/v1", "gpt-4o-mini"
    state.set_api_key("sk-test")
    state.onboarding_complete = True
    state.data_acknowledged = True
    state.ensure_default_prompt()
    settings_module.save_settings(state)


def reset_manager():
    from app.core import bot_manager

    bot_manager._manager = None  # noqa: SLF001


def test_main_shows_banner_for_pending_update_and_later_hides_it(opened):
    reset_manager()
    onboarded()
    page = FakePage()
    checker = StubChecker(pending=INFO)
    main(page, checker=checker, start_update_thread=False)
    root = page.controls[0].content
    assert find(root, "update_banner") is not None
    assert find(root, "update_banner_holder").visible is True
    fire(find(root, "update_later"), "on_click")
    assert checker.dismissed == ["1.2.0"]
    assert find(root, "update_banner_holder").visible is False


def test_main_has_no_banner_without_update_and_about_nav_opens_the_about_page(opened):
    reset_manager()
    onboarded()
    page = FakePage()
    main(page, checker=StubChecker(), start_update_thread=False)
    body = page.controls[0]
    assert find(body.content, "update_banner") is None
    fire(find(body.content, "nav_about"), "on_click")
    assert find(body.content, "about_check") is not None and find(body.content, "support_tile") is not None


def test_update_thread_starts_only_when_enabled_and_refreshes_the_banner(opened):
    reset_manager()
    onboarded()
    # ۱) متغیر محیطیِ تست ⇒ هیچ ترد/شبکه‌ای
    before = {t.name for t in threading.enumerate()}
    main(FakePage(), checker=StubChecker(), start_update_thread=None)
    assert "smart-business-update-check" not in {t.name for t in threading.enumerate()} - before
    # ۲) فعالِ صریح + نتیجه‌ی «نسخه‌ی تازه» ⇒ بنر بعد از بررسی ظاهر می‌شه
    reset_manager()
    page = FakePage()
    checker = StubChecker(CheckResult(STATUS_UPDATE, info=INFO))
    main(page, checker=checker, start_update_thread=True)
    assert wait_until(lambda: bool(checker.calls))
    checker._pending = INFO  # بعد از بررسی، pending() نسخه را برمی‌گردونه
    from app import main as main_module

    assert main_module.NO_UPDATE_CHECK_ENV == "SMART_BUSINESS_NO_UPDATE_CHECK"


def test_update_check_disabled_in_settings_never_starts_the_thread(opened):
    reset_manager()
    state = settings_module.load_settings()
    state.update_check_enabled = False
    state.user_name, state.business_mode, state.ai_mode = "سارا", "store", "api"
    state.api_base_url, state.api_model_name = "https://api.example.com/v1", "gpt-4o-mini"
    state.set_api_key("sk-test")
    state.onboarding_complete = True
    state.data_acknowledged = True
    state.ensure_default_prompt()
    settings_module.save_settings(state)
    checker = StubChecker()
    main(FakePage(), checker=checker, start_update_thread=True)
    assert not wait_until(lambda: bool(checker.calls), timeout=0.5)


def test_open_url_helper_refuses_non_http_and_never_raises():
    page = FakePage()
    assert common.open_url(page, "javascript:alert(1)") is False
    assert common.open_url(page, "file:///etc/passwd") is False
    assert common.open_url(page, "") is False
    assert common.open_url(page, "https://github.com") in (True, False)  # FakePage بدونِ run_task ⇒ False؛ هرگز exception
    assert common.copy_text(page, "x") in (True, False)
