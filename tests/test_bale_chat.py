"""قلم ۲۴ مستر‌پرامپت: چتِ ربات روی بله باید مستقل از «بله‌پی» باشد و هوش مصنوعیِ هر
پیام‌رسان جدا خاموش/روشن شود — هر چهار ترکیب، نه فقط «تلگرام با بله‌پی».
"""

import asyncio

import pytest
from fakes import FakeEngine
from app.core import ai_engine, bot_manager as bm
from app.core.bot_manager import BotManager
from app.core.bot_pipeline import ConversationPipeline, IncomingMessage
from app.core.conversations import ConversationStore
from app.core.settings import AppSettings
from app.core.telegram_adapter import BALE_API_BASE, PLATFORM_BALE, TelegramAdapter
from app.core.usage_limits import UsageLimiter

TG_TOKEN = "123:AAAA-goodtoken"
BALE_TOKEN = "456:BBBB-baletoken"
FAST = dict(debounce_wait=0.05, debounce_max_wait=0.2)


def run(coro):
    return asyncio.run(coro)


def base_settings(**kw):
    s = AppSettings(business_mode="consultant")
    s.system_prompt = "تو فروشنده‌ای."
    for key, value in kw.items():
        setattr(s, key, value)
    return s


# ═══════════════════════════════════════ جدولِ چهارحالته ═══════════════════════════════════════


def manager_for(settings, tmp_path, tg=None):
    store = ConversationStore(db_path=tmp_path / "bale.db")
    factories = {}
    if tg is not None:
        factories = {
            "telegram": lambda s, p: TelegramAdapter(s.get_telegram_token(), p, api_base=tg.base_url, retry_delays=(0.1, 0.3), poll_timeout=1),
            "bale": lambda s, p: TelegramAdapter(s.get_bale_chat_token(), p, api_base=tg.base_url, platform=PLATFORM_BALE, retry_delays=(0.1, 0.3), poll_timeout=1),
        }
    return BotManager(settings, store=store, adapter_factories=factories or None, pipeline_kwargs=FAST, log_dir=tmp_path), store


def test_enabled_platforms_is_the_four_combination_truth_table(tmp_path):
    cases = [
        (dict(), []),
        (dict(telegram_enabled=True), []),  # توکن بدونِ فعال‌سازی یا بالعکس: هیچی
        (dict(telegram_enabled=True, tg=TG_TOKEN), ["telegram"]),
        (dict(bale_chat_enabled=True, bale=BALE_TOKEN), ["bale"]),
        (dict(telegram_enabled=True, tg=TG_TOKEN, bale_chat_enabled=True, bale=BALE_TOKEN), ["telegram", "bale"]),
    ]
    for flags, expected in cases:
        s = base_settings(**{k: v for k, v in flags.items() if k not in ("tg", "bale")})
        if flags.get("tg"):
            s.set_telegram_token(flags["tg"])
        if flags.get("bale"):
            s.set_bale_chat_token(flags["bale"])
        manager, _store = manager_for(s, tmp_path)
        assert manager.enabled_platforms() == expected, flags


def test_each_token_is_stored_in_its_own_secret(tmp_path):
    s = base_settings()
    s.set_bale_chat_token(BALE_TOKEN)
    s.set_telegram_token(TG_TOKEN)
    assert s.get_bale_chat_token() == BALE_TOKEN and s.get_telegram_token() == TG_TOKEN
    assert BALE_TOKEN not in s.bale_chat_token_encrypted and TG_TOKEN not in s.telegram_bot_token_encrypted
    assert s.bale_chat_token_encrypted != s.telegram_bot_token_encrypted
    s.set_bale_chat_token("")
    assert s.get_bale_chat_token() == "" and s.get_telegram_token() == TG_TOKEN  # پاک‌کردنِ یکی، دیگری را نمی‌بَرد


def test_bale_pay_alone_can_run_without_any_messenger(tmp_path):
    """این چهارحالتِ واقعیِ فروشنده است: فقط درگاه، بدونِ هیچ چتی."""
    s = base_settings(bale_pay_enabled=True)
    s.set_bale_pay_bot_token("789:pay")
    s.set_bale_pay_provider_token("provider-token")
    manager, _store = manager_for(s, tmp_path)
    assert manager.enabled_platforms() == [] and manager.can_start() is True
    assert s.bale_pay_configured() and not s.bale_chat_configured()


def test_bale_chat_is_configured_only_with_its_own_token(tmp_path):
    s = base_settings(bale_chat_enabled=True)
    assert s.bale_chat_configured() is False
    s.set_bale_chat_token(BALE_TOKEN)
    assert s.bale_chat_configured() is True
    s.bale_chat_enabled = False
    assert s.bale_chat_configured() is False  # توکن هست ولی پیام‌رسان خاموش


def test_start_is_refused_only_when_nothing_is_configured(tmp_path):
    manager, _store = manager_for(base_settings(), tmp_path)
    with pytest.raises(bm.BotManagerError):
        manager.start()


def test_bale_adapter_points_at_the_bale_api(tmp_path):
    """آداپتورِ بله = همان آداپتورِ تلگرام با میزبانِ API و پلتفرمِ خودش."""
    s = base_settings(bale_chat_enabled=True)
    s.set_bale_chat_token(BALE_TOKEN)
    store = ConversationStore(db_path=tmp_path / "x.db")
    pipeline = ConversationPipeline(s, store=store, **FAST)
    manager = BotManager(s, store=store, pipeline_kwargs=FAST, log_dir=tmp_path)
    adapter = manager._default_factories()["bale"](s, pipeline)
    assert adapter.platform == PLATFORM_BALE
    assert adapter.api_base == BALE_API_BASE == "https://tapi.bale.ai"
    assert TelegramAdapter(TG_TOKEN, pipeline).platform == "telegram"  # رفتارِ پیش‌فرض عوض نشد


# ═══════════════════════════════════ هوش مصنوعیِ جدا برای هر پیام‌رسان ═══════════════════════════════════


def limiter_for(s, store):
    return UsageLimiter(store, lambda: s)


def test_ai_switches_are_per_platform(tmp_path):
    s = base_settings()
    store = ConversationStore(db_path=tmp_path / "u.db")
    limits = limiter_for(s, store)
    assert limits.check_ai("telegram", "1") == "ok" and limits.check_ai("bale", "1") == "ok"
    s.bale_chat_ai = False
    assert limits.check_ai("bale", "1") == "off" and limits.check_ai("telegram", "1") == "ok"
    s.telegram_ai = False
    assert limits.check_ai("telegram", "1") == "off"
    s.telegram_ai = s.bale_chat_ai = True
    assert limits.check_ai("bale", "1") == "ok"
    s.ai_kill_switch = True  # سوییچِ اضطراری روی همه غالب است
    assert limits.check_ai("bale", "1") == "kill" and limits.check_ai("telegram", "1") == "kill"


def test_pipeline_answers_a_bale_customer_without_calling_the_model(tmp_path, monkeypatch):
    engine = FakeEngine()
    monkeypatch.setattr(ai_engine, "build_engine_from_settings", lambda s: engine)
    s = base_settings(bale_chat_ai=False)
    store = ConversationStore(db_path=tmp_path / "p.db")
    pipeline = ConversationPipeline(s, store=store, limits=limiter_for(s, store), **FAST)
    sent = []

    async def go():
        async def send(text):
            sent.append(text)

        await pipeline.handle_incoming(IncomingMessage("bale", "7", "مریم", "قیمت؟"), send)
        await asyncio.sleep(0.3)
        await pipeline.handle_incoming(IncomingMessage("telegram", "8", "رضا", "قیمت؟"), send)
        await asyncio.sleep(0.3)
        await pipeline.shutdown()

    run(go())
    assert len(engine.calls) == 1, "فقط تلگرام باید مدل را صدا بزند"
    assert any("خاموش" in text for text in sent) and any(text.startswith("پاسخ:") for text in sent)


def test_bale_conversations_are_kept_separate_from_telegram(tmp_path, monkeypatch):
    engine = FakeEngine()
    monkeypatch.setattr(ai_engine, "build_engine_from_settings", lambda s: engine)
    s = base_settings()
    store = ConversationStore(db_path=tmp_path / "sep.db")
    pipeline = ConversationPipeline(s, store=store, **FAST)

    async def go():
        async def send(text):
            pass

        await pipeline.handle_incoming(IncomingMessage("bale", "55", "مریم", "سلام"), send)
        await asyncio.sleep(0.3)
        await pipeline.shutdown()

    run(go())
    assert [c.platform for c in store.list_conversations()] == ["bale"]
    assert store.get_history("bale", "55", limit=5)[0].content == "سلام"
    assert engine.calls[0][2] == "سلام"
