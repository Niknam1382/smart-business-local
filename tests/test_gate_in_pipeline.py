"""N13 + N7 در سطحِ پایپ‌لاین با دروازه‌ی جعلی (بدونِ شبکه): مسیرهای دفاعی (fail-open) و ترتیبِ بررسی‌ها."""

import asyncio

import pytest
from fakes import FakeEngine, FakeSettings

from app.core import ai_engine
from app.core.bot_pipeline import ConversationPipeline, IncomingMessage
from app.core.channel_gate import Channel, Verdict
from app.core.conversations import ConversationStore
from app.core.customers import CustomerStore

FAST = dict(debounce_wait=0.05, debounce_max_wait=0.2)
CHANNEL = Channel("telegram", "@shop_channel", "کانال فروشگاه", "https://t.me/shop_channel")
GATE_TEXT = "اول توی کانالِ زیر عضو شو"


def run(coro):
    return asyncio.run(coro)


def msg(chat, text, **kw):
    return IncomingMessage(platform="telegram", chat_id=str(chat), display_name="سارا", text=text, **kw)


class StubGate:
    """جایگزینِ ChannelGate: رفتارِ دلخواه، ثبتِ تماس‌ها."""

    def __init__(self, verdict=None, check_raises=None, enabled_raises=None, covers=True):
        self.verdict = verdict if verdict is not None else Verdict(False, [CHANNEL])
        self.check_raises, self.enabled_raises, self.covers = check_raises, enabled_raises, covers
        self.calls = []

    def enabled_for(self, platform, point):
        if self.enabled_raises:
            raise self.enabled_raises
        return self.covers

    def channels(self, platform):
        return [CHANNEL] if self.covers else []

    async def check(self, platform, user_id, *, force=False):
        self.calls.append((platform, user_id, force))
        if self.check_raises:
            raise self.check_raises
        return self.verdict


class StubAdmins:
    def __init__(self, role="", raises=None):
        self.role, self.raises = role, raises

    def role_of(self, platform, chat_id):
        if self.raises:
            raise self.raises
        return self.role


@pytest.fixture
def env(tmp_path, monkeypatch):
    settings = FakeSettings(tmp_path)
    store = ConversationStore(db_path=tmp_path / "c.db")
    engines = []

    def build(_settings):
        eng = FakeEngine()
        engines.append(eng)
        return eng

    monkeypatch.setattr(ai_engine, "build_engine_from_settings", build)
    return settings, store, engines


async def converse(env, messages, **kwargs):
    settings, store, engines = env
    sent = []

    async def send(text):
        sent.append(text)

    pipeline = ConversationPipeline(settings, store=store, **FAST, **kwargs)
    for m in messages:
        await pipeline.handle_incoming(m, send)
    await asyncio.sleep(0.4)
    await pipeline.shutdown()
    return sent, engines, store


def ai_calls(engines):
    return [c for e in engines for c in e.calls]


def test_a_blocked_customer_gets_the_prompt_and_the_ai_is_never_called(env):
    gate = StubGate()
    sent, engines, _ = run(converse(env, [msg(1, "سلام")], channel_gate=gate))
    assert len(sent) == 1 and GATE_TEXT in sent[0] and ai_calls(engines) == []
    assert gate.calls == [("telegram", "1", False)]


def test_members_pass_through_to_the_ai(env):
    sent, engines, _ = run(converse(env, [msg(1, "سلام")], channel_gate=StubGate(Verdict(True))))
    assert sent == ["پاسخ: سلام"] and len(ai_calls(engines)) == 1


def test_a_gate_that_crashes_while_checking_never_locks_the_customer(env):
    gate = StubGate(check_raises=RuntimeError("bug in the gate"))
    sent, engines, _ = run(converse(env, [msg(1, "سلام")], channel_gate=gate))
    assert sent == ["پاسخ: سلام"] and len(gate.calls) == 1


def test_a_gate_with_broken_configuration_never_locks_the_customer(env):
    gate = StubGate(enabled_raises=RuntimeError("corrupt settings"))
    sent, engines, _ = run(converse(env, [msg(1, "سلام")], channel_gate=gate))
    assert sent == ["پاسخ: سلام"] and gate.calls == []


def test_a_gate_that_does_not_cover_this_point_is_skipped_entirely(env):
    gate = StubGate(covers=False)
    sent, _, _ = run(converse(env, [msg(1, "سلام")], channel_gate=gate))
    assert sent == ["پاسخ: سلام"] and gate.calls == []


def test_start_always_forces_a_fresh_membership_check(env):
    gate = StubGate()
    run(converse(env, [msg(1, "/start"), msg(1, "سلام"), msg(2, "/start@my_bot")], channel_gate=gate))
    assert gate.calls == [("telegram", "1", True), ("telegram", "1", False), ("telegram", "2", True)]


def test_owner_and_admins_are_never_checked_but_a_failing_role_lookup_is_not_an_exemption(env):
    gate = StubGate()
    sent, engines, _ = run(converse(env, [msg(1, "سلام")], channel_gate=gate, admins=StubAdmins("support")))
    assert sent == ["پاسخ: سلام"] and gate.calls == []
    gate2 = StubGate()
    sent, engines, _ = run(converse(env, [msg(1, "سلام")], channel_gate=gate2, admins=StubAdmins(raises=RuntimeError("db"))))
    assert len(sent) == 1 and GATE_TEXT in sent[0] and len(gate2.calls) == 1


def test_the_join_button_with_a_crashing_gate_lets_the_customer_in_as_a_fresh_start(env):
    gate = StubGate(check_raises=RuntimeError("bug"))
    joined = msg(1, "", callback_data="c:joined", callback_id="cb1", message_id="7")
    sent, engines, _ = run(converse(env, [joined], channel_gate=gate))
    assert [c[2] for c in ai_calls(engines)] == ["/start"]  # پیامِ ساختگیِ /start وارد گفتگو شد


def test_the_join_button_when_still_missing_stops_everything(env):
    gate = StubGate()
    joined = msg(1, "", callback_data="c:joined", callback_id="cb1", message_id="7")
    sent, engines, _ = run(converse(env, [joined], channel_gate=gate))
    assert sent == [] and ai_calls(engines) == [] and gate.calls == [("telegram", "1", True)]


def test_the_join_button_without_any_gate_object_is_a_harmless_noop(env):
    """(در برنامه‌ی واقعی همیشه یک دروازه هست؛ «خاموش» = بدونِ کانال، که تستِ e2e پوشانده.) اینجا فقط: کلیکِ بی‌صاحب خطا نمی‌دهد."""
    joined = msg(1, "", callback_data="c:joined", callback_id="cb1", message_id="7")
    sent, engines, _ = run(converse(env, [joined]))
    assert sent == [] and ai_calls(engines) == []


def test_stop_never_reaches_the_ai_and_start_resubscribes_with_one_confirmation(env):
    settings, store, _ = env
    sent, engines, store = run(converse(env, [msg(1, "سلام"), msg(1, "/stop"), msg(1, "/stop"), msg(1, "/start"), msg(1, "/start")]))
    to_ai = "\n".join(c[2] for c in ai_calls(engines))  # پیام‌های پشت‌سرهم عمداً ادغام می‌شن
    assert "/stop" not in to_ai and to_ai.count("/start") == 2 and "سلام" in to_ai  # /stop هرگز به AI نمی‌رسد؛ /start عادی ادامه می‌دهد
    assert sum("دیگه پیامِ همگانی برات نمی‌فرستیم" in s for s in sent) == 2  # هر /stop تأیید می‌گیرد
    assert sum("دوباره پیام‌های همگانی برات فعال شد" in s for s in sent) == 1  # فقط یک بار (اولین /start بعد از /stop)
    assert not CustomerStore(store).get("telegram", "1").opted_out


def test_stop_works_even_when_the_flood_limit_is_exhausted(env):
    settings, store, _ = env
    sent, engines, store = run(converse(env, [msg(1, "الف"), msg(1, "ب"), msg(1, "ج"), msg(1, "/stop")], flood_max=1, flood_window=60))
    assert CustomerStore(store).get("telegram", "1").opted_out  # حقِ توقف هرگز گرفتارِ محدودیتِ سیل نمی‌شود
    assert any("دیگه پیامِ همگانی برات نمی‌فرستیم" in s for s in sent)


def test_callbacks_never_trigger_stop_or_start_handling(env):
    sent, engines, store = run(converse(env, [msg(1, "سلام"), msg(1, "/stop", callback_data="x:y", callback_id="c1")]))
    assert not CustomerStore(store).get("telegram", "1").opted_out
