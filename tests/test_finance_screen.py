"""N19 — صفحه‌ی «مالی و فاکتور» (UI با Page جعلی؛ منطق در test_finance*.py / test_invoices.py)."""

import pytest
from fake_page import FakePage, collect_text, find, fire

from app.core.bot_manager import BotManager
from app.core.conversations import ConversationStore
from app.core.orders import OrderStore
from app.core.products import ProductStore
from app.core.settings import AppSettings
from app.screens import finance as screen


class Rig:
    def __init__(self, tmp_path, lang="fa", shop=True):
        self.products = ProductStore(tmp_path / "p.db")
        self.orders = OrderStore(tmp_path / "o.db", product_store=self.products)
        self.settings = AppSettings(business_mode="store")
        self.manager = BotManager(self.settings, store=ConversationStore(db_path=tmp_path / "c.db"),
                                  product_store=self.products if shop else None, order_store=self.orders if shop else None,
                                  adapter_factories={}, log_dir=tmp_path)
        self.page = FakePage()
        self.lang = lang
        self.control = screen.build(self.page, lang, self.manager, self.settings, self.products)

    def f(self, key):
        return find(self.control, key)

    def text(self, key):
        return collect_text(self.f(key))

    def click(self, key):
        fire(self.f(key), "on_click")

    def type(self, **fields):
        for key, value in fields.items():
            self.f(key).value = value

    def notice(self):
        n = self.f("fn_notice")
        return (n.value, n.color) if n.visible else ("", None)

    def sale(self, price=100_000, qty=2, cost=0, chat="1"):
        pid = self.products.add(f"کالا{chat}", price, 50)
        if cost:
            self.products.set_cost(pid, cost)
        oid = self.orders.create("telegram", chat, [(pid, qty)], payment_method="card_to_card", customer_name="علی رضایی")
        self.orders.mark_paid(oid, "card_to_card")
        self.orders.confirm(oid)
        return oid


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def test_parsers():
    assert screen.parse_percent_bp("۱٫۵") == 150 and screen.parse_percent_bp("10") == 1000 and screen.parse_percent_bp("") == 0 and screen.parse_percent_bp("2.5٪") == 250
    for bad in ["x", "-1", "31", "1.234", "99999"]:
        assert screen.parse_percent_bp(bad) is None
    assert screen.parse_amount("۵۰٬۰۰۰", "toman") == 500_000 and screen.parse_amount("50,000", "irr") == 50_000
    for bad in ["", "0", "abc", "-5", "1.5", "9" * 20]:
        assert screen.parse_amount(bad, "toman") is None and screen.parse_amount(bad, "irr") is None
    a, b = screen.period_range("month", 1_780_000_000)
    assert a < 1_780_000_000 < b and screen.period_range("all") == (0, 2**40)
    t0, t1 = screen.period_range("today", 1_780_000_000)
    assert screen.period_range("7", 1_780_000_000)[0] == t0 - 6 * 86400 and t1 - t0 == 86400
    assert screen.period_range("prev", 1_780_000_000)[1] == a


def test_without_shop_shows_notice(tmp_path):
    r = Rig(tmp_path, shop=False)
    assert "فقط در حالتِ «فروشگاه»" in collect_text(r.control)


def test_dashboard_numbers_and_missing_cost_warning(rig):
    rig.sale(100_000, 2, cost=0)
    rig.manager.finance.post_missing()
    rig.click("fn_period_all")
    assert "20,000 تومان" in rig.text("fn_k_sales") and rig.text("fn_k_orders") == "1"
    assert rig.f("fn_warn_cost") is not None
    rig.settings.finance_unit = "irr"
    rig.click("fn_period_all")
    assert "200,000 ریال" in rig.text("fn_k_sales")


def test_toman_display_and_profit_with_cost(rig):
    rig.sale(100_000, 2, cost=60_000)
    rig.manager.finance.post_missing()
    rig.click("fn_period_all")
    assert "8,000 تومان" in rig.text("fn_k_gp") and rig.f("fn_warn_cost") is None  # (۲۰۰−۱۲۰)هزار ریال = ۸٬۰۰۰ تومان
    assert "کارت‌به‌کارت" in rig.text("fn_by_method")


def test_ledger_add_validate_reverse_and_filter(rig):
    rig.click("fn_tab_led")
    rig.type(fn_led_amount="abc")
    rig.click("fn_led_add")
    assert rig.notice()[1] is not None and "درست نیست" in rig.notice()[0]
    rig.type(fn_led_amount="۵۰٬۰۰۰", fn_led_note="تبلیغ اینستاگرام")
    rig.f("fn_led_cat").value = "ads"
    rig.click("fn_led_add")
    assert rig.notice()[0] == "✅ ثبت شد." and "تبلیغ اینستاگرام" in rig.text("fn_led_list")
    entry = rig.manager.finance.list_entries()[0]
    assert entry.amount_irr == 500_000 and entry.category == "تبلیغات"
    rig.type(fn_led_amount="1", fn_led_date="1405/13/40")
    rig.click("fn_led_add")
    assert rig.notice()[0] == "این تاریخِ جلالی وجود ندارد." and rig.notice()[1] is not None
    rig.click(f"fn_led_rev_{entry.id}")
    assert rig.notice()[0] == "✅ برگشت خورد." and "[برگشت‌خورده]" in rig.text("fn_led_list")
    assert rig.f(f"fn_led_rev_{entry.id}") is None  # دوباره برگشت‌پذیر نیست
    fire(rig.f("fn_led_filter"), "on_select", "income")
    assert "ردیفی نیست" in rig.text("fn_led_list")


def test_ledger_export_csv_file(rig, monkeypatch):
    opened = []
    monkeypatch.setattr("app.screens.finance.common.open_folder", lambda p: opened.append(p) or True)
    rig.manager.finance.add_entry("expense", 7000, "ads", note="=1+1")
    rig.click("fn_tab_led")
    rig.click("fn_led_export")
    path = opened[0] / next(p for p in (x.name for x in opened[0].iterdir()) if p.endswith(".csv"))
    text = path.read_text(encoding="utf-8")
    assert "'=1+1" in text and text.startswith("\ufeff") and rig.notice()[0].startswith("✅ ذخیره شد")


def test_invoice_tab_issue_pdf_resend_credit_note(rig, monkeypatch):
    oid = rig.sale()
    monkeypatch.setattr("app.screens.finance.common.open_folder", lambda p: True)
    rig.click("fn_tab_inv")
    assert "فاکتوری نیست" in rig.text("fn_inv_list")
    rig.type(fn_issue_order="999")
    rig.click("fn_issue")
    assert "درست نیست" in rig.notice()[0]
    rig.type(fn_issue_order=f"#{oid}")
    rig.click("fn_issue")
    assert "✅ فاکتور" in rig.notice()[0] and "علی رضایی" in rig.text("fn_inv_list")
    inv = rig.manager.invoices.store.for_order(oid)
    rig.click(f"fn_inv_pdf_{inv.id}")
    assert "PDF آماده است" in rig.notice()[0] and rig.manager.invoices.path_of(inv).is_file()
    rig.click(f"fn_inv_resend_{inv.id}")  # ربات‌ها خاموش
    assert rig.notice()[1] is not None and "خاموش" in rig.notice()[0]
    rig.click(f"fn_inv_credit_{inv.id}")  # مرحله‌ی اول: فقط «مطمئنی؟»
    assert rig.manager.invoices.store.return_note_for(inv.id) is None and "مطمئنی" in rig.text("fn_inv_list")
    rig.click(f"fn_inv_credit_{inv.id}")
    assert "برگشتی" in rig.notice()[0] and rig.manager.invoices.store.return_note_for(inv.id) is not None
    assert rig.f(f"fn_inv_credit_{inv.id}") is None
    assert rig.manager.finance.report(0, 2**40).refunds == 200_000
    rig.type(fn_inv_search="نیست‌کس")
    fire(rig.f("fn_inv_search"), "on_submit", "نیست‌کس")
    assert "فاکتوری نیست" in rig.text("fn_inv_list")


def test_settings_validation_and_save(rig, tmp_path):
    rig.click("fn_tab_set")
    for key, bad, label in [("fn_set_vat_rate", "abc", "نرخِ مالیات"), ("fn_set_fee_bale", "50", "کارمزدِ بله‌پی"), ("fn_set_start", "0", "شماره‌ی شروع"),
                            ("fn_set_color", "red", "رنگِ اصلی"), ("fn_set_logo", str(tmp_path / "nope.png"), "لوگو")]:
        field = rig.f(key)
        old = field.value
        field.value = bad
        rig.click("fn_set_save")
        assert label in rig.notice()[0] and rig.notice()[1] is not None, key
        field.value = old
    big = tmp_path / "big.png"
    big.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 400_000)
    rig.type(fn_set_logo=str(big))
    rig.click("fn_set_save")
    assert "لوگو" in rig.notice()[0]  # بزرگ‌تر از ۳۰۰ کیلوبایت
    rig.type(fn_set_logo="", fn_set_name="فروشگاه من", fn_set_prefix="a-b!", fn_set_start="۷۰۰", fn_set_vat_rate="۹٫۵", fn_set_fee_zp="1.5", fn_set_color="#aabbcc")
    rig.f("fn_set_vat").value = True
    rig.f("fn_set_auto").value = "after_confirm"
    rig.f("fn_set_mgr").value = True
    rig.click("fn_set_save")
    s = rig.settings
    assert rig.notice()[0] == "✅ ذخیره شد."
    assert (s.invoice_seller_name, s.invoice_number_prefix, s.invoice_number_start) == ("فروشگاه من", "ab", 700)
    assert (s.invoice_vat_enabled, s.invoice_vat_rate_bp, s.finance_fee_bp_zarinpal, s.invoice_auto_send, s.finance_manager_access) == (True, 950, 150, "after_confirm", True)


def test_english_ui_builds(tmp_path):
    r = Rig(tmp_path, lang="en")
    assert "Dashboard" in collect_text(r.control) and "Net sales" in collect_text(r.control)
    for tab in ("inv", "led", "set"):
        r.click(f"fn_tab_{tab}")
