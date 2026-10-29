"""R10-۳/۷ — سقفِ مصرفِ AI، کلیدِ قطع، اعلانِ یک‌باره، و صندوقِ «نیاز به توجه»."""

import asyncio
from datetime import datetime, timezone

import pytest
from fake_servers import FakeBotApiServer
from helpers import wait_until
from test_shop_e2e import send, shop, status, tap  # noqa: F401

from app.core.attention import AttentionInbox
from app.core.conversations import ConversationStore
from app.core.settings import AppSettings
from app.core.usage_limits import UsageLimiter

BASE = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc).timestamp()  # ۱۲:۳۰ تهران


class Clock:
    def __init__(self, now=BASE):
        self.now = now

    def __call__(self):
        return self.now


def make(tmp_path, **kw):
    settings = AppSettings(**kw)
    clock = Clock()
    alerts: list = []

    async def notify(text):
        alerts.append(text)

    caps: list = []
    limiter = UsageLimiter(ConversationStore(tmp_path / "c.db"), lambda: settings, notify, on_cap=caps.append, clock=clock)
    return limiter, settings, clock, alerts, caps


def test_per_chat_cap_blocks_only_that_chat(tmp_path):
    lim, settings, clock, alerts, caps = make(tmp_path, max_ai_messages_per_chat_per_day=3, max_ai_messages_per_day_total=100)
    for _ in range(3):
        assert lim.check_ai("telegram", "1") == "ok"
        lim.record_ai("telegram", "1", 50)
    assert lim.check_ai("telegram", "1") == "chat"
    assert lim.check_ai("telegram", "2") == "ok" and lim.check_ai("bale", "1") == "ok"  # چتِ دیگه/پلتفرمِ دیگه آزاد
    assert lim.totals()["ai_calls"] == 3 and lim.totals()["tokens_est"] == 150


def test_total_cap_and_midnight_tehran_reset(tmp_path):
    lim, settings, clock, alerts, caps = make(tmp_path, max_ai_messages_per_chat_per_day=0, max_ai_messages_per_day_total=4)
    for i in range(4):
        lim.record_ai("telegram", str(i))
    assert lim.check_ai("telegram", "99") == "total"
    clock.now = datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc).timestamp()  # ۲۳:۳۰ تهران: هنوز همون روز
    assert lim.check_ai("telegram", "99") == "total"
    clock.now = datetime(2026, 10, 12, 20, 31, tzinfo=timezone.utc).timestamp()  # ۰۰:۰۱ تهرانِ روزِ بعد
    assert lim.check_ai("telegram", "99") == "ok" and lim.totals()["ai_calls"] == 0


def test_zero_means_unlimited_and_kill_switch_wins(tmp_path):
    lim, settings, *_ = make(tmp_path, max_ai_messages_per_chat_per_day=0, max_ai_messages_per_day_total=0)
    for _ in range(500):
        lim.record_ai("telegram", "1")
    assert lim.check_ai("telegram", "1") == "ok"
    settings.ai_kill_switch = True
    assert lim.check_ai("telegram", "1") == "kill" and lim.check_ai("bale", "9") == "kill"


def test_owner_alerted_once_at_80_and_once_at_100(tmp_path):
    lim, settings, clock, alerts, caps = make(tmp_path, max_ai_messages_per_chat_per_day=0, max_ai_messages_per_day_total=10)
    for i in range(7):
        lim.record_ai("telegram", str(i))
    asyncio.run(lim.maybe_alert())
    assert alerts == [] and caps == []
    lim.record_ai("telegram", "7")  # ۸۰٪
    asyncio.run(lim.maybe_alert()); asyncio.run(lim.maybe_alert())
    assert len(alerts) == 1 and "۸۰٪" in alerts[0] and caps == ["80"]
    lim.record_ai("telegram", "8"); lim.record_ai("telegram", "9")  # ۱۰۰٪
    asyncio.run(lim.maybe_alert()); asyncio.run(lim.maybe_alert())
    assert len(alerts) == 2 and "تموم شد" in alerts[1] and caps == ["80", "100"]
    clock.now += 86400  # روزِ بعد: دوباره می‌تونه اعلان بده
    for i in range(8):
        lim.record_ai("bale", str(i))
    asyncio.run(lim.maybe_alert())
    assert len(alerts) == 3


def test_sys_flag_rows_do_not_count_as_usage(tmp_path):
    lim, settings, clock, alerts, caps = make(tmp_path, max_ai_messages_per_chat_per_day=0, max_ai_messages_per_day_total=2)
    lim.record_ai("telegram", "1"); lim.record_ai("telegram", "2")
    asyncio.run(lim.maybe_alert())
    assert lim.total_calls() == 2 and lim.totals()["chats"] == 2


def test_attention_inbox_dedup_handle_and_cap(tmp_path):
    inbox = AttentionInbox(ConversationStore(tmp_path / "a.db"))
    a = inbox.add("delivery_failed", "12", "ربات خاموش بود")
    assert inbox.add("delivery_failed", "12", "دوباره") == a and inbox.count_open() == 1  # تکراری ثبت نمی‌شه
    assert inbox.add("weird_type", "x") is not None and inbox.list_open()[0].type == "other"
    assert inbox.handle(a) and not inbox.handle(a) and inbox.count_open() == 1
    assert inbox.handle_ref("other", "x") == 1 and inbox.count_open() == 0
    inbox.add("ai_cap", "100"); assert inbox.handle_all() == 1


# ---------------------------------------------------------------- e2e ----


@pytest.fixture
def tg():
    srv = FakeBotApiServer(username="tg_shop_bot").start()
    yield srv
    srv.stop()


@pytest.fixture
def bale():
    srv = FakeBotApiServer(username="bale_shop_bot").start()
    yield srv
    srv.stop()


def test_kill_switch_stops_ai_but_buttons_and_checkout_keep_working(tmp_path, tg, bale, monkeypatch):
    manager, products, orders, settings, engine = shop(tmp_path, tg, bale, monkeypatch, ai_kill_switch=True)
    pid = products.add("کالا", 1000, 5)
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        send(tg, 10, "سلام، یه سؤال دارم", "موقتاً غیرفعاله")
        assert engine.calls == []  # AI اصلاً صدا زده نشد
        send(tg, 10, "🛍 محصولات", "محصولات")
        tap(tg, 10, f"c:a:{pid}:1:-:1")
        assert manager._pipeline._shop_flow.carts.quantity("telegram", "10", pid) == 1  # noqa: SLF001
        settings.ai_kill_switch = False
        send(tg, 10, "حالا بپرس", "جواب AI")
        assert len(engine.calls) == 1 and manager.limits.totals()["ai_calls"] == 1
    finally:
        manager.stop()


def test_chat_cap_message_and_owner_alert_end_to_end(tmp_path, tg, bale, monkeypatch):
    manager, products, orders, settings, engine = shop(
        tmp_path, tg, bale, monkeypatch, max_ai_messages_per_chat_per_day=2, max_ai_messages_per_day_total=2
    )
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        send(tg, 900, f"/owner {manager.owner_console.new_link_code()}", "ثبت شد")
        send(tg, 10, "یک", "جواب AI")
        send(tg, 10, "دو", "جواب AI", since=1)
        send(tg, 10, "سه", "به سقفِ پرسش")
        assert len(engine.calls) == 2
        assert wait_until(lambda: any("سقفِ روزانه" in m for m in tg.sent_to(900)))
        assert sum("سقفِ روزانه" in m for m in tg.sent_to(900)) == 1  # یک‌باره
        assert manager.attention.count_open() >= 1
    finally:
        manager.stop()
