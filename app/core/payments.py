"""
منطقِ پرداخت — دو روش، هر دو با پولِ خودِ فروشنده:

* **کارت‌به‌کارت**: شماره کارت و مبلغ دقیق به مشتری نشان داده می‌شه و **همان‌جا فقط یک چیز**
  از او خواسته می‌شه: بعد از واریز، رسید را (متن یا عکس) بفرستد. (اگر مالک دریافتِ رسید را
  خاموش کرده باشد، همان‌جا می‌نویسد «پرداخت کردم».) برنامه مبلغ/کدِ رهگیری را از متنِ رسید
  می‌خواند، با مبلغِ سفارش مقایسه می‌کند و **فوری** به مالک و مدیرها هشدار می‌دهد.
  تأییدِ نهایی همیشه دستی است — پول در حسابِ خودِ فروشنده است و هیچ درگاهی نبود که
  از آن استعلام بگیری.
* **بله‌پی**: صورتحساب در درگاهِ بله ساخته می‌شه. مسیرِ اصلی ``createInvoiceLink`` است:
  یک لینک که مشتریِ تلگرامی با یک کلیک مستقیم داخلِ اپِ بله پرداخت می‌کند (نیازی به
  chat_id ندارد). اگر بله لینک نداد، همان فاکتور با دیپ‌لینکِ رباتِ پرداخت ساخته می‌شه.
  تأییدِ پرداخت خودکار است، ولی فقط بعد از اینکه مبلغ، ارز، کدِ سفارش و استعلامِ
  تراکنش (`inquireTransaction`) دقیقاً بخواند.

واحدِ پول همه‌جا ریالِ صحیح (int) است. هیچ مبلغی از مشتری خوانده نمی‌شه؛ همیشه از خودِ
سفارش در دیتابیس گرفته می‌شه (ناوردا ۱ و ۴).
"""

from __future__ import annotations

import hmac
import logging
import math
import secrets
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from app.core.bale_pay import (
    BaleApiError,
    BalePayClient,
    BalePreCheckoutQuery,
    BaleSuccessfulPayment,
    is_test_provider_token,
)
from app.core.orders import (
    METHOD_BALE_PAY,
    METHOD_CARD_TO_CARD,
    STATUS_CONFIRMED,
    STATUS_EXPIRED,
    STATUS_PAID,
    STATUS_PENDING_PAYMENT,
    Order,
    OrderError,
    OrderStore,
    build_order_confirmed_text,
    build_order_summary_text,
)
from app.core.products import ProductStore
from app.core.receipts import parse_receipt
from app.core.shop_texts import t

logger = logging.getLogger(__name__)

_PAYLOAD_PREFIX = "order:"
_SUCCESSFUL_STATUSES = {"successful", "success", "paid", "completed", "done", "approved", "settled"}
_PENDING_STATUSES = {"pending", "in_process", "processing", "created", "new", ""}

# چندِ بایتِ آخرِ payload = کدِ یکتای هر دستورِ پرداخت (جلوگیری از حدس‌زدنِ سفارشِ دیگری)


def order_payload(order_id: int, code: str = "") -> str:
    return f"{_PAYLOAD_PREFIX}{order_id}" + (f":{code}" if code else "")


def parse_payload(payload: str) -> tuple:
    """``(order_id, code)`` — ``code`` ممکن است خالی باشد (سفارش‌های قدیمی)."""
    if not payload or not payload.startswith(_PAYLOAD_PREFIX):
        return None, ""
    tail = payload[len(_PAYLOAD_PREFIX) :]
    parts = tail.split(":", 1)
    try:
        order_id = int(parts[0])
    except ValueError:
        return None, ""
    return order_id, parts[1] if len(parts) > 1 else ""


def make_pay_code() -> str:
    return secrets.token_hex(6)  # ۱۲ کاراکترِ hex — حدس‌زدنش عملی نیست


def bale_pay_deep_link(username: str, order_id: int, code: str) -> str:
    return f"https://ble.ir/{username}?start=pay_{order_id}_{code}"


def looks_like_payment_url(link: str) -> bool:
    return link.startswith("https://") or link.startswith("http://")


_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_provider_token(raw: str) -> str:
    """شماره کارتِ ۱۶ رقمی (با ارقام فارسی/عربی، فاصله یا خط‌تیره) → ۱۶ رقمِ لاتینِ
    پشت‌سرهم؛ هر چیز دیگه (مثل توکنِ کیف‌پولِ آزمایشی) فقط trim می‌شه."""
    text = (raw or "").translate(_DIGIT_MAP).strip()
    stripped = "".join(ch for ch in text if ch not in " -_\u200c\u200f\u200e")
    if stripped.isdigit() and len(stripped) == 16:
        return stripped
    return text


def describe_provider_token(token: str) -> str:
    normalized = normalize_provider_token(token)
    if normalized.isdigit() and len(normalized) == 16:
        return "شماره کارتِ ۱۶ رقمی"
    if normalized.upper().startswith("WALLET-"):
        return "توکنِ آزمایشیِ کیف‌پولِ بله (پولی کم نمی‌شه)"
    return "توکنِ کیف‌پولِ بله"


def build_payment_received_text(order: Order) -> str:
    text = t("pay.received") + "\n\n" + build_order_summary_text(order)
    text += "\n\n" + (t("pay.received_late") if order.paid_late else t("pay.received_pending"))
    return text


def build_payment_notification_text(order: Order) -> str:
    """پیامِ خودکارِ بعد از پرداختِ آنلاین: اگر سفارش هم‌زمان تأیید شده (تأییدِ خودکار)
    فاکتورِ نهایی، وگرنه «پرداخت دریافت شد، منتظر تأییدِ فروشنده»."""
    if order.status == STATUS_CONFIRMED:
        return t("pay.received") + "\n\n" + build_order_confirmed_text(order)
    return build_payment_received_text(order)


METHOD_LABELS = {METHOD_CARD_TO_CARD: "کارت‌به‌کارت", METHOD_BALE_PAY: "بله‌پی"}


class PaymentError(Exception):
    """خطای قابل‌نمایش (فارسی) در ساختنِ دستورِ پرداخت."""


@dataclass
class PaymentInstruction:
    method: str
    text: str
    buttons: list = field(default_factory=list)  # [(برچسب, url)]
    url: str = ""
    receipt_requested: bool = False  # مشتری باید بعد از واریز، رسید بفرستد


async def _no_attachment(*_args) -> str:
    """جایِ خالیِ هوکِ دانلودِ پیوست (وقتی آداپتورِ تلگرام وصل نیست)."""
    return ""


@dataclass
class PaymentHooks:
    """چیزهایی که فقط BotManager می‌دونه (کلاینتِ زندهٔ پرداختِ بله، یوزرنیم، اعلان به مالک)."""

    bale_client: Callable[[], Optional[BalePayClient]] = lambda: None
    notify_owner: Callable[[str], Awaitable[bool]] = lambda text: _false_future()
    # رسید/ادعایِ پرداختِ کارت‌به‌کارت ⇒ آلارمِ فوری (attention + پیام به مالک/مدیرها)
    payment_claim: Callable[[Order, dict], None] = lambda order, receipt: None
    # دانلودِ عکس/فایلِ فرستاده‌شده توسط مشتری و ذخیره‌اش در پوشهٔ داده → مسیرِ محلی (یا "").
    # async است: فراخوانیِ هم‌زمانِ دانلود از داخلِ loopِ ربات، همان loop را قفل می‌کرد.
    attachment_saver: Callable[..., Awaitable[str]] = _no_attachment


async def _false_future() -> bool:
    return False


PAY_CODE_MAX_ATTEMPTS_PER_CHAT = 6  # حدسِ کدِ ۱۲ رقمی از ۱۶ نمایش، آن‌قدرها که ممکن نیست
PAY_CODE_WINDOW_SECONDS = 900  # بعد از ۱۵ دقیقه شمارشِ حدسِ هر چت صفر می‌شه
_MEMORY_CAP = 512  # سقفِ دیک‌هایِ حافظه‌یِ سرویس (ربات هفته‌ها روشن می‌ماند)


def reservation_active(order: Order, now: Optional[float] = None) -> bool:
    if order.status != STATUS_PENDING_PAYMENT:
        return False
    return order.expires_ts == 0 or order.expires_ts > (time.time() if now is None else now)


def _left_text(order: Order) -> str:
    seconds = order.seconds_left()
    if not seconds:
        return ""
    return t("pay.left", minutes=max(1, math.ceil(seconds / 60)))


def invoice_prices(order: Order) -> list:
    """ردیف‌هایِ فاکتورِ درگاه. جمعِ آن‌ها باید دقیقاً مبلغِ نهاییِ سفارش باشد، پس وقتی
    تخفیف اعمال شده یک ردیفِ واحد می‌سازیم (ردیفِ منفی ممکن است رد شود)."""
    if order.discount_irr > 0 or not order.items:
        return [(f"سفارش #{order.id}"[:32], order.total_irr)]
    return [(item.product_name[:32] or "کالا", item.subtotal_irr) for item in order.items]


def invoice_description(order: Order) -> str:
    return "، ".join(f"{i.product_name} ×{i.quantity}" for i in order.items)[:255] or f"سفارش #{order.id}"


class PaymentService:
    def __init__(self, order_store: OrderStore, product_store: ProductStore, settings=None):
        self._orders = order_store
        self._products = product_store
        self._settings = settings
        self.last_errors: dict = {}  # روش -> آخرین پیام خطا (برایِ دکمهٔ «تست» در UI)
        self._pending_verify: dict = {}  # سفارش -> (شناسهٔ تراکنش، اولین‌بار) برایِ استعلامِ معوق
        self._pay_attempts: dict = {}  # شناسهٔ چتِ بله -> (تعدادِ کدِ اشتباه، زمانِ شروعِ پنجره)
        self._expected_payer: dict = {}  # سفارش -> شناسهٔ کاربری که pre_checkout را زد

    def set_settings(self, settings) -> None:
        self._settings = settings

    # ------------------------------------------------------------ روش‌های فعال

    def available_methods(self, bale_running: bool = False) -> list:
        """روش‌هایی که *همین الان* واقعاً قابل‌ارائه‌ان. بله‌پی بدونِ توکن‌ها و بدونِ اتصالِ
        رباتِ پرداخت کار نمی‌کند."""
        s = self._settings
        if s is None:
            return []
        methods = []
        if s.card_to_card_number:
            methods.append(METHOD_CARD_TO_CARD)
        if s.bale_pay_configured() and bale_running:
            methods.append(METHOD_BALE_PAY)
        return methods

    # ---------------------------------------------------------- دستورِ پرداخت

    def _after_pay_sentence(self) -> str:
        auto = bool(self._settings and self._settings.auto_confirm_gateway_payments)
        return t("pay.after_auto") if auto else t("pay.after_manual")

    def _card_instruction(self, order: Order) -> PaymentInstruction:
        """پیامِ حداقلیِ کارت‌به‌کارت (F4): شماره کارت و مبلغ، **یک** جمله «رسید را بفرست»
        و مهلتِ رزرو.

        هیچ دستورِ دومی («بنویس پرداخت کردم») و هیچ پاراگرافِ شرطیِ بلند نبود؛ وقتی دریافتِ
        رسید روشن است، تنها خواسته‌ی برنامه فرستادنِ رسید است. اگر مالک رسید را خاموش کرده
        باشد، همان سطرِ قدیمیِ «پرداخت کردم بنویس» می‌ماند. هر سطر از ``shop_texts``/``t``
        می‌آید تا مالک بتواند متنش را در «متن‌های ربات» عوض کند."""
        s = self._settings
        self._orders.set_payment_info(order.id, METHOD_CARD_TO_CARD)
        want_receipt = bool(getattr(s, "receipt_check_enabled", True))
        lines = [
            t("pay.card.title", order_id=order.id),
            t("pay.amount", amount=f"{order.total_irr:,}"),
            t("pay.card.number", number=s.card_to_card_number),
        ]
        if s.card_to_card_holder_name:
            lines.append(t("pay.card.holder", holder=s.card_to_card_holder_name))
        lines.append(t("pay.card.receipt.ask" if want_receipt else "pay.card.after"))
        left = _left_text(order)
        if left:
            lines.append(left)
        return PaymentInstruction(METHOD_CARD_TO_CARD, "\n".join(lines), receipt_requested=want_receipt)

    async def build_instruction(self, order: Order, method: str, hooks: PaymentHooks) -> PaymentInstruction:
        s = self._settings
        if s is None:
            raise PaymentError("پرداخت هنوز تنظیم نشده.")
        if method == METHOD_CARD_TO_CARD:
            if not s.card_to_card_number:
                raise PaymentError("کارت‌به‌کارت فعال نیست.")
            return self._card_instruction(order)

        if method == METHOD_BALE_PAY:
            if not s.bale_pay_configured():
                raise PaymentError("بله‌پی فعال نیست (توکنِ رباتِ پرداخت و توکنِ درگاه لازم است).")
            client = hooks.bale_client()
            if client is None:
                raise PaymentError("رباتِ پرداختِ بله الان وصل نیست. چند لحظهٔ دیگر دوباره امتحان کن.")
            return await self._bale_pay_instruction(order, client, hooks)

        raise PaymentError("این روش پرداخت وجود نداره.")

    async def _bale_pay_instruction(self, order: Order, client: BalePayClient, hooks: PaymentHooks) -> PaymentInstruction:
        """مسیرِ اصلی: لینکِ پرداختِ مستقیم (``createInvoiceLink``). اگر نشد، دیپ‌لینکِ ربات."""
        token = self._settings.get_bale_pay_provider_token()
        code = make_pay_code()
        self._orders.set_payment_info(order.id, METHOD_BALE_PAY, gateway_ref=code)
        prices = invoice_prices(order)
        link = ""
        mode = getattr(self._settings, "bale_pay_link_mode", "auto") or "auto"
        if mode != "deeplink":
            try:
                link = await client.create_invoice_link(
                    f"سفارش #{order.id}", invoice_description(order), order_payload(order.id, code), token, prices
                )
            except BaleApiError as exc:
                self.last_errors[METHOD_BALE_PAY] = str(exc)
                logger.warning("createInvoiceLink برای سفارش %s شکست خورد: %s", order.id, exc)
            if looks_like_payment_url(link):
                self._orders.set_payment_info(order.id, METHOD_BALE_PAY, gateway_ref=code, payment_url=link)
                self.last_errors.pop(METHOD_BALE_PAY, None)
                return self._link_instruction(order, link, t("pay.bale.link.button"))

        deep = self._deep_link_fallback(order, client, hooks, code)
        if deep is not None:
            return deep
        if link and not looks_like_payment_url(link):
            raise PaymentError("بله لینکِ پرداختِ معتبری برگرداند نکرد؛ بعداً دوباره امتحان کن یا کارت‌به‌کارت را انتخاب کن.")
        raise PaymentError("ساختِ لینکِ بله‌پی ممکن نشد؛ کارت‌به‌کارت را انتخاب کن یا چند دقیقهٔ دیگر دوباره امتحان کن.")

    def _link_instruction(self, order: Order, link: str, button_label: str) -> PaymentInstruction:
        lines = [
            t("pay.bale.link.title", order_id=order.id),
            t("pay.amount", amount=f"{order.total_irr:,}"),
        ]
        left = _left_text(order)
        if left:
            lines.append(left)
        lines += [t("pay.bale.link.how"), self._after_pay_sentence()]
        return PaymentInstruction(METHOD_BALE_PAY, "\n".join(lines), [(button_label, link)], link)

    def _deep_link_fallback(self, order: Order, client: BalePayClient, hooks: PaymentHooks, code: str) -> Optional[PaymentInstruction]:
        """رباتِ پرداختِ بله با ``/start pay_<id>_<code>`` فاکتورِ بومی را در چتِ بله می‌فرستد."""
        username = getattr(client, "bot_username", "") or ""
        if not username:
            return None
        link = bale_pay_deep_link(username, order.id, code)
        self._orders.set_payment_info(order.id, METHOD_BALE_PAY, gateway_ref=code, payment_url=link)
        lines = [
            t("pay.bale.link.title", order_id=order.id),
            t("pay.amount", amount=f"{order.total_irr:,}"),
        ]
        left = _left_text(order)
        if left:
            lines.append(left)
        lines += [t("pay.bale.deeplink.how"), t("pay.bale.deeplink.manual", order_id=order.id, code=code), self._after_pay_sentence()]
        return PaymentInstruction(METHOD_BALE_PAY, "\n".join(lines), [(t("pay.bale.button"), link)], link)

    def _pay_attempt_allowed(self, chat_id: str) -> bool:
        """سقفِ تلاشِ حدسِ کدِ پرداخت به‌ازای هر چت؛ کدِ درست ۴۸ بیت تصادفی است، ولی
        حدسِ خودکار را هم می‌بندیم چون لینکِ پرداخت پولِ یک سفارشِ دیگر را تأیید می‌کند.
        شمارش بعد از ``PAY_CODE_WINDOW_SECONDS`` از نو شروع می‌شه (بستنِ دائمی چت لازم نیست)
        و دیک هیچ‌وقت بی‌سقف بزرگ نمی‌شه."""
        chat = str(chat_id)
        used, first_ts = self._pay_attempts.get(chat, (0, time.time()))
        if time.time() - first_ts > PAY_CODE_WINDOW_SECONDS:
            used = 0
        if used >= PAY_CODE_MAX_ATTEMPTS_PER_CHAT:
            return False
        self._pay_attempts[chat] = (used + 1, first_ts if used else time.time())
        if len(self._pay_attempts) > _MEMORY_CAP:
            for stale in [k for k, (_, ts) in self._pay_attempts.items() if time.time() - ts > PAY_CODE_WINDOW_SECONDS]:
                self._pay_attempts.pop(stale, None)
            if len(self._pay_attempts) > _MEMORY_CAP:
                self._pay_attempts.clear()
        return True

    def _remember_payer(self, order_id: int, user_id: str) -> None:
        if len(self._expected_payer) > _MEMORY_CAP:
            for stale in list(self._expected_payer)[: len(self._expected_payer) - _MEMORY_CAP + 64]:
                self._expected_payer.pop(stale, None)
        self._expected_payer[order_id] = user_id

    async def handle_pay_command(self, command, client: BalePayClient) -> Optional[str]:
        """پاسخ به ``/pay`` یا ``/start pay_…`` در چتِ رباتِ پرداختِ بله — فاکتورِ بومی می‌فرستد.

        پیامِ عادیِ دیگر را پاسخ نمی‌دهیم (رباتِ بله با کسی حرف نمی‌زند)."""
        if not self._pay_attempt_allowed(command.chat_id):
            logger.warning("چتِ %s به سقفِ تلاشِ کدِ پرداخت رسید", str(command.chat_id)[-8:])
            return t("pay.link_invalid")
        order = self._orders.get(command.order_id)
        if (
            order is None
            or order.payment_method != METHOD_BALE_PAY
            or not order.gateway_ref
            or not hmac.compare_digest(str(order.gateway_ref), str(command.code))
        ):
            return t("pay.link_invalid")
        self._pay_attempts.pop(str(command.chat_id), None)
        if order.status in (STATUS_PAID, STATUS_CONFIRMED):
            return t("pay.already_paid")
        if not reservation_active(order):
            return t("pay.link_expired")
        token = self._settings.get_bale_pay_provider_token() if self._settings else ""
        if not token:
            return t("pay.disabled")
        try:
            await client.send_invoice(command.chat_id, f"سفارش #{order.id}", invoice_description(order), order_payload(order.id, command.code), token, invoice_prices(order))
        except BaleApiError as exc:
            self.last_errors[METHOD_BALE_PAY] = str(exc)
            logger.exception("فاکتورِ بله‌پی برای سفارش %s فرستاده نشد", order.id)
            return t("pay.failed")
        self.last_errors.pop(METHOD_BALE_PAY, None)
        return t("pay.invoice_sent", order_id=order.id)

    # ---------------------------------------------------------- کارت‌به‌کارت: رسید

    def attach_receipt(self, order_id: int, text: str, hooks: PaymentHooks, file_path: str = "") -> Optional[dict]:
        """رسیدِ مشتری (متن یا عکس) را ثبت و مبلغش را با سفارش مقایسه می‌کند.

        هیچ تأییدی انجام نمی‌شه؛ فقط «چه فرستاد» + «مبلغ می‌خونه یا نه» برایِ مالک."""
        order = self._orders.get(order_id)
        if order is None or order.status not in (STATUS_PENDING_PAYMENT, STATUS_PAID, STATUS_EXPIRED):
            return None
        kind = "image" if file_path else "text"
        info = parse_receipt(text or "", order.total_irr) if (text and kind == "text") else None
        state = info.state if info else "none"
        if not getattr(self._settings, "receipt_amount_check", True):
            state = "none"
        amount = info.matched_amount or info.nearest_amount if info else 0
        receipt_id = self._orders.add_receipt(
            order_id,
            kind=kind,
            body=(text or "")[:2000],
            file_path=file_path,
            amount_irr=int(amount or 0),
            trace_code=(info.trace if info else ""),
            card_last4=(info.card_last4 if info else ""),
            match_state=state,
        )
        if receipt_id is None:
            return None
        fresh = self._orders.get(order_id)
        trace = (info.trace if info else "") or ""
        # «یک رسید، دو سفارش»: همان کدِ رهگیری ممکن است به سفارشِ دیگری چسبیده باشد. ما تأیید
        # نمی‌کنیم و رد هم نمی‌کنیم — فقط مالک را هم‌زمانِ همین آلارم مطلع می‌کنیم.
        duplicate_of = self._orders.find_paid_by_reference(trace) if trace else None
        if duplicate_of == order_id:
            duplicate_of = None
        payload = {
            "kind": kind,
            "receipt_id": receipt_id,
            "text": (text or "")[:400],
            "file_path": file_path,
            "state": state,
            "summary": info.summary(order.total_irr) if info else ("عکسِ رسید دریافت شد." if kind == "image" else ""),
            "trace": trace,
            "duplicate_of": duplicate_of or 0,
        }
        hooks.payment_claim(fresh or order, payload)
        return payload

    # ----------------------------------------------------------- تأییدِ پرداخت

    def finalize_online_payment(
        self,
        order_id: int,
        method: str,
        reference: str = "",
        paid_amount: Optional[int] = None,
        gateway_verified: bool = True,
    ) -> Optional[Order]:
        """پرداختِ *تأییدشدهٔ* درگاه را ثبت می‌کند و (طبقِ تنظیمات) سفارش را خودکار تأیید می‌کند.

        **تأییدِ خودکار فقط وقتی که درگاه جوابِ قطعی داده باشد:** پرداختِ دیررس (بعد از انقضا/لغو)، مبلغِ
        نامطابق، استعلامِ تراکنشِ بی‌جواب یا «در انتظار»، یا سفارشی که همین شناسهٔ تراکنش را قبلاً ثبت
        کرده، خودکار تأیید نمی‌شه و «پرداخت‌شده» می‌مونه تا صاحبِ فروشگاه تصمیم بگیره."""
        order = self._orders.get(order_id)
        if order is None:
            return None
        if reference and order.payment_reference and not hmac.compare_digest(order.payment_reference, reference):
            logger.error("سفارش %s از قبل شناسهٔ تراکنشِ دیگری دارد؛ ثبتِ دوباره انجام نشد", order_id)
            return None
        if reference and not self._orders.claim_payment_charge(reference, order_id, method):
            owner = self._orders.charge_owner(reference)
            if owner != order_id:  # تراکنشِ سفارشِ دیگری است ⇒ رد
                logger.error("تراکنش %s قبلاً سفارش %s را پرداخت کرده؛ سفارش %s نادیده گرفته شد", reference[:24], owner, order_id)
                return None
            # شناسه از قبل مالِ همین سفارش است: رویدادِ تکراری یا شکستِ بعد از claim و قبل از
            # mark_paid. اینجا باید ادامه داد (idempotent)، وگرنه پولِ مشتری روی نیمه‌کاره می‌ماند
            # و هیچ تلاشِ دوباره‌ای نمی‌تواند سفارش را به مقصد برساند.
            logger.info("تراکنش %s پیش‌تر برای همین سفارش %s ثبت شده بود؛ ادامه می‌دهیم", reference[:24], order_id)
        already_paid = order.status == STATUS_PAID and bool(reference) and hmac.compare_digest(str(order.payment_reference or ""), reference)
        if not already_paid:
            try:
                self._orders.mark_paid(order_id, method, payment_reference=reference)
            except OrderError:
                logger.exception("ثبتِ پرداختِ سفارش %s ناموفق بود", order_id)
                return None
        else:
            # همین شناسه قبلاً روی همین سفارش ثبت شده (استعلامِ دوباره، یا رویدادِ تکراریِ بله):
            # عبورِ paid→paid ممکن نیست، ولی نتیجه‌ی استعلامِ تازه باید بتواند تأیید را تکمیل کند
            logger.info("سفارش %s از قبل با همین شناسه پرداخت شده بود؛ فقط وضعیتِ تأیید بررسی می‌شه", order_id)
        order = self._orders.get(order_id)
        if self._settings is None or not self._settings.auto_confirm_gateway_payments or order is None:
            return order
        if not gateway_verified:
            logger.warning("استعلامِ تراکنشِ سفارش %s جوابِ قطعی نداد؛ تأییدِ خودکار انجام نشد", order_id)
            return order
        if order.paid_late:
            logger.warning("سفارش %s پرداختِ دیررس داشت؛ تأییدِ خودکار انجام نشد (دستی تصمیم بگیر)", order_id)
            return order
        if paid_amount is not None and paid_amount != order.total_irr:
            logger.error(
                "مبلغِ پرداخت‌شده (%s) با مبلغِ سفارش %s (%s) نمی‌خونه؛ تأییدِ خودکار انجام نشد",
                paid_amount, order_id, order.total_irr,
            )
            return order
        try:
            self._orders.confirm(order_id, by="auto")
        except OrderError as exc:
            logger.warning("تأییدِ خودکارِ سفارش %s انجام نشد (دستی تأیید کن): %s", order_id, exc)
        return self._orders.get(order_id)

    # ------------------------------------------------------------------ بله‌پی

    async def handle_pre_checkout(self, query: BalePreCheckoutQuery, client: BalePayClient) -> None:
        """باید سریع تمام بشه: فقط یک خواندنِ سریع از SQLite، بدونِ شبکه و بدونِ AI.

        سفارشِ منقضی‌شده، ارزِ نادرست، مبلغِ نخوان، یا کالایی که موجودی‌اش کم شده ⇒ ردِ
        پرداخت (به‌جایِ پذیرفتنِ ریسک)."""
        order_id, code = parse_payload(query.invoice_payload)
        order = self._orders.get(order_id) if order_id is not None else None
        if order is None or not reservation_active(order):
            await self._safe_answer(client, query.query_id, False, t("pay.order_invalid"))
            return
        if code and order.gateway_ref and not hmac.compare_digest(str(order.gateway_ref), code):
            await self._safe_answer(client, query.query_id, False, t("pay.link_invalid"))
            return
        if query.total_amount <= 0 or query.total_amount != order.total_irr:
            await self._safe_answer(client, query.query_id, False, t("pay.amount_changed"))
            return
        if (query.currency or "IRR").upper() != "IRR":
            await self._safe_answer(client, query.query_id, False, t("pay.currency_error"))
            return
        self._remember_payer(order.id, str(query.from_user_id))
        for item in order.items:
            if item.product_id is None:
                continue
            product = self._products.get(item.product_id)
            if product is None or (not product.unlimited_stock and product.stock_quantity < item.quantity):
                await self._safe_answer(client, query.query_id, False, t("pay.item_unavailable", name=item.product_name))
                return
        await self._safe_answer(client, query.query_id, True)

    async def _safe_answer(self, client: BalePayClient, query_id: str, ok: bool, error_message: str = "") -> None:
        try:
            await client.answer_pre_checkout_query(query_id, ok, error_message)
        except BaleApiError:
            logger.exception("پاسخ به pre_checkout_query %s ناموفق بود", query_id)

    async def handle_successful_payment(self, payment: BaleSuccessfulPayment, client: BalePayClient) -> Optional[Order]:
        """تأییدِ نهاییِ پرداخت — عمداً خودش به مشتری پیامی نمی‌فرستد.

        ``payment.chat_id`` چتِ سمتِ **بله** است (جایی که تراکنش رخ داده)، نه چتِ اصلیِ مشتری؛
        مسیریابیِ پیام به مشتری با ``order.platform``/``order.chat_id`` به BotManager سپرده می‌شه.

        سه نگهبانی: (۱) payload و کدِ هر-سفارش، (۲) ارز و مبلغِ دقیق، (۳) استعلامِ تراکنش از
        خودِ بله. شکستِ استعلام = ثبتِ پرداخت با وضعیتِ «منتظرِ تأیید» (نه تأییدِ خودکار)، تا
        پولِ مشتری گم نشه و مالک هم چشم‌بسته تأیید نکنه."""
        order_id, code = parse_payload(payment.invoice_payload)
        if order_id is None:
            logger.warning("successful_payment با payload ناشناس: %r", payment.invoice_payload)
            return None
        order = self._orders.get(order_id)
        if order is None:
            logger.warning("successful_payment برای سفارشِ ناموجود %s", order_id)
            return None
        if code and order.gateway_ref and not hmac.compare_digest(str(order.gateway_ref), code):
            logger.error("کدِ پرداختِ سفارش %s نمی‌خونه؛ رویدادِ پرداخت نادیده گرفته شد", order_id)
            return None
        expected = self._expected_payer.get(order_id)
        if expected and payment.from_user_id and expected != str(payment.from_user_id):
            logger.error("پرداخت‌کنندهٔ سفارش %s با کسی که فاکتور را باز کرد نمی‌خواند (%s ≠ %s)",
                         order_id, expected, payment.from_user_id)
            return None
        if (payment.currency or "IRR").upper() != "IRR":
            logger.error("successful_paymentِ سفارش %s ارزِ غیرریال دارد: %s", order_id, payment.currency)
            return None
        if payment.total_amount != order.total_irr:
            # پول ثبت می‌شه (مشتری چیزی پرداخته و نباید گم بشه) ولی تأییدِ خودکار هرگز:
            # مبلغِ نخوان یعنی یا کم واریز شده یا رویداد به سفارشِ دیگری تعلق دارد ⇒ تصمیم با مالک
            logger.error("مبلغِ تراکنش (%s) با سفارش %s (%s) نمی‌خونه", payment.total_amount, order_id, order.total_irr)

        reference = payment.provider_payment_charge_id or payment.telegram_payment_charge_id
        if not reference:
            logger.error("تراکنشِ سفارش %s شناسهٔ یکتا ندارد؛ ثبت نشد", order_id)
            return None
        # «یک تراکنش، یک بار» از روی دیتابیس (نه حافظه): رویدادِ دوباره‌ی بله — برای همین سفارش
        # یا برای سفارشِ دیگر — قبل از هر هزینه‌ی شبکه‌ای رد می‌شه و بازنویسی نمی‌شه.
        already = self._orders.charge_owner(reference)
        if already is not None:
            logger.info("تراکنشِ تکراری (%s) قبلاً سفارش %s را پرداخت کرده؛ نادیده گرفته شد", reference[:24], already)
            return None

        verified = False
        try:
            tx = await client.inquire_transaction(reference)
            status = str(tx.get("status", "")).strip().lower()
            if status in _SUCCESSFUL_STATUSES:
                verified = True
            elif not status or status in _PENDING_STATUSES:
                # «بدونِ وضعیت» یعنی نمی‌دانیم؛ حدسِ «موفق» برایِ پولِ مشتری مجاز نیست
                logger.warning("استعلامِ تراکنشِ سفارش %s جوابِ قطعی نداد: %r", order_id, status or tx)
                self._pending_verify[order_id] = (reference, time.time())
            else:
                logger.error("استعلامِ تراکنشِ سفارش %s وضعیتِ غیرموفق داد: %r", order_id, tx)
                return None
        except BaleApiError as exc:
            logger.warning("استعلامِ تراکنشِ سفارش %s ممکن نشد (%s)؛ پرداخت ثبت می‌شه ولی تأییدِ خودکار نه", order_id, exc)
            self._pending_verify.setdefault(order_id, (reference, time.time()))

        amount_ok = payment.total_amount == order.total_irr
        finalized = self.finalize_online_payment(
            order_id, METHOD_BALE_PAY, reference, payment.total_amount, gateway_verified=verified and amount_ok
        )
        if verified and finalized is not None:
            self._pending_verify.pop(order_id, None)
        return finalized

    def has_pending_verifications(self) -> bool:
        """آیا تراکنشی هست که بله درباره‌اش جوابِ قطعی نداد و باید دوباره استعلام شود؟"""
        return bool(self._pending_verify)

    async def retry_pending_verifications(self, client: BalePayClient) -> list:
        """استعلامِ دوبارهٔ تراکنش‌هایی که آخرین‌بار بله جوابِ قطعی نداد (تا ۲۴ ساعت)."""
        done = []
        for order_id, (reference, first_ts) in list(self._pending_verify.items()):
            if time.time() - first_ts > 24 * 3600:
                self._pending_verify.pop(order_id, None)
                continue
            try:
                tx = await client.inquire_transaction(reference)
            except BaleApiError:
                continue
            status = str(tx.get("status", "")).strip().lower()
            if status and status not in _SUCCESSFUL_STATUSES:
                if status not in _PENDING_STATUSES:
                    self._pending_verify.pop(order_id, None)
                continue
            order = self._orders.get(order_id)
            if order is None or order.status == STATUS_CONFIRMED:
                self._pending_verify.pop(order_id, None)
                continue
            # «پرداخت‌شده ولی تأییدِنشده» را رها نمی‌کنیم: همان حالتِ استعلامِ بی‌جواب است و باید
            # تا سقفِ ۲۴ ساعت دوباره بررسی شود، وگرنه سفارش نیمه‌کاره می‌ماند
            # مقدار و ارزِ استعلام هم اگر بله اعلام کرده باشد باید بخوانند (دفاعِ چندلایه)
            tx_amount = tx.get("amount", tx.get("total_amount"))
            amount_ok = tx_amount is None or str(tx_amount).strip() in {"", str(order.total_irr)}
            finalized = self.finalize_online_payment(
                order_id,
                METHOD_BALE_PAY,
                reference,
                order.total_irr if amount_ok else None,
                gateway_verified=bool(status) and status in _SUCCESSFUL_STATUSES and amount_ok,
            )
            if finalized is not None:
                self._pending_verify.pop(order_id, None)
                done.append(finalized)
        return done

    # ------------------------------------------------------------ تشخیص (UI)

    async def diagnose_bale_pay(self, hooks: PaymentHooks) -> tuple:
        """چکِ واقعیِ بله‌پی: توکن‌ها، اتصالِ رباتِ پرداخت، و ساختنِ یک لینکِ پرداختِ آزمایشی
        (یک ریال، پرداختش نکن) تا مطمئن بشی درگاه جواب می‌ده."""
        s = self._settings
        if s is None or not s.bale_pay_enabled:
            return False, "بله‌پی خاموش است."
        bot_token = s.get_bale_pay_bot_token()
        provider = s.get_bale_pay_provider_token()
        if not bot_token:
            return False, "توکنِ رباتِ پرداختِ بله وارد نشده."
        if not provider:
            return False, "توکنِ درگاه (provider_token) وارد نشده."
        client = hooks.bale_client()
        if client is None:
            return False, ("رباتِ پرداختِ بله وصل نیست — ربات‌ها خاموش‌اند؛ در صفحهٔ «ربات‌ها» روشن یا "
                         "ری‌استارتشان کن (دکمهٔ «روشن/ری‌استارت کردنِ ربات‌ها» پایینِ همین کارت هم هست).")
        kind = describe_provider_token(provider)
        note = f" | توکن از نوعِ «{kind}»" + (" ⚠️ این توکنِ آزمایشیِ مستندات است" if is_test_provider_token(provider) else "")
        try:
            link = await client.create_invoice_link("تست پرداخت", "تست اتصالِ بله‌پی (پرداخت نکن)", "diag", provider, [("تست", 10_000)])
        except BaleApiError as exc:
            self.last_errors[METHOD_BALE_PAY] = str(exc)
            return False, f"بله لینکِ آزمایشی را نپذیرفت: {exc}"
        if looks_like_payment_url(link):
            self.last_errors.pop(METHOD_BALE_PAY, None)
            return True, f"✅ لینکِ پرداختِ آزمایشی ساخته شد: {link[:80]}… (پرداختش نکن){note}"
        username = getattr(client, "bot_username", "") or ""
        if username:
            self.last_errors.pop(METHOD_BALE_PAY, None)
            return True, f"✅ رباتِ پرداخت وصل است؛ برنامه از دیپ‌لینکِ «ble.ir/{username}» استفاده می‌کند{note}"
        return False, f"بله لینکی برگرداند ({str(link)[:60]!r}) و یوزرنیمِ ربات هم مشخص نیست.{note}"

    async def diagnose_card_to_card(self) -> tuple:
        s = self._settings
        if s is None or not s.card_to_card_number:
            return False, "شماره کارت وارد نشده."
        return True, f"✅ کارت {s.card_to_card_number} ثبت شده؛ تأییدِ پرداخت همیشه دستی است."
