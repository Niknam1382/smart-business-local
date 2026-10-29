import asyncio


from app.core.bale_client import BaleApiError, BalePreCheckoutQuery, BaleSuccessfulPayment
from app.core.orders import METHOD_BALE_PAY, OrderStore
from app.core.payments import PaymentService, order_payload
from app.core.products import ProductStore


def run(coro):
    return asyncio.run(coro)


class FakeBaleClient:
    def __init__(self, transaction_status="Successful", fail_inquire=False):
        self.answers = []  # [(query_id, ok, error_message)]
        self.transaction_status = transaction_status
        self.fail_inquire = fail_inquire
        self.inquired = []
        self.invoice_calls = []
        self.fail_invoice = None

    async def answer_pre_checkout_query(self, query_id, ok, error_message=""):
        self.answers.append((query_id, ok, error_message))

    async def inquire_transaction(self, transaction_id):
        self.inquired.append(transaction_id)
        if self.fail_inquire:
            raise BaleApiError("شبکه قطع شد")
        return {"status": self.transaction_status, "transaction_id": transaction_id}

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


def test_pre_checkout_accepts_valid_order_with_stock(tmp_path):
    products, orders, service = make_service(tmp_path)
    pid = products.add("گوشی", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 2)])
    client = FakeBaleClient()
    query = BalePreCheckoutQuery(update_id=1, query_id="q1", from_user_id="1", invoice_payload=order_payload(oid), total_amount=2000, currency="IRR")

    run(service.handle_pre_checkout(query, client))
    assert client.answers == [("q1", True, "")]


def test_pre_checkout_rejects_unknown_payload(tmp_path):
    _, _, service = make_service(tmp_path)
    client = FakeBaleClient()
    query = BalePreCheckoutQuery(update_id=1, query_id="q1", from_user_id="1", invoice_payload="garbage", total_amount=1000, currency="IRR")
    run(service.handle_pre_checkout(query, client))
    assert client.answers[0][0] == "q1" and client.answers[0][1] is False


def test_pre_checkout_rejects_order_not_pending(tmp_path):
    products, orders, service = make_service(tmp_path)
    pid = products.add("گوشی", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)])
    orders.mark_paid(oid, METHOD_BALE_PAY)  # دیگه pending_payment نیست
    client = FakeBaleClient()
    query = BalePreCheckoutQuery(update_id=1, query_id="q1", from_user_id="1", invoice_payload=order_payload(oid), total_amount=1000, currency="IRR")
    run(service.handle_pre_checkout(query, client))
    assert client.answers[0][1] is False


def test_pre_checkout_rejects_insufficient_stock_with_item_name(tmp_path):
    products, orders, service = make_service(tmp_path)
    pid = products.add("گوشی کمیاب", 1000, 1)
    oid = orders.create("telegram", "1", [(pid, 1)])
    products.adjust_stock(pid, -1)  # یکی دیگه زودتر خرید؛ الان موجودی صفره
    client = FakeBaleClient()
    query = BalePreCheckoutQuery(update_id=1, query_id="q1", from_user_id="1", invoice_payload=order_payload(oid), total_amount=1000, currency="IRR")
    run(service.handle_pre_checkout(query, client))
    _, ok, msg = client.answers[0]
    assert ok is False and "گوشی کمیاب" in msg


def test_successful_payment_marks_paid(tmp_path):
    products, orders, service = make_service(tmp_path)
    pid = products.add("گوشی", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 2)])
    client = FakeBaleClient()

    payment = BaleSuccessfulPayment(
        update_id=1, chat_id="1", invoice_payload=order_payload(oid), total_amount=2000, currency="IRR",
        telegram_payment_charge_id="tg1", provider_payment_charge_id="prov1",
    )
    # عمداً send نمی‌گیره: کیِ/به‌کجا اطلاع بدیم مسئولیت BotManagerه، نه PaymentService
    # (چون payment.chat_id سمتِ بله‌ست، نه لزوماً چت اصلیِ مشتری — جزئیات در payments.py)
    order = run(service.handle_successful_payment(payment, client))
    assert orders.get(oid).status == "paid"
    assert orders.get(oid).payment_reference == "prov1"
    assert client.inquired == ["prov1"]
    assert order.id == oid


def test_successful_payment_blocked_by_explicit_failed_transaction_status(tmp_path):
    products, orders, service = make_service(tmp_path)
    pid = products.add("گوشی", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)])
    client = FakeBaleClient(transaction_status="Failed")

    payment = BaleSuccessfulPayment(update_id=1, chat_id="1", invoice_payload=order_payload(oid), total_amount=1000, currency="IRR", telegram_payment_charge_id="t", provider_payment_charge_id="p")
    result = run(service.handle_successful_payment(payment, client))
    assert result is None
    assert orders.get(oid).status == "pending_payment", "نباید paid بشه وقتی استعلام صراحتاً ناموفق می‌گه"


def test_successful_payment_proceeds_when_inquiry_itself_fails(tmp_path):
    """خطای شبکه در استعلام نباید جلوی ثبت پرداختی که خودِ بله تایید کرده رو بگیره."""
    products, orders, service = make_service(tmp_path)
    pid = products.add("گوشی", 1000, 5)
    oid = orders.create("telegram", "1", [(pid, 1)])
    client = FakeBaleClient(fail_inquire=True)

    payment = BaleSuccessfulPayment(update_id=1, chat_id="1", invoice_payload=order_payload(oid), total_amount=1000, currency="IRR", telegram_payment_charge_id="t", provider_payment_charge_id="p")
    result = run(service.handle_successful_payment(payment, client))
    assert result is not None
    assert orders.get(oid).status == "paid"


def test_successful_payment_unknown_payload_does_nothing(tmp_path):
    _, orders, service = make_service(tmp_path)
    client = FakeBaleClient()

    payment = BaleSuccessfulPayment(update_id=1, chat_id="1", invoice_payload="garbage", total_amount=1000, currency="IRR", telegram_payment_charge_id="t", provider_payment_charge_id="p")
    result = run(service.handle_successful_payment(payment, client))
    assert result is None


def test_successful_payment_does_not_depend_on_any_notification_step(tmp_path):
    """خودِ PaymentService دیگه send نمی‌گیره؛ این یعنی ثبتِ پرداخت هیچ‌وقت به
    موفقیتِ اطلاع‌رسانی (که حالا مسئولیتِ BotManagerه) وابسته نیست."""
    products, orders, service = make_service(tmp_path)
    pid = products.add("گوشی", 1000, 1)
    oid = orders.create("telegram", "1", [(pid, 1)])
    client = FakeBaleClient()

    payment = BaleSuccessfulPayment(update_id=1, chat_id="1", invoice_payload=order_payload(oid), total_amount=1000, currency="IRR", telegram_payment_charge_id="t", provider_payment_charge_id="p")
    result = run(service.handle_successful_payment(payment, client))
    assert result is not None
    assert orders.get(oid).status == "paid"


# ------------------------------------------------ بله‌پی: فاکتورِ بومی و دیپ‌لینک


def bale_service(tmp_path, platform="telegram", chat_id="1", price=500_000, quantity=2):
    from app.core.payments import PaymentHooks
    from app.core.settings import AppSettings

    products = ProductStore(db_path=tmp_path / "p.db")
    orders = OrderStore(db_path=tmp_path / "o.db", product_store=products)
    settings = AppSettings()
    settings.business_mode = "store"
    settings.shop_mode = "shop_ai"  # جریانِ AIِ ۰.۵.۰ (آزمایشی)؛ پیش‌فرضِ ۱.۰.۰ دکمه‌ایه
    settings.set_bale_pay_provider_token("WALLET-TEST-1111111111111111")
    settings.bale_pay_enabled = True
    service = PaymentService(orders, products, settings)
    client = FakeBaleClient()
    hooks = PaymentHooks(bale_client=lambda: client, bot_username=lambda p: f"{p}_shop_bot")
    pid = products.add("هدفون", price, 10)
    oid = orders.create(platform, chat_id, [(pid, quantity)])
    return service, orders, client, hooks, oid


def test_bale_customer_gets_native_invoice_and_no_link(tmp_path):
    service, orders, client, hooks, oid = bale_service(tmp_path, platform="bale", chat_id="40")
    instruction = run(service.build_instruction(orders.get(oid), METHOD_BALE_PAY, hooks))
    [call] = client.invoice_calls
    assert call["chat_id"] == "40" and call["payload"] == order_payload(oid)
    assert call["token"] == "WALLET-TEST-1111111111111111" and call["prices"] == [("هدفون", 1_000_000)]
    assert "فاکتور بله‌پی" in instruction.text and not instruction.buttons and not instruction.url
    assert orders.get(oid).payment_method == METHOD_BALE_PAY


def test_native_invoice_respects_bale_length_limits(tmp_path):
    service, orders, client, hooks, oid = bale_service(tmp_path, platform="bale", chat_id="40")
    products = ProductStore(db_path=tmp_path / "p.db")
    long_name = "کالای خیلی طولانی " * 6
    pid = products.add(long_name, 1000, 5)
    oid2 = orders.create("bale", "40", [(pid, 1)])
    run(service.build_instruction(orders.get(oid2), METHOD_BALE_PAY, hooks))
    call = client.invoice_calls[-1]
    assert len(call["title"]) <= 32 and len(call["description"]) <= 255
    assert all(len(label) <= 32 for label, _ in call["prices"])


def test_native_invoice_failure_is_a_clean_payment_error(tmp_path):
    from app.core.payments import PaymentError

    service, orders, client, hooks, oid = bale_service(tmp_path, platform="bale", chat_id="40")
    client.fail_invoice = "invalid provider_token"
    try:
        run(service.build_instruction(orders.get(oid), METHOD_BALE_PAY, hooks))
        raise AssertionError("باید PaymentError می‌داد")
    except PaymentError as exc:
        assert "ممکن نشد" in str(exc)
    assert "invalid provider_token" in service.last_errors[METHOD_BALE_PAY]


def test_telegram_customer_gets_deep_link_with_secret_code(tmp_path):
    service, orders, client, hooks, oid = bale_service(tmp_path)
    instruction = run(service.build_instruction(orders.get(oid), METHOD_BALE_PAY, hooks))
    order = orders.get(oid)
    code = order.gateway_ref
    assert len(code) == 8
    link = f"https://ble.ir/bale_shop_bot?start=pay_{oid}_{code}"
    assert instruction.url == link and instruction.buttons == [("💳 پرداخت با بله‌پی", link)]
    assert link in instruction.text and f"/pay {oid} {code}" in instruction.text and "[" not in instruction.text
    assert order.payment_url == link and order.payment_method == METHOD_BALE_PAY
    assert client.invoice_calls == [], "فاکتور تا وقتی مشتری توی بله «شروع» نزده فرستاده نمی‌شه"


def test_deep_link_needs_bale_username(tmp_path):
    from app.core.payments import PaymentError, PaymentHooks

    service, orders, client, _hooks, oid = bale_service(tmp_path)
    no_username = PaymentHooks(bale_client=lambda: client, bot_username=lambda p: None)
    try:
        run(service.build_instruction(orders.get(oid), METHOD_BALE_PAY, no_username))
        raise AssertionError("باید PaymentError می‌داد")
    except PaymentError as exc:
        assert "مشخص نیست" in str(exc)


def test_new_payment_instruction_invalidates_the_old_code(tmp_path):
    service, orders, client, hooks, oid = bale_service(tmp_path)
    run(service.build_instruction(orders.get(oid), METHOD_BALE_PAY, hooks))
    first = orders.get(oid).gateway_ref
    run(service.build_instruction(orders.get(oid), METHOD_BALE_PAY, hooks))
    second = orders.get(oid).gateway_ref
    assert first != second
    assert "معتبر نیست" in run(service.handle_pay_command(f"/pay {oid} {first}", "77", client))


def test_pay_command_forms_are_parsed():
    from app.core.payments import parse_pay_command

    assert parse_pay_command("/start pay_12_ab12cd34") == (12, "ab12cd34")
    assert parse_pay_command("/pay 12 ab12cd34") == (12, "ab12cd34")
    assert parse_pay_command("/pay@my_bot 12 AB12CD34") == (12, "AB12CD34")
    assert parse_pay_command("/start") is None
    assert parse_pay_command("سلام") is None
    assert parse_pay_command("/pay abc def") is None
    assert parse_pay_command("") is None and parse_pay_command(None) is None


def test_pay_command_sends_invoice_to_the_chat_that_issued_it(tmp_path):
    service, orders, client, hooks, oid = bale_service(tmp_path)  # مشتریِ اصلی تلگرامیه
    run(service.build_instruction(orders.get(oid), METHOD_BALE_PAY, hooks))
    code = orders.get(oid).gateway_ref
    reply = run(service.handle_pay_command(f"/start pay_{oid}_{code}", "77", client))
    assert f"#{oid}" in reply and "فاکتور" in reply
    [call] = client.invoice_calls
    assert call["chat_id"] == "77" and call["payload"] == order_payload(oid), "به چتِ بله‌ای که فرمان داده"
    # فرمانِ دستی هم همون کار رو می‌کنه
    run(service.handle_pay_command(f"/pay {oid} {code}", "78", client))
    assert client.invoice_calls[-1]["chat_id"] == "78"


def test_pay_command_ignores_plain_messages_and_rejects_bad_codes(tmp_path):
    service, orders, client, hooks, oid = bale_service(tmp_path)
    run(service.build_instruction(orders.get(oid), METHOD_BALE_PAY, hooks))
    assert run(service.handle_pay_command("سلام", "77", client)) is None
    assert run(service.handle_pay_command("/start", "77", client)) is None
    for bad in (f"/pay {oid} deadbeef", f"/pay {oid + 5} deadbeef", f"/start pay_{oid}_xxxxxxxx"):
        assert "معتبر نیست" in run(service.handle_pay_command(bad, "77", client))
    assert client.invoice_calls == []


def test_pay_command_refuses_other_methods_expired_paid_and_disabled(tmp_path):
    service, orders, client, hooks, oid = bale_service(tmp_path)
    run(service.build_instruction(orders.get(oid), METHOD_BALE_PAY, hooks))
    code = orders.get(oid).gateway_ref

    # روشِ پرداخت عوض شد → کدِ بله‌پی دیگه کار نمی‌کنه
    orders.set_payment_info(oid, "card_to_card")
    assert "معتبر نیست" in run(service.handle_pay_command(f"/pay {oid} {code}", "77", client))
    orders.set_payment_info(oid, METHOD_BALE_PAY, gateway_ref=code, payment_url="x")

    service._settings.bale_pay_enabled = False  # noqa: SLF001
    assert "فعال نیست" in run(service.handle_pay_command(f"/pay {oid} {code}", "77", client))
    service._settings.bale_pay_enabled = True  # noqa: SLF001

    conn = orders._connection()  # noqa: SLF001
    conn.execute("UPDATE orders SET expires_ts=1 WHERE id=?", (oid,))
    conn.commit()
    assert "معتبر نیست" in run(service.handle_pay_command(f"/pay {oid} {code}", "77", client))
    conn.execute("UPDATE orders SET expires_ts=0 WHERE id=?", (oid,))
    conn.commit()

    orders.mark_paid(oid, METHOD_BALE_PAY)
    assert "قبلاً پرداخت" in run(service.handle_pay_command(f"/pay {oid} {code}", "77", client))
    assert client.invoice_calls == []


def test_pay_command_reports_invoice_failure_without_crashing(tmp_path):
    service, orders, client, hooks, oid = bale_service(tmp_path)
    run(service.build_instruction(orders.get(oid), METHOD_BALE_PAY, hooks))
    code = orders.get(oid).gateway_ref
    client.fail_invoice = "boom"
    reply = run(service.handle_pay_command(f"/pay {oid} {code}", "77", client))
    assert "ممکن نشد" in reply and "boom" in service.last_errors[METHOD_BALE_PAY]


def test_provider_token_normalization_and_description():
    from app.core.payments import describe_provider_token, normalize_provider_token

    assert normalize_provider_token("۶۰۳۷-۹۹۱۱ ۲۲۳۳-۴۴۵۵") == "6037991122334455"
    assert normalize_provider_token("  WALLET-TEST-1111111111111111 ") == "WALLET-TEST-1111111111111111"
    assert normalize_provider_token("12345") == "12345", "فرمتِ ناشناخته دست‌نخورده می‌مونه"
    assert normalize_provider_token("") == ""
    assert "کارت" in describe_provider_token("6037-9911-2233-4455")
    assert "کیف‌پول" in describe_provider_token("WALLET-TEST-1")
    assert "ناشناخته" in describe_provider_token("abc")


def test_diagnose_bale_pay_sends_a_real_test_invoice_to_the_owner(tmp_path):
    service, orders, client, hooks, oid = bale_service(tmp_path)
    ok, message = run(service.diagnose_bale_pay(hooks))
    assert ok and "ثبت کن" in message, "بدون چتِ مالک فقط اتصال/نوعِ توکن چک می‌شه"
    assert client.invoice_calls == []

    service._settings.owner_chats = {"bale": "555"}  # noqa: SLF001
    ok, message = run(service.diagnose_bale_pay(hooks))
    assert ok and client.invoice_calls[-1]["chat_id"] == "555" and client.invoice_calls[-1]["payload"] == "diag"

    client.fail_invoice = "invalid provider_token"
    ok, message = run(service.diagnose_bale_pay(hooks))
    assert not ok and "invalid provider_token" in message
    assert "invalid provider_token" in service.last_errors[METHOD_BALE_PAY]


def test_diagnose_bale_pay_without_token_or_bot(tmp_path):
    from app.core.payments import PaymentHooks

    service, orders, client, hooks, oid = bale_service(tmp_path)
    no_bot = PaymentHooks(bale_client=lambda: None, bot_username=lambda p: None)
    ok, message = run(service.diagnose_bale_pay(no_bot))
    assert not ok and "ربات بله" in message
    service._settings.set_bale_pay_provider_token("")  # noqa: SLF001
    ok, message = run(service.diagnose_bale_pay(hooks))
    assert not ok and "وارد نشده" in message


def test_order_payload_roundtrip():
    from app.core.payments import _parse_order_id

    assert order_payload(42) == "order:42"
    assert _parse_order_id("order:42") == 42
    assert _parse_order_id("garbage") is None
    assert _parse_order_id("") is None
    assert _parse_order_id("order:abc") is None
