"""۱٫۲٫۰ — وضعیتِ «بسته‌شده» (closed) نباید فروشِ معتبر را از آمار/دفتر/سقفِ تخفیف ناپدید کند."""

import pytest

from app.core.finance import FinanceStore
from app.core.orders import OrderStore
from app.core.products import ProductStore


class Rig:
    def __init__(self, tmp_path):
        self.products = ProductStore(tmp_path / "products.db")
        self.orders = OrderStore(tmp_path / "orders.db", product_store=self.products)
        self.fin = FinanceStore(self.orders, self.products)

    def closed_order(self, chat="1"):
        pid = self.products.add("کفش", 100_000, 50)
        oid = self.orders.create("telegram", chat, [(pid, 1)], payment_method="card_to_card", customer_name="علی")
        self.orders.mark_paid(oid, "card_to_card")
        self.orders.confirm(oid)
        self.orders.close(oid, by="test")
        return oid


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def test_a_closed_order_is_still_posted_to_the_ledger_by_the_repair_pass(rig):
    oid = rig.closed_order()
    assert rig.orders.get(oid).status == "closed"
    assert rig.fin.post_missing() == 1  # قبلاً: ۰ — فروشِ بسته‌شده هرگز در دفتر نمی‌آمد
    assert rig.fin.post_missing() == 0  # idempotent
    rows = rig.orders.connection().execute("SELECT auto_key FROM ledger_entries WHERE ref_type='order' AND ref_id=?", (oid,)).fetchall()
    assert "sale" in {r["auto_key"] for r in rows}


def test_closing_after_posting_keeps_the_sale_in_the_report(rig):
    pid = rig.products.add("کفش", 100_000, 50)
    oid = rig.orders.create("telegram", "9", [(pid, 1)], payment_method="card_to_card", customer_name="علی")
    rig.orders.mark_paid(oid, "card_to_card")
    rig.orders.confirm(oid)
    rig.fin.post_order(rig.orders.get(oid))
    before = rig.fin.report(0, 2**40)
    rig.orders.close(oid, by="test")
    rig.fin.post_missing()
    after = rig.fin.report(0, 2**40)
    assert after.net_profit == before.net_profit and after.net_profit != 0
