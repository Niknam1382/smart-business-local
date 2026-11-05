"""تستِ سطح-سرویسِ PaymentService (بدونِ شبکه): ساختِ دستورِ پرداخت، نگهبانی‌هایِ بله‌پی،
استعلامِ تراکنش، فرمانِ /pay و تشخیصِ UI.

مسیرهایِ واقعیِ شبکه (createInvoiceLink و …) با سرورِ جعلی در ``tests/test_bale_pay.py`` و
سرتاسری در ``tests/test_commerce_e2e.py`` تست می‌شوند؛ این‌جا فقط منطقِ پول بررسی می‌شود —
پس کلاینتِ جعلی صرفاً «ضبطِ فراخوانی‌ها» است.

قاعده‌هایِ مهمی که این فایل میخکوب می‌کند:
* پول همیشه ``int`` ریال است و مبلغِ فاکتور از **دیتابیس** گرفته می‌شود، نه از مشتری.
* هیچ رویدادِ پرداختِ بله بدونِ payload درست، ارز درست و استعلامِ موفق تأییدِ خودکار نمی‌شود.
* تأییدِ کارت‌به‌کارت هرگز خودکار نیست (آن بخش در ``tests/test_receipts.py``).
"""

import asyncio

import pytest
from app.core.bale_pay import (
    TEST_PROVIDER_TOKEN,
    BaleApiError,
    BalePayCommand,
    BalePreCheckoutQuery,
    BaleSuccessfulPayment,
    parse_pay_command,
)
from app.core.orders import METHOD_BALE_PAY, METHOD_CARD_TO_CARD, OrderStore, STATUS_CONFIRMED, STATUS_PAID, STATUS_PENDING_PAYMENT
from app.core.payments import PaymentError, PaymentHooks, PaymentService, describe_provider_token, invoice_prices, make_pay_code, normalize_provider_token, order_payload, parse_payload
from app.core.products import ProductStore
from app.core.settings import AppSettings


def run(coro):
    return asyncio.run(coro)


class FakeBaleClient:
    """جای BalePayClient: فراخوانی‌ها را ضبط می‌کند و پاسخ‌های دلخواه را برمی‌گرداند."""

    def __init__(self, transaction_status="Successful", fail_inquire=False, link="https://bale.ai/pay/test", link_error=None):
        self.answers = []  # [(query_id, ok, error_message)]
        self.transaction_status = transaction_status
        self.fail_inquire = fail_inquire
        self.inquired = []
        self.invoice_calls = []
        self.link_calls = []
        self.link = link
        self.link_error = link_error  # اگر بدهیم، createInvoiceLink این خطا را می‌دهد
        self.fail_invoice = None
        self.bot_username = "bale_pay_bot"

    async def answer_pre_checkout_query(self, query_id, ok, error_message=""):
        self.answers.append((query_id, ok, error_message))

    async def inquire_transaction(self, transaction_id):
        self.inquired.append(transaction_id)
        if self.fail_inquire:
            raise BaleApiError("شبکه قطع شد")
        return {"status": self.transaction_status, "transaction_id": transaction_id}

    async def create_invoice_link(self, title, description, payload, provider_token, prices, **kw):
        self.link_calls.append(
            dict(title=title, description=description, payload=payload, token=provider_token, prices=prices, **kw)
        )
        if self.link_error:
            raise BaleApiError(self.link_error)
        return self.link

    async def send_invoice(self, chat_id, title, description, payload, provider_token, prices):
        self.invoice_calls.append(
            dict(chat_id=chat_id, title=title, description=description, payload=payload, token=provider_token, prices=prices)
        )
        if self.fail_invoice:
            raise BaleApiError(self.fail_invoice)


def make_service(tmp_path):
    products = ProductStore(db_path=tmp_path / "p.db")
    orders = OrderStore(db_path=tmp_path / "o.db", product_store=products)
    return products, orders, PaymentService(orders, products)


def bale_service(tmp_path, platform="telegram", chat_id="1", price=500_000, quantity=2, **client_kw):
    products = ProductStore(db_path=tmp_path / "p.db")
    orders = OrderStore(db_path=tmp_path / "o.db", product_store=products)
    settings = AppSettings(business_mode="store")
    settings.set_bale_pay_bot_token("987654321:BALEpayBALEpayBALEpayBALEpay12345")
    settings.set_bale_pay_provider_token(TEST_PROVIDER_TOKEN)
    settings.bale_pay_enabled = True
    service = PaymentService(orders, products, settings)
    client = FakeBaleClient(**client_kw)
    claims = []
    hooks = PaymentHooks(bale_client=lambda: client, payment_claim=lambda order, receipt: claims.append(receipt))
    pid = products.add("هدفون", price, 10)
    oid = orders.create(platform, chat_id, [(pid, quantity)])
    return service, orders, client, hooks, oid, claims


def query(oid, amount, payload=None, currency="IRR", query_id="q1", user="1"):
    return BalePreCheckoutQuery(
        update_id=1, query_id=query_id, from_user_id=user,
        invoice_payload=order_payload(oid) if payload is None else payload,
        total_amount=amount, currency=currency,
    )


def payment(oid, amount, payload=None, provider="prov1", currency="IRR", tg_charge="tg1", chat="99"):
    return BaleSuccessfulPayment(
        update_id=1, chat_id=chat, from_user_id="99",
        invoice_payload=order_payload(oid) if payload is None else payload,
        total_amount=amount, currency=currency,
        telegram_payment_charge_id=tg_charge, provider_payment_charge_id=provider,
    )


# ================================================== pre_checkout: نگهبانی‌هایِ سریع


def test_pre_checkout_accepts_valid_order_with_stock(tmp_path):
    products, orders, service = make_service(tmp_path)
    pid = products.add("گوشی", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 2)])
    client = FakeBaleClient()
    run(service.handle_pre_checkout(query(oid, 2000), client))
    assert client.answers == [("q1", True, "")]


def test_pre_checkout_rejects_unknown_payload(tmp_path):
    _, _, service = make_service(tmp_path)
    client = FakeBaleClient()
    run(service.handle_pre_checkout(query(None, 1000, payload="garbage"), client))
    assert client.answers[0][0] == "q1" and client.answers[0][1] is False


def test_pre_checkout_rejects_order_not_pending(tmp_path):
    products, orders, service = make_service(tmp_path)
    pid = products.add("گوشی", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)])
    orders.mark_paid(oid, METHOD_BALE_PAY)  # دیگه pending_payment نیست
    client = FakeBaleClient()
    run(service.handle_pre_checkout(query(oid, 1000), client))
    assert client.answers[0][1] is False


def test_pre_checkout_rejects_insufficient_stock_with_item_name(tmp_path):
    products, orders, service = make_service(tmp_path)
    pid = products.add("گوشی کمیاب", 1000, 1)
    oid = orders.create("telegram", "1", [(pid, 1)])
    products.adjust_stock(pid, -1)  # یکی دیگه زودتر خرید؛ الان موجودی صفره
    client = FakeBaleClient()
    run(service.handle_pre_checkout(query(oid, 1000), client))
    _, ok, msg = client.answers[0]
    assert ok is False and "گوشی کمیاب" in msg


def test_pre_checkout_rejects_wrong_currency_and_amount(tmp_path):
    """ارز/مبلغِ نخوان = ردِ پرداخت، نه پذیرفتنِ ریسک (ریالِ صحیح، دقیقاً مبلغِ سفارش)."""
    products, orders, service = make_service(tmp_path)
    pid = products.add("گوشی", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 2)])
    client = FakeBaleClient()
    run(service.handle_pre_checkout(query(oid, 2000, currency="IRT"), client), )
    run(service.handle_pre_checkout(query(oid, 1999, query_id="q2"), client))
    run(service.handle_pre_checkout(query(oid, 0, query_id="q3"), client))
    by_id = {q: ok for q, ok, _msg in client.answers}
    assert by_id == {"q1": False, "q2": False, "q3": False}
    assert any("ریال" in msg for _q, _ok, msg in client.answers)


def test_pre_checkout_rejects_payload_code_mismatch(tmp_path):
    """دیپ‌لینکِ قدیمیِ همان سفارش با کدِ دیگری رد می‌شود (کدِ هر-سفارش)."""
    products, orders, service = make_service(tmp_path)
    pid = products.add("گوشی", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)])
    orders.set_payment_info(oid, METHOD_BALE_PAY, gateway_ref="aaaa1111bbbb")
    client = FakeBaleClient()
    run(service.handle_pre_checkout(query(oid, 1000, payload=order_payload(oid, "deadbeef")), client))
    assert client.answers[0][1] is False


# ================================================== successful_payment → تأیید


def test_successful_payment_marks_paid_and_confirms(tmp_path):
    """با auto_confirm روشن و استعلامِ موفق، سفارش «تاییدشده» می‌شود."""
    products, orders, service = make_service(tmp_path)
    settings = AppSettings(business_mode="store")
    settings.set_bale_pay_provider_token(TEST_PROVIDER_TOKEN)
    settings.bale_pay_enabled = True
    service.set_settings(settings)
    pid = products.add("گوشی", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 2)])
    client = FakeBaleClient()
    order = run(service.handle_successful_payment(payment(oid, 2000), client))
    assert orders.get(oid).status == STATUS_CONFIRMED
    assert orders.get(oid).payment_reference == "prov1"
    assert client.inquired == ["prov1"]
    assert order.id == oid


def test_successful_payment_without_settings_stays_paid(tmp_path):
    """بدونِ تنظیمات (یا با auto_confirm خاموش) فقط «پرداخت‌شده» می‌شود؛ تصمیم با مالک است."""
    products, orders, service = make_service(tmp_path)
    pid = products.add("گوشی", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 2)])
    client = FakeBaleClient()
    run(service.handle_successful_payment(payment(oid, 2000), client))
    assert orders.get(oid).status == STATUS_PAID


def test_successful_payment_blocked_by_explicit_failed_transaction_status(tmp_path):
    products, orders, service = make_service(tmp_path)
    settings = AppSettings(business_mode="store")
    settings.bale_pay_enabled = True
    service.set_settings(settings)
    pid = products.add("گوشی", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)])
    client = FakeBaleClient(transaction_status="Failed")
    result = run(service.handle_successful_payment(payment(oid, 1000), client))
    assert result is None
    assert orders.get(oid).status == STATUS_PENDING_PAYMENT, "نباید paid بشه وقتی استعلام صراحتاً ناموفق می‌گه"


def test_successful_payment_pending_status_is_queued_for_reverification(tmp_path):
    """استعلامِ «در انتظار»: پرداخت ثبت می‌شود و در صفِ استعلامِ دوباره می‌ماند."""
    products, orders, service = make_service(tmp_path)
    settings = AppSettings(business_mode="store")
    settings.bale_pay_enabled = True
    service.set_settings(settings)
    pid = products.add("گوشی", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)])
    client = FakeBaleClient(transaction_status="Pending")
    assert run(service.handle_successful_payment(payment(oid, 1000), client)) is not None
    assert service.has_pending_verifications()

    client.transaction_status = "Successful"
    run(service.retry_pending_verifications(client))
    assert not service.has_pending_verifications()


@pytest.mark.parametrize("mode", ["pending", "network-error"])
def test_uncertain_inquiry_never_auto_confirms(tmp_path, mode):
    """پولِ مشتری ثبت می‌شود، ولی تا استعلام تأیید نشود سفارش «پرداخت‌شده» می‌ماند."""
    products, orders, service = make_service(tmp_path)
    settings = AppSettings(business_mode="store")
    settings.bale_pay_enabled = True
    service.set_settings(settings)
    pid = products.add("گوشی", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)])
    client = FakeBaleClient(transaction_status="Pending") if mode == "pending" else FakeBaleClient(fail_inquire=True)
    assert run(service.handle_successful_payment(payment(oid, 1000), client)) is not None
    assert orders.get(oid).status == STATUS_PAID, "بدونِ استعلامِ موفق، تأییدِ خودکار نباید انجام شود"
    assert not got_confirmed(orders, oid)


def got_confirmed(orders, oid) -> bool:
    return orders.get(oid).status == STATUS_CONFIRMED


def test_successful_payment_unknown_payload_does_nothing(tmp_path):
    _, orders, service = make_service(tmp_path)
    client = FakeBaleClient()
    result = run(service.handle_successful_payment(payment(None, 1000, payload="garbage"), client))
    assert result is None
    assert client.inquired == []


def test_successful_payment_rejects_wrong_currency(tmp_path):
    products, orders, service = make_service(tmp_path)
    pid = products.add("گوشی", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)])
    client = FakeBaleClient()
    assert run(service.handle_successful_payment(payment(oid, 1000, currency="USD"), client)) is None
    assert orders.get(oid).status == STATUS_PENDING_PAYMENT


def test_duplicate_charge_id_is_never_applied_twice(tmp_path):
    """یک شناسهٔ تراکنش = یک سفارش؛ تکرارِ رویداد هیچ چیزی را عوض نمی‌کند."""
    products, orders, service = make_service(tmp_path)
    settings = AppSettings(business_mode="store")
    settings.bale_pay_enabled = True
    service.set_settings(settings)
    pid = products.add("گوشی", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)])
    client = FakeBaleClient()
    assert run(service.handle_successful_payment(payment(oid, 1000, provider="dup"), client)) is not None
    other_pid = products.add("گوشی دوم", 1000, 5)
    other = orders.create("telegram", "2", [(other_pid, 1)])
    assert run(service.handle_successful_payment(payment(other, 1000, provider="dup"), client)) is None
    assert orders.get(other).status == STATUS_PENDING_PAYMENT, "یک رسید برای دو سفارش مصرف نمی‌شه"


def test_charge_id_reused_for_the_same_order_is_ignored(tmp_path):
    products, orders, service = make_service(tmp_path)
    pid = products.add("گوشی", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)])
    client = FakeBaleClient()
    assert run(service.handle_successful_payment(payment(oid, 1000, provider="same"), client)) is not None
    assert run(service.handle_successful_payment(payment(oid, 1000, provider="same"), client)) is None
    assert client.inquired == ["same"], "رویدادِ تکراری حتی استعلام هم نمی‌شود"


def test_missing_reference_is_not_recorded(tmp_path):
    products, orders, service = make_service(tmp_path)
    pid = products.add("گوشی", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)])
    client = FakeBaleClient()
    p = payment(oid, 1000, provider="", tg_charge="")
    assert run(service.handle_successful_payment(p, client)) is None
    assert orders.get(oid).status == STATUS_PENDING_PAYMENT


def test_find_paid_by_reference_blocks_one_receipt_two_orders(tmp_path):
    """یک تراکنش فقط به نامِ یک سفارش «ادعا» می‌شود — در سطحِ دیتابیس، نه حافظه‌ی یک پردازش."""
    products, orders, service = make_service(tmp_path)
    settings = AppSettings(business_mode="store")
    settings.bale_pay_enabled = True
    service.set_settings(settings)
    pid = products.add("گوشی", 1000, 5)
    first = orders.create("telegram", "1", [(pid, 1)])
    assert service.finalize_online_payment(first, METHOD_BALE_PAY, "ref-1") is not None
    assert orders.find_paid_by_reference("ref-1") == first
    assert orders.charge_owner("ref-1") == first
    assert orders.find_paid_by_reference("nope") is None
    assert orders.find_paid_by_reference("") is None and orders.claim_payment_charge("", 9) is False

    other_pid = products.add("گوشی دوم", 1000, 5)
    other = orders.create("telegram", "2", [(other_pid, 1)])
    assert service.finalize_online_payment(other, METHOD_BALE_PAY, "ref-1") is None
    assert orders.get(other).status == STATUS_PENDING_PAYMENT, "یک رسید برای دو سفارش مصرف نمی‌شه"

    # سرویسِ تازه (انگار برنامه ری‌استارت شده) هم همان شناسه را قبول نمی‌کند
    fresh = PaymentService(orders, products, settings)
    third_pid = products.add("گوشی سوم", 1000, 5)
    third = orders.create("telegram", "3", [(third_pid, 1)])
    assert fresh.finalize_online_payment(third, METHOD_BALE_PAY, "ref-1") is None
    assert orders.get(third).status == STATUS_PENDING_PAYMENT


# ================================================== دستورِ پرداخت (Instruction)


def test_bale_pay_uses_the_direct_invoice_link_first(tmp_path):
    service, orders, client, hooks, oid, _claims = bale_service(tmp_path)
    instruction = run(service.build_instruction(orders.get(oid), METHOD_BALE_PAY, hooks))
    [call] = client.link_calls
    assert call["payload"] == order_payload(oid, orders.get(oid).gateway_ref)
    assert call["token"] == TEST_PROVIDER_TOKEN
    assert call["prices"] == [("هدفون", 1_000_000)], "مبلغ از سفارشِ دیتابیس (۲×۵۰۰٬۰۰۰)"
    assert all(isinstance(amount, int) for _label, amount in call["prices"]), "ریالِ صحیح (int)"
    assert instruction.url == "https://bale.ai/pay/test"
    assert instruction.buttons and instruction.buttons[0][1] == instruction.url
    assert "بله‌پی" in instruction.text and "500٬000" not in instruction.text  # فقط با جداکننده‌ی هزارگان نمایش داده می‌شه
    assert orders.get(oid).payment_url == instruction.url
    assert client.invoice_calls == [], "مسیرِ اصلی لینک است؛ فاکتورِ بومی فقط پشتیبان است"


def test_invoice_link_failure_falls_back_to_the_deep_link(tmp_path):
    service, orders, client, hooks, oid, _claims = bale_service(tmp_path, link_error="invalid provider_token")
    instruction = run(service.build_instruction(orders.get(oid), METHOD_BALE_PAY, hooks))
    code = orders.get(oid).gateway_ref
    link = f"https://ble.ir/bale_pay_bot?start=pay_{oid}_{code}"
    assert instruction.url == link and instruction.buttons == [(instruction.buttons[0][0], link)]
    assert f"/pay {oid} {code}" in instruction.text, "فرمانِ دستیِ پشتیبان در متن هست"
    assert "invalid provider_token" in service.last_errors[METHOD_BALE_PAY]


def test_non_url_link_result_without_username_is_a_clean_error(tmp_path):
    service, orders, client, hooks, oid, _claims = bale_service(tmp_path)
    client.link = "ble://nonsense"
    client.bot_username = ""
    with pytest.raises(PaymentError):
        run(service.build_instruction(orders.get(oid), METHOD_BALE_PAY, hooks))


def test_bale_pay_needs_two_tokens_and_a_live_bot(tmp_path):
    service, orders, client, hooks, oid, _claims = bale_service(tmp_path)
    service._settings.bale_pay_enabled = False  # noqa: SLF001
    with pytest.raises(PaymentError, match="فعال نیست"):
        run(service.build_instruction(orders.get(oid), METHOD_BALE_PAY, hooks))
    service._settings.bale_pay_enabled = True  # noqa: SLF001
    dead = PaymentHooks(bale_client=lambda: None)
    with pytest.raises(PaymentError, match="وصل نیست"):
        run(service.build_instruction(orders.get(oid), METHOD_BALE_PAY, dead))


def test_card_to_card_instruction_shows_the_number_and_asks_a_receipt(tmp_path):
    products = ProductStore(db_path=tmp_path / "p.db")
    orders = OrderStore(db_path=tmp_path / "o.db", product_store=products)
    settings = AppSettings(business_mode="store")
    settings.card_to_card_number = "6037991234567890"
    settings.card_to_card_holder_name = "علی رضایی"
    service = PaymentService(orders, products, settings)
    pid = products.add("کتاب", 250_000, 3)
    oid = orders.create("telegram", "1", [(pid, 1)])
    ins = run(service.build_instruction(orders.get(oid), METHOD_CARD_TO_CARD, PaymentHooks()))
    assert "6037991234567890" in ins.text and "علی رضایی" in ins.text
    assert ins.receipt_requested is True and ins.buttons == []
    assert orders.get(oid).payment_method == METHOD_CARD_TO_CARD
    assert "رسید" in ins.text, "از همان پیامِ پرداخت باید خواستنِ رسید مشخص باشد"


def test_card_to_card_receipt_request_can_be_switched_off(tmp_path):
    products = ProductStore(db_path=tmp_path / "p.db")
    orders = OrderStore(db_path=tmp_path / "o.db", product_store=products)
    settings = AppSettings(business_mode="store", card_to_card_number="6037991234567890", receipt_check_enabled=False)
    service = PaymentService(orders, products, settings)
    pid = products.add("کتاب", 250_000, 3)
    oid = orders.create("telegram", "1", [(pid, 1)])
    ins = run(service.build_instruction(orders.get(oid), METHOD_CARD_TO_CARD, PaymentHooks()))
    assert ins.receipt_requested is False and "رسید" not in ins.text


def test_available_methods_reflects_reality(tmp_path):
    service, orders, client, hooks, oid, _claims = bale_service(tmp_path)
    assert service.available_methods(bale_running=False) == []  # بدونِ توکنِ کارت و بدونِ رباتِ پرداخت
    service._settings.card_to_card_number = "6037991234567890"  # noqa: SLF001
    assert service.available_methods(bale_running=False) == [METHOD_CARD_TO_CARD]
    assert service.available_methods(bale_running=True) == [METHOD_CARD_TO_CARD, METHOD_BALE_PAY]


def test_unknown_method_is_rejected(tmp_path):
    service, orders, client, hooks, oid, _claims = bale_service(tmp_path)
    with pytest.raises(PaymentError):
        run(service.build_instruction(orders.get(oid), "zarinpal", hooks))
    with pytest.raises(PaymentError):
        run(service.build_instruction(orders.get(oid), "bale", hooks))


def test_invoice_prices_collapse_when_a_discount_was_applied(tmp_path):
    """ردیفِ منفیِ تخفیف را درگاه ممکن است رد کند؛ با تخفیف یک ردیفِ واحد می‌سازیم."""
    products = ProductStore(db_path=tmp_path / "p.db")
    orders = OrderStore(db_path=tmp_path / "o.db", product_store=products)
    pid = products.add("گوشی", 1_000_000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)], discount_code="")
    assert invoice_prices(orders.get(oid)) == [("گوشی", 1_000_000)]
    orders._connection().execute("UPDATE orders SET discount_irr=200000, total_irr=800000 WHERE id=?", (oid,))  # noqa: SLF001
    orders._connection().commit()  # noqa: SLF001
    order = orders.get(oid)
    assert invoice_prices(order) == [(f"سفارش #{oid}", 800_000)]
    assert sum(a for _l, a in invoice_prices(order)) == order.total_irr, "جمعِ فاکتور دقیقاً مبلغِ نهایی است"


# ================================================== فرمانِ /pay (فاکتورِ بومی)


def command(oid, code, chat="77"):
    return BalePayCommand(update_id=1, chat_id=chat, from_user_id=chat, order_id=oid, code=code)


def test_pay_command_forms_are_parsed():
    assert parse_pay_command("/start pay_12_ab12cd34") == (12, "ab12cd34")
    assert parse_pay_command("/pay 12 ab12cd34") == (12, "ab12cd34")
    assert parse_pay_command("/pay@my_bot 12 AB12CD34") == (12, "AB12CD34")
    assert parse_pay_command("/start pay-12-ab12cd34") == (12, "ab12cd34")
    assert parse_pay_command("/start") is None
    assert parse_pay_command("سلام") is None
    assert parse_pay_command("/pay abc def") is None
    assert parse_pay_command("") is None and parse_pay_command(None) is None


def test_pay_command_sends_invoice_to_the_chat_that_issued_it(tmp_path):
    service, orders, client, hooks, oid, _claims = bale_service(tmp_path)
    run(service.build_instruction(orders.get(oid), METHOD_BALE_PAY, hooks))
    code = orders.get(oid).gateway_ref
    reply = run(service.handle_pay_command(command(oid, code, "77"), client))
    assert f"#{oid}" in reply and "سفارش" in reply
    [call] = client.invoice_calls
    assert call["chat_id"] == "77" and call["payload"] == order_payload(oid, code), "به چتِ بله‌ای که فرمان داده"
    run(service.handle_pay_command(command(oid, code, "78"), client))
    assert client.invoice_calls[-1]["chat_id"] == "78"


def test_pay_command_rejects_bad_codes_and_unknown_orders(tmp_path):
    service, orders, client, hooks, oid, _claims = bale_service(tmp_path)
    run(service.build_instruction(orders.get(oid), METHOD_BALE_PAY, hooks))
    assert "معتبر نیست" in run(service.handle_pay_command(command(oid, "deadbeef"), client))
    assert "معتبر نیست" in run(service.handle_pay_command(command(oid + 5, "deadbeef"), client))
    assert client.invoice_calls == []


def test_pay_command_refuses_other_methods_expired_paid_and_disabled(tmp_path):
    service, orders, client, hooks, oid, _claims = bale_service(tmp_path)
    run(service.build_instruction(orders.get(oid), METHOD_BALE_PAY, hooks))
    code = orders.get(oid).gateway_ref

    orders.set_payment_info(oid, METHOD_CARD_TO_CARD)  # روش عوض شد → کدِ بله‌پی دیگر کار نمی‌کند
    assert "معتبر نیست" in run(service.handle_pay_command(command(oid, code), client))
    orders.set_payment_info(oid, METHOD_BALE_PAY, gateway_ref=code, payment_url="x")

    service._settings.bale_pay_enabled = False  # noqa: SLF001
    service._settings.set_bale_pay_provider_token("")  # noqa: SLF001
    assert "فعال نیست" in run(service.handle_pay_command(command(oid, code), client))
    service._settings.bale_pay_enabled = True  # noqa: SLF001
    service._settings.set_bale_pay_provider_token(TEST_PROVIDER_TOKEN)  # noqa: SLF001

    conn = orders._connection()  # noqa: SLF001
    conn.execute("UPDATE orders SET expires_ts=1 WHERE id=?", (oid,))
    conn.commit()
    assert "تمام شده" in run(service.handle_pay_command(command(oid, code), client))
    conn.execute("UPDATE orders SET expires_ts=0 WHERE id=?", (oid,))
    conn.commit()

    orders.mark_paid(oid, METHOD_BALE_PAY)
    assert "قبلاً پرداخت" in run(service.handle_pay_command(command(oid, code), client))
    assert client.invoice_calls == []


def test_pay_command_reports_invoice_failure_without_crashing(tmp_path):
    service, orders, client, hooks, oid, _claims = bale_service(tmp_path)
    run(service.build_instruction(orders.get(oid), METHOD_BALE_PAY, hooks))
    code = orders.get(oid).gateway_ref
    client.fail_invoice = "boom"
    reply = run(service.handle_pay_command(command(oid, code), client))
    assert "ممکن نشد" in reply and "boom" in service.last_errors[METHOD_BALE_PAY]


def test_new_payment_instruction_invalidates_the_old_code(tmp_path):
    service, orders, client, hooks, oid, _claims = bale_service(tmp_path)
    run(service.build_instruction(orders.get(oid), METHOD_BALE_PAY, hooks))
    first = orders.get(oid).gateway_ref
    run(service.build_instruction(orders.get(oid), METHOD_BALE_PAY, hooks))
    second = orders.get(oid).gateway_ref
    assert first != second and len(first) == 12 and len(make_pay_code()) == 12
    assert "معتبر نیست" in run(service.handle_pay_command(command(oid, first), client))


# ================================================== تشخیص (UI) و ابزارها


def test_provider_token_normalization_and_description():
    assert normalize_provider_token("۶۰۳۷-۹۹۱۱ ۲۲۳۳-۴۴۵۵") == "6037991122334455"
    assert normalize_provider_token(f"  {TEST_PROVIDER_TOKEN} ") == TEST_PROVIDER_TOKEN
    assert normalize_provider_token("12345") == "12345", "فرمتِ ناشناخته دست‌نخورده می‌مونه"
    assert normalize_provider_token("") == ""
    assert "کارت" in describe_provider_token("6037-9911-2233-4455")
    assert "آزمایشی" in describe_provider_token(TEST_PROVIDER_TOKEN)
    assert "کیف‌پول" in describe_provider_token("WALLET-OTHER")


def test_diagnose_bale_pay_builds_a_test_link(tmp_path):
    service, orders, client, hooks, oid, _claims = bale_service(tmp_path)
    ok, message = run(service.diagnose_bale_pay(hooks))
    assert ok and "لینکِ پرداختِ آزمایشی" in message
    assert client.link_calls[-1]["prices"] == [("تست", 10_000)] and client.link_calls[-1]["payload"] == "diag"
    assert "آزمایشی" in message, "توکنِ تستِ مستندات باید به مالک گفته شود"

    client.link_error = "invalid provider_token"
    ok, message = run(service.diagnose_bale_pay(hooks))
    assert not ok and "invalid provider_token" in message
    assert "invalid provider_token" in service.last_errors[METHOD_BALE_PAY]


def test_diagnose_bale_pay_without_token_or_bot(tmp_path):
    service, orders, client, hooks, oid, _claims = bale_service(tmp_path)
    no_bot = PaymentHooks(bale_client=lambda: None)
    ok, message = run(service.diagnose_bale_pay(no_bot))
    assert not ok and "وصل نیست" in message
    service._settings.set_bale_pay_provider_token("")  # noqa: SLF001
    ok, message = run(service.diagnose_bale_pay(hooks))
    assert not ok and "وارد نشده" in message
    service._settings.bale_pay_enabled = False  # noqa: SLF001
    ok, message = run(service.diagnose_bale_pay(hooks))
    assert not ok and "خاموش" in message


def test_diagnose_card_to_card_says_confirmation_is_manual(tmp_path):
    service = PaymentService(None, None, AppSettings(card_to_card_number="6037991234567890"))
    ok, message = run(service.diagnose_card_to_card())
    assert ok and "دستی" in message
    off = PaymentService(None, None, AppSettings())
    ok, message = run(off.diagnose_card_to_card())
    assert not ok and "کارت" in message


def test_order_payload_roundtrip_with_code():
    assert order_payload(42) == "order:42"
    assert order_payload(42, "abcd") == "order:42:abcd"
    assert parse_payload("order:42") == (42, "")
    assert parse_payload("order:42:abcd") == (42, "abcd")
    assert parse_payload("garbage") == (None, "")
    assert parse_payload("") == (None, "")
    assert parse_payload("order:abc") == (None, "")


def test_deep_link_and_payment_url_helpers():
    from app.core.payments import bale_pay_deep_link, looks_like_payment_url

    assert bale_pay_deep_link("my_bot", 7, "code7") == "https://ble.ir/my_bot?start=pay_7_code7"
    assert looks_like_payment_url("https://bale.ai/pay/x") and looks_like_payment_url("http://x")
    assert not looks_like_payment_url("ble://x") and not looks_like_payment_url("")
