"""N7 + N13 در لایه‌ی آداپتر (با سرورِ جعلیِ Bot API): ارسالِ سخت‌گیر (بدونِ fallback و تلاشِ دوباره؛ خطای اصلی بالا می‌ره)
و پرسیدنِ وضعیتِ عضویتِ کانال.

نسخه‌ی ۱.۰.۰: تلگرام تنها پیام‌رسانِ ربات است، پس این فایل فقط مسیرِ aiogram را می‌سنجد.
«بله» دیگر عضویتِ کانال نمی‌پرسد و پیامِ همگانی نمی‌فرستد؛ تنها نقشش درگاهِ پرداخت است
(app/core/bale_pay.py — تستش در tests/test_bale_pay.py)."""

import asyncio

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from app.core import telegram_adapter as tg_module
from app.core.telegram_adapter import TelegramAdapter, _make_bot
from tests.fake_servers import FakeBotApiServer

TG_TOKEN = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"


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


async def _closing(adapter, coro_fn):
    """coro_fn(adapter) را اجرا و بعدش نشستِ شبکه را می‌بندد (تا هشدارِ unclosed session نیاید)."""
    try:
        return await coro_fn(adapter)
    finally:
        bot = getattr(adapter, "_bot", None)
        if bot is not None:
            await bot.session.close()


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


def test_unsafe_button_urls_never_become_buttons(srv):
    """دکمه‌ی شیشه‌ای با URLِ ساخته‌شده از داده، خطرناک‌ترین سطحِ حمله است؛ هر دو مسیرِ ارسال
    (سخت‌گیر و عمومی) باید از same safe_urlِ بقیه‌ی مسیرها رد شوند."""
    adapter = tg_adapter(srv)
    for scheme in ("javascript:alert(1)", "tel:+989120000000", "data:text/html,hi", "file:///etc/passwd"):
        call(adapter, lambda a, s=scheme: a.send_strict("14", "لینک", button=("بزن", s)))
    assert [m for m in srv.sent if m["chat_id"] == "14" and m["reply_markup"]] == []
    assert len([m for m in srv.sent if m["chat_id"] == "14"]) == 4  # متن رفت، دکمه نه

    sent = []

    class StubBot:
        async def send_message(self, **kw):
            sent.append(kw)

    run(tg_module._send_with_buttons(StubBot(), 5, "متن", [("مراجعه", "javascript:alert(1)")]))
    assert len(sent) == 1 and "reply_markup" not in sent[0]
    run(tg_module._send_with_buttons(StubBot(), 6, "متن", [("سایت", "https://example.com"), ("بد", "javascript:x")]))
    assert len(sent) == 2 and sent[1]["reply_markup"].inline_keyboard[0][0].url == "https://example.com"


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
