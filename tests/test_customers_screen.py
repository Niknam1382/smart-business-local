"""صفحه‌ی «مشتریان» (N12): فهرست، جست‌وجو/فیلتر/مرتب‌سازی، کارتِ جزئیات، برچسب/یادداشت، بلاک، پیام، حذف و خروجیِ CSV."""

import csv

import pytest
from fake_page import FakePage, collect_text, find, fire
from test_customers import NOW, add_order, msg
from test_update_banner_install import StubChecker, boot

from app.core.bot_manager import BotManagerError
from app.core.conversations import ConversationStore
from app.core.customers import CustomerStore
from app.core.orders import OrderStore
from app.core.products import ProductStore
from app.i18n import STRINGS
from app.screens import common
from app.screens import customers as screen


class FakeManager:
    def __init__(self, store, customers):
        self.store, self.customers = store, customers
        self.sent, self.fail = [], ""

    def send_to_customer_sync(self, platform, chat_id, text, timeout=20.0):
        if self.fail:
            raise BotManagerError(self.fail)
        self.sent.append((platform, chat_id, text))
        self.store.add_message(platform, chat_id, "owner", text)


@pytest.fixture
def env(tmp_path):
    conv = ConversationStore(tmp_path / "c.db")
    orders = OrderStore(tmp_path / "o.db", product_store=ProductStore(tmp_path / "p.db"))
    crm = CustomerStore(conv, orders)
    return FakeManager(conv, crm), conv, crm, orders, tmp_path


def seed(conv, crm, orders):
    people = [
        ("telegram", "1", dict(first_name="علی", last_name="رضایی", username="ali_r"), NOW - 5000),
        ("bale", "2", dict(first_name="مینا", username="mina_b", phone="+989123333333"), NOW - 1000),
        ("telegram", "3", dict(first_name="سارا", last_name="احمدی"), NOW - 9000),
    ]
    for platform, chat, ident, seen in people:
        conv.ensure_conversation(platform, chat, "")
        crm.touch(msg(chat, platform=platform, text="سلام", **ident), now=seen)
    add_order(orders, "telegram", "1", "confirmed", 300_000, NOW - 4000)
    add_order(orders, "telegram", "1", "pending_payment", 111, NOW - 100)
    add_order(orders, "bale", "2", "paid", 50_000, NOW - 900)


def make(env, **kw):
    manager, conv, crm, orders, tmp = env
    page = FakePage()
    kw.setdefault("export_dir", lambda: tmp / "exports")
    root = screen.build(page, "fa", manager, orders, **kw)
    return root, page


def rows(root):
    out = []

    def walk(c):
        key = getattr(c, "key", None)
        if isinstance(key, str) and key.startswith("customer_row_"):
            out.append(key.removeprefix("customer_row_"))
        for attr in ("controls", "content"):
            val = getattr(c, attr, None)
            for item in (val if isinstance(val, list) else [val]):
                if item is not None and not isinstance(item, str):
                    walk(item)

    walk(root)
    return out


# ---------------------------------------------------------------------- فهرست ----

def test_empty_state(env):
    root, _p = make(env)
    assert "هنوز مشتری‌ای ثبت نشده" in collect_text(root) and rows(root) == []
    assert "۰" not in collect_text(find(root, "customers_count")) and "0 از 0" in collect_text(find(root, "customers_count"))


def test_list_shows_rows_sorted_by_last_activity_with_purchases(env):
    manager, conv, crm, orders, _t = env
    seed(conv, crm, orders)
    root, _p = make(env)
    assert rows(root) == ["bale_2", "telegram_1", "telegram_3"]
    text = collect_text(root)
    assert "علی رضایی" in text and "@mina_b" in text and "بدونِ خرید" in text and "1 خرید" in text
    assert "3 از 3 مشتری" in collect_text(find(root, "customers_count"))


def test_search_filter_sort_and_platform_controls_refilter_the_list(env):
    manager, conv, crm, orders, _t = env
    seed(conv, crm, orders)
    root, page = make(env)
    fire(find(root, "customers_search"), "on_change", "علی")
    assert rows(root) == ["telegram_1"]
    fire(find(root, "customers_search"), "on_change", "989123333333")
    assert rows(root) == ["bale_2"]
    fire(find(root, "customers_search"), "on_change", "نیست")
    assert rows(root) == [] and "پیدا نشد" in collect_text(root)
    fire(find(root, "customers_search"), "on_change", "")
    fire(find(root, "customers_filter"), "on_select", "buyers")
    assert set(rows(root)) == {"telegram_1", "bale_2"}
    fire(find(root, "customers_filter"), "on_select", "no_orders")
    assert rows(root) == ["telegram_3"]
    fire(find(root, "customers_filter"), "on_select", "all")
    fire(find(root, "customers_sort"), "on_select", "spent")
    assert rows(root)[0] == "telegram_1"
    fire(find(root, "customers_platform"), "on_select", "bale")
    assert rows(root) == ["bale_2"]
    fire(find(root, "customers_platform"), "on_select", "all")
    assert len(rows(root)) == 3 and page.update_count > 0


def test_long_lists_are_truncated_with_a_hint(env, monkeypatch):
    manager, conv, crm, orders, _t = env
    seed(conv, crm, orders)
    monkeypatch.setattr(screen, "MAX_ROWS", 2)
    root, _p = make(env)
    assert len(rows(root)) == 2 and find(root, "customers_truncated") is not None
    assert "3 از 3" in collect_text(find(root, "customers_count"))  # شمارش واقعی، فقط نمایش کوتاه شده


# ---------------------------------------------------------------------- جزئیات ----

def open_row(root, key):
    row = find(root, f"customer_row_{key}")
    fire(row, "on_click")


def test_detail_card_shows_profile_orders_chat_and_token_usage(env):
    manager, conv, crm, orders, _t = env
    seed(conv, crm, orders)
    conv.add_message("telegram", "1", "user", "قیمتِ هدفون چنده؟")
    conv.add_message("telegram", "1", "assistant", "۳۰۰ هزار تومان")
    c = conv.connection()
    c.execute("INSERT INTO usage (day, platform, chat_id, messages, ai_calls, tokens_est) VALUES ('2026-10-01', 'telegram', '1', 4, 3, 1200)")
    c.execute("INSERT INTO usage (day, platform, chat_id, messages, ai_calls, tokens_est) VALUES ('2026-10-02', 'telegram', '1', 1, 1, 300)")
    c.commit()
    root, _p = make(env)
    open_row(root, "telegram_1")
    text = collect_text(root)
    assert "علی رضایی" in text and "@ali_r" in text and "شماره:" in text and "خودِ مشتری نداده" in text
    assert "4 فراخوان، حدود 1,500 توکن" in text
    assert "تایید‌شده" in text and "منتظر پرداخت" in text and "300,000" in text  # سفارش‌ها با وضعیت (همه‌ی سفارش‌ها، نه فقط معتبرها)
    assert "مشتری: قیمتِ هدفون چنده؟" in text and "ربات: ۳۰۰ هزار تومان" in text
    assert find(root, "customers_back") is not None and find(root, "customers_search") is None


def test_phone_is_shown_only_when_the_customer_shared_it(env):
    manager, conv, crm, orders, _t = env
    seed(conv, crm, orders)
    root, _p = make(env)
    open_row(root, "bale_2")
    assert find(root, "customer_phone").value == "+989123333333"


def test_back_button_returns_to_the_list(env):
    manager, conv, crm, orders, _t = env
    seed(conv, crm, orders)
    root, _p = make(env)
    open_row(root, "telegram_1")
    fire(find(root, "customers_back"), "on_click")
    assert len(rows(root)) == 3


def test_tags_and_notes_are_saved(env):
    manager, conv, crm, orders, _t = env
    seed(conv, crm, orders)
    root, _p = make(env)
    open_row(root, "telegram_1")
    find(root, "customer_tags").value = "vip، تهران, vip"
    find(root, "customer_notes").value = "عمده‌خرید؛ تخفیف می‌خواد"
    fire(find(root, "customer_save"), "on_click")
    saved = crm.get("telegram", "1")
    assert saved.tags == ["vip", "تهران"] and saved.notes == "عمده‌خرید؛ تخفیف می‌خواد"
    assert "ذخیره شد" in collect_text(find(root, "customers_notice"))
    assert find(root, "customer_tags").value == "vip, تهران"  # بعد از ذخیره، همان نسخه‌ی تمیز نشان داده می‌شه


def test_block_and_unblock_use_the_conversation_flag(env):
    manager, conv, crm, orders, _t = env
    seed(conv, crm, orders)
    root, _p = make(env)
    open_row(root, "telegram_1")
    assert "بلاک کن" in collect_text(find(root, "customer_block"))
    fire(find(root, "customer_block"), "on_click")
    assert conv.is_blocked("telegram", "1") is True and crm.get("telegram", "1").blocked is True
    assert "آزاد کن" in collect_text(find(root, "customer_block")) and "بلاک‌شده" in collect_text(find(root, "customer_flags"))
    fire(find(root, "customer_block"), "on_click")
    assert conv.is_blocked("telegram", "1") is False and find(root, "customer_flags") is None


def test_block_creates_the_conversation_row_when_missing(env):
    manager, conv, crm, orders, _t = env
    crm.touch(msg("77", first_name="بدونِ مکالمه"), now=NOW)  # ردیفِ conversations ندارد
    root, _p = make(env)
    open_row(root, "telegram_77")
    fire(find(root, "customer_block"), "on_click")
    assert conv.is_blocked("telegram", "77") is True


def test_opt_out_switch(env):
    manager, conv, crm, orders, _t = env
    seed(conv, crm, orders)
    root, _p = make(env)
    open_row(root, "telegram_3")
    fire(find(root, "customer_optout"), "on_change", True)
    assert crm.get("telegram", "3").opted_out is True and "پیامِ تبلیغاتی نمی‌خواد" in collect_text(find(root, "customer_flags"))
    fire(find(root, "customer_optout"), "on_change", False)
    assert crm.get("telegram", "3").opted_out is False


def test_send_message_success_failure_and_empty_text(env):
    manager, conv, crm, orders, _t = env
    seed(conv, crm, orders)
    root, _p = make(env)
    open_row(root, "telegram_1")
    fire(find(root, "customer_send"), "on_click")  # خالی ⇒ هیچ‌چیز
    assert manager.sent == []
    find(root, "customer_message").value = "  سفارشت فردا می‌رسه  "
    fire(find(root, "customer_send"), "on_click")
    assert manager.sent == [("telegram", "1", "سفارشت فردا می‌رسه")]
    assert "پیام فرستاده شد" in collect_text(find(root, "customers_notice")) and "شما: سفارشت فردا می‌رسه" in collect_text(root)
    manager.fail = "ربات این پلتفرم الان روشن/وصل نیست"
    find(root, "customer_message").value = "دومی"
    fire(find(root, "customer_send"), "on_click")
    assert "فرستاده نشد" in collect_text(find(root, "customers_notice")) and "روشن/وصل نیست" in collect_text(find(root, "customers_notice"))
    assert len(manager.sent) == 1


def test_delete_needs_a_second_click_and_keeps_orders_and_block(env):
    manager, conv, crm, orders, _t = env
    seed(conv, crm, orders)
    conv.set_blocked("telegram", "1", True)
    root, _p = make(env)
    open_row(root, "telegram_1")
    fire(find(root, "customer_delete"), "on_click")
    assert crm.get("telegram", "1") is not None and "مطمئنی" in collect_text(find(root, "customer_delete"))
    fire(find(root, "customer_delete"), "on_click")
    assert crm.get("telegram", "1") is None and "telegram_1" not in rows(root) and len(rows(root)) == 2
    assert orders.customer_stats()[("telegram", "1")][0] == 1 and conv.is_blocked("telegram", "1") is True


def test_leaving_the_detail_disarms_the_delete_confirmation(env):
    manager, conv, crm, orders, _t = env
    seed(conv, crm, orders)
    root, _p = make(env)
    open_row(root, "telegram_1")
    fire(find(root, "customer_delete"), "on_click")
    fire(find(root, "customers_back"), "on_click")
    open_row(root, "telegram_1")
    assert "مطمئنی" not in collect_text(find(root, "customer_delete"))


def test_detail_of_a_customer_who_just_used_forget_falls_back_to_the_list(env):
    manager, conv, crm, orders, _t = env
    seed(conv, crm, orders)
    root, _p = make(env)
    open_row(root, "telegram_3")
    conv.forget_chat("telegram", "3")  # مشتری /forget زد، همین الان
    fire(find(root, "customer_save"), "on_click")
    assert find(root, "customers_search") is not None and "telegram_3" not in rows(root)


# --------------------------------------------------------------------- CSV ----

def test_export_writes_the_filtered_list_with_localized_headers(env, monkeypatch):
    manager, conv, crm, orders, tmp = env
    seed(conv, crm, orders)
    opened = []
    monkeypatch.setattr(common, "open_folder", lambda path: opened.append(str(path)) or True)
    root, _p = make(env)
    fire(find(root, "customers_filter"), "on_select", "buyers")
    fire(find(root, "customers_export"), "on_click")
    files = list((tmp / "exports").glob("customers-*.csv"))
    assert len(files) == 1
    parsed = list(csv.reader(files[0].read_text(encoding="utf-8-sig").splitlines()))
    assert parsed[0][:3] == ["پلتفرم", "شناسه", "نام"] and len(parsed) == 3  # فقط خریدارها
    assert {r[1] for r in parsed[1:]} == {"1", "2"}
    notice = collect_text(find(root, "customers_notice"))
    assert "2 مشتری" in notice and str(files[0]) in notice and "اطلاعاتِ شخصی" in notice
    fire(find(root, "customers_open_folder"), "on_click")
    assert opened == [str(tmp / "exports")]


def test_export_failure_is_reported_not_raised(env):
    manager, conv, crm, orders, tmp = env
    seed(conv, crm, orders)
    blocker = tmp / "blocker"
    blocker.write_text("i am a file", encoding="utf-8")
    root, _p = make(env, export_dir=lambda: blocker / "sub")  # پوشه نمی‌شه ساخت
    fire(find(root, "customers_export"), "on_click")
    assert "ناموفق بود" in collect_text(find(root, "customers_notice")) and find(root, "customers_open_folder") is None


def test_every_csv_column_has_a_localized_header():
    for column in CustomerStore.CSV_COLUMNS:
        entry = STRINGS.get(f"customers.csv.{column}")
        assert entry and entry["fa"] and entry["en"], column
    assert set(screen._CSV_KEYS) == set(CustomerStore.CSV_COLUMNS)


# ------------------------------------------------------------------------ main ----

def test_customers_is_in_the_sidebar_and_opens_from_main():
    page, root, _q = boot(checker=StubChecker(None))
    nav = find(root, "nav_customers")
    assert nav is not None
    fire(nav, "on_click")
    view = page.controls[0].content
    assert find(view, "customers_search") is not None and "مشتریان" in collect_text(view)
