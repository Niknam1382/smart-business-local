"""N8 — کدِ تخفیف: اعتبارسنجی، محاسبه، شرط‌ها، مصرفِ اتمیک/آزادسازی، ضدِ brute-force و جریانِ ربات."""

import threading

import pytest

from app.core import discounts as d
from app.core.discounts import DiscountCode, DiscountConfigError, DiscountError, DiscountStore, normalize_code
from app.core.orders import OrderStore
from app.core.products import ProductStore
from tests.shop_harness import Harness, datas, texts


@pytest.fixture
def env(tmp_path):
    products = ProductStore(tmp_path / "products.db")
    orders = OrderStore(tmp_path / "orders.db", product_store=products)
    clock = {"t": 1_000_000.0}
    store = DiscountStore(orders, clock=lambda: clock["t"])
    return products, orders, store, clock


def pct(code="SALE10", value=10, **kw):
    return DiscountCode(0, code, d.KIND_PERCENT, value, **kw)


def fixed(code="OFF50", value=500_000, **kw):
    return DiscountCode(0, code, d.KIND_FIXED, value, **kw)


def mk_order(orders, pid, qty=1, chat="1", code="", auto=False, platform="telegram"):
    return orders.create(platform, chat, [(pid, qty)], discount_code=code, auto_discounts=auto)


# ---------------------------------------------------------------- نرمال‌سازی و اعتبارسنجی


def test_normalize_code_handles_persian_digits_spaces_case_and_garbage():
    assert normalize_code(" sale ۱۰ ") == "SALE10"
    assert normalize_code("a\u200cb-c_٣") == "AB-C_3"
    assert normalize_code("ab") == ""  # کوتاه
    assert normalize_code("x" * 33) == ""
    assert normalize_code("سلام!!") == ""
    assert normalize_code(None) == ""


@pytest.mark.parametrize("bad", [
    pct(value=100), pct(value=0), pct(value=-5), fixed(value=0), pct(max_discount_irr=-1), pct(applies="products"),
    pct(applies="x"), pct(starts_ts=10, ends_ts=5), pct(platforms=["sms"]), pct(code="a"), pct(total_limit=-1),
])
def test_validate_rejects_bad_definitions(bad):
    with pytest.raises(DiscountConfigError):
        d.validate_code(bad)


def test_duplicate_code_is_rejected_case_insensitively(env):
    _p, _o, store, _c = env
    store.create(pct("Hello1"))
    with pytest.raises(DiscountConfigError):
        store.create(pct("HELLO1"))
    assert store.find("hello1").code == "HELLO1"


# ---------------------------------------------------------------- محاسبه


def lines(*triples):
    return [d.CartLine(i + 1, f"p{i}", cat, price, qty) for i, (price, qty, cat) in enumerate(triples)]


def test_percent_is_floor_and_capped_and_fixed_never_exceeds_base():
    ls = lines((10_001, 1, ""))
    assert d.raw_amount(DiscountCode(0, "AAA", "percent", 33), ls) == 10_001 * 33 // 100
    assert d.raw_amount(DiscountCode(0, "AAA", "percent", 50, max_discount_irr=1000), ls) == 1000
    assert d.raw_amount(DiscountCode(0, "AAA", "fixed", 99_999_999), ls) == 10_001


def test_scope_by_product_and_category():
    ls = lines((100_000, 1, "کفش"), (200_000, 1, "کیف"))
    assert d.raw_amount(DiscountCode(0, "AAA", "percent", 10, applies="products", targets=[1]), ls) == 10_000
    assert d.raw_amount(DiscountCode(0, "AAA", "percent", 10, applies="categories", targets=["کیف"]), ls) == 20_000
    assert d.raw_amount(DiscountCode(0, "AAA", "percent", 10, applies="categories", targets=["هیچ"]), ls) == 0


def test_resolution_never_goes_below_gateway_minimum(env):
    products, orders, store, _c = env
    pid = products.add("ارزان", 30_000, 5)
    store.create(fixed("BIG", 29_999))
    order = orders.get(mk_order(orders, pid, code="BIG"))
    assert order.total_irr == d.MIN_FINAL_IRR and order.discount_irr == 20_000 and order.subtotal_irr == 30_000
    tiny = products.add("خیلی ارزان", 9_000, 5)
    with pytest.raises(DiscountError) as exc:
        mk_order(orders, tiny, code="BIG")
    assert exc.value.code == "too_low"
    assert len(orders.list()) == 1  # هیچ سفارشی ساخته نشد


# ---------------------------------------------------------------- شرط‌ها


def test_window_platform_min_subtotal_and_inactive(env):
    products, orders, store, clock = env
    pid = products.add("کالا", 100_000, 50)
    store.create(pct("TIMED", starts_ts=int(clock["t"]) + 100, ends_ts=int(clock["t"]) + 200))
    store.create(pct("TGONLY", platforms=["telegram"]))
    store.create(pct("MINSUB", min_subtotal_irr=500_000))
    cid = store.create(pct("OFFCODE"))
    store.set_active(cid, False)
    import time as _t
    now = _t.time()
    # (ساعتِ ``store`` فقط برای پیش‌نمایش است؛ ساختِ سفارش از ساعتِ واقعی می‌گیره)
    store.create(pct("PAST", starts_ts=int(now) - 500, ends_ts=int(now) - 100))
    store.create(pct("FUTURE", starts_ts=int(now) + 9999))
    for code, err in (("PAST", "expired"), ("FUTURE", "not_started"), ("MINSUB", "min_subtotal"), ("OFFCODE", "inactive")):
        with pytest.raises(DiscountError) as exc:
            mk_order(orders, pid, code=code)
        assert exc.value.code == err, code
    with pytest.raises(DiscountError) as exc:
        mk_order(orders, pid, code="TGONLY", platform="bale")
    assert exc.value.code == "platform"
    assert orders.get(mk_order(orders, pid, code="TGONLY")).discount_irr == 10_000


def test_first_order_only_and_min_prev_orders(env):
    products, orders, store, _c = env
    pid = products.add("کالا", 100_000, 50)
    store.create(pct("FIRST", first_order_only=True))
    store.create(pct("LOYAL", min_prev_orders=1))
    with pytest.raises(DiscountError) as exc:
        mk_order(orders, pid, code="LOYAL")
    assert exc.value.code == "min_prev"
    first = mk_order(orders, pid, code="FIRST")
    orders.mark_paid(first, "card_to_card")
    with pytest.raises(DiscountError) as exc:
        mk_order(orders, pid, code="FIRST")
    assert exc.value.code == "first_only"
    assert orders.get(mk_order(orders, pid, code="LOYAL")).discount_irr == 10_000


def test_per_customer_and_total_limits_with_release_on_cancel(env):
    products, orders, store, _c = env
    pid = products.add("کالا", 100_000, 50)
    cid = store.create(pct("ONCE", per_customer_limit=1, total_limit=2))
    a = mk_order(orders, pid, chat="1", code="ONCE")
    with pytest.raises(DiscountError) as exc:
        mk_order(orders, pid, chat="1", code="ONCE")
    assert exc.value.code == "per_customer"
    b = mk_order(orders, pid, chat="2", code="ONCE")
    with pytest.raises(DiscountError) as exc:
        mk_order(orders, pid, chat="3", code="ONCE")
    assert exc.value.code == "exhausted" and store.get(cid).used_count == 2
    orders.cancel(a)  # آزاد می‌شه
    assert store.get(cid).used_count == 1
    assert orders.get(mk_order(orders, pid, chat="3", code="ONCE")).discount_irr == 10_000
    orders.cancel(b)
    assert store.get(cid).used_count == 1


def test_release_on_expire_and_reject_and_reclaim_on_late_payment(env):
    products, orders, store, _c = env
    pid = products.add("کالا", 100_000, 50)
    cid = store.create(pct("RLS"))
    o1 = mk_order(orders, pid, code="RLS")
    assert store.get(cid).used_count == 1
    expired = orders.expire_stale(now=10**12)
    assert [o.id for o in expired] == [o1] and store.get(cid).used_count == 0
    orders.mark_paid(o1, "zarinpal", "ref")  # پرداختِ دیرهنگام: پولِ واقعی رسیده
    assert store.get(cid).used_count == 1 and orders.get(o1).paid_late
    orders.reject(o1)
    assert store.get(cid).used_count == 0
    o2 = mk_order(orders, pid, code="RLS")
    orders.mark_paid(o2, "card_to_card")
    orders.confirm(o2)
    assert store.get(cid).used_count == 1 and orders.get(o2).status == "confirmed"


def test_concurrent_orders_cannot_exceed_total_limit(env):
    products, orders, store, _c = env
    pid = products.add("کالا", 100_000, 500)
    cid = store.create(pct("RACE", total_limit=3))
    results = []

    def worker(i):
        try:
            mk_order(orders, pid, chat=str(i), code="RACE")
            results.append("ok")
        except DiscountError as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 3 and store.get(cid).used_count == 3
    assert sum(1 for o in orders.list() if o.discount_irr) == 3


# ---------------------------------------------------------------- خودکار و ترکیب


def test_auto_apply_picks_best_single_or_stackable_sum(env):
    products, orders, store, _c = env
    pid = products.add("کالا", 1_000_000, 50)
    store.create(pct("AUTO5", 5, auto_apply=True))
    store.create(pct("AUTO12", 12, auto_apply=True))
    assert orders.get(mk_order(orders, pid, auto=True)).discount_irr == 120_000  # بهترین تکی
    store.create(pct("ST4", 4, auto_apply=True, stackable=True))
    store.create(pct("ST9", 9, auto_apply=True, stackable=True))
    o = orders.get(mk_order(orders, pid, chat="2", auto=True))
    assert o.discount_irr == 130_000 and o.discount_code == "ST4,ST9"  # جمعِ stackableها (13٪) > بهترین تکی (12٪)


def test_manual_code_wins_and_stacks_only_when_stackable(env):
    products, orders, store, _c = env
    pid = products.add("کالا", 1_000_000, 50)
    store.create(pct("AUTOST", 5, auto_apply=True, stackable=True))
    store.create(pct("PLAIN", 10))
    store.create(pct("COMBO", 10, stackable=True))
    assert orders.get(mk_order(orders, pid, code="PLAIN", auto=True)).discount_irr == 100_000
    assert orders.get(mk_order(orders, pid, chat="2", code="COMBO", auto=True)).discount_irr == 150_000
    assert orders.get(mk_order(orders, pid, chat="3", auto=False)).discount_irr == 0


def test_replace_items_drops_the_discount(env):
    products, orders, store, _c = env
    pid = products.add("کالا", 100_000, 50)
    cid = store.create(pct("RPL"))
    oid = mk_order(orders, pid, code="RPL")
    orders.replace_items(oid, [(pid, 2)])
    o = orders.get(oid)
    assert o.total_irr == 200_000 and o.discount_irr == 0 and o.discount_code == "" and store.get(cid).used_count == 0


# ---------------------------------------------------------------- ضدِ brute-force و آمار


def test_wrong_codes_lock_the_chat_then_release_after_an_hour(env):
    products, orders, store, clock = env
    pid = products.add("کالا", 100_000, 50)
    store.create(pct("REAL"))
    items = [(pid, 1)]
    for i in range(d.WRONG_ATTEMPT_LIMIT):
        with pytest.raises(DiscountError) as exc:
            store.try_set_code("telegram", "9", f"WRONG{i}", items)
        assert exc.value.code == "unknown"
    with pytest.raises(DiscountError) as exc:  # حتی کدِ درست هم الان رد می‌شه
        store.try_set_code("telegram", "9", "REAL", items)
    assert exc.value.code == "locked" and exc.value.retry_after > 0
    assert store.try_set_code("telegram", "8", "REAL", items).discount == 10_000  # چتِ دیگه آزاده
    clock["t"] += d.ATTEMPT_WINDOW_SECONDS + 5
    assert store.try_set_code("telegram", "9", "real", items).manual_code == "REAL"


def test_stats_count_only_paid_or_confirmed_unreleased(env):
    products, orders, store, _c = env
    pid = products.add("کالا", 100_000, 50)
    cid = store.create(pct("STAT"))
    a = mk_order(orders, pid, chat="1", code="STAT")
    b = mk_order(orders, pid, chat="2", code="STAT")
    mk_order(orders, pid, chat="3", code="STAT")  # pending: شمرده نمی‌شه
    orders.mark_paid(a, "card_to_card"); orders.mark_paid(b, "card_to_card")
    orders.reject(b)
    st = store.stats(cid)
    assert (st.uses, st.revenue_irr, st.discount_irr) == (1, 90_000, 10_000)


def test_delete_only_unused_code(env):
    products, orders, store, _c = env
    pid = products.add("کالا", 100_000, 50)
    a, b = store.create(pct("DEL1")), store.create(pct("DEL2"))
    mk_order(orders, pid, code="DEL2")
    assert store.delete(a) is True and store.delete(b) is False


def test_migration_backfills_subtotal_of_existing_orders(tmp_path):
    import sqlite3
    products = ProductStore(tmp_path / "products.db")
    orders = OrderStore(tmp_path / "orders.db", product_store=products)
    pid = products.add("کالا", 70_000, 5)
    oid = mk_order(orders, pid)
    o = orders.get(oid)
    assert (o.subtotal_irr, o.discount_irr, o.total_irr) == (70_000, 0, 70_000)
    c = sqlite3.connect(tmp_path / "orders.db")
    c.execute("UPDATE orders SET subtotal_irr=0")
    c.commit()
    assert OrderStore(tmp_path / "orders.db", product_store=products).get(oid).subtotal_irr == 70_000  # خواندن
    c.close()


# ---------------------------------------------------------------- جریانِ ربات


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


def test_cart_shows_code_button_only_when_shop_has_codes_and_applies_discount(h):
    pid = h.products.add("کفش", 1_000_000, 5)
    h.tap(f"c:a:{pid}:1:-:1")
    assert "c:dc" not in datas(h.tap("c:cart"))
    h.flow.discounts.create(pct("WELCOME", 10))
    cart = h.tap("c:cart")
    assert "c:dc" in datas(cart)
    ask = h.tap("c:dc")
    assert h.flow.sessions.get("telegram", "1").step == "code" and "کدِ تخفیف" in texts(ask)
    bad = h.say("NOPE")
    assert "معتبر نیست" in texts(bad) and h.flow.sessions.get("telegram", "1").step == "code"
    ok = h.say("welcome")
    assert "WELCOME" in texts(ok) and "900,000" in texts(ok) and "c:dr" in datas(ok) and "c:dc" not in datas(ok)
    assert h.flow.sessions.get("telegram", "1") is None
    removed = h.tap("c:dr")
    assert "900,000" not in texts(removed) and "c:dc" in datas(removed)


def test_menu_button_while_waiting_for_code_cancels_it(h):
    pid = h.products.add("کفش", 1_000_000, 5)
    h.flow.discounts.create(pct("WELCOME", 10))
    h.tap(f"c:a:{pid}:1:-:1")
    h.tap("c:dc")
    res = h.say("🧺 سبد خرید")
    assert "c:co" in datas(res) and h.flow.sessions.get("telegram", "1") is None


def test_full_checkout_charges_discounted_amount_everywhere(h):
    pid = h.products.add("کفش", 1_000_000, 5)
    h.flow.discounts.create(pct("WELCOME", 10))
    h.tap(f"c:a:{pid}:2:-:1")
    h.tap("c:dc"); h.say("WELCOME")
    h.tap("c:co")
    h.say("علی رضایی"); h.say("۰۹۱۲۳۴۵۶۷۸۹"); h.say("تهران، خیابان آزادی، پلاک ۱۲")
    h.tap("c:ck:s"); h.tap("c:ck:s")  # کدپستی و توضیحات اختیاری
    res = h.tap("c:ck:ok")
    assert "c:pm:card_to_card" in datas(res)
    res = h.tap("c:pm:card_to_card")
    order = h.orders.list()[0]
    assert (order.subtotal_irr, order.discount_irr, order.total_irr, order.discount_code) == (2_000_000, 200_000, 1_800_000, "WELCOME")
    assert "1,800,000" in texts(res)
    assert h.flow.discounts.cart_code("telegram", "1") == ""
    assert "تخفیف" in texts(h.tap(f"c:od:{order.id}")) or "1,800,000" in texts(h.tap(f"c:od:{order.id}"))


def test_code_that_becomes_invalid_before_ordering_returns_to_cart_without_order(h):
    pid = h.products.add("کفش", 1_000_000, 5)
    cid = h.flow.discounts.create(pct("WELCOME", 10, total_limit=1))
    h.tap(f"c:a:{pid}:1:-:1")
    h.tap("c:dc"); h.say("WELCOME")
    # مشتریِ دیگه ظرفیت رو می‌گیره
    h.orders.create("telegram", "2", [(pid, 1)], discount_code="WELCOME")
    h.tap("c:co")
    assert h.orders.count_by_status("pending_payment") == 1  # فقط سفارشِ مشتریِ دیگه
    assert "c:dr" not in datas(h.tap("c:cart")) and h.flow.discounts.get(cid).used_count == 1


def test_discount_verbs_are_inert_outside_shop_mode(tmp_path):
    h2 = Harness(tmp_path, business_mode="consult")
    assert "c:dc" not in datas(h2.tap("c:cart"))
    res = h2.tap("c:dc")
    assert "c:co" not in datas(res)


def test_consume_itself_refuses_a_stale_resolution_when_the_limit_filled_meanwhile(env):
    """لایه‌ی دفاعیِ اتمیکِ ``consume`` جدا از پیش‌چکِ ``check_conditions`` (جهشِ «بدونِ گارد» باید بیفته)."""
    products, orders, store, _c = env
    pid = products.add("کالا", 100_000, 50)
    cid = store.create(pct("LAST", total_limit=1))
    conn = orders.connection()
    lines = store.lines_for([(pid, 1)])
    stale = d.resolve(conn, "telegram", "1", lines, "LAST", auto=False)
    other = mk_order(orders, pid, chat="2", code="LAST")  # ظرفیت همین حالا پر شد
    assert store.get(cid).used_count == 1
    with pytest.raises(DiscountError) as exc:
        d.consume(conn, other, "telegram", "1", stale)
    assert exc.value.code == "exhausted" and store.get(cid).used_count == 1
