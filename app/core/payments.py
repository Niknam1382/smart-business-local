"""
منطق پرداخت بله‌پی: پاسخ به ``pre_checkout_query`` (باید سریع باشه، زیر ۱۰
ثانیه)، ثبت ``successful_payment``، و ساخت لینک پرداخت. مستقل از خودِ
آداپتور بله — تست‌پذیر با کلاینت/فروشگاه‌های جعلی.

نکته‌ی مهم معماری: بله‌پی فقط بخشی از Bot API خودِ بله‌ست (``provider_token`` و کل جریان
pre_checkout/successful_payment به ربات **بله** می‌رسه، نه تلگرام). برای همین:

* مشتریِ **بله‌ای** → فاکتورِ بومیِ ``sendInvoice`` مستقیم توی چتش فرستاده می‌شه (روشِ
  رسمی و مستندِ بله؛ هیچ لینکی لازم نیست و چیزی برای «خراب‌شدن» نمی‌مونه).
* مشتریِ **تلگرامی** → یه دیپ‌لینکِ ربات بله (``https://ble.ir/<ربات>?start=pay_<سفارش>_<کد>``)
  می‌گیره؛ با باز کردنش و زدنِ «شروع»، ربات بله همون فاکتورِ بومی رو توی چتِ بله‌ی خودش
  می‌فرسته (``handle_pay_command``). اگه «شروع» خودکار نشد، فرمانِ ``/pay <سفارش> <کد>``
  همون کار رو می‌کنه. ``<کد>`` یه رمزِ تصادفیِ هر-سفارشه تا کسی با حدس‌زدنِ شماره‌ی سفارش
  فاکتورِ دیگران رو نبینه.
* قبلاً این‌جا از ``createInvoiceLink`` استفاده می‌شد؛ فرمتِ خروجیِ اون متد توی مستنداتِ
  اصلیِ بله مشخص نیست و لینک‌ها در عمل خراب بودن، پس دیگه توی مسیرِ پرداخت نیست.

تاییدِ پرداخت همیشه از طریق ربات **بله** می‌رسه؛ سفارش‌ها با platform/chat_id واقعیِ مشتری
(نه لزوماً «بله») ذخیره می‌شن و پیام تاییدِ پرداخت با همون platform/chat_id اصلی (از طریق هر
آداپتوری که لازمه) برای مشتری فرستاده می‌شه — ``send`` همیشه از بیرون (توسط bot_manager، که
می‌دونه هر چت به کدوم آداپتور وصله) تزریق می‌شه، نه خودِ این ماژول.
"""

from __future__ import annotations

import hmac
import logging
import math
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from app.core.bale_client import BaleApiError, BaleClient, BalePreCheckoutQuery, BaleSuccessfulPayment
from app.core.orders import (
    METHOD_BALE_PAY,
    METHOD_CARD_TO_CARD,
    METHOD_ZARINPAL,
    STATUS_CONFIRMED,
    STATUS_PAID,
    STATUS_PENDING_PAYMENT,
    Order,
    OrderError,
    OrderStore,
    build_order_confirmed_text,
    build_order_summary_text,
)
from app.core.products import ProductStore
from app.core.shop_texts import t
from app.core.zarinpal import ZarinpalClient, ZarinpalError, ZarinpalPayment, is_valid_merchant_id

logger = logging.getLogger(__name__)

_PAYLOAD_PREFIX = "order:"

_SUCCESSFUL_STATUSES = {"successful", "success", "paid", "completed", "done"}


def order_payload(order_id: int) -> str:
    return f"{_PAYLOAD_PREFIX}{order_id}"


def _parse_order_id(payload: str) -> Optional[int]:
    if not payload or not payload.startswith(_PAYLOAD_PREFIX):
        return None
    try:
        return int(payload[len(_PAYLOAD_PREFIX) :])
    except ValueError:
        return None


# ------------------------------------------- دیپ‌لینکِ پرداخت و توکنِ بله‌پی ---

# `/start pay_12_ab12cd34` (دیپ‌لینک) یا `/pay 12 ab12cd34` (دستی، وقتی «شروع» خودکار نشد)
_PAY_COMMAND = re.compile(
    r"^\s*/(?:start|pay)(?:@\w+)?\s+(?:pay[_\s-]?)?(\d{1,12})[_\s-]+([A-Za-z0-9]{6,32})\s*$",
    re.IGNORECASE,
)

# متن‌های این بخش: app/core/shop_texts.py (کلیدهای pay.*)


def parse_pay_command(text: str) -> Optional[tuple]:
    """``(order_id, code)`` اگه پیام فرمانِ پرداختِ بله‌پی بود، وگرنه ``None``."""
    match = _PAY_COMMAND.match(text or "")
    return (int(match.group(1)), match.group(2)) if match else None


def make_pay_code() -> str:
    return secrets.token_hex(4)  # ۸ کاراکتر؛ برای هر بار ساختنِ دستورِ پرداخت تازه


def bale_pay_deep_link(username: str, order_id: int, code: str) -> str:
    return f"https://ble.ir/{username}?start=pay_{order_id}_{code}"


def normalize_provider_token(raw: str) -> str:
    """شماره کارتِ ۱۶ رقمی (با ارقام فارسی/عربی، فاصله یا خط‌تیره) → ۱۶ رقمِ لاتینِ
    پشت‌سرهم؛ هر چیز دیگه (مثل ``WALLET-TEST-…``) فقط trim می‌شه."""
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
        return "توکنِ کیف‌پولِ بله"
    return "فرمتِ ناشناخته (بله‌پی شماره کارتِ ۱۶ رقمی یا توکنِ کیف‌پول می‌خواد)"


def build_payment_received_text(order: Order) -> str:
    text = t("pay.received") + "\n\n" + build_order_summary_text(order)
    text += "\n\n" + (t("pay.received_late") if order.paid_late else t("pay.received_pending"))
    return text


def build_payment_notification_text(order: Order) -> str:
    """پیامِ خودکارِ بعد از پرداختِ آنلاین: اگه سفارش هم‌زمان تایید شده (تایید خودکار)
    فاکتورِ نهایی، وگرنه «پرداخت دریافت شد، منتظر تایید فروشنده»."""
    if order.status == STATUS_CONFIRMED:
        return t("pay.received") + "\n\n" + build_order_confirmed_text(order)
    return build_payment_received_text(order)


METHOD_LABELS = {METHOD_CARD_TO_CARD: "کارت‌به‌کارت", METHOD_BALE_PAY: "بله‌پی", METHOD_ZARINPAL: "زرین‌پال"}


class PaymentError(Exception):
    """خطای قابل‌نمایش (فارسی) در ساختن دستورِ پرداخت؛ مدل زبانی پیامش رو می‌بینه."""


@dataclass
class PaymentInstruction:
    method: str
    text: str
    buttons: list = field(default_factory=list)  # [(برچسب, url)]
    url: str = ""


async def _no_owner(text: str) -> bool:
    return False


@dataclass
class PaymentHooks:
    """چیزهایی که فقط BotManager می‌دونه (کلاینتِ زنده‌ی بله، یوزرنیم ربات‌ها، اعلان به مالک)."""

    bale_client: Callable[[], Optional[BaleClient]] = lambda: None
    bot_username: Callable[[str], Optional[str]] = lambda platform: None
    # اعلان به چت(های) ثبت‌شده‌ی مالک؛ True یعنی حداقل به یکی رسید
    notify_owner: Callable[[str], Awaitable[bool]] = _no_owner


def reservation_active(order: Order, now: Optional[float] = None) -> bool:
    if order.status != STATUS_PENDING_PAYMENT:
        return False
    return order.expires_ts == 0 or order.expires_ts > (time.time() if now is None else now)


def _left_text(order: Order) -> str:
    seconds = order.seconds_left()
    if not seconds:
        return ""
    return t("pay.left", minutes=max(1, math.ceil(seconds / 60)))


class PaymentService:
    def __init__(self, order_store: OrderStore, product_store: ProductStore, settings=None, zarinpal_base_url: str = ""):
        self._orders = order_store
        self._products = product_store
        self._settings = settings
        self._zarinpal_base_url = zarinpal_base_url  # فقط برای تست (سرور جعلی)
        self._zarinpal_dead: set = set()  # سفارش‌هایی که استعلامشون قطعاً بی‌فایده‌ست
        self.last_errors: dict = {}  # روش -> آخرین پیام خطا (برای دکمه‌های تشخیص در UI)

    def set_settings(self, settings) -> None:
        self._settings = settings

    # ------------------------------------------------------------ روش‌های فعال

    def available_methods(self, bale_running: bool = False) -> list:
        """روش‌هایی که *همین الان* واقعاً قابل‌ارائه‌ان. بله‌پی فقط وقتی که ربات بله
        وصل باشه (لینکش از طریق همون ساخته می‌شه)."""
        s = self._settings
        if s is None:
            return []
        methods = []
        if s.card_to_card_number:
            methods.append(METHOD_CARD_TO_CARD)
        if s.bale_pay_enabled and s.get_bale_pay_provider_token() and bale_running:
            methods.append(METHOD_BALE_PAY)
        if s.zarinpal_enabled and is_valid_merchant_id(s.get_zarinpal_merchant_id()):
            methods.append(METHOD_ZARINPAL)
        return methods

    def _zarinpal_client(self) -> Optional[ZarinpalClient]:
        s = self._settings
        if s is None or not (s.zarinpal_enabled and is_valid_merchant_id(s.get_zarinpal_merchant_id())):
            return None
        return ZarinpalClient(
            s.get_zarinpal_merchant_id(), sandbox=bool(s.zarinpal_sandbox), base_url=self._zarinpal_base_url
        )

    # ---------------------------------------------------------- دستورِ پرداخت

    def _after_pay_sentence(self) -> str:
        auto = bool(self._settings and self._settings.auto_confirm_gateway_payments)
        return t("pay.after_auto") if auto else t("pay.after_manual")

    def _link_message(self, order: Order, label: str, url: str) -> tuple:
        lines = [t("pay.link.title", label=label, order_id=order.id), t("pay.amount", amount=f"{order.total_irr:,}")]
        left = _left_text(order)
        if left:
            lines.append(left)
        # بله فرمتِ [متن](لینک) رو می‌شناسه و لینکِ دارای underscore رو توی متنِ ساده
        # ممکنه خراب کنه؛ تلگرام متن ساده نشون می‌ده، پس لینکِ عریان.
        lines.append(t("pay.link.cta", url=url) if order.platform == "bale" else url)
        lines.append(self._after_pay_sentence())
        return "\n".join(lines), [(t("pay.link.button", label=label), url)]

    async def build_instruction(self, order: Order, method: str, hooks: PaymentHooks) -> PaymentInstruction:
        s = self._settings
        if s is None:
            raise PaymentError("پرداخت هنوز تنظیم نشده.")
        if method == METHOD_CARD_TO_CARD:
            if not s.card_to_card_number:
                raise PaymentError("کارت‌به‌کارت فعال نیست.")
            self._orders.set_payment_info(order.id, METHOD_CARD_TO_CARD)
            lines = [
                t("pay.card.title", order_id=order.id),
                t("pay.card.amount", amount=f"{order.total_irr:,}"),
                t("pay.card.number", number=s.card_to_card_number),
            ]
            if s.card_to_card_holder_name:
                lines.append(t("pay.card.holder", holder=s.card_to_card_holder_name))
            left = _left_text(order)
            if left:
                lines.append(left)
            lines.append(t("pay.card.after"))
            return PaymentInstruction(METHOD_CARD_TO_CARD, "\n".join(lines))

        if method == METHOD_BALE_PAY:
            token = s.get_bale_pay_provider_token()
            client = hooks.bale_client()
            if not (s.bale_pay_enabled and token):
                raise PaymentError("بله‌پی فعال نیست.")
            if client is None:
                raise PaymentError("بله‌پی از طریق ربات بله انجام می‌شه و ربات بله الان وصل نیست.")
            if order.platform == "bale":
                return await self._native_bale_invoice(order, client, token)
            return self._bale_deep_link_instruction(order, hooks)

        if method == METHOD_ZARINPAL:
            client = self._zarinpal_client()
            if client is None:
                raise PaymentError("زرین‌پال فعال نیست.")
            callback = s.zarinpal_callback_url.strip() or self._default_callback(order.platform, hooks)
            description = "، ".join(f"{i.product_name} ×{i.quantity}" for i in order.items)
            try:
                pay: ZarinpalPayment = await client.create_payment(order.total_irr, callback, f"سفارش #{order.id}: {description}")
            except ZarinpalError as exc:
                self.last_errors[METHOD_ZARINPAL] = str(exc)
                logger.error("ساخت پرداخت زرین‌پال برای سفارش %s شکست خورد: %s", order.id, exc)
                raise PaymentError(f"ساخت لینک زرین‌پال الان ممکن نشد ({exc}) روش پرداخت دیگه‌ای پیشنهاد بده.") from exc
            self.last_errors.pop(METHOD_ZARINPAL, None)
            self._orders.set_payment_info(order.id, METHOD_ZARINPAL, gateway_ref=pay.authority, payment_url=pay.url)
            text, buttons = self._link_message(order, "زرین‌پال", pay.url)
            return PaymentInstruction(METHOD_ZARINPAL, text, buttons, pay.url)

        raise PaymentError("این روش پرداخت وجود نداره.")

    @staticmethod
    def _default_callback(platform: str, hooks: PaymentHooks) -> str:
        """بعد از پرداخت، زرین‌پال مشتری رو به این آدرس برمی‌گردونه — بهترین مقصد خودِ
        چتِ ربات (t.me / ble.ir)، تا مشتری بعد از پرداخت یه صفحه‌ی خطا نبینه."""
        username = hooks.bot_username(platform)
        if platform == "bale":
            return f"https://ble.ir/{username}" if username else "https://ble.ir"
        return f"https://t.me/{username}" if username else "https://t.me"

    @staticmethod
    async def _send_native_invoice(client: BaleClient, chat_id: str, order: Order, token: str) -> None:
        """فاکتورِ بومیِ بله (sendInvoice) — محدودیت‌های بله: عنوان ≤۳۲ و توضیح ≤۲۵۵ کاراکتر."""
        prices = [(item.product_name[:32] or "کالا", item.subtotal_irr) for item in order.items]
        if order.discount_irr > 0:  # N8: جمعِ ردیف‌ها باید دقیقاً مبلغِ نهایی باشه (بدونِ ردیفِ منفی که ممکنه رد بشه)
            prices = [(f"سفارش #{order.id}"[:32], order.total_irr)]
        description = "، ".join(f"{i.product_name} ×{i.quantity}" for i in order.items)[:255] or f"سفارش #{order.id}"
        await client.send_invoice(
            chat_id, f"سفارش #{order.id}"[:32], description, order_payload(order.id), token, prices
        )

    async def _native_bale_invoice(self, order: Order, client: BaleClient, token: str) -> PaymentInstruction:
        """مشتریِ بله‌ای: فاکتورِ بومی مستقیم توی همین چت فرستاده می‌شه."""
        try:
            await self._send_native_invoice(client, order.chat_id, order, token)
        except Exception as exc:  # noqa: BLE001
            self.last_errors[METHOD_BALE_PAY] = str(exc)
            logger.exception("sendInvoice بله برای سفارش %s شکست خورد", order.id)
            raise PaymentError("ساخت فاکتور بله‌پی الان ممکن نشد؛ روش پرداخت دیگه‌ای پیشنهاد بده.") from exc
        self.last_errors.pop(METHOD_BALE_PAY, None)
        self._orders.set_payment_info(order.id, METHOD_BALE_PAY)
        text = (
            f"{t('pay.bale.native', order_id=order.id)}\n"
            f"{_left_text(order)}\n{self._after_pay_sentence()}"
        ).replace("\n\n", "\n")
        return PaymentInstruction(METHOD_BALE_PAY, text)

    def _bale_deep_link_instruction(self, order: Order, hooks: PaymentHooks) -> PaymentInstruction:
        """مشتریِ تلگرامی: دیپ‌لینکِ ربات بله. فاکتور با «شروع» (یا ``/pay``) توی چتِ بله می‌رسه."""
        username = hooks.bot_username("bale")
        if not username:
            raise PaymentError(
                "نام کاربریِ ربات بله هنوز مشخص نیست؛ چند لحظه‌ی دیگه دوباره امتحان کن یا روش پرداخت دیگه‌ای پیشنهاد بده."
            )
        code = make_pay_code()
        link = bale_pay_deep_link(username, order.id, code)
        self._orders.set_payment_info(order.id, METHOD_BALE_PAY, gateway_ref=code, payment_url=link)
        lines = [t("pay.bale.link.title", order_id=order.id), t("pay.amount", amount=f"{order.total_irr:,}")]
        left = _left_text(order)
        if left:
            lines.append(left)
        lines += [
            t("pay.bale.link.open"),
            t("pay.bale.link.manual", order_id=order.id, code=code),
            link,
            self._after_pay_sentence(),
        ]
        return PaymentInstruction(METHOD_BALE_PAY, "\n".join(lines), [(t("pay.bale.button"), link)], link)

    async def handle_pay_command(self, text: str, chat_id: str, client: BaleClient) -> Optional[str]:
        """پاسخ به فرمانِ پرداختِ ربات بله (دیپ‌لینک ``/start pay_<id>_<code>`` یا
        ``/pay <id> <code>``). ``None`` یعنی این پیام فرمانِ پرداخت نبود (بره سراغ
        پایپ‌لاینِ معمول)؛ وگرنه متنِ پاسخ برای مشتری. فاکتور همیشه به چتِ **بله‌ای که
        فرمان ازش اومده** فرستاده می‌شه؛ تاییدِ پرداخت بعداً با ``order.platform`` به
        مشتریِ اصلی می‌رسه."""
        parsed = parse_pay_command(text)
        if parsed is None:
            return None
        order_id, code = parsed
        order = self._orders.get(order_id)
        if (
            order is None
            or order.payment_method != METHOD_BALE_PAY
            or not order.gateway_ref
            or not hmac.compare_digest(order.gateway_ref.encode("utf-8"), code.encode("utf-8"))
        ):
            return t("pay.link_invalid")
        if order.status in (STATUS_PAID, STATUS_CONFIRMED):
            return t("pay.already_paid")
        if not reservation_active(order):
            return t("pay.link_invalid")
        s = self._settings
        token = s.get_bale_pay_provider_token() if s else ""
        if not (s and s.bale_pay_enabled and token):
            return t("pay.disabled")
        try:
            await self._send_native_invoice(client, chat_id, order, token)
        except Exception as exc:  # noqa: BLE001
            self.last_errors[METHOD_BALE_PAY] = str(exc)
            logger.exception("فاکتور بله‌پی برای سفارش %s (فرمان /pay) فرستاده نشد", order.id)
            return t("pay.failed")
        self.last_errors.pop(METHOD_BALE_PAY, None)
        return t("pay.invoice_sent", order_id=order.id)

    # ----------------------------------------------------------- تایید پرداخت

    def finalize_online_payment(
        self, order_id: int, method: str, reference: str = "", paid_amount: Optional[int] = None
    ) -> Optional[Order]:
        """پرداختِ *تاییدشده‌ی* درگاه رو ثبت می‌کنه و (طبق تنظیمات) سفارش رو خودکار
        تایید می‌کنه. **تایید خودکار فقط برای پرداختِ عادیه:** پرداختِ دیررس (بعد از انقضا/لغو)
        یا مبلغِ نامطابق با سفارش خودکار تایید نمی‌شه و «پرداخت‌شده» می‌مونه تا صاحب فروشگاه
        تصمیم بگیره. ``None`` یعنی ثبت ممکن نبود (مثلاً قبلاً پرداخت شده)."""
        try:
            self._orders.mark_paid(order_id, method, payment_reference=reference)
        except OrderError:
            logger.exception("ثبت پرداخت سفارش %s ناموفق بود", order_id)
            return None
        order = self._orders.get(order_id)
        if self._settings is None or not self._settings.auto_confirm_gateway_payments or order is None:
            return order
        if order.paid_late:
            logger.warning("سفارش %s پرداختِ دیررس داشت؛ تایید خودکار انجام نشد (دستی تصمیم بگیر)", order_id)
            return order
        if paid_amount is not None and paid_amount != order.total_irr:
            logger.error("مبلغِ پرداخت‌شده (%s) با مبلغ سفارش %s (%s) نمی‌خونه؛ تایید خودکار انجام نشد", paid_amount, order_id, order.total_irr)
            return order
        try:
            self._orders.confirm(order_id)
            self._orders.set_confirmed_by(order_id, "auto")  # N11: تأییدِ خودکارِ پرداختِ آنلاین
        except OrderError as exc:
            logger.warning("تایید خودکار سفارش %s انجام نشد (دستی تایید کن): %s", order_id, exc)
        return self._orders.get(order_id)

    async def check_zarinpal_orders(self) -> list:
        """سفارش‌های زرین‌پالیِ در انتظار رو استعلام (verify) می‌کنه و آن‌هایی که پرداخت
        شدن رو نهایی می‌کنه. لیستِ سفارش‌های تازه‌نهایی‌شده رو برمی‌گردونه تا به
        مشتری اطلاع داده بشه. خطای شبکه فقط یعنی «دفعه‌ی بعد دوباره»."""
        client = self._zarinpal_client()
        if client is None:
            return []
        done = []
        for order in self._orders.pending_gateway_orders(METHOD_ZARINPAL):
            if order.id in self._zarinpal_dead:
                continue
            try:
                result = await client.verify(order.gateway_ref, order.total_irr)
            except ZarinpalError:
                continue
            if result.fatal:
                self._zarinpal_dead.add(order.id)
                logger.warning("استعلام زرین‌پالِ سفارش %s قطعاً نامعتبره (کد %s)", order.id, result.code)
                continue
            if result.paid:
                finalized = self.finalize_online_payment(order.id, METHOD_ZARINPAL, result.ref_id)
                if finalized is not None:
                    done.append(finalized)
        return done

    # ------------------------------------------------------------ تشخیص (UI)

    async def diagnose_bale_pay(self, hooks: PaymentHooks) -> tuple:
        """چک‌کردنِ بله‌پی: توکن/شماره کارت، اتصالِ ربات بله و — اگه چتِ مالک توی بله ثبت
        شده — یه فاکتورِ آزمایشیِ ۱۰٬۰۰۰ ریالی (پرداختش نکن) تا مطمئن بشی بله همه‌چیز رو
        می‌پذیره. پیامِ دقیقِ خطای بله اگه باشه نشون داده می‌شه."""
        s = self._settings
        token = s.get_bale_pay_provider_token() if s else ""
        if not token:
            return False, "شماره کارت/توکنِ بله‌پی وارد نشده."
        client = hooks.bale_client()
        if client is None:
            return False, "ربات بله وصل نیست — اول از صفحه‌ی «ربات‌ها» روشنش کن."
        kind = describe_provider_token(token)
        owner_chat = ((s.owner_chats or {}) if s else {}).get("bale")
        if not owner_chat:
            return True, (
                f"✅ ربات بله وصله و توکن از نوعِ «{kind}» ثبت شده. برای آزمایشِ واقعیِ فاکتور، "
                "چتِ شخصیِ خودت رو توی بله به‌عنوان مالک ثبت کن (کدِ یک‌بارمصرفِ «ثبت مالک»)، بعد دوباره «تست» رو بزن."
            )
        try:
            await client.send_invoice(owner_chat, "تست پرداخت", "تست اتصال بله‌پی (پرداخت نکن)", "diag", token, [("تست", 10_000)])
        except Exception as exc:  # noqa: BLE001
            self.last_errors[METHOD_BALE_PAY] = str(exc)
            return False, f"بله فاکتورِ آزمایشی رو نپذیرفت: {exc}"
        self.last_errors.pop(METHOD_BALE_PAY, None)
        return True, "✅ فاکتورِ آزمایشیِ ۱۰٬۰۰۰ ریالی توی چتِ بله‌ی خودت فرستاده شد. اگه دیدیش، بله‌پی درسته (پرداختش نکن)."

    async def diagnose_zarinpal(self, hooks: PaymentHooks) -> tuple:
        client = self._zarinpal_client()
        if client is None:
            return False, "زرین‌پال فعال نیست یا مرچنت‌کد معتبر (۳۶ کاراکتر) وارد نشده."
        try:
            pay = await client.create_payment(10_000, self._default_callback("telegram", hooks), "تست اتصال زرین‌پال")
        except ZarinpalError as exc:
            self.last_errors[METHOD_ZARINPAL] = str(exc)
            return False, str(exc)
        self.last_errors.pop(METHOD_ZARINPAL, None)
        return True, f"✅ زرین‌پال کار می‌کنه. لینک آزمایشی (پرداخت نشده): {pay.url}"

    # -------------------------------------------------------------- بله‌پی

    async def handle_pre_checkout(self, query: BalePreCheckoutQuery, client: BaleClient) -> None:
        """باید سریع تموم بشه: فقط چکِ سریع روی SQLite محلی، بدون هیچ تماس شبکه‌ای
        دیگه یا فراخوانی AI. سفارشِ منقضی‌شده، یا فاکتوری که مبلغش با سفارشِ فعلی
        نمی‌خونه (مثلاً مشتری سفارش رو ویرایش کرده و لینک قدیمی رو باز کرده)
        رد می‌شه."""
        order_id = _parse_order_id(query.invoice_payload)
        order = self._orders.get(order_id) if order_id is not None else None
        if order is None or not reservation_active(order):
            await self._safe_answer(client, query.query_id, False, t("pay.order_invalid"))
            return
        if query.total_amount and query.total_amount != order.total_irr:
            await self._safe_answer(client, query.query_id, False, t("pay.order_invalid"))
            return
        for item in order.items:
            if item.product_id is None:
                continue
            product = self._products.get(item.product_id)
            if product is None or (not product.unlimited_stock and product.stock_quantity < item.quantity):
                await self._safe_answer(
                    client, query.query_id, False, t("pay.item_unavailable", name=item.product_name)
                )
                return
        await self._safe_answer(client, query.query_id, True)

    async def _safe_answer(self, client: BaleClient, query_id: str, ok: bool, error_message: str = "") -> None:
        try:
            await client.answer_pre_checkout_query(query_id, ok, error_message)
        except BaleApiError:
            logger.exception("پاسخ به pre_checkout_query %s ناموفق بود", query_id)

    async def handle_successful_payment(
        self,
        payment: BaleSuccessfulPayment,
        client: BaleClient,
    ) -> Optional[Order]:
        """فقط تایید/ثبتِ پرداخت — عمداً خودش پیامی به مشتری نمی‌فرسته.

        چرا: ``payment.chat_id`` چتِ سمتِ **بله**ست (جایی که خودِ تراکنش
        پرداخت اتفاق افتاده)، نه لزوماً چت اصلیِ مشتری — وقتی مشتری تلگرامی
        یه لینک بله‌پی رو باز می‌کنه، successful_payment به ربات بله می‌رسه،
        نه تلگرام. برای فرستادن پیام درست به مشتریِ درست، باید از
        ``order.platform``/``order.chat_id`` (که خودِ سفارش موقع ساخته‌شدن
        ذخیره کرده) استفاده کرد، نه ``payment.chat_id``. این مسیریابی به
        BotManager سپرده می‌شه چون اون به هر دو آداپتور دسترسی داره، نه فقط
        بله."""
        order_id = _parse_order_id(payment.invoice_payload)
        if order_id is None:
            logger.warning("successful_payment با payload ناشناس: %r", payment.invoice_payload)
            return None
        reference = payment.provider_payment_charge_id or payment.telegram_payment_charge_id

        # استعلام نهایی طبق توصیه‌ی مستندات (جلوگیری از تقلب). خطای شبکه/عدم
        # قطعیت مانع ثبت نمی‌شه — چون successful_payment خودش از طریق بله
        # اومده. فقط وضعیتِ *صراحتاً* ناموفق جلوش رو می‌گیره.
        try:
            tx = await client.inquire_transaction(reference)
            status = str(tx.get("status", "")).strip().lower()
            if status and status not in _SUCCESSFUL_STATUSES:
                logger.error("استعلام تراکنش سفارش %s وضعیت غیرموفق داد: %r", order_id, tx)
                return None
        except BaleApiError:
            logger.warning("استعلام تراکنش سفارش %s ناموفق بود؛ successful_payment از بله هنوز معتبر فرض می‌شه", order_id)

        return self.finalize_online_payment(order_id, METHOD_BALE_PAY, reference, paid_amount=payment.total_amount or None)


# ------------------------------------------------------- شماره کارت (تنظیمات) ---

_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_card_number(raw: str) -> str:
    """شماره کارت ورودیِ صاحب فروشگاه رو (با هر نوع رقم فارسی/عربی/لاتین، با
    فاصله یا خط‌تیره یا بدونشون) به شکل استاندارد «۱۲۳۴-۵۶۷۸-۹۰۱۲-۳۴۵۶» (با ارقام
    لاتین) درمیاره. ورودیِ خالی یعنی «غیرفعال‌کردنِ کارت‌به‌کارت» و خالی
    برمی‌گرده. اگه ۱۶ رقم نبود ``ValueError`` (با پیام فارسی) می‌ده — کارت‌های
    بانکی ایران همیشه ۱۶ رقمین و یه رقم جا‌افتاده یعنی پولِ مشتری به حساب
    اشتباه می‌ره، پس بهتره همون‌جا گرفته بشه. (فقط عددبودن و طول چک می‌شه، نه
    Luhn — رد‌کردنِ اشتباهیِ یه کارتِ درست برای صاحب فروشگاه آزاردهنده‌تر از
    این‌ه که یه غلطِ نادرِ هم‌طول رد بشه.)"""
    text = (raw or "").translate(_DIGIT_MAP).strip()
    if not text:
        return ""
    stripped = "".join(ch for ch in text if ch not in " -_\u200c\u200f\u200e")
    if not stripped.isdigit():
        raise ValueError("شماره کارت فقط باید عدد باشه.")
    if len(stripped) != 16:
        raise ValueError(f"شماره کارت باید ۱۶ رقم باشه (الان {len(stripped)} رقم وارد شده).")
    return "-".join(stripped[i : i + 4] for i in range(0, 16, 4))
