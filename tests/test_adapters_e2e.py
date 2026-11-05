"""
تست سرتاسریِ آداپتورِ تلگرام: aiogramِ واقعی با HTTPِ واقعی روی loopback به سرورِ جعلی
وصل می‌شه (tests/fake_servers.py). ربات مثلِ برنامه‌ی واقعی توی تردِ پس‌زمینه (BotManager)
اجرا می‌شه — پس مشکل سیگنال (handle_signals) روی تردِ غیرِ اصلی هم واقعاً تست می‌شه.

نسخه‌ی ۱.۰.۰: تلگرام تنها پیام‌رسانِ گفتگوست. «بله» فقط به‌عنوانِ درگاهِ پرداختِ بله‌پی می‌ماند
(تستش در test_bale_pay.py و test_commerce_e2e.py)؛ پس این فایل هیچ BaleAdapter ندارد.

این فایل ابزارِ مشترکِ تست‌های سرتاسری را هم صادر می‌کند: ``TG_TOKEN``، ``make_settings``،
``make_manager``، ``status`` — بقیه از اینجا import می‌کنن.
"""

import pytest
from fake_servers import FakeBotApiServer, free_port
from fakes import FakeEngine
from helpers import wait_until

from app.core import ai_engine
from app.core.adapter_common import (
    ERR_BAD_PROXY,
    ERR_CONFLICT,
    ERR_INVALID_TOKEN,
    ERR_NO_CONNECTION,
    ERR_WEBHOOK,
    STATE_CONNECTING,
    STATE_ERROR,
    STATE_STOPPED,
)
from app.core.bot_manager import PLATFORMS, BotManager
from app.core.conversations import ConversationStore
from app.core.settings import AppSettings
from app.core.telegram_adapter import (
    MSG_BAD_PROXY,
    MSG_CONFLICT,
    MSG_INVALID_TOKEN,
    MSG_NO_CONNECTION,
    MSG_WEBHOOK,
    TelegramAdapter,
)
from app.core.telegram_adapter import check_token as tg_check

TG_TOKEN = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
FAST = dict(debounce_wait=0.15, debounce_max_wait=0.5)


@pytest.fixture
def tg():
    srv = FakeBotApiServer(username="tg_shop_bot").start()
    yield srv
    srv.stop()


@pytest.fixture
def engine(monkeypatch):
    eng = FakeEngine(reply=lambda text: f"پاسخ: {text}")
    monkeypatch.setattr(ai_engine, "build_engine_from_settings", lambda s: eng)
    return eng


def make_settings(tg_token: str = TG_TOKEN):
    """تنظیماتِ پایه‌ی تست‌های سرتاسری: فروشگاهِ فارسی‌زبان با توکنِ تلگرام."""
    s = AppSettings(business_mode="store")
    s.system_prompt = "تو فروشنده‌ای."
    s.set_telegram_token(tg_token)
    return s


def make_manager(tmp_path, settings, tg, product_store=None, order_store=None, **tg_kwargs):
    store = ConversationStore(db_path=tmp_path / "e2e.db")
    factories = {
        "telegram": lambda s, p: TelegramAdapter(
            s.get_telegram_token(), p, api_base=tg.base_url, retry_delays=(0.1, 0.3), poll_timeout=1, **tg_kwargs
        ),
    }
    return (
        BotManager(
            settings,
            store=store,
            product_store=product_store,
            order_store=order_store,
            adapter_factories=factories,
            pipeline_kwargs=FAST,
            log_dir=tmp_path,
        ),
        store,
    )


def status(manager, name):
    return manager.get_status().platforms[name]


# ------------------------------------------------------------ مسیر شاد ----


def test_telegram_is_the_only_messenger_platform():
    """بله دیگر پیام‌رسان نیست؛ هر چیزِ دیگری در «پلتفرم‌ها» یعنی بازگشتِ باگ."""
    assert PLATFORMS == ("telegram",)


def test_full_flow_and_clean_stop(tmp_path, tg, engine):
    manager, store = make_manager(tmp_path, make_settings(), tg)
    manager.start()
    try:
        assert manager.is_running()
        assert wait_until(lambda: status(manager, "telegram").connected)
        assert status(manager, "telegram").username == "tg_shop_bot"

        # دو پیام سریع → یک پاسخ ادغام‌شده
        tg.push_message(555, "سلام", first_name="سارا")
        tg.push_message(555, "قیمت چنده؟", first_name="سارا")
        assert wait_until(lambda: tg.sent_to(555) == ["پاسخ: سلام\nقیمت چنده؟"], timeout=20)

        convs = {(c.platform, c.chat_id): c.display_name for c in store.list_conversations()}
        assert convs == {("telegram", "555"): "سارا"}
        assert [m.role for m in store.get_messages("telegram", "555")] == ["user", "assistant"]

        # بلاک از طریق دیتابیس (همون کاری که UI می‌کنه) → دیگه جواب نمی‌گیره
        store.set_blocked("telegram", "555", True)
        before = len(tg.sent)
        polls = tg.calls.count("getUpdates")
        tg.push_message(555, "پیام بعد از بلاک")
        # سیگنالِ مثبت: دورِ *بعدیِ* پولینگ یعنی آپدیتِ بلاک‌شده گرفته و رد شده؛
        # هیچ‌وقت «صبرِ حدسی» برای اثباتِ نیامدنِ پاسخ نمی‌کنیم
        assert wait_until(lambda: tg.calls.count("getUpdates") > polls, timeout=20)
        assert len(tg.sent) == before
    finally:
        assert manager.stop(timeout=10) is True
    assert not manager.is_running()
    assert status(manager, "telegram").state == STATE_STOPPED


def test_crm_captures_identity_from_real_telegram_traffic(tmp_path, tg, engine):
    """N12: هویتِ فرستنده از aiogramِ واقعی تا جدولِ مشتریان می‌رسه (نه فقط واحد)."""
    manager, _store = make_manager(tmp_path, make_settings(), tg)
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected)
        tg.push_message(555, "سلام", first_name="سارا", last_name="احمدی", username="sara_a", language_code="fa")
        assert wait_until(lambda: tg.sent_to(555), timeout=20)
        customers = manager.customers
        t_c = customers.get("telegram", "555")
        assert (t_c.first_name, t_c.last_name, t_c.username, t_c.language_code, t_c.msg_count) == ("سارا", "احمدی", "sara_a", "fa", 1)
        assert t_c.phone == ""  # شماره فقط با «اشتراکِ شماره» توسط خودِ مشتری
        assert {c.display_name for c in customers.list()} == {"سارا احمدی"}
    finally:
        assert manager.stop(timeout=10) is True


def test_stop_is_fast_even_with_pending_longpoll(tmp_path, tg, engine):
    import time

    manager, _ = make_manager(tmp_path, make_settings(), tg)
    manager.start()
    assert wait_until(lambda: status(manager, "telegram").connected)
    t0 = time.monotonic()
    assert manager.stop(timeout=10)
    assert time.monotonic() - t0 < 3.0  # درخواست‌های long-poll در حال انتظار لغو می‌شن، نه صبر تا تایم‌اوت


def test_restart_works(tmp_path, tg, engine):
    manager, _ = make_manager(tmp_path, make_settings(), tg)
    manager.start()
    assert wait_until(lambda: status(manager, "telegram").connected)
    manager.restart(timeout=10)
    assert wait_until(lambda: status(manager, "telegram").connected)
    tg.push_message(1, "بعد از ری‌استارت")
    assert wait_until(lambda: tg.sent_to(1) == ["پاسخ: بعد از ری‌استارت"], timeout=20)
    assert manager.stop(timeout=10)


def test_start_without_token_gives_persian_error(tmp_path, tg):
    from app.core.bot_manager import BotManagerError

    manager, _ = make_manager(tmp_path, make_settings(""), tg)
    assert manager.enabled_platforms() == []
    with pytest.raises(BotManagerError, match="توکن"):
        manager.start()
    assert not manager.is_running()


def test_disabled_telegram_does_not_start_anything(tmp_path, tg, engine):
    settings = make_settings()
    settings.telegram_enabled = False  # توکن دارد ولی غیرفعاله
    manager, _ = make_manager(tmp_path, settings, tg)
    assert manager.enabled_platforms() == []
    with pytest.raises(Exception):
        manager.start()
    assert "getMe" not in tg.calls  # اصلاً به سرور وصل نشد


# ------------------------------------------------------- خطاها و بازیابی ----


def test_invalid_token_shows_persian_error_and_manager_ends_by_itself(tmp_path, tg, engine):
    tg.mode = "unauthorized"
    manager, _ = make_manager(tmp_path, make_settings(), tg)
    manager.start()
    assert wait_until(lambda: not manager.is_running(), timeout=20)  # آداپتور خطای نهایی گرفت و تموم شد
    st_tg = status(manager, "telegram")
    assert st_tg.state == STATE_ERROR and st_tg.error == MSG_INVALID_TOKEN and st_tg.error_code == ERR_INVALID_TOKEN


def test_malformed_token_is_handled_without_network(tmp_path, tg, engine):
    manager, _ = make_manager(tmp_path, make_settings(tg_token="این-توکن-نیست"), tg)
    manager.start()
    assert wait_until(lambda: not manager.is_running(), timeout=20)
    assert status(manager, "telegram").error == MSG_INVALID_TOKEN
    assert tg.calls == []  # حتی یه درخواست هم نرفت


def test_conflict_needs_three_consecutive_and_is_reported_honestly(tmp_path, tg, engine):
    tg.mode = "conflict"
    manager, _ = make_manager(tmp_path, make_settings(), tg)
    manager.start()
    assert wait_until(lambda: status(manager, "telegram").state == STATE_ERROR, timeout=20)
    assert status(manager, "telegram").error == MSG_CONFLICT
    assert status(manager, "telegram").error_code == ERR_CONFLICT
    assert tg.calls.count("getUpdates") >= 3  # سه تلاش قبل از تسلیم
    assert wait_until(lambda: not manager.is_running(), timeout=20)


def test_webhook_conflict_gets_specific_message(tmp_path, tg, engine):
    tg.mode = "webhook_conflict"
    manager, _ = make_manager(tmp_path, make_settings(), tg)
    manager.start()
    assert wait_until(lambda: status(manager, "telegram").state == STATE_ERROR, timeout=20)
    assert status(manager, "telegram").error == MSG_WEBHOOK
    assert status(manager, "telegram").error_code == ERR_WEBHOOK
    assert "BotFather" in MSG_WEBHOOK


def test_server_5xx_html_is_transient_and_recovers(tmp_path, tg, engine):
    tg.mode = "html_502"
    manager, _ = make_manager(tmp_path, make_settings(), tg)
    manager.start()
    try:
        # حالت connecting از همون ابتدا (قبل از اولین تلاش) هم برقراره؛ منتظر خودِ پیام خطا می‌مونیم
        assert wait_until(lambda: status(manager, "telegram").error == MSG_NO_CONNECTION, timeout=20)
        assert status(manager, "telegram").state == STATE_CONNECTING
        assert status(manager, "telegram").error_code == ERR_NO_CONNECTION
        tg.mode = "ok"  # سرور درست شد → خودش وصل می‌شه
        assert wait_until(lambda: status(manager, "telegram").connected, timeout=20)
        tg.push_message(3, "بعد از بازیابی")
        assert wait_until(lambda: tg.sent_to(3) == ["پاسخ: بعد از بازیابی"], timeout=20)
    finally:
        manager.stop(timeout=10)


def test_server_down_at_start_then_up(tmp_path, engine):
    tg_server = FakeBotApiServer(port=free_port())  # هنوز بالا نیومده
    manager, _ = make_manager(tmp_path, make_settings(), tg_server)
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").error == MSG_NO_CONNECTION, timeout=20)
        assert status(manager, "telegram").state == STATE_CONNECTING
        tg_server.start()
        assert wait_until(lambda: status(manager, "telegram").connected, timeout=15)
    finally:
        assert manager.stop(timeout=10)
        tg_server.stop()


def test_bad_proxy_reports_persian_message(tmp_path, tg, engine):
    manager, _ = make_manager(tmp_path, make_settings(), tg, proxy="https://bad-scheme:1")
    manager.start()
    assert wait_until(lambda: not manager.is_running(), timeout=20)
    assert status(manager, "telegram").error == MSG_BAD_PROXY
    assert status(manager, "telegram").error_code == ERR_BAD_PROXY


# ----------------------------------------------------- تست اتصال (UI) ----


def test_check_token_helper(tg):
    async def go():
        ok = await tg_check(TG_TOKEN, api_base=tg.base_url)
        assert ok.connected and ok.username == "tg_shop_bot"
        assert (await tg_check("توکن غلط", api_base=tg.base_url)).error == MSG_INVALID_TOKEN
        assert (await tg_check(TG_TOKEN, proxy="https://x:1")).error == MSG_BAD_PROXY
        tg.mode = "unauthorized"
        assert (await tg_check(TG_TOKEN, api_base=tg.base_url)).error == MSG_INVALID_TOKEN
        tg.stop()
        assert (await tg_check(TG_TOKEN, api_base=tg.base_url)).error == MSG_NO_CONNECTION

    import asyncio

    asyncio.run(go())


def test_secrets_never_reach_log_file(tmp_path, tg, engine):
    """فایل bot.log ممکنه توسط کاربر به اشتراک گذاشته بشه → هیچ توکنی نباید توش باشه."""
    import logging

    from app.core import bot_manager as bm

    tg.mode = "html_502"
    provider = "WALLET-TEST-1111111111111111"
    settings = make_settings()
    settings.set_bale_pay_provider_token(provider)
    manager, _ = make_manager(tmp_path, settings, tg)
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").error == MSG_NO_CONNECTION, timeout=20)
        logging.getLogger("app.test").error("عمداً توکن رو لاگ می‌کنیم: %s و %s", TG_TOKEN, provider)
        for h in logging.getLogger("app").handlers:
            h.flush()
    finally:
        manager.stop(timeout=10)
        bm.shutdown_logging()
    text = (tmp_path / "bot.log").read_text(encoding="utf-8")
    assert "عمداً توکن رو لاگ می‌کنیم" in text  # لاگ واقعاً نوشته می‌شه
    assert TG_TOKEN not in text and "AAHdqTcv" not in text and provider not in text
