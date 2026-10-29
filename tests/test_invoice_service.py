"""N19: سرویسِ فاکتور — PDF قطعی، ارسالِ idempotent، retry/backoff، شکست ⇒ attention + فاکتورِ متنی، بلاک/دسترس‌ناپذیر، مالکِ سفارش."""

import asyncio
import hashlib
import pytest

from app.core import invoice_pdf
from app.core.invoice_service import MAX_AUTO_ATTEMPTS, InvoiceService, invoice_text
from tests.test_finance import Rig
from tests.test_invoices import NOW, S

pypdf = pytest.importorskip("pypdf")


class Fx:
    def __init__(self, tmp_path, **settings):
        self.rig = Rig(tmp_path)
        self.settings = S(invoice_auto_send="after_confirm", invoice_send_owner_copy=False, **settings)
        self.docs, self.texts, self.att, self.cleared, self.unreach, self.sleeps = [], [], [], [], [], []
        self.fail = []  # صفِ خطاهایی که sender پرتاب می‌کند
        self.block = ""
        self.now = float(NOW)

        async def doc(platform, chat, path, caption):
            if self.fail:
                raise self.fail.pop(0)
            self.docs.append((platform, chat, path, caption))

        async def text(platform, chat, body):
            self.texts.append((platform, chat, body))

        async def sleep(s):
            self.sleeps.append(s)

        self.svc = InvoiceService(
            self.rig.orders, lambda: self.settings, doc_sender=doc, text_sender=text, can_send=lambda p, c: self.block,
            on_unreachable=lambda p, c, e: self.unreach.append((p, c)), attention_add=lambda *a: self.att.append(a),
            attention_clear=lambda *a: self.cleared.append(a), owner_chats=lambda: {"telegram": "900"},
            directory=lambda: tmp_path / "inv", sleep=sleep, clock=lambda: self.now,
        )

    def order(self, chat="1", name="علی", price=100_000):
        pid = self.rig.product(f"کالا{chat}", price, 100)
        return self.rig.orders.get(self.rig.confirmed([(pid, 1)], chat=chat, name=name))


@pytest.fixture
def fx(tmp_path):
    return Fx(tmp_path)


def run(coro):
    return asyncio.run(coro)


def test_pdf_valid_deterministic_text_extractable_and_cached(fx):
    inv = fx.svc.issue(fx.order(name="علی رضایی"))
    path = fx.svc.path_of(inv)
    data = path.read_bytes()
    assert data.startswith(b"%PDF-") and fx.svc.store.get(inv.id).pdf_sha256 == hashlib.sha256(data).hexdigest()
    text = "".join(p.extract_text() or "" for p in pypdf.PdfReader(str(path)).pages)
    # pypdf ترتیبِ بصریِ راست‌به‌چپ را برعکس/ناقص استخراج می‌کنه؛ فارسی/ارقامِ فارسی (هر دو ترتیب) و عنوانِ فایل را می‌سنجیم
    assert "فاکتور فروش" in text and "فروشگاه نمونه" in text and ("۱۰۰٬۰۰۰" in text or "۰۰۰٬۰۰۱" in text)
    assert pypdf.PdfReader(str(path)).metadata.title == inv.number
    path.unlink()
    again = fx.svc.ensure_pdf(inv)  # بازسازی از snapshot ⇒ بایتِ یکسان
    assert again.read_bytes() == data


def test_pdf_sanitizes_hostile_text_and_a5_and_digits(fx):
    fx.settings.invoice_seller_name = "فروشگاه 😀\u202e"
    fx.settings.invoice_paper, fx.settings.invoice_digits = "A5", "en"
    inv = fx.svc.issue(fx.order(name="<b>x</b>\u202e😀 \x00"))
    reader = pypdf.PdfReader(str(fx.svc.path_of(inv)))
    w, h = float(reader.pages[0].mediabox.width), float(reader.pages[0].mediabox.height)
    assert abs(w - 419.5) < 2 and abs(h - 595.3) < 2  # A5
    assert invoice_pdf.clean("a\u202eb😀\x00c") == "a b c"
    assert invoice_pdf.money(1250000, "en") == "1,250,000" and invoice_pdf.money(1250000) == "۱٬۲۵۰٬۰۰۰"


def test_credit_note_pdf_and_text_fallback(fx):
    sale = fx.svc.issue(fx.order())
    cn = fx.svc.credit_note(sale.id)
    assert fx.svc.path_of(cn).is_file() and "برگشتی" in invoice_text(cn) and cn.number != sale.number and cn.number.startswith("CN")


def test_send_once_then_skipped_unless_force(fx):
    inv = fx.svc.issue(fx.order())
    assert run(fx.svc.send_customer(inv.id)) == "sent"
    assert run(fx.svc.send_customer(inv.id)) == "skipped:already"
    assert len(fx.docs) == 1 and fx.docs[0][:2] == ("telegram", "1") and inv.number in fx.docs[0][3]
    assert run(fx.svc.send_customer(inv.id, force=True)) == "sent" and len(fx.docs) == 2  # «ارسالِ دوباره»
    assert fx.cleared  # «نیاز به توجه» پاک شد


def test_concurrent_sends_deliver_once(fx):
    inv = fx.svc.issue(fx.order())

    async def many():
        return await asyncio.gather(*[fx.svc.send_customer(inv.id) for _ in range(6)])

    out = run(many())
    assert out.count("sent") == 1 and len(fx.docs) == 1


def test_retry_with_backoff_then_success(fx):
    inv = fx.svc.issue(fx.order())
    fx.fail = [ConnectionError("net"), TimeoutError("slow")]
    assert run(fx.svc.send_customer(inv.id)) == "sent"
    assert fx.sleeps == [1.0, 4.0] and len(fx.docs) == 1 and fx.att == []
    assert fx.svc.store.get(inv.id).sent["customer"]["ok"] is True


def test_permanent_failure_alerts_once_and_sends_text_fallback_once(fx):
    inv = fx.svc.issue(fx.order())
    fx.fail = [ConnectionError("x")] * 3
    out = run(fx.svc.send_customer(inv.id))
    assert out.startswith("failed:") and fx.docs == [] and len(fx.att) == 1 and fx.att[0][0] == "invoice_send"
    assert len(fx.texts) == 1 and inv.number in fx.texts[0][2]
    fx.fail = [ConnectionError("x")] * 3
    run(fx.svc.send_customer(inv.id))
    assert len(fx.texts) == 1  # فاکتورِ متنی فقط یک‌بار
    st = fx.svc.store.get(inv.id).sent["customer"]
    assert st["ok"] is False and st["attempts"] == 2 and "ConnectionError" in st["error"]


def test_blocked_unreachable_and_forgotten_never_sent(fx):
    o = fx.order()
    inv = fx.svc.issue(o)
    fx.block = "blocked"
    assert run(fx.svc.send_customer(inv.id)) == "skipped:blocked" and fx.docs == [] and fx.att == []
    fx.block = ""
    fx.fail = [Exception("Forbidden: bot was blocked by the user")]
    out = run(fx.svc.send_customer(inv.id))
    assert out.startswith("failed:") and fx.sleeps == [] and fx.unreach == [("telegram", "1")]  # قطعی ⇒ بدونِ retry
    fx.rig.orders.anonymize_chat("telegram", "1")
    assert run(fx.svc.send_customer(inv.id, force=True)) == "skipped:forgotten"
    assert not fx.svc.path_of(inv).exists()  # PDF با /forget پاک شد


def test_customer_button_only_for_own_confirmed_order_and_cooldown(fx):
    o = fx.order(chat="5")
    other = fx.order(chat="6")
    assert run(fx.svc.send_for_customer_button("telegram", "6", o.id)) == "unavailable"  # سفارشِ دیگری
    assert run(fx.svc.send_for_customer_button("bale", "5", o.id)) == "unavailable"  # پلتفرمِ دیگر
    pending = fx.rig.orders.create("telegram", "5", [(fx.rig.product("p", 10), 1)])
    assert run(fx.svc.send_for_customer_button("telegram", "5", pending)) == "unavailable"
    assert run(fx.svc.send_for_customer_button("telegram", "5", o.id)) == "sent" and len(fx.docs) == 1
    assert run(fx.svc.send_for_customer_button("telegram", "5", o.id)) == "sent" and len(fx.docs) == 1  # دابل‌تپ
    fx.now += 60
    assert run(fx.svc.send_for_customer_button("telegram", "5", o.id)) == "sent" and len(fx.docs) == 2
    assert other.id and len(fx.docs) == 2


def test_process_pending_issues_sends_backs_off_and_caps(fx):
    o = fx.order()  # فاکتور هنوز صادر نشده
    assert run(fx.svc.process_pending()) == 1 and len(fx.docs) == 1
    assert run(fx.svc.process_pending()) == 0 and len(fx.docs) == 1  # دوباره نمی‌فرستد
    fx2 = fx.order("2")
    fx.fail = [ConnectionError("x")] * 3
    assert run(fx.svc.process_pending()) == 1 and fx.docs[-1][1] != "2"
    assert run(fx.svc.process_pending()) == 0  # backoff: هنوز زود است
    fx.now += 130
    assert run(fx.svc.process_pending()) == 1 and fx.docs[-1][1] == "2"
    assert o.id and fx2.id


def test_process_pending_respects_off_and_attempt_cap_and_owner_copy(fx):
    fx.order()
    fx.settings.invoice_auto_send = "off"
    assert run(fx.svc.process_pending()) == 0 and fx.docs == []
    fx.settings.invoice_auto_send, fx.settings.invoice_send_owner_copy = "after_confirm", True
    assert run(fx.svc.process_pending()) == 1
    assert [d[:2] for d in fx.docs] == [("telegram", "1"), ("telegram", "900")]  # نسخه‌ی مالک
    assert run(fx.svc.process_pending()) == 0 and len(fx.docs) == 2


def test_attempt_cap_stops_automatic_but_manual_resend_works(fx):
    o = fx.order("7")
    inv = fx.svc.issue(o)
    for _ in range(MAX_AUTO_ATTEMPTS):
        fx.svc.store.record_send(inv.id, "customer", False, "x")
    fx.now += 10**7
    assert run(fx.svc.process_pending()) == 0 and fx.docs == []
    assert run(fx.svc.send_customer(inv.id, force=True)) == "sent" and len(fx.docs) == 1
