"""N19: دفترِ مالی — append-only، ثبتِ خودکارِ idempotent، ترمیم، COGS/کارمزد، گزارش در برابرِ داده‌ی معلوم، CSV امن."""

import sqlite3
import time

import pytest

from app.core import finance, jalali
from app.core.finance import FinanceError, FinanceStore
from app.core.orders import OrderStore
from app.core.products import ProductStore


class Rig:
    def __init__(self, tmp_path):
        self.products = ProductStore(tmp_path / "products.db")
        self.orders = OrderStore(tmp_path / "orders.db", product_store=self.products)
        self.fin = FinanceStore(self.orders, self.products)

    def product(self, name="کفش", price=100_000, stock=50, cost=0):
        pid = self.products.add(name, price, stock)
        if cost:
            self.products.set_cost(pid, cost)
        return pid

    def confirmed(self, items, method="card_to_card", chat="1", name="علی", **kw):
        oid = self.orders.create("telegram", chat, items, payment_method=method, customer_name=name, **kw)
        self.orders.mark_paid(oid, method)
        self.orders.confirm(oid)
        return oid


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def _all(rig, where=""):
    return rig.orders.connection().execute(f"SELECT * FROM ledger_entries {where} ORDER BY id").fetchall()


def test_ledger_is_append_only_by_triggers(rig):
    eid = rig.fin.add_entry("expense", 5000, "ads")
    conn = rig.orders.connection()
    for sql in ("UPDATE ledger_entries SET amount_irr=1 WHERE id=?", "UPDATE ledger_entries SET note='x' WHERE id=?",
                "UPDATE ledger_entries SET kind='income' WHERE id=?", "DELETE FROM ledger_entries WHERE id=?"):
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(sql, (eid,))
    assert _all(rig)[0]["amount_irr"] == 5000


def test_reversal_nets_to_zero_and_only_once(rig):
    eid = rig.fin.add_entry("expense", 7000, "rent")
    rid = rig.fin.reverse(eid, note="اشتباه")
    row = rig.fin.get(eid)
    assert row.reversed_by_id == rid and rig.fin.get(rid).reverses_id == eid
    rep = rig.fin.report(0, 2**40)
    assert rep.expenses == 0 and rep.net_profit == 0
    with pytest.raises(FinanceError):
        rig.fin.reverse(eid)
    with pytest.raises(FinanceError):
        rig.fin.reverse(rid)
    with pytest.raises(FinanceError):
        rig.fin.reverse(999)


@pytest.mark.parametrize("kw", [
    dict(kind="expense", amount_irr=0), dict(kind="expense", amount_irr=-5), dict(kind="expense", amount_irr=1.5),
    dict(kind="expense", amount_irr=True), dict(kind="expense", amount_irr=finance.MAX_AMOUNT + 1), dict(kind="refund", amount_irr=5),
    dict(kind="cogs", amount_irr=5), dict(kind="expense", amount_irr=5, account="bitcoin"),
    dict(kind="expense", amount_irr=5, category_key="sales"), dict(kind="income", amount_irr=5, category_key="ads"),
    dict(kind="expense", amount_irr=5, category_key="nope"), dict(kind="expense", amount_irr=5, ts=1),
    dict(kind="expense", amount_irr=5, ts=int(time.time()) + 10 * 86400),
])
def test_manual_entry_validation(rig, kw):
    kw.setdefault("category_key", "ads")
    with pytest.raises(FinanceError):
        rig.fin.add_entry(**kw)
    assert _all(rig) == []


def test_manual_note_sanitized(rig):
    eid = rig.fin.add_entry("income", 10, "other_income", note="=cmd|' /C calc'!A0\u202e" + "x" * 500)
    note = rig.fin.get(eid).note
    assert len(note) == finance.MAX_NOTE and "\u202e" not in note


def test_post_order_creates_expected_rows_once(rig):
    a, b = rig.product("الف", 100_000, cost=60_000), rig.product("ب", 50_000, cost=0)
    oid = rig.confirmed([(a, 2), (b, 1)], method="zarinpal")
    order = rig.orders.get(oid)
    fee = {"zarinpal": 150}
    assert rig.fin.post_order(order, fee) == 3
    assert rig.fin.post_order(order, fee) == 0  # idempotent
    rows = {r["auto_key"]: r for r in _all(rig)}
    assert rows["sale"]["amount_irr"] == 250_000 and rows["sale"]["account"] == "zarinpal"
    assert rows["fee"]["amount_irr"] == 3750  # 250000*1.5%
    assert rows["cogs"]["amount_irr"] == 120_000 and "ناقص" in rows["cogs"]["note"]  # قلمِ «ب» بهای ثبت‌شده ندارد
    assert rig.fin.report(0, 2**40).missing_cost_orders == 1


def test_no_cogs_row_when_no_cost_and_missing_flag(rig):
    oid = rig.confirmed([(rig.product(), 1)])
    rig.fin.post_order(rig.orders.get(oid))
    assert [r["auto_key"] for r in _all(rig)] == ["sale"]
    assert rig.fin.report(0, 2**40).missing_cost_orders == 1


def test_unconfirmed_or_free_orders_not_posted(rig):
    pid = rig.product()
    pending = rig.orders.get(rig.orders.create("telegram", "9", [(pid, 1)]))
    assert rig.fin.post_order(pending) == 0
    free = rig.product("رایگان", 0)
    oid = rig.confirmed([(free, 1)])
    assert rig.fin.post_order(rig.orders.get(oid)) == 0 and _all(rig) == []


def test_listener_and_repair_queue(rig):
    pid = rig.product(cost=10_000)
    calls = []
    rig.orders.add_confirm_listener(lambda o: calls.append(o.id))
    rig.orders.add_confirm_listener(lambda o: 1 / 0)  # شنونده‌ی خراب تایید را خراب نمی‌کند
    oid = rig.confirmed([(pid, 1)])
    assert calls == [oid] and rig.orders.get(oid).status == "confirmed"
    assert _all(rig) == []  # قلاب شکسته/نصب‌نشده ⇒ ردیفی نیست
    assert rig.fin.post_missing() == 1 and rig.fin.post_missing() == 0  # ترمیم، سپس idempotent
    assert {r["auto_key"] for r in _all(rig)} == {"sale", "cogs"}


def test_report_matches_known_data(rig):
    a = rig.product("الف", 100_000, cost=40_000)
    rig.confirmed([(a, 3)], method="card_to_card", chat="1")  # ۳۰۰٬۰۰۰
    rig.confirmed([(a, 1)], method="bale_pay", chat="2", name="سارا")  # ۱۰۰٬۰۰۰
    for o in rig.orders.list():
        rig.fin.post_order(rig.orders.get(o.id), {"bale_pay": 200})
    rig.fin.add_entry("expense", 30_000, "ads", account="cash")
    rig.fin.add_entry("income", 5_000, "other_income")
    rep = rig.fin.report(0, 2**40)
    assert (rep.gross_sales, rep.discounts, rep.sales_net, rep.orders_count) == (400_000, 0, 400_000, 2)
    assert rep.other_income == 5_000 and rep.cogs == 160_000
    assert rep.expenses == 30_000 + 2_000  # دستی + کارمزدِ بله‌پی ۲٪ از ۱۰۰٬۰۰۰
    assert rep.gross_profit == 400_000 + 5_000 - 160_000 == 245_000
    assert rep.net_profit == 245_000 - 32_000
    assert rep.by_method == {"card": 300_000, "bale_pay": 100_000, "cash": 5_000}
    assert rep.by_product == [("الف", 4, 400_000)]
    assert dict(rep.by_category) == {"تبلیغات": 30_000, "کارمزدِ درگاه": 2_000}
    assert rep.top_customers[0][3] == 300_000 and rep.top_customers[0][1] == "1"
    assert sum(v for _, v in rep.by_day) == 405_000
    assert rep.inventory_value == (50 - 4) * 40_000


def test_report_uses_discount_from_orders_and_range_filter(rig):
    pid = rig.product("الف", 100_000)
    oid = rig.confirmed([(pid, 2)])
    rig.orders.connection().execute("UPDATE orders SET discount_irr=20000, total_irr=180000, subtotal_irr=200000 WHERE id=?", (oid,))
    rig.orders.connection().commit()
    rig.fin.post_order(rig.orders.get(oid))
    now = int(time.time())
    rep = rig.fin.report(now - 100, now + 100)
    assert (rep.gross_sales, rep.discounts, rep.sales_net) == (200_000, 20_000, 180_000)
    assert rep.gross_sales - rep.discounts == rep.sales_net
    empty = rig.fin.report(0, now - 10_000)
    assert (empty.sales_net, empty.orders_count, empty.net_profit) == (0, 0, 0)


def test_receivables_and_inventory_value(rig):
    pid = rig.product("الف", 100_000, stock=10, cost=1000)
    waiting = rig.orders.create("telegram", "5", [(pid, 1)], payment_method="card_to_card")
    rig.orders.mark_paid(waiting, "card_to_card")
    rig.orders.create("telegram", "6", [(pid, 2)])  # pending (مهلت دارد)
    rep = rig.fin.report(0, 2**40)
    assert rep.receivables_waiting == 100_000 and rep.receivables_pending == 200_000 and rep.inventory_value == 10_000


def test_rounding_helpers():
    assert finance.round_div(5, 2) == 3 and finance.round_div(4, 2) == 2 and finance.round_div(1, 3) == 0 and finance.round_div(2, 3) == 1
    assert finance.bp_of(250_000, 150) == 3750 and finance.bp_of(1, 5000) == 1
    for bad in [(-1, 2), (1, 0)]:
        with pytest.raises(FinanceError):
            finance.round_div(*bad)


def test_csv_export_is_formula_safe(rig):
    rig.fin.add_entry("expense", 5, "ads", note="=HYPERLINK(\"http://x\")")
    rig.fin.add_entry("expense", 6, "ads", note="+1+1")
    rig.fin.add_entry("expense", 7, "ads", note="@SUM(A1)")
    rig.fin.add_entry("expense", 8, "ads", note="-2+3")
    text = rig.fin.export_csv()
    assert text.startswith("\ufeff")
    for line in text.splitlines()[1:]:
        note = line.split(",")[-2] if "HYPERLINK" not in line else "'=HYPERLINK"
        assert not note.startswith(("=", "+", "-", "@"))
    assert FinanceStore.csv_cell("-5") == "-5" and FinanceStore.csv_cell("=1") == "'=1" and FinanceStore.csv_cell("سلام") == "سلام"


def test_categories(rig):
    cid = rig.fin.add_category("  تعمیرات  ", "expense")
    rig.fin.rename_category(cid, "تعمیر و نگهداری")
    assert "تعمیر و نگهداری" in [c["name"] for c in rig.fin.categories("expense")]
    rig.fin.add_entry("expense", 10, next(c["key"] for c in rig.fin.categories() if c["id"] == cid))
    for bad in [("", "expense"), ("x", "cogs"), ("x", "refund")]:
        with pytest.raises(FinanceError):
            rig.fin.add_category(*bad)
    assert rig.fin.report(0, 2**40).by_category == [("تعمیر و نگهداری", 10)]
    assert jalali.format_ts(time.time())  # دفتر به تقویم وصل است
