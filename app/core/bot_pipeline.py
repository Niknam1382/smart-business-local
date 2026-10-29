"""
پایپ‌لاین مشترک پردازش پیام‌های ورودی از تلگرام/بله: چک بلاک‌لیست، ادغام
پیام‌های پشت‌سرهم (debounce)، فراخوانی موتور AI، ذخیره در تاریخچه، و ارسال
پاسخ.

این ماژول از هیچ کتابخونه‌ی مخصوص تلگرام/بله (aiogram، aiohttp) استفاده
نمی‌کنه — آداپتور هر پلتفرم (telegram_adapter.py / bale_adapter.py) این رو
صدا می‌زنه و فقط یه تابع «send» متناسب با همون پلتفرم بهش می‌ده. جدا
نگه‌داشتنش یعنی می‌شه کل منطق «چه‌جوری به یه پیام جواب بدیم» رو با یه
send/AI جعلی و بدون شبیه‌سازی تلگرام/بله واقعی تست کرد.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, replace
from typing import Awaitable, Callable, Hashable, Optional

from app.core import ai_engine, ai_usage
from app.core.customers import CustomerStore
from app.core.conversations import ConversationStore
from app.core import shop_texts
from app.core.debounce import Debouncer
from app.core.channel_gate import JOINED_CALLBACK, POINT_AI, POINT_SHOP
from app.core.modes import resolve_mode
from app.core.ui import Btn, FlowResult, SendOnlyTransport, Transport, UiMessage, deliver, plain_text

logger = logging.getLogger(__name__)

# send(text) یا send(text, buttons=[(برچسب, url), ...]) — آداپتورها هر دو شکل رو پشتیبانی می‌کنن
SendFn = Callable[..., Awaitable[None]]

# الگوی ادغام پیام: طبق تصمیم MASTER_PROMPT، پورت‌شده از نسخه‌ی SaaS ابری.
DEBOUNCE_WAIT_SECONDS = 3.0
DEBOUNCE_MAX_WAIT_SECONDS = 10.0
HISTORY_LIMIT = 20

# محافظ ساده‌ی سیل پیام (جدا از دیباونس و از بلاک‌لیست دستی): بیشتر از این تعداد
# پیام از یه مکالمه توی این بازه نادیده گرفته می‌شه. مهم برای صاحب کسب‌وکاری که
# API پولی داره — یه مزاحم نباید بتونه هزاران درخواست بسوزونه.
FLOOD_MAX_MESSAGES = 20
FLOOD_WINDOW_SECONDS = 60.0

# پاسخ پیش‌فرض به مشتری نهایی وقتی AI جواب نده — فارسی و قابل‌فهم، بدون
# جزئیات فنی (جزئیات فنی توی لاگ برنامه ثبت می‌شه، نه توی پیام به مشتری).
DEFAULT_ERROR_REPLY_FA = (
    "متأسفم، الان امکان پاسخ‌گویی نیست. لطفاً چند لحظه‌ی دیگر دوباره امتحان کنید."
)


class RateLimiter:
    """پنجره‌ی لغزان: حداکثر ``max_events`` رویداد در هر ``window_seconds`` برای هر کلید."""

    def __init__(self, max_events: int, window_seconds: float, clock=time.monotonic):
        self._max = max_events
        self._window = window_seconds
        self._clock = clock
        self._events: dict[Hashable, deque] = {}

    def allow(self, key: Hashable) -> bool:
        now = self._clock()
        events = self._events.setdefault(key, deque())
        while events and now - events[0] > self._window:
            events.popleft()
        if len(events) >= self._max:
            return False
        events.append(now)
        return True


def _is_command(text: str, command: str) -> bool:
    parts = (text or "").strip().split()
    return bool(parts) and parts[0].split("@")[0].lower() == command


@dataclass
class IncomingMessage:
    platform: str
    chat_id: str
    display_name: str
    text: str
    callback_data: str = ""  # کلیکِ دکمه‌ی شیشه‌ای (R1)؛ متن در این حالت خالیه
    callback_id: str = ""
    message_id: str = ""  # پیامی که دکمه روش زده شد (برای ویرایش)
    language_code: str = ""
    phone: str = ""  # شماره‌ی اشتراک‌گذاری‌شده با دکمه‌ی «اشتراکِ شماره»
    reply_to_id: str = ""  # شناسه‌ی پیامی که این پیام Reply به آن بوده (مسیریابیِ جوابِ مالک)
    username: str = ""  # N12 (CRM): فقط چیزی که خودِ پلتفرم برای فرستنده می‌فرسته؛ هرگز حدس/جست‌وجو نمی‌شه
    first_name: str = ""
    last_name: str = ""
    is_premium: bool = False


class ConversationPipeline:
    def __init__(
        self,
        settings,
        store: Optional[ConversationStore] = None,
        error_reply: str = DEFAULT_ERROR_REPLY_FA,
        debounce_wait: float = DEBOUNCE_WAIT_SECONDS,
        debounce_max_wait: float = DEBOUNCE_MAX_WAIT_SECONDS,
        flood_max: int = FLOOD_MAX_MESSAGES,
        flood_window: float = FLOOD_WINDOW_SECONDS,
        store_agent=None,  # Optional[StoreAgent] — None یعنی این ربات فروشگاهی نیست
        owner_console=None,  # Optional[OwnerConsole] — فرمان‌های مالک (/confirm ...) از چتِ ثبت‌شده‌ی خودش
        admin_panel=None,  # Optional[AdminPanel] — N11: /id، دعوتِ مدیر، /admin و دکمه‌های adm:…
        shop_flow=None,  # Optional[ShopFlow] — فروشگاهِ دکمه‌ای (R1)
        handoff=None,  # Optional[HandoffService] — پشتیبانیِ انسانی (R5)
        limits=None,  # Optional[UsageLimiter] — سقفِ مصرفِ AI (R10-۳)
        qa_agent=None,  # Optional[QaAgent] — پرسش‌وپاسخِ فقط‌خواندنی در حالت‌های دکمه‌ای
        customers=None,  # Optional[CustomerStore] — N12 (CRM)؛ None = از همین store ساخته می‌شه
        channel_gate=None,  # Optional[ChannelGate] — N13: عضویتِ اجباریِ کانال (None = بدونِ دروازه)
        admins=None,  # Optional[AdminStore] — N13: مالک و مدیرانِ فعال از دروازه معافند
    ):
        self._settings = settings
        self._store = store or ConversationStore()
        self._customers = customers or CustomerStore(self._store)
        self._error_reply = error_reply
        self._store_agent = store_agent
        self._owner_console = owner_console
        self._admin_panel = admin_panel
        self._shop_flow = shop_flow
        self._handoff = handoff
        self._limits = limits
        self._qa_agent = qa_agent
        self._gate = channel_gate
        self._admins = admins
        self._transports: dict[tuple, Transport] = {}
        self._debouncer = Debouncer(
            self._on_flush,
            wait_seconds=debounce_wait,
            max_wait_seconds=debounce_max_wait,
        )
        self._limiter = RateLimiter(flood_max, flood_window)
        self._send_fns: dict[tuple, SendFn] = {}
        # هر مکالمه پردازشش پشت یه قفل سریالی می‌شه: اگه مشتری وسط انتظار پاسخ
        # اول، دسته‌ی دوم رو بفرسته، جواب دوم باید بعد از اولی (و با تاریخچه‌ی
        # شاملِ جواب اول) تولید بشه، نه هم‌زمان و با ترتیب به‌هم‌ریخته.
        self._chat_locks: dict[tuple, asyncio.Lock] = {}
        # موتور محلی هم‌زمان‌امن نیست → کل تماس‌های AI پشت یه قفل مشترک.
        self._engine_lock = asyncio.Lock()
        self._engine = None
        self._engine_signature: Optional[tuple] = None

    @property
    def store(self) -> ConversationStore:
        return self._store

    def _settings_signature(self) -> tuple:
        s = self._settings
        return (
            s.ai_mode,
            s.api_base_url,
            s.get_api_key(),
            s.api_model_name,
            s.model_tier,
            str(s.get_model_storage_dir()),
            json.dumps(getattr(s, "ai_providers", []), sort_keys=True, ensure_ascii=False),  # N16: تغییرِ ارائه‌دهنده/مدل ⇒ موتورِ تازه
            getattr(s, "ai_local_fallback", False),
            getattr(s, "ai_attempt_timeout", 15), getattr(s, "ai_total_timeout", 45), getattr(s, "ai_max_targets", 3), getattr(s, "ai_provider_concurrency", 4),
        )

    def _get_engine(self):
        """موتور AI رو کش می‌کنه و فقط وقتی تنظیمات واقعاً عوض شده دوباره
        می‌سازه — حیاتیه برای حالت محلی: ساختن LocalEngine جدید به‌ازای هر
        پیام یعنی مدل چندگیگابایتی هر بار از نو لود بشه."""
        sig = self._settings_signature()
        if self._engine is None or sig != self._engine_signature:
            old_engine = self._engine
            self._engine = ai_engine.build_engine_from_settings(self._settings)
            self._engine_signature = sig
            if old_engine is not None and hasattr(old_engine, "unload"):
                old_engine.unload()
        return self._engine

    async def handle_incoming(self, message: IncomingMessage, send: SendFn, transport: Optional[Transport] = None) -> None:
        """نقطه‌ی ورود هر آداپتور برای هر پیام/کلیکِ جدید (قبل از هر ادغامی).

        ``transport``: عملیاتِ غنیِ آداپتور (ارسال با کیبورد، ویرایش، پاسخ به callback)؛ بدونِ آن فقط متن فرستاده می‌شه."""
        transport = transport or SendOnlyTransport(send)
        is_callback = bool(message.callback_data)
        if not is_callback and _is_command(message.text, "/forget"):
            await self._forget(message, send)
            return
        # پنلِ مدیریت (N11): /id، دعوتِ مدیر، /admin و دکمه‌های adm:… هیچ‌وقت وارد گفتگوی مشتری/AI نمی‌شن
        if self._admin_panel is not None:
            try:
                if await self._admin_panel.handle(message, send, transport, rate_ok=lambda: self._limiter.allow(("adm", message.platform, message.chat_id))):
                    return
            except Exception:  # noqa: BLE001 — خرابیِ پنل نباید ربات را از کار بندازه
                logger.exception("خطا در پنلِ مدیریت")
        # فرمان‌های مالک (و ثبتِ مالک با کد) هیچ‌وقت وارد گفتگوی مشتری/AI نمی‌شن
        if self._owner_console is not None and not is_callback:
            try:
                if await self._owner_console.handle(message.platform, message.chat_id, message.text, send, reply_to=message.reply_to_id):
                    return
            except Exception:  # noqa: BLE001 — خرابیِ کنسول نباید ربات رو از کار بندازه
                logger.exception("خطا در کنسول مالک")
        self._store.ensure_conversation(message.platform, message.chat_id, message.display_name)
        try:
            self._customers.touch(message)
        except Exception:  # noqa: BLE001 — خرابیِ CRM هرگز نباید پاسخ‌دهی به مشتری را متوقف کنه
            logger.debug("ثبتِ مشتری (CRM) ناموفق بود", exc_info=True)
        if self._store.is_blocked(message.platform, message.chat_id):
            await self._ack(transport, message)
            return
        if not is_callback:  # N7: /stop و /start ↔ لغو/ازسرگیریِ پیامِ همگانی (هرگز گرفتارِ محدودیتِ سیل نمی‌شه)
            if _is_command(message.text, "/stop"):
                await self._opt_out(message, send)
                return
            if _is_command(message.text, "/start"):
                await self._opt_back_in(message, send)
        key = (message.platform, message.chat_id)
        if not self._limiter.allow(key):
            logger.warning("سیل پیام از %s/%s — پیام نادیده گرفته شد", message.platform, message.chat_id)
            await self._ack(transport, message)
            return
        mode = resolve_mode(self._settings, message.platform)
        buttons_mode = mode.buttons and self._shop_flow is not None
        if self._gate is not None and is_callback and message.callback_data == JOINED_CALLBACK:
            message = await self._gate_joined(message, transport)  # N13: دکمه‌ی «عضو شدم» (بدونِ کش)
            if message is None:
                return
            is_callback = False
        if buttons_mode:
            if await self._gate_stops(message, transport, POINT_SHOP):  # N13: منو/سبد/سفارش
                return
            result = await self._shop_flow.handle(message)
            if result.consumed:
                await self._deliver_flow(transport, message, result)
                return
            if is_callback:
                await self._ack(transport, message)
                return
            if result.ai_text:
                message = replace(message, text=result.ai_text)
        elif is_callback:  # حالتِ بدونِ دکمه: کلیکِ قدیمی بی‌اثره
            await self._ack(transport, message)
            return
        if not message.text:
            return
        if not (buttons_mode and self._gate_covers(message.platform, POINT_SHOP)):  # N13: گفتگو با AI (وقتی نقطه‌ی «فروشگاه» قبلاً بررسی نشده)
            if await self._gate_stops(message, transport, POINT_AI):
                return
        if not mode.buttons and getattr(self._settings, "ai_disclosure_enabled", True) and _is_command(message.text, "/start"):
            try:  # حالتِ مشاوره/AIِ خالص: خطِ شفافیت جدا فرستاده می‌شه و بعدش AI طبقِ معمول جواب می‌ده
                await send(shop_texts.t("privacy.ai_disclosure", lang=shop_texts.resolve_lang(self._settings, message.language_code)))
            except Exception:  # noqa: BLE001
                logger.exception("ارسالِ خطِ شفافیتِ AI ناموفق بود")
        if self._handoff is not None and self._handoff.is_open(message.platform, message.chat_id):
            await self._handoff.relay_customer(message)  # گفتگوی انسانی باز است: AI ساکت، پیام مستقیم به مالک
            return
        self._send_fns[key] = send
        self._transports[key] = transport
        self._debouncer.feed(key, message.text)

    # ----------------------------------------------------------- N7: لغو/ازسرگیریِ پیامِ همگانی ----

    async def _opt_out(self, message: IncomingMessage, send: SendFn) -> None:
        """/stop: دیگه پیامِ همگانی نمی‌گیره؛ پاسخ به سؤال‌ها و پیگیریِ سفارش مثلِ قبل کار می‌کنه. همیشه تأیید می‌دیم (حتی اگه از قبل لغو کرده بود)."""
        try:
            self._customers.set_opted_out(message.platform, message.chat_id, True)
        except Exception:  # noqa: BLE001
            logger.exception("ثبتِ لغوِ پیامِ همگانی ناموفق بود")
        try:
            await send(shop_texts.t("broadcast.stopped", lang=shop_texts.resolve_lang(self._settings, message.language_code)))
        except Exception:  # noqa: BLE001
            logger.exception("ارسالِ تأییدِ /stop ناموفق بود")

    async def _opt_back_in(self, message: IncomingMessage, send: SendFn) -> None:
        """/start: اگه مشتری قبلاً /stop زده بود، دوباره عضوِ پیامِ همگانی می‌شه (و یک خطِ تأیید می‌گیره)؛ وگرنه هیچ‌چیز."""
        try:
            existing = self._customers.get(message.platform, message.chat_id)
            if existing is not None and existing.opted_out:
                self._customers.set_opted_out(message.platform, message.chat_id, False)
                await send(shop_texts.t("broadcast.resumed", lang=shop_texts.resolve_lang(self._settings, message.language_code)))
        except Exception:  # noqa: BLE001 — خرابیِ این مسیر هرگز /start را نمی‌خوابونه
            logger.debug("ازسرگیریِ پیامِ همگانی ناموفق بود", exc_info=True)

    # ------------------------------------------------------ N13: عضویتِ اجباریِ کانال ----

    def _gate_covers(self, platform: str, point: str) -> bool:
        try:
            return self._gate is not None and self._gate.enabled_for(platform, point)
        except Exception:  # noqa: BLE001 — تنظیمِ خراب = بدونِ دروازه
            logger.exception("خطا در تنظیمِ دروازه‌ی کانال")
            return False

    def _gate_exempt(self, message: IncomingMessage) -> bool:
        """مالک و مدیرانِ فعال (هر نقش) هرگز با دروازه متوقف نمی‌شن؛ مدیرِ در انتظار/غیرفعال مشتریِ عادی است."""
        if self._admins is None:
            return False
        try:
            return bool(self._admins.role_of(message.platform, message.chat_id))
        except Exception:  # noqa: BLE001
            return False

    async def _gate_stops(self, message: IncomingMessage, transport: Transport, point: str) -> bool:
        """``True`` = مشتری عضوِ کانالِ اجباری نیست و پیامِ «اول عضو شو» فرستاده شد (پردازش باید همین‌جا تمام بشه).
        هر خطا = fail-open (گذر)؛ ``/start`` همیشه تازه بررسی می‌شه تا کسی که همین الان عضو شده معطل نشه."""
        if not self._gate_covers(message.platform, point) or self._gate_exempt(message):
            return False
        force = not message.callback_data and _is_command(message.text, "/start")
        try:
            verdict = await self._gate.check(message.platform, message.chat_id, force=force)
        except Exception:  # noqa: BLE001
            logger.exception("بررسیِ عضویتِ کانال ناموفق بود؛ مشتری رد شد (fail-open)")
            return False
        if verdict.allowed:
            return False
        lang = shop_texts.resolve_lang(self._settings, message.language_code)
        rows = [[Btn(shop_texts.t("channel.join", lang=lang, title=ch.label), url=ch.link)] for ch in verdict.missing]
        rows.append([Btn(shop_texts.t("channel.joined", lang=lang), data=JOINED_CALLBACK)])
        await self._deliver_flow(transport, message, FlowResult(messages=[UiMessage(shop_texts.t("channel.required", lang=lang), rows=rows)]))
        return True

    async def _gate_joined(self, message: IncomingMessage, transport: Transport) -> Optional[IncomingMessage]:
        """دکمه‌ی «عضو شدم»: بررسیِ تازه. ``None`` = هنوز عضو نیست (هشدار داده شد)؛ وگرنه یک «/start»ِ ساختگی برمی‌گردونه تا مشتری وارد منو/گفتگو بشه."""
        proceed = replace(message, text="/start", callback_data="", callback_id="", message_id="")
        if self._gate is None or self._gate_exempt(message) or not self._gate.channels(message.platform):
            await self._ack(transport, message)  # دکمه‌ی قدیمی (دروازه خاموش/مدیر): فقط ادامه
            return proceed
        lang = shop_texts.resolve_lang(self._settings, message.language_code)
        try:
            verdict = await self._gate.check(message.platform, message.chat_id, force=True)
        except Exception:  # noqa: BLE001
            logger.exception("بررسیِ عضویتِ کانال ناموفق بود؛ مشتری رد شد (fail-open)")
            verdict = None
        if verdict is not None and verdict.blocked:
            await deliver(transport, message.chat_id, FlowResult(messages=[], answer=shop_texts.t("channel.still_missing", lang=lang), alert=True), callback_id=message.callback_id)
            return None
        await deliver(transport, message.chat_id, FlowResult(messages=[], answer=shop_texts.t("channel.confirmed", lang=lang)), callback_id=message.callback_id)
        if message.message_id:
            try:
                await transport.delete_message(message.chat_id, message.message_id)  # پیامِ «اول عضو شو» دیگه لازم نیست
            except Exception:  # noqa: BLE001
                logger.debug("حذفِ پیامِ دروازه ناموفق بود", exc_info=True)
        return proceed

    async def _forget(self, message: IncomingMessage, send: SendFn) -> None:
        """«حذفِ داده‌ی من»: مکالمه/سبد/چک‌اوتِ نیمه‌کاره + مشخصاتِ سفارش‌های بسته‌شده؛ سفارش‌های باز و بلاک‌شدن دست‌نخورده."""
        platform, chat_id = message.platform, str(message.chat_id)
        self._debouncer.cancel((platform, chat_id))  # پیامِ در انتظارِ ادغام هم دور ریخته می‌شه
        if self._handoff is not None:
            self._handoff.close(platform, chat_id, "forgotten")
        self._store.forget_chat(platform, chat_id)
        if self._shop_flow is not None:
            self._shop_flow.carts.clear(platform, chat_id)
            self._shop_flow.sessions.clear(platform, chat_id)
            self._shop_flow.orders.anonymize_chat(platform, chat_id)
            self._shop_flow.discounts.forget_chat(platform, str(chat_id))  # N8: کدِ سبد و تلاش‌های اشتباه
        try:
            await send(shop_texts.t("privacy.forgotten", lang=shop_texts.resolve_lang(self._settings, message.language_code)))
        except Exception:  # noqa: BLE001
            logger.exception("ارسالِ تاییدِ /forget ناموفق بود")

    @staticmethod
    async def _ack(transport: Transport, message: IncomingMessage) -> None:
        if message.callback_id:
            try:
                await transport.answer_callback(message.callback_id, "", False)
            except Exception:  # noqa: BLE001
                logger.debug("answerCallbackQuery ناموفق", exc_info=True)

    async def _deliver_flow(self, transport: Transport, message: IncomingMessage, result: FlowResult) -> None:
        await deliver(transport, message.chat_id, result, callback_id=message.callback_id, source_message_id=message.message_id)
        for msg in result.messages:
            if msg.log and msg.text:
                self._store.add_message(message.platform, message.chat_id, "assistant", plain_text(msg))

    async def _on_flush(self, key: tuple, merged_text: str) -> None:
        lock = self._chat_locks.setdefault(key, asyncio.Lock())
        async with lock:
            await self._process(key, merged_text)

    async def _process(self, key: tuple, merged_text: str) -> None:
        platform, chat_id = key
        send = self._send_fns.get(key)
        if send is None:
            return  # نباید پیش بیاد، ولی محافظه‌کارانه

        if self._limits is not None:
            verdict = self._limits.check_ai(platform, chat_id)
            if verdict != "ok":  # سقف/کلیدِ قطع: AI صدا زده نمی‌شه؛ مشتری مؤدبانه به منو هدایت می‌شه
                notice = shop_texts.t(f"limit.{verdict}")
                self._store.add_message(platform, chat_id, "user", merged_text)
                self._store.add_message(platform, chat_id, "assistant", notice)
                try:
                    await send(notice)
                except Exception:  # noqa: BLE001
                    logger.exception("ارسالِ پیامِ سقف به %s/%s ناموفق بود", platform, chat_id)
                await self._limits.maybe_alert()
                return

        # مهم: تاریخچه رو قبل از ذخیره‌ی پیام تازه می‌خونیم، وگرنه همین پیام
        # هم توی history میاد و هم به‌عنوان user_message جدا — یعنی تکراری
        # به AI فرستاده می‌شه.
        memory_on = self._store.is_memory_enabled(platform, chat_id)
        expire_hours = getattr(self._settings, "memory_expire_hours", 0)
        if memory_on and expire_hours:
            idle_seconds = self._store.time_since_last_message_seconds(platform, chat_id)
            if idle_seconds is not None and idle_seconds > expire_hours * 3600:
                memory_on = False  # مدت زیادی از آخرین پیام گذشته -> انگار مکالمه تازه‌ست
        history_limit = getattr(self._settings, "memory_history_limit", HISTORY_LIMIT)
        history = self._store.get_history(platform, chat_id, limit=history_limit) if memory_on else []

        self._store.add_message(platform, chat_id, "user", merged_text)

        outbox: list = []
        try:
            system_prompt = self._settings.system_prompt or "You are a helpful assistant."
            engine = self._get_engine()
            mode = resolve_mode(self._settings, platform)
            if self._agent_enabled(engine) or self._qa_enabled(engine, mode):
                display_name = self._store.get_display_name(platform, chat_id)

                async def call_engine(sys_prompt, hist, user_msg, specs, tool_messages):
                    if getattr(engine, "concurrent_safe", False):
                        return await asyncio.to_thread(engine.chat_tools, sys_prompt, hist, user_msg, specs, tool_messages)
                    async with self._engine_lock:
                        return await asyncio.to_thread(engine.chat_tools, sys_prompt, hist, user_msg, specs, tool_messages)

                if self._agent_enabled(engine):
                    with ai_usage.bind(platform, chat_id, "agent"):  # N1: مصرف به همین چت نسبت داده می‌شه (contextvar تا داخلِ thread می‌رسه)
                        agent_reply = await self._store_agent.respond(
                            call_engine, self._settings, platform, chat_id, display_name, system_prompt, history, merged_text
                        )
                else:
                    with ai_usage.bind(platform, chat_id, "qa"):
                        agent_reply = await self._qa_agent.respond(
                            call_engine, self._settings, platform, chat_id, display_name, system_prompt, history, merged_text,
                            can_suggest=mode.cart,
                        )
                reply, outbox = agent_reply.text, agent_reply.outbox
            elif getattr(engine, "concurrent_safe", False):
                with ai_usage.bind(platform, chat_id, "chat"):
                    reply = await asyncio.to_thread(engine.chat, system_prompt, history, merged_text)
            else:
                async with self._engine_lock:
                    with ai_usage.bind(platform, chat_id, "chat"):
                        reply = await asyncio.to_thread(engine.chat, system_prompt, history, merged_text)
        except ai_engine.AiEngineError as exc:
            logger.error("خطای AI برای %s/%s: %s", platform, chat_id, exc)
            reply = self._error_reply
        except Exception:  # noqa: BLE001 — خطای غیرمنتظره نباید کل ربات رو متوقف کنه
            logger.exception("خطای غیرمنتظره در پردازش پیام %s/%s", platform, chat_id)
            reply = self._error_reply

        if self._limits is not None:
            self._limits.record_ai(platform, chat_id, (len(merged_text) + len(reply or "")) // 3)

        # پیام‌های «دقیق» (شماره کارت/لینک پرداخت) هم توی تاریخچه می‌رن تا هم صاحب
        # فروشگاه توی «گفتگوها» ببینه، هم مدل توی نوبت بعد بدونه چی فرستاده شده
        if reply:
            self._store.add_message(platform, chat_id, "assistant", reply)
        for msg in outbox:
            text = plain_text(msg) if isinstance(msg, UiMessage) else msg.text
            if text:
                self._store.add_message(platform, chat_id, "assistant", text)

        try:
            if reply:
                await send(reply)
            transport = self._transports.get(key) or SendOnlyTransport(send)
            for msg in outbox:
                if isinstance(msg, UiMessage):
                    await deliver(transport, chat_id, FlowResult([msg]))
                elif msg.buttons:
                    await send(msg.text, buttons=msg.buttons)
                else:
                    await send(msg.text)
        except Exception:  # noqa: BLE001
            logger.exception("ارسال پاسخ به %s/%s ناموفق بود", platform, chat_id)
        if self._limits is not None:
            await self._limits.maybe_alert()

    def _agent_enabled(self, engine) -> bool:
        """ایجنتِ فروشگاه فقط وقتی کار می‌کنه که حالتِ کسب‌وکار «فروشگاه» باشه و موتور
        ابزار بفهمه؛ وگرنه همون گفتگوی ساده."""
        return (
            self._store_agent is not None
            and getattr(self._settings, "business_mode", "") == "store"
            and resolve_mode(self._settings).store_agent
            and hasattr(engine, "chat_tools")
        )

    def _qa_enabled(self, engine, mode) -> bool:
        """پرسش‌وپاسخِ فقط‌خواندنی (حالت‌های دکمه‌ای) — فقط وقتی موتور ابزار بفهمه."""
        return self._qa_agent is not None and mode.ai_qa and hasattr(engine, "chat_tools")

    async def shutdown(self) -> None:
        await self._debouncer.cancel_all()
