"""N13 — کارتِ تنظیماتِ «عضویتِ اجباریِ کانال» (UI با Page جعلی) و جایگیری‌اش در تبِ «پیشرفته»."""

import pytest
from fake_page import FakePage, collect_text, find, fire

from app import theme
from app.core.bot_manager import BotManagerError
from app.core.settings import AppSettings
from app.screens import bot_experience, required_channels_card


class FakeManager:
    def __init__(self):
        self.result, self.calls = (True, "administrator"), []

    def test_channel_sync(self, platform, channel):
        self.calls.append((platform, channel))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class Rig:
    def __init__(self, with_manager=True, **settings_kw):
        self.settings = AppSettings()
        for k, v in settings_kw.items():
            setattr(self.settings, k, v)
        self.saves = 0
        self.manager = FakeManager() if with_manager else None
        self.page = FakePage()
        self.card = required_channels_card.build(self.page, "fa", self.settings, self.save, self.manager)

    def save(self):
        self.saves += 1

    def f(self, key):
        return find(self.card, key)

    def add(self, channel, platform="telegram", title="", link=""):
        self.f("rc_platform").value = platform
        self.f("rc_channel").value, self.f("rc_title").value, self.f("rc_link").value = channel, title, link
        fire(self.f("rc_add"), "on_click")

    def note(self):
        n = self.f("rc_note")
        return (n.value, n.color) if n.visible else ("", None)


def test_defaults_are_off_with_an_empty_list_and_everywhere_scope():
    r = Rig()
    assert r.f("rc_enabled").value is False and r.f("rc_scope").value == "both" and "هنوز کانالی اضافه نشده" in collect_text(r.f("rc_list"))
    assert sorted(o.key for o in r.f("rc_scope").options) == ["ai", "both", "shop"]


def test_adding_a_channel_normalizes_it_saves_and_shows_it():
    r = Rig()
    r.add("https://t.me/MyShopChannel", title="  کانالِ  فروشگاه ")
    assert r.settings.required_channels == [{"platform": "telegram", "channel": "@MyShopChannel", "title": "کانالِ فروشگاه", "link": "https://t.me/MyShopChannel"}]
    assert r.saves == 1 and r.note()[1] == theme.SUCCESS and "تستِ دسترسی" in r.note()[0]
    assert "@MyShopChannel" in collect_text(r.f("rc_list")) and "کانالِ فروشگاه" in collect_text(r.f("rc_list"))
    assert r.f("rc_channel").value == r.f("rc_title").value == r.f("rc_link").value == ""  # فرم خالی شد
    r.add("bale_chan", platform="bale")
    assert [c["platform"] for c in r.settings.required_channels] == ["telegram", "bale"]
    assert r.settings.required_channels[1]["link"] == "https://ble.ir/bale_chan"


@pytest.mark.parametrize("channel, link, pattern", [
    ("", "", "نامِ کانال"), ("@abc", "", "معتبر نیست"), ("-1001234567890", "", "لینکِ دعوت"),
    ("@good_channel", "javascript:alert(1)", "http"), ("https://t.me/+AbCdEfGhIj", "", "دعوتِ خصوصی"),
])
def test_invalid_input_is_rejected_with_a_persian_error_and_nothing_is_saved(channel, link, pattern):
    r = Rig()
    r.add(channel, link=link)
    value, color = r.note()
    assert pattern in value and color == theme.DANGER and r.settings.required_channels == [] and r.saves == 0


def test_duplicates_and_the_channel_limit_are_refused():
    r = Rig()
    r.add("@shop_channel")
    r.add("https://t.me/shop_channel")
    assert "قبلاً اضافه شده" in r.note()[0] and len(r.settings.required_channels) == 1
    r.add("@shop_channel", platform="bale")  # همان نام روی بله = کانالِ دیگر
    assert len(r.settings.required_channels) == 2
    for i in range(8):
        r.add(f"@chan_number_{i}")
    assert len(r.settings.required_channels) == 10
    r.add("@one_more_chan")
    assert "حداکثر 10" in r.note()[0] and len(r.settings.required_channels) == 10


def test_removing_a_channel_saves_and_refreshes_the_list():
    r = Rig()
    r.add("@first_chan")
    r.add("@second_chan")
    saves = r.saves
    fire(r.f("rc_del_telegram_@first_chan"), "on_click")
    assert [c["channel"] for c in r.settings.required_channels] == ["@second_chan"] and r.saves == saves + 1
    assert "@first_chan" not in collect_text(r.f("rc_list")) and "حذف شد" in r.note()[0]


def test_toggle_and_scope_persist_immediately():
    r = Rig()
    fire(r.f("rc_enabled"), "on_change", value=True)
    assert r.settings.required_channels_enabled is True and r.saves == 1 and "کانالی اضافه نکرده‌ای" in r.note()[0]
    r.add("@shop_channel")
    fire(r.f("rc_enabled"), "on_change", value=True)
    assert r.note()[0] == "ذخیره شد."
    fire(r.f("rc_scope"), "on_select", "ai")
    assert r.settings.required_channels_scope == "ai"
    fire(r.f("rc_scope"), "on_select", "bogus")  # مقدارِ نامعتبر نادیده گرفته می‌شود
    assert r.settings.required_channels_scope == "ai"
    fire(r.f("rc_enabled"), "on_change", value=False)
    assert r.settings.required_channels_enabled is False


def test_stored_state_is_shown_and_corrupt_rows_never_crash_the_card():
    r = Rig(
        required_channels_enabled=True, required_channels_scope="shop",
        required_channels=[{"platform": "bale", "channel": "@bale_chan", "title": "بله", "link": "https://ble.ir/bale_chan"}, "garbage", None, {"platform": "x"}],
    )
    assert r.f("rc_enabled").value is True and r.f("rc_scope").value == "shop" and "@bale_chan" in collect_text(r.f("rc_list"))
    r.add("@other_chan")  # ذخیره‌ی بعدی ردیف‌های خراب را هم پاک می‌کند
    assert [c["channel"] for c in r.settings.required_channels] == ["@bale_chan", "@other_chan"]
    assert Rig(required_channels_scope="weird").f("rc_scope").value == "both"


@pytest.mark.parametrize("result, expected, ok", [
    ((True, "administrator"), "ادمین است", True),
    ((True, "creator"), "ادمین است", True),
    ((True, "member"), "فقط عضوِ این کانال", False),
    ((False, "BadRequest: chat not found"), "chat not found", False),
    (BotManagerError("ربات‌ها خاموشن؛ اول از صفحه‌ی «ربات‌ها» روشنشون کن."), "خاموشن", False),
    (RuntimeError("boom"), "دسترسی نداره", False),
])
def test_access_test_reports_each_outcome(result, expected, ok):
    r = Rig()
    r.add("@shop_channel")
    r.manager.result = result
    fire(r.f("rc_test_telegram_@shop_channel"), "on_click")
    value, color = r.note()
    assert expected in value and (color == theme.SUCCESS) is ok
    assert r.manager.calls == [("telegram", "@shop_channel")]


def test_access_test_without_a_manager_asks_to_turn_the_bots_on():
    r = Rig(with_manager=False)
    r.add("@shop_channel")
    fire(r.f("rc_test_telegram_@shop_channel"), "on_click")
    assert "اول ربات‌ها رو روشن کن" in r.note()[0]


def test_english_card():
    page = FakePage()
    card = required_channels_card.build(page, "en", AppSettings(), lambda: None, None)
    assert "Required channel membership" in collect_text(card) and find(card, "rc_add").content == "Add channel"


def test_the_card_lives_in_the_advanced_tab_of_the_bot_experience_screen(tmp_path):
    from app.core.orders import OrderStore
    from app.core.products import ProductStore

    settings = AppSettings()
    root = bot_experience.build(FakePage(), "fa", settings, lambda: None, ProductStore(tmp_path / "p.db"), OrderStore(tmp_path / "o.db", product_store=ProductStore(tmp_path / "p2.db")))
    panel = find(root, "exp_panel_advanced")
    assert panel is not None and find(panel, "required_channels_card") is not None and find(panel, "rc_enabled") is not None
    assert find(find(root, "exp_panel_quick"), "required_channels_card") is None


def test_every_attention_type_has_a_label_in_the_inbox():
    from app.core import attention

    for type_ in attention.TYPES:
        assert f"i.{type_}" in bot_experience._S, type_  # نوعِ تازه بدونِ برچسب = ترکیدنِ صندوقِ «نیاز به توجه»
