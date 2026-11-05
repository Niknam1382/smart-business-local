"""رابطِ «پروفایلِ ربات» (N17، نسخه‌ی ۱.۰.۰): پیش‌نمایش، شمارنده، تأییدِ بیوگرافیِ موجود و ذخیره‌ی آیکن — فقط تلگرام."""

from pathlib import Path

from fake_page import FakePage, collect_text, find, fire

from app import branding, theme
from app.core import bot_profile
from app.core.bot_manager import BotManagerError
from app.core.bot_profile import STATUS_NEEDS_CONFIRM, STATUS_OK, STATUS_TOO_LONG, STATUS_UNSUPPORTED, STATUS_UPDATED, SyncReport
from app.core.settings import AppSettings
from app.screens import bot_profile_card, common

FA = branding.CREDIT_FA
SEP = branding.CREDIT_SEPARATOR


class StubManager:
    def __init__(self, reports=None, error=None):
        self._reports = dict(reports or {})
        self.error = error
        self.syncs = 0

    def profile_reports(self):
        return dict(self._reports)

    def sync_profiles_now(self, timeout=40.0):
        self.syncs += 1
        if self.error:
            raise self.error
        return self._reports


def build(manager=None, lang="fa", settings=None):
    page = FakePage()
    settings = settings or AppSettings()
    saves = []
    root = bot_profile_card.build(page, lang, settings, lambda: saves.append(1), manager)
    return page, root, settings, saves


def test_builds_in_both_languages_with_locked_credit_and_explanation():
    for lang in ("fa", "en"):
        settings = AppSettings()
        settings.bot_language = lang  # زبانِ خطِ اعتبار = زبانِ رباتِ مشتری
        _page, root, _s, _ = build(lang=lang, settings=settings)
        assert find(root, "sec_profile") is not None
        assert find(root, "bio_credit").value.endswith(branding.credit_for(lang))
        assert "🔒" in find(root, "bio_credit").value
        intro = find(root, "bio_intro").value
        assert ("فقط" in intro) if lang == "fa" else ("Only" in intro)
    # قفل = متنِ فقط‌خواندنی؛ هیچ فیلدِ قابل‌ویرایشی برای خطِ اعتبار نیست
    _page, root, _s, _ = build()
    assert find(root, "bio_credit").__class__.__name__ == "Text"


def test_typing_updates_counter_and_final_preview_with_the_credit_line():
    _page, root, _s, _ = build()
    assert find(root, "bio_preview").value == FA  # بدونِ متن فقط اعتبار
    fire(find(root, "bio_text"), "on_change", value="فروشگاهِ سارا")
    assert find(root, "bio_preview").value == "فروشگاهِ سارا" + SEP + FA
    assert find(root, "bio_counter").value == f"13/{bot_profile.seller_limit('fa')}"


def test_too_long_text_shows_an_error_and_save_refuses_without_touching_settings():
    manager = StubManager()
    _page, root, settings, saves = build(manager)
    fire(find(root, "bio_text"), "on_change", value="ا" * (bot_profile.seller_limit("fa") + 3))
    preview = find(root, "bio_preview")
    assert preview.color == theme.DANGER and "3" in preview.value
    fire(find(root, "bio_save"), "on_click")
    assert settings.bot_bio_text == "" and saves == [] and manager.syncs == 0
    assert find(root, "bio_note").visible and find(root, "bio_note").color == theme.DANGER


def test_save_persists_text_syncs_and_shows_telegram_status():
    manager = StubManager({"telegram": SyncReport(STATUS_UPDATED, "telegram")})
    _page, root, settings, saves = build(manager)
    fire(find(root, "bio_text"), "on_change", value="فروشگاه من")
    fire(find(root, "bio_save"), "on_click")
    assert settings.bot_bio_text == "فروشگاه من" and saves == [1] and manager.syncs == 1
    assert "✅" in find(root, "bio_status_telegram").value
    assert find(root, "bio_status_bale") is None and find(root, "bio_bale_box") is None  # ۱.۰.۰: هیچ ردیف/جعبه‌ی بله نیست
    assert find(root, "bio_note").color == theme.SUCCESS


def test_when_bots_are_off_text_is_still_saved_with_a_friendly_note():
    manager = StubManager(error=BotManagerError("خاموش"))
    _page, root, settings, saves = build(manager)
    fire(find(root, "bio_text"), "on_change", value="متن")
    fire(find(root, "bio_save"), "on_click")
    assert settings.bot_bio_text == "متن" and saves == [1]
    assert "بعد از روشن" in find(root, "bio_note").value
    _page, root, settings, _ = build(None)  # بدونِ manager هم می‌ترکه
    fire(find(root, "bio_save"), "on_click")
    assert "بعد از روشن" in find(root, "bio_note").value


def test_status_before_bots_run_is_not_connected_yet():
    _page, root, _s, _ = build(StubManager())
    assert "هنوز" in find(root, "bio_status_telegram").value


def test_existing_bio_is_shown_and_only_changes_after_explicit_confirmation():
    report = SyncReport(STATUS_NEEDS_CONFIRM, "telegram", existing={"": "فروشگاهِ پوشاکِ سارا"})
    manager = StubManager({"telegram": report})
    _page, root, settings, saves = build(manager)
    box = find(root, "bio_confirm_box")
    assert box.visible is True and "فروشگاهِ پوشاکِ سارا" in find(root, "bio_confirm_existing").value
    assert "⏸" in find(root, "bio_status_telegram").value
    fire(find(root, "bio_confirm_no"), "on_click")
    assert box.visible is False and settings.bot_bio_confirmed is False and manager.syncs == 0  # هیچ‌چیز نوشته نشد
    _page, root, settings, saves = build(manager)
    fire(find(root, "bio_confirm_yes"), "on_click")
    assert settings.bot_bio_confirmed is True and manager.syncs == 1 and saves == [1]


def test_too_long_existing_bio_status_is_a_warning():
    manager = StubManager({"telegram": SyncReport(STATUS_TOO_LONG, "telegram", over=7)})
    _page, root, _s, _ = build(manager)
    assert "7" in find(root, "bio_status_telegram").value and "⚠️" in find(root, "bio_status_telegram").value


def test_bale_reports_are_ignored_in_the_ui():
    # داده‌ی قدیمیِ بله در گزارش‌ها باشه، صفحه فقط وضعیتِ تلگرام را نشون می‌ده و جعبه‌ی پیشنهادِ بله ساخته نمی‌شه.
    manager = StubManager({"telegram": SyncReport(STATUS_OK, "telegram"), "bale": SyncReport(STATUS_UNSUPPORTED, "bale")})
    _page, root, _s, _ = build(manager)
    assert find(root, "bio_bale_box") is None and "بله" not in collect_text(root)


def test_icon_save_copies_the_real_icon_into_the_data_folder(monkeypatch):
    from app.core import paths

    opened = []
    monkeypatch.setattr(common, "open_folder", lambda p: opened.append(Path(p)) or True)
    _page, root, _s, _ = build()
    fire(find(root, "bio_icon_save"), "on_click")
    saved = paths.get_app_data_dir() / "exports" / "smart-business-icon.png"
    assert saved.is_file() and saved.stat().st_size > 1000 and opened == [saved.parent]
    assert "smart-business-icon.png" in find(root, "bio_icon_note").value
    assert bot_profile_card.ICON_SOURCE.is_file()


def test_section_is_part_of_the_bot_experience_screen(tmp_path):
    from app.core.orders import OrderStore
    from app.core.products import ProductStore
    from app.screens import bot_experience

    page = FakePage()
    products = ProductStore(tmp_path / "p.db")
    root = bot_experience.build(page, "fa", AppSettings(), lambda: None, products, OrderStore(tmp_path / "o.db", product_store=products), None)
    assert find(root, "sec_profile") is not None and find(root, "bio_save") is not None
    assert "پروفایلِ ربات" in collect_text(root)
