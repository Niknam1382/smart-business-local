"""N8 — صفحه‌ی «تخفیف و کمپین» (UI با Page جعلی؛ منطق در test_discounts.py / test_campaigns.py)."""

from datetime import datetime, timedelta

import pytest
from fake_page import FakePage, collect_text, find, fire

from app.core.bot_manager import BotManager
from app.core.bot_pipeline import IncomingMessage
from app.core.conversations import ConversationStore
from app.core.orders import OrderStore
from app.core.products import ProductStore
from app.core.settings import AppSettings
from app.screens import discounts as screen


class Rig:
    def __init__(self, tmp_path, lang="fa"):
        self.products = ProductStore(tmp_path / "p.db")
        self.orders = OrderStore(tmp_path / "o.db", product_store=self.products)
        self.manager = BotManager(AppSettings(business_mode="store"), store=ConversationStore(db_path=tmp_path / "c.db"),
                                  product_store=self.products, order_store=self.orders, adapter_factories={}, log_dir=tmp_path)
        self.page = FakePage()
        self.control = screen.build(self.page, lang, self.manager, self.products)

    def f(self, key):
        return find(self.control, key)

    def type(self, **fields):
        for key, value in fields.items():
            self.f(key).value = value

    def click(self, key):
        fire(self.f(key), "on_click")

    def text(self, key):
        return collect_text(self.f(key))

    def notice(self, key="dc_notice"):
        n = self.f(key)
        return (n.value, n.color) if n.visible else ("", None)


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def test_parsers_handle_persian_digits_commas_and_garbage():
    assert screen.parse_toman("۵۰٬۰۰۰") == 500_000
    assert screen.parse_toman("") == 0 and screen.parse_toman("12abc") is None and screen.parse_toman("", allow_empty=False) is None
    assert screen.parse_count("۱۲") == 12 and screen.parse_count("-1") is None
    assert screen.parse_when("") == 0 and screen.parse_when("2026-13-45") is None
    assert screen.parse_when("2026-12-31") and screen.parse_when("2026-12-31 18:30") > screen.parse_when("2026-12-31")


def test_empty_state_and_create_percent_code(rig):
    assert "هنوز کدی نساخته‌ای" in rig.text("dc_list")
    rig.type(dc_code="welcome10", dc_value="۱۰")
    rig.click("dc_create")
    assert rig.notice() == ("✅ کدِ «WELCOME10» ساخته شد.", screen.theme.SUCCESS)
    code = rig.manager.discounts.find("welcome10")
    assert code.kind == "percent" and code.value == 10 and code.max_discount_irr == 0
    assert "WELCOME10" in rig.text("dc_list") and "۱۰٪" in rig.text("dc_list") or "10٪" in rig.text("dc_list")


def test_fixed_amount_is_entered_in_toman_and_stored_in_rials(rig):
    rig.type(dc_code="OFF50K", dc_value="50000", dc_min="500000")
    fire(rig.f("dc_kind"), "on_select", "fixed")
    rig.click("dc_create")
    code = rig.manager.discounts.find("OFF50K")
    assert code.kind == "fixed" and code.value == 500_000 and code.min_subtotal_irr == 5_000_000


def test_validation_messages_do_not_create_codes(rig):
    rig.type(dc_code="BAD", dc_value="abc")
    rig.click("dc_create")
    assert "عددِ درست" in rig.notice()[0] and rig.manager.discounts.list() == []
    rig.type(dc_value="100")  # ۱۰۰٪ مجاز نیست
    rig.click("dc_create")
    assert "۹۹" in rig.notice()[0] and rig.manager.discounts.list() == []
    rig.type(dc_value="10", dc_start="not-a-date")
    rig.click("dc_create")
    assert "تاریخ" in rig.notice()[0]
    rig.type(dc_start="")
    rig.click("dc_create")
    rig.type(dc_code="BAD", dc_value="10")
    rig.click("dc_create")
    assert "قبلاً ساخته" in rig.notice()[0] and len(rig.manager.discounts.list()) == 1


def test_scope_products_and_categories_are_saved(rig):
    pid = rig.products.add("کفش", 1_000_000, 5, category="پوشاک")
    other = screen.build(rig.page, "fa", rig.manager, rig.products)
    rig.control = other
    fire(rig.f("dc_scope"), "on_select", "products")
    assert rig.f("dc_products").visible is True
    fire(rig.f(f"dc_prod_{pid}"), "on_change", True)
    rig.type(dc_code="SHOES", dc_value="5")
    rig.click("dc_create")
    assert rig.manager.discounts.find("SHOES").targets == [pid]
    fire(rig.f("dc_scope"), "on_select", "categories")
    rig.type(dc_code="CATS", dc_value="5", dc_cats="پوشاک، کیف")
    rig.click("dc_create")
    assert rig.manager.discounts.find("CATS").targets == ["پوشاک", "کیف"]
    rig.type(dc_code="EMPTY", dc_value="5", dc_cats="")
    rig.click("dc_create")
    assert rig.manager.discounts.find("EMPTY") is None


def test_preset_fills_the_form_and_generated_code_is_valid(rig):
    fire(rig.f("dc_preset"), "on_select", "first10")
    assert rig.f("dc_first").value is True and rig.f("dc_value").value == "10"
    rig.click("dc_gen")
    generated = rig.f("dc_code").value
    assert len(generated) == 8
    rig.click("dc_create")
    assert rig.manager.discounts.find(generated).first_order_only is True


def test_toggle_and_two_step_delete_and_used_code_is_only_deactivated(rig):
    rig.type(dc_code="TOGGLE", dc_value="10")
    rig.click("dc_create")
    cid = rig.manager.discounts.find("TOGGLE").id
    fire(rig.f(f"dc_active_{cid}"), "on_change", False)
    assert rig.manager.discounts.get(cid).active is False and "غیرفعال" in rig.text("dc_list")
    rig.click(f"dc_del_{cid}")
    assert rig.manager.discounts.get(cid) is not None and "مطمئنی" in rig.text("dc_list")
    rig.click(f"dc_del_{cid}")
    assert rig.manager.discounts.get(cid) is None
    pid = rig.products.add("کالا", 100_000, 5)
    rig.type(dc_code="USED", dc_value="10")
    rig.click("dc_create")
    rig.orders.create("telegram", "1", [(pid, 1)], discount_code="USED")
    used = rig.manager.discounts.find("USED").id
    rig.click(f"dc_del_{used}"); rig.click(f"dc_del_{used}")
    assert rig.manager.discounts.get(used) is not None and rig.manager.discounts.get(used).active is False


def test_campaign_create_schedule_and_cancel(rig):
    rig.manager.customers.touch(IncomingMessage(platform="telegram", chat_id="1", display_name="", text="سلام"))
    rig.type(dc_code="SPRING", dc_value="10")
    rig.click("dc_create")
    rig.click("cm_create")
    assert "نامِ کمپین" in rig.notice("cm_notice")[0]
    code_id = rig.manager.discounts.find("SPRING").id
    assert str(code_id) in {o.key for o in rig.f("cm_code").options}
    rig.type(cm_name="بهار", cm_text="تخفیفِ بهاری!", cm_code=str(code_id), cm_when=(datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d %H:%M"))
    rig.click("cm_create")
    assert "✅" in rig.notice("cm_notice")[0]
    camp = rig.manager.campaigns.list()[0]
    assert camp.code_id == code_id and camp.status == "scheduled" and "بهار" in rig.text("cm_list")
    rig.click(f"cm_cancel_{camp.id}")
    assert rig.manager.campaigns.get(camp.id).status == "cancelled" and "لغو شد" in rig.text("cm_list")


def test_english_ui_builds(tmp_path):
    r = Rig(tmp_path, lang="en")
    assert "Discount codes" in r.text("dc_list") or r.f("dc_create").content == "Create code"
