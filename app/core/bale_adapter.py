"""
آداپتور بله: حلقه‌ی polling روی ``BaleClient`` (کلاینت سبک خودمون) که هر پیام
رو به پایپ‌لاین مشترک می‌ده. ساختارش عمداً با ``TelegramAdapter`` یکیه (وضعیت،
run، stop، check_token) تا bot_manager با هر دو یکسان رفتار کنه.

توقف سریع: long-poll بله تا ``poll_timeout`` ثانیه (پیش‌فرض ۱۵) معطل می‌مونه؛
هر درخواست با ``stop_event`` مسابقه می‌ده (``run_until_stop``) و اگه توقف اول
برسه، درخواست در حال انتظار لغو می‌شه — دکمه‌ی «توقف» توی UI فوری جواب می‌ده.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

from app.core.adapter_common import (
    STATE_CONNECTED,
    STATE_CONNECTING,
    STATE_ERROR,
    STATE_STOPPED,
    STOPPED,
    ERR_INVALID_TOKEN,
    ERR_NO_CONNECTION,
    AdapterStatus,
    run_until_stop,
    wait_or_stop,
)
from app.core.bale_client import BaleApiError, BaleClient
from app.core.bot_pipeline import ConversationPipeline, IncomingMessage
from app.core.payments import parse_pay_command
from app.core.redact import redact
from app.core.ui import Transport, UiMessage, plain_text, safe_url

logger = logging.getLogger(__name__)

PLATFORM = "bale"

MSG_INVALID_TOKEN = "توکن ربات بله نامعتبره — از ربات «بات‌فادر» (@botfather) توی بله دوباره بگیرید."
MSG_NO_CONNECTION = "اتصال به بله برقرار نشد (اینترنت قطعه؟). دوباره تلاش می‌کنم…"


class BaleTransport(Transport):
    """عملیاتِ غنیِ رابط روی بله. شکلِ JSON عمداً هم‌شکلِ تلگرامه (مستنداتِ SDKهای بله: ``inline_keyboard`` با
    ``callback_data``، ``keyboard`` برای منوی پایدار، ``answerCallbackQuery``، ``editMessageText``، ``sendPhoto/…``).
    رفتارِ دقیقِ بعضی موارد (ویرایشِ پیامِ عکس‌دار، شکلِ reply keyboard) آفلاین قابل‌تأیید نیست؛ هر خطا → fallbackِ ساده."""

    def __init__(self, client: BaleClient):
        self._client = client

    @staticmethod
    def _inline(rows) -> Optional[dict]:
        keyboard = []
        for row in rows or []:
            buttons = []
            for b in row:
                if b.url and safe_url(b.url):
                    buttons.append({"text": b.label, "url": b.url})
                elif b.data:
                    buttons.append({"text": b.label, "callback_data": b.data})
            if buttons:
                keyboard.append(buttons)
        return {"inline_keyboard": keyboard} if keyboard else None

    def _markup(self, msg: UiMessage) -> Optional[dict]:
        inline = self._inline(msg.rows)
        if inline is not None:
            return inline
        if msg.menu or msg.request_contact:
            keyboard = [[{"text": label} for label in row] for row in (msg.menu or [])]
            if msg.request_contact:
                keyboard.append([{"text": msg.request_contact, "request_contact": True}])
            return {"keyboard": keyboard, "resize_keyboard": True}
        if msg.remove_menu:
            return {"remove_keyboard": True}
        return None

    async def send_ui(self, chat_id: str, msg: UiMessage) -> Optional[str]:
        if msg.contact:
            try:
                return await self._client.send_contact(chat_id, msg.contact[0], msg.contact[1])
            except BaleApiError:
                logger.warning("ارسالِ کارتِ تماس در بله ناموفق بود", exc_info=True)
                return None
        if msg.document:
            return await self._client.send_document(chat_id, msg.document, msg.text)
        markup = self._markup(msg)
        if msg.photo:
            try:
                return await self._client.send_photo(chat_id, msg.photo, msg.text, markup)
            except BaleApiError:
                logger.warning("ارسالِ عکس در بله ناموفق بود؛ فقط متن فرستاده می‌شه", exc_info=True)
        text = msg.text or plain_text(msg) or "…"
        if markup is not None:
            try:
                return await self._client.send_with_markup(chat_id, text, markup)
            except BaleApiError:
                logger.warning("ارسالِ پیامِ دکمه‌دار در بله ناموفق بود؛ نسخه‌ی متنیِ بدونِ دکمه فرستاده می‌شه", exc_info=True)
                text = plain_text(msg) or text
        return await self._client.send_with_markup(chat_id, text)

    async def edit_ui(self, chat_id: str, message_id: str, msg: UiMessage) -> bool:
        try:
            if msg.keyboard_only:
                await self._client.edit_message_reply_markup(chat_id, message_id, self._inline(msg.rows))
                return True
            if msg.photo or msg.contact or msg.document or msg.menu or msg.request_contact or msg.remove_menu:
                return False
            await self._client.edit_message_text(chat_id, message_id, msg.text or "…", self._inline(msg.rows))
            return True
        except (BaleApiError, ValueError):
            logger.info("ویرایشِ پیام در بله ممکن نشد؛ پیامِ تازه می‌ره")
            return False

    async def delete_message(self, chat_id: str, message_id: str) -> None:
        try:
            await self._client.delete_message(chat_id, message_id)
        except (BaleApiError, ValueError):
            logger.debug("حذفِ پیام در بله ممکن نشد", exc_info=True)

    async def answer_callback(self, callback_id: str, text: str = "", alert: bool = False) -> None:
        await self._client.answer_callback_query(callback_id, text, alert)


class BaleAdapter:
    def __init__(
        self,
        token: str,
        pipeline: ConversationPipeline,
        poll_timeout: int = 15,
        retry_delays: tuple = (3.0, 30.0),
        client_factory: Optional[Callable[[str], BaleClient]] = None,
        payments=None,  # Optional["PaymentService"] — None یعنی این ربات بله‌پی رو مدیریت نمی‌کنه
        on_payment_confirmed=None,  # Optional[Callable[[Order], Awaitable[None]]]
    ):
        self.token = token
        self.pipeline = pipeline
        self.payments = payments
        self.on_payment_confirmed = on_payment_confirmed
        self.status = AdapterStatus()
        self._poll_timeout = poll_timeout
        self._retry_min, self._retry_max = retry_delays
        self._client_factory = client_factory or (lambda tok: BaleClient(tok))
        self._client: Optional[BaleClient] = None
        self._stop_event = asyncio.Event()

    def _fail(self, message: str, username: Optional[str] = None, code: Optional[str] = None) -> None:
        self.status = AdapterStatus(state=STATE_ERROR, username=username, error=message, error_code=code)

    async def run(self) -> None:
        self._client = self._client_factory(self.token)
        try:
            username = await self._connect_with_retry()
            if username is None:
                return
            await self._poll_loop(username)
        finally:
            await self._client.close()
            if self.status.state in (STATE_CONNECTED, STATE_CONNECTING):
                self.status = AdapterStatus(state=STATE_STOPPED, username=self.status.username)

    async def _connect_with_retry(self) -> Optional[str]:
        delay = self._retry_min
        while not self._stop_event.is_set():
            self.status = AdapterStatus(
                state=STATE_CONNECTING, error=self.status.error, error_code=self.status.error_code
            )
            try:
                me = await run_until_stop(self._client.get_me(), self._stop_event)
            except BaleApiError as exc:
                if exc.is_auth_error:
                    self._fail(MSG_INVALID_TOKEN, code=ERR_INVALID_TOKEN)
                    return None
                logger.warning("اتصال بله ناموفق: %s", redact(str(exc), self.token))
                self.status = AdapterStatus(
                    state=STATE_CONNECTING, error=MSG_NO_CONNECTION, error_code=ERR_NO_CONNECTION
                )
                if await wait_or_stop(self._stop_event, delay):
                    return None
                delay = min(delay * 2, self._retry_max)
                continue
            if me is STOPPED:
                return None
            username = me.get("username")
            self.status = AdapterStatus(state=STATE_CONNECTED, username=username)
            return username
        return None

    async def _poll_loop(self, username: Optional[str]) -> None:
        delay = self._retry_min
        while not self._stop_event.is_set():
            try:
                batch = await run_until_stop(
                    self._client.get_updates(timeout=self._poll_timeout), self._stop_event
                )
            except BaleApiError as exc:
                if exc.is_auth_error:
                    self._fail(MSG_INVALID_TOKEN, username, code=ERR_INVALID_TOKEN)
                    return
                logger.warning("خطا در دریافت پیام بله: %s", redact(str(exc), self.token))
                self.status = AdapterStatus(
                    state=STATE_CONNECTING, username=username, error=MSG_NO_CONNECTION, error_code=ERR_NO_CONNECTION
                )
                if await wait_or_stop(self._stop_event, delay):
                    return
                delay = min(delay * 2, self._retry_max)
                continue

            if batch is STOPPED:
                return
            delay = self._retry_min
            if self.status.state != STATE_CONNECTED:
                self.status = AdapterStatus(state=STATE_CONNECTED, username=username)
            for incoming in batch.messages:
                # دیپ‌لینک/فرمانِ پرداختِ بله‌پی (/start pay_<id>_<code> یا /pay <id> <code>)
                # فرمانِ ثابته، نه حرفِ آزاد → بدون عبور از هوش مصنوعی جواب داده می‌شه
                if self.payments is not None and not incoming.callback_data and parse_pay_command(incoming.text) is not None:
                    await self._handle_pay_command(incoming)
                    continue
                await self.pipeline.handle_incoming(
                    IncomingMessage(
                        platform=PLATFORM,
                        chat_id=incoming.chat_id,
                        display_name=incoming.from_display_name,
                        text=incoming.text,
                        callback_data=incoming.callback_data,
                        callback_id=incoming.callback_id,
                        message_id=incoming.message_id,
                        language_code=incoming.language_code,
                        phone=incoming.phone,
                        reply_to_id=incoming.reply_to_id,
                        username=incoming.username,
                        first_name=incoming.first_name,
                        last_name=incoming.last_name,
                    ),
                    send=self._make_send(incoming.chat_id),
                    transport=BaleTransport(self._client),
                )
            if self.payments is not None:
                for query in batch.pre_checkout_queries:
                    await self.payments.handle_pre_checkout(query, self._client)
                for payment in batch.successful_payments:
                    # مهم: پیام تاییدیه مستقیم از اینجا به payment.chat_id
                    # فرستاده *نمی‌شه* — اون چتِ سمتِ بله‌ست، نه لزوماً چت
                    # اصلیِ مشتری (که ممکنه تلگرامی باشه). مسیریابیِ درست به
                    # BotManager سپرده می‌شه که به هر دو آداپتور دسترسی داره.
                    order = await self.payments.handle_successful_payment(payment, self._client)
                    if order is not None and self.on_payment_confirmed is not None:
                        try:
                            await self.on_payment_confirmed(order)
                        except Exception:  # noqa: BLE001
                            logger.exception("on_payment_confirmed برای سفارش %s شکست خورد", order.id)

    async def _handle_pay_command(self, incoming) -> None:
        try:
            reply = await self.payments.handle_pay_command(incoming.text, incoming.chat_id, self._client)
            if reply:
                await self._send_with_fallback(incoming.chat_id, reply)
        except Exception:  # noqa: BLE001 — یه فرمانِ پرداختِ خراب نباید حلقه‌ی polling رو بشکنه
            logger.exception("پردازش فرمان پرداخت بله ناموفق بود")

    def _make_send(self, chat_id: str):
        async def send(text: str, buttons=None) -> None:
            await self._send_with_fallback(chat_id, text, buttons)

        return send

    async def _send_with_fallback(self, chat_id: str, text: str, buttons=None) -> None:
        """اگه بله پیامِ دکمه‌دار رو رد کرد، همون متن بدون دکمه فرستاده می‌شه؛ لینک
        پرداخت همیشه توی متنِ پیام هم هست (فرمتِ [متن](لینک) که بله می‌شناسه)."""
        if buttons:
            try:
                await self._client.send_message(chat_id, text, buttons=buttons)
                return
            except BaleApiError:
                logger.warning("ارسال پیام دکمه‌دار در بله ناموفق بود؛ بدون دکمه دوباره امتحان می‌شه", exc_info=True)
        await self._client.send_message(chat_id, text)

    async def stop(self) -> None:
        self._stop_event.set()

    async def send_message(self, chat_id: str, text: str, buttons=None) -> None:
        """ارسالِ عمومی/مستقل از جریانِ polling — برای وقتی BotManager باید
        به یه چتِ این پلتفرم پیام بده (مثلاً تاییدِ پرداختی که از سمتِ بله
        اومده ولی مشتری اصلی تلگرامیه، پس اینجا به‌جاش برای یه مشتریِ بله‌ای
        استفاده می‌شه)."""
        if self._client is None:
            raise RuntimeError("ربات بله وصل نیست.")
        await self._send_with_fallback(chat_id, text, buttons)

    async def send_ui(self, chat_id: str, msg: UiMessage) -> Optional[str]:
        """ارسالِ پیامِ غنی (دکمه/عکس/فایل/کارتِ تماس) به یه چتِ این پلتفرم — مثلاً تحویلِ دیجیتال."""
        if self._client is None:
            raise RuntimeError("ربات بله وصل نیست.")
        return await BaleTransport(self._client).send_ui(chat_id, msg)

    async def chat_member_status(self, channel: str, user_id: str) -> str:
        """N13: وضعیتِ عضویتِ کاربر در کانال (creator/administrator/member/left/kicked). خطا بالا می‌ره؛ دروازه fail-open می‌کنه."""
        if self._client is None:
            raise RuntimeError("ربات بله وصل نیست.")
        return await self._client.get_chat_member(channel, user_id)

    async def send_strict(self, chat_id: str, text: str, *, photo: str = "", button=None) -> str:
        """N7: ارسالِ سخت‌گیر برای پیامِ همگانی (بدونِ fallback و تلاشِ دوباره؛ خطای اصلی بالا می‌ره). ``button`` = (برچسب, url) یا None."""
        if self._client is None:
            raise RuntimeError("ربات بله وصل نیست.")
        markup = {"inline_keyboard": [[{"text": button[0], "url": button[1]}]]} if button else None
        if photo:
            return await self._client.send_photo(chat_id, photo, text, markup)
        return await self._client.send_with_markup(chat_id, text, markup)

    async def send_document_strict(self, chat_id: str, path: str, caption: str = "") -> str:
        """N19: فایلِ PDFِ فاکتور (آپلودِ محلی با multipart)؛ خطای اصلی بالا می‌ره."""
        if self._client is None:
            raise RuntimeError("ربات بله وصل نیست.")
        return await self._client.send_document(chat_id, path, caption)

    def profile_client(self):
        """کلاینتِ بیوگرافیِ ربات (N17)؛ ``None`` تا وقتی واقعاً وصل نشده."""
        if self._client is None or self.status.state != STATE_CONNECTED:
            return None
        from app.core.bot_profile import BaleProfileClient

        return BaleProfileClient(self._client)

    @property
    def client(self) -> Optional[BaleClient]:
        """برای جریان خرید (``purchase_flow.py``): حتی وقتی مشتری اصلی
        تلگرامیه، ساختن لینک بله‌پی همیشه از طریق همین کلاینتِ بله انجام
        می‌شه. ``None`` تا وقتی ``run()`` واقعاً وصل بشه."""
        return self._client


async def check_token(token: str, client_factory: Optional[Callable[[str], BaleClient]] = None) -> AdapterStatus:
    """تست سریع توکن بدون شروع polling — برای دکمه‌ی «تست اتصال» توی UI."""
    client = (client_factory or (lambda tok: BaleClient(tok)))(token)
    try:
        me = await client.get_me()
        return AdapterStatus(state=STATE_CONNECTED, username=me.get("username"))
    except BaleApiError as exc:
        if exc.is_auth_error:
            return AdapterStatus(state=STATE_ERROR, error=MSG_INVALID_TOKEN, error_code=ERR_INVALID_TOKEN)
        logger.warning("تست اتصال بله ناموفق: %s", redact(str(exc), token))
        return AdapterStatus(state=STATE_ERROR, error=MSG_NO_CONNECTION, error_code=ERR_NO_CONNECTION)
    finally:
        await client.close()
