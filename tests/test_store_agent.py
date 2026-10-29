"""
ادمینِ هوشمند (store_agent): ابزارها همه‌چیز رو سمتِ سرور اعتبارسنجی می‌کنن —
مدل نمی‌تونه قیمت/موجودی بسازه، سفارشِ مشتریِ دیگه رو ببینه، یا پرداخت رو تایید کنه.
"""

import asyncio
import json

import pytest
from fake_zarinpal import FakeZarinpalServer
from fakes import ScriptedToolEngine, say, tool

from app.core import ai_engine
from app.core.bale_client import BaleApiError
from app.core.orders import (
    METHOD_BALE_PAY,
    METHOD_CARD_TO_CARD,
    METHOD_ZARINPAL,
    STATUS_CANCELLED,
    STATUS_EXPIRED,
    STATUS_PAID,
    OrderStore,
)
from app.core.payments import PaymentHooks, PaymentService
from app.core.products import ProductStore
from app.core.settings import AppSettings
from app.core.store_agent import (
    FALLBACK_REPLY,
    StoreAgent,
    StoreToolbox,
    build_agent_prompt,
    normalize_fa,
)

MERCHANT = "12345678-1234-1234-1234-123456789012"


class FakeBaleClient:
    """جای BaleClient واقعی: فاکتورِ بومی رو ثبت می‌کنه و می‌تونه خطا بده. عمداً
    ``create_invoice_link`` نداره — مسیرِ پرداخت دیگه نباید ازش استفاده کنه."""

    def __init__(self):
        self.invoices = []
        self.fail_invoice = None

    async def send_invoice(self, chat_id, title, description, payload, provider_token, prices):
        self.invoices.append(dict(chat_id=chat_id, payload=payload, prices=prices, token=provider_token))
        if self.fail_invoice:
            raise BaleApiError(self.fail_invoice)


class Env:
    def __init__(self, tmp_path):
        self.products = ProductStore(db_path=tmp_path / "p.db")
        self.orders = OrderStore(db_path=tmp_path / "o.db", product_store=self.products)
        self.settings = AppSettings()
        self.settings.business_mode = "store"
        self.settings.shop_mode = "shop_ai"  # جریانِ AIِ ۰.۵.۰ (آزمایشی)؛ پیش‌فرضِ ۱.۰.۰ دکمه‌ایه
        self.settings.card_to_card_number = "6219-8610-1234-5678"
        self.settings.card_to_card_holder_name = "علی رضایی"
        self.zarinpal = FakeZarinpalServer(MERCHANT).start()
        self.payments = PaymentService(self.orders, self.products, self.settings, zarinpal_base_url=self.zarinpal.base_url)
        self.bale = FakeBaleClient()
        self.hooks = PaymentHooks(bale_client=lambda: self.bale, bot_username=lambda platform: f"{platform}_shop_bot")
        self.no_bale_hooks = PaymentHooks(bale_client=lambda: None, bot_username=lambda platform: None)

    def enable_bale_pay(self):
        self.settings.set_bale_pay_provider_token("WALLET-TEST-1")
        self.settings.bale_pay_enabled = True

    def enable_zarinpal(self):
        self.settings.set_zarinpal_merchant_id(MERCHANT)
        self.settings.zarinpal_enabled = True

    def box(self, platform="telegram", chat_id="1", hooks=None):
        return StoreToolbox(platform, chat_id, self.settings, self.products, self.orders, self.payments, hooks or self.hooks)

    def stop(self):
        self.zarinpal.stop()


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    e.stop()


def run(coro):
    return asyncio.run(coro)


def call(box, name, **args):
    return run(box.execute(name, args))


# ----------------------------------------------------------------- جست‌وجو


def test_normalize_persian_variants():
    assert normalize_fa("گوشي ۱۲۳ كتاب") == normalize_fa("گوشی 123 کتاب")
    assert normalize_fa("می‌خوام") == "می خوام"


def test_search_finds_by_name_description_and_arabic_letters(env):
    env.products.add("گوشی سامسونگ A54", 12_000_000, 3, description="رنگ مشکی، ۱۲۸ گیگ")
    env.products.add("هدفون بلوتوثی", 900_000, 10)
    box = env.box()
    assert [p["name"] for p in call(box, "search_products", query="گوشي")["products"]] == ["گوشی سامسونگ A54"]
    assert call(box, "search_products", query="مشکی")["count"] == 1
    assert call(box, "search_products", query="هدفون")["products"][0]["available"] == 10


def test_search_tolerates_typos_and_multiple_words(env):
    env.products.add("گوشی سامسونگ", 1000, 3)
    box = env.box()
    assert call(box, "search_products", query="سامسنگ")["count"] == 1, "غلطِ تایپی"
    assert call(box, "search_products", query="گوشی سامسونگ")["count"] == 1
    assert call(box, "search_products", query="لپ تاپ")["count"] == 0


def test_search_empty_query_lists_all_and_respects_limit(env):
    for i in range(12):
        env.products.add(f"کالا {i:02d}", 1000, 1)
    result = call(env.box(), "search_products", query="", limit=5)
    assert result["count"] == 12 and len(result["products"]) == 5 and "note" in result


def test_search_shows_availability_after_reservations_and_excludes_inactive(env):
    pid = env.products.add("گوشی", 1000, 3)
    hidden = env.products.add("مخفی", 1000, 3)
    env.products.set_active(hidden, False)
    env.orders.create("bale", "9", [(pid, 2)])
    products = call(env.box(), "search_products", query="")["products"]
    assert [(p["name"], p["available"]) for p in products] == [("گوشی", 1)]


# ----------------------------------------------------------------- create_order


def test_create_order_success_reserves_and_reports_everything_the_model_needs(env):
    pid = env.products.add("گوشی", 1_000_000, 5)
    r = call(env.box(), "create_order", items=[{"product_id": pid, "quantity": 2}], customer_name="علی")
    assert r["ok"] and r["total_irr"] == 2_000_000 and r["reserved_for_minutes"] == 15
    assert r["items"][0]["quantity"] == 2 and r["status"] == "pending_payment"
    assert [m["id"] for m in r["payment_methods"]] == [METHOD_CARD_TO_CARD]
    assert env.orders.available_quantity(pid) == 3
    assert env.orders.get(r["order_id"]).customer_name == "علی"


def test_create_order_uses_configured_reservation_minutes(env):
    env.settings.reservation_minutes = 30
    pid = env.products.add("گوشی", 1000, 5)
    r = call(env.box(), "create_order", items=[{"product_id": pid, "quantity": 1}])
    assert r["reserved_for_minutes"] == 30 and 29 * 60 < env.orders.get(r["order_id"]).seconds_left() <= 30 * 60


def test_create_order_insufficient_stock_gives_the_number_and_creates_nothing(env):
    pid = env.products.add("گوشی", 1000, 3)
    env.orders.create("bale", "9", [(pid, 2)])  # مشتری دیگه
    r = call(env.box(), "create_order", items=[{"product_id": pid, "quantity": 2}])
    assert r["ok"] is False and "فقط 1 عدد" in r["error"]
    assert len(env.orders.list()) == 1


def test_two_customers_cannot_both_get_the_last_item(env):
    pid = env.products.add("آخرین قطعه", 1000, 1)
    first = call(env.box("telegram", "1"), "create_order", items=[{"product_id": pid, "quantity": 1}])
    second = call(env.box("bale", "2"), "create_order", items=[{"product_id": pid, "quantity": 1}])
    assert first["ok"] and second["ok"] is False and "رزرو" in second["error"]


def test_second_unpaid_order_is_refused_with_the_existing_one_shown(env):
    pid = env.products.add("گوشی", 1000, 5)
    box = env.box()
    first = call(box, "create_order", items=[{"product_id": pid, "quantity": 1}])
    again = call(box, "create_order", items=[{"product_id": pid, "quantity": 1}])
    assert again["ok"] is False and again["existing_order"]["order_id"] == first["order_id"] and "update_order" in again["hint"]


def test_other_customer_can_order_while_first_has_pending(env):
    pid = env.products.add("گوشی", 1000, 5)
    assert call(env.box("telegram", "1"), "create_order", items=[{"product_id": pid, "quantity": 1}])["ok"]
    assert call(env.box("telegram", "2"), "create_order", items=[{"product_id": pid, "quantity": 1}])["ok"]


@pytest.mark.parametrize(
    "items",
    [None, [], "x", [{"product_id": 1}], [{"product_id": "a", "quantity": 1}], [{"product_id": 1, "quantity": 0}],
     [{"product_id": 1, "quantity": 1000}], [{"product_id": 1, "quantity": 1}] * 21],
)
def test_create_order_rejects_malformed_items_without_raising(env, items):
    env.products.add("گوشی", 1000, 5)
    r = call(env.box(), "create_order", items=items)
    assert r["ok"] is False and r["error"]


def test_create_order_unknown_product(env):
    r = call(env.box(), "create_order", items=[{"product_id": 999, "quantity": 1}])
    assert r["ok"] is False and "وجود نداره" in r["error"]


def test_required_phone_and_address_are_enforced(env):
    env.settings.require_customer_phone = True
    env.settings.require_customer_address = True
    pid = env.products.add("گوشی", 1000, 5)
    box = env.box()
    item = [{"product_id": pid, "quantity": 1}]
    r = call(box, "create_order", items=item)
    assert r["error"] == "missing_info" and r["missing"] == ["phone", "address"]
    r = call(box, "create_order", items=item, customer_phone="۰۹۱۲ ۰۰۰-۰۰۰۰", customer_address="تهران")
    assert r["ok"] and env.orders.get(r["order_id"]).customer_phone == "09120000000", "رقم فارسی نرمال می‌شه"


def test_invalid_phone_is_rejected(env):
    pid = env.products.add("گوشی", 1000, 5)
    r = call(env.box(), "create_order", items=[{"product_id": pid, "quantity": 1}], customer_phone="abc")
    assert r["ok"] is False and "شماره تماس" in r["error"]


# ----------------------------------------------------------------- update/cancel/list


def test_update_order_changes_items_and_warns_payment_info_is_void(env):
    a, b = env.products.add("الف", 1000, 5), env.products.add("ب", 500, 5)
    box = env.box()
    oid = call(box, "create_order", items=[{"product_id": a, "quantity": 1}])["order_id"]
    r = call(box, "update_order", order_id=oid, items=[{"product_id": a, "quantity": 2}, {"product_id": b, "quantity": 1}])
    assert r["ok"] and r["total_irr"] == 2500 and "start_payment" in r["note"]


def test_update_and_cancel_only_work_on_own_orders(env):
    pid = env.products.add("گوشی", 1000, 5)
    oid = call(env.box("telegram", "1"), "create_order", items=[{"product_id": pid, "quantity": 1}])["order_id"]
    stranger = env.box("telegram", "2")
    for name, args in [("update_order", dict(order_id=oid, items=[{"product_id": pid, "quantity": 3}])),
                       ("cancel_order", dict(order_id=oid)), ("start_payment", dict(order_id=oid, method="card_to_card")),
                       ("report_card_payment", dict(order_id=oid))]:
        r = call(stranger, name, **args)
        assert r["ok"] is False and "پیدا نشد" in r["error"], name
    assert env.orders.get(oid).total_irr == 1000 and env.orders.get(oid).status == "pending_payment"


def test_get_my_orders_lists_only_own_orders(env):
    pid = env.products.add("گوشی", 1000, 9)
    call(env.box("telegram", "1"), "create_order", items=[{"product_id": pid, "quantity": 1}])
    call(env.box("telegram", "2"), "create_order", items=[{"product_id": pid, "quantity": 4}])
    mine = call(env.box("telegram", "1"), "get_my_orders")["orders"]
    assert len(mine) == 1 and mine[0]["total_irr"] == 1000 and mine[0]["minutes_left"] == 15


def test_cancel_releases_stock_and_paid_orders_cannot_be_cancelled(env):
    pid = env.products.add("گوشی", 1000, 1)
    box = env.box()
    oid = call(box, "create_order", items=[{"product_id": pid, "quantity": 1}])["order_id"]
    assert call(box, "cancel_order", order_id=oid)["ok"]
    assert env.orders.available_quantity(pid) == 1 and env.orders.get(oid).status == STATUS_CANCELLED
    oid2 = call(box, "create_order", items=[{"product_id": pid, "quantity": 1}])["order_id"]
    env.orders.mark_paid(oid2, METHOD_CARD_TO_CARD)
    r = call(box, "cancel_order", order_id=oid2)
    assert r["ok"] is False and "فروشنده" in r["error"]


# ----------------------------------------------------------------- start_payment


def new_order(env, box=None, qty=1, price=1_000_000, stock=5):
    pid = env.products.add("گوشی", price, stock)
    box = box or env.box()
    return box, call(box, "create_order", items=[{"product_id": pid, "quantity": qty}])["order_id"], pid


def test_card_payment_message_is_exact_and_verbatim(env):
    box, oid, _ = new_order(env, qty=2)
    r = call(box, "start_payment", order_id=oid, method="card_to_card")
    assert r["ok"] and r["method"] == METHOD_CARD_TO_CARD
    [msg] = box.outbox
    assert "6219-8610-1234-5678" in msg.text and "علی رضایی" in msg.text and "2,000,000 ریال" in msg.text
    assert f"#{oid}" in msg.text and "دقیقه" in msg.text and msg.buttons == []
    assert env.orders.get(oid).payment_method == METHOD_CARD_TO_CARD


def test_inactive_method_is_refused_and_alternatives_listed(env):
    box, oid, _ = new_order(env)
    r = call(box, "start_payment", order_id=oid, method="zarinpal")
    assert r["ok"] is False and [m["id"] for m in r["available_methods"]] == [METHOD_CARD_TO_CARD]
    assert box.outbox == []


def test_bale_pay_message_for_telegram_customer_is_a_deep_link_with_button(env):
    env.enable_bale_pay()
    box, oid, _ = new_order(env, env.box("telegram", "1"))
    r = call(box, "start_payment", order_id=oid, method="bale_pay")
    assert r["ok"]
    [msg] = box.outbox
    code = env.orders.get(oid).gateway_ref
    link = f"https://ble.ir/bale_shop_bot?start=pay_{oid}_{code}"
    assert link in msg.text and f"/pay {oid} {code}" in msg.text and "[" not in msg.text, "تلگرام متن ساده نشون می‌ده"
    assert msg.buttons == [("💳 پرداخت با بله‌پی", link)]
    assert env.orders.get(oid).payment_url == link
    assert env.bale.invoices == [], "فاکتور فقط بعد از «شروع» توی بله فرستاده می‌شه"


def test_bale_pay_for_bale_customer_sends_the_native_invoice_in_chat(env):
    env.enable_bale_pay()
    box, oid, _ = new_order(env, env.box("bale", "7"), qty=2)
    r = call(box, "start_payment", order_id=oid, method="bale_pay")
    assert r["ok"] is True
    assert env.bale.invoices[0]["chat_id"] == "7" and env.bale.invoices[0]["payload"] == f"order:{oid}"
    assert env.bale.invoices[0]["prices"] == [("گوشی", 2_000_000)] and env.bale.invoices[0]["token"] == "WALLET-TEST-1"
    [msg] = box.outbox
    assert "فاکتور بله‌پی" in msg.text and msg.buttons == [] and "[" not in msg.text


def test_bale_pay_not_offered_when_bale_bot_is_not_running(env):
    env.enable_bale_pay()
    box = env.box(hooks=env.no_bale_hooks)
    assert box.methods() == [METHOD_CARD_TO_CARD]


def test_bale_invoice_failure_for_bale_customer_is_reported_to_the_model(env):
    env.enable_bale_pay()
    env.bale.fail_invoice = "invalid provider_token"
    box, oid, _ = new_order(env, env.box("bale", "7"), qty=2)
    r = call(box, "start_payment", order_id=oid, method="bale_pay")
    assert r["ok"] is False and "ممکن نشد" in r["error"] and box.outbox == []
    assert "invalid provider_token" in env.payments.last_errors[METHOD_BALE_PAY]
    assert [m["id"] for m in r["available_methods"]] == [METHOD_CARD_TO_CARD]


def test_bale_pay_for_telegram_customer_without_bale_username_is_a_clean_error(env):
    from app.core.payments import PaymentHooks

    env.enable_bale_pay()
    hooks = PaymentHooks(bale_client=lambda: env.bale, bot_username=lambda platform: None)
    box, oid, _ = new_order(env, env.box("telegram", "1", hooks=hooks))
    r = call(box, "start_payment", order_id=oid, method="bale_pay")
    assert r["ok"] is False and "مشخص نیست" in r["error"] and box.outbox == []
    assert env.bale.invoices == []


def test_zarinpal_link_message_and_bookkeeping(env):
    env.enable_zarinpal()
    box, oid, _ = new_order(env, env.box("telegram", "1"), qty=3)
    r = call(box, "start_payment", order_id=oid, method="zarinpal")
    assert r["ok"]
    req = env.zarinpal.requests[0]
    assert req["amount"] == 3_000_000 and req["merchant_id"] == MERCHANT
    assert req["callback_url"] == "https://t.me/telegram_shop_bot", "بعد از پرداخت مشتری به چتِ ربات برمی‌گرده"
    [msg] = box.outbox
    order = env.orders.get(oid)
    assert order.payment_method == METHOD_ZARINPAL and order.gateway_ref == env.zarinpal.last_authority
    assert order.payment_url in msg.text and msg.buttons == [("💳 پرداخت با زرین‌پال", order.payment_url)]


def test_zarinpal_callback_url_for_bale_and_custom_override(env):
    env.enable_zarinpal()
    box, oid, _ = new_order(env, env.box("bale", "7"))
    call(box, "start_payment", order_id=oid, method="zarinpal")
    assert env.zarinpal.requests[-1]["callback_url"] == "https://ble.ir/bale_shop_bot"
    env.settings.zarinpal_callback_url = "https://myshop.ir/thanks"
    oid2 = call(env.box("bale", "8"), "create_order", items=[{"product_id": 1, "quantity": 1}])["order_id"]
    call(env.box("bale", "8"), "start_payment", order_id=oid2, method="zarinpal")
    assert env.zarinpal.requests[-1]["callback_url"] == "https://myshop.ir/thanks"


def test_zarinpal_error_is_reported_with_the_reason(env):
    env.enable_zarinpal()
    env.zarinpal.fail_request_with = {"code": -11, "message": "inactive"}
    box, oid, _ = new_order(env)
    r = call(box, "start_payment", order_id=oid, method="zarinpal")
    assert r["ok"] is False and "فعال نیست" in r["error"] and box.outbox == []
    assert METHOD_ZARINPAL in env.payments.last_errors


def test_invalid_merchant_id_means_zarinpal_is_not_offered(env):
    env.settings.set_zarinpal_merchant_id("not-a-uuid")
    env.settings.zarinpal_enabled = True
    assert env.box().methods() == [METHOD_CARD_TO_CARD]


def test_changing_payment_method_replaces_the_previous_choice(env):
    env.enable_zarinpal()
    box, oid, _ = new_order(env)
    call(box, "start_payment", order_id=oid, method="zarinpal")
    call(box, "start_payment", order_id=oid, method="card_to_card")
    o = env.orders.get(oid)
    assert o.payment_method == METHOD_CARD_TO_CARD and len(box.outbox) == 2


def test_start_payment_refused_for_expired_or_paid_orders(env):
    box, oid, _ = new_order(env)
    env.orders.expire_stale(now=env.orders.get(oid).expires_ts + 5)
    assert env.orders.get(oid).status == STATUS_EXPIRED
    r = call(box, "start_payment", order_id=oid, method="card_to_card")
    assert r["ok"] is False and "ثبت بشه" in r["error"]


def test_start_payment_refused_when_deadline_passed_even_before_sweeper_runs(env):
    box, oid, _ = new_order(env)
    env.orders._connection().execute("UPDATE orders SET expires_ts=1 WHERE id=?", (oid,))  # noqa: SLF001
    env.orders._connection().commit()  # noqa: SLF001
    assert call(box, "start_payment", order_id=oid, method="card_to_card")["ok"] is False


# ----------------------------------------------------------------- report_card_payment


def test_report_card_payment_requires_card_method_first(env):
    box, oid, _ = new_order(env)
    r = call(box, "report_card_payment", order_id=oid)
    assert r["ok"] is False and "start_payment" in r["error"]
    assert env.orders.get(oid).status == "pending_payment"


def test_report_card_payment_marks_paid_and_never_confirms(env):
    box, oid, pid = new_order(env, qty=2)
    call(box, "start_payment", order_id=oid, method="card_to_card")
    r = call(box, "report_card_payment", order_id=oid, reference="4321")
    assert r["ok"] and r["status"] == "paid_waiting_owner_confirmation"
    o = env.orders.get(oid)
    assert o.status == STATUS_PAID and o.payment_reference == "4321"
    assert env.products.get(pid).stock_quantity == 5, "فقط تاییدِ صاحب فروشگاه موجودی رو کم می‌کنه"


def test_report_card_payment_after_expiry_is_recorded_as_late(env):
    box, oid, _ = new_order(env)
    call(box, "start_payment", order_id=oid, method="card_to_card")
    env.orders.expire_stale(now=env.orders.get(oid).expires_ts + 5)
    r = call(box, "report_card_payment", order_id=oid)
    assert r["ok"] and "بررسی" in r["note"] and env.orders.get(oid).paid_late is True


def test_report_card_payment_on_cancelled_order_is_refused(env):
    box, oid, _ = new_order(env)
    call(box, "start_payment", order_id=oid, method="card_to_card")
    call(box, "cancel_order", order_id=oid)
    assert call(box, "report_card_payment", order_id=oid)["ok"] is False


# ----------------------------------------------------------------- مقاومت


def test_unknown_tool_and_bad_arguments_never_raise(env):
    box = env.box()
    assert call(box, "drop_all_tables")["ok"] is False
    assert call(box, "_tool_search_products")["ok"] is False
    assert run(box.execute("create_order", "not a dict"))["ok"] is False
    assert call(box, "cancel_order", order_id="abc")["ok"] is False
    assert call(box, "cancel_order", order_id=None)["ok"] is False


def test_tool_internal_error_is_contained(env, monkeypatch):
    box = env.box()
    monkeypatch.setattr(env.products, "list", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    r = call(box, "search_products", query="x")
    assert r["ok"] is False and "خطای داخلی" in r["error"]


# ----------------------------------------------------------------- پرامپت


def test_prompt_contains_rules_catalog_methods_and_active_orders(env):
    env.enable_zarinpal()
    env.settings.reservation_minutes = 20
    pid = env.products.add("گوشی سامسونگ", 12_000_000, 3)
    env.products.add("ناموجود", 1000, 0)
    box = env.box()
    call(box, "create_order", items=[{"product_id": pid, "quantity": 1}])
    prompt = build_agent_prompt("من فروشگاه موبایلم", env.settings, box, env.products, env.orders, "مریم")
    assert prompt.startswith("من فروشگاه موبایلم")
    assert "20 دقیقه" in prompt and "زرین‌پال (`zarinpal`)" in prompt and "کارت‌به‌کارت (`card_to_card`)" in prompt
    assert f"#{pid} | گوشی سامسونگ | 12,000,000 ریال | موجود: 2" in prompt
    assert "| ناموجود" in prompt and "مریم" in prompt
    assert "سفارش #1: در انتظار پرداخت" in prompt and "غیرقابل‌اعتماده" in prompt


def test_prompt_lists_required_info_and_no_methods_warning(env):
    env.settings.card_to_card_number = ""
    env.settings.require_customer_phone = True
    prompt = build_agent_prompt("x", env.settings, env.box(), env.products, env.orders, "")
    assert "شماره تماس" in prompt and "هیچ روشی فعال نیست" in prompt and "فروشگاه هنوز محصولی ندارد" in prompt


def test_prompt_truncates_big_catalogs(env):
    for i in range(35):
        env.products.add(f"کالا {i:02d}", 1000, 1)
    prompt = build_agent_prompt("x", env.settings, env.box(), env.products, env.orders, "")
    assert "+5 محصول دیگه" in prompt


def test_tool_specs_hide_nothing_and_enum_reflects_active_methods(env):
    env.enable_zarinpal()
    specs = {s.name: s for s in env.box().specs()}
    assert set(specs) == {"search_products", "create_order", "update_order", "get_my_orders", "cancel_order", "start_payment", "report_card_payment", "escalate_to_owner"}
    assert specs["start_payment"].parameters["properties"]["method"]["enum"] == [METHOD_CARD_TO_CARD, METHOD_ZARINPAL]


# ----------------------------------------------------------------- حلقه‌ی ایجنت


def make_agent(env):
    return StoreAgent(env.products, env.orders, env.payments, env.hooks)


def respond(env, engine, message, platform="telegram", chat_id="1", history=None):
    async def call_engine(system_prompt, hist, user_message, specs, tool_messages):
        return engine.chat_tools(system_prompt, hist, user_message, specs, tool_messages)

    return run(
        make_agent(env).respond(call_engine, env.settings, platform, chat_id, "مشتری", "پرامپت فروشگاه", history or [], message)
    )


def test_agent_runs_tool_then_answers(env):
    env.products.add("گوشی", 1000, 4)
    engine = ScriptedToolEngine({"گوشی دارید؟": [tool("search_products", query="گوشی"), lambda res: say(f"بله، {res[0]['products'][0]['available']} عدد داریم")]})
    reply = respond(env, engine, "گوشی دارید؟")
    assert reply.text == "بله، 4 عدد داریم" and reply.outbox == []
    second = engine.calls[1]["tool_messages"]
    assert second[0]["role"] == "assistant" and second[1]["role"] == "tool"
    assert json.loads(second[1]["content"])["ok"] is True


def test_agent_chains_create_order_and_payment_and_collects_outbox(env):
    pid = env.products.add("گوشی", 1_000_000, 4)
    engine = ScriptedToolEngine(
        {
            "یکی می‌خوام و کارت‌به‌کارت": [
                tool("create_order", items=[{"product_id": pid, "quantity": 1}]),
                lambda res: tool("start_payment", order_id=res[0]["order_id"], method="card_to_card"),
                say("ثبت شد؛ پیام پرداخت رو ببین."),
            ]
        }
    )
    reply = respond(env, engine, "یکی می‌خوام و کارت‌به‌کارت")
    assert reply.text == "ثبت شد؛ پیام پرداخت رو ببین." and len(reply.outbox) == 1
    assert "6219-8610-1234-5678" in reply.outbox[0].text


def test_agent_falls_back_when_model_returns_nothing(env):
    reply = respond(env, ScriptedToolEngine({"سلام": [say("")]}), "سلام")
    assert reply.text == FALLBACK_REPLY


def test_agent_stops_runaway_tool_loops(env):
    env.products.add("گوشی", 1000, 4)
    endless = ScriptedToolEngine({}, default=tool("search_products", query="گوشی"))
    reply = respond(env, endless, "سلام")
    assert reply.text == FALLBACK_REPLY and len(endless.calls) == 7


def test_agent_survives_model_error_after_payment_message_was_queued(env):
    pid = env.products.add("گوشی", 1000, 4)

    def boom(results):
        raise ai_engine.AiEngineError("API down")

    engine = ScriptedToolEngine(
        {"بخرم": [tool("create_order", items=[{"product_id": pid, "quantity": 1}]),
                  lambda res: tool("start_payment", order_id=res[0]["order_id"], method="card_to_card"), boom]}
    )
    reply = respond(env, engine, "بخرم")
    assert reply.text == "" and len(reply.outbox) == 1, "پیامِ پرداخت نباید با خطای مدل گم بشه"


def test_agent_reraises_model_error_when_nothing_was_done(env):
    def boom(results):
        raise ai_engine.AiEngineError("API down")

    with pytest.raises(ai_engine.AiEngineError):
        respond(env, ScriptedToolEngine({"سلام": [boom]}), "سلام")


def test_agent_executes_at_most_four_calls_per_turn(env):
    env.products.add("گوشی", 1000, 4)
    from app.core.tool_protocol import ToolCall, ToolTurn

    many = ToolTurn("", [ToolCall(f"c{i}", "get_my_orders", {}) for i in range(6)])
    # ScriptedToolEngine قدم رو با «تعداد نتایج ابزار» پیدا می‌کنه: بعد از ۴ نتیجه، قدمِ ۴ (indexِ ۴) اجرا می‌شه
    engine = ScriptedToolEngine({"x": [many, None, None, None, say("ok")]})
    respond(env, engine, "x")
    tool_msgs = engine.calls[1]["tool_messages"]
    assert sum(1 for m in tool_msgs if m["role"] == "tool") == 4
