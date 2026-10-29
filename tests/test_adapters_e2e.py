"""
تست سرتاسری آداپتورها: aiogram واقعی و BaleClient واقعی با HTTP واقعی روی
loopback به سرور جعلی وصل می‌شن (tests/fake_servers.py). ربات‌ها مثل برنامه‌ی
واقعی توی ترد پس‌زمینه‌ی جدا (BotManager) اجرا می‌شن — پس مشکل سیگنال
(handle_signals) روی ترد غیر اصلی هم واقعاً تست می‌شه.
"""

import asyncio

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
from app.core.bale_adapter import BaleAdapter
from app.core.bale_adapter import check_token as bale_check
from app.core.bale_client import BaleClient
from app.core.bot_manager import BotManager
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
BALE_TOKEN = "987654321:BALEtokenBALEtokenBALEtoken12345"
FAST = dict(debounce_wait=0.15, debounce_max_wait=0.5)


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


@pytest.fixture
def engine(monkeypatch):
    eng = FakeEngine(reply=lambda text: f"پاسخ: {text}")
    monkeypatch.setattr(ai_engine, "build_engine_from_settings", lambda s: eng)
    return eng


def make_settings(tg_token=TG_TOKEN, bale_token=BALE_TOKEN):
    s = AppSettings()
    s.system_prompt = "تو فروشنده‌ای."
    s.set_telegram_token(tg_token)
    s.set_bale_token(bale_token)
    return s


def make_manager(tmp_path, settings, tg, bale, product_store=None, order_store=None, **tg_kwargs):
    store = ConversationStore(db_path=tmp_path / "e2e.db")
    from app.core.payments import PaymentService

    payments = PaymentService(order_store, product_store) if (order_store and product_store) else None
    factories = {
        "telegram": lambda s, p: TelegramAdapter(
            s.get_telegram_token(), p, api_base=tg.base_url, retry_delays=(0.1, 0.3), poll_timeout=1, **tg_kwargs
        ),
        "bale": lambda s, p: BaleAdapter(
            s.get_bale_token(), p, poll_timeout=1, retry_delays=(0.1, 0.3),
            client_factory=lambda tok: BaleClient(tok, base_url_template=bale.url_template),
            payments=payments,
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


def st_bale_code(manager):
    return status(manager, "bale").error_code


# ------------------------------------------------------------ مسیر شاد ----


def test_full_flow_both_platforms_and_clean_stop(tmp_path, tg, bale, engine):
    manager, store = make_manager(tmp_path, make_settings(), tg, bale)
    manager.start()
    try:
        assert manager.is_running()
        assert wait_until(lambda: status(manager, "telegram").connected and status(manager, "bale").connected)
        assert status(manager, "telegram").username == "tg_shop_bot"
        assert status(manager, "bale").username == "bale_shop_bot"

        # تلگرام: دو پیام سریع → یک پاسخ ادغام‌شده
        tg.push_message(555, "سلام", first_name="سارا")
        tg.push_message(555, "قیمت چنده؟", first_name="سارا")
        assert wait_until(lambda: tg.sent_to(555) == ["پاسخ: سلام\nقیمت چنده؟"])
        # بله
        bale.push_message(777, "سلام از بله", first_name="رضا")
        assert wait_until(lambda: bale.sent_to(777) == ["پاسخ: سلام از بله"])

        convs = {(c.platform, c.chat_id): c.display_name for c in store.list_conversations()}
        assert convs == {("telegram", "555"): "سارا", ("bale", "777"): "رضا"}
        assert [m.role for m in store.get_messages("telegram", "555")] == ["user", "assistant"]

        # بلاک از طریق دیتابیس (همون کاری که UI می‌کنه) → دیگه جواب نمی‌گیره
        store.set_blocked("telegram", "555", True)
        before = len(tg.sent)
        tg.push_message(555, "پیام بعد از بلاک")
        import time as _t; _t.sleep(0.8)
        assert len(tg.sent) == before
    finally:
        assert manager.stop(timeout=10) is True
    assert not manager.is_running()
    assert status(manager, "telegram").state == STATE_STOPPED
    assert status(manager, "bale").state == STATE_STOPPED


def test_crm_captures_identity_from_real_telegram_and_bale_traffic(tmp_path, tg, bale, engine):
    """N12: هویتِ فرستنده از aiogram واقعی و BaleClient واقعی تا جدولِ مشتریان می‌رسه (نه فقط واحد)."""
    manager, _store = make_manager(tmp_path, make_settings(), tg, bale)
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").connected and status(manager, "bale").connected)
        tg.push_message(555, "سلام", first_name="سارا", last_name="احمدی", username="sara_a", language_code="fa")
        bale.push_message(777, "سلام از بله", first_name="رضا", last_name="کریمی", username="reza_k", language_code="fa")
        assert wait_until(lambda: tg.sent_to(555) and bale.sent_to(777))
        customers = manager.customers
        t_c = customers.get("telegram", "555")
        b_c = customers.get("bale", "777")
        assert (t_c.first_name, t_c.last_name, t_c.username, t_c.language_code, t_c.msg_count) == ("سارا", "احمدی", "sara_a", "fa", 1)
        assert (b_c.first_name, b_c.last_name, b_c.username, b_c.language_code, b_c.msg_count) == ("رضا", "کریمی", "reza_k", "fa", 1)
        assert t_c.phone == "" and b_c.phone == ""  # شماره فقط با «اشتراکِ شماره» توسط خودِ مشتری
        assert {c.display_name for c in customers.list()} == {"سارا احمدی", "رضا کریمی"}
    finally:
        assert manager.stop(timeout=10) is True


def test_stop_is_fast_even_with_pending_longpoll(tmp_path, tg, bale, engine):
    import time
    manager, _ = make_manager(tmp_path, make_settings(), tg, bale)
    manager.start()
    assert wait_until(lambda: status(manager, "telegram").connected and status(manager, "bale").connected)
    t0 = time.monotonic()
    assert manager.stop(timeout=10)
    assert time.monotonic() - t0 < 3.0  # درخواست‌های long-poll در حال انتظار لغو می‌شن، نه صبر تا تایم‌اوت


def test_restart_works(tmp_path, tg, bale, engine):
    manager, _ = make_manager(tmp_path, make_settings(), tg, bale)
    manager.start()
    assert wait_until(lambda: status(manager, "telegram").connected)
    manager.restart(timeout=10)
    assert wait_until(lambda: status(manager, "telegram").connected and status(manager, "bale").connected)
    tg.push_message(1, "بعد از ری‌استارت")
    assert wait_until(lambda: tg.sent_to(1) == ["پاسخ: بعد از ری‌استارت"])
    assert manager.stop(timeout=10)


def test_only_enabled_platforms_with_tokens_start(tmp_path, tg, bale, engine):
    settings = make_settings()
    settings.bale_enabled = False  # توکن داره ولی غیرفعاله
    manager, _ = make_manager(tmp_path, settings, tg, bale)
    assert manager.enabled_platforms() == ["telegram"]
    manager.start()
    assert wait_until(lambda: status(manager, "telegram").connected)
    assert status(manager, "bale").state == STATE_STOPPED
    assert "getMe" not in bale.calls  # اصلاً به بله وصل نشد
    manager.stop(timeout=10)


def test_start_without_any_token_gives_persian_error(tmp_path, tg, bale):
    from app.core.bot_manager import BotManagerError

    manager, _ = make_manager(tmp_path, make_settings("", ""), tg, bale)
    with pytest.raises(BotManagerError, match="توکن"):
        manager.start()
    assert not manager.is_running()


# ------------------------------------------------------- خطاها و بازیابی ----


def test_invalid_tokens_show_persian_error_and_manager_ends_by_itself(tmp_path, tg, bale, engine):
    tg.mode = bale.mode = "unauthorized"
    manager, _ = make_manager(tmp_path, make_settings(), tg, bale)
    manager.start()
    assert wait_until(lambda: not manager.is_running())  # هر دو آداپتور خطای نهایی گرفتن و تموم شدن
    st_tg, st_bale = status(manager, "telegram"), status(manager, "bale")
    assert st_tg.state == STATE_ERROR and st_tg.error == MSG_INVALID_TOKEN and st_tg.error_code == ERR_INVALID_TOKEN
    assert st_bale_code(manager) == ERR_INVALID_TOKEN
    assert st_bale.state == STATE_ERROR and "نامعتبره" in st_bale.error


def test_malformed_token_is_handled_without_network(tmp_path, tg, bale, engine):
    manager, _ = make_manager(tmp_path, make_settings(tg_token="این-توکن-نیست", bale_token=""), tg, bale)
    manager.start()
    assert wait_until(lambda: not manager.is_running())
    assert status(manager, "telegram").error == MSG_INVALID_TOKEN
    assert tg.calls == []  # حتی یه درخواست هم نرفت


def test_conflict_needs_three_consecutive_and_is_reported_honestly(tmp_path, tg, bale, engine):
    tg.mode = "conflict"
    manager, _ = make_manager(tmp_path, make_settings(bale_token=""), tg, bale)
    manager.start()
    assert wait_until(lambda: status(manager, "telegram").state == STATE_ERROR)
    assert status(manager, "telegram").error == MSG_CONFLICT
    assert status(manager, "telegram").error_code == ERR_CONFLICT
    assert tg.calls.count("getUpdates") >= 3  # سه تلاش قبل از تسلیم
    assert wait_until(lambda: not manager.is_running())


def test_webhook_conflict_gets_specific_message(tmp_path, tg, bale, engine):
    tg.mode = "webhook_conflict"
    manager, _ = make_manager(tmp_path, make_settings(bale_token=""), tg, bale)
    manager.start()
    assert wait_until(lambda: status(manager, "telegram").state == STATE_ERROR)
    assert status(manager, "telegram").error == MSG_WEBHOOK
    assert status(manager, "telegram").error_code == ERR_WEBHOOK
    assert "BotFather" in MSG_WEBHOOK


def test_server_5xx_html_is_transient_and_recovers(tmp_path, tg, bale, engine):
    tg.mode = "html_502"
    manager, _ = make_manager(tmp_path, make_settings(bale_token=""), tg, bale)
    manager.start()
    try:
        # حالت connecting از همون ابتدا (قبل از اولین تلاش) هم برقراره؛ منتظر خودِ پیام خطا می‌مونیم
        assert wait_until(lambda: status(manager, "telegram").error == MSG_NO_CONNECTION)
        assert status(manager, "telegram").state == STATE_CONNECTING
        assert status(manager, "telegram").error_code == ERR_NO_CONNECTION
        tg.mode = "ok"  # سرور درست شد → خودش وصل می‌شه
        assert wait_until(lambda: status(manager, "telegram").connected)
        tg.push_message(3, "بعد از بازیابی")
        assert wait_until(lambda: tg.sent_to(3) == ["پاسخ: بعد از بازیابی"])
    finally:
        manager.stop(timeout=10)


def test_server_down_at_start_then_up_bale_and_telegram(tmp_path, engine):
    tg_port, bale_port = free_port(), free_port()
    tg, bale = FakeBotApiServer(port=tg_port), FakeBotApiServer(username="late_bale", port=bale_port)  # هنوز بالا نیومدن
    manager, _ = make_manager(tmp_path, make_settings(), tg, bale)
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").error == MSG_NO_CONNECTION and status(manager, "bale").error is not None)
        assert status(manager, "telegram").state == STATE_CONNECTING and status(manager, "bale").state == STATE_CONNECTING
        tg.start(); bale.start()
        assert wait_until(lambda: status(manager, "telegram").connected and status(manager, "bale").connected, timeout=10)
    finally:
        assert manager.stop(timeout=10)
        tg.stop(); bale.stop()


def test_network_drop_mid_run_recovers_bale(tmp_path, tg, bale, engine):
    manager, _ = make_manager(tmp_path, make_settings(tg_token=""), tg, bale)
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "bale").connected)
        bale.mode = "html_502"
        assert wait_until(lambda: status(manager, "bale").state == STATE_CONNECTING)
        bale.mode = "ok"
        assert wait_until(lambda: status(manager, "bale").connected)
        bale.push_message(8, "زنده شد")
        assert wait_until(lambda: bale.sent_to(8) == ["پاسخ: زنده شد"])
    finally:
        manager.stop(timeout=10)


def test_bad_proxy_reports_persian_message(tmp_path, tg, bale, engine):
    manager, _ = make_manager(tmp_path, make_settings(bale_token=""), tg, bale, proxy="https://bad-scheme:1")
    manager.start()
    assert wait_until(lambda: not manager.is_running())
    assert status(manager, "telegram").error == MSG_BAD_PROXY
    assert status(manager, "telegram").error_code == ERR_BAD_PROXY


# ----------------------------------------------------- تست اتصال (UI) ----


def test_check_token_helpers(tg, bale):
    async def go():
        ok = await tg_check(TG_TOKEN, api_base=tg.base_url)
        assert ok.connected and ok.username == "tg_shop_bot"
        assert (await tg_check("توکن غلط", api_base=tg.base_url)).error == MSG_INVALID_TOKEN
        assert (await tg_check(TG_TOKEN, proxy="https://x:1")).error == MSG_BAD_PROXY
        tg.mode = "unauthorized"
        assert (await tg_check(TG_TOKEN, api_base=tg.base_url)).error == MSG_INVALID_TOKEN
        tg.stop()
        assert (await tg_check(TG_TOKEN, api_base=tg.base_url)).error == MSG_NO_CONNECTION

        factory = lambda tok: BaleClient(tok, base_url_template=bale.url_template)  # noqa: E731
        assert (await bale_check(BALE_TOKEN, factory)).username == "bale_shop_bot"
        bale.mode = "unauthorized"
        assert "نامعتبره" in (await bale_check(BALE_TOKEN, factory)).error

    asyncio.run(go())


def test_secrets_never_reach_log_file(tmp_path, tg, bale, engine):
    """فایل bot.log ممکنه توسط کاربر به اشتراک گذاشته بشه → هیچ توکنی نباید توش باشه."""
    import logging

    from app.core import bot_manager as bm

    tg.mode = "html_502"
    bale.mode = "html_502"
    manager, _ = make_manager(tmp_path, make_settings(), tg, bale)
    manager.start()
    try:
        assert wait_until(lambda: status(manager, "telegram").error == MSG_NO_CONNECTION)
        logging.getLogger("app.test").error("عمداً توکن رو لاگ می‌کنیم: %s و %s", TG_TOKEN, BALE_TOKEN)
        for h in logging.getLogger("app").handlers:
            h.flush()
    finally:
        manager.stop(timeout=10)
        bm.shutdown_logging()
    text = (tmp_path / "bot.log").read_text(encoding="utf-8")
    assert "عمداً توکن رو لاگ می‌کنیم" in text  # لاگ واقعاً نوشته می‌شه
    assert TG_TOKEN not in text and BALE_TOKEN not in text and "AAHdqTcv" not in text
