"""۱.۰.۰ — رسیدِ کارت‌به‌کارت: خواندنِ متن (``app/core/receipts.py``) و مسیرِ کاملِ آن در ShopFlow.

قراردادهایی که این فایل میخکوب می‌کند (همه‌اش روی کدِ قدیمی/بدونِ این ماژول‌ها می‌شکنه):
* «پرداخت کردم» هیچ‌وقت سفارش را تأیید نمی‌کند؛ فقط «پرداخت‌شده» + آلارمِ مالک + درخواستِ رسید.
* رسیدِ متنی ذخیره می‌شه و نظرِ برنامه (``amount_ok`` / ``amount_mismatch`` / ``none``) در همان ردیف می‌شینه؛
  مبلغِ سفارش هرگز از متنِ رسید بازنویسی نمی‌شه و ``payment_reference`` فقط کدِ تراکنش است.
* عکسِ رسید فقط با ``hooks.attachment_saver`` ذخیره می‌شه؛ اگر دانلود نشد، برنامه نمی‌ترکد و رسیدی ثبت نمی‌شه.
* پیامِ منو/فرمان در مرحله‌ی رسید = «این رسید نبود» ⇒ نشست بسته می‌شه و پیام به جریانِ عادی می‌ره.
* یک شناسهٔ تراکنش فقط یک سفارش را تأیید می‌کند (``orders.claim_payment_charge``).
"""

import asyncio

import pytest
from shop_harness import Harness, texts

from app.core import receipts
from app.core.owner_console import OwnerConsole
from app.core.orders import (
    METHOD_BALE_PAY,
    METHOD_CARD_TO_CARD,
    STATUS_CONFIRMED,
    STATUS_PAID,
    STATUS_PENDING_PAYMENT,
)

AMOUNT = 1_250_000  # ریال
TOMAN = AMOUNT // 10


# ================================================================ پارسرِ متن ====

def test_persian_and_arabic_digits_read_as_the_same_amount():
    assert receipts.normalize_digits("۱۲۵۰۰۰۰") == "1250000"
    assert receipts.normalize_digits("١٢٥٠٠٠٠") == "1250000"
    for body in ("یاریز ۱۲۵۰۰۰۰ ریال", "واریز ١٢٥٠٠٠٠ ریال", "amount 1250000 IRR"):
        info = receipts.parse_receipt(body, AMOUNT)
        assert info.amounts == [AMOUNT], body
        assert info.state == "amount_ok" and info.matched_amount == AMOUNT, body


def test_thousands_separators_are_stripped_not_misread():
    for body in ("1,250,000", "۱,۲۵۰,۰۰۰", "1 250 000", "1.250.000", "1\u00a0250\u00a0000"):
        info = receipts.parse_receipt(f"مبلغ: {body} ریال", AMOUNT)
        assert info.amounts == [AMOUNT], (body, info.amounts)
        assert info.state == "amount_ok", body


def test_a_toman_number_matches_an_irr_order_amount():
    """رسیدهایِ تومانِ مشتری را هم می‌شناسد (×۱۰)، ولی همان عدد را ذخیره می‌کند."""
    info = receipts.parse_receipt(f"{TOMAN:,} تومان", AMOUNT)
    assert info.state == "amount_ok" and info.matched_amount == TOMAN
    assert info.summary(AMOUNT).startswith(f"مبلغِ {TOMAN:,} ریال"), info.summary(AMOUNT)


def test_number_equal_to_the_order_is_ok_and_a_clearly_different_one_is_a_mismatch():
    assert receipts.parse_receipt("1250000", AMOUNT).state == "amount_ok"
    low = receipts.parse_receipt("مبلغ 800,000 ریال", AMOUNT)
    assert low.state == "amount_mismatch" and low.nearest_amount == 800_000
    assert "کمتر" in low.summary(AMOUNT) and "450,000" in low.summary(AMOUNT)
    high = receipts.parse_receipt("مبلغ 2,500,000 ریال", AMOUNT)
    assert high.state == "amount_mismatch" and high.nearest_amount == 2_500_000
    assert "بیشتر" in high.summary(AMOUNT)
    # نزدیک‌ترین عدد وقتی چند عددِ بی‌ربط هست: فاصله تا مبلغِ سفارش، نه بزرگ‌ترین عدد
    mixed = receipts.parse_receipt("کارمزد 1,240,000 و موجودی 9,999,999", AMOUNT)
    assert mixed.state == "amount_mismatch" and mixed.nearest_amount == 1_240_000


def test_card_number_runs_are_never_taken_as_amounts():
    for card in ("6037991234567890", "6037-9912-3456-7890", "6037 9912 3456 7890"):
        info = receipts.parse_receipt(f"کارت مقصد: {card}", AMOUNT)
        assert info.amounts == [], (card, info.amounts)  # تکه‌هایِ کارت «مبلغ» نمی‌شن
        assert info.state == "none"
        assert info.card_last4 == "7890", card
    # کارت + مبلغِ واقعی: فقط مبلغ شمرده می‌شه
    both = receipts.parse_receipt("به کارت 6037-9912-3456-7890 مبلغ 1,250,000 ریال", AMOUNT)
    assert both.amounts == [AMOUNT] and both.state == "amount_ok" and both.card_last4 == "7890"


def test_trace_code_from_its_keywords():
    for body in (
        "کد پیگیری: 456789012",
        "شماره رهگیری ۴۵۶۷۸۹۰۱۲",
        "کد تراکنش 456789012 مبلغ 1250000",
        "Trace Code 456789012",
        "RRN 456789012",
        "Reference No: 456789012",
    ):
        assert receipts.parse_receipt(body, AMOUNT).trace == "456789012", body


def test_trace_code_falls_back_to_the_longest_transaction_like_number():
    """بدونِ برچسب: عددِ «مبلغ» نیست ⇒ بلندترین عددِ ۹ تا ۱۶ رقمی که با مبلغ سفارش نمی‌خونه."""
    info = receipts.parse_receipt("شماره 123456789 مبلغ 1,250,000", AMOUNT)
    assert info.trace == "123456789" and info.state == "amount_ok"
    # مبلغِ سفارش و ده‌برابرش (تومان) هیچ‌وقت به‌عنوان کد تراکنش برداشته نمی‌شن
    only_amount = receipts.parse_receipt("1250000", AMOUNT)
    assert only_amount.trace == ""
    assert receipts.parse_receipt(f"{TOMAN}", AMOUNT).trace == ""
    # کوتاه‌تر از ۹ رقم ⇒ کد نیست
    assert receipts.parse_receipt("کارت 1234 مبلغ 1,250,000", AMOUNT).trace == ""


def test_last4_from_a_masked_or_full_card_and_the_date():
    assert receipts.parse_receipt("کارت ****1234 رسید", 0).card_last4 == "1234"
    assert receipts.parse_receipt("کارت ★★★★★★۷۸۹۰", 0).card_last4 == "7890"
    assert receipts.parse_receipt("6037-9912-3456-7890", 0).card_last4 == "7890"
    # ستاره به سبکِ فارسی («××××۱۲۳۴») ماسک نیست؛ فقط * و ★ ⇒ برنامه دروغ نمی‌سازد
    assert receipts.parse_receipt("کارت ××××1234", 0).card_last4 == ""
    assert receipts.parse_receipt("1405/04/12 10:23 — 1,250,000 ریال", AMOUNT).date_text == "1405/04/12 10:23"
    assert receipts.parse_receipt("هیچ چیزی", AMOUNT).date_text == ""


def test_summary_wording_for_every_state():
    ok = receipts.parse_receipt("1,250,000", AMOUNT)
    assert ok.summary(AMOUNT) == f"مبلغِ {AMOUNT:,} ریال با مبلغ سفارش می‌خونه."
    bad = receipts.parse_receipt("900,000", AMOUNT)
    assert bad.summary(AMOUNT) == f"مبلغِ رسید (900,000) {AMOUNT - 900_000:,} ریال کمتر از مبلغ سفارشه — چک کن."
    numbers = receipts.parse_receipt("شماره کارت 603799 ۳۵", 0)  # مبلغِ سفارش مشخص نیست ⇒ نظر نمی‌دهد
    assert numbers.state == "none" and numbers.amounts and "عددهای یافت‌شده" in numbers.summary(0)
    empty = receipts.parse_receipt("رسیدِ دست‌نویس بدون عدد", AMOUNT)
    assert not empty.has_anything and empty.summary(AMOUNT) == "متنِ رسید عددی نداشت؛ خودِ متن را بخوان."
    assert receipts.parse_receipt("", AMOUNT).summary(AMOUNT) == empty.summary(AMOUNT)


@pytest.mark.parametrize("hostile", [
    "۱" * 2000,
    "1,250,000" * 250,
    "\x00\x01\x02\x0b\x0c\x1f\x7f" + "1250000" + "\x00" * 500,
    "🎉💵🧾" * 700 + " مبلغ ۱۲۵۰۰۰۰ ",
    "1" + ",1" * 900,  # الگوی بد backstring: هیچ‌وقت «۳ رقم» نمی‌شود
    "\u200f\u200e\u200c ۱۲۵۰۰۰۰ \u200f",
    "؛" * 3000,
    "۰" * 1500,
])
def test_the_parser_survives_anything_a_customer_can_paste(hostile):
    """هیچ ورودیِ کثیفی نه کرش می‌کند، نه عددِ بی‌ربط را «تأیید» می‌کند."""
    info = receipts.parse_receipt(hostile, AMOUNT)
    assert info.state in ("amount_ok", "amount_mismatch", "none")
    assert all(100 <= a <= 10**14 for a in info.amounts)  # MIN_AMOUNT و سقفِ ۱۴ رقم
    assert len(info.trace) <= 20 and len(info.card_last4) <= 4
    info.summary(AMOUNT)  # خلاصه هم نباید ترکید


# ====================================================== مسیرِ رسید در ShopFlow ====

@pytest.fixture
def h(tmp_path):
    harness = Harness(tmp_path)
    harness.pid = harness.add_product("گوشی", AMOUNT, 5)
    return harness


def claim(h, oid=None):
    oid = oid if oid is not None else h.card_order(h.pid)
    res = h.tap(f"c:paid:{oid}")
    assert "رسید" in texts(res), texts(res)
    return oid


def test_claim_asks_a_receipt_then_a_text_receipt_is_recorded_but_not_confirmed(h):
    oid = claim(h)
    assert h.orders.get(oid).status == STATUS_PAID
    assert h.flow.sessions.get("telegram", "1").step == "receipt"
    res = h.say(f"واریز {AMOUNT:,} ریال — کد پیگیری 456789012")
    assert res.consumed and "رسید ثبت شد" in texts(res)
    [row] = h.orders.receipts_for(oid)
    assert row["kind"] == "text" and row["match_state"] == "amount_ok"
    assert row["amount_irr"] == AMOUNT and row["trace_code"] == "456789012"
    assert "456789012" in row["body"] and "ریال" in row["body"]
    # هیچ‌وقت تأیید نشد؛ فقط پرداخت‌شده — و موجودی هم کم نشده
    assert h.orders.get(oid).status == STATUS_PAID
    assert h.orders.get(oid).payment_reference == "456789012", "کدِ تراکنش روی سفارش می‌شینه"
    assert h.products.get(h.pid).stock_quantity == 5
    assert h.flow.sessions.get("telegram", "1") is None


def test_the_owner_is_alarm_twice_and_can_confirm_afterwards(h):
    """آلارمِ فوری (hooks.payment_claim) هم موقعِ ادعا و هم موقعِ رسید؛ بعد /confirm مالک کار می‌کند."""
    oid = claim(h)
    assert h.claims[-1][1] == {"kind": "claim"} and h.claims[-1][0].id == oid  # ادعا
    assert any("منتظر تاییدته" in a and f"/confirm {oid}" in a for a in h.owner_alerts)
    h.say(f"واریز {TOMAN} تومان")
    [row] = h.orders.receipts_for(oid)
    assert row["match_state"] == "amount_ok"
    order, payload = h.claims[-1]
    assert (order.id, payload["kind"], payload["state"], payload["receipt_id"]) == (oid, "text", "amount_ok", row["id"])
    assert payload["summary"].startswith(f"مبلغِ {TOMAN:,} ریال")

    delivered = []

    async def deliver(platform, chat_id, text, log_history):
        delivered.append((platform, chat_id, text))
        return True

    h.settings.owner_chats = {"telegram": "900"}
    console = OwnerConsole(lambda: h.settings, h.orders, h.products, deliver, lambda: None)
    replies = []

    async def send(text):
        replies.append(text)

    handled = asyncio.run(console.handle("telegram", "900", f"/confirm {oid}", send))
    assert handled and h.orders.get(oid).status == STATUS_CONFIRMED
    assert replies and "تایید" in replies[-1], replies
    assert h.products.get(h.pid).stock_quantity == 4, "موجودی فقط با تأییدِ مالک کم می‌شه"


def test_a_mismatched_receipt_is_recorded_as_a_warning_not_a_confirmation(h):
    oid = claim(h)
    res = h.say("مبلغ 500,000 ریال واریز شد")
    assert res.consumed
    [row] = h.orders.receipts_for(oid)
    assert row["match_state"] == "amount_mismatch" and row["amount_irr"] == 500_000
    assert h.orders.get(oid).status == STATUS_PAID  # هرگز تأیید نشد
    assert any("نمی‌خونه" in str(c[1].get("summary", "")) or c[1].get("state") == "amount_mismatch" for c in h.claims)


def test_a_receipt_without_any_number_is_stored_with_the_none_state(h):
    oid = claim(h)
    h.say("رسیدِ دست‌نویسِ بانکِ من")
    [row] = h.orders.receipts_for(oid)
    assert row["kind"] == "text" and row["match_state"] == "none" and row["amount_irr"] == 0
    assert h.orders.get(oid).status == STATUS_PAID


def test_amount_check_can_be_turned_off_but_the_receipt_is_still_kept(tmp_path):
    h = Harness(tmp_path, receipt_amount_check=False)
    pid = h.add_product("کالا", AMOUNT, 5)
    oid = h.card_order(pid)
    h.tap(f"c:paid:{oid}")
    h.say("مبلغ 500,000 ریال")
    [row] = h.orders.receipts_for(oid)
    assert row["match_state"] == "none" and str(AMOUNT) not in str(row["amount_irr"])
    assert h.orders.get(oid).status == STATUS_PAID


def test_photo_receipt_is_saved_through_the_attachment_hook_and_stays_unconfirmed(h):
    oid = claim(h)
    h.attachment_paths = ["/data/receipts/receipt-7.jpg"]
    res = h.say("", chat="1", attachment={"kind": "photo", "file_id": "ABC123", "size": 120, "mime": "image/jpeg"})
    assert res.consumed and "عکسِ رسید" in texts(res)
    assert h.saved_attachments == [("telegram", "1", {"kind": "photo", "file_id": "ABC123", "size": 120, "mime": "image/jpeg"})]
    [row] = h.orders.receipts_for(oid)
    assert row["kind"] == "image" and row["file_path"] == "/data/receipts/receipt-7.jpg"
    assert row["match_state"] == "none" and row["body"] == ""
    assert h.orders.get(oid).status == STATUS_PAID
    assert h.claims[-1][1]["kind"] == "image" and h.claims[-1][1]["file_path"] == "/data/receipts/receipt-7.jpg"
    assert h.flow.sessions.get("telegram", "1") is None


def test_a_photo_that_could_not_be_downloaded_does_not_crash_or_record_anything(h):
    oid = claim(h)
    h.attachment_paths = []  # هوکِ دانلود مسیری برنمی‌گرداند (تلگرام جواب نداد)
    res = h.say("", chat="1", attachment={"kind": "photo", "file_id": "ABC", "size": 1, "mime": "image/jpeg"})
    assert res.consumed is False
    assert h.orders.receipts_for(oid) == []
    assert h.orders.get(oid).status == STATUS_PAID
    assert h.flow.sessions.get("telegram", "1") is None
    assert h.claims[-1][1] == {"kind": "claim"}  # چیزی جز ادعا ثبت نشد


@pytest.mark.parametrize("text", ["🛍 محصولات", "🧺 سبد خرید", "🙋 ارتباط با پشتیبانی", "/start", "/orders", "/menu"])
def test_a_menu_button_instead_of_a_receipt_clears_the_session_and_falls_through(h, text):
    """مشتری به‌جای رسید دکمه‌ی منو را زد: نباید داخلِ مرحله گیر کند."""
    oid = claim(h)
    res = h.say(text)
    assert res.consumed is False, (text, texts(res))  # پیام به جریانِ عادی (پایپ‌لاین/AI) می‌ره
    assert h.flow.sessions.get("telegram", "1") is None, text
    assert h.orders.receipts_for(oid) == [], text
    assert h.orders.get(oid).status == STATUS_PAID, text
    assert h.say("/menu").consumed  # منو دوباره عادی کار می‌کند
    assert h.flow.carts.get("telegram", "1") == []


def test_the_orders_button_instead_of_a_receipt_is_not_swallowed_as_a_receipt(h):
    oid = claim(h)
    res = h.say("📦 سفارش\u200cهای من")  # همان چیزی که تلگرام برای دکمه‌ی کیبورد می‌فرستد
    assert res.consumed is False
    assert h.flow.sessions.get("telegram", "1") is None
    assert h.orders.receipts_for(oid) == []


def test_a_receipt_for_another_customer_is_refused(h):
    oid = claim(h)
    res = h.say(f"واریز {AMOUNT} ریال", chat="2")  # نشستِ چت ۲ نیست ⇒ چتِ دیگری حتی اگر عدد بفرستد
    assert res.consumed is False and h.orders.receipts_for(oid) == []


def test_claim_is_only_possible_once_and_the_second_tap_is_inert(h):
    oid = claim(h)
    h.say(f"واریز {AMOUNT} ریال")
    assert h.tap(f"c:paid:{oid}").answer, "«پرداخت کردم» روی سفارشِ پرداخت‌شده رد می‌شه"
    assert len(h.claims) == 2  # ادعا + رسید؛ چیزِ سومی اضافه نشد


def test_the_receipt_ask_can_be_turned_off_back_to_the_reference_step(tmp_path):
    h = Harness(tmp_path, receipt_check_enabled=False)
    pid = h.add_product("کالا", AMOUNT, 5)
    oid = h.card_order(pid)
    res = h.tap(f"c:paid:{oid}")
    assert "رسید" not in texts(res) and h.flow.sessions.get("telegram", "1").step == "ref"
    h.say("پیگیری 456789012")
    assert h.orders.get(oid).payment_reference == "پیگیری 456789012"
    assert h.orders.receipts_for(oid) == []


# ============================================ یک تراکنش = یک سفارش (ضدِ «یک رسید، دو سفارش» ====

def test_one_gateway_charge_id_cannot_mark_two_orders_paid(h):
    """شناسهٔ یکتای تراکنش در *دیتابیس* ادعا می‌شه، پس یک واریز دو سفارش را پرداخت نمی‌کند."""
    first = h.card_order(h.pid, chat="2")
    second = h.card_order(h.pid, chat="3")
    assert h.payments.finalize_online_payment(first, METHOD_BALE_PAY, "charge-1") is not None
    assert h.orders.get(first).status == STATUS_CONFIRMED, "بله‌پیِ تأییدشده + auto_confirm = تأییدِ خودکار"
    assert h.orders.claim_payment_charge("charge-1", second) is False
    assert h.payments.finalize_online_payment(second, METHOD_BALE_PAY, "charge-1") is None
    assert h.orders.get(second).status == STATUS_PENDING_PAYMENT, "یک تراکنش، دو سفارش ⇒ دومی پرداخت نمی‌شه"
    assert h.orders.charge_owner("charge-1") == first
    assert h.orders.find_paid_by_reference("charge-1") == first
    assert h.orders.claim_payment_charge("", second) is False  # شناسهٔ خالی هرگز ادعا نمی‌شه
    assert h.orders.claim_payment_charge("charge-2", second) is True
    assert h.orders.claim_payment_charge("charge-2", first) is False
    assert h.products.get(h.pid).stock_quantity == 4, "موجودی فقط به اندازهٔ همان یک سفارشِ تأییدشده کم شده"


def test_a_second_receipt_with_the_same_trace_shouts_instead_of_silently_passing(h):
    """«یک رسید، دو سفارش» در کارت‌به‌کارت: برنامه تأیید یا رد نمی‌کند (تصمیم با مالک است)
    ولی باید همان لحظه بگوید همین کدِ رهگیری روی سفارشِ دیگری هم ثبت شده است."""
    from app.core.owner_console import build_payment_claim_alert

    first = claim(h)
    h.say(f"واریز {AMOUNT} ریال — کد پیگیری 987654321")
    assert h.claims and h.claims[-1][1].get("duplicate_of", 0) == 0

    second_chat = h.card_order(h.pid, chat="2")
    h.tap(f"c:paid:{second_chat}", chat="2")
    h.say(f"واریز {AMOUNT} ریال — کد پیگیری 987654321", chat="2")
    payload = h.claims[-1][1]
    assert payload["duplicate_of"] == first, payload
    alert = build_payment_claim_alert(h.orders.get(second_chat), payload)
    assert f"#{first}" in alert and "دو واریز" in alert
    assert h.orders.get(second_chat).status == STATUS_PAID, "ثبت می‌شه؛ فقط بی‌صدا رد نمی‌شه"
    assert h.orders.get(first).payment_reference == "987654321", "سفارشِ اولِ خودی overwrite نمی‌شه"


def test_mark_paid_with_no_reference_keeps_the_trace_already_on_file(h):
    """رسید زودتر از دکمه ثبت شده باشد؛ «پرداخت کردم» نباید کدِ رهگیریِ موجود را پاک کند،
    ولی یک شناسهٔ تازه (درگاه) جایگزین می‌شه."""
    oid = h.card_order(h.pid)
    assert h.orders.set_reference(oid, "555000111") is True
    h.orders.mark_paid(oid, METHOD_CARD_TO_CARD)
    assert h.orders.get(oid).status == STATUS_PAID
    assert h.orders.get(oid).payment_reference == "555000111", "پاک‌شدنِ بی‌دلیلِ کدِ رهگیری ممنوع"

    other = h.card_order(h.pid, chat="2")
    assert h.orders.set_reference(other, "121212121") is True
    h.orders.mark_paid(other, METHOD_BALE_PAY, "charge-9")  # درگاه همیشه شناسه دارد ⇒ جایگزین می‌شه
    assert h.orders.get(other).payment_reference == "charge-9"


def test_a_receipt_text_cannot_replay_a_gateway_charge(h):
    """متنِ رسید (ادعایِ مشتری) هرگز تراکنشِ یک سفارشِ دیگر را پرداخت‌شده نمی‌کند:
    مسیرِ رسید فقط ``set_reference`` می‌زند و ``payment_reference`` ستونِ یکتا نیست، پس
    ضامنِ واقعی همان ``claim_payment_charge`` است — همان‌جا که پولِ درگاه می‌آید."""
    oid = claim(h)
    h.say(f"واریز {AMOUNT} ریال — کد پیگیری 456789012")
    assert h.orders.get(oid).payment_reference == "456789012"
    assert h.orders.claim_payment_charge("456789012", oid) is True  # ادعایِ همینِ رسید، یک‌بار
    other = h.card_order(h.pid, chat="2")
    assert h.orders.claim_payment_charge("456789012", other) is False
    assert h.orders.get(other).status == STATUS_PENDING_PAYMENT
    assert h.payments.finalize_online_payment(other, METHOD_BALE_PAY, "456789012") is None
