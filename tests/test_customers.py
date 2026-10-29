"""مشتریان (N12 — CRM): مهاجرت، ثبتِ هویت از هر دو پلتفرم، آمارِ خرید، جست‌وجو/فیلتر/مرتب‌سازی، برچسب/یادداشت، CSV امن و حریم."""

import asyncio
import calendar
import csv
import sqlite3
import time

import pytest
from fakes import FakeEngine, FakeSettings

from app.core import ai_engine, bot_manager, conversations, migrations
from app.core import customers as crm
from app.core.bot_pipeline import ConversationPipeline, IncomingMessage
from app.core.conversations import ConversationStore
from app.core.customers import CustomerStore
from app.core.orders import OrderStore
from app.core.products import ProductStore

DAY = 86400
NOW = 1_800_000_000


def msg(chat="1", platform="telegram", text="سلام", **kw):
    return IncomingMessage(platform=platform, chat_id=str(chat), display_name=kw.pop("display_name", ""), text=text, **kw)


@pytest.fixture
def stores(tmp_path):
    conv = ConversationStore(tmp_path / "conversations.db")
    orders = OrderStore(tmp_path / "orders.db", product_store=ProductStore(tmp_path / "products.db"))
    return conv, orders, CustomerStore(conv, orders)


def add_order(orders, platform, chat, status, total, when=NOW):
    conn = orders.connection()
    conn.execute(
        "INSERT INTO orders (platform, chat_id, status, total_irr, created_at) VALUES (?, ?, ?, ?, datetime(?, 'unixepoch'))",
        (platform, str(chat), status, total, when),
    )
    conn.commit()


# ------------------------------------------------------------------ مهاجرت ----

def test_migration_backfills_customers_from_existing_conversations(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    assert migrations.apply_migrations(conn, conversations.MIGRATIONS[:2]) == 2  # دیتابیسِ نسخه‌ی قبل (بدونِ جدولِ customers)
    conn.executemany(
        "INSERT INTO conversations (platform, chat_id, display_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        [
            ("telegram", "5", "علی رضایی", "2026-01-01 10:00:00", "2026-02-01 12:30:00"),
            ("bale", "7", "7", "2026-03-01 08:00:00", "2026-03-02 08:00:00"),  # نامِ نمایشی = شناسه ⇒ بی‌نام
            ("preview", "p", "پیش‌نمایش", "2026-03-01 08:00:00", "2026-03-02 08:00:00"),
        ],
    )
    conn.executemany("INSERT INTO messages (platform, chat_id, role, content) VALUES (?, ?, ?, ?)", [("telegram", "5", "user", "a"), ("telegram", "5", "assistant", "b"), ("telegram", "5", "user", "c")])
    conn.commit()
    conn.close()
    store = ConversationStore(path)
    customers = CustomerStore(store)
    assert customers.count() == 2  # اولین استفاده، مهاجرت را اجرا می‌کنه؛ پیش‌نمایش جزوِ مشتری‌ها نیست
    assert migrations.file_version(path) == len(conversations.MIGRATIONS) >= 3  # تا آخرین مهاجرت بالا آمده (customers = مهاجرتِ ۳)
    ali = customers.get("telegram", "5")
    assert ali.full_name == "علی رضایی" and ali.msg_count == 2  # فقط پیام‌های کاربر
    assert ali.first_seen_ts == calendar.timegm(time.strptime("2026-01-01 10:00:00", "%Y-%m-%d %H:%M:%S"))
    assert ali.last_seen_ts == calendar.timegm(time.strptime("2026-02-01 12:30:00", "%Y-%m-%d %H:%M:%S"))
    assert customers.get("bale", "7").full_name == "" and customers.get("bale", "7").display_name == "7"
    assert customers.get("preview", "p") is None


def test_migration_is_idempotent_and_keeps_existing_rows(tmp_path):
    first = ConversationStore(tmp_path / "c.db")
    CustomerStore(first).touch(msg("1", first_name="سارا"), now=NOW)
    again = ConversationStore(tmp_path / "c.db")  # باز شدنِ دوباره، مهاجرت دوباره اجرا نمی‌شه/خرابش نمی‌کنه
    assert CustomerStore(again).get("telegram", "1").first_name == "سارا"


# ------------------------------------------------------------------- touch ----

def test_touch_creates_and_updates_identity(stores):
    _c, _o, crm_ = stores
    crm_.touch(msg("42", first_name="سارا", last_name="احمدی", username="@sara_a", language_code="fa", is_premium=True), now=NOW)
    c = crm_.get("telegram", "42")
    assert (c.first_name, c.last_name, c.username, c.language_code, c.is_premium) == ("سارا", "احمدی", "sara_a", "fa", True)
    assert c.first_seen_ts == c.last_seen_ts == NOW and c.msg_count == 1 and c.phone == ""
    crm_.touch(msg("42", first_name="سارا", last_name="", username="sara_new", language_code="en"), now=NOW + 60)
    c = crm_.get("telegram", "42")
    assert (c.last_name, c.username, c.language_code, c.is_premium) == ("", "sara_new", "en", False)  # کاربر نام‌خانوادگی را برداشته
    assert c.first_seen_ts == NOW and c.last_seen_ts == NOW + 60 and c.msg_count == 2


def test_callbacks_without_identity_do_not_blank_the_profile_or_count_as_messages(stores):
    _c, _o, crm_ = stores
    crm_.touch(msg("1", first_name="رضا", username="reza", language_code="fa"), now=NOW)
    crm_.touch(msg("1", text="", callback_data="menu:products"), now=NOW + 5)
    c = crm_.get("telegram", "1")
    assert (c.first_name, c.username, c.language_code) == ("رضا", "reza", "fa")
    assert c.msg_count == 1 and c.last_seen_ts == NOW + 5  # کلیک پیام نیست ولی آخرین فعالیت هست


def test_phone_is_stored_only_when_the_customer_shared_it(stores):
    _c, _o, crm_ = stores
    crm_.touch(msg("1", first_name="a"), now=NOW)
    assert crm_.get("telegram", "1").phone == ""
    crm_.touch(msg("1", text="", phone="+98 912-345 6789"), now=NOW + 1)
    assert crm_.get("telegram", "1").phone == "+989123456789"
    crm_.touch(msg("1", text="سلام دوباره"), now=NOW + 2)  # پیام‌های بعدی شماره را پاک نمی‌کنن
    assert crm_.get("telegram", "1").phone == "+989123456789"


def test_display_name_fallback_only_when_the_platform_has_no_real_names(stores):
    _c, _o, crm_ = stores
    crm_.touch(msg("1", display_name="علی رضایی"), now=NOW)  # مسیرِ قدیمی: فقط «نامِ نمایشی»
    assert crm_.get("telegram", "1").full_name == "علی رضایی"
    crm_.touch(msg("2", display_name="2"), now=NOW)  # نامِ نمایشی = شناسه
    crm_.touch(msg("3", display_name="@mina", username="mina"), now=NOW)  # نامِ نمایشی = یوزرنیم
    assert crm_.get("telegram", "2").full_name == "" and crm_.get("telegram", "3").full_name == ""
    assert crm_.get("telegram", "3").display_name == "@mina"


def test_inputs_are_cleaned_and_capped(stores):
    _c, _o, crm_ = stores
    crm_.touch(msg("1", first_name="a\x00b\nc" + "x" * 500, username="u" * 300, language_code="fa" * 20), now=NOW)
    c = crm_.get("telegram", "1")
    assert "\x00" not in c.first_name and "\n" not in c.first_name and len(c.first_name) <= crm.MAX_NAME
    assert len(c.username) <= crm.MAX_USERNAME and len(c.language_code) <= 16


def test_contact_again_clears_the_unreachable_flag(stores):
    _c, _o, crm_ = stores
    crm_.touch(msg("1", first_name="a"), now=NOW)
    assert crm_.mark_unreachable("telegram", "1") and crm_.get("telegram", "1").unreachable
    crm_.touch(msg("1"), now=NOW + 1)
    assert crm_.get("telegram", "1").unreachable is False


# --------------------------------------------------------------- آمارِ خرید ----

def test_order_stats_count_only_paid_and_confirmed_orders(stores):
    conv, orders, crm_ = stores
    crm_.touch(msg("1", first_name="a"), now=NOW)
    add_order(orders, "telegram", "1", "confirmed", 100_000, NOW - 5 * DAY)
    add_order(orders, "telegram", "1", "paid", 50_000, NOW - DAY)
    for status in ("pending_payment", "rejected", "cancelled", "expired"):
        add_order(orders, "telegram", "1", status, 999_999, NOW)
    add_order(orders, "bale", "1", "confirmed", 777, NOW)  # پلتفرمِ دیگر، همان شناسه
    c = crm_.get("telegram", "1")
    assert (c.orders_count, c.total_spent_irr, c.last_order_ts) == (2, 150_000, NOW - DAY)
    assert orders.customer_stats()[("bale", "1")] == (1, 777, NOW)


def test_customers_without_an_order_store_have_zero_stats(tmp_path):
    crm_ = CustomerStore(ConversationStore(tmp_path / "c.db"))
    crm_.touch(msg("1", first_name="a"), now=NOW)
    assert crm_.get("telegram", "1").orders_count == 0 and crm_.list()[0].total_spent_irr == 0


# ------------------------------------------------- جست‌وجو / فیلتر / مرتب‌سازی ----

@pytest.fixture
def crowd(stores):
    conv, orders, crm_ = stores
    people = [
        ("telegram", "1", dict(first_name="علی", last_name="رضایی", username="ali_r", phone="+989121111111"), NOW - 40 * DAY, NOW - 35 * DAY),
        ("telegram", "2", dict(first_name="سارا", last_name="احمدی", username="sara"), NOW - 3 * DAY, NOW - 1 * DAY),
        ("bale", "3", dict(first_name="مینا", username="mina_b", phone="+989123333333"), NOW - 100 * DAY, NOW - 2 * DAY),
        ("bale", "4", dict(first_name="Ali", last_name="Karimi"), NOW - 10 * DAY, NOW - 10 * DAY),
    ]
    for platform, chat, ident, first, last in people:
        conv.ensure_conversation(platform, chat, "")  # مثلِ پایپ‌لاین: اول مکالمه، بعد مشتری
        crm_.touch(msg(chat, platform=platform, **ident), now=first)
        crm_.touch(msg(chat, platform=platform), now=last)
    add_order(orders, "telegram", "1", "confirmed", 300_000, NOW - 36 * DAY)
    add_order(orders, "bale", "3", "paid", 100_000, NOW - 2 * DAY)
    add_order(orders, "bale", "3", "confirmed", 250_000, NOW - 50 * DAY)
    crm_.set_tags("telegram", "2", "vip, تهران")
    crm_.set_notes("bale", "4", "پیگیری گارانتی لپ‌تاپ")
    crm_.set_opted_out("bale", "4")
    conv.set_blocked("telegram", "1", True)
    return crm_


def ids(customers):
    return [f"{c.platform}:{c.user_id}" for c in customers]


def test_search_matches_all_tokens_across_fields(crowd):
    now = NOW
    assert ids(crowd.list(search="ali", now=now)) == ["bale:4", "telegram:1"] or set(ids(crowd.list(search="ali", now=now))) == {"telegram:1", "bale:4"}
    assert ids(crowd.list(search="علی رضایی", now=now)) == ["telegram:1"]
    assert ids(crowd.list(search="@mina_b", now=now)) == ["bale:3"]
    assert ids(crowd.list(search="09123333333", now=now)) == []  # شماره‌ی بین‌المللی ذخیره شده؛ جست‌وجوی دقیق‌تر پایین
    assert ids(crowd.list(search="989123333333", now=now)) == ["bale:3"]
    assert ids(crowd.list(search="vip", now=now)) == ["telegram:2"]
    assert ids(crowd.list(search="گارانتی", now=now)) == ["bale:4"]
    assert ids(crowd.list(search="ali karimi", now=now)) == ["bale:4"]
    assert ids(crowd.list(search="nobody", now=now)) == []
    assert len(crowd.list(search="   ", now=now)) == 4


def test_filters(crowd):
    now = NOW
    assert set(ids(crowd.list(flt="buyers", now=now))) == {"telegram:1", "bale:3"}
    assert set(ids(crowd.list(flt="no_orders", now=now))) == {"telegram:2", "bale:4"}
    assert ids(crowd.list(flt="blocked", now=now)) == ["telegram:1"]
    assert ids(crowd.list(flt="opted_out", now=now)) == ["bale:4"]
    assert ids(crowd.list(flt="new_7d", now=now)) == ["telegram:2"]
    assert set(ids(crowd.list(flt="inactive_30d", now=now))) == {"telegram:1"}
    assert set(ids(crowd.list(platform="bale", now=now))) == {"bale:3", "bale:4"}
    assert ids(crowd.list(tag="VIP", now=now)) == ["telegram:2"]  # بدونِ حساسیت به حروف
    assert len(crowd.list(flt="unknown-filter", now=now)) == 4  # فیلترِ ناشناخته = همه


def test_sorting(crowd):
    now = NOW
    assert ids(crowd.list(sort="last_seen", now=now)) == ["telegram:2", "bale:3", "bale:4", "telegram:1"]
    assert ids(crowd.list(sort="first_seen", now=now)) == ["telegram:2", "bale:4", "telegram:1", "bale:3"]
    assert ids(crowd.list(sort="orders", now=now))[:2] == ["bale:3", "telegram:1"]
    assert ids(crowd.list(sort="spent", now=now))[:2] == ["bale:3", "telegram:1"]
    assert ids(crowd.list(sort="messages", now=now))[0] in {"telegram:1", "telegram:2", "bale:3", "bale:4"}
    assert [c.display_name for c in crowd.list(sort="name", now=now)] == sorted([c.display_name for c in crowd.list(now=now)], key=str.casefold)
    assert ids(crowd.list(sort="bogus", now=now)) == ids(crowd.list(sort="last_seen", now=now))


def test_blocked_state_comes_from_the_conversation_row(crowd):
    assert crowd.get("telegram", "1").blocked is True and crowd.get("telegram", "2").blocked is False


# ------------------------------------------------------------- برچسب و یادداشت ----

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("vip, تهران،عمده ; vip\nVIP", ["vip", "تهران", "عمده"]),
        ("  ", []),
        ("a,,b", ["a", "b"]),
        (["x", "X", " y "], ["x", "y"]),
        (None, []),
    ],
)
def test_parse_tags(raw, expected):
    assert crm.parse_tags(raw) == expected


def test_tag_limits_and_all_tags_counts(stores):
    _c, _o, crm_ = stores
    for chat in ("1", "2", "3"):
        crm_.touch(msg(chat, first_name=chat), now=NOW)
    assert len(crm_.set_tags("telegram", "1", ",".join(f"t{i}" for i in range(50)))) == crm.MAX_TAGS
    assert len(crm_.set_tags("telegram", "1", "x" * 200)[0]) == crm.MAX_TAG_LEN
    crm_.set_tags("telegram", "1", "vip, عمده")
    crm_.set_tags("telegram", "2", "VIP")
    crm_.set_tags("telegram", "3", "تهران")
    assert crm_.all_tags()[0] == ("vip", 2) or crm_.all_tags()[0][1] == 2
    assert {t.casefold() for t, _n in crm_.all_tags()} == {"vip", "عمده", "تهران"}


def test_notes_are_capped_and_missing_customers_are_reported(stores):
    _c, _o, crm_ = stores
    crm_.touch(msg("1", first_name="a"), now=NOW)
    assert crm_.set_notes("telegram", "1", "n" * 5000) and len(crm_.get("telegram", "1").notes) == crm.MAX_NOTES
    assert crm_.set_notes("telegram", "404", "x") is False and crm_.set_tags("telegram", "404", "x") == ["x"]
    assert crm_.get("telegram", "404") is None


# ---------------------------------------------------------------------- CSV ----

def test_csv_export_has_bom_headers_and_flat_rows(tmp_path, crowd):
    path = tmp_path / "out" / "customers.csv"
    rows = crowd.list(sort="name", now=NOW)
    assert crowd.export_csv(path, rows, headers=["پلتفرم"] + ["c"] * 16) == 4
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    parsed = list(csv.reader(raw.decode("utf-8-sig").splitlines(), delimiter=","))
    assert len(parsed) == 5 and parsed[0][0] == "پلتفرم" and len(parsed[1]) == len(crm.CustomerStore.CSV_COLUMNS)
    by_user = {r[1]: r for r in parsed[1:]}
    assert by_user["3"][4] == "+989123333333" and by_user["3"][9] == "2" and by_user["3"][10] == "350000"
    assert by_user["4"][13] == "پیگیری گارانتی لپ‌تاپ" and by_user["1"][14] == "1" and by_user["4"][15] == "1"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("=HYPERLINK(\"http://evil\")", "'=HYPERLINK(\"http://evil\")"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("+cmd|' /C calc'!A0", "'+cmd|' /C calc'!A0"),
        ("-2+3+cmd", "'-2+3+cmd"),
        ("\tTAB", "'\tTAB"),
        ("+989123456789", "+989123456789"),  # شماره‌ی تلفنِ واقعی دست نمی‌خوره
        ("-12.5", "-12.5"),
        ("(021) 123-4567", "(021) 123-4567"),
        ("سلام", "سلام"),
        ("", ""),
        (None, ""),
        (123, "123"),
    ],
)
def test_csv_formula_injection_guard(value, expected):
    assert CustomerStore.csv_safe(value) == expected


def test_csv_export_neutralizes_malicious_names_and_notes(tmp_path, stores):
    _c, _o, crm_ = stores
    crm_.touch(msg("1", first_name="=2+5", last_name="@x", username="+evil"), now=NOW)
    crm_.set_notes("telegram", "1", "=1+1\nسطرِ دوم")
    path = tmp_path / "x.csv"
    crm_.export_csv(path, crm_.list())
    row = list(csv.reader(path.read_text(encoding="utf-8-sig").splitlines()))[1]
    assert row[2].startswith("'=2+5") and row[3].startswith("'+evil") and row[13].startswith("'=1+1") and "\n" not in row[13]


# ------------------------------------------------------------------- حریم ----

def test_forget_removes_the_whole_customer_row_but_keeps_the_block(stores):
    conv, _o, crm_ = stores
    conv.ensure_conversation("telegram", "1", "سارا")
    crm_.touch(msg("1", first_name="سارا", username="sara", phone="+98912"), now=NOW)
    crm_.set_notes("telegram", "1", "مشتریِ ویژه")
    conv.forget_chat("telegram", "1")
    assert crm_.get("telegram", "1") is None
    conv.ensure_conversation("telegram", "2", "ب")
    crm_.touch(msg("2", first_name="ب"), now=NOW)
    conv.set_blocked("telegram", "2", True)
    conv.forget_chat("telegram", "2")
    assert crm_.get("telegram", "2") is None and conv.is_blocked("telegram", "2") is True  # /forget بلاک را دور نمی‌زند


def test_retention_purges_old_customers_but_not_blocked_or_recent_ones(stores):
    conv, _o, crm_ = stores
    now = int(time.time())
    for chat, seen in (("old", now - 200 * DAY), ("recent", now - 5 * DAY), ("oldblocked", now - 300 * DAY)):
        conv.ensure_conversation("telegram", chat, chat)
        crm_.touch(msg(chat, first_name=chat), now=seen)
    conv.set_blocked("telegram", "oldblocked", True)
    conv.purge_older_than(90)
    assert crm_.get("telegram", "old") is None
    assert crm_.get("telegram", "recent") is not None and crm_.get("telegram", "oldblocked") is not None
    conv.purge_older_than(0)  # صفر = غیرفعال
    assert crm_.count() == 2


def test_delete_removes_a_customer(stores):
    _c, _o, crm_ = stores
    crm_.touch(msg("1", first_name="a"), now=NOW)
    assert crm_.delete("telegram", "1") is True and crm_.delete("telegram", "1") is False


# ------------------------------------------------------------ پایپ‌لاین و آداپترها ----

@pytest.fixture
def pipeline_env(tmp_path, monkeypatch):
    settings = FakeSettings(tmp_path)
    store = ConversationStore(db_path=tmp_path / "c.db")
    monkeypatch.setattr(ai_engine, "build_engine_from_settings", lambda _s: FakeEngine())
    return settings, store


def test_pipeline_records_every_incoming_customer_even_when_blocked(pipeline_env):
    settings, store = pipeline_env

    async def go():
        async def send(_text):
            pass

        pipe = ConversationPipeline(settings, store=store, debounce_wait=0.05, debounce_max_wait=0.2)
        await pipe.handle_incoming(msg("9", first_name="سارا", username="sara", language_code="fa"), send)
        store.set_blocked("telegram", "9", True)
        await pipe.handle_incoming(msg("9", text="هنوز اینجام", first_name="سارا", username="sara"), send)
        await asyncio.sleep(0.2)

    asyncio.run(go())
    c = CustomerStore(store).get("telegram", "9")
    assert (c.first_name, c.username, c.language_code, c.msg_count, c.blocked) == ("سارا", "sara", "fa", 2, True)


def test_crm_failure_never_breaks_the_pipeline(pipeline_env):
    settings, store = pipeline_env

    class Broken:
        def touch(self, _message):
            raise RuntimeError("db locked")

    async def go():
        sent = []

        async def send(text):
            sent.append(text)

        pipe = ConversationPipeline(settings, store=store, customers=Broken(), debounce_wait=0.05, debounce_max_wait=0.2)
        await pipe.handle_incoming(msg("9", first_name="x"), send)
        await asyncio.sleep(0.3)
        return sent

    assert asyncio.run(go()) == ["پاسخ: سلام"]


def test_telegram_sender_fields_helper():
    from types import SimpleNamespace

    from app.core.telegram_adapter import _sender_fields

    user = SimpleNamespace(username="sara", first_name="سارا", last_name=None, is_premium=True)
    assert _sender_fields(user) == {"username": "sara", "first_name": "سارا", "last_name": "", "is_premium": True}
    assert _sender_fields(None) == {}
    assert _sender_fields(SimpleNamespace())["is_premium"] is False  # نسخه‌ی قدیمیِ aiogram بدونِ is_premium


def test_bale_client_carries_sender_identity_for_messages_and_callbacks():
    from test_bale_client import TOKEN, patched, run

    from app.core.bale_client import BaleClient

    batch = {
        "ok": True,
        "result": [
            {"update_id": 1, "message": {"message_id": 5, "chat": {"id": 10}, "from": {"id": 10, "first_name": "مینا", "last_name": "کریمی", "username": "mina", "language_code": "fa"}, "text": "سلام"}},
            {"update_id": 2, "callback_query": {"id": "cb1", "data": "menu:x", "from": {"id": 11, "first_name": "رضا", "username": "reza"}, "message": {"message_id": 6, "chat": {"id": 11}}}},
        ],
    }

    async def go():
        async def fake(url, payload, timeout):
            return batch

        result = await patched(BaleClient(TOKEN), fake).get_updates()
        first, second = result.messages
        assert (first.username, first.first_name, first.last_name) == ("mina", "مینا", "کریمی")
        assert (second.username, second.first_name, second.last_name) == ("reza", "رضا", "")

    run(go())


# ------------------------------------------------------- دسترس‌ناپذیر (manager) ----

@pytest.mark.parametrize(
    "error,expected",
    [
        (Exception("Forbidden: bot was blocked by the user"), True),
        (Exception("Telegram server says - Forbidden: user is deactivated"), True),
        (Exception("Bad Request: chat not found"), True),
        (Exception("HTTP 403 Forbidden"), True),
        (TimeoutError("timed out"), False),
        (ConnectionError("network unreachable"), False),
        (Exception("Too Many Requests: retry after 5"), False),
    ],
)
def test_looks_unreachable_only_for_explicit_platform_refusals(error, expected):
    assert bot_manager.looks_unreachable(error) is expected


def test_forbidden_error_class_name_counts_even_with_an_empty_message():
    class TelegramForbiddenError(Exception):
        pass

    assert bot_manager.looks_unreachable(TelegramForbiddenError()) is True


def test_manager_marks_a_customer_unreachable_only_for_explicit_refusals(stores):
    conv, _o, crm_ = stores
    crm_.touch(msg("1", first_name="a"), now=NOW)
    mgr = bot_manager.BotManager.__new__(bot_manager.BotManager)
    mgr._customers = crm_
    mgr._note_unreachable("telegram", "1", ConnectionError("no network"))
    assert crm_.get("telegram", "1").unreachable is False
    mgr._note_unreachable("telegram", "1", Exception("Forbidden: bot was blocked by the user"))
    assert crm_.get("telegram", "1").unreachable is True
