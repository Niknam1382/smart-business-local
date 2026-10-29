"""رابطِ نصبِ یک‌کلیکی (N14b): مراحلِ بنر، قفلِ دوکلیک، خطاها، پیامِ نتیجه، اتصال به main و صفحه‌ی «درباره»."""

import re
from pathlib import Path

import pytest
from fake_page import FakePage, collect_text, find, fire

from app.core import bot_manager, settings as settings_module, update_install as ui
from app.core.settings import AppSettings
from app.core.updater import STATUS_CURRENT, STATUS_UPDATE, Asset, CheckResult, UpdateChecker, UpdateInfo
from app.i18n import STRINGS, t
from app.main import main
from app.screens import about, common, update_banner

INFO = UpdateInfo(version="1.2.0", tag="v1.2.0", html_url="https://github.com/niknam1382/smart-business-local/releases/tag/v1.2.0")


class FakeInstaller:
    """جایگزینِ UpdateInstaller: ``steps`` را به‌عنوانِ پیشرفت گزارش می‌ده و بعد ``outcome`` را برمی‌گردونه/می‌اندازه."""

    def __init__(self, mode=ui.MODE_AUTO, outcome=None, steps=(), call_hook=True, on_step=None):
        self.mode = mode
        self.outcome = outcome if outcome is not None else ui.InstallResult("restart", backup="b.zip")
        self.steps, self.call_hook, self.on_step = steps, call_hook, on_step
        self.calls, self.cancelled, self.busy = [], 0, False

    def availability(self, info):
        reason = ui.REASON_NO_KEY if self.mode == ui.MODE_MANUAL else ui.REASON_OK
        return ui.Availability(self.mode, ui.KIND_WINDOWS_EXE, reason, Asset("a.exe", "https://github.com/x", 1))

    def install(self, info, on_progress=None, before_handoff=None):
        self.calls.append(info)
        for phase, fraction in self.steps:
            on_progress(phase, fraction)
            if self.on_step:
                self.on_step(phase, fraction)
        if self.call_hook and before_handoff:
            before_handoff()
        outcome = self.outcome.pop(0) if isinstance(self.outcome, list) else self.outcome
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def cancel(self):
        self.cancelled += 1


@pytest.fixture
def opened(monkeypatch):
    urls, folders = [], []
    monkeypatch.setattr(common, "open_url", lambda page, url: urls.append(url) or True)
    monkeypatch.setattr(common, "open_folder", lambda path: folders.append(str(path)) or True)
    return urls, folders


def banner(installer=None, lang="fa", **kw):
    page, later = FakePage(), []
    restarts, resumes, hooks = [], [], []
    control = update_banner.build(
        page, lang, INFO, later.append, installer=installer, on_restart=lambda: restarts.append(1),
        before_handoff=lambda: hooks.append(1), on_resume=lambda: resumes.append(1), **kw,
    )
    return control, page, dict(later=later, restarts=restarts, resumes=resumes, hooks=hooks)


# ------------------------------------------------------------------ حالتِ idle ----

@pytest.mark.parametrize("installer", [None, FakeInstaller(mode=ui.MODE_MANUAL)])
def test_without_auto_install_the_banner_is_exactly_the_old_one(installer, opened):
    control, _page, _ = banner(installer)
    assert find(control, "update_install") is None
    assert find(control, "update_changes") is not None and find(control, "update_later") is not None
    assert "1.2.0" in collect_text(control)


def test_auto_mode_adds_the_install_button_in_both_languages():
    for lang, label in (("fa", "نصبِ به‌روزرسانی"), ("en", "Install update")):
        control, _p, _ = banner(FakeInstaller(), lang)
        assert label in collect_text(control) and find(control, "update_install") is not None


def test_download_only_mode_labels_the_button_differently():
    control, _p, _ = banner(FakeInstaller(mode=ui.MODE_DOWNLOAD))
    assert "دانلودِ فایلِ تأییدشده" in collect_text(control)


# --------------------------------------------------------- تأیید ← نصب ← خروج ----

def test_install_asks_for_confirmation_first_and_cancel_goes_back():
    installer = FakeInstaller()
    control, _p, log = banner(installer)
    fire(find(control, "update_install"), "on_click")
    text = collect_text(control)
    assert "1.2.0" in text and "پشتیبان" in text and "دست‌نخورده" in text
    assert find(control, "update_confirm_yes") is not None and find(control, "update_install") is None
    fire(find(control, "update_confirm_no"), "on_click")
    assert find(control, "update_install") is not None and installer.calls == []  # هنوز هیچ کاری نشده


def test_confirm_runs_the_install_then_asks_the_app_to_quit():
    installer = FakeInstaller()
    control, page, log = banner(installer)
    fire(find(control, "update_install"), "on_click")
    fire(find(control, "update_confirm_yes"), "on_click")
    assert installer.calls == [INFO] and log["hooks"] == [1] and log["restarts"] == [1] and log["resumes"] == []
    assert "در حال نصب و بازراه‌اندازی" in collect_text(control)
    assert find(control, "update_install") is None and find(control, "update_cancel") is None  # دیگه دکمه‌ای نیست
    assert page.run_thread_calls == 1


def test_progress_is_shown_with_a_real_percentage_and_bar():
    seen = {}

    def inspect(phase, fraction):
        if (phase, fraction) == ("download", 0.42):
            seen["text"] = collect_text(control)
            seen["value"] = find(control, "update_progress").value
            seen["cancel"] = find(control, "update_cancel") is not None
        if phase == "signature":
            seen["sig"] = collect_text(control)

    installer = FakeInstaller(steps=[("signature", None), ("download", 0.42), ("verify", None), ("backup", None)], on_step=inspect)
    control, _p, _ = banner(installer)
    fire(find(control, "update_install"), "on_click")
    fire(find(control, "update_confirm_yes"), "on_click")
    assert "42%" in seen["text"] and seen["value"] == 0.42 and seen["cancel"] is True
    assert "امضا" in seen["sig"]


def test_double_click_while_installing_starts_only_one_install():
    installer = FakeInstaller()
    control, _p, _ = banner(installer)
    fire(find(control, "update_install"), "on_click")
    installer.busy = True  # یک نصبِ دیگر در جریان است
    fire(find(control, "update_confirm_yes"), "on_click")
    assert installer.calls == []


def test_start_in_confirm_opens_directly_on_the_confirmation():
    control, _p, _ = banner(FakeInstaller(), start_in_confirm=True)
    assert find(control, "update_confirm_yes") is not None
    plain, _p2, _ = banner(FakeInstaller(mode=ui.MODE_MANUAL), start_in_confirm=True)  # نصب ممکن نیست ⇒ همان بنرِ ساده
    assert find(plain, "update_confirm_yes") is None and find(plain, "update_changes") is not None


def test_cancel_button_calls_the_installer_cancel():
    seen = {}
    installer = FakeInstaller(steps=[("download", 0.1)], on_step=lambda p, f: seen.update(clicked=fire(find(control, "update_cancel"), "on_click")))
    control, _p, _ = banner(installer)
    fire(find(control, "update_install"), "on_click")
    fire(find(control, "update_confirm_yes"), "on_click")
    assert installer.cancelled == 1


# ------------------------------------------------------------------------ خطاها ----

def test_cancelled_install_returns_quietly_to_the_banner_and_resumes_bots():
    installer = FakeInstaller(outcome=ui.InstallError("cancelled"))
    control, _p, log = banner(installer)
    fire(find(control, "update_install"), "on_click")
    fire(find(control, "update_confirm_yes"), "on_click")
    assert find(control, "update_install") is not None and find(control, "update_back") is None
    assert log["resumes"] == [1] and log["restarts"] == []


def test_network_error_offers_retry_manual_and_close_then_retry_succeeds(opened):
    urls, _ = opened
    installer = FakeInstaller(outcome=[ui.InstallError("network", "timeout"), ui.InstallResult("restart")])
    control, _p, log = banner(installer)
    fire(find(control, "update_install"), "on_click")
    fire(find(control, "update_confirm_yes"), "on_click")
    assert "اینترنت" in collect_text(control) and log["resumes"] == [1] and log["restarts"] == []
    assert find(control, "update_retry") is not None
    fire(find(control, "update_manual"), "on_click")
    assert urls == [INFO.html_url]
    fire(find(control, "update_retry"), "on_click")  # بار دوم موفق
    assert len(installer.calls) == 2 and log["restarts"] == [1]


def test_verification_failure_has_no_retry_but_keeps_the_manual_download():
    installer = FakeInstaller(outcome=ui.InstallError("verify", "signature"))
    control, _p, _ = banner(installer)
    fire(find(control, "update_install"), "on_click")
    fire(find(control, "update_confirm_yes"), "on_click")
    assert "معتبر نبود" in collect_text(control) and "برای امنیت" in collect_text(control)
    assert find(control, "update_retry") is None and find(control, "update_manual") is not None
    fire(find(control, "update_back"), "on_click")
    assert find(control, "update_install") is not None  # بستنِ خطا ⇒ برگشت به بنر


def test_unknown_error_codes_and_exceptions_never_leave_the_banner_stuck():
    for outcome in (ui.InstallError("brand_new_code"), RuntimeError("bug")):
        installer = FakeInstaller(outcome=outcome)
        control, _p, log = banner(installer)
        fire(find(control, "update_install"), "on_click")
        fire(find(control, "update_confirm_yes"), "on_click")
        assert find(control, "update_manual") is not None and find(control, "update_cancel") is None
        assert log["resumes"] == [1]


def test_every_install_error_code_has_a_message_in_both_languages():
    source = (Path(ui.__file__)).read_text(encoding="utf-8")
    codes = set(re.findall(r'InstallError\("([a-z_]+)"', source))
    assert {"network", "verify", "backup", "busy", "cancelled", "disk", "launch", "unpack", "unsupported"} <= codes
    for code in codes:
        entry = STRINGS.get(f"update.error.{code}")
        assert entry and entry.get("fa") and entry.get("en"), code


# --------------------------------------------------------------- فقط دانلود (مک/لینوکس) ----

def test_download_only_flow_shows_the_path_and_reveals_the_folder(opened):
    _urls, folders = opened
    installer = FakeInstaller(mode=ui.MODE_DOWNLOAD, outcome=ui.InstallResult("downloaded", path="/home/u/Downloads/SBL-1.2.0.zip"))
    control, _p, log = banner(installer)
    fire(find(control, "update_install"), "on_click")
    assert "Downloads" in collect_text(control) and "جایگزینی با خودته" in collect_text(control)
    fire(find(control, "update_confirm_yes"), "on_click")
    assert "SBL-1.2.0.zip" in collect_text(control) and log["restarts"] == []  # برنامه بسته نمی‌شه
    fire(find(control, "update_reveal"), "on_click")
    assert folders == ["/home/u/Downloads"]


# ---------------------------------------------------------------- پیامِ نتیجه ----

@pytest.mark.parametrize(
    "status,fa_snippet,en_snippet",
    [("ok", "انجام شد", "Updated to version 1.2.0"), ("rolled_back", "بازگردانده شد", "previous one was restored"), ("failed", "همون نسخه‌ی قبلی", "previous version was kept")],
)
def test_result_notice_texts_and_dismiss(status, fa_snippet, en_snippet):
    for lang, snippet in (("fa", fa_snippet), ("en", en_snippet)):
        dismissed = []
        notice = update_banner.build_notice(FakePage(), lang, {"status": status, "to": "1.2.0"}, lambda: dismissed.append(1))
        assert snippet in collect_text(notice) and notice.key == "update_notice"
        fire(find(notice, "update_notice_dismiss"), "on_click")
        assert dismissed == [1]


def test_unknown_result_status_falls_back_to_the_failure_text():
    notice = update_banner.build_notice(FakePage(), "fa", {"status": "???"}, lambda: None)
    assert t("update.result.failed", "fa") in collect_text(notice)


# ------------------------------------------------------------------------ main ----

class StubChecker:
    """مثلِ UpdateChecker واقعی: ``dismiss(نسخه)`` پنهان می‌کنه و ``dismiss("")`` دوباره نشان می‌ده."""

    def __init__(self, info=None, result=None):
        self.info, self._pending = info, info
        self.result = result or (CheckResult(STATUS_UPDATE, info=info) if info else CheckResult(STATUS_CURRENT))
        self.dismissed = []

    def check(self, force=False):
        return self.result

    def pending(self):
        return self._pending

    def dismiss(self, version):
        self.dismissed.append(version)
        self._pending = None if version else self.info


def onboarded():
    state = settings_module.load_settings()
    state.user_name, state.business_mode, state.ai_mode = "سارا", "store", "api"
    state.api_base_url, state.api_model_name = "https://api.example.com/v1", "gpt-4o-mini"
    state.set_api_key("sk-test")
    state.onboarding_complete = True
    state.data_acknowledged = True
    state.ensure_default_prompt()
    settings_module.save_settings(state)


def boot(installer=None, checker=None, **kw):
    bot_manager._manager = None  # noqa: SLF001
    onboarded()
    page, quits = FakePage(), []
    main(page, checker=checker or StubChecker(INFO), installer=installer or FakeInstaller(), quit_app=lambda: quits.append(1), start_update_thread=False, **kw)
    return page, page.controls[0].content, quits


def test_main_full_install_flow_stops_bots_then_quits(monkeypatch):
    stops = []
    monkeypatch.setattr(bot_manager.BotManager, "is_running", lambda self: True)
    monkeypatch.setattr(bot_manager.BotManager, "stop", lambda self, timeout=15.0: stops.append(timeout) or True)
    starts = []
    monkeypatch.setattr(bot_manager.BotManager, "start", lambda self: starts.append(1))
    _page, root, quits = boot()
    fire(find(root, "update_install"), "on_click")
    fire(find(root, "update_confirm_yes"), "on_click")
    assert stops == [10] and quits == [1] and starts == []  # ربات‌ها تمیز خاموش شدن و برنامه بسته شد؛ دوباره روشن نمی‌شن


def test_main_resumes_the_bots_it_stopped_when_the_handoff_fails(monkeypatch):
    stops, starts = [], []
    monkeypatch.setattr(bot_manager.BotManager, "is_running", lambda self: True)
    monkeypatch.setattr(bot_manager.BotManager, "stop", lambda self, timeout=15.0: stops.append(1) or True)
    monkeypatch.setattr(bot_manager.BotManager, "start", lambda self: starts.append(1))
    _page, root, quits = boot(installer=FakeInstaller(outcome=ui.InstallError("launch")))
    fire(find(root, "update_install"), "on_click")
    fire(find(root, "update_confirm_yes"), "on_click")
    assert stops == [1] and starts == [1] and quits == []  # برنامه باز موند و رباتی که ما خاموش کردیم برگشت


def test_main_does_not_touch_the_bots_when_the_failure_came_before_the_handoff(monkeypatch):
    stops, starts = [], []
    monkeypatch.setattr(bot_manager.BotManager, "is_running", lambda self: True)
    monkeypatch.setattr(bot_manager.BotManager, "stop", lambda self, timeout=15.0: stops.append(1) or True)
    monkeypatch.setattr(bot_manager.BotManager, "start", lambda self: starts.append(1))
    _page, root, quits = boot(installer=FakeInstaller(outcome=ui.InstallError("network"), call_hook=False))
    fire(find(root, "update_install"), "on_click")
    fire(find(root, "update_confirm_yes"), "on_click")
    assert stops == [] and starts == [] and quits == []


def test_main_does_not_restart_bots_that_were_not_running(monkeypatch):
    starts = []
    monkeypatch.setattr(bot_manager.BotManager, "is_running", lambda self: False)
    monkeypatch.setattr(bot_manager.BotManager, "start", lambda self: starts.append(1))
    _page, root, _q = boot(installer=FakeInstaller(outcome=ui.InstallError("launch")))
    fire(find(root, "update_install"), "on_click")
    fire(find(root, "update_confirm_yes"), "on_click")
    assert starts == []


def test_main_shows_the_result_notice_once_and_it_can_be_dismissed():
    _page, root, _q = boot(update_result={"status": "ok", "from": "1.1.0", "to": "1.2.0"})
    assert find(root, "update_notice") is not None and find(root, "update_notice_holder").visible is True
    assert "انجام شد" in collect_text(find(root, "update_notice"))
    fire(find(root, "update_notice_dismiss"), "on_click")
    assert find(root, "update_notice_holder").visible is False


def test_main_reads_the_result_file_from_the_data_dir_and_consumes_it():
    from app.core import paths
    from app.version import __version__

    data = paths.get_app_data_dir()
    data.mkdir(parents=True, exist_ok=True)
    (data / ui.RESULT_FILE).write_text('{"status": "rolled_back", "from": "%s", "to": "9.9.9", "detail": "unhealthy"}' % __version__, encoding="utf-8")
    _page, root, _q = boot()
    assert "بازگردانده شد" in collect_text(find(root, "update_notice"))
    assert not (data / ui.RESULT_FILE).exists()


def test_main_without_a_result_has_no_notice():
    _page, root, _q = boot()
    assert find(root, "update_notice") is None and find(root, "update_notice_holder").visible is False


def test_main_with_default_installer_in_dev_mode_shows_the_plain_banner():
    """اجرا از سورس (نه exe) ⇒ نصبِ خودکار ممکن نیست ⇒ همان بنرِ N14a."""
    bot_manager._manager = None  # noqa: SLF001
    onboarded()
    page = FakePage()
    main(page, checker=StubChecker(INFO), start_update_thread=False)
    root = page.controls[0].content
    assert find(root, "update_banner") is not None and find(root, "update_install") is None


def test_about_install_button_appears_only_when_install_is_possible_and_reopens_the_banner():
    page, root, _q = boot(checker=StubChecker(INFO))
    fire(find(root, "update_later"), "on_click")  # کاربر «بعداً» زده
    assert find(root, "update_banner_holder").visible is False
    fire(find(page.controls[0].content, "nav_about"), "on_click")
    view = page.controls[0].content  # بعد از ناوبری، شِلِ تازه ساخته می‌شه
    fire(find(view, "about_check"), "on_click")
    button = find(view, "about_update_install")
    assert button is not None and button.visible is True
    fire(button, "on_click")  # بنر برمی‌گرده و مستقیم روی «تأیید» باز می‌شه
    assert find(view, "update_banner_holder").visible is True and find(view, "update_confirm_yes") is not None


def test_about_hides_the_install_button_in_manual_mode():
    page, _root, _q = boot(installer=FakeInstaller(mode=ui.MODE_MANUAL), checker=StubChecker(INFO))
    fire(find(page.controls[0].content, "nav_about"), "on_click")
    view = page.controls[0].content
    fire(find(view, "about_check"), "on_click")
    assert find(view, "about_update_link").visible is True and find(view, "about_update_install").visible is False


def test_about_screen_standalone_wiring():
    page, calls = FakePage(), []
    checker = StubChecker(INFO)
    root = about.build(page, "fa", AppSettings(), lambda: None, checker=checker, version="1.1.0", can_install=lambda i: True, on_install=calls.append)
    fire(find(root, "about_check"), "on_click")
    fire(find(root, "about_update_install"), "on_click")
    assert calls == [INFO]
    # بدونِ can_install/on_install (امضای قدیمی) دکمه هرگز نمی‌آید
    page2 = FakePage()
    root2 = about.build(page2, "fa", AppSettings(), lambda: None, checker=checker, version="1.1.0")
    fire(find(root2, "about_check"), "on_click")
    assert find(root2, "about_update_install").visible is False


def test_real_checker_undismiss_semantics_used_by_the_about_button():
    state = AppSettings()
    checker = UpdateChecker(lambda: state, lambda: None, current_version="1.1.0")
    checker.last = CheckResult(STATUS_UPDATE, info=INFO)
    checker.dismiss("1.2.0")
    assert checker.pending() is None
    checker.dismiss("")
    assert checker.pending() == INFO
