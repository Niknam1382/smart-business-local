"""
کلاینت سبک برای Bot API بله — فقط سه متدی که برای این پروژه لازمه: getMe
(تست اتصال)، getUpdates (پولینگ طولانی)، sendMessage.

بله یه Bot API شبیه به تلگرام داره (همون شکل JSON، آدرس پایه‌ی
``https://tapi.bale.ai/bot<TOKEN>/<METHOD>``). کتابخونه‌ی معروف پایتونی
براش («python-bale-bot») با لایسنس GPL-2.0 منتشر شده، در حالی که این پروژه
با لایسنس MIT منتشر می‌شه (README.md) — باندل‌کردن یه وابستگی GPL توی exe
نهایی (که با PyInstaller توی یه فایل باینری واحد بسته‌بندی می‌شه) می‌تونه
از نظر لایسنس مشکل‌ساز بشه. برای همینه که — دقیقاً مثل ApiEngine که به‌جای
پکیج ``openai`` از ``urllib`` خام استفاده می‌کنه — این‌جا هم یه کلاینت
مینیمال خودمون رو می‌نویسیم؛ API بله به‌قدری ساده‌ست (JSON روی HTTP) که به
کتابخونه‌ی جداگانه نیازی نیست.

نکته‌ی مهم برای تست: اتصال واقعی به ``tapi.bale.ai`` رو نمی‌شه از محیط
توسعه/CI تأیید کرد (نیاز به توکن واقعی ربات داره) — طبق قرارداد MASTER_PROMPT
این بخش با «بساز یه ربات واقعی، توکن بده» توسط خودِ کاربر تست می‌شه. تست‌های
خودکار با یه سرور جعلی Bot API روی loopback (tests/fake_servers.py) و
``base_url_template`` قابل‌تنظیم انجام می‌شن؛ حتی مسیر واقعی aiohttp تست می‌شه.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import aiohttp

from app.core.redact import redact

BASE_URL_TEMPLATE = "https://tapi.bale.ai/bot{token}/{method}"
_MAX_MESSAGE_LEN = 3500  # محافظه‌کارانه؛ محدودیت واقعی بله مثل تلگرام (۴۰۹۶) به نظر می‌رسه


class BaleApiError(Exception):
    """خطای قابل‌نمایش (فارسی) برای هر مشکلی در ارتباط با API بله.

    ``error_code`` فقط وقتی پر می‌شه که خودِ بله ``ok=false`` با کد خطا برگردونده
    باشه (نه مشکل شبکه)؛ آداپتور با ``is_auth_error`` تشخیص می‌ده توکن نامعتبره
    و تلاش دوباره فایده‌ای نداره."""

    def __init__(self, message: str, error_code: Optional[int] = None, retry_after: Optional[float] = None):
        super().__init__(message)
        self.error_code = error_code
        self.retry_after = retry_after  # ثانیه؛ فقط وقتی بله (۴۲۹) خودش گفته باشد (N7: ارسالِ همگانی صبر می‌کنه)

    @property
    def is_auth_error(self) -> bool:
        return self.error_code in (401, 403, 404)


from app.core.adapter_common import MEDIA_KINDS, normalize_member_status, with_media_note  # noqa: E402


def _error_code(data) -> Optional[int]:
    code = data.get("error_code") if isinstance(data, dict) else None
    return code if isinstance(code, int) and not isinstance(code, bool) else None


def _retry_after(data) -> Optional[float]:
    params = data.get("parameters") if isinstance(data, dict) else None
    value = params.get("retry_after") if isinstance(params, dict) else None
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None

logger = logging.getLogger(__name__)


@dataclass
class BaleIncomingMessage:
    update_id: int
    chat_id: str
    text: str
    from_user_id: str
    from_display_name: str
    callback_data: str = ""  # کلیکِ دکمه‌ی شیشه‌ای (callback_query)؛ ``text`` در این حالت خالیه
    callback_id: str = ""
    message_id: str = ""
    language_code: str = ""
    phone: str = ""  # مخاطبِ اشتراک‌گذاری‌شده
    reply_to_id: str = ""
    username: str = ""  # N12 (CRM): فقط چیزی که بله برای فرستنده می‌فرسته
    first_name: str = ""
    last_name: str = ""


@dataclass
class BalePreCheckoutQuery:
    """پیش از نهایی‌شدن پرداخت بله‌پی می‌رسه — باید ظرف ۱۰ ثانیه جواب داده بشه.

    بله (مثل تلگرام) ``chat_id`` جدا نمی‌ده؛ توی چت خصوصی با ربات،
    ``from_user_id`` همون شناسه‌ایه که برای جواب/پیام به مشتری لازمه."""

    update_id: int
    query_id: str
    from_user_id: str
    invoice_payload: str
    total_amount: int
    currency: str


@dataclass
class BaleSuccessfulPayment:
    """بعد از نهایی‌شدن واقعی پرداخت می‌رسه — تنها منبع قطعی برای تایید موفقیت."""

    update_id: int
    chat_id: str
    invoice_payload: str
    total_amount: int
    currency: str
    telegram_payment_charge_id: str
    provider_payment_charge_id: str


@dataclass
class BaleUpdateBatch:
    """خروجی ``get_updates`` — سه نوع رویداد ممکنه توی یه poll با هم بیان."""

    messages: list = field(default_factory=list)  # list[BaleIncomingMessage]
    pre_checkout_queries: list = field(default_factory=list)  # list[BalePreCheckoutQuery]
    successful_payments: list = field(default_factory=list)  # list[BaleSuccessfulPayment]

    def __bool__(self) -> bool:
        return bool(self.messages or self.pre_checkout_queries or self.successful_payments)


class BaleClient:
    def __init__(
        self,
        token: str,
        session: Optional[aiohttp.ClientSession] = None,
        base_url_template: str = BASE_URL_TEMPLATE,
    ):
        self.token = token
        self._session = session
        self._own_session = session is None
        self._base_url_template = base_url_template
        self._offset: Optional[int] = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._own_session and self._session is not None and not self._session.closed:
            await self._session.close()

    def _url(self, method: str) -> str:
        return self._base_url_template.format(token=self.token, method=method)

    async def _post_json(self, url: str, payload: dict, timeout: float) -> Any:
        """تنها نقطه‌ی تماس واقعی با شبکه — برای تست‌های واحد جایگزین می‌شه."""
        session = await self._ensure_session()
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            return await resp.json(content_type=None)

    async def _call(self, method: str, payload: Optional[dict] = None, timeout: float = 20.0) -> Any:
        try:
            data = await self._post_json(self._url(method), payload or {}, timeout)
        except asyncio.TimeoutError as exc:
            raise BaleApiError("اتصال به سرور بله با تایم‌اوت مواجه شد.") from exc
        except aiohttp.ClientError as exc:
            # پیام بعضی خطاهای aiohttp آدرس کامل (شامل توکن) رو داره — حتماً پاک می‌شه.
            raise BaleApiError(
                f"اتصال به سرور بله ناموفق بود: {redact(str(exc), self.token)}"
            ) from exc
        except ValueError as exc:  # json.JSONDecodeError — مثلاً صفحه‌ی HTML خطای ۵۰۲
            raise BaleApiError("پاسخ سرور بله قابل‌فهم نبود (غیر JSON).") from exc

        if not isinstance(data, dict):
            raise BaleApiError("پاسخ غیرمنتظره از بله دریافت شد.")
        if not data.get("ok", False):
            description = redact(str(data.get("description", data)), self.token)
            raise BaleApiError(f"بله خطا برگردوند: {description}", error_code=_error_code(data), retry_after=_retry_after(data))
        return data.get("result")

    async def get_my_short_description(self) -> str:
        """⚠️ در مستنداتِ بله تأیید نشده (N17)؛ ``BaleProfileClient`` خطای «متد نیست» را به «پشتیبانی‌نشده» تبدیل می‌کنه."""
        result = await self._call("getMyShortDescription", {}, timeout=15.0)
        if isinstance(result, dict):
            return str(result.get("short_description") or "")
        return result if isinstance(result, str) else ""

    async def set_my_short_description(self, text: str) -> None:
        await self._call("setMyShortDescription", {"short_description": text}, timeout=15.0)

    async def get_me(self) -> dict:
        result = await self._call("getMe", timeout=15.0)
        if not isinstance(result, dict) or "id" not in result:
            raise BaleApiError("پاسخ getMe فرمت غیرمنتظره‌ای داشت — توکن رو بررسی کنید.")
        return result

    async def get_chat_member(self, chat_id: str, user_id: str) -> str:
        """وضعیتِ عضویتِ یک کاربر در یک کانال/گروه (N13): creator/administrator/member/left/kicked.
        ⚠️ رفتارِ دقیقِ بله (مثلاً پشتیبانی از @username به‌جای شناسه‌ی عددی) آفلاین قابل‌تأیید نیست؛ هر خطا بالا می‌ره
        و دروازه‌ی عضویت fail-open می‌شه (مشتری قفل نمی‌شه، مالک خبردار می‌شه)."""
        def number(value):
            text = str(value)
            return int(text) if text.lstrip("-").isdigit() else text

        result = await self._call("getChatMember", {"chat_id": number(chat_id), "user_id": number(user_id)}, timeout=15.0)
        if not isinstance(result, dict) or not result.get("status"):
            raise BaleApiError("پاسخ getChatMember فرمت غیرمنتظره‌ای داشت.")
        return normalize_member_status(result.get("status"), result.get("is_member"))

    async def send_message(self, chat_id: str, text: str, buttons: Optional[list] = None) -> None:
        """``buttons``: لیستی از (برچسب, url) — به‌صورت دکمه‌ی شیشه‌ای (inline) زیرِ
        آخرین تکه‌ی پیام می‌چسبه. دکمه‌ی url مطمئن‌ترین راه رسوندنِ لینکه: بله
        فرمت‌بندیِ markdown (مثل ``_x_``) رو توی متن پردازش می‌کنه و ممکنه یه
        URLِ دارای underscore رو خراب کنه، ولی آدرسِ دکمه دست‌نخورده می‌مونه."""
        chunks = _split_text(text, _MAX_MESSAGE_LEN)
        for i, chunk in enumerate(chunks):
            payload: dict = {"chat_id": chat_id, "text": chunk}
            if buttons and i == len(chunks) - 1:
                payload["reply_markup"] = {"inline_keyboard": [[{"text": label, "url": url}] for label, url in buttons]}
            await self._call("sendMessage", payload, timeout=20.0)

    async def get_updates(self, timeout: int = 15) -> BaleUpdateBatch:
        payload: dict = {"timeout": timeout}
        if self._offset is not None:
            payload["offset"] = self._offset
        # مهلت HTTP باید از long-poll سمت سرور بلندتر باشه، وگرنه کلاینت قبل از
        # جواب سرور قطع می‌کنه.
        result = await self._call("getUpdates", payload, timeout=timeout + 15.0)
        batch = BaleUpdateBatch()
        if not isinstance(result, list):
            return batch

        for update in result:
            if not isinstance(update, dict):
                continue
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                # offset رو حتی برای آپدیت‌های بی‌ربط هم جلو می‌بریم، وگرنه بله
                # همون‌ها رو دوباره و دوباره برمی‌گردونه.
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
                            invoice_payload=pre_checkout.get("invoice_payload", ""),
                            total_amount=int(pre_checkout.get("total_amount") or 0),
                            currency=pre_checkout.get("currency", "IRR"),
                        )
                    )
                continue  # یه آپدیت فقط یه نوعه؛ لازم نیست بقیه رو هم چک کنیم

            callback = update.get("callback_query")
            if isinstance(callback, dict):
                cb_sender = callback.get("from") or {}
                cb_message = callback.get("message") or {}
                cb_chat = cb_message.get("chat") or {}
                chat_id = cb_chat.get("id", cb_sender.get("id"))
                data = callback.get("data")
                if callback.get("id") is not None and chat_id is not None and isinstance(data, str):
                    batch.messages.append(
                        BaleIncomingMessage(
                            update_id=uid,
                            chat_id=str(chat_id),
                            text="",
                            from_user_id=str(cb_sender.get("id", chat_id)),
                            from_display_name=" ".join(p for p in [cb_sender.get("first_name"), cb_sender.get("last_name")] if p)
                            or cb_sender.get("username") or str(chat_id),
                            callback_data=data,
                            callback_id=str(callback["id"]),
                            message_id=str(cb_message.get("message_id", "")),
                            language_code=str(cb_sender.get("language_code") or ""),
                            username=str(cb_sender.get("username") or ""),
                            first_name=str(cb_sender.get("first_name") or ""),
                            last_name=str(cb_sender.get("last_name") or ""),
                        )
                    )
                continue

            message = update.get("message")
            if not isinstance(message, dict):
                continue

            successful_payment = message.get("successful_payment")
            chat = message.get("chat") or {}
            if isinstance(successful_payment, dict) and chat.get("id") is not None:
                batch.successful_payments.append(
                    BaleSuccessfulPayment(
                        update_id=uid,
                        chat_id=str(chat["id"]),
                        invoice_payload=successful_payment.get("invoice_payload", ""),
                        total_amount=int(successful_payment.get("total_amount") or 0),
                        currency=successful_payment.get("currency", "IRR"),
                        telegram_payment_charge_id=successful_payment.get("telegram_payment_charge_id", ""),
                        provider_payment_charge_id=successful_payment.get("provider_payment_charge_id", ""),
                    )
                )
                continue

            media = next((label for key, label in MEDIA_KINDS if message.get(key)), "")
            text = with_media_note(message.get("text") or message.get("caption") or "", media)
            sender = message.get("from") or {}
            contact = message.get("contact") if isinstance(message.get("contact"), dict) else {}
            phone = str(contact.get("phone_number") or "")
            location = message.get("location") if isinstance(message.get("location"), dict) else {}
            if not text and location.get("latitude") is not None and location.get("longitude") is not None:
                text = f"{location['latitude']},{location['longitude']}"
            if (not text and not phone) or chat.get("id") is None:
                continue
            display = (
                " ".join(part for part in [sender.get("first_name"), sender.get("last_name")] if part)
                or sender.get("username")
                or str(chat.get("id"))
            )
            batch.messages.append(
                BaleIncomingMessage(
                    update_id=uid,
                    chat_id=str(chat["id"]),
                    text=text,
                    from_user_id=str(sender.get("id", chat["id"])),
                    from_display_name=display,
                    language_code=str(sender.get("language_code") or ""),
                    phone=phone,
                    message_id=str(message.get("message_id", "")),
                    reply_to_id=str((message.get("reply_to_message") or {}).get("message_id", "")),
                    username=str(sender.get("username") or ""),
                    first_name=str(sender.get("first_name") or ""),
                    last_name=str(sender.get("last_name") or ""),
                )
            )
        return batch

    # ------------------------------------------- رابطِ دکمه‌ای (R1): ارسال/ویرایش/پاسخ

    @staticmethod
    def _message_id(result: Any) -> str:
        return str(result.get("message_id", "")) if isinstance(result, dict) else ""

    async def send_with_markup(self, chat_id: str, text: str, markup: Optional[dict] = None) -> str:
        """یک پیامِ متنی (با کیبوردِ شیشه‌ای یا پایدار)؛ ``message_id`` رو برمی‌گردونه."""
        payload: dict = {"chat_id": chat_id, "text": text[:_MAX_MESSAGE_LEN]}
        if markup:
            payload["reply_markup"] = markup
        return self._message_id(await self._call("sendMessage", payload))

    async def _post_multipart(self, url: str, fields: dict, file_field: str, path: str, timeout: float) -> Any:
        session = await self._ensure_session()
        form = aiohttp.FormData()
        for key, value in fields.items():
            form.add_field(key, value if isinstance(value, str) else str(value))
        with open(path, "rb") as handle:
            form.add_field(file_field, handle, filename=path.rsplit("/", 1)[-1])
            async with session.post(url, data=form, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                return await resp.json(content_type=None)

    async def _send_media(self, method: str, field_name: str, chat_id: str, media: str, caption: str, markup: Optional[dict]) -> str:
        import json as _json
        import os as _os

        fields: dict = {"chat_id": chat_id}
        if caption:
            fields["caption"] = caption[:1000]
        if markup:
            fields["reply_markup"] = _json.dumps(markup, ensure_ascii=False)
        if _os.path.isfile(media):  # فایلِ محلی ← آپلودِ multipart
            try:
                data = await self._post_multipart(self._url(method), fields, field_name, media, 40.0)
            except asyncio.TimeoutError as exc:
                raise BaleApiError("اتصال به سرور بله با تایم‌اوت مواجه شد.") from exc
            except (aiohttp.ClientError, OSError) as exc:
                raise BaleApiError(f"ارسالِ فایل به بله ناموفق بود: {redact(str(exc), self.token)}") from exc
            if not isinstance(data, dict) or not data.get("ok", False):
                raise BaleApiError(
                    f"بله خطا برگردوند: {redact(str((data or {}).get('description', data)), self.token)}",
                    error_code=_error_code(data), retry_after=_retry_after(data),
                )
            return self._message_id(data.get("result"))
        payload: dict = {"chat_id": chat_id, field_name: media}  # URL یا file_id
        if caption:
            payload["caption"] = caption[:1000]
        if markup:
            payload["reply_markup"] = markup
        return self._message_id(await self._call(method, payload, timeout=40.0))

    async def send_photo(self, chat_id: str, photo: str, caption: str = "", markup: Optional[dict] = None) -> str:
        return await self._send_media("sendPhoto", "photo", chat_id, photo, caption, markup)

    async def send_document(self, chat_id: str, document: str, caption: str = "") -> str:
        return await self._send_media("sendDocument", "document", chat_id, document, caption, None)

    async def send_contact(self, chat_id: str, phone_number: str, first_name: str) -> str:
        return self._message_id(
            await self._call("sendContact", {"chat_id": chat_id, "phone_number": phone_number, "first_name": first_name or "-"})
        )

    async def edit_message_text(self, chat_id: str, message_id: str, text: str, markup: Optional[dict] = None) -> None:
        payload: dict = {"chat_id": chat_id, "message_id": int(message_id), "text": text[:_MAX_MESSAGE_LEN]}
        if markup:
            payload["reply_markup"] = markup
        await self._call("editMessageText", payload)

    async def edit_message_reply_markup(self, chat_id: str, message_id: str, markup: Optional[dict]) -> None:
        payload: dict = {"chat_id": chat_id, "message_id": int(message_id)}
        if markup:
            payload["reply_markup"] = markup
        await self._call("editMessageReplyMarkup", payload)

    async def answer_callback_query(self, callback_id: str, text: str = "", alert: bool = False) -> None:
        payload: dict = {"callback_query_id": callback_id}
        if text:
            payload["text"] = text[:200]
        if alert:
            payload["show_alert"] = True
        await self._call("answerCallbackQuery", payload, timeout=10.0)

    async def delete_message(self, chat_id: str, message_id: str) -> None:
        await self._call("deleteMessage", {"chat_id": chat_id, "message_id": int(message_id)}, timeout=10.0)

    # ------------------------------------------------------------- پرداخت

    async def send_invoice(
        self,
        chat_id: str,
        title: str,
        description: str,
        payload: str,
        provider_token: str,
        prices: list,
    ) -> None:
        """فاکتورِ پرداختِ بومیِ بله، مستقیم توی چتِ مشتری (روشِ رسمیِ sendInvoice).
        فالبک وقتی ساختنِ لینک شکست می‌خوره و مشتری توی خودِ بله‌ست."""
        await self._call(
            "sendInvoice",
            {
                "chat_id": chat_id,
                "title": title[:32],
                "description": description[:255],
                "payload": payload,
                "provider_token": provider_token,
                "currency": "IRR",
                "prices": [{"label": label, "amount": amount} for label, amount in prices],
            },
            timeout=20.0,
        )

    async def answer_pre_checkout_query(self, query_id: str, ok: bool, error_message: str = "") -> None:
        """باید خیلی سریع صدا زده بشه — بله حداکثر ۱۰ ثانیه صبر می‌کنه؛ مهلت
        این تماس عمداً کوتاهه (۸ ثانیه) تا وقت کافی برای رسیدن پاسخ بمونه."""
        payload: dict = {"pre_checkout_query_id": query_id, "ok": ok}
        if not ok and error_message:
            payload["error_message"] = error_message
        await self._call("answerPreCheckoutQuery", payload, timeout=8.0)

    async def inquire_transaction(self, transaction_id: str) -> dict:
        result = await self._call("inquireTransaction", {"transaction_id": transaction_id}, timeout=15.0)
        if not isinstance(result, dict):
            raise BaleApiError("پاسخ استعلام تراکنش فرمت غیرمنتظره‌ای داشت.")
        return result


def _split_text(text: str, max_len: int) -> list[str]:
    if len(text) <= max_len:
        return [text] if text else [""]
    return [text[i : i + max_len] for i in range(0, len(text), max_len)]
