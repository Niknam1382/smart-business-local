import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fakes import FakeEngine, FakeSettings

from app.core import ai_engine
from app.core.bot_pipeline import (
    DEFAULT_ERROR_REPLY_FA,
    ConversationPipeline,
    IncomingMessage,
    RateLimiter,
)
from app.core.conversations import ConversationStore

FAST = dict(debounce_wait=0.1, debounce_max_wait=0.4)


def msg(chat_id, text, platform="telegram", name="سارا"):
    return IncomingMessage(platform=platform, chat_id=str(chat_id), display_name=name, text=text)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """(settings, store, engines-list) با build_engine_from_settings جعلی."""
    settings = FakeSettings(tmp_path)
    store = ConversationStore(db_path=tmp_path / "c.db")
    engines = []

    def build(_settings):
        eng = FakeEngine()
        engines.append(eng)
        return eng

    monkeypatch.setattr(ai_engine, "build_engine_from_settings", build)
    return settings, store, engines


def run(coro):
    return asyncio.run(coro)


def test_normal_flow_history_without_duplication_and_engine_cached(env):
    settings, store, engines = env

    async def go():
        sent = []

        async def send(text):
            sent.append(text)

        p = ConversationPipeline(settings, store=store, **FAST)
        await p.handle_incoming(msg(1, "سلام"), send)
        await asyncio.sleep(0.5)
        assert sent == ["پاسخ: سلام"]
        assert engines[0].calls[0] == ("تو یک فروشنده‌ی مفید هستی.", [], "سلام")

        await p.handle_incoming(msg(1, "قیمت چنده؟"), send)
        await asyncio.sleep(0.5)
        _, history, user_msg = engines[0].calls[1]
        assert user_msg == "قیمت چنده؟"
        # فقط دو پیام قبلی (سلام + پاسخش)؛ پیام جاری نباید توی history هم بیاد
        assert [m.content for m in history] == ["سلام", "پاسخ: سلام"]
        assert len(engines) == 1  # تنظیمات عوض نشده → همون موتور (کش)
        await p.shutdown()

    run(go())


def test_engine_rebuilt_only_when_settings_change_and_old_unloaded(env):
    settings, store, engines = env

    async def go():
        async def send(text):
            pass

        p = ConversationPipeline(settings, store=store, **FAST)
        await p.handle_incoming(msg(1, "الف"), send)
        await asyncio.sleep(0.4)
        settings.api_model_name = "gpt-4o"  # امضای تنظیمات عوض شد
        await p.handle_incoming(msg(1, "ب"), send)
        await asyncio.sleep(0.4)
        assert len(engines) == 2 and engines[0].unloaded is True and engines[1].unloaded is False
        await p.shutdown()

    run(go())


def test_burst_of_messages_is_merged_into_one_ai_call(env):
    settings, store, engines = env

    async def go():
        sent = []

        async def send(text):
            sent.append(text)

        p = ConversationPipeline(settings, store=store, **FAST)
        for text in ["سلام", "گوشی X دارین؟", "قیمتش؟"]:
            await p.handle_incoming(msg(1, text), send)
            await asyncio.sleep(0.03)
        await asyncio.sleep(0.5)
        assert len(engines[0].calls) == 1
        assert engines[0].calls[0][2] == "سلام\nگوشی X دارین؟\nقیمتش؟"
        assert len(sent) == 1
        await p.shutdown()

    run(go())


def test_blocked_user_gets_no_reply_and_nothing_stored(env):
    settings, store, engines = env

    async def go():
        sent = []

        async def send(text):
            sent.append(text)

        store.ensure_conversation("telegram", "1", "مزاحم")
        store.set_blocked("telegram", "1", True)
        p = ConversationPipeline(settings, store=store, **FAST)
        await p.handle_incoming(msg(1, "پیام مزاحم"), send)
        await asyncio.sleep(0.4)
        assert sent == [] and engines == []
        assert store.get_messages("telegram", "1") == []
        # رفع بلاک → دوباره جواب می‌گیره
        store.set_blocked("telegram", "1", False)
        await p.handle_incoming(msg(1, "سلام"), send)
        await asyncio.sleep(0.4)
        assert sent == ["پاسخ: سلام"]
        await p.shutdown()

    run(go())


def test_memory_disabled_sends_no_history(env):
    settings, store, engines = env

    async def go():
        async def send(text):
            pass

        p = ConversationPipeline(settings, store=store, **FAST)
        await p.handle_incoming(msg(1, "اول"), send)
        await asyncio.sleep(0.4)
        store.set_memory_enabled("telegram", "1", False)
        await p.handle_incoming(msg(1, "دوم"), send)
        await asyncio.sleep(0.4)
        assert engines[0].calls[1][1] == []  # بدون حافظه: تاریخچه‌ای نمی‌ره
        # ولی خودِ مکالمه برای نمایش توی UI همچنان ذخیره می‌شه
        assert len(store.get_messages("telegram", "1")) == 4
        await p.shutdown()

    run(go())


def test_ai_error_falls_back_to_persian_apology(env, monkeypatch):
    settings, store, _ = env

    class Failing(FakeEngine):
        def chat(self, *a):
            raise ai_engine.AiEngineError("خطای فرضی اتصال")

    monkeypatch.setattr(ai_engine, "build_engine_from_settings", lambda s: Failing())

    async def go():
        sent = []

        async def send(text):
            sent.append(text)

        p = ConversationPipeline(settings, store=store, **FAST)
        await p.handle_incoming(msg(2, "کمک"), send)
        await asyncio.sleep(0.4)
        assert sent == [DEFAULT_ERROR_REPLY_FA]
        assert store.get_messages("telegram", "2")[-1].content == DEFAULT_ERROR_REPLY_FA
        await p.shutdown()

    run(go())


def test_unexpected_exception_also_falls_back(env, monkeypatch):
    settings, store, _ = env

    class Crashy(FakeEngine):
        def chat(self, *a):
            raise KeyError("باگ غیرمنتظره")

    monkeypatch.setattr(ai_engine, "build_engine_from_settings", lambda s: Crashy())

    async def go():
        sent = []

        async def send(text):
            sent.append(text)

        p = ConversationPipeline(settings, store=store, **FAST)
        await p.handle_incoming(msg(3, "سلام"), send)
        await asyncio.sleep(0.4)
        assert sent == [DEFAULT_ERROR_REPLY_FA]
        await p.shutdown()

    run(go())


def test_send_failure_does_not_crash_and_reply_is_still_stored(env):
    settings, store, _ = env

    async def go():
        async def broken_send(text):
            raise RuntimeError("شبکه قطع شد")

        p = ConversationPipeline(settings, store=store, **FAST)
        await p.handle_incoming(msg(1, "سلام"), broken_send)
        await asyncio.sleep(0.4)
        assert store.get_messages("telegram", "1")[-1].role == "assistant"
        await p.shutdown()

    run(go())


def test_same_chat_is_processed_sequentially_with_up_to_date_history(env, monkeypatch):
    settings, store, _ = env
    slow = FakeEngine(delay=0.4)
    monkeypatch.setattr(ai_engine, "build_engine_from_settings", lambda s: slow)

    async def go():
        sent = []

        async def send(text):
            sent.append(text)

        p = ConversationPipeline(settings, store=store, **FAST)
        await p.handle_incoming(msg(1, "اول"), send)
        await asyncio.sleep(0.25)  # دسته‌ی اول flush شده و AI (۰.۴ثانیه) در حال کاره
        await p.handle_incoming(msg(1, "دوم"), send)
        await asyncio.sleep(1.3)
        assert sent == ["پاسخ: اول", "پاسخ: دوم"]  # ترتیب حفظ شد
        # دسته‌ی دوم باید بعد از کامل‌شدن اولی اجرا شده باشه → تاریخچه شامل جواب اول
        assert [m.content for m in slow.calls[1][1]] == ["اول", "پاسخ: اول"]
        assert slow.max_active == 1
        await p.shutdown()

    run(go())


@pytest.mark.parametrize("concurrent_safe, expected_max", [(False, 1), (True, 2)])
def test_engine_lock_only_for_non_concurrent_safe_engines(env, monkeypatch, concurrent_safe, expected_max):
    settings, store, _ = env
    eng = FakeEngine(delay=0.3, concurrent_safe=concurrent_safe)
    monkeypatch.setattr(ai_engine, "build_engine_from_settings", lambda s: eng)

    async def go():
        async def send(text):
            pass

        p = ConversationPipeline(settings, store=store, **FAST)
        await p.handle_incoming(msg(1, "الف"), send)
        await p.handle_incoming(msg(2, "ب"), send)  # دو مشتری هم‌زمان
        await asyncio.sleep(1.0)
        assert len(eng.calls) == 2
        assert eng.max_active == expected_max  # مدل محلی: سریالی؛ API: هم‌زمان
        await p.shutdown()

    run(go())


def test_flood_protection_drops_excess_messages(env):
    settings, store, engines = env

    async def go():
        async def send(text):
            pass

        p = ConversationPipeline(settings, store=store, flood_max=5, flood_window=60, **FAST)
        for i in range(12):
            await p.handle_incoming(msg(1, f"spam {i}"), send)
        await asyncio.sleep(0.5)
        merged = engines[0].calls[0][2].split("\n")
        assert merged == [f"spam {i}" for i in range(5)]  # ۵ تای اول رسید، ۷ تای بعدی دور ریخته شد
        # مشتری دیگه تحت‌تأثیر قرار نمی‌گیره
        await p.handle_incoming(msg(2, "سلام"), send)
        await asyncio.sleep(0.4)
        assert any(c[2] == "سلام" for e in engines for c in e.calls)
        await p.shutdown()

    run(go())


def test_rate_limiter_sliding_window():
    now = [0.0]
    rl = RateLimiter(max_events=2, window_seconds=10, clock=lambda: now[0])
    assert rl.allow("a") and rl.allow("a")
    assert not rl.allow("a")
    assert rl.allow("b")  # کلید دیگه مستقل
    now[0] = 10.5  # پنجره گذشت
    assert rl.allow("a")


def test_conversation_created_even_when_flood_dropped_so_owner_can_block(env):
    settings, store, _ = env

    async def go():
        async def send(text):
            pass

        p = ConversationPipeline(settings, store=store, flood_max=1, flood_window=60, **FAST)
        await p.handle_incoming(msg(9, "الف", name="مزاحم"), send)
        await p.handle_incoming(msg(9, "ب", name="مزاحم"), send)  # دور ریخته می‌شه
        assert [c.display_name for c in store.list_conversations()] == ["مزاحم"]
        await p.shutdown()

    run(go())


def test_memory_expires_after_configured_inactivity(env):
    settings, store, engines = env
    settings.memory_expire_hours = 1  # ۱ ساعت بی‌فعالیتی یعنی شروع تازه

    async def go():
        async def send(text):
            pass

        p = ConversationPipeline(settings, store=store, **FAST)
        await p.handle_incoming(msg(1, "اول"), send)
        await asyncio.sleep(0.4)

        # وانمود می‌کنیم آخرین پیام مال ۲ ساعت پیش بوده (بیشتر از سقف ۱ ساعت)
        old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        conn = store._connection()  # noqa: SLF001 — فقط برای تست، شبیه‌سازی گذر زمان
        conn.execute("UPDATE messages SET created_at = ? WHERE id = (SELECT MAX(id) FROM messages)", (old_time,))
        conn.commit()

        await p.handle_incoming(msg(1, "دوم، بعد از یه مکث طولانی"), send)
        await asyncio.sleep(0.4)
        _, history, _ = engines[0].calls[1]
        assert history == [], "بعد از گذشت بیشتر از سقف، نباید تاریخچه‌ی قدیمی فرستاده بشه"
        await p.shutdown()

    run(go())


def test_memory_does_not_expire_within_window(env):
    settings, store, engines = env
    settings.memory_expire_hours = 24

    async def go():
        async def send(text):
            pass

        p = ConversationPipeline(settings, store=store, **FAST)
        await p.handle_incoming(msg(1, "اول"), send)
        await asyncio.sleep(0.4)
        await p.handle_incoming(msg(1, "دوم، بلافاصله"), send)
        await asyncio.sleep(0.4)
        _, history, _ = engines[0].calls[1]
        assert len(history) == 2, "چون هنوز داخل بازه‌ایم، تاریخچه باید بمونه"
        await p.shutdown()

    run(go())


def test_memory_expiry_disabled_by_default_means_history_never_expires(env):
    settings, store, engines = env
    assert settings.memory_expire_hours == 0

    async def go():
        async def send(text):
            pass

        p = ConversationPipeline(settings, store=store, **FAST)
        await p.handle_incoming(msg(1, "اول"), send)
        await asyncio.sleep(0.4)
        old_time = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        conn = store._connection()  # noqa: SLF001
        conn.execute("UPDATE messages SET created_at = ? WHERE id = (SELECT MAX(id) FROM messages)", (old_time,))
        conn.commit()
        await p.handle_incoming(msg(1, "دوم"), send)
        await asyncio.sleep(0.4)
        _, history, _ = engines[0].calls[1]
        assert len(history) == 2, "با ۰ (هیچ‌وقت)، حتی بعد از یه ماه هم نباید منقضی بشه"
        await p.shutdown()

    run(go())


def test_configurable_history_limit_is_respected(env):
    settings, store, engines = env
    settings.memory_history_limit = 2

    async def go():
        async def send(text):
            pass

        p = ConversationPipeline(settings, store=store, **FAST)
        for i in range(4):
            await p.handle_incoming(msg(1, f"پیام {i}"), send)
            await asyncio.sleep(0.4)
        _, last_history, _ = engines[0].calls[-1]
        assert len(last_history) == 2, f"باید فقط ۲ پیامِ آخر پاس داده بشه، نه {len(last_history)}"
        await p.shutdown()

    run(go())


def test_missing_memory_settings_fields_default_gracefully(env):
    """یه شیء تنظیمات ساده‌تر (بدون memory_expire_hours/memory_history_limit)
    نباید کرش کنه — سازگاری با نسخه‌های قدیمی‌تر تنظیمات."""
    settings, store, engines = env
    del settings.memory_expire_hours
    del settings.memory_history_limit

    async def go():
        async def send(text):
            pass

        p = ConversationPipeline(settings, store=store, **FAST)
        await p.handle_incoming(msg(1, "سلام"), send)
        await asyncio.sleep(0.4)
        assert len(engines) == 1 and engines[0].calls[0][2] == "سلام"
        await p.shutdown()

    run(go())


def test_pipeline_without_store_agent_behaves_exactly_as_before(env):
    """store_agent=None (پیش‌فرض) -> هیچ رفتاری عوض نشه، سازگار با حالت مشاوره‌ای."""
    settings, store, engines = env

    async def go():
        sent = []

        async def send(text):
            sent.append(text)

        p = ConversationPipeline(settings, store=store, **FAST)  # store_agent پاس داده نشده
        await p.handle_incoming(msg(1, "فروشگاه"), send)
        await asyncio.sleep(0.4)
        assert sent == ["پاسخ: فروشگاه"]  # چون store_agent نیست، همه‌چی از AI رد می‌شه
        assert len(engines) == 1
        await p.shutdown()

    run(go())
