"""
اتصال polling به تلگرام با aiogram3. این ماژول فقط «رابط» بین تلگرام و
پایپ‌لاین مشترک (bot_pipeline.py) — منطق پاسخ‌گویی، دیباونس و بلاک‌لیست همه
توی bot_pipeline.py هستن و به aiogram وابسته نیستن (برای تست بدون شبکه).

نکته‌های فنی مهم که حین ساخت با تست واقعی/خواندن سورس کشف شدن (مثل نکات فاز
۱/۲ درباره‌ی Flet — کتابخونه رو با inspect چک کن، حدس نزن):

۱. **حلقه‌ی polling خودمونه، نه ``Dispatcher.start_polling``.** حلقه‌ی داخلی
   aiogram (``_listen_updates``) *همه‌ی* خطاها (Conflict، Unauthorized، …) رو
   می‌بلعه و برای همیشه با backoff دوباره تلاش می‌کنه — یعنی اگه توکن وسط کار
   باطل بشه یا برنامه دوبار اجرا شده باشه، UI همچنان «متصل» نشون می‌داد در
   حالی که هیچ پیامی نمی‌رسه. با حلقه‌ی خودمون (``bot.get_updates`` +
   ``dp.feed_update``) وضعیت همیشه راست‌گوئه، توقف فوری‌ه، و مشکل سیگنال (بند
   بعد) هم اصلاً پیش نمیاد. Bot/Router/Dispatcher/پروکسی/تایپ‌ها همچنان aiogram.

۲. ``start_polling(handle_signals=True)`` روی ترد غیر از ترد اصلی روی لینوکس/مک
   با RuntimeError شکست می‌خوره (ربات توی ترد پس‌زمینه‌ی bot_manager اجرا
   می‌شه) — با حلقه‌ی خودمون این مشکل وجود نداره.

۳. برای فرستادن پیام از داخل هندلر، عمداً ``bot.send_message(...)`` صریح
   صدا می‌زنیم، نه ``message.answer(...)``. ``answer`` مسیر داخلی متفاوتی داره
   (``bot(method)`` یعنی ``Bot.__call__`` که متد ویژه‌ست و روی instance
   جایگزین‌شدنی نیست).

۴. ``parse_mode`` عمداً None می‌مونه. پاسخ AI متن آزاده — با parse_mode روشن، هر
   کاراکتر خاص ناخواسته‌ی توش (``<``، ``&``، ``*``) خطای ۴۰۰ می‌ده و ارسال
   کامل شکست می‌خوره.

۵. هر پروکسی (حتی HTTP) توی aiogram از طریق ``aiohttp-socks`` کار می‌کنه.
   اسکیم‌های پذیرفته‌شده: ``socks5://``، ``socks4://``، ``http://`` (با یا بدون
   user:pass). ``https://`` و ``socks5h://`` رد می‌شن. تلگرام برای خیلی از
   کاربرای ایرانی بدون پروکسی/VPN در دسترس نیست، برای همین پروکسی اختیاری
   پشتیبانی می‌شه (بله داخلیه و پروکسی نمی‌خواد).

۶. ``TokenValidationError`` (توکنی که شکلش غلطه، مثلاً بدون «:») زیرکلاس
   ``Exception`` ساده‌ست، نه ``ValueError`` — جداگانه گرفته می‌شه.

۸. **استخر پروکسی و جابه‌جاییِ خودکار** (``proxy_pool.py``): اگه چند پروکسی داده بشه، بعد از
   ``failover_after`` خطای شبکه‌ی پشت‌سرهم، پروکسیِ فعلی «استراحت» می‌گیره و آداپتور با
   پروکسیِ بعدی یه ``Bot`` تازه می‌سازه؛ polling از همون‌جا ادامه پیدا می‌کنه (offset توی
   حلقه‌ی خودمونه، پس هیچ پیامی گم یا تکراری نمی‌شه). Conflict/Unauthorized/RetryAfter خطای
   شبکه حساب نمی‌شن.

۷. Conflict (۴۰۹) یه بار می‌تونه گذرا باشه (ری‌استارت سریع؛ درخواست قدیمیِ هنوز
   باز روی سرور تلگرام). فقط بعد از ۳ Conflict پشت‌سرهم خطای نهایی نشون می‌دیم.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import os
import time
from typing import Optional

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.exceptions import (
    AiogramError,
    TelegramConflictError,
    TelegramRetryAfter,
    TelegramUnauthorizedError,
)
from aiogram.types import CallbackQuery, Message
from aiogram.utils.token import TokenValidationError

from app.core.adapter_common import (
    MEDIA_KINDS,
    normalize_member_status,
    with_media_note,
    STATE_CONNECTED,
    STATE_CONNECTING,
    STATE_ERROR,
    STATE_STOPPED,
    STOPPED,
    ERR_BAD_PROXY,
    ERR_CONFLICT,
    ERR_INVALID_TOKEN,
    ERR_NO_CONNECTION,
    ERR_WEBHOOK,
    AdapterStatus,
    run_until_stop,
    wait_or_stop,
)
from app.core.bot_pipeline import ConversationPipeline, IncomingMessage
from app.core.proxy_pool import ProxyPool, mask_credentials, probe_proxy
from app.core.redact import redact
from app.core.ui import Transport, UiMessage, plain_text, safe_url

logger = logging.getLogger(__name__)

PLATFORM = "telegram"

MSG_INVALID_TOKEN = "توکن ربات تلگرام نامعتبره — از @BotFather دوباره بگیرید."
MSG_CONFLICT = (
    "این ربات هم‌زمان جای دیگه‌ای هم پیام‌ها رو دریافت می‌کنه (شاید برنامه دوبار اجرا "
    "شده). فقط یک نمونه می‌تونه فعال باشه."
)
MSG_WEBHOOK = (
    "این ربات روی وب‌هوک تنظیم شده (احتمالاً برای یه سرویس ابری دیگه). برای این برنامه "
    "یه ربات جدید از @BotFather بساز تا سرویس قبلی‌ت مختل نشه."
)
MSG_BAD_PROXY = (
    "آدرس پروکسی نامعتبره. شکل درست: socks5://127.0.0.1:10808 یا "
    "http://127.0.0.1:10809"
)
MSG_NO_CONNECTION = (
    "اتصال به تلگرام برقرار نشد (اینترنت قطعه یا تلگرام بدون پروکسی/VPN در دسترس "
    "نیست). دوباره تلاش می‌کنم…"
)

CONFLICT_LIMIT = 3
FAILOVER_AFTER = 2  # چند خطای شبکه‌ی پشت‌سرهم قبل از عوض‌کردنِ پروکسی


class _BadProxy(Exception):
    pass


class _BadToken(Exception):
    pass


def _make_bot(token: str, proxy: str = "", api_base: str = "") -> Bot:
    """``api_base`` (سرور Bot API سفارشی/آینه) برای تست با سرور جعلی و برای
    استفاده‌ی آینده‌ی «آدرس API سفارشی» (شبیه آدرس قابل‌تنظیم API هوش مصنوعی)."""
    try:
        session = None
        if proxy or api_base:
            kwargs = {"api": TelegramAPIServer.from_base(api_base)} if api_base else {}
            session = AiohttpSession(proxy=proxy or None, **kwargs)
    except (ValueError, RuntimeError) as exc:
        raise _BadProxy(str(exc)) from exc
    try:
        return Bot(token=token, session=session, default=DefaultBotProperties(parse_mode=None))
    except TokenValidationError as exc:
        raise _BadToken(str(exc)) from exc


def _sender_fields(user) -> dict:
    """هویتِ فرستنده برای CRM (N12): فقط فیلدهایی که خودِ تلگرام می‌فرسته."""
    if user is None:
        return {}
    return {
        "username": getattr(user, "username", None) or "",
        "first_name": getattr(user, "first_name", None) or "",
        "last_name": getattr(user, "last_name", None) or "",
        "is_premium": bool(getattr(user, "is_premium", False)),
    }


class TelegramAdapter:
    def __init__(
        self,
        token: str,
        pipeline: ConversationPipeline,
        proxy: str = "",
        api_base: str = "",
        retry_delays: tuple = (3.0, 30.0),
        poll_timeout: int = 10,
        proxy_pool: Optional[ProxyPool] = None,
        failover_after: int = FAILOVER_AFTER,
        bot_factory=None,
        best_check_interval: float = 600.0,
        prober=None,
        clock=time.monotonic,
    ):
        self.token = token
        self.pipeline = pipeline
        self._pool = proxy_pool if proxy_pool is not None and len(proxy_pool) > 0 else None
        self.proxy = self._pool.pick() if self._pool is not None else proxy
        self._failover_after = max(1, failover_after)
        self._bot_factory = bot_factory or _make_bot  # تزریق‌پذیر برای تست (بدون شبکه‌ی واقعی)
        self._net_failures = 0
        self._best_check_interval = best_check_interval  # ثانیه؛ ۰ = غیرفعال
        self._prober = prober or probe_proxy
        self._clock = clock
        self._last_best_check = clock()
        self.proxy_events: collections.deque = collections.deque(maxlen=10)  # (زمان, از, به, دلیل)
        self.api_base = api_base
        self.status = AdapterStatus()
        self._retry_min, self._retry_max = retry_delays
        self._poll_timeout = poll_timeout
        self._bot: Optional[Bot] = None
        self._dispatcher: Optional[Dispatcher] = None
        self._stop_event = asyncio.Event()

    # ------------------------------------------------------------------
    def _build_dispatcher(self) -> Dispatcher:
        router = Router(name="smart_business_local_telegram")

        @router.message()
        async def on_message(message: Message, bot: Bot) -> None:
            media = next((label for attr, label in MEDIA_KINDS if getattr(message, attr, None)), "")
            text = with_media_note(message.text or message.caption or "", media)
            phone = message.contact.phone_number if getattr(message, "contact", None) else ""
            if not text and getattr(message, "location", None):
                text = f"{message.location.latitude},{message.location.longitude}"
            if not text and not phone:
                return  # استیکر و ... — چیزی برای گفتن ندارن
            display_name = message.from_user.full_name if message.from_user else str(message.chat.id)

            async def send(reply_text: str, buttons=None) -> None:
                await _send_with_buttons(bot, message.chat.id, reply_text, buttons)

            await self.pipeline.handle_incoming(
                IncomingMessage(
                    platform=PLATFORM,
                    chat_id=str(message.chat.id),
                    display_name=display_name,
                    text=text,
                    language_code=(message.from_user.language_code or "") if message.from_user else "",
                    phone=phone or "",
                    reply_to_id=str(message.reply_to_message.message_id) if getattr(message, "reply_to_message", None) else "",
                    **_sender_fields(message.from_user),
                ),
                send=send,
                transport=TelegramTransport(bot),
            )

        @router.callback_query()
        async def on_callback(query: CallbackQuery, bot: Bot) -> None:
            transport = TelegramTransport(bot)
            msg = query.message
            if msg is None or not query.data:  # پیامِ خیلی قدیمی (غیرقابل‌دسترس) — فقط spinner رو قطع کن
                await transport.answer_callback(query.id, "", False)
                return
            chat_id = msg.chat.id
            display_name = query.from_user.full_name if query.from_user else str(chat_id)

            async def send(reply_text: str, buttons=None) -> None:
                await _send_with_buttons(bot, chat_id, reply_text, buttons)

            await self.pipeline.handle_incoming(
                IncomingMessage(
                    platform=PLATFORM,
                    chat_id=str(chat_id),
                    display_name=display_name,
                    text="",
                    callback_data=query.data,
                    callback_id=query.id,
                    message_id=str(msg.message_id),
                    language_code=(query.from_user.language_code or "") if query.from_user else "",
                    **_sender_fields(query.from_user),
                ),
                send=send,
                transport=transport,
            )

        dp = Dispatcher()
        dp.include_router(router)
        return dp

    def _fail(self, message: str, username: Optional[str] = None, code: Optional[str] = None) -> None:
        self.status = AdapterStatus(state=STATE_ERROR, username=username, error=message, error_code=code)

    def _secrets(self) -> tuple:
        pool_urls = tuple(self._pool.urls) if self._pool is not None else ()
        return (self.token, self.proxy, *pool_urls)

    async def _note_network_ok(self) -> None:
        self._net_failures = 0
        if self._pool is not None:
            self._pool.report_success(self.proxy)

    async def _note_network_failure(self) -> None:
        """خطای شبکه ثبت می‌شه؛ اگه چند پروکسی داریم و پشت‌سرهم شکست خورده، عوضش می‌کنیم."""
        if self._pool is None or len(self._pool) < 2:
            return
        self._net_failures += 1
        if self._net_failures < self._failover_after:
            return
        self._net_failures = 0
        old = self.proxy
        new = self._pool.report_failure(old)
        if new == old:
            return
        try:
            bot = self._bot_factory(self.token, new, self.api_base)
        except (_BadProxy, _BadToken):
            logger.warning("پروکسیِ %s نامعتبره؛ از استخر کنار گذاشته شد", mask_credentials(new))
            self._pool.report_failure(new)
            return
        logger.warning("پروکسی تلگرام عوض شد: %s → %s", mask_credentials(old), mask_credentials(new))
        await self._close_bot()
        self.proxy = new
        self._bot = bot
        self._record_proxy_event(old, new, "failover")

    def _record_proxy_event(self, old: str, new: str, reason: str) -> None:
        self.proxy_events.append((time.time(), mask_credentials(old) if old else "", mask_credentials(new) if new else "", reason))

    async def _maybe_return_to_best(self) -> None:
        """وقتی روی پروکسیِ غیرِ اول هستیم، هر N دقیقه اولی (= بهترینِ رتبه‌بندی‌شده) رو probe می‌کنه؛ اگه سالم و
        ≥۳۰٪ سریع‌تر از فعلی بود برمی‌گرده (hysteresis تا فلیپ‌فلاپ نشه). فقط بینِ دو ``getUpdates`` صدا زده می‌شه."""
        pool = self._pool
        if pool is None or len(pool) < 2 or self._best_check_interval <= 0:
            return
        now = self._clock()
        if now - self._last_best_check < self._best_check_interval:
            return
        self._last_best_check = now
        best = pool.urls[0]
        if self.proxy == best:
            return
        latency = await self._prober(best)
        if latency is None:
            return
        current = pool.entry(self.proxy)
        known = current.latency_ms if current is not None else None
        if known is not None and latency > known * 0.7:
            return  # hysteresis: فقط اگه واقعاً (≥۳۰٪) سریع‌تره
        try:
            bot = self._bot_factory(self.token, best, self.api_base)
        except (_BadProxy, _BadToken):
            pool.report_failure(best)
            return
        old = self.proxy
        logger.info("بازگشت به بهترین پروکسی: %s → %s", mask_credentials(old), mask_credentials(best))
        await self._close_bot()
        self.proxy = best
        self._bot = bot
        pool.report_success(best, latency)
        self._record_proxy_event(old, best, "back_to_best")

    def update_proxy_pool(self, text: str) -> str:
        """لیستِ پروکسیِ تازه (دستی + اشتراک) رو اعمال می‌کنه: ``hot`` (استخر درجا عوض شد) | ``same`` | ``restart``
        (ساختارِ تنظیم عوض شده — مثلاً از بدونِ استخر به استخر — و باید ربات ری‌استارت بشه)."""
        from app.core.proxy_pool import parse_proxy_text

        urls = parse_proxy_text(text).urls
        if self._pool is not None and len(urls) >= 2:
            return "hot" if self._pool.replace(urls) else "same"
        if self._pool is None and ((not urls and not self.proxy) or (len(urls) == 1 and urls[0] == self.proxy)):
            return "same"
        return "restart"

    @property
    def current_proxy(self) -> str:
        """پروکسیِ در حال استفاده (بدون رمز)، یا خالی اگه مستقیم وصله."""
        return mask_credentials(self.proxy) if self.proxy else ""

    async def _close_bot(self) -> None:
        if self._bot is not None:
            try:
                await self._bot.session.close()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    async def run(self) -> None:
        """اجرای مسدودکننده تا وقتی stop() صدا زده بشه یا خطای غیرقابل‌جبران
        پیش بیاد. باید توی یه event loop جدا (ترد پس‌زمینه) صدا زده بشه."""
        try:
            self._bot = self._bot_factory(self.token, self.proxy, self.api_base)
        except _BadProxy as exc:
            logger.error("ساخت ربات تلگرام ناموفق (پروکسی): %s", redact(str(exc), *self._secrets()))
            self._fail(MSG_BAD_PROXY, code=ERR_BAD_PROXY)
            return
        except _BadToken:
            self._fail(MSG_INVALID_TOKEN, code=ERR_INVALID_TOKEN)
            return
        self._dispatcher = self._build_dispatcher()

        try:
            username = await self._connect_with_retry()
            if username is None:  # توقف خواسته شد یا خطای نهایی (وضعیتش ثبت شده)
                return
            await self._poll_loop(username)
        finally:
            await self._close_bot()
            if self.status.state in (STATE_CONNECTED, STATE_CONNECTING):
                self.status = AdapterStatus(state=STATE_STOPPED, username=self.status.username)

    async def _connect_with_retry(self) -> Optional[str]:
        delay = self._retry_min
        while not self._stop_event.is_set():
            self.status = AdapterStatus(
                state=STATE_CONNECTING, error=self.status.error, error_code=self.status.error_code
            )
            try:
                me = await run_until_stop(self._bot.get_me(request_timeout=15), self._stop_event)
            except TelegramUnauthorizedError:
                self._fail(MSG_INVALID_TOKEN, code=ERR_INVALID_TOKEN)
                return None
            except AiogramError as exc:
                logger.warning("اتصال تلگرام ناموفق: %s", redact(str(exc), *self._secrets()))
                self.status = AdapterStatus(
                    state=STATE_CONNECTING, error=MSG_NO_CONNECTION, error_code=ERR_NO_CONNECTION
                )
                await self._note_network_failure()
                if await wait_or_stop(self._stop_event, delay):
                    return None
                delay = min(delay * 2, self._retry_max)
                continue
            if me is STOPPED:
                return None
            await self._note_network_ok()
            self.status = AdapterStatus(state=STATE_CONNECTED, username=me.username)
            return me.username
        return None

    async def _poll_loop(self, username: Optional[str]) -> None:
        delay = self._retry_min
        offset: Optional[int] = None
        conflicts = 0
        allowed = self._dispatcher.resolve_used_update_types()
        while not self._stop_event.is_set():
            try:
                updates = await run_until_stop(
                    self._bot.get_updates(
                        offset=offset,
                        timeout=self._poll_timeout,
                        allowed_updates=allowed,
                        request_timeout=self._poll_timeout + 20,
                    ),
                    self._stop_event,
                )
            except TelegramUnauthorizedError:
                self._fail(MSG_INVALID_TOKEN, username, code=ERR_INVALID_TOKEN)
                return
            except TelegramConflictError as exc:
                conflicts += 1
                logger.warning("Conflict از تلگرام (%d/%d): %s", conflicts, CONFLICT_LIMIT, redact(str(exc), *self._secrets()))
                if conflicts >= CONFLICT_LIMIT:
                    is_webhook = "webhook" in str(exc).lower()
                    self._fail(
                        MSG_WEBHOOK if is_webhook else MSG_CONFLICT,
                        username,
                        code=ERR_WEBHOOK if is_webhook else ERR_CONFLICT,
                    )
                    return
                if await wait_or_stop(self._stop_event, 1.0):
                    return
                continue
            except TelegramRetryAfter as exc:
                if await wait_or_stop(self._stop_event, min(float(exc.retry_after), 60.0)):
                    return
                continue
            except AiogramError as exc:
                logger.warning("خطا در دریافت پیام تلگرام: %s", redact(str(exc), *self._secrets()))
                self.status = AdapterStatus(
                    state=STATE_CONNECTING, username=username, error=MSG_NO_CONNECTION, error_code=ERR_NO_CONNECTION
                )
                await self._note_network_failure()
                if await wait_or_stop(self._stop_event, delay):
                    return
                delay = min(delay * 2, self._retry_max)
                continue

            if updates is STOPPED:
                return
            conflicts = 0
            delay = self._retry_min
            await self._note_network_ok()
            if not updates:
                await self._maybe_return_to_best()
            if self.status.state != STATE_CONNECTED:
                self.status = AdapterStatus(state=STATE_CONNECTED, username=username)
            for update in updates:
                offset = update.update_id + 1
                try:
                    await self._dispatcher.feed_update(self._bot, update)
                except Exception:  # noqa: BLE001 — یه آپدیت خراب نباید حلقه رو بشکنه
                    logger.exception("پردازش یه آپدیت تلگرام ناموفق بود")

    def profile_client(self):
        """کلاینتِ بیوگرافیِ ربات (N17)؛ ``None`` تا وقتی واقعاً وصل نشده."""
        if self._bot is None or self.status.state != STATE_CONNECTED:
            return None
        from app.core.bot_profile import TelegramProfileClient

        return TelegramProfileClient(self._bot)

    async def send_message(self, chat_id: str, text: str, buttons=None) -> None:
        """ارسالِ عمومی/مستقل از جریانِ polling — برای وقتی BotManager باید
        به یه چتِ این پلتفرم پیام بده (مثلاً تاییدِ پرداختی که از سمتِ بله
        اومده ولی مشتری اصلی تلگرامیه)."""
        if self._bot is None:
            raise RuntimeError("ربات تلگرام وصل نیست.")
        await _send_with_buttons(self._bot, int(chat_id), text, buttons)

    async def send_ui(self, chat_id: str, msg: UiMessage) -> Optional[str]:
        """ارسالِ پیامِ غنی (دکمه/عکس/فایل/کارتِ تماس) به یه چتِ این پلتفرم — مثلاً تحویلِ دیجیتال."""
        if self._bot is None:
            raise RuntimeError("ربات تلگرام وصل نیست.")
        return await TelegramTransport(self._bot).send_ui(chat_id, msg)

    async def chat_member_status(self, channel: str, user_id: str) -> str:
        """N13: وضعیتِ عضویتِ کاربر در کانال (creator/administrator/member/left/kicked). خطا بالا می‌ره؛ دروازه fail-open می‌کنه."""
        if self._bot is None:
            raise RuntimeError("ربات تلگرام وصل نیست.")
        ref = int(channel) if str(channel).lstrip("-").isdigit() else channel
        member = await self._bot.get_chat_member(chat_id=ref, user_id=int(user_id))
        return normalize_member_status(member.status, getattr(member, "is_member", None))

    async def send_strict(self, chat_id: str, text: str, *, photo: str = "", button=None) -> str:
        """N7: ارسالِ *سخت‌گیر* برای پیامِ همگانی — برخلافِ ``send_ui``، هیچ fallbackی (عکس→متن، دکمه→بی‌دکمه) و تلاشِ دوباره‌ای نداره
        و خطای اصلیِ پلتفرم (۴۰۳ بلاک‌شده، ۴۲۹ + retry_after، …) همان‌طور بالا می‌ره تا موتورِ ارسال درست تصمیم بگیره.
        ``photo`` مسیرِ فایلِ محلی؛ ``button`` = (برچسب, url) یا None. شناسه‌ی پیامِ فرستاده‌شده را برمی‌گردونه."""
        if self._bot is None:
            raise RuntimeError("ربات تلگرام وصل نیست.")
        markup = None
        if button:
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

            markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=button[0], url=button[1])]])
        if photo:
            from aiogram.types import FSInputFile

            sent = await self._bot.send_photo(chat_id=int(chat_id), photo=FSInputFile(photo), caption=text[:1000] or None, reply_markup=markup)
        else:
            sent = await self._bot.send_message(chat_id=int(chat_id), text=text, reply_markup=markup)
        return str(sent.message_id)

    async def send_document_strict(self, chat_id: str, path: str, caption: str = "") -> str:
        """N19: فایلِ PDFِ فاکتور (آپلودِ محلی)؛ بدونِ fallback/retry — خطای اصلی بالا می‌ره تا ``InvoiceService`` تصمیم بگیره."""
        if self._bot is None:
            raise RuntimeError("ربات تلگرام وصل نیست.")
        from aiogram.types import FSInputFile

        sent = await self._bot.send_document(chat_id=int(chat_id), document=FSInputFile(path), caption=caption[:1000] or None)
        return str(sent.message_id)

    async def stop(self) -> None:
        self._stop_event.set()


class TelegramTransport(Transport):
    """عملیاتِ غنیِ رابط روی تلگرام (aiogram): ارسال با کیبورد، ویرایش، پاسخ به callback، عکس/فایل/کارتِ تماس."""

    def __init__(self, bot):
        self._bot = bot

    @staticmethod
    def _inline(rows):
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        keyboard = []
        for row in rows or []:
            buttons = []
            for b in row:
                if b.url and safe_url(b.url):
                    buttons.append(InlineKeyboardButton(text=b.label, url=b.url))
                elif b.data:
                    buttons.append(InlineKeyboardButton(text=b.label, callback_data=b.data))
            if buttons:
                keyboard.append(buttons)
        return InlineKeyboardMarkup(inline_keyboard=keyboard) if keyboard else None

    def _markup(self, msg: UiMessage):
        inline = self._inline(msg.rows)
        if inline is not None:
            return inline
        if msg.menu or msg.request_contact:
            from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

            keyboard = [[KeyboardButton(text=label) for label in row] for row in (msg.menu or [])]
            if msg.request_contact:
                keyboard.append([KeyboardButton(text=msg.request_contact, request_contact=True)])
            return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, is_persistent=True)
        if msg.remove_menu:
            from aiogram.types import ReplyKeyboardRemove

            return ReplyKeyboardRemove()
        return None

    @staticmethod
    def _photo(path: str):
        from aiogram.types import FSInputFile

        if os.path.isfile(path):
            return FSInputFile(path)
        return path if safe_url(path) else None

    async def send_ui(self, chat_id: str, msg: UiMessage) -> Optional[str]:
        cid = int(chat_id)
        if msg.contact:
            try:
                sent = await self._bot.send_contact(chat_id=cid, phone_number=msg.contact[0], first_name=msg.contact[1] or "-")
                return str(sent.message_id)
            except Exception:  # noqa: BLE001 — پیامِ متنیِ شماره قبلاً رفته؛ کارتِ تماس «بهترِ ممکن» است
                logger.warning("ارسالِ کارتِ تماس ناموفق بود", exc_info=True)
                return None
        if msg.document:
            from aiogram.types import FSInputFile

            sent = await self._bot.send_document(chat_id=cid, document=FSInputFile(msg.document), caption=(msg.text or None) and msg.text[:1000])
            return str(sent.message_id)
        markup = self._markup(msg)
        if msg.photo:
            photo = self._photo(msg.photo)
            if photo is not None:
                try:
                    sent = await self._bot.send_photo(chat_id=cid, photo=photo, caption=(msg.text or "")[:1000] or None, reply_markup=markup)
                    return str(sent.message_id)
                except Exception:  # noqa: BLE001
                    logger.warning("ارسالِ عکسِ محصول ناموفق بود؛ فقط متن فرستاده می‌شه", exc_info=True)
        return await self._send_text(cid, msg, markup)

    async def _send_text(self, cid: int, msg: UiMessage, markup) -> Optional[str]:
        text = msg.text or plain_text(msg) or "…"
        if markup is not None:
            try:
                sent = await self._bot.send_message(chat_id=cid, text=text, reply_markup=markup)
                return str(sent.message_id)
            except Exception:  # noqa: BLE001 — مثلاً BUTTON_URL_INVALID؛ لینک‌ها داخلِ متنِ ساده می‌مونن
                logger.warning("ارسالِ پیامِ دکمه‌دار ناموفق بود؛ نسخه‌ی متنیِ بدونِ دکمه فرستاده می‌شه", exc_info=True)
                text = plain_text(msg) or text
        sent = await self._bot.send_message(chat_id=cid, text=text)
        return str(sent.message_id)

    async def edit_ui(self, chat_id: str, message_id: str, msg: UiMessage) -> bool:
        cid, mid = int(chat_id), int(message_id)
        try:
            if msg.keyboard_only:
                await self._bot.edit_message_reply_markup(chat_id=cid, message_id=mid, reply_markup=self._inline(msg.rows))
                return True
            if msg.photo or msg.contact or msg.document or msg.menu or msg.request_contact or msg.remove_menu:
                return False  # متن→عکس/کیبوردِ پایدار قابل‌ویرایش نیست؛ deliver حذف+ارسالِ تازه می‌کنه
            await self._bot.edit_message_text(text=msg.text or "…", chat_id=cid, message_id=mid, reply_markup=self._inline(msg.rows))
            return True
        except AiogramError as exc:
            if "not modified" in str(exc).lower():
                return True
            logger.info("ویرایشِ پیام ممکن نشد (%s)؛ پیامِ تازه می‌ره", str(exc)[:80])
            return False
        except Exception:  # noqa: BLE001
            logger.warning("ویرایشِ پیام ناموفق بود", exc_info=True)
            return False

    async def delete_message(self, chat_id: str, message_id: str) -> None:
        try:
            await self._bot.delete_message(chat_id=int(chat_id), message_id=int(message_id))
        except Exception:  # noqa: BLE001 — حذف «بهترِ ممکن» است
            logger.debug("حذفِ پیام ممکن نشد", exc_info=True)

    async def answer_callback(self, callback_id: str, text: str = "", alert: bool = False) -> None:
        await self._bot.answer_callback_query(callback_query_id=callback_id, text=text or None, show_alert=alert)


async def _send_with_buttons(bot, chat_id: int, text: str, buttons=None) -> None:
    """``buttons``: لیستی از (برچسب, url) به‌صورت دکمه‌ی شیشه‌ای. اگه تلگرام پیامِ
    دکمه‌دار رو رد کرد (مثلاً URLِ نامعتبر برای دکمه)، همون متن بدون دکمه
    فرستاده می‌شه — لینک باید توی متن هم باشه، پس چیزی گم نمی‌شه."""
    if buttons:
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=label, url=url)] for label, url in buttons]
        )
        try:
            await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)
            return
        except Exception:  # noqa: BLE001
            logger.warning("ارسال پیام با دکمه ناموفق بود؛ بدون دکمه دوباره امتحان می‌شه", exc_info=True)
    await bot.send_message(chat_id=chat_id, text=text)


async def check_token_via_proxies(token: str, proxies, api_base: str = "") -> AdapterStatus:
    """تستِ توکن از طریقِ لیستی از پروکسی‌ها: اولین پروکسی که وصل شد جواب می‌ده. اگه هیچ‌کدوم
    وصل نشد، خطای آخرین. لیست خالی = اتصالِ مستقیم. توکنِ نامعتبر همون‌جا (بدون امتحانِ بقیه)
    گزارش می‌شه چون به پروکسی ربطی نداره."""
    candidates = list(proxies or []) or [""]
    last = AdapterStatus(state=STATE_ERROR, error=MSG_NO_CONNECTION, error_code=ERR_NO_CONNECTION)
    for proxy in candidates:
        status = await check_token(token, proxy, api_base)
        if status.connected or status.error_code in (ERR_INVALID_TOKEN, ERR_BAD_PROXY):
            return status
        last = status
    return last


async def webhook_url(token: str, proxy: str = "", api_base: str = "") -> str:
    """N10 (عیب‌یاب): آدرسِ webhookِ فعالِ ربات؛ خالی = ندارد. هر خطا ← ``RuntimeError`` با پیامِ بدونِ توکن."""
    try:
        bot = _make_bot(token, proxy, api_base)
    except (_BadProxy, _BadToken) as exc:
        raise RuntimeError("توکن یا پروکسی نامعتبره.") from exc
    try:
        info = await bot.get_webhook_info(request_timeout=15)
        return info.url or ""
    except AiogramError as exc:
        raise RuntimeError(redact(str(exc), token, proxy)[:120]) from exc
    finally:
        await bot.session.close()


async def check_token(token: str, proxy: str = "", api_base: str = "") -> AdapterStatus:
    """تست سریع یه توکن بدون شروع polling — برای دکمه‌ی «تست اتصال» توی UI."""
    try:
        bot = _make_bot(token, proxy, api_base)
    except _BadProxy:
        return AdapterStatus(state=STATE_ERROR, error=MSG_BAD_PROXY, error_code=ERR_BAD_PROXY)
    except _BadToken:
        return AdapterStatus(state=STATE_ERROR, error=MSG_INVALID_TOKEN, error_code=ERR_INVALID_TOKEN)
    try:
        me = await bot.get_me(request_timeout=15)
        return AdapterStatus(state=STATE_CONNECTED, username=me.username)
    except TelegramUnauthorizedError:
        return AdapterStatus(state=STATE_ERROR, error=MSG_INVALID_TOKEN, error_code=ERR_INVALID_TOKEN)
    except AiogramError as exc:
        logger.warning("تست اتصال تلگرام ناموفق: %s", redact(str(exc), token, proxy))
        return AdapterStatus(state=STATE_ERROR, error=MSG_NO_CONNECTION, error_code=ERR_NO_CONNECTION)
    finally:
        await bot.session.close()
