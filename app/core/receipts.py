"""
خواندنِ متنِ «رسیدِ کارت‌به‌کارت» — بدونِ OCR و بدونِ اینترنت.

تصمیمِ محصولی (۱.۰.۰): تأییدِ پرداختِ کارت‌به‌کارت **همیشه دستی** است. کارِ برنامه این است که
رسید را از مشتری بگیرد، مبلغ/کد رهگیری/۴ رقم آخرِ کارت را از متنِ آن دربیاورد، با مبلغِ سفارش
مقایسه کند و **فوری** به مالک و مدیرها هشدار بدهد تا بروند حساب را چک کنند. پس این ماژول
«راهنمایِ چشمی» است، نه داورِ نهایی: هیچ‌جا سفارشی را تأیید نمی‌کند.

چرا این‌قدر محافظه‌کار: رسیدهای بانکیِ ایرانی قالبِ یکسانی ندارند (دستگاهِ خودپرداز، همراه‌بانک،
اپ بانک، فیشِ hand-written). پس هر عددی که شبیه مبلغ است جمع می‌شود و «مطابقت» فقط وقتی اعلام
می‌شود که عدد **دقیقاً** با مبلغِ سفارش (یا ده‌ برابرش، یعنی تومان) بخواند. هیچ تلورانسِ تصاعدی
نیست: مبلغِ کمتر یعنی مشتری کم واریز کرده و مالک باید ببینه.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

# «۱۲,۵۰۰,۰۰۰» یا «۱۲۵۰۰۰۰۰» یا «۱۲ ۵۰۰ ۰۰۰» — همه یک عددند
_NUMBER_RUN = re.compile(r"\d{1,3}(?:[ ,.\u200c\u00a0]\d{3})+(?![\d])|\d{2,14}")
_CARD_RUN = re.compile(r"(?:\d[ -]?){15}\d")
_TRACE_HINT = re.compile(
    r"(?:کد\s*(?:پیگیری|رهگیری|تراکنش|رجیستری)|شماره\s*(?:پیگیری|تراکنش|رجیستری|مرجع)|"
    r"trace(?:\s*code)?|reference(?:\s*no)?|rrn|auth(?:orization)?\s*(?:code|no)?)[^\d]{0,14}(\d{5,20})",
    re.IGNORECASE,
)
_LAST4_HINT = re.compile(r"[*\u2605]{2,10}\s*(\d{4})")
_DATE_HINT = re.compile(r"(\d{1,4}[/-]\d{1,2}[/-]\d{1,4}(?:[ T]\d{1,2}[:.]\d{2}(?::\d{2})?)?)")

MIN_AMOUNT = 100  # زیر این، عدد مبلغ نیست (ساعت، شمارهٔ شبا، کد ملی و…)


def normalize_digits(text: str) -> str:
    return (text or "").translate(_DIGIT_MAP)


@dataclass
class ReceiptInfo:
    amounts: list = field(default_factory=list)  # همهٔ اعدادِ شبیه مبلغ، مرتب و یکتا
    trace: str = ""
    card_last4: str = ""
    date_text: str = ""
    matched_amount: int = 0  # عددی که دقیقاً با مبلغ سفارش (یا تومانِ آن) می‌خونه
    nearest_amount: int = 0  # نزدیک‌ترین عدد، برای وقتی مطابقتی نیست
    state: str = "none"  # amount_ok | amount_mismatch | none

    @property
    def has_anything(self) -> bool:
        return bool(self.amounts or self.trace or self.card_last4 or self.date_text)

    def summary(self, order_amount_irr: int) -> str:
        """یک خطِ فارسی برای پیامِ مالک و صفحهٔ سفارش‌ها."""
        if self.state == "amount_ok":
            return f"مبلغِ {self.matched_amount:,} ریال با مبلغ سفارش می‌خونه."
        if self.state == "amount_mismatch":
            diff = order_amount_irr - self.nearest_amount
            word = "کمتر" if diff > 0 else "بیشتر"
            return f"مبلغِ رسید ({self.nearest_amount:,}) {abs(diff):,} ریال {word} از مبلغ سفارشه — چک کن."
        if self.amounts:
            return "مبلغِ مشخصی در رسید پیدا نشد؛ عددهای یافت‌شده: " + "، ".join(f"{a:,}" for a in self.amounts[:6])
        return "متنِ رسید عددی نداشت؛ خودِ متن را بخوان."


def _card_spans(text: str) -> list:
    return [(m.start(), m.end()) for m in _CARD_RUN.finditer(text)]


def parse_receipt(text: str, order_amount_irr: int) -> ReceiptInfo:
    """رسیدِ متنی را می‌خواند و وضعیتِ مبلغ را نسبت به سفارش report می‌کند."""
    info = ReceiptInfo()
    source = normalize_digits(text or "")
    if not source.strip():
        return info

    spans = _card_spans(source)
    values = []
    for match in _NUMBER_RUN.finditer(source):
        if any(start <= match.start() < end for start, end in spans):
            continue  # بخشی از شمارهٔ کارته، نه مبلغ
        raw = match.group(0)
        digits = re.sub(r"[ ,.\u200c\u00a0]", "", raw)
        if not digits.isdigit() or len(digits) > 14:
            continue
        value = int(digits)
        if value < MIN_AMOUNT:
            continue
        values.append(value)

    seen, amounts = set(), []
    for value in values:
        if value not in seen:
            seen.add(value)
            amounts.append(value)
    info.amounts = sorted(amounts)

    trace_match = _TRACE_HINT.search(source)
    if trace_match:
        info.trace = trace_match.group(1)
    elif amounts:
        # بدونِ برچسب: بلندترین عددِ «تراکنش‌مانند» که شبیه مبلغ نیست
        candidates = [v for v in info.amounts if 9 <= len(str(v)) <= 16 and v != order_amount_irr and v != order_amount_irr * 10]
        if candidates:
            info.trace = str(max(candidates, key=lambda v: len(str(v))))
    last4 = _LAST4_HINT.search(source)
    if last4:
        info.card_last4 = last4.group(1)
    elif spans:
        info.card_last4 = re.sub(r"[ -]", "", source[spans[0][0] : spans[0][1]])[-4:]
    date_match = _DATE_HINT.search(source)
    if date_match:
        info.date_text = date_match.group(1)

    if order_amount_irr > 0 and info.amounts:
        target = int(order_amount_irr)
        for value in info.amounts:
            if value == target or value * 10 == target:
                info.matched_amount = value
                info.state = "amount_ok"
                break
        if info.state == "none":
            info.nearest_amount = min(info.amounts, key=lambda v: abs(v - target))
            info.state = "amount_mismatch"
    return info
