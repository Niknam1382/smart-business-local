"""R5 — پشتیبانیِ انسانی (handoff)، ساعتِ کاری و مسیریابیِ Reply."""

import asyncio
from datetime import datetime, timezone

import pytest
from fake_servers import FakeBotApiServer
from helpers import wait_until
from test_shop_e2e import send, shop, status, tap  # noqa: F401

from app.core import working_hours
from app.core.bot_pipeline import IncomingMessage
from app.core.conversations import ConversationStore
from app.core.handoff import HandoffService, make_ref, parse_ref
from app.core.settings import AppSettings


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def make_service(tmp_path, owners=True):
    settings = AppSettings(owner_chats={"telegram": "900"} if owners else {})
    clock = Clock()
    owner_msgs, customer_msgs = [], []

    async def send_owner(text):
        owner_msgs.append(text)
        return [("telegram", "900", str(100 + len(owner_msgs)))]

    async def send_customer(platform, chat_id, text):
        customer_msgs.append((platform, chat_id, text))
        return True

    svc = HandoffService(ConversationStore(tmp_path / "c.db"), lambda: settings, send_owner, send_customer, clock)
    return svc, settings, clock, owner_msgs, customer_msgs


def run(coro):
    return asyncio.run(coro)


def ev(chat="55", platform="telegram", text="سلام"):
    return IncomingMessage(platform, chat, "مریم", text)


def test_ref_roundtrip_and_garbage():
    assert make_ref("telegram", "123") == "t123" and parse_ref("t123") == ("telegram", "123") and parse_ref("B77") == ("bale", "77")
    assert parse_ref("x1") is None and parse_ref("t") is None and parse_ref("t12a") is None and parse_ref("") is None


def test_session_lifecycle_expiry_and_reopen(tmp_path):
    svc, settings, clock, owner_msgs, customer_msgs = make_service(tmp_path)
    assert svc.open("telegram", "55", "مریم") is True and svc.open("telegram", "55", "مریم") is False
    assert svc.is_open("telegram", "55") and not svc.is_open("bale", "55")
    clock.now += 3600
    svc.touch("telegram", "55")
    clock.now += 23 * 3600 + 1
    assert svc.expire_stale(24 * 3600) == []  # فعالیتِ اخیر دارد
    clock.now += 2 * 3600
    stale = svc.expire_stale(24 * 3600)
    assert [s.ref for s in stale] == ["t55"] and not svc.is_open("telegram", "55")
    assert svc.get("telegram", "55").closed_reason == "timeout"
    assert svc.open("telegram", "55", "مریم") is True  # دوباره باز می‌شه


def test_flow_handler_notifies_owner_once_and_requires_owner(tmp_path):
    svc, settings, clock, owner_msgs, _ = make_service(tmp_path)
    res = run(svc.flow_handler(ev()))
    assert "ثبت شد" in res.messages[0].text and res.messages[0].rows[0][0].data == "c:hx"
    assert len(owner_msgs) == 1 and "t55" in owner_msgs[0]
    run(svc.flow_handler(ev()))
    assert len(owner_msgs) == 1  # دابل‌تپ اعلانِ تکراری نمی‌سازه
    svc2, *_ = make_service(tmp_path / "x", owners=False)
    res = run(svc2.flow_handler(ev()))
    assert "فعال نیست" in res.messages[0].text and svc2.list_open() == []  # مالک نیست ⇒ پیام‌های مشتری قورت داده نمی‌شه


def test_relay_and_reply_mapping_and_owner_commands(tmp_path):
    svc, settings, clock, owner_msgs, customer_msgs = make_service(tmp_path)
    run(svc.flow_handler(ev()))
    run(svc.relay_customer(ev(text="قیمتِ ارسال؟")))
    assert "قیمتِ ارسال؟" in owner_msgs[-1] and "t55" in owner_msgs[-1]
    owner_msg_id = "102"  # ایدیِ پیامِ فورواردشده
    assert svc.lookup("telegram", "900", owner_msg_id) == ("telegram", "55")
    assert svc.lookup("telegram", "900", "999") is None
    assert "فرستاده شد" in run(svc.owner_reply("telegram", "55", "ارسال رایگانه"))
    assert customer_msgs[-1] == ("telegram", "55", "💬 پشتیبان: ارسال رایگانه")
    assert "t55" in svc.owner_list()
    assert "بسته شد" in run(svc.owner_close("telegram", "55")) and svc.owner_list().startswith("گفتگوی پشتیبانیِ بازی نداری")
    assert "بسته شده" in run(svc.owner_reply("telegram", "55", "دیرشد"))


def test_working_hours_validation_and_tehran_time():
    wh = {"enabled": True, "tz": "Asia/Tehran", "days": {"sat": ["09:00-17:00"], "sun": ["22:00-02:00"]}}
    assert working_hours.validate(wh) is None
    for bad in ({"days": {"xyz": []}}, {"days": {"sat": ["9-17"]}}, {"days": {"sat": ["25:00-26:00"]}}, {"days": {"sat": "09:00-17:00"}}, "x"):
        assert working_hours.validate(bad)
    sat_noon_utc = datetime(2026, 10, 10, 8, 30, tzinfo=timezone.utc)  # شنبه ۱۲:۰۰ تهران (UTC+3:30)
    assert working_hours.is_open(wh, sat_noon_utc)
    assert not working_hours.is_open(wh, datetime(2026, 10, 10, 15, 0, tzinfo=timezone.utc))  # شنبه ۱۸:۳۰
    assert not working_hours.is_open(wh, datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc))  # دوشنبه: بازه ندارد
    assert working_hours.is_open(wh, datetime(2026, 10, 11, 19, 0, tzinfo=timezone.utc))  # یکشنبه ۲۲:۳۰ تهران — بازه‌ی شبانه
    assert working_hours.is_open({"enabled": False, "days": {}}) and working_hours.is_open({}) and working_hours.is_open(None)
    assert working_hours.is_open({"enabled": True, "days": {"sat": ["bad"]}})  # خراب ⇒ همیشه باز، نه کرش


def test_offhours_message_appended_to_started_text(tmp_path):
    svc, settings, *_ = make_service(tmp_path)
    settings.working_hours = {"enabled": True, "days": {}, "message": "فردا ساعت ۹ برمی‌گردیم 🌙"}
    res = run(svc.flow_handler(ev()))
    assert "فردا ساعت ۹ برمی‌گردیم" in res.messages[0].text


# ---------------------------------------------------------------- e2e (تلگرام) ----


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


def test_support_conversation_end_to_end_ai_stays_silent_while_open(tmp_path, tg, bale, monkeypatch):
    manager, products, orders, settings, engine = shop(
        tmp_path, tg, bale, monkeypatch,
        custom_buttons=[{"id": "support", "label": "پشتیبانی", "emoji": "🙋", "action": "support", "config": {}}],
    )
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        code = manager.owner_console.new_link_code()
        send(tg, 900, f"/owner {code}", "ثبت شد")
        send(tg, 10, "🙋 پشتیبانی", "ثبت شد")
        assert wait_until(lambda: any("t10" in m for m in tg.sent_to(900)))
        calls_before = len(engine.calls)
        tg.push_message(10, "سلام، ارسال دارید؟")  # پیامِ مشتری به جای AI به مالک می‌رسه (به مشتری چیزی برنمی‌گرده)
        assert wait_until(lambda: any("سلام، ارسال دارید؟" in m for m in tg.sent_to(900)))
        assert len(engine.calls) == calls_before, "AI در گفتگوی انسانیِ باز نباید جواب بده"
        fwd = [m for m in tg.sent if m["chat_id"] == "900" and "سلام، ارسال دارید؟" in m["text"]][0]
        tg.push_message(900, "بله، رایگان", reply_to=fwd["message_id"])  # Reply روی پیامِ فورواردشده
        assert wait_until(lambda: any("💬 پشتیبان: بله، رایگان" in m for m in tg.sent_to(10)))
        tg.push_message(900, "/reply t10 ممنون از صبرتون")
        assert wait_until(lambda: any("ممنون از صبرتون" in m for m in tg.sent_to(10)))
        tg.push_message(900, "/close t10")
        assert wait_until(lambda: any("بسته شد" in m for m in tg.sent_to(10)))
        send(tg, 10, "حالا AI جواب بده", "جواب AI")  # بعد از بسته‌شدن دوباره AI
        assert len(engine.calls) == calls_before + 1
    finally:
        manager.stop()


def test_customer_can_end_chat_with_button(tmp_path, tg, bale, monkeypatch):
    manager, products, orders, settings, engine = shop(
        tmp_path, tg, bale, monkeypatch,
        custom_buttons=[{"id": "support", "label": "پشتیبانی", "action": "support", "config": {}}],
    )
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        send(tg, 900, f"/owner {manager.owner_console.new_link_code()}", "ثبت شد")
        send(tg, 10, "پشتیبانی", "ثبت شد")
        assert "c:hx" in tg.callback_datas(10)
        tap(tg, 10, "c:hx")
        assert wait_until(lambda: any("مشتری گفتگوی پشتیبانی" in m for m in tg.sent_to(900)))
        assert not manager._handoff.is_open("telegram", "10")  # noqa: SLF001
    finally:
        manager.stop()
