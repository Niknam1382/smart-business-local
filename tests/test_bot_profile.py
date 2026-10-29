"""N17: نشانِ کوچکِ سازنده در بیوگرافیِ ربات — ساختِ متن، قواعدِ ایمنی (هرگز پاک/کوتاه نکردنِ متنِ فروشنده)،
همگام‌سازیِ چندزبانه، بازگردانیِ خطِ حذف‌شده، تلگرام و بله روی سرورِ جعلی، و اینکه جای دیگری از ربات اعتبار نداره."""

import asyncio

import pytest
from fake_servers import FakeBotApiServer
from fakes import FakeEngine
from helpers import wait_until

from app import branding
from app.core import ai_engine, bot_profile
from app.core.bale_adapter import BaleAdapter
from app.core.bale_client import BaleClient
from app.core.bot_manager import BotManager, BotManagerError
from app.core.bot_profile import (
    STATUS_ERROR, STATUS_FLOOD, STATUS_NEEDS_CONFIRM, STATUS_OK, STATUS_TOO_LONG, STATUS_UNSUPPORTED, STATUS_UPDATED,
    BioTooLong, ProfileError, ProfileFlood, ProfileUnsupported, compose, sync_profile,
)
from app.core.conversations import ConversationStore
from app.core.settings import AppSettings
from app.core.telegram_adapter import TelegramAdapter

FA, EN, SEP = branding.CREDIT_FA, branding.CREDIT_EN, branding.CREDIT_SEPARATOR
TG_TOKEN = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
BALE_TOKEN = "987654321:BALEtokenBALEtokenBALEtoken12345"


def run(coro):
    return asyncio.run(coro)


# ================================================================== متن ====

def test_compose_joins_with_the_fixed_separator_and_credit_only_when_empty():
    assert compose("فروشگاهِ لوازم‌التحریر", "fa") == "فروشگاهِ لوازم‌التحریر" + SEP + FA
    assert compose("Pens & paper", "en") == "Pens & paper" + SEP + EN
    assert compose("", "fa") == FA and compose("   ", "en") == EN


def test_seller_share_boundary_is_measured_in_utf16_units():
    limit = bot_profile.seller_limit("fa")
    assert 55 <= limit <= 70  # «سهمِ فروشنده ≈ ۶۰–۶۵» در مستر پرامپت
    assert bot_profile.utf16_len(compose("a" * limit, "fa")) == bot_profile.SHORT_MAX
    with pytest.raises(BioTooLong) as exc:
        compose("a" * (limit + 1), "fa")
    assert exc.value.over == 1 and exc.value.limit == 120
    # ایموجی ۲ واحد است
    assert compose("😀" * (limit // 2), "fa")
    with pytest.raises(BioTooLong):
        compose("😀" * (limit // 2 + 1), "fa")


def test_credit_is_never_duplicated_and_can_be_stripped_in_both_languages():
    once = compose("سلام", "fa")
    assert compose(once, "fa") == once  # چسباندنِ کلِ بیو دوباره اعتبار اضافه نمی‌کنه
    assert bot_profile.strip_credit(once) == "سلام"
    assert bot_profile.strip_credit(compose("Hello", "en")) == "Hello"
    assert bot_profile.strip_credit(FA) == "" and bot_profile.strip_credit("بدونِ اعتبار") == "بدونِ اعتبار"
    assert bot_profile.has_credit(once) and not bot_profile.has_credit("سلام")


def test_clean_removes_control_and_bidi_but_keeps_zwnj_and_collapses_lines():
    assert bot_profile.clean("می\u200cخوام\nسلام\t\u202e ب\x00ی") == "می\u200cخوام سلام بی"  # کنترلی حذف می‌شه، خط/تب فاصله
    assert compose("خط۱\nخط۲", "fa").startswith("خط۱ خط۲ · ")


def test_counter_and_suggested_bio_never_raise():
    assert bot_profile.counter("", "fa") == f"0/{bot_profile.seller_limit('fa')}"
    assert bot_profile.counter("سلام", "fa").startswith("4/")
    assert bot_profile.suggested_bio("x" * 500, "fa") == FA  # بلند ⇒ فقط اعتبار؛ UI هشدار می‌ده
    assert bot_profile.suggested_bio("سلام", "fa").endswith(FA)


# ============================================================ همگام‌سازی ====

class FakeProfile:
    def __init__(self, texts=None):
        self.texts = dict(texts or {})
        self.sets = []
        self.get_error = None
        self.set_error = None

    async def get_short_description(self, language_code):
        if self.get_error:
            raise self.get_error
        return self.texts.get(language_code, self.texts.get("", ""))

    async def set_short_description(self, text, language_code):
        if self.set_error:
            raise self.set_error
        self.sets.append((language_code, text))
        self.texts[language_code] = text


def sync(client, seller="", confirmed=False, default_lang="fa", languages=bot_profile.DEFAULT_LANGS):
    return run(sync_profile(client, seller_text=seller, confirmed=confirmed, default_lang=default_lang, languages=languages, platform="telegram"))


def test_empty_bio_gets_only_the_credit_line_and_other_languages_are_left_alone():
    c = FakeProfile()
    report = sync(c)
    assert report.status == STATUS_UPDATED and c.sets == [("", FA)]


def test_second_run_is_idempotent_no_writes():
    c = FakeProfile()
    sync(c, "فروشگاه")
    before = list(c.sets)
    report = sync(c, "فروشگاه")
    assert report.status == STATUS_OK and c.sets == before


def test_existing_seller_text_is_never_overwritten_before_confirmation():
    original = "فروشگاهِ آنلاینِ ما — ارسال به سراسر ایران"
    c = FakeProfile({"": original})
    report = sync(c, confirmed=False)
    assert report.status == STATUS_NEEDS_CONFIRM and c.sets == []
    assert report.existing_default == original and c.texts[""] == original


def test_after_confirmation_the_credit_is_appended_to_the_existing_text_and_text_is_adopted():
    original = "فروشگاهِ آنلاینِ ما"
    c = FakeProfile({"": original})
    report = sync(c, confirmed=True)
    assert report.status == STATUS_UPDATED and report.adopted_text == original
    assert c.texts[""] == original + SEP + FA and c.texts[""].startswith(original)  # متنِ فروشنده بی‌تغییر، اعتبار در انتها


def test_seller_text_from_the_app_replaces_remote_without_needing_confirmation():
    c = FakeProfile({"": "متنِ قدیمی"})
    report = sync(c, seller="متنِ تازه")  # فروشنده خودش در برنامه نوشته؛ پیش‌نمایش را دیده
    assert report.status == STATUS_UPDATED and c.texts[""] == "متنِ تازه" + SEP + FA


def test_removed_credit_line_is_restored():
    c = FakeProfile()
    sync(c, "فروشگاه")
    c.texts[""] = "فروشگاه"  # با BotFather پاک شد
    report = sync(c, "فروشگاه")
    assert report.status == STATUS_UPDATED and c.texts[""] == "فروشگاه" + SEP + FA
    c.texts[""] = ""  # کاملاً خالی شد
    assert sync(c, "").status == STATUS_UPDATED and c.texts[""] == FA


def test_already_credited_remote_needs_no_confirmation_and_text_is_adopted():
    c = FakeProfile({"": "متنِ من" + SEP + FA})
    report = sync(c, confirmed=False)
    assert report.status == STATUS_OK and c.sets == []


def test_dedicated_language_versions_get_the_credit_in_their_own_language():
    c = FakeProfile({"": "پیش‌فرض", "fa": "فارسی", "en": "English text"})
    report = sync(c, seller="پیش‌فرض")
    assert report.status == STATUS_UPDATED
    assert c.texts[""] == "پیش‌فرض" + SEP + FA
    assert c.texts["fa"] == "فارسی" + SEP + FA and c.texts["en"] == "English text" + SEP + EN
    assert report.updated == ["", "fa", "en"]


def test_languages_without_a_dedicated_text_are_not_written():
    c = FakeProfile({"": "همان متن"})
    sync(c, seller="همان متن")
    assert [code for code, _t in c.sets] == [""]


def test_too_long_text_is_never_truncated_and_nothing_is_written():
    limit = bot_profile.seller_limit("fa")
    long_text = "ا" * (limit + 5)
    c = FakeProfile({"": long_text})
    report = sync(c, confirmed=True)
    assert report.status == STATUS_TOO_LONG and report.over == 5 and c.sets == [] and c.texts[""] == long_text
    c2 = FakeProfile()
    report2 = sync(c2, seller=long_text)
    assert report2.status == STATUS_TOO_LONG and c2.sets == []


def test_too_long_dedicated_language_does_not_block_the_others():
    limit = bot_profile.seller_limit("en")
    c = FakeProfile({"": "ok", "en": "e" * (limit + 3), "fa": "فارسی"})
    report = sync(c, seller="ok")
    assert report.status == STATUS_TOO_LONG and "en" in report.detail
    assert c.texts["fa"] == "فارسی" + SEP + FA and c.texts["en"] == "e" * (limit + 3)


def test_english_bots_get_the_english_credit_by_default():
    c = FakeProfile()
    sync(c, seller="Best shop", default_lang="en")
    assert c.texts[""] == "Best shop" + SEP + EN


def test_api_failures_are_reported_not_raised_and_never_corrupt_text():
    c = FakeProfile({"": "x"})
    c.get_error = ProfileFlood(3)
    assert sync(c, confirmed=True).status == STATUS_FLOOD
    c.get_error = ProfileUnsupported("nf")
    assert sync(c, confirmed=True).status == STATUS_UNSUPPORTED
    c.get_error = ProfileError("net")
    assert sync(c, confirmed=True).status == STATUS_ERROR
    c.get_error = RuntimeError("boom")
    assert sync(c, confirmed=True).status == STATUS_ERROR
    c.get_error = None
    c.set_error = ProfileFlood(1)
    assert sync(c, confirmed=True).status == STATUS_FLOOD and c.texts[""] == "x"
    c.set_error = ProfileError("500")
    assert sync(c, confirmed=True).status == STATUS_ERROR and c.texts[""] == "x"
    c.set_error = ProfileUnsupported("nf")
    assert sync(c, confirmed=True).status == STATUS_UNSUPPORTED


def test_bale_style_single_language_sync():
    c = FakeProfile({"": "فروشگاه بله"})
    report = sync(c, confirmed=True, languages=("",))
    assert report.status == STATUS_UPDATED and c.texts[""] == "فروشگاه بله" + SEP + FA


# ======================================================= تلگرام/بله روی سرورِ جعلی ====

@pytest.fixture
def servers():
    tg = FakeBotApiServer(username="tg_shop_bot").start()
    bale = FakeBotApiServer(username="bale_shop_bot").start()
    yield tg, bale
    tg.stop()
    bale.stop()


@pytest.fixture
def engine(monkeypatch):
    eng = FakeEngine(reply=lambda text: f"پاسخ: {text}")
    monkeypatch.setattr(ai_engine, "build_engine_from_settings", lambda s: eng)
    return eng


def make_manager(tmp_path, tg, bale, settings=None, **kw):
    s = settings or AppSettings()
    s.system_prompt = "تو فروشنده‌ای."
    s.set_telegram_token(TG_TOKEN)
    s.set_bale_token(BALE_TOKEN)
    factories = {
        "telegram": lambda st, p: TelegramAdapter(st.get_telegram_token(), p, api_base=tg.base_url, retry_delays=(0.1, 0.3), poll_timeout=1),
        "bale": lambda st, p: BaleAdapter(
            st.get_bale_token(), p, poll_timeout=1, retry_delays=(0.1, 0.3), client_factory=lambda tok: BaleClient(tok, base_url_template=bale.url_template)
        ),
    }
    store = ConversationStore(db_path=tmp_path / "bio.db")
    manager = BotManager(
        s, store=store, adapter_factories=factories, pipeline_kwargs=dict(debounce_wait=0.15, debounce_max_wait=0.5), log_dir=tmp_path,
        profile_poll=0.05, profile_retry=0.2, **kw,
    )
    manager._persist_settings = lambda: None  # بدونِ نوشتنِ settings.json روی دیسکِ واقعی
    return manager, s, store


def test_fresh_bots_get_the_credit_automatically_after_connecting(tmp_path, servers, engine):
    tg, bale = servers
    manager, _s, _store = make_manager(tmp_path, tg, bale)
    manager.start()
    try:
        assert wait_until(lambda: tg.short_descriptions.get("") == FA and bale.short_descriptions.get("") == FA)
        assert tg.short_description_sets == [("", FA)]  # یک‌بار؛ زبان‌های دیگر دست نخوردن
        assert wait_until(lambda: manager.profile_reports().get("telegram") and manager.profile_reports().get("bale"))
        assert manager.profile_reports()["telegram"].status == STATUS_UPDATED
    finally:
        manager.stop()


def test_existing_bio_waits_for_confirmation_then_credit_is_appended(tmp_path, servers, engine):
    tg, bale = servers
    tg.short_descriptions[""] = "فروشگاهِ پوشاکِ سارا"
    bale.short_description_mode = "unsupported"
    manager, s, store = make_manager(tmp_path, tg, bale)
    manager.start()
    try:
        assert wait_until(lambda: manager.profile_reports().get("telegram") is not None)
        assert manager.profile_reports()["telegram"].status == STATUS_NEEDS_CONFIRM
        assert tg.short_description_sets == [] and tg.short_descriptions[""] == "فروشگاهِ پوشاکِ سارا"  # دست‌نخورده
        assert any(i.type == "bio_confirm" for i in manager.attention.list_open())
        s.bot_bio_confirmed = True  # فروشنده در UI تأیید کرد
        reports = manager.sync_profiles_now()
        assert reports["telegram"].status == STATUS_UPDATED
        assert tg.short_descriptions[""] == "فروشگاهِ پوشاکِ سارا" + SEP + FA
        assert s.bot_bio_text == "فروشگاهِ پوشاکِ سارا"  # متن در تنظیمات هم ثبت شد
    finally:
        manager.stop()


def test_removed_credit_is_restored_on_the_next_sync(tmp_path, servers, engine):
    tg, bale = servers
    manager, s, _ = make_manager(tmp_path, tg, bale)
    s.bot_bio_text = "فروشگاه من"
    manager.start()
    try:
        assert wait_until(lambda: tg.short_descriptions.get("") == "فروشگاه من" + SEP + FA)
        tg.short_descriptions[""] = "فروشگاه من"  # با BotFather حذف شد
        manager.sync_profiles_now()
        assert tg.short_descriptions[""] == "فروشگاه من" + SEP + FA
    finally:
        manager.stop()


def test_bale_without_support_is_remembered_and_not_retried_until_reset(tmp_path, servers, engine):
    tg, bale = servers
    bale.short_description_mode = "unsupported"
    manager, s, _ = make_manager(tmp_path, tg, bale)
    manager.start()
    try:
        assert wait_until(lambda: s.bale_bio_supported is False)
        assert manager.profile_reports()["bale"].status == STATUS_UNSUPPORTED
        assert wait_until(lambda: tg.short_descriptions.get("") == FA)  # تلگرام کارش را کرد
        calls_before = sum(1 for c in bale.calls if "ShortDescription" in c)
        manager.sync_profiles_now()
        assert sum(1 for c in bale.calls if "ShortDescription" in c) == calls_before  # دیگه صدا زده نمی‌شه
        # «امتحانِ دوباره»: این بار بله پشتیبانی می‌کنه
        bale.short_description_mode = "ok"
        manager.reset_bale_bio_probe()
        assert s.bale_bio_supported is None
        manager.sync_profiles_now()
        assert bale.short_descriptions.get("") == FA and s.bale_bio_supported is True
    finally:
        manager.stop()


def test_flood_is_silent_and_retried_later_without_touching_the_bot(tmp_path, servers, engine):
    tg, bale = servers
    tg.short_description_mode = "flood"
    manager, s, _ = make_manager(tmp_path, tg, bale)
    manager.start()
    try:
        assert wait_until(lambda: manager.profile_reports().get("telegram") is not None and manager.profile_reports()["telegram"].status == STATUS_FLOOD)
        assert manager.get_status().platforms["telegram"].connected  # ربات سالم می‌مونه
        tg.short_description_mode = "ok"
        assert wait_until(lambda: tg.short_descriptions.get("") == FA, timeout=10)  # تلاشِ بعدیِ خودکار
    finally:
        manager.stop()


def test_server_error_never_breaks_the_bot_and_reports_error(tmp_path, servers, engine):
    tg, bale = servers
    tg.short_description_mode = "error"
    manager, _s, _ = make_manager(tmp_path, tg, bale)
    manager.start()
    try:
        assert wait_until(lambda: manager.profile_reports().get("telegram") is not None and manager.profile_reports()["telegram"].status == STATUS_ERROR)
        assert manager.get_status().platforms["telegram"].connected
    finally:
        manager.stop()


def test_sync_now_requires_running_bots(tmp_path, servers):
    tg, bale = servers
    manager, _s, _ = make_manager(tmp_path, tg, bale)
    with pytest.raises(BotManagerError):
        manager.sync_profiles_now()


def test_credit_never_appears_in_any_customer_message(tmp_path, servers, engine):
    tg, bale = servers
    manager, s, _ = make_manager(tmp_path, tg, bale)
    s.bot_bio_text = "فروشگاه من"
    manager.start()
    try:
        assert wait_until(lambda: tg.short_descriptions.get("") is not None)
        tg.push_message(555, "سلام", first_name="سارا")
        tg.push_message(555, "/start", first_name="سارا")
        assert wait_until(lambda: len(tg.sent_to(555)) >= 1)
        bale.push_message(777, "سلام", first_name="رضا")
        assert wait_until(lambda: len(bale.sent_to(777)) >= 1)
        for message in tg.sent_to(555) + bale.sent_to(777):
            assert "github.com/niknam1382" not in message and FA not in message and EN not in message
        for entry in tg.sent + bale.sent:
            assert "niknam1382" not in str(entry)
    finally:
        manager.stop()
