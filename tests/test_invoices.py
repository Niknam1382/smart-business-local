"""N19: فاکتور — snapshotِ تغییرناپذیر، شماره‌گذاریِ اتمیکِ بی‌شکاف (threads)، ریاضیِ مجموع، برگشتی، ناشناس‌سازی."""

import sqlite3
import threading
from types import SimpleNamespace

import pytest

from app.core import invoices, jalali
from app.core.invoices import InvoiceError, InvoiceStore, compute_totals
from tests.test_finance import Rig

NOW = jalali.jalali_day_start_ts(1405, 3, 10) + 3600


def S(**kw):
    base = dict(invoice_seller_name="فروشگاه نمونه", invoice_number_prefix="F", invoice_number_start=1, invoice_number_use_year=True,
                invoice_vat_enabled=False, invoice_vat_rate_bp=1000, invoice_color="#1F6FEB", invoice_paper="A4", invoice_digits="fa")
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def rig(tmp_path):
    r = Rig(tmp_path)
    r.inv = InvoiceStore(r.orders)
    return r


def line(total, qty=1):
    return {"name": "x", "qty": qty, "unit_irr": total // qty, "total_irr": total}


@pytest.mark.parametrize("lines,total,disc,vat,bp,expect", [
    ([line(100_000)], 100_000, 0, False, 0, (100_000, 0, 0, 0)),
    ([line(100_000), line(50_000)], 135_000, 15_000, False, 0, (150_000, 15_000, 0, 0)),
    ([line(100_000)], 100_000, 0, True, 1000, (100_000, 0, 0, 9_091)),  # ۱۰۰٬۰۰۰ − round(100000/1.1)=90909
    ([line(1)], 1, 0, True, 1000, (1, 0, 0, 0)),  # گردکردنِ نیم‌به‌بالا روی مبلغِ کوچک
    ([line(100_000)], 110_000, 0, False, 0, (100_000, 0, 10_000, 0)),  # پرداختیِ بیشتر ⇒ ارسال/سایر
    ([line(100_000)], 80_000, 5_000, False, 0, (100_000, 20_000, 0, 0)),  # پرداختیِ کمتر از اقلام−تخفیف ⇒ تخفیف اصلاح می‌شود
    ([line(100_000)], 100_000, 999_999, False, 0, (100_000, 0, 0, 0)),  # تخفیفِ بی‌معنی نادیده گرفته می‌شود
    ([line(33_333, 3)], 33_333, 0, True, 900, (33_333, 0, 0, 2_752)),
])
def test_totals_identity_and_vat(lines, total, disc, vat, bp, expect):
    t = compute_totals(lines, total, disc, vat, bp)
    assert (t["subtotal_irr"], t["discount_irr"], t["shipping_irr"], t["tax_irr"]) == expect
    assert t["subtotal_irr"] - t["discount_irr"] + t["shipping_irr"] == t["total_irr"] == total  # جمعِ سطرها = جمعِ کل
    assert 0 <= t["tax_irr"] <= total


def test_vat_rate_out_of_range_ignored():
    assert compute_totals([line(1000)], 1000, 0, True, 99_999)["tax_irr"] == 0
    assert compute_totals([line(1000)], 1000, 0, True, 0)["tax_irr"] == 0


def test_issue_sale_snapshot_idempotent_and_number_format(rig):
    pid = rig.product("کفش", 100_000)
    oid = rig.confirmed([(pid, 2)], name="علی رضایی", customer_phone="09120000000", customer_address="تهران")
    order = rig.orders.get(oid)
    inv = rig.inv.issue_sale(order, S(), now=NOW)
    assert inv.number == "F140500001" and inv.kind == "sale" and inv.total_irr == 200_000 and inv.pay_status == "paid"
    assert inv.buyer["name"] == "علی رضایی" and inv.lines[0]["qty"] == 2 and inv.seller["name"] == "فروشگاه نمونه"
    assert rig.inv.issue_sale(order, S(), now=NOW + 5).id == inv.id  # idempotent
    # تغییرِ بعدیِ قیمت/تنظیمات/خریدار فاکتور را عوض نمی‌کند
    rig.orders.connection().execute("UPDATE order_items SET unit_price_irr=1, product_name='جدید'")
    rig.orders.connection().execute("UPDATE orders SET customer_name='کسِ دیگر'")
    rig.orders.connection().commit()
    again = rig.inv.get(inv.id)
    assert again.lines == inv.lines and again.buyer["name"] == "علی رضایی" and again.total_irr == 200_000


def test_unconfirmed_and_free_orders_rejected(rig):
    pid = rig.product()
    pending = rig.orders.get(rig.orders.create("telegram", "7", [(pid, 1)]))
    with pytest.raises(InvoiceError):
        rig.inv.issue_sale(pending, S())
    free = rig.confirmed([(rig.product("f", 0), 1)])
    with pytest.raises(InvoiceError):
        rig.inv.issue_sale(rig.orders.get(free), S())
    assert rig.inv.list() == []


@pytest.mark.parametrize("sql", [
    "UPDATE invoices SET total_irr=1", "UPDATE invoices SET lines_json='[]'", "UPDATE invoices SET number='X'",
    "UPDATE invoices SET seller_json='{}'", "UPDATE invoices SET issued_ts=1", "UPDATE invoices SET tax_irr=5",
    "UPDATE invoices SET buyer_json='{\"name\":\"دیگری\"}'", "DELETE FROM invoices",
])
def test_invoice_columns_immutable_by_trigger(rig, sql):
    oid = rig.confirmed([(rig.product(), 1)])
    rig.inv.issue_sale(rig.orders.get(oid), S(), now=NOW)
    with pytest.raises(sqlite3.DatabaseError):
        rig.orders.connection().execute(sql)


def test_numbering_gap_free_unique_under_threads(rig):
    pid = rig.product(stock=1000)
    oids = [rig.confirmed([(pid, 1)], chat=str(i)) for i in range(24)]
    orders = [rig.orders.get(o) for o in oids]
    errors, numbers = [], []
    lock = threading.Lock()

    def work(chunk):
        try:
            for o in chunk:
                inv = rig.inv.issue_sale(o, S(), now=NOW)
                with lock:
                    numbers.append(inv.number)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(orders[i::6],)) for i in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and len(set(numbers)) == 24
    assert sorted(int(n[-5:]) for n in numbers) == list(range(1, 25))  # بی‌شکاف


def test_same_order_issued_concurrently_gives_single_invoice_no_gap(rig):
    oid = rig.confirmed([(rig.product(), 1)])
    order = rig.orders.get(oid)
    out = []
    ts = [threading.Thread(target=lambda: out.append(rig.inv.issue_sale(order, S(), now=NOW).number)) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert set(out) == {"F140500001"} and len(rig.inv.list()) == 1
    nxt = rig.confirmed([(rig.product("b"), 1)], chat="2")
    assert rig.inv.issue_sale(rig.orders.get(nxt), S(), now=NOW).number == "F140500002"  # شماره‌ی مصرف‌نشده نداریم


def test_series_per_year_start_number_prefix_and_no_year(rig):
    pid = rig.product(stock=100)
    mk = lambda c: rig.orders.get(rig.confirmed([(pid, 1)], chat=c))  # noqa: E731
    a = rig.inv.issue_sale(mk("1"), S(invoice_number_start=500, invoice_number_prefix="a-b!"), now=NOW)
    b = rig.inv.issue_sale(mk("2"), S(invoice_number_start=500, invoice_number_prefix="a-b!"), now=NOW)
    c = rig.inv.issue_sale(mk("3"), S(invoice_number_start=500), now=jalali.jalali_day_start_ts(1406, 1, 5))
    d = rig.inv.issue_sale(mk("4"), S(invoice_number_use_year=False), now=NOW)
    assert (a.number, b.number, c.number, d.number) == ("ab140500500", "ab140500501", "F140600500", "F00001")
    assert rig.inv.get_by_number("F00001").id == d.id and rig.inv.for_order(d.order_id).id == d.id


def test_credit_note_once_copies_snapshot(rig):
    oid = rig.confirmed([(rig.product(), 3)])
    sale = rig.inv.issue_sale(rig.orders.get(oid), S(invoice_vat_enabled=True), now=NOW)
    cn = rig.inv.issue_credit_note(sale.id, S(), now=NOW + 60)
    assert cn.kind == "credit_note" and cn.ref_invoice_id == sale.id and cn.number == "CNF140500001"
    assert (cn.total_irr, cn.tax_irr, cn.lines, cn.buyer) == (sale.total_irr, sale.tax_irr, sale.lines, sale.buyer)
    assert rig.inv.return_note_for(sale.id).id == cn.id
    with pytest.raises(InvoiceError):
        rig.inv.issue_credit_note(sale.id, S())
    with pytest.raises(InvoiceError):
        rig.inv.issue_credit_note(cn.id, S())  # برگشتی روی برگشتی ممنوع
    with pytest.raises(InvoiceError):
        rig.inv.issue_credit_note(999, S())
    assert rig.inv.issue_sale(rig.orders.get(oid), S()).id == sale.id  # فروش یکتا می‌ماند


def test_anonymize_keeps_amounts_and_returns_numbers(rig):
    pid = rig.product()
    o1 = rig.confirmed([(pid, 1)], chat="10", name="مریم")
    o2 = rig.confirmed([(pid, 1)], chat="11", name="رضا")
    i1 = rig.inv.issue_sale(rig.orders.get(o1), S(), now=NOW)
    rig.inv.issue_sale(rig.orders.get(o2), S(), now=NOW)
    gone = []
    rig.orders.add_anonymize_listener(gone.extend)
    rig.orders.anonymize_chat("telegram", "10")
    after, other = rig.inv.get(i1.id), rig.inv.for_order(o2)
    assert after.anonymized and after.buyer["name"] == invoices.ANON_NAME and after.buyer["phone"] == ""
    assert (after.total_irr, after.lines) == (i1.total_irr, i1.lines) and not other.anonymized and other.buyer["name"] == "رضا"
    assert gone == [i1.number]
    with pytest.raises(sqlite3.DatabaseError):  # ناشناس‌سازی ≠ مجوزِ تغییرِ دلخواه
        rig.orders.connection().execute("UPDATE invoices SET total_irr=1 WHERE id=?", (i1.id,))


def test_record_send_tracks_attempts_and_list_filters(rig):
    oid = rig.confirmed([(rig.product(), 1)], name="سارا")
    inv = rig.inv.issue_sale(rig.orders.get(oid), S(), now=NOW)
    rig.inv.record_send(inv.id, "customer", False, "x" * 500)
    st = rig.inv.record_send(inv.id, "customer", True)
    assert st["ok"] and st["attempts"] == 2 and st["error"] == ""
    assert len(rig.inv.get(inv.id).sent["customer"]) == 4
    assert [i.id for i in rig.inv.list("سارا")] == [inv.id] and rig.inv.list("نیست") == []
    assert [i.id for i in rig.inv.list(f"#{oid}")] == [inv.id] and rig.inv.list(kind="credit_note") == []
    assert len(rig.inv.list("%")) == 1  # «%» جستجوی همه‌چیز نیست (حذف می‌شود ⇒ رشته‌ی خالی ⇒ همه)
    assert rig.inv.sale_missing_for_confirmed() == []
    o2 = rig.confirmed([(rig.product("z"), 1)], chat="3")
    assert rig.inv.sale_missing_for_confirmed() == [o2]


def test_credit_note_posts_refund_and_optionally_returns_cogs(tmp_path):
    from app.core.finance import FinanceStore
    from app.core.invoice_service import InvoiceService

    r = Rig(tmp_path)
    pid = r.product("کفش", 100_000, 10, cost=60_000)
    oid = r.confirmed([(pid, 2)])
    fin = FinanceStore(r.orders, r.products)
    fin.post_order(r.orders.get(oid), {})
    svc = InvoiceService(r.orders, lambda: S(), directory=lambda: tmp_path / "inv")
    svc.finance = fin
    sale = svc.issue(r.orders.get(oid))
    before = fin.report(0, 2**40)
    assert (before.sales_net, before.cogs, before.refunds, before.net_profit) == (200_000, 120_000, 0, 80_000)
    cn = svc.credit_note(sale.id, cogs_back=True)
    after = fin.report(0, 2**40)
    assert (after.sales_net, after.refunds, after.cogs, after.net_profit) == (200_000, 200_000, 0, 0)  # برگشتِ کامل ⇒ سود صفر
    assert fin.post_credit_note(cn, cogs_back=True) == 0  # idempotent
    with pytest.raises(InvoiceError):
        svc.credit_note(sale.id)
    # بدونِ برگشتِ کالا: بهای کالا می‌ماند (ضرر)
    oid2 = r.confirmed([(pid, 1)], chat="2")
    fin.post_order(r.orders.get(oid2), {})
    s2 = svc.issue(r.orders.get(oid2))
    svc.credit_note(s2.id, cogs_back=False)
    assert fin.report(0, 2**40).cogs == 60_000
