"""
مدیر ربات‌ها: تلگرام و بله رو روی یه ترد پس‌زمینه‌ی جدا (با event loop مخصوص
خودش) اجرا می‌کنه و یه رابط thread-safe به UI می‌ده: start / stop / restart /
get_status.

چرا ترد جدا با loop جدا (و نه سوار شدن روی loop خودِ Flet): مدل داخلی
تردینگ Flet (``page.run_thread`` + یه loop مختص هر session) یه جزئیات
پیاده‌سازیه که نمی‌خوایم ربات‌های همیشه‌روشن بهش وابسته باشن. ترد ما
``daemon`` هم هست تا بستن پنجره‌ی برنامه هیچ‌وقت به‌خاطر یه polling در حال
انتظار گیر نکنه (ترد غیر-daemon جلوی خروج پروسه رو می‌گیره).

قانون ارتباط با UI: ترد ربات هیچ‌وقت مستقیم کنترل Flet رو دست نمی‌زنه و
``page.update()`` صدا نمی‌زنه. UI فقط از طریق ``get_status()`` و دیتابیس
مکالمه‌ها (ConversationStore) وضعیت رو می‌خونه — منبع حقیقت یکیه و هیچ
callback بین‌تردی‌ای وجود نداره که بشه خرابش کرد.

لاگ: در ویندوز exe بدون کنسول اجرا می‌شه، پس خطاهای ترد ربات بدون فایل لاگ
هیچ‌جا دیده نمی‌شن. ``bot.log`` توی پوشه‌ی داده‌ی برنامه نوشته می‌شه — و چون
کاربر ممکنه اون رو برای رفع اشکال به اشتراک بذاره، توکن‌ها قبل از نوشتن
پاک می‌شن (redact.py).
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Optional

from app.core import admins as admins_module
from app.core.admin_panel import AdminPanel
from app.core.admins import AdminStore
from app.core.customers import CustomerStore
from app.core.adapter_common import ERR_UNEXPECTED, STATE_CONNECTED, STATE_ERROR, AdapterStatus, looks_unreachable  # looks_unreachable حالا در adapter_common است؛ همین نام اینجا هم می‌مونه
from app.core.bale_adapter import BaleAdapter
from app.core.bot_pipeline import ConversationPipeline
from app.core.conversations import ConversationStore
from app.core import ai_cache, ai_providers, ai_usage
from app.core import finance as finance_module
from app.core import invoice_service as invoice_service_module
from app.core.campaigns import CampaignService
from app.core.discounts import DiscountStore
from app.core.orders import METHOD_CARD_TO_CARD, OrderStore
from app.core import bot_profile, checkout_fields, shop_texts
from app.core import broadcast as broadcast_module
from app.core import channel_gate as channel_gate_module
from app.core import owner_console as owner_console_module
from app.core.attention import AttentionInbox
from app.core.delivery import DeliveryService
from app.core.handoff import HandoffService, make_ref
from app.core.qa_agent import QaAgent
from app.core.ui import UiMessage
from app.core.usage_limits import UsageLimiter
from app.core.shop_flow import ShopFlow
from app.core.owner_console import OwnerConsole
from app.core.paths import get_app_data_dir
from app.core import payments as payments_module
from app.core.payments import PaymentHooks, PaymentService
from app.core.products import ProductStore
from app.core import proxy_subscription
from app.core.proxy_pool import proxy_config_from_text, proxy_secrets
from app.core.store_agent import StoreAgent
from app.core.redact import redact
from app.core.telegram_adapter import TelegramAdapter

logger = logging.getLogger(__name__)

PLATFORMS = ("telegram", "bale")
LOG_FILE_NAME = "bot.log"
PROFILE_INTERVAL_SECONDS = 24 * 3600  # N17: هر ۲۴ ساعتِ اجرا بیوگرافیِ ربات دوباره بررسی می‌شه (خطِ اعتبار برگردونده بشه)
PROFILE_POLL_SECONDS = 5.0  # تا وقتی آداپتور وصل نشده هر چند ثانیه دوباره نگاه کن
PROFILE_RETRY_SECONDS = 600.0  # خطای شبکه/flood (۴۲۹): بی‌صدا با تلاشِ بعدی

AdapterFactory = Callable[["object", ConversationPipeline], object]


class BotManagerError(Exception):
    """خطای قابل‌نمایش (فارسی) به کاربر."""


@dataclass
class ManagerStatus:
    running: bool = False
    platforms: dict = field(default_factory=lambda: {name: AdapterStatus() for name in PLATFORMS})


# ------------------------------------------------------------------ لاگ ----


class RedactingFormatter(logging.Formatter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.secrets: list = []

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record), *self.secrets)


_log_handler: Optional[RotatingFileHandler] = None
_log_formatter: Optional[RedactingFormatter] = None


def configure_logging(secrets: list, log_dir: Optional[Path] = None) -> Path:
    """لاگ فایلی (چرخشی) برای ربات‌ها؛ بی‌خطر برای صدا زدن چندباره. برمی‌گردونه
    مسیر فایل لاگ رو. ``secrets`` = مقادیر متنی که نباید توی فایل بیان."""
    global _log_handler, _log_formatter
    path = (log_dir or get_app_data_dir()) / LOG_FILE_NAME

    if _log_handler is not None and Path(_log_handler.baseFilename) != path.resolve():
        for name in ("app", "aiogram"):
            logging.getLogger(name).removeHandler(_log_handler)
        _log_handler.close()
        _log_handler = None

    if _log_handler is None:
        _log_formatter = RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        _log_handler = RotatingFileHandler(path, maxBytes=512_000, backupCount=2, encoding="utf-8")
        _log_handler.setFormatter(_log_formatter)
        for name in ("app", "aiogram"):
            lg = logging.getLogger(name)
            lg.addHandler(_log_handler)
            if lg.level == logging.NOTSET or lg.level > logging.INFO:
                lg.setLevel(logging.INFO)

    _log_formatter.secrets = [s for s in secrets if s]
    return path


def shutdown_logging() -> None:
    """برای تست‌ها و بستن تمیز: هندلر فایل رو از لاگرها جدا و بسته می‌کنه."""
    global _log_handler, _log_formatter
    if _log_handler is not None:
        for name in ("app", "aiogram"):
            logging.getLogger(name).removeHandler(_log_handler)
        _log_handler.close()
    _log_handler = None
    _log_formatter = None


# ---------------------------------------------------------------- مدیر ----

# جاروکننده‌ی سفارش‌ها: انقضای رزرو (هر چند ثانیه) و استعلامِ زرین‌پال (چون برنامه روی
# سیستمِ صاحب فروشگاه اجرا می‌شه و آدرس عمومی برای callback نداره)
MAINTENANCE_INTERVAL_SECONDS = 10.0
STALE_EXPIRY_NOTICE_SECONDS = 30 * 60  # بعد از این مدت، انقضا فقط بی‌صدا ثبت می‌شه
RECOVER_INTERVAL_SECONDS = 60.0  # هر چند ثانیه سفارش‌های نیمه‌کاره‌ی saga بررسی بشن
DELIVERY_RETRY_MIN_AGE_SECONDS = 20  # تلاشِ مجدد برای تحویل‌های ناموفق
RETENTION_INTERVAL_SECONDS = 3600.0
RECOVER_MIN_AGE_SECONDS = 30  # فقط سفارش‌هایی که این‌قدر وقته نیمه‌کاره‌ان (تاییدِ در جریان رو لمس نکن)
ZARINPAL_POLL_INTERVAL_SECONDS = 20.0


class BotManager:
    def __init__(
        self,
        settings,
        store: Optional[ConversationStore] = None,
        product_store: Optional[ProductStore] = None,
        order_store: Optional[OrderStore] = None,
        adapter_factories: Optional[dict] = None,
        pipeline_kwargs: Optional[dict] = None,
        log_dir: Optional[Path] = None,
        zarinpal_base_url: str = "",
        maintenance_interval: float = MAINTENANCE_INTERVAL_SECONDS,
        recover_interval: float = RECOVER_INTERVAL_SECONDS,
        proxy_sub_fetcher=None,
        zarinpal_poll_interval: float = ZARINPAL_POLL_INTERVAL_SECONDS,
        profile_interval: float = PROFILE_INTERVAL_SECONDS,
        profile_poll: float = PROFILE_POLL_SECONDS,
        profile_retry: float = PROFILE_RETRY_SECONDS,
    ):
        self._settings = settings
        self._profile_interval = profile_interval
        self._profile_poll = profile_poll
        self._profile_retry = profile_retry
        self._profile_reports: dict = {}  # platform → bot_profile.SyncReport (آخرین نتیجه؛ برای UI)
        self._profile_due: dict = {}  # platform → زمانِ (loop.time) بررسیِ بعدی
        self._store = store or ConversationStore()
        # product_store/order_store اختیاری‌ان: یه کاربر در حالت «مشاوره»
        # اصلاً فروشگاه نداره، پس جریان خرید/پرداخت اینجا خاموش می‌مونه.
        self._product_store = product_store
        self._order_store = order_store
        self._customers = CustomerStore(self._store, order_store)  # N12 (CRM)
        self._usage = ai_usage.UsageStore(self._store)  # N1: مصرفِ توکن/هزینه
        ai_usage.RECORDER = self._usage
        ai_cache.install_hooks()  # N18: ابطالِ کشِ پاسخ با هر تغییرِ داده (کمربندوتسمه؛ کلیدِ محتوا خودش هم امن است)
        ai_providers.HEALTH.notifier = self._notify_owner_threadsafe  # N16: هشدارِ یک‌باره‌ی قطع/وصلِ APIها
        self._admins = AdminStore(self._store, lambda: dict(getattr(self._settings, "owner_chats", {}) or {}))  # N11
        self._payments = (
            PaymentService(order_store, product_store, settings, zarinpal_base_url=zarinpal_base_url)
            if (order_store and product_store)
            else None
        )
        self._attention = AttentionInbox(self._store)
        # N7 (پیامِ همگانی) و N13 (عضویتِ اجباریِ کانال)
        self._broadcast_store = broadcast_module.BroadcastStore(self._store)
        self._broadcasts = broadcast_module.BroadcastService(
            self._broadcast_store, self._customers, lambda: self._settings, on_resolved=lambda bid: self._attention.handle_ref("broadcast", str(bid))
        )
        # N8: کدِ تخفیف و کمپین (فقط وقتی فروشگاه هست)
        self._discounts = DiscountStore(order_store) if order_store is not None else None
        self._campaigns = (
            CampaignService(order_store, self._discounts, self._broadcasts, lambda: self._settings) if order_store is not None else None
        )
        self._broadcast_engine = broadcast_module.BroadcastEngine(
            self._broadcast_store, self._customers, lambda: self._settings, self._send_broadcast,
            ready=self._adapter_ready, notify=self._notify_owner_text,
            alert=lambda bid, reason: self._attention.add("broadcast", str(bid), f"#{bid}: {reason}"[:200]),
            resolved=lambda bid: self._attention.handle_ref("broadcast", str(bid)),
        )
        self._membership_timeout = 10.0  # ثانیه؛ گیرکردنِ شبکه نباید پیام‌های مشتری را بخوابونه (بعدش fail-open)
        self._gate = channel_gate_module.ChannelGate(
            lambda: self._settings, self._check_membership, on_error=self._on_gate_error, on_recovered=self._on_gate_recovered
        )
        self._handoff = HandoffService(
            self._store, lambda: self._settings, self._send_owner_ids, self._send_customer_text,
            on_no_owner=lambda platform, chat_id: self._attention.add("support_no_owner", make_ref(platform, chat_id), "مشتری پشتیبانی خواست ولی مالکی ثبت نشده"),
        )
        self._limits = UsageLimiter(
            self._store, lambda: self._settings, self._notify_owner_text, on_cap=lambda level: self._attention.add("ai_cap", level, "سقفِ روزانه‌ی AI")
        )
        self._owner = (
            OwnerConsole(
                lambda: self._settings, order_store, product_store, self._deliver, self._persist_settings,
                after_confirm=self._deliver_digital, handoff=self._handoff, admins=self._admins,
            )
            if (order_store and product_store)
            else None
        )
        self._admin_panel = (
            AdminPanel(self._admins, self._owner, order_store, product_store, handoff=self._handoff, discounts=self._discounts, get_settings=lambda: self._settings) if self._owner is not None else None
        )
        self._delivery = DeliveryService(product_store, order_store, lambda: self._settings) if (order_store and product_store) else None
        self._delivery_alerted: set = set()
        self._maintenance_interval = maintenance_interval
        shop_texts.configure(lambda: self._settings)  # متن‌های قابل‌تنظیمِ ربات (R13)
        owner_console_module.set_label_provider(lambda: {f.id: f.label for f in checkout_fields.load_fields(self._settings)})
        self._recover_interval = recover_interval
        self._sub_fetcher = proxy_sub_fetcher  # تزریق‌پذیر برای تست (بدونِ شبکه)
        self._sub_next_try = 0.0
        self._proxy_restart_pending = False
        self._zarinpal_poll_interval = zarinpal_poll_interval
        self._factories = adapter_factories or self._default_factories()
        self._pipeline_kwargs = pipeline_kwargs or {}
        self._log_dir = log_dir

        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()
        self._start_error: Optional[str] = None
        self._pipeline: Optional[ConversationPipeline] = None
        self._adapters: dict = {}
        self._tasks: dict = {}
        # N19: دفترِ مالی + فاکتور (فقط وقتی فروشگاه هست)
        self._finance = None
        self._invoices = None
        self._invoice_tasks: set = set()
        if order_store is not None and product_store is not None:
            self._finance = finance_module.FinanceStore(order_store, product_store)
            self._invoices = invoice_service_module.InvoiceService(
                order_store, lambda: self._settings, doc_sender=self._send_invoice_doc, text_sender=self._send_plain_text,
                can_send=self._invoice_can_send, on_unreachable=self._note_unreachable,
                attention_add=lambda kind, ref, detail: self._attention.add(kind, ref, detail),
                attention_clear=lambda kind, ref: self._attention.handle_ref(kind, ref),
                owner_chats=lambda: dict(getattr(self._settings, "owner_chats", {}) or {}),
            )
            self._invoices.finance = self._finance
            order_store.add_confirm_listener(self._on_order_confirmed)
            if self._admin_panel is not None:
                self._admin_panel.attach_finance(self._finance, self._invoices)

    def _default_factories(self) -> dict:
        def telegram(settings, pipeline):
            proxy, pool = proxy_config_from_text(settings.combined_telegram_proxy_text())
            minutes = int(getattr(settings, "telegram_proxy_best_check_minutes", 10) or 0)
            return TelegramAdapter(settings.get_telegram_token(), pipeline, proxy=proxy, proxy_pool=pool, best_check_interval=minutes * 60.0)

        def bale(settings, pipeline):
            return BaleAdapter(
                settings.get_bale_token(), pipeline, payments=self._payments, on_payment_confirmed=self._notify_payment_confirmed
            )

        return {"telegram": telegram, "bale": bale}

    async def _notify_payment_confirmed(self, order) -> None:
        """بله‌پی همیشه از طریق ربات بله تایید می‌شه، ولی مشتریِ اصلی ممکنه تلگرامی باشه — این تابع
        به آداپتورِ *درستِ* ``order.platform`` پیام می‌ده، نه لزوماً به بله. پیام توی تاریخچه هم
        ثبت می‌شه تا صاحب فروشگاه توی تب «گفتگوها» ببینتش. بعدش مالک هم خبردار می‌شه (فروشِ
        جدید یا «منتظر تاییدته»)."""
        await self._deliver(order.platform, order.chat_id, payments_module.build_payment_notification_text(order), True)
        await self._deliver_digital(order)
        if self._owner is not None:
            await self._owner.alert_order(order)

    async def _deliver_digital(self, order) -> None:
        """تحویلِ محصولِ دیجیتالِ یه سفارشِ تاییدشده (idempotent)؛ شکست = اعلان به مالک (یک‌بار) + تلاشِ مجدد در حلقه‌ی نگهداری."""
        if self._delivery is None:
            return

        async def send_ui(msg) -> None:
            adapter = self._adapters.get(order.platform)
            if adapter is None:
                raise RuntimeError(f"ربات {order.platform} وصل نیست")
            await adapter.send_ui(order.chat_id, msg)

        result = await self._delivery.deliver(order, send_ui)
        if result == "delivered":
            self._delivery_alerted.discard(order.id)
            self._attention.handle_ref("delivery_failed", str(order.id))
        elif result.startswith("failed:") and order.id not in self._delivery_alerted and self._owner is not None:
            self._delivery_alerted.add(order.id)
            self._attention.add("delivery_failed", str(order.id), result[7:][:200])
            await self._owner.notify(shop_texts.t("deliver.failed_owner", order_id=order.id, reason=result[7:][:120]))

    async def _send_owner_ids(self, text: str) -> list:
        """به همه‌ی چت‌های مالک می‌فرسته و ``[(platform, chat_id, message_id)]`` برمی‌گردونه (برای مسیریابیِ Reply)."""
        if self._owner is None:
            return []
        out = []
        targets = list(self._owner.owner_chats().items())
        targets += [(a.platform, a.user_id) for a in self._admins.active_with(admins_module.CAP_SUPPORT_REPLY)]  # N11: پشتیبان‌ها/مدیرها
        for platform, chat_id in targets:
            adapter = self._adapters.get(platform)
            if adapter is None:
                continue
            try:
                message_id = await adapter.send_ui(chat_id, UiMessage(text))
            except Exception:  # noqa: BLE001
                logger.exception("اعلان به مالک (%s) ناموفق بود", platform)
                continue
            out.append((platform, chat_id, message_id or ""))
        return out

    async def _notify_owner_text(self, text: str) -> None:
        if self._owner is not None:
            await self._owner.notify(text)

    @property
    def attention(self) -> AttentionInbox:
        return self._attention

    @property
    def limits(self) -> UsageLimiter:
        return self._limits

    async def _send_customer_text(self, platform: str, chat_id: str, text: str) -> bool:
        return await self._deliver(platform, chat_id, text, True)

    async def _refresh_proxy_subscription(self, force: bool = False) -> str:
        """به‌روزرسانیِ اشتراکِ پروکسی (R6-الف): دوره‌ای (``telegram_proxy_sub_hours``؛ ۰ = دستی) یا با ``force``.
        شکست هرگز کشِ قبلی رو پاک نمی‌کنه؛ بعد از شکست تا ۱۵ دقیقه تلاشِ خودکارِ دیگه‌ای نمی‌شه."""
        settings = self._settings
        url = settings.get_telegram_proxy_sub_url()
        if not url:
            return ""
        now = int(time.time())
        hours = int(settings.telegram_proxy_sub_hours or 0)
        if not force:
            if hours <= 0 or now - int(settings.telegram_proxy_sub_updated_ts) < hours * 3600 or time.monotonic() < self._sub_next_try:
                return ""
        try:
            parsed = await proxy_subscription.fetch_proxies(url, self._sub_fetcher)
        except proxy_subscription.SubscriptionError as exc:
            self._sub_next_try = time.monotonic() + 900
            settings.telegram_proxy_sub_error = str(exc)
            self._persist_settings()
            return f"⚠️ {exc}"
        new_cache = "\n".join(parsed.urls)
        changed = new_cache != settings.get_telegram_proxy_sub_cache()
        settings.set_telegram_proxy_sub_cache(new_cache)
        settings.telegram_proxy_sub_updated_ts = now
        settings.telegram_proxy_sub_error = ""
        self._persist_settings()
        if changed:
            adapter = self._adapters.get("telegram")
            if adapter is not None and adapter.update_proxy_pool(settings.combined_telegram_proxy_text()) == "restart":
                self._proxy_restart_pending = True
        return f"✅ {len(parsed.urls)} پروکسی از اشتراک گرفته شد."

    def refresh_proxy_subscription_sync(self, timeout: float = 30.0) -> str:
        """نسخه‌ی blocking برای UI («به‌روزرسانیِ همین الان»)؛ پیامِ نتیجه رو برمی‌گردونه (هرگز exception نمی‌ده)."""
        with self._lock:
            loop = self._loop
            alive = self.is_running()
        try:
            coro = self._refresh_proxy_subscription(force=True)
            if alive and loop is not None:
                return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=timeout) or "—"
            return asyncio.run(coro) or "—"
        except Exception as exc:  # noqa: BLE001
            return f"⚠️ {exc}"

    def telegram_proxy_info(self) -> dict:
        """پروکسیِ فعلی (بدونِ رمز) + ۱۰ رویدادِ آخرِ جابه‌جایی برای صفحه‌ی ربات‌ها."""
        adapter = self._adapters.get("telegram")
        return {
            "current": adapter.current_proxy if adapter is not None else "",
            "events": list(getattr(adapter, "proxy_events", [])) if adapter is not None else [],
            "restart_pending": self._proxy_restart_pending,
        }

    async def _apply_retention(self) -> None:
        """نگه‌داریِ محدودِ داده (R10-۴): فقط وقتی ``retention_days > 0``."""
        days = int(getattr(self._settings, "retention_days", 0) or 0)
        if days <= 0:
            return
        removed = await asyncio.to_thread(self._store.purge_older_than, days)
        anonymized = await asyncio.to_thread(self._order_store.anonymize_closed, days) if self._order_store else 0
        if removed or anonymized:
            logger.info("نگه‌داریِ داده: %s پیام حذف و %s سفارش ناشناس شد", removed, anonymized)

    async def _expire_handoffs(self) -> None:
        hours = max(1, int(getattr(self._settings, "handoff_timeout_hours", 24) or 24))
        for session in await asyncio.to_thread(self._handoff.expire_stale, hours * 3600):
            await self._deliver(session.platform, session.chat_id, shop_texts.t("handoff.timeout"), True)

    async def _retry_deliveries(self) -> None:
        if self._delivery is None:
            return
        for order_id in await asyncio.to_thread(self._order_store.pending_deliveries, DELIVERY_RETRY_MIN_AGE_SECONDS):
            order = await asyncio.to_thread(self._order_store.get, order_id)
            if order is not None:
                await self._deliver_digital(order)

    def deliver_digital_sync(self, order_id: int, timeout: float = 30.0) -> str:
        """نسخه‌ی blocking برای UI (بعد از تاییدِ دستی)؛ ``delivered``/``nothing``/``failed:...``."""
        with self._lock:
            loop = self._loop
            alive = self.is_running()
        order = self._order_store.get(order_id) if self._order_store else None
        if not alive or loop is None or order is None or self._delivery is None:
            return "failed:ربات خاموشه"
        future = asyncio.run_coroutine_threadsafe(self._deliver_digital(order), loop)
        try:
            future.result(timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            future.cancel()
            return f"failed:{exc}"
        fresh = self._order_store.get(order_id)
        return "delivered" if fresh is not None and fresh.delivered_ts > 0 else ("nothing" if fresh is not None and fresh.delivered_ts == -1 else "failed:تحویل انجام نشد")

    async def _deliver(self, platform: str, chat_id: str, text: str, log_history: bool = True) -> bool:
        """ارسال از طریق آداپتورِ زنده؛ True یعنی رسید. (چت‌های مشتری توی تاریخچه ثبت می‌شن؛ اعلان‌های
        مالک نه.)"""
        adapter = self._adapters.get(platform)
        if adapter is None:
            logger.warning("نمی‌شه به %s/%s پیام داد — آداپتورِ %s وصل نیست", platform, chat_id, platform)
            return False
        try:
            await adapter.send_message(chat_id, text)
        except Exception as exc:  # noqa: BLE001
            logger.exception("ارسال پیام به %s/%s ناموفق بود", platform, chat_id)
            self._note_unreachable(platform, chat_id, exc)
            return False
        if log_history:
            self._store.add_message(platform, chat_id, "assistant", text)
        return True

    # ---------------------------------------------------- پیامِ همگانی (N7) و پیامِ شخصی (N6) ----

    _PLATFORM_FA = {"telegram": "تلگرام", "bale": "بله"}

    def _adapter_ready(self, platform: str) -> bool:
        """آداپتور هست و *وصل* است (نه در حالِ اتصالِ دوباره/خطا) — موتورِ ارسال فقط به پلتفرمِ آماده می‌فرسته."""
        adapter = self._adapters.get(platform)
        if adapter is None:
            return False
        status = getattr(adapter, "status", None)
        return status is None or getattr(status, "state", STATE_CONNECTED) == STATE_CONNECTED

    async def _send_broadcast(self, platform: str, chat_id: str, text: str, photo: str, button) -> str:
        adapter = self._adapters.get(platform)
        if adapter is None:  # بینِ «آماده؟» و ارسال خاموش شد: خطای اتصال (گیرنده سوخته نمی‌شه، تلاشِ دوباره)
            raise ConnectionError(f"ربات {platform} وصل نیست")
        return await adapter.send_strict(chat_id, text, photo=photo, button=button)

    def _run_in_loop(self, make_coro, timeout: float = 20.0):
        """اجرای یک coroutine روی loopِ ربات‌ها از ترد UI و انتظار برای نتیجه (خطاهای فارسیِ خودمان بدونِ تغییر رد می‌شن)."""
        with self._lock:
            loop = self._loop
            alive = self.is_running()
        if not alive or loop is None:
            raise BotManagerError("ربات‌ها خاموشن؛ اول از صفحه‌ی «ربات‌ها» روشنشون کن.")
        future = asyncio.run_coroutine_threadsafe(make_coro(), loop)
        try:
            return future.result(timeout=timeout)
        except (BotManagerError, broadcast_module.BroadcastError):
            raise
        except Exception as exc:  # noqa: BLE001 — timeout و غیره
            future.cancel()
            raise BotManagerError("عملیات انجام نشد؛ اتصال ربات رو چک کن.") from exc

    async def send_to_customer(self, platform: str, chat_id: str, text: str) -> None:
        """N6: پیامِ شخصیِ مالک به یک مشتری (از صفحه‌ی گفتگوها). مشتری «💬 فروشگاه: …» می‌بینه؛ در تاریخچه با نقشِ ``owner`` ثبت
        می‌شه (برای AI به‌صورتِ پیامِ فروشگاه). هرگز به مشتریِ بلاک‌شده یا لغوکرده (/stop)؛ اگه گفتگوی پشتیبانیِ بازی هست همین جواب حساب می‌شه.
        هر مشکل = ``BotManagerError`` فارسی."""
        chat_id = str(chat_id)
        clean = broadcast_module._clean_text(text)  # noqa: SLF001 — همان پاک‌سازیِ محتوای پیامِ همگانی
        if not clean:
            raise BotManagerError("متنِ پیام خالیه.")
        if len(clean) > 3000:
            raise BotManagerError(f"متن بیش از حد بلنده (حداکثر ۳۰۰۰ نویسه؛ الان {len(clean)}).")
        if self._store.is_blocked(platform, chat_id):
            raise BotManagerError("این مشتری بلاک شده؛ اول از بلاک درش بیار.")
        customer = self._customers.get(platform, chat_id)
        if customer is not None and customer.opted_out:
            raise BotManagerError(
                "این مشتری با /stop دریافتِ پیام رو لغو کرده؛ بهش پیام نده. اگه خودش پشتیبانی خواسته، از خودِ تلگرام/بله با Reply روی پیامش جواب بده."
            )
        adapter = self._adapters.get(platform)
        if adapter is None:
            raise BotManagerError("ربات این پلتفرم الان روشن/وصل نیست؛ اول ربات رو روشن کن، بعد دوباره امتحان کن.")
        lang = shop_texts.resolve_lang(self._settings, customer.language_code if customer else "")
        try:
            await adapter.send_message(chat_id, shop_texts.t("owner.direct", lang=lang, text=clean))
        except Exception as exc:  # noqa: BLE001
            logger.exception("ارسالِ پیامِ شخصی به %s/%s ناموفق بود", platform, chat_id)
            self._note_unreachable(platform, chat_id, exc)
            if looks_unreachable(exc):
                raise BotManagerError("این مشتری ربات رو بلاک کرده یا حسابش بسته شده؛ دیگه نمی‌شه بهش پیام داد.") from exc
            raise BotManagerError("پیام برای مشتری فرستاده نشد؛ اتصال ربات رو چک کن.") from exc
        self._store.add_message(platform, chat_id, "owner", clean)
        if self._handoff.is_open(platform, chat_id):
            self._handoff.touch(platform, chat_id)  # گفتگوی پشتیبانیِ باز: همین پیام جواب حساب می‌شه (بسته‌شدنِ خودکار عقب می‌افته)

    def send_to_customer_sync(self, platform: str, chat_id: str, text: str, timeout: float = 20.0) -> None:
        self._run_in_loop(lambda: self.send_to_customer(platform, chat_id, text), timeout)

    async def broadcast_test(self, content) -> list:
        """ارسالِ آزمایشیِ همان پیام به چتِ مالک (روی هر پلتفرمی که مالک ثبت کرده) — بدونِ ثبت در صفِ ارسال. ``[(platform, ok, detail)]``."""
        content = broadcast_module.validate_content(content, self._settings)
        owner_chats = dict(getattr(self._settings, "owner_chats", {}) or {})
        if not owner_chats:
            raise broadcast_module.BroadcastError("برای پیامِ آزمایشی اول خودت را به‌عنوان مالک به ربات وصل کن (کدِ مالک).")
        lang = shop_texts.resolve_lang(self._settings, "")
        text = broadcast_module.compose(content, self._settings, lang)
        results = []
        for platform, chat_id in owner_chats.items():
            adapter = self._adapters.get(platform)
            if adapter is None:
                results.append((platform, False, "ربات این پلتفرم روشن نیست"))
                continue
            try:
                await adapter.send_strict(str(chat_id), text, photo=content.photo, button=content.button)
                results.append((platform, True, ""))
            except Exception as exc:  # noqa: BLE001
                results.append((platform, False, redact(f"{type(exc).__name__}: {exc}", *self._secrets())[:160]))
        return results

    def broadcast_test_sync(self, content, timeout: float = 30.0) -> list:
        return self._run_in_loop(lambda: self.broadcast_test(content), timeout)

    # ---- عضویتِ اجباریِ کانال (N13) ----

    async def _check_membership(self, platform: str, channel: str, user_id: str) -> str:
        adapter = self._adapters.get(platform)
        if adapter is None:
            raise ConnectionError(f"ربات {platform} وصل نیست")
        return await asyncio.wait_for(adapter.chat_member_status(channel, user_id), timeout=self._membership_timeout)

    async def _on_gate_error(self, channel, exc: BaseException) -> None:
        detail = redact(f"{type(exc).__name__}: {exc}", *self._secrets())[:150]
        platform = self._PLATFORM_FA.get(channel.platform, channel.platform)
        self._attention.add("channel_check", channel.ref, f"{channel.label} ({platform}): {detail}")
        await self._notify_owner_text(
            f"⚠️ بررسیِ عضویتِ کانالِ «{channel.label}» ({platform}) خطا داد؛ تا درست‌شدنش مشتری‌ها بدونِ بررسی رد می‌شن (قفل نمی‌شن).\n"
            f"معمولاً یعنی ربات «ادمینِ کانال» نیست؛ ربات را ادمینِ کانال کن. جزئیات: {detail}"
        )

    async def _on_gate_recovered(self, channel) -> None:
        self._attention.handle_ref("channel_check", channel.ref)

    async def test_channel(self, platform: str, channel: str) -> tuple:
        """«تستِ دسترسی» در تنظیمات: ربات از خودش (شناسه‌ی عددیِ توکن) در کانال می‌پرسه؛ موفق ⇒ ربات ادمینِ کانال است. ``(ok, detail)``."""
        adapter = self._adapters.get(platform)
        if adapter is None:
            return False, "ربات این پلتفرم روشن نیست؛ اول روشنش کن."
        token = self._settings.get_telegram_token() if platform == "telegram" else self._settings.get_bale_token()
        bot_id = str(token or "").split(":", 1)[0]
        if not bot_id.isdigit():
            return False, "توکنِ ربات معتبر نیست."
        try:
            status = await asyncio.wait_for(adapter.chat_member_status(channel, bot_id), timeout=15.0)
        except Exception as exc:  # noqa: BLE001
            return False, redact(f"{type(exc).__name__}: {exc}", *self._secrets())[:160]
        return True, status

    def test_channel_sync(self, platform: str, channel: str, timeout: float = 25.0) -> tuple:
        return self._run_in_loop(lambda: self.test_channel(platform, channel), timeout)

    def _notify_owner_threadsafe(self, text: str) -> None:
        loop, owner = self._loop, self._owner
        if loop is None or owner is None or loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(owner.notify(text), loop)

    @property
    def usage(self):
        return self._usage

    @property
    def discounts(self):
        return self._discounts

    @property
    def finance(self):
        """N19: دفترِ مالی (``None`` در حالتِ مشاوره/بدونِ فروشگاه)."""
        return self._finance

    @property
    def invoices(self):
        """N19: سرویسِ فاکتور (``None`` بدونِ فروشگاه)."""
        return self._invoices

    def send_invoice(self, invoice_id: int) -> str:
        """از ترد UI: «ارسالِ دوباره»ی فاکتور به مشتری (``BotManagerError`` اگه ربات‌ها خاموش باشن). نتیجه: sent|skipped:…|failed:…"""
        return self._run_in_loop(lambda: self._invoices.send_customer(invoice_id, force=True), timeout=90)

    def fee_bp(self) -> dict:
        s = self._settings
        return {"bale_pay": int(getattr(s, "finance_fee_bp_bale_pay", 0) or 0), "zarinpal": int(getattr(s, "finance_fee_bp_zarinpal", 0) or 0)}

    def _on_order_confirmed(self, order) -> None:
        """شنونده‌ی تاییدِ سفارش (هر ترد): دفترِ مالی + (اگه روشن) ارسالِ خودکارِ فاکتور. خطا تایید را خراب نمی‌کنه؛ ``post_missing`` ترمیم می‌کنه."""
        try:
            self._finance.post_order(order, self.fee_bp())
        except Exception:  # noqa: BLE001
            logger.exception("ثبتِ دفترِ مالیِ سفارش %s", order.id)
        self._check_low_stock(order)
        if getattr(self._settings, "invoice_auto_send", "off") == "after_confirm":
            loop = self._loop
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(self._spawn_invoice_run)

    def _check_low_stock(self, order) -> None:
        """A7: بعد از تأییدِ سفارش، محصولِ فیزیکیِ کم‌موجودی ← یک «نیاز به توجه» (تکراری ثبت نمی‌شه)."""
        threshold = int(getattr(self._settings, "low_stock_threshold", 0) or 0)
        if threshold <= 0 or self._product_store is None:
            return
        for item in order.items:
            if item.product_id is None:
                continue
            product = self._product_store.get(item.product_id)
            if product is not None and product.active and not product.unlimited_stock and product.stock_quantity <= threshold:
                self._attention.add("low_stock", str(product.id), f"{product.name}: {product.stock_quantity} عدد مانده")

    def _reconcile_low_stock(self) -> None:
        """هشدارِ موجودیِ کم وقتی محصول دوباره پر شد (یا حذف/غیرفعال شد یا آستانه خاموش شد) خودکار بسته می‌شه."""
        threshold = int(getattr(self._settings, "low_stock_threshold", 0) or 0)
        for item in self._attention.list_open(200):
            if item.type != "low_stock":
                continue
            product = self._product_store.get(int(item.ref)) if self._product_store is not None and item.ref.isdigit() else None
            if threshold <= 0 or product is None or not product.active or product.unlimited_stock or product.stock_quantity > threshold:
                self._attention.handle_ref("low_stock", item.ref)

    def _spawn_invoice_run(self) -> None:
        task = asyncio.ensure_future(self._invoices.process_pending())
        self._invoice_tasks.add(task)
        task.add_done_callback(self._invoice_tasks.discard)

    async def _send_invoice_doc(self, platform: str, chat_id: str, path: str, caption: str) -> None:
        adapter = self._adapters.get(platform)
        if adapter is None:
            raise RuntimeError(f"ربات {platform} وصل نیست")
        await adapter.send_document_strict(str(chat_id), path, caption)

    async def _send_plain_text(self, platform: str, chat_id: str, text: str) -> None:
        adapter = self._adapters.get(platform)
        if adapter is None:
            raise RuntimeError(f"ربات {platform} وصل نیست")
        await adapter.send_message(str(chat_id), text)

    def _invoice_can_send(self, platform: str, chat_id: str) -> str:
        """هرگز به مشتریِ بلاک‌شده یا دسترس‌ناپذیر (دلیلِ ممنوعیت یا ``""``)."""
        if self._store.is_blocked(platform, str(chat_id)):
            return "blocked"
        customer = self._customers.get(platform, str(chat_id))
        if customer is not None and customer.unreachable:
            return "unreachable"
        return ""

    def invoice_visible(self) -> bool:
        s = self._settings
        return bool(getattr(s, "invoice_seller_name", "")) or getattr(s, "invoice_auto_send", "off") != "off"

    @property
    def campaigns(self):
        return self._campaigns

    @property
    def broadcasts(self):
        return self._broadcasts

    @property
    def channel_gate(self):
        return self._gate

    def _note_unreachable(self, platform: str, chat_id: str, exc: BaseException) -> None:
        """فقط وقتی پلتفرم صریحاً می‌گه مشتری ربات را بلاک کرده/حسابش بسته شده، «دسترس‌ناپذیر» ثبت می‌شه (نه خطای اینترنت)."""
        if looks_unreachable(exc):
            try:
                self._customers.mark_unreachable(platform, str(chat_id))
            except Exception:  # noqa: BLE001
                logger.debug("ثبتِ دسترس‌ناپذیریِ مشتری ناموفق بود", exc_info=True)

    def _persist_settings(self) -> None:
        from app.core import settings as settings_module

        settings_module.save_settings(self._settings)

    async def send_message(self, platform: str, chat_id: str, text: str) -> None:
        """ارسال پیام به یه چتِ مشخص روی آداپتورِ *همون* پلتفرم (مثلاً تاییدیه‌ی
        سفارش بعد از تاییدِ دستیِ صاحب فروشگاه). باید روی event loopِ خودِ ربات‌ها
        اجرا بشه — از UI از ``send_message_sync`` استفاده کن. بعد از موفقیت،
        پیام توی تاریخچه هم ثبت می‌شه تا توی تب «گفتگوها» دیده بشه. اگه آداپتور
        وصل نباشه یا ارسال خطا بده، ``BotManagerError`` (فارسی) می‌ده."""
        adapter = self._adapters.get(platform)
        if adapter is None:
            raise BotManagerError(
                "ربات این پلتفرم الان روشن/وصل نیست؛ اول ربات رو روشن کن، بعد دوباره امتحان کن."
            )
        try:
            await adapter.send_message(chat_id, text)
        except Exception as exc:  # noqa: BLE001
            logger.exception("ارسال پیام به %s/%s ناموفق بود", platform, chat_id)
            self._note_unreachable(platform, chat_id, exc)
            raise BotManagerError("پیام برای مشتری فرستاده نشد؛ اتصال ربات رو چک کن.") from exc
        self._store.add_message(platform, chat_id, "assistant", text)

    def send_message_sync(self, platform: str, chat_id: str, text: str, timeout: float = 20.0) -> None:
        """نسخه‌ی blocking برای صدازدن از ترد UI/``page.run_thread``: کار رو به
        loopِ ربات‌ها می‌سپره و منتظر نتیجه می‌مونه."""
        with self._lock:
            loop = self._loop
            alive = self.is_running()
        if not alive or loop is None:
            raise BotManagerError("ربات‌ها خاموشن؛ اول از صفحه‌ی «ربات‌ها» روشنشون کن.")
        future = asyncio.run_coroutine_threadsafe(self.send_message(platform, chat_id, text), loop)
        try:
            future.result(timeout=timeout)
        except BotManagerError:
            raise
        except Exception as exc:  # noqa: BLE001 — timeout و غیره
            future.cancel()
            raise BotManagerError("پیام برای مشتری فرستاده نشد؛ اتصال ربات رو چک کن.") from exc

    # ---- دسترسی‌ها ----
    @property
    def store(self) -> ConversationStore:
        return self._store

    @property
    def customers(self) -> CustomerStore:
        return self._customers

    @property
    def admins(self) -> AdminStore:
        return self._admins

    def set_settings(self, settings) -> None:
        """برای وقتی که شیء تنظیمات عوض شده (مثلاً session جدید توی حالت وب)."""
        with self._lock:
            self._settings = settings
            if self._payments is not None:
                self._payments.set_settings(settings)
            if self._pipeline is not None:
                self._pipeline._settings = settings  # noqa: SLF001 — همون شیء زنده

    def enabled_platforms(self) -> list:
        s = self._settings
        platforms = []
        if s.telegram_enabled and s.get_telegram_token():
            platforms.append("telegram")
        if s.bale_enabled and s.get_bale_token():
            platforms.append("bale")
        return platforms

    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def started_platforms(self) -> list:
        """پلتفرم‌هایی که توی «روشن‌شدنِ» فعلیِ ربات‌ها واقعاً آداپتورشون ساخته
        شده (خالی وقتی خاموشه). فرقش با ``enabled_platforms``: اون از روی
        تنظیمات فعلیه؛ این از روی چیزیه که الان توی حافظه در حال اجراست — مثلاً
        اگه کاربر بعد از روشن‌شدن، ربات بله رو فعال کنه، اولی «bale» داره
        ولی دومی نه تا ری‌استارت."""
        with self._lock:
            if not self.is_running():
                return []
            return list(self._adapters.keys())

    def get_status(self) -> ManagerStatus:
        with self._lock:
            platforms = {name: AdapterStatus() for name in PLATFORMS}
            for name, adapter in self._adapters.items():
                platforms[name] = adapter.status
            return ManagerStatus(running=self.is_running(), platforms=platforms)

    # ---- چرخه‌ی حیات ----
    def start(self) -> None:
        with self._lock:
            if self.is_running():
                return
            platforms = self.enabled_platforms()
            if not platforms:
                raise BotManagerError("اول توکن حداقل یکی از ربات‌ها (تلگرام یا بله) رو وارد و فعالش کن.")

            configure_logging(
                [
                    self._settings.get_telegram_token(),
                    self._settings.get_bale_token(),
                    *proxy_secrets(self._settings.combined_telegram_proxy_text()),
                    *proxy_secrets(self._settings.get_telegram_proxy_sub_url()),
                    self._settings.get_bale_pay_provider_token(),
                    self._settings.get_zarinpal_merchant_id(),
                ],
                self._log_dir,
            )
            self._ready.clear()
            self._start_error = None
            self._adapters = {}
            self._tasks = {}
            thread = threading.Thread(
                target=self._thread_main, args=(platforms,), name="smart-business-bots", daemon=True
            )
            self._thread = thread
            thread.start()

        self._ready.wait(timeout=10)
        if self._start_error:
            raise BotManagerError(self._start_error)

    def stop(self, timeout: float = 15.0) -> bool:
        """True یعنی ترد ربات کاملاً متوقف شد."""
        with self._lock:
            thread, loop = self._thread, self._loop
        if thread is None or not thread.is_alive():
            return True
        if loop is not None:
            try:
                asyncio.run_coroutine_threadsafe(self._stop_all(), loop).result(timeout=timeout)
            except Exception:  # noqa: BLE001 — زمان‌بر شدن توقف نباید UI رو خراب کنه
                logger.warning("توقف ربات‌ها بیشتر از حد انتظار طول کشید")
        thread.join(timeout=timeout)
        return not thread.is_alive()

    def restart(self, timeout: float = 15.0) -> None:
        if not self.stop(timeout=timeout):
            raise BotManagerError("ربات هنوز در حال توقفه؛ چند ثانیه‌ی دیگه دوباره امتحان کن.")
        self.start()

    # ---- داخل ترد ربات ----
    def _thread_main(self, platforms: list) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._run_all(platforms))
        except Exception as exc:  # noqa: BLE001
            logger.exception("ترد ربات‌ها با خطا متوقف شد")
            self._start_error = self._start_error or redact(f"خطای غیرمنتظره در راه‌اندازی ربات: {exc}")
        finally:
            self._ready.set()  # اگه هنوز کسی منتظره، رهاش کن
            try:
                pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:  # noqa: BLE001
                logger.exception("پاکسازی event loop ربات‌ها ناموفق بود")
            finally:
                loop.close()
                self._loop = None

    # ---- چیزهایی که فقط مدیر می‌دونه (به PaymentService/ایجنت داده می‌شه)
    def _bale_client(self):
        """کلاینتِ زنده‌ی بله (None اگه ربات بله وصل نیست). لینک/فاکتور بله‌پی همیشه
        از طریق همین ساخته می‌شه — حتی برای مشتریِ تلگرامی."""
        bale = self._adapters.get("bale")
        return getattr(bale, "client", None) if bale is not None else None

    def _bot_username(self, platform: str) -> Optional[str]:
        adapter = self._adapters.get(platform)
        return adapter.status.username if adapter is not None else None

    def payment_hooks(self) -> PaymentHooks:
        hooks = PaymentHooks(bale_client=self._bale_client, bot_username=self._bot_username)
        if self._owner is not None:
            hooks.notify_owner = self._owner.notify
        return hooks

    async def _run_all(self, platforms: list) -> None:
        store_agent = shop_flow = qa_agent = None
        if self._payments is not None:
            hooks = self.payment_hooks()
            store_agent = StoreAgent(self._product_store, self._order_store, self._payments, hooks)
            shop_flow = ShopFlow(lambda: self._settings, self._product_store, self._order_store, self._payments, hooks)
            shop_flow.attention = self._attention
            if self._invoices is not None:
                shop_flow.invoice_handler = self._invoices.send_for_customer_button
                shop_flow.invoice_visible = self.invoice_visible
            shop_flow.support_handler = self._handoff.flow_handler
            shop_flow.support_end_handler = self._handoff.end_handler
            qa_agent = QaAgent(self._product_store, self._order_store, shop_flow)
        pipeline_kwargs = dict(self._pipeline_kwargs)
        pipeline_kwargs["store_agent"] = store_agent
        pipeline_kwargs["shop_flow"] = shop_flow
        pipeline_kwargs["handoff"] = self._handoff
        pipeline_kwargs["limits"] = self._limits
        pipeline_kwargs["qa_agent"] = qa_agent
        pipeline_kwargs["owner_console"] = self._owner
        pipeline_kwargs["admin_panel"] = self._admin_panel
        pipeline_kwargs["channel_gate"] = self._gate
        pipeline_kwargs["admins"] = self._admins
        pipeline = ConversationPipeline(self._settings, store=self._store, customers=self._customers, **pipeline_kwargs)
        self._pipeline = pipeline
        adapters = {name: self._factories[name](self._settings, pipeline) for name in platforms}
        self._adapters = adapters
        self._tasks = {
            name: asyncio.create_task(self._guarded(name, adapter), name=f"bot-{name}")
            for name, adapter in adapters.items()
        }
        maintenance = (
            asyncio.create_task(self._maintenance_loop(), name="orders-maintenance") if self._payments is not None else None
        )
        profile_task = asyncio.create_task(self._profile_loop(), name="bot-profile")  # N17: برای مشاور هم لازم است
        broadcast_task = asyncio.create_task(self._broadcast_engine.run_forever(), name="broadcast")  # N7: ارسالِ صفِ پایدار
        self._ready.set()
        try:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        finally:
            if maintenance is not None:
                maintenance.cancel()
                await asyncio.gather(maintenance, return_exceptions=True)
            profile_task.cancel()
            broadcast_task.cancel()
            await asyncio.gather(profile_task, broadcast_task, return_exceptions=True)
            await pipeline.shutdown()

    # ---- بیوگرافیِ ربات: نشانِ کوچکِ سازنده (N17) ----
    def _secrets(self) -> list:
        return [self._settings.get_telegram_token(), self._settings.get_bale_token()]

    async def _sync_profile_for(self, platform: str, adapter) -> Optional[bot_profile.SyncReport]:
        """``None`` = هنوز وصل نشده (دورِ بعد دوباره). هرگز exception نمی‌ده."""
        settings = self._settings
        if platform == "bale" and getattr(settings, "bale_bio_supported", None) is False:
            report = bot_profile.SyncReport(bot_profile.STATUS_UNSUPPORTED, platform)
            self._profile_reports[platform] = report
            return report
        maker = getattr(adapter, "profile_client", None)
        client = maker() if callable(maker) else None
        if client is None:
            return None
        languages = bot_profile.DEFAULT_LANGS if platform == "telegram" else ("",)
        lang = getattr(settings, "bot_language", "fa")
        report = await bot_profile.sync_profile(
            client,
            seller_text=getattr(settings, "bot_bio_text", ""),
            confirmed=bool(getattr(settings, "bot_bio_confirmed", False)),
            default_lang=lang if lang in ("fa", "en") else "fa",
            languages=languages,
            platform=platform,
        )
        report.detail = redact(report.detail, *self._secrets())
        changed = False
        if report.adopted_text and not (getattr(settings, "bot_bio_text", "") or "").strip():
            settings.bot_bio_text = report.adopted_text
            changed = True
        if platform == "bale":
            if report.status == bot_profile.STATUS_UNSUPPORTED:
                settings.bale_bio_supported, changed = False, True
            elif report.status in (bot_profile.STATUS_OK, bot_profile.STATUS_UPDATED) and getattr(settings, "bale_bio_supported", None) is None:
                settings.bale_bio_supported, changed = True, True
        if changed:
            try:
                self._persist_settings()
            except Exception:  # noqa: BLE001
                logger.warning("ذخیره‌ی تنظیماتِ بیوگرافی ناموفق بود", exc_info=True)
        if report.status == bot_profile.STATUS_NEEDS_CONFIRM:
            self._attention.add("bio_confirm", platform, "بیوگرافیِ فعلیِ ربات منتظرِ تأییدِ شماست")
        elif report.status == bot_profile.STATUS_TOO_LONG:
            self._attention.add("bio_too_long", platform, f"بیوگرافی {report.over} کاراکتر بیشتر از سقفه")
        self._profile_reports[platform] = report
        return report

    async def _sync_all_profiles(self) -> dict:
        loop = asyncio.get_running_loop()
        out: dict = {}
        for platform, adapter in list(self._adapters.items()):
            report = await self._sync_profile_for(platform, adapter)
            if report is None:
                continue
            out[platform] = report
            retry = report.status in (bot_profile.STATUS_FLOOD, bot_profile.STATUS_ERROR)
            self._profile_due[platform] = loop.time() + (self._profile_retry if retry else self._profile_interval)
        return out

    async def _profile_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            try:
                for platform, adapter in list(self._adapters.items()):
                    if loop.time() < self._profile_due.get(platform, 0.0):
                        continue
                    report = await self._sync_profile_for(platform, adapter)
                    if report is None:
                        continue
                    retry = report.status in (bot_profile.STATUS_FLOOD, bot_profile.STATUS_ERROR)
                    self._profile_due[platform] = loop.time() + (self._profile_retry if retry else self._profile_interval)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — خطا در نشانِ بیوگرافی هرگز ربات را نمی‌کُشد
                logger.exception("خطا در همگام‌سازیِ بیوگرافیِ ربات")
            await asyncio.sleep(self._profile_poll)

    def sync_profiles_now(self, timeout: float = 40.0) -> dict:
        """از ترد UI (بعد از «ذخیره» یا تأییدِ فروشنده): همین الان همگام می‌کنه و ``{platform: SyncReport}`` برمی‌گردونه.
        ربات‌ها خاموش باشن ⇒ ``BotManagerError`` (متن ذخیره شده و بعد از روشن‌شدن خودکار اعمال می‌شه)."""
        with self._lock:
            loop = self._loop
            alive = self.is_running()
        if not alive or loop is None:
            raise BotManagerError("ربات‌ها خاموشن؛ بیوگرافی بعد از روشن‌شدنِ ربات خودکار اعمال می‌شه.")
        future = asyncio.run_coroutine_threadsafe(self._sync_all_profiles(), loop)
        try:
            return future.result(timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            future.cancel()
            raise BotManagerError("همگام‌سازیِ بیوگرافی بیشتر از حد انتظار طول کشید.") from exc

    def reset_bale_bio_probe(self) -> None:
        """«امتحانِ دوباره‌ی بله»: برچسبِ «پشتیبانی‌نشده» پاک می‌شه تا بررسیِ بعدی دوباره امتحان کنه."""
        self._settings.bale_bio_supported = None
        self._profile_due.pop("bale", None)
        self._profile_reports.pop("bale", None)
        try:
            self._persist_settings()
        except Exception:  # noqa: BLE001
            logger.warning("ذخیره‌ی تنظیماتِ بیوگرافی ناموفق بود", exc_info=True)

    def profile_reports(self) -> dict:
        return dict(self._profile_reports)

    # ---- جاروکننده: انقضای رزرو + استعلام زرین‌پال
    async def _maintenance_loop(self) -> None:
        last_poll = 0.0
        last_recover = -1e9
        last_retention = -1e9
        loop = asyncio.get_running_loop()
        while True:
            try:
                if loop.time() - last_recover >= self._recover_interval:
                    last_recover = loop.time()
                    await self._recover_inventory()
                await self._retry_deliveries()
                await self._refresh_proxy_subscription()
                await self._expire_handoffs()
                if loop.time() - last_retention >= RETENTION_INTERVAL_SECONDS:
                    last_retention = loop.time()
                    await self._apply_retention()
                    await asyncio.to_thread(self._usage.prune)  # N1: خامِ بیش از ۹۰ روز ← جمع‌بندیِ روزانه
                await self._expire_orders()
                await self._tick_campaigns()
                await self._tick_finance()
                if loop.time() - last_poll >= self._zarinpal_poll_interval:
                    last_poll = loop.time()
                    await self._poll_zarinpal()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — یه خطا نباید جاروکننده رو برای همیشه بکشه
                logger.exception("خطا در جاروکننده‌ی سفارش‌ها")
            await asyncio.sleep(self._maintenance_interval)

    async def _recover_inventory(self) -> None:
        """saga موجودی (R10-۱): سفارش‌های تاییدشده‌ای که وسطِ راه قطع شدن رو کامل می‌کنه. اگه موجودی دیگه کافی
        نبود، سفارش به «پرداخت‌شده» برمی‌گرده و مالک خبردار می‌شه تا تصمیم بگیره."""
        results = await asyncio.to_thread(self._order_store.recover_inventory, RECOVER_MIN_AGE_SECONDS)
        for order_id, outcome, detail in results:
            logger.info("بازیابیِ موجودیِ سفارش #%s: %s", order_id, outcome)
            if outcome == "insufficient":
                self._attention.add("inventory_short", str(order_id), detail)
            if outcome == "insufficient" and self._owner is not None:
                await self._owner.notify(
                    f"⚠️ سفارش #{order_id} تایید شده بود ولی اعمالِ موجودی نیمه‌کاره موند و حالا موجودی کافی نیست "
                    f"({detail}). سفارش به «پرداخت‌شده» برگشت؛ دوباره بررسی کن."
                )

    async def _expire_orders(self) -> None:
        now = time.time()
        for order in self._order_store.expire_stale(now=now):
            # اگه برنامه ساعت‌ها خاموش بوده، پیامِ «مهلتت تموم شد» برای سفارشی که خیلی وقت پیش
            # منقضی شده فقط گیج‌کننده‌ست؛ بی‌صدا منقضی می‌شه.
            if order.expires_ts and now - order.expires_ts > STALE_EXPIRY_NOTICE_SECONDS:
                continue
            text = shop_texts.t("order.expired", order_id=order.id)
            if order.payment_method == METHOD_CARD_TO_CARD:
                text += "\n" + shop_texts.t("order.expired_card_hint")
            await self._notify_customer(order.platform, order.chat_id, text, order.id)

    async def _tick_finance(self) -> None:
        """N19: ترمیمِ دفترِ مالیِ جاافتاده + صدور/ارسالِ فاکتورِ عقب‌افتاده (idempotent)."""
        if self._finance is None:
            return
        await asyncio.to_thread(self._finance.post_missing, self.fee_bp())
        await asyncio.to_thread(self._reconcile_low_stock)
        await self._invoices.process_pending()

    async def _tick_campaigns(self) -> None:
        if self._campaigns is None:
            return
        for cid, status in await asyncio.to_thread(self._campaigns.tick):
            logger.info("کمپین #%s ← %s", cid, status)
            if status == "failed" and self._owner is not None:
                camp = self._campaigns.get(cid)
                await self._owner.notify(f"⚠️ کمپینِ «{camp.name if camp else cid}» شروع نشد: {camp.error if camp else ''}")
        await asyncio.to_thread(self._discounts.purge_old)

    async def _poll_zarinpal(self) -> None:
        for order in await self._payments.check_zarinpal_orders():
            await self._notify_payment_confirmed(order)

    async def _notify_customer(self, platform: str, chat_id: str, text: str, order_id: int) -> bool:
        return await self._deliver(platform, chat_id, text, True)

    # ---- کنسولِ مالک (برای UI)
    @property
    def owner_console(self):
        return self._owner

    def payment_last_errors(self) -> dict:
        """آخرین خطای هر روش پرداخت (از چتِ واقعیِ مشتری‌ها) — برای نمایش توی UI، تا صاحب
        فروشگاه بدونه مثلاً لینک بله‌پی دارد شکست می‌خوره."""
        return dict(self._payments.last_errors) if self._payments is not None else {}

    # ---- تشخیص (برای دکمه‌های «تست اتصال» توی UI)
    def diagnose_payment_sync(self, method: str, timeout: float = 30.0) -> tuple:
        """(ok, پیام) — نتیجه‌ی یه تماسِ آزمایشیِ واقعی با بله‌پی/زرین‌پال. بله‌پی باید روی
        loopِ ربات‌ها اجرا بشه (کلاینت بله اونجا ساخته شده)؛ زرین‌پال مستقله."""
        if self._payments is None:
            return False, "این قابلیت فقط توی حالت فروشگاه فعاله."
        from app.core.orders import METHOD_BALE_PAY, METHOD_ZARINPAL

        if method == METHOD_ZARINPAL:
            return asyncio.run(self._payments.diagnose_zarinpal(self.payment_hooks()))
        if method == METHOD_BALE_PAY:
            with self._lock:
                loop, alive = self._loop, self.is_running()
            if not alive or loop is None:
                return False, "ربات‌ها خاموشن؛ اول از صفحه‌ی «ربات‌ها» روشنشون کن (بله‌پی از طریق ربات بله تست می‌شه)."
            future = asyncio.run_coroutine_threadsafe(self._payments.diagnose_bale_pay(self.payment_hooks()), loop)
            try:
                return future.result(timeout=timeout)
            except Exception as exc:  # noqa: BLE001
                future.cancel()
                return False, f"تست بله‌پی تموم نشد: {exc}"
        return False, "روش نامعتبر."

    async def _guarded(self, name: str, adapter) -> None:
        try:
            await adapter.run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — یه باگ توی یه آداپتور نباید اون یکی رو بترکونه
            logger.exception("آداپتور %s با خطای غیرمنتظره متوقف شد", name)
            secrets = [self._settings.get_telegram_token(), self._settings.get_bale_token()]
            adapter.status = AdapterStatus(
                state=STATE_ERROR,
                error=redact(f"خطای غیرمنتظره: {exc}", *secrets),
                error_code=ERR_UNEXPECTED,
            )

    async def _stop_all(self) -> None:
        for name, adapter in list(self._adapters.items()):
            try:
                await asyncio.wait_for(adapter.stop(), timeout=5)
            except Exception:  # noqa: BLE001
                logger.warning("درخواست توقف آداپتور %s ارسال نشد", name)
        # صبر می‌کنیم run() هر آداپتور خودش تمیز تموم بشه (بستن session و ...)
        pending_tasks = [t for t in self._tasks.values() if not t.done()]
        if pending_tasks:
            _, still_running = await asyncio.wait(pending_tasks, timeout=10)
            for task in still_running:
                logger.warning("توقف کامل نشد؛ لغو اجباری %s", task.get_name())
                task.cancel()


# --------------------------------------------------------- نمونه‌ی سراسری ---

_manager: Optional[BotManager] = None
_manager_lock = threading.Lock()


def get_manager(settings, product_store: Optional[ProductStore] = None, order_store: Optional[OrderStore] = None) -> BotManager:
    """یه نمونه‌ی مشترک برای کل پروسه — تا توی حالت وب (چند تب) هم‌زمان دو
    poller برای یه توکن راه نیفته و تلگرام خطای Conflict نده. ``product_store``/
    ``order_store`` فقط لازمن اگه کاربر حالت فروشگاهی داشته باشه؛ برای حالت
    مشاوره، None بمونن کافیه (جریان خرید/پرداخت غیرفعال می‌مونه)."""
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = BotManager(settings, product_store=product_store, order_store=order_store)
        else:
            _manager.set_settings(settings)
        return _manager
