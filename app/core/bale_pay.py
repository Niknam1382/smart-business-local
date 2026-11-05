"""
کلاینتِ فقط‌پرداختیِ بله — «بله‌پی» به‌عنوانِ درگاه، بدونِ رباتِ گفتگو.

از نسخه‌ی ۱.۰.۰، بله دیگر پیام‌رسانِ ربات نیست: هیچ منویی، هیچ پاسخی به چت، هیچ هوش مصنوعی‌ای روی
بله اجرا نمی‌شه. اما متدهای پرداختِ بله (``sendInvoice`` / ``createInvoiceLink`` و رویدادهای
``pre_checkout_query`` و ``successful_payment``) در همان Bot API ربات می‌آیند — پس صاحب فروشگاه
یک رباتِ بله می‌سازد، توکنِ آن را به‌همراه ``provider_token`` به برنامه می‌دهد و آن ربات **فقط**
صورتحساب می‌سازد و پرداخت را تأیید می‌کند.

چرا کلاینتِ دست‌نویس: کتابخونه‌های معروفِ پایتونیِ بله (مثل python-bale-bot) با لایسنس GPL-2.0
انتشار می‌شن و باندل‌کردنشان در exe نهاییِ یک پروژه‌ی MIT دردسرِ لایسنس می‌سازه. پس مثلِ بقیه‌ی
تماس‌های شبکه‌ی این پروژه، JSON روی HTTP خام.

مستندات: https://docs.bale.ai/#پرداخت
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.core.redact import redact

BASE_URL_TEMPLATE = "https://tapi.bale.ai/bot{token}/{method}"
TEST_PROVIDER_TOKEN = "WALLET-TEST-1111111111111111"  # توکنِ آزمایشیِ مستندات؛ پولی کم نمی‌شه

logger = logging.getLogger(__name__)


def _client_error():
    """خطای شبکه‌ی aiohttp؛ دیر-import (عبارتِ `except` در زمانِ اجرا ارزیابی می‌شه)."""
    import aiohttp

    return aiohttp.ClientError


class BaleApiError(Exception):
    """خطای قابل‌نمایش (فارسی) در ارتباط با API پرداختِ بله."""

    def __init__(self, message: str, error_code: Optional[int] = None):
        super().__init__(message)
        self.error_code = error_code

    @property
    def is_auth_error(self) -> bool:
        return self.error_code in (401, 403, 404)


def _error_code(data) -> Optional[int]:
    code = data.get("error_code") if isinstance(data, dict) else None
    return code if isinstance(code, int) and not isinstance(code, bool) else None


@dataclass
class BalePreCheckoutQuery:
    """درست پیش از نهایی‌شدنِ پرداخت می‌رسه — باید زیرِ ۱۰ ثانیه جواب داده بشه.

    بله ``chat_id`` جدا نمی‌ده؛ در چتِ خصوصیِ ربات، ``from_user_id`` همانِ شناسه‌ای است که
    برای فرستادنِ فاکتور لازم است. آن شناسه با شناسهٔ پرداخت‌کننده در ``successful_payment``
    مقایسه می‌شه تا کسی نتونه سفارشِ دیگری را پرداخت/تأیید کند."""

    update_id: int
    query_id: str
    from_user_id: str
    invoice_payload: str
    total_amount: int
    currency: str


@dataclass
class BaleSuccessfulPayment:
    """بعد از پرداختِ واقعی می‌رسه — تنها منبعِ قطعیِ تأیید."""

    update_id: int
    chat_id: str
    from_user_id: str
    invoice_payload: str
    total_amount: int
    currency: str
    telegram_payment_charge_id: str
    provider_payment_charge_id: str


@dataclass
class BalePayCommand:
    """``/start pay_<id>_<code>`` یا ``/pay <id> <code>`` — مسیرِ پشتیبانِ دیپ‌لینک."""

    update_id: int
    chat_id: str
    from_user_id: str
    order_id: int
    code: str


@dataclass
class BalePaymentBatch:
    pre_checkout_queries: list = field(default_factory=list)
    successful_payments: list = field(default_factory=list)
    pay_commands: list = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.pre_checkout_queries or self.successful_payments or self.pay_commands)


_PAY_COMMAND = re.compile(
    r"^\s*/(?:start|pay)(?:@\w+)?\s+(?:pay[_\s-]?)?(\d{1,12})[_\s-]+([A-Za-z0-9]{6,32})\s*$",
    re.IGNORECASE,
)


def parse_pay_command(text: str) -> Optional[tuple]:
    """``(order_id, code)`` اگر پیام فرمانِ پرداخت بود، وگرنه ``None``."""
    match = _PAY_COMMAND.match(text or "")
    return (int(match.group(1)), match.group(2)) if match else None


def is_test_provider_token(token: str) -> bool:
    return (token or "").strip().upper() == TEST_PROVIDER_TOKEN


class BalePayClient:
    def __init__(self, token: str, session: Optional[Any] = None, base_url_template: str = BASE_URL_TEMPLATE):
        """``session`` یک ``aiohttp.ClientSession``ِ ساختهِ‌خودِ تست است؛ تایپِ صریح نمی‌شه
        چون aiohttp دیر-import می‌شه (نام در زمانِ ارزیابیِ annotation وجود ندارد)."""
        self.token = token
        self._session = session
        self._own_session = session is None
        self._base = base_url_template
        self._offset: Optional[int] = None
        self._username: str = ""

    @property
    def bot_username(self) -> str:
        return self._username

    async def _ensure_session(self) -> Any:
        import aiohttp  # noqa: PLC0415 — دیر-import: aiohttp ≈۰.۳ ثانیه از شروعِ برنامه می‌کاهد و فقط برایِ پرداخت لازم است

        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._own_session and self._session is not None and not self._session.closed:
            await self._session.close()

    def _url(self, method: str) -> str:
        return self._base.format(token=self.token, method=method)

    async def _post_json(self, url: str, payload: dict, timeout: float) -> Any:
        """تنها نقطهٔ تماسِ واقعی با شبکه — در تست‌ها جایگزین می‌شه."""
        import aiohttp  # noqa: PLC0415 — دیر-import (به همون دلیلِ _ensure_session)

        session = await self._ensure_session()
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            return await resp.json(content_type=None)

    async def _call(self, method: str, payload: Optional[dict] = None, timeout: float = 20.0) -> Any:
        try:
            data = await self._post_json(self._url(method), payload or {}, timeout)
        except asyncio.TimeoutError as exc:
            raise BaleApiError("اتصال به سرور بله با تایم‌اوت مواجه شد.") from exc
        except _client_error() as exc:
            # بعضی خطاهای aiohttp آدرسِ کامل (با توکن) را در متنشان دارند — همیشه پاک می‌شه
            raise BaleApiError(f"اتصال به سرور بله ناموفق بود: {redact(str(exc), self.token)}") from exc
        except ValueError as exc:  # پاسخِ غیر JSON (مثلاً صفحهٔ HTML خطا)
            raise BaleApiError("پاسخ سرور بله قابل‌فهم نبود (غیر JSON).") from exc

        if not isinstance(data, dict):
            raise BaleApiError("پاسخ غیرمنتظره از بله دریافت شد.")
        if not data.get("ok", False):
            description = redact(str(data.get("description", data)), self.token)
            raise BaleApiError(f"بله خطا برگردوند: {description}", error_code=_error_code(data))
        return data.get("result")

    # ------------------------------------------------------------------ هویتِ ربات

    async def get_me(self) -> dict:
        result = await self._call("getMe", timeout=15.0)
        if not isinstance(result, dict) or "id" not in result:
            raise BaleApiError("پاسخ getMe فرمت غیرمنتظره‌ای داشت — توکن را بررسی کنید.")
        self._username = str(result.get("username") or "")
        return result

    # ------------------------------------------------------------------ ساختنِ پرداخت

    async def create_invoice_link(
        self,
        title: str,
        description: str,
        payload: str,
        provider_token: str,
        prices: list,
        photo_url: str = "",
        need_name: bool = False,
        need_phone_number: bool = False,
        need_email: bool = False,
    ) -> str:
        """لینک/شناسهٔ پرداخت می‌سازد (``createInvoiceLink``) — نیازی به ``chat_id`` ندارد،
        پس مشتریِ تلگرامی با یک کلیک مستقیم واردِ پرداختِ بله می‌شه.

        خروجی طبقِ مستندات یک رشته است (مثلاً ``https://bale.ai/pay/…``). اگر بله چیزی
        غیر از یک آدرسِ http برگرداند، همان رشته برمی‌گرده و مسئولِ مسیر تصمیم می‌گیره
        (فاکتور بومی/دیپ‌لینک پشتیبان)."""
        body = {
            "title": title[:32],
            "description": description[:255],
            "payload": payload[:128],
            "provider_token": provider_token,
            "currency": "IRR",  # ریال — نه تومان، نه IRT
            "prices": [{"label": str(label)[:32], "amount": int(amount)} for label, amount in prices],
            "need_name": need_name,
            "need_phone_number": need_phone_number,
            "need_email": need_email,
        }
        if photo_url:
            body["photo_url"] = photo_url
        result = await self._call("createInvoiceLink", body, timeout=20.0)
        if isinstance(result, dict):
            result = result.get("url") or result.get("invoice_link") or ""
        return str(result or "").strip()

    async def send_invoice(self, chat_id: str, title: str, description: str, payload: str, provider_token: str, prices: list) -> None:
        """فاکتورِ بومی داخلِ چتِ بله — مسیرِ پشتیبان وقتی لینکِ مستقیم ساخته نمی‌شه."""
        await self._call(
            "sendInvoice",
            {
                "chat_id": chat_id,
                "title": title[:32],
                "description": description[:255],
                "payload": payload[:128],
                "provider_token": provider_token,
                "currency": "IRR",
                "prices": [{"label": str(label)[:32], "amount": int(amount)} for label, amount in prices],
            },
            timeout=20.0,
        )

    async def answer_pre_checkout_query(self, query_id: str, ok: bool, error_message: str = "") -> None:
        """عمداً مهلتش ۸ ثانیه است: بله حداکثر ۱۰ ثانیه صبر می‌کند و بعد پرداخت را لغو می‌کند."""
        payload: dict = {"pre_checkout_query_id": query_id, "ok": bool(ok)}
        if not ok and error_message:
            payload["error_message"] = error_message[:200]
        await self._call("answerPreCheckoutQuery", payload, timeout=8.0)

    async def send_text(self, chat_id: str, text: str) -> None:
        """تک‌راسته‌ی پیام‌هایِ این ربات: پاسخِ فرمانِ پرداخت. (رباتِ بله با کسی
        حرف نمی‌زند؛ هر چیز دیگری باید بیرونِ این کلاینت تصمیم گرفته بشه.)"""
        await self._call("sendMessage", {"chat_id": chat_id, "text": (text or "")[:3500]}, timeout=20.0)

    async def inquire_transaction(self, transaction_id: str) -> dict:
        """استعلامِ نهاییِ تراکنش (توصیهٔ مستندات برای جلوگیری از تقلب)."""
        result = await self._call("inquireTransaction", {"transaction_id": transaction_id}, timeout=15.0)
        if not isinstance(result, dict):
            raise BaleApiError("پاسخ استعلام تراکنش فرمت غیرمنتظره‌ای داشت.")
        return result

    # ------------------------------------------------------------------ رویدادها

    async def get_updates(self, timeout: int = 15) -> BalePaymentBatch:
        """فقط رویدادهایِ پرداخت (و فرمانِ /pay پشتیبان) را برمی‌گرداند.

        پیام‌هایِ عادیِ چتِ این ربات عمداً نادیده گرفته می‌شن: رباتِ بله با کسی
        حرف نمی‌زنه. offset حتی برای آپدیت‌های بی‌ربط جلو می‌ره، وگرنه بله همان‌ها را
        دوباره و دوباره می‌فرسته."""
        payload: dict = {"timeout": timeout}
        if self._offset is not None:
            payload["offset"] = self._offset
        result = await self._call("getUpdates", payload, timeout=timeout + 15.0)
        batch = BalePaymentBatch()
        if not isinstance(result, list):
            return batch

        for update in result:
            if not isinstance(update, dict):
                continue
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                self._offset = update_id + 1
            uid = update_id if isinstance(update_id, int) else -1

            pre_checkout = update.get("pre_checkout_query")
            if isinstance(pre_checkout, dict):
                sender = pre_checkout.get("from") or {}
                if pre_checkout.get("id") is not None and sender.get("id") is not None:
                    batch.pre_checkout_queries.append(
                        BalePreCheckoutQuery(
                            update_id=uid,
                            query_id=str(pre_checkout["id"]),
                            from_user_id=str(sender["id"]),
                            invoice_payload=str(pre_checkout.get("invoice_payload", "")),
                            total_amount=int(pre_checkout.get("total_amount") or 0),
                            currency=str(pre_checkout.get("currency", "IRR")),
                        )
                    )
                continue

            message = update.get("message")
            if not isinstance(message, dict):
                continue

            payment = message.get("successful_payment")
            chat = message.get("chat") or {}
            sender = message.get("from") or {}
            if isinstance(payment, dict) and chat.get("id") is not None:
                batch.successful_payments.append(
                    BaleSuccessfulPayment(
                        update_id=uid,
                        chat_id=str(chat["id"]),
                        from_user_id=str(sender.get("id", chat["id"])),
                        invoice_payload=str(payment.get("invoice_payload", "")),
                        total_amount=int(payment.get("total_amount") or 0),
                        currency=str(payment.get("currency", "IRR")),
                        telegram_payment_charge_id=str(payment.get("telegram_payment_charge_id", "")),
                        provider_payment_charge_id=str(payment.get("provider_payment_charge_id", "")),
                    )
                )
                continue

            text = str(message.get("text") or "")
            parsed = parse_pay_command(text)
            if parsed and chat.get("id") is not None:
                batch.pay_commands.append(
                    BalePayCommand(
                        update_id=uid,
                        chat_id=str(chat["id"]),
                        from_user_id=str(sender.get("id", chat["id"])),
                        order_id=parsed[0],
                        code=parsed[1],
                    )
                )
        return batch
