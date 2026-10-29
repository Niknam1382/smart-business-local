"""
کلاینت درگاه زرین‌پال (API نسخه ۴، JSON) — طبق مستندات رسمی:

- ساخت پرداخت: ``POST {base}/pg/v4/payment/request.json`` با
  ``merchant_id, amount (ریال), callback_url, description`` ← ``data.authority``
- لینک پرداخت: ``{base}/pg/StartPay/{authority}``
- تاییدیه: ``POST {base}/pg/v4/payment/verify.json`` با
  ``merchant_id, amount, authority`` ← ``data.code`` برابر ۱۰۰ (پرداخت شد) یا ۱۰۱
  (قبلاً تایید شده)؛ در غیر این صورت ``errors``

این برنامه روی سیستم خودِ صاحب فروشگاه اجرا می‌شه و آدرسِ عمومی نداره که زرین‌پال
بعد از پرداخت بهش برگرده؛ پس نتیجه‌ی پرداخت با **استعلامِ دوره‌ایِ verify**
فهمیده می‌شه (``poll`` توی PaymentService)، نه با callback. verify روی
authorityِ پرداخت‌نشده بی‌ضرره (خطای «پرداخت ناموفق/نامعتبر» برمی‌گردونه و
پرداخت مشتری رو خراب نمی‌کنه).

پولی از این برنامه رد نمی‌شه: مرچنت‌کد مالِ صاحب فروشگاهه و پول مستقیم به
حساب زرین‌پالِ خودش می‌ره.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import aiohttp

PROD_BASE = "https://payment.zarinpal.com"
SANDBOX_BASE = "https://sandbox.zarinpal.com"

_MERCHANT_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

# کدهای خطایی که یعنی «این authority هیچ‌وقت پرداخت‌شده نمی‌شه»؛ استعلام براش بی‌فایده‌ست
_FATAL_VERIFY_CODES = {-50, -53, -54}

_KNOWN_ERRORS = {
    -9: "اطلاعاتِ ارسالی به زرین‌پال معتبر نیست (مرچنت‌کد یا مبلغ رو چک کن).",
    -10: "مرچنت‌کد یا آی‌پیِ پذیرنده توی زرین‌پال معتبر نیست.",
    -11: "درگاهِ این مرچنت‌کد توی زرین‌پال فعال نیست.",
    -12: "تعداد درخواست‌ها به زرین‌پال زیاد بوده؛ کمی بعد دوباره امتحان کن.",
    -15: "درگاهِ این مرچنت‌کد توی زرین‌پال معلق شده.",
}


class ZarinpalError(Exception):
    """خطای قابل‌نمایش (پیام فارسی) از ساخت/استعلام پرداخت زرین‌پال."""


def is_valid_merchant_id(value: str) -> bool:
    return bool(_MERCHANT_RE.match((value or "").strip()))


@dataclass
class ZarinpalPayment:
    authority: str
    url: str


@dataclass
class ZarinpalVerify:
    paid: bool
    already_verified: bool = False
    ref_id: str = ""
    code: int = 0
    message: str = ""
    fatal: bool = False  # True = دیگه استعلامش نکن


def _errors(payload: dict) -> dict:
    errors = payload.get("errors") if isinstance(payload, dict) else None
    return errors if isinstance(errors, dict) else {}


class ZarinpalClient:
    def __init__(self, merchant_id: str, sandbox: bool = False, base_url: str = "", timeout: float = 15.0) -> None:
        self.merchant_id = (merchant_id or "").strip()
        self.base_url = (base_url or (SANDBOX_BASE if sandbox else PROD_BASE)).rstrip("/")
        self.timeout = timeout

    def start_url(self, authority: str) -> str:
        return f"{self.base_url}/pg/StartPay/{authority}"

    async def _post(self, path: str, body: dict) -> dict:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                async with session.post(f"{self.base_url}{path}", json=body, headers={"accept": "application/json"}) as resp:
                    return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            raise ZarinpalError("ارتباط با زرین‌پال برقرار نشد؛ اینترنت رو چک کن و دوباره امتحان کن.") from exc

    async def create_payment(
        self, amount_irr: int, callback_url: str, description: str, mobile: str = ""
    ) -> ZarinpalPayment:
        body = {
            "merchant_id": self.merchant_id,
            "amount": int(amount_irr),
            "currency": "IRR",
            "callback_url": callback_url,
            "description": (description or "پرداخت سفارش")[:500],
        }
        if mobile:
            body["metadata"] = {"mobile": mobile}
        payload = await self._post("/pg/v4/payment/request.json", body)
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, dict) and data.get("code") == 100 and data.get("authority"):
            authority = str(data["authority"])
            return ZarinpalPayment(authority=authority, url=self.start_url(authority))
        err = _errors(payload)
        code = err.get("code")
        known = _KNOWN_ERRORS.get(code) if isinstance(code, int) else None
        detail = known or f"زرین‌پال خطا داد (کد {code}): {err.get('message', 'نامشخص')}"
        raise ZarinpalError(detail)

    async def verify(self, authority: str, amount_irr: int) -> ZarinpalVerify:
        payload = await self._post(
            "/pg/v4/payment/verify.json",
            {"merchant_id": self.merchant_id, "amount": int(amount_irr), "authority": authority},
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, dict) and data.get("code") in (100, 101):
            return ZarinpalVerify(
                paid=True,
                already_verified=data.get("code") == 101,
                ref_id=str(data.get("ref_id", "")),
                code=int(data["code"]),
                message=str(data.get("message", "")),
            )
        err = _errors(payload)
        code = err.get("code") if isinstance(err.get("code"), int) else 0
        return ZarinpalVerify(paid=False, code=code, message=str(err.get("message", "")), fatal=code in _FATAL_VERIFY_CODES)
