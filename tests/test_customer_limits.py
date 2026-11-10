"""قلم ۶ — محدودیتِ شخصیِ روزانه‌ی AI به‌ازای هر مشتری + رتبه‌بندی «پرمصرف‌ترین‌ها».

پوششِ خواسته‌هایِ مالک:
* محدودیتِ شخصی بر سقفِ سراسری اولویت دارد؛
* ۰ یعنی AI برای *همان* مشتری خاموش (و همان پیامِ سقفِ فارسی، بی‌بن‌بستِ تازه)؛
* مقدارِ خرابِ ذخیره‌شده → سقفِ سراسری + لاگِ هشدار، بدونِ exception؛
* مهاجرتِ ``_m7`` دیتابیسِ قدیمی را بدونِ از‌دست‌رفتنِ ردیف‌ها ارتقا می‌دهد و زنجیره یک سر می‌ماند؛
* فهرستِ «پرمصرف‌ترین» پر‌مصرف‌ترینِ گفتگو را اول با کارتِ هویت نشان می‌دهد؛
* کنترل‌هایِ بلاک و سقف ذخیره می‌شن و یک خطِ ممیزی/لاگ نوشته می‌شه.
"""

import asyncio
import logging
import sqlite3

import pytest
from fakes import FakeEngine, FakeSettings
from fake_page import FakePage, collect_text, find, fire

import app.core.ai_engine as ai_engine
from app.core import migrations
from app.core.bot_pipeline import ConversationPipeline, IncomingMessage
from app.core.conversations import (
    MIGRATIONS,
    ConversationStore,
    _coerce_stored_limit,
    _m7_customer_limit,
    _normalize_input_limit,
)
from app.core.settings import AppSettings
from app.core.usage_limits import UsageLimiter
from app.screens import chat_view

FAST = dict(debounce_wait=0.1, debounce_max_wait=0.4)


# ─────────────────────────── اعتبارسنجیِ خالصِ مقدارِ سقف ───────────────────────────

def test_normalize_input_accepts_none_blank_int_and_persian_digits():
    assert _normalize_input_limit(None) is None
    assert _normalize_input_limit("   ") is None
    assert _normalize_input_limit(0) == 0
    assert _normalize_input_limit("۵") == 5          # رقمِ فارسی
    assert _normalize_input_limit(" ۱۲ ") == 12
    assert _normalize_input_limit(1000) == 1000


@pytest.mark.parametrize("bad", [True, -1, 1001, "abc", "۱۲۳۴۵۶", 12.5])
def test_normalize_input_rejects_garbage_out_of_range_and_bools(bad):
    with pytest.raises(ValueError):
        _normalize_input_limit(bad)


def test_coerce_stored_limit_fails_closed_to_global_on_garbage():
    assert _coerce_stored_limit(None) is None            # سراسری (بدونِ هشدار)
    assert _coerce_stored_limit(0) == 0
    assert _coerce_stored_limit("abc") is None           # خراب → سراسری
    assert _coerce_stored_limit(5000) is None            # خارجِ بازه → سراسری


# ─────────────────────────── استور: خواندن/نوشتنِ سقفِ شخصی ───────────────────────────

def test_store_set_and_get_override_roundtrip(tmp_path):
    store = ConversationStore(tmp_path / "c.db")
    store.ensure_conversation("telegram", "1", "علی")
    assert store.get_limit_override("telegram", "1") is None
    assert store.set_limit_override("telegram", "1", "۳") == 3
    assert store.get_limit_override("telegram", "1") == 3
    assert store.set_limit_override("telegram", "1", 0) == 0
    assert store.get_limit_override("telegram", "1") == 0
    assert store.set_limit_override("telegram", "1", "") is None      # پاک → سراسری
    assert store.get_limit_override("telegram", "1") is None


def test_store_get_override_garbage_is_logged_not_raised(tmp_path, caplog):
    store = ConversationStore(tmp_path / "c.db")
    store.ensure_conversation("telegram", "1", "علی")
    conn = store.connection()
    conn.execute("UPDATE conversations SET daily_ai_limit = 'خراب' WHERE platform='telegram' AND chat_id='1'")  # noqa: S608
    conn.commit()
    with caplog.at_level(logging.WARNING):
        assert store.get_limit_override("telegram", "1") is None      # fail-closed → سراسری
    assert any("خراب" in r.getMessage() for r in caplog.records)


def test_store_set_override_creates_missing_row_and_validates(tmp_path):
    store = ConversationStore(tmp_path / "c.db")
    store.set_limit_override("telegram", "99", 4)                     # ردیفِ مکالمه نبود؛ ساخته می‌شه
    assert store.get_limit_override("telegram", "99") == 4
    with pytest.raises(ValueError):
        store.set_limit_override("telegram", "99", 99999)


# ─────────────────────────── لیمیتر: سقفِ شخصی بر سراسری اولویت دارد ───────────────────────────

def make_limiter(tmp_path, **caps):
    settings = AppSettings(**caps)
    store = ConversationStore(tmp_path / "c.db")
    store.ensure_conversation("telegram", "1", "علی")
    store.ensure_conversation("telegram", "2", "مریم")
    return UsageLimiter(store, lambda: settings, clock=lambda: 0.0), store


def test_override_beats_global_cap(tmp_path):
    limiter, store = make_limiter(tmp_path, max_ai_messages_per_chat_per_day=100, max_ai_messages_per_day_total=10000)
    store.set_limit_override("telegram", "1", 2)
    for _ in range(2):
        assert limiter.check_ai("telegram", "1") == "ok"
        limiter.record_ai("telegram", "1", 10)
    assert limiter.check_ai("telegram", "1") == "chat"        # سقفِ شخصیِ ۲ پر شده، با اینکه سراسری ۱۰۰ است
    assert limiter.check_ai("telegram", "2") == "ok"          # مشتریِ دیگه هنوز سراسری دارد


def test_override_zero_disables_only_that_customer(tmp_path):
    limiter, store = make_limiter(tmp_path, max_ai_messages_per_chat_per_day=100, max_ai_messages_per_day_total=10000)
    store.set_limit_override("telegram", "1", 0)
    assert limiter.check_ai("telegram", "1") == "chat"        # بدونِ هیچ مصرفِ قبلی، AIِ این مشتری خاموش
    assert limiter.check_ai("telegram", "2") == "ok"          # بقیه دست‌نخورده


def test_kill_and_off_still_beat_the_override(tmp_path):
    settings = AppSettings(max_ai_messages_per_chat_per_day=100)
    store = ConversationStore(tmp_path / "k.db")
    store.ensure_conversation("telegram", "1", "علی")
    store.set_limit_override("telegram", "1", 50)             # محدودیتِ آزادِ عددی
    limiter = UsageLimiter(store, lambda: settings, clock=lambda: 0.0)
    settings.ai_kill_switch = True
    assert limiter.check_ai("telegram", "1") == "kill"        # کلیدِ اضطراری اولویتِ مطلق دارد
    settings.ai_kill_switch = False
    settings.telegram_ai = False
    assert limiter.check_ai("telegram", "1") == "off"         # سوییچِ پیام‌رسان هم اولویت دارد


def test_garbage_override_falls_back_to_global_and_logs(tmp_path, caplog):
    limiter, store = make_limiter(tmp_path, max_ai_messages_per_chat_per_day=1, max_ai_messages_per_day_total=10000)
    conn = store.connection()
    conn.execute("UPDATE conversations SET daily_ai_limit = 99999 WHERE platform='telegram' AND chat_id='1'")  # خارجِ بازه
    conn.commit()
    with caplog.at_level(logging.WARNING):
        assert limiter.check_ai("telegram", "1") == "ok"       # مقدارِ خراب نادیده → سقفِ سراسری (۱) که هنوز پر نشده
    assert any("خراب" in r.getMessage() or "99999" in r.getMessage() for r in caplog.records)
    limiter.record_ai("telegram", "1", 5)
    assert limiter.check_ai("telegram", "1") == "chat"         # حالا سقفِ سراسریِ ۱ پر شده


def test_chat_cap_reflects_override_for_display(tmp_path):
    limiter, store = make_limiter(tmp_path, max_ai_messages_per_chat_per_day=100, max_ai_messages_per_day_total=10000)
    assert limiter.chat_cap("telegram", "1") == 100            # بدونِ محدودیتِ شخصی → سراسری
    store.set_limit_override("telegram", "1", 7)
    assert limiter.chat_cap("telegram", "1") == 7


# ─────────────────────────── مهاجرتِ _m7 ───────────────────────────

def test_migrations_have_exactly_one_head_and_m7_is_the_tip():
    assert len(MIGRATIONS) == 7
    assert MIGRATIONS[-1] is _m7_customer_limit
    assert migrations.latest_version("conversations.db") == 7


def test_m7_upgrades_old_db_without_losing_rows(tmp_path):
    path = tmp_path / "conversations.db"
    conn = sqlite3.connect(str(path))
    for step in MIGRATIONS[:6]:                                # دیتابیسِ نسخه‌ی ۶ (پیشِ _m7)
        step(conn)
    conn.execute("PRAGMA user_version = 6")
    conn.execute("INSERT INTO conversations (platform, chat_id, display_name) VALUES ('telegram','5','علی')")
    conn.execute("INSERT INTO messages (platform, chat_id, role, content) VALUES ('telegram','5','user','سلام')")
    conn.commit()
    conn.close()

    assert migrations.apply_migrations(sqlite3.connect(str(path)), MIGRATIONS, name="conversations.db") == 7
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(conversations)")}
    assert "daily_ai_limit" in columns
    row = conn.execute("SELECT display_name, daily_ai_limit FROM conversations WHERE chat_id='5'").fetchone()
    assert row["display_name"] == "علی" and row["daily_ai_limit"] is None   # ردیفِ کهنه با ستونِ خالی سالم مانده
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1  # هیچ پیامی حذف نشده
    conn.close()


# ─────────────────────────── صفحه‌ی گفتگوها: پرمصرف‌ها + کارتِ هویت + کنترل‌ها ───────────────────────────

def build_env(tmp_path):
    from app.core.bot_manager import BotManager

    settings = AppSettings()
    store = ConversationStore(tmp_path / "c.db")
    manager = BotManager(settings, store=store, adapter_factories={}, log_dir=tmp_path)
    return manager, store


def conv_row_order(root) -> list:
    """کلیدِ ردیف‌هایِ گفتگو را به همان ترتیبِ نمایش (DFS) جمع می‌کند تا ترتیبِ «پرمصرف‌ترین» سنجیده شود."""
    out: list = []

    def walk(c):
        key = getattr(c, "key", None)
        if isinstance(key, str) and key.startswith("conv_") and not key.startswith("conv_count_"):
            out.append(key)
        for attr in ("controls", "content"):
            val = getattr(c, attr, None)
            for item in (val if isinstance(val, list) else [val]):
                if item is not None and not isinstance(item, str):
                    walk(item)

    walk(root)
    return out


def seed_two_chats(store):
    # «کم‌مصرف» (۲ پیام) تازه‌تر است؛ «پرمصرف» (۵ پیام) قدیمی‌تر ولی پر‌مصرف‌تر.
    store.ensure_conversation("telegram", "big", "پرمصرف")
    for _ in range(5):
        store.add_message("telegram", "big", "user", "پرسشِ پرمصرف")
    store.ensure_conversation("telegram", "small", "کم‌مصرف")
    for _ in range(2):
        store.add_message("telegram", "small", "user", "کم")


def test_volume_sort_shows_most_used_first_with_identity(tmp_path):
    manager, store = build_env(tmp_path)
    seed_two_chats(store)
    manager.customers.touch(IncomingMessage(platform="telegram", chat_id="big", display_name="پرمصرف", text="x", username="biguser", first_name="آقا"))
    page = FakePage()
    control, cleanup = chat_view.build(page, "fa", manager, on_open_bots=lambda: None)
    cleanup()

    # پیش‌فرض «تازه‌ترین»: کم‌مصرف که تازه‌تر پیام داشت اول است.
    assert conv_row_order(control)[0] == "conv_telegram_small"
    fire(find(control, "chats_sort"), "on_select", "volume")
    assert conv_row_order(control)[0] == "conv_telegram_big"        # پرمصرف‌ترین اول

    fire(find(control, "conv_telegram_big"), "on_click")
    card = find(control, "identity_card")
    text = collect_text(card)
    assert "آقا" in text and "@biguser" in text and "big" in text     # نامِ CRM/یوزرنیم/شناسه در کارتِ هویت
    assert "مجموعِ پیام‌ها" in text and "5" in text                    # رتبه‌بندیِ مصرف از شمارشِ دیتابیس
    assert find(control, "management_row") is not None
    assert find(control, "daily_limit_input") is not None and find(control, "daily_limit_save") is not None
    assert find(control, "block_button") is not None and find(control, "memory_switch") is not None


def test_block_and_limit_controls_persist_and_log(tmp_path, caplog):
    manager, store = build_env(tmp_path)
    seed_two_chats(store)
    page = FakePage()
    control, cleanup = chat_view.build(page, "fa", manager, on_open_bots=lambda: None)
    fire(find(control, "conv_telegram_big"), "on_click")

    # سقفِ روزانه‌ی AI: تایپ + ذخیره → در استور نوشته می‌شه و یک خطِ لاگ می‌خورد
    find(control, "daily_limit_input").value = "۸"
    with caplog.at_level(logging.INFO, logger="app.core.conversations"):
        fire(find(control, "daily_limit_save"), "on_click")
    assert store.get_limit_override("telegram", "big") == 8
    assert any("big" in r.getMessage() for r in caplog.records)

    # مقدارِ بد: نه ذخیره می‌شه نه کرش — فقط پیام/لاگ
    find(control, "daily_limit_input").value = "۵۰۰۰"
    fire(find(control, "daily_limit_save"), "on_click")
    assert store.get_limit_override("telegram", "big") == 8          # دست‌نخورده
    assert "بین" in collect_text(find(control, "daily_limit_note"))  # توضیحِ فارسی

    # بلاک از همان دکمه‌ی همیشگی ذخیره می‌شه
    fire(find(control, "block_button"), "on_click")
    assert store.is_blocked("telegram", "big") is True
    cleanup()


def test_open_customer_button_calls_callback_only_when_wired(tmp_path):
    manager, store = build_env(tmp_path)
    seed_two_chats(store)
    unwired = chat_view.build(FakePage(), "fa", manager, on_open_bots=lambda: None)
    assert unwired[0] is not None
    unwired[1]()

    calls = []
    control, cleanup = chat_view.build(FakePage(), "fa", manager, on_open_bots=lambda: None,
                                       on_open_customer=lambda p, cid: calls.append((p, cid)))
    fire(find(control, "conv_telegram_big"), "on_click")
    assert find(control, "open_customer_button").visible is True
    fire(find(control, "open_customer_button"), "on_click")
    assert calls == [("telegram", "big")]
    cleanup()


# ─────────────────────────── e2e: صفحۀ ربات همان پیامِ سقف را می‌دهد ───────────────────────────

def test_pipeline_zero_override_sends_persian_throttle_and_skips_engine(tmp_path, monkeypatch):
    settings = FakeSettings(tmp_path)
    store = ConversationStore(tmp_path / "c.db")
    store.ensure_conversation("telegram", "off", "مزاحم")
    store.ensure_conversation("telegram", "on", "مشتری")
    store.set_limit_override("telegram", "off", 0)

    limiter = UsageLimiter(store, lambda: settings, clock=lambda: 0.0)
    engines = []
    engine = FakeEngine()
    engines.append(engine)
    monkeypatch.setattr(ai_engine, "build_engine_from_settings", lambda s: engine)

    async def go():
        sent = {"off": [], "on": []}

        async def send_off(text):
            sent["off"].append(text)

        async def send_on(text):
            sent["on"].append(text)

        p = ConversationPipeline(settings, store=store, limits=limiter, **FAST)
        await p.handle_incoming(IncomingMessage("telegram", "off", "مزاحم", "سلام"), send_off)
        await asyncio.sleep(0.5)
        await p.handle_incoming(IncomingMessage("telegram", "on", "مشتری", "سلام"), send_on)
        await asyncio.sleep(0.5)
        await p.shutdown()
        return sent

    result = asyncio.run(go())
    assert engine.calls and all(c[2] == "سلام" for c in engine.calls)
    assert len(engine.calls) == 1                                   # فقط مشتریِ مجاز به AI رسید
    assert "سقف" in result["off"][0] and "هوش مصنوعی" in result["off"][0]  # همان پیامِ سقفِ فارسیِ موجود
    assert result["on"] == ["پاسخ: سلام"]
