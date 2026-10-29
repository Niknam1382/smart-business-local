import asyncio

import pytest
from fake_zarinpal import FakeZarinpalServer

from app.core.zarinpal import (
    PROD_BASE,
    SANDBOX_BASE,
    ZarinpalClient,
    ZarinpalError,
    is_valid_merchant_id,
)

MERCHANT = "12345678-1234-1234-1234-123456789012"


@pytest.fixture
def server():
    srv = FakeZarinpalServer(MERCHANT).start()
    yield srv
    srv.stop()


def run(coro):
    return asyncio.run(coro)


def client(server, **kw):
    return ZarinpalClient(MERCHANT, base_url=server.base_url, **kw)


def test_defaults_point_to_official_hosts():
    assert ZarinpalClient(MERCHANT).base_url == PROD_BASE == "https://payment.zarinpal.com"
    assert ZarinpalClient(MERCHANT, sandbox=True).base_url == SANDBOX_BASE
    assert ZarinpalClient(MERCHANT).start_url("A1") == "https://payment.zarinpal.com/pg/StartPay/A1"


@pytest.mark.parametrize(
    "value,ok",
    [(MERCHANT, True), (MERCHANT.upper(), True), ("  " + MERCHANT + " ", True), ("", False), ("abc", False), (MERCHANT + "0", False), ("zzzzzzzz-1234-1234-1234-123456789012", False)],
)
def test_merchant_id_validation(value, ok):
    assert is_valid_merchant_id(value) is ok


def test_create_payment_sends_documented_body_and_builds_link(server):
    pay = run(client(server).create_payment(250_000, "https://t.me/shop_bot", "سفارش #7", mobile="09120000000"))
    body = server.requests[0]
    assert body["merchant_id"] == MERCHANT and body["amount"] == 250_000
    assert body["currency"] == "IRR" and body["callback_url"] == "https://t.me/shop_bot"
    assert body["description"] == "سفارش #7" and body["metadata"] == {"mobile": "09120000000"}
    assert pay.authority.startswith("A") and pay.url == f"{server.base_url}/pg/StartPay/{pay.authority}"


def test_create_payment_without_mobile_omits_metadata(server):
    run(client(server).create_payment(10_000, "https://x", "d"))
    assert "metadata" not in server.requests[0]


def test_create_payment_zarinpal_error_is_persian(server):
    server.fail_request_with = {"code": -9, "message": "Validation error"}
    with pytest.raises(ZarinpalError, match="مرچنت‌کد"):
        run(client(server).create_payment(10_000, "https://x", "d"))
    server.fail_request_with = {"code": -777, "message": "عجیب"}
    with pytest.raises(ZarinpalError, match="کد -777"):
        run(client(server).create_payment(10_000, "https://x", "d"))


def test_wrong_merchant_is_rejected(server):
    bad = ZarinpalClient("00000000-0000-0000-0000-000000000000", base_url=server.base_url)
    with pytest.raises(ZarinpalError, match="معتبر نیست"):
        run(bad.create_payment(10_000, "https://x", "d"))


def test_network_down_raises_persian_error(server):
    server.down = True
    with pytest.raises(ZarinpalError, match="ارتباط با زرین‌پال"):
        run(client(server, timeout=3).create_payment(10_000, "https://x", "d"))


def test_verify_unpaid_then_paid_then_already_verified(server):
    c = client(server)
    pay = run(c.create_payment(10_000, "https://x", "d"))

    unpaid = run(c.verify(pay.authority, 10_000))
    assert unpaid.paid is False and unpaid.fatal is False, "پرداخت‌نشده = بعداً دوباره استعلام کن"

    server.pay(pay.authority)
    paid = run(c.verify(pay.authority, 10_000))
    assert paid.paid and not paid.already_verified and paid.ref_id == "201" and paid.code == 100

    again = run(c.verify(pay.authority, 10_000))
    assert again.paid and again.already_verified and again.code == 101


def test_verify_amount_mismatch_and_unknown_authority_are_fatal(server):
    c = client(server)
    pay = run(c.create_payment(10_000, "https://x", "d"))
    server.pay(pay.authority)
    wrong = run(c.verify(pay.authority, 99_999))
    assert wrong.paid is False and wrong.fatal is True, "مبلغِ نامطابق هرگز نباید «پرداخت‌شده» حساب بشه"
    unknown = run(c.verify("A-nonexistent", 10_000))
    assert unknown.paid is False and unknown.fatal is True


def test_verify_network_error_raises_not_false(server):
    c = client(server, timeout=3)
    pay = run(c.create_payment(10_000, "https://x", "d"))
    server.down = True
    with pytest.raises(ZarinpalError):
        run(c.verify(pay.authority, 10_000))
