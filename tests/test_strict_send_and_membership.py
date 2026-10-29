"""N7 + N13 در لایه‌ی آداپتر (با سرورِ جعلیِ Bot API): ارسالِ سخت‌گیر (بدونِ fallback و تلاشِ دوباره؛ خطای اصلی بالا می‌ره)
و پرسیدنِ وضعیتِ عضویتِ کانال — هم تلگرام (aiogram) و هم بله (BaleClient)."""

import asyncio

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from app.core.bale_adapter import BaleAdapter
from app.core.bale_client import BaleApiError, BaleClient
from app.core.telegram_adapter import TelegramAdapter, _make_bot
from tests.fake_servers import FakeBotApiServer

TG_TOKEN = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
BALE_TOKEN = "987654321:BALEtokenBALEtokenBALEtoken12345"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def srv():
    server = FakeBotApiServer().start()
    yield server
    server.stop()


@pytest.fixture
def photo(tmp_path):
    path = tmp_path / "promo.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0 fake jpeg")
    return str(path)


def tg_adapter(srv):
    adapter = TelegramAdapter(TG_TOKEN, None, api_base=srv.base_url)
    adapter._bot = _make_bot(TG_TOKEN, api_base=srv.base_url)  # noqa: SLF001
    return adapter


def bale_adapter(srv):
    adapter = BaleAdapter(BALE_TOKEN, None)
    adapter._client = BaleClient(BALE_TOKEN, base_url_template=srv.url_template)  # noqa: SLF001
    return adapter


async def _closing(adapter, coro_fn):
    """coro_fn(adapter) را اجرا و بعدش نشستِ شبکه را می‌بندد (تا هشدارِ unclosed session نیاید)."""
    try:
        return await coro_fn(adapter)
    finally:
        bot = getattr(adapter, "_bot", None)
        if bot is not None:
            await bot.session.close()
        client = getattr(adapter, "_client", None)
        if client is not None:
            await client.close()


def call(adapter, coro_fn):
    return run(_closing(adapter, coro_fn))


# ============================================================ تلگرام: وضعیتِ عضویت ====


@pytest.mark.parametrize("status", ["creator", "administrator", "member", "left", "kicked"])
def test_telegram_member_status_is_returned_as_is(srv, status):
    srv.member_status["@shop_channel"] = status
    assert call(tg_adapter(srv), lambda a: a.chat_member_status("@shop_channel", "555")) == status
    assert srv.chat_member_calls == [{"chat_id": "@shop_channel", "user_id": "555"}]


def test_telegram_restricted_members_count_by_is_member(srv):
    srv.member_status[("@shop_channel", "555")] = "restricted"
    srv.member_status[("@shop_channel", "555", "is_member")] = True
    srv.member_status[("@shop_channel", "556")] = "restricted"
    srv.member_status[("@shop_channel", "556", "is_member")] = False
    adapter = tg_adapter(srv)
    assert call(adapter, lambda a: a.chat_member_status("@shop_channel", "555")) == "member"
    assert call(tg_adapter(srv), lambda a: a.chat_member_status("@shop_channel", "556")) == "left"


def test_telegram_numeric_channel_ids_are_sent_as_numbers(srv):
    srv.member_status["-1001234567890"] = "member"
    assert call(tg_adapter(srv), lambda a: a.chat_member_status("-1001234567890", "7")) == "member"
    assert srv.chat_member_calls[0]["chat_id"] == "-1001234567890"


@pytest.mark.parametrize(
    "mode, exc",
    [("no_chat", TelegramBadRequest), ("not_admin", TelegramForbiddenError), ("flood", TelegramRetryAfter)],
)
def test_telegram_membership_errors_propagate_for_the_gate_to_fail_open(srv, mode, exc):
    srv.chat_member_mode = mode
    with pytest.raises(exc):
        call(tg_adapter(srv), lambda a: a.chat_member_status("@shop_channel", "555"))


def test_membership_lookup_requires_a_connected_bot():
    with pytest.raises(RuntimeError):
        run(TelegramAdapter(TG_TOKEN, None).chat_member_status("@x_channel", "1"))
    with pytest.raises(RuntimeError):
        run(BaleAdapter(BALE_TOKEN, None).chat_member_status("@x_channel", "1"))


# ================================================================ تلگرام: ارسالِ سخت‌گیر ====


def test_telegram_strict_send_text_with_button_and_photo(srv, photo):
    adapter = tg_adapter(srv)

    async def go(a):
        plain = await a.send_strict("11", "سلام")
        with_button = await a.send_strict("12", "تخفیف", button=("ببین", "https://example.com/offer"))
        with_photo = await a.send_strict("13", "عکس‌دار", photo=photo, button=("خرید", "https://example.com/buy"))
        return plain, with_button, with_photo

    ids = call(adapter, go)
    assert all(i.isdigit() for i in ids)
    by_chat = {m["chat_id"]: m for m in srv.sent}
    assert by_chat["11"]["kind"] == "sendMessage" and by_chat["11"]["text"] == "سلام" and not by_chat["11"]["reply_markup"]
    assert by_chat["12"]["reply_markup"]["inline_keyboard"] == [[{"text": "ببین", "url": "https://example.com/offer"}]]
    assert by_chat["13"]["kind"] == "sendPhoto" and by_chat["13"]["text"] == "عکس‌دار"
    assert by_chat["13"]["reply_markup"]["inline_keyboard"][0][0]["url"] == "https://example.com/buy"


def test_telegram_strict_send_raises_the_original_error_after_exactly_one_attempt(srv, photo):
    srv.send_failures["21"] = (403, "Forbidden: bot was blocked by the user")
    adapter = tg_adapter(srv)
    with pytest.raises(TelegramForbiddenError):
        call(adapter, lambda a: a.send_strict("21", "x", photo=photo, button=("a", "https://example.com")))
    # برخلافِ send_ui: نه fallbackِ عکس→متن، نه بدونِ دکمه؛ دقیقاً یک تلاش
    assert srv.send_log == [("21", "fail:403")]


def test_telegram_strict_send_respects_retry_after_without_doubling_the_requests(srv):
    srv.flood_sends, srv.flood_retry_after = 1, 7
    adapter = tg_adapter(srv)
    with pytest.raises(TelegramRetryAfter) as info:
        call(adapter, lambda a: a.send_strict("31", "x"))
    assert info.value.retry_after == 7 and srv.send_log == [("31", "fail:429")]


def test_the_old_rich_send_retries_on_errors_which_is_why_broadcasts_use_the_strict_path(srv):
    """مستندِ تصمیم: send_ui روی خطا fallback می‌زند (دکمه‌دار ← متنِ ساده)؛ برای پیام‌های تکی عالی، ولی زیرِ ۴۲۹ هر پیام را دو بار می‌فرستد."""
    from app.core.ui import Btn, UiMessage

    srv.flood_sends = 5
    adapter = tg_adapter(srv)
    msg = UiMessage("x", rows=[[Btn("لینک", url="https://example.com/x")]])
    with pytest.raises(TelegramRetryAfter):
        call(adapter, lambda a: a.send_ui("41", msg))
    assert srv.send_log == [("41", "fail:429"), ("41", "fail:429")]  # دو درخواست برای یک پیام


def test_strict_send_requires_a_connected_bot():
    with pytest.raises(RuntimeError):
        run(TelegramAdapter(TG_TOKEN, None).send_strict("1", "x"))
    with pytest.raises(RuntimeError):
        run(BaleAdapter(BALE_TOKEN, None).send_strict("1", "x"))


# ==================================================================== بله ====


@pytest.mark.parametrize("status", ["creator", "administrator", "member", "left", "kicked"])
def test_bale_member_status(srv, status):
    srv.member_status["@shop_channel"] = status
    assert call(bale_adapter(srv), lambda a: a.chat_member_status("@shop_channel", "555")) == status


def test_bale_restricted_and_numeric_ids(srv):
    srv.member_status[("-100777", "5")] = "restricted"
    srv.member_status[("-100777", "5", "is_member")] = False
    assert call(bale_adapter(srv), lambda a: a.chat_member_status("-100777", "5")) == "left"
    assert srv.chat_member_calls == [{"chat_id": "-100777", "user_id": "5"}]


@pytest.mark.parametrize("mode, code", [("no_chat", 400), ("not_admin", 403), ("flood", 429)])
def test_bale_membership_errors_carry_the_platform_code(srv, mode, code):
    srv.chat_member_mode = mode
    with pytest.raises(BaleApiError) as info:
        call(bale_adapter(srv), lambda a: a.chat_member_status("@shop_channel", "1"))
    assert info.value.error_code == code
    if code == 429:
        assert info.value.retry_after == 1.0
    else:
        assert info.value.retry_after is None


def test_bale_unexpected_membership_payload_is_an_error_not_a_guess(srv):
    srv.chat_member_mode = "garbage"
    with pytest.raises(BaleApiError, match="getChatMember"):
        call(bale_adapter(srv), lambda a: a.chat_member_status("@shop_channel", "1"))


def test_bale_strict_send_text_button_and_photo(srv, photo):
    async def go(a):
        await a.send_strict("11", "سلام")
        await a.send_strict("12", "تخفیف", button=("ببین", "https://example.com/offer"))
        await a.send_strict("13", "عکس‌دار", photo=photo, button=("خرید", "https://example.com/buy"))

    call(bale_adapter(srv), go)
    by_chat = {m["chat_id"]: m for m in srv.sent}
    assert by_chat["11"]["text"] == "سلام" and by_chat["12"]["reply_markup"]["inline_keyboard"][0][0]["text"] == "ببین"
    assert by_chat["13"]["kind"] == "sendPhoto" and by_chat["13"]["reply_markup"]["inline_keyboard"][0][0]["url"] == "https://example.com/buy"


@pytest.mark.parametrize("with_photo", [False, True])
def test_bale_strict_send_keeps_error_code_and_retry_after_even_for_photo_uploads(srv, photo, with_photo):
    kwargs = {"photo": photo} if with_photo else {}
    srv.send_failures["21"] = (403, "Forbidden: bot was blocked by the user")
    with pytest.raises(BaleApiError) as info:
        call(bale_adapter(srv), lambda a: a.send_strict("21", "x", **kwargs))
    assert info.value.error_code == 403 and srv.send_log == [("21", "fail:403")]
    srv.send_log.clear()
    srv.flood_sends, srv.flood_retry_after = 1, 9
    with pytest.raises(BaleApiError) as info:
        call(bale_adapter(srv), lambda a: a.send_strict("22", "x", **kwargs))
    assert info.value.error_code == 429 and info.value.retry_after == 9.0 and srv.send_log == [("22", "fail:429")]
