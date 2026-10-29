"""
فیلدهای قابل‌تنظیمِ چک‌اوت (R3): مدل، پیش‌فرض‌ها، قالب‌های آماده، اعتبارسنجی.

ورودیِ مشتری **نامطمئن** است: طول‌محدود، بدونِ کاراکترِ کنترلی، ارقام فارسی/عربی نرمال می‌شن، و هرگز
مستقیم وارد پرامپتِ سیستمی نمی‌شه. regexِ نامعتبرِ صاحب فروشگاه موقعِ *ذخیره* رد می‌شه (برنامه نمی‌ترکه).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Optional

FIELD_TYPES = ("text", "phone", "number", "choice", "location", "email")
APPLIES_TO = ("all", "physical", "digital")
HARD_MAX_LEN = 500
MAX_FIELDS = 12
MAX_CHOICES = 12

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_PHONE = re.compile(r"^(?:\+98|0098|98|0)?(9\d{9})$")
_EMAIL = re.compile(r"^[^\s@]{1,64}@[^\s@]{1,190}\.[A-Za-z]{2,24}$")
_ID = re.compile(r"^[a-z][a-z0-9_]{0,23}$")


@dataclass
class CheckoutField:
    id: str
    label: str
    prompt: str
    type: str = "text"
    required: bool = True
    applies_to: str = "all"
    regex: str = ""
    choices: list = field(default_factory=list)
    min_len: int = 0
    max_len: int = 200


def normalize_input(raw: str, max_len: int = 200) -> str:
    text = _CTRL.sub("", (raw or "").translate(_DIGITS)).replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[: min(max_len, HARD_MAX_LEN)] if max_len else text[:HARD_MAX_LEN]


def normalize_phone(raw: str) -> Optional[str]:
    cleaned = re.sub(r"[\s\-()]", "", normalize_input(raw, 40))
    match = _PHONE.match(cleaned)
    return "0" + match.group(1) if match else None


def default_fields(lang: str = "fa") -> list:
    if lang == "en":
        return [
            CheckoutField("name", "Name", "Please send your full name:", "text", True, "all", min_len=2, max_len=60),
            CheckoutField("phone", "Mobile", "Please send your mobile number (e.g. 09123456789):", "phone", True),
            CheckoutField("address", "Address", "Please send your full delivery address:", "text", True, "physical", min_len=8, max_len=300),
            CheckoutField("postal", "Postal code", "Postal code (10 digits):", "number", False, "physical", min_len=10, max_len=10),
            CheckoutField("notes", "Notes", "Any notes for the seller?", "text", False, "all", max_len=300),
        ]
    return [
        CheckoutField("name", "نام و نام‌خانوادگی", "نام و نام‌خانوادگیت رو بفرست:", "text", True, "all", min_len=2, max_len=60),
        CheckoutField("phone", "شماره موبایل", "شماره موبایلت رو بفرست (مثلاً 09123456789):", "phone", True),
        CheckoutField("address", "آدرس", "آدرس کاملِ تحویل رو بفرست:", "text", True, "physical", min_len=8, max_len=300),
        CheckoutField("postal", "کدپستی", "کدپستیِ ۱۰ رقمی (اختیاری):", "number", False, "physical", min_len=10, max_len=10),
        CheckoutField("notes", "توضیحات", "توضیحاتی برای فروشنده داری؟ (اختیاری)", "text", False, "all", max_len=300),
    ]


def templates(lang: str = "fa") -> dict:
    base = {f.id: f for f in default_fields(lang)}
    fa = lang != "en"
    return {
        "physical": [base["name"], base["phone"], base["address"], base["postal"], base["notes"]],
        "digital": [
            CheckoutField("name", base["name"].label, base["name"].prompt, "text", True, "all", min_len=2, max_len=60),
            CheckoutField("email", "ایمیل" if fa else "Email", "ایمیلت رو بفرست:" if fa else "Please send your email:", "email", False, "digital"),
            base["phone"].__class__(**{**asdict(base["phone"]), "required": False}),
        ],
        "services": [
            base["name"],
            base["phone"],
            CheckoutField("request", "درخواست" if fa else "Request", "درخواستت رو بنویس:" if fa else "Describe your request:", "text", True, "all", min_len=3, max_len=500),
        ],
    }


# ------------------------------------------------------------ ذخیره/بارگذاری ----


def validate_definition(raw: dict) -> Optional[str]:
    """پیامِ خطای فارسی اگه تعریفِ فیلد معیوب باشه، وگرنه ``None``."""
    if not isinstance(raw, dict):
        return "تعریفِ فیلد باید یک شیء باشه."
    fid = str(raw.get("id", ""))
    if not _ID.match(fid):
        return "شناسه‌ی فیلد باید با حرفِ انگلیسی شروع بشه و فقط حروف کوچک، عدد و _ داشته باشه (حداکثر ۲۴)."
    if not str(raw.get("label", "")).strip():
        return "برچسبِ فیلد نمی‌تونه خالی باشه."
    if not str(raw.get("prompt", "")).strip():
        return "متنِ پرسش نمی‌تونه خالی باشه."
    if raw.get("type", "text") not in FIELD_TYPES:
        return "نوعِ فیلد نامعتبره."
    if raw.get("applies_to", "all") not in APPLIES_TO:
        return "«اعمال برای» نامعتبره."
    pattern = str(raw.get("regex", "") or "")
    if pattern:
        if len(pattern) > 200:
            return "الگوی regex خیلی بلنده (حداکثر ۲۰۰ کاراکتر)."
        try:
            re.compile(pattern)
        except re.error as exc:
            return f"الگوی regex نامعتبره: {exc}"
    choices = raw.get("choices") or []
    if raw.get("type") == "choice":
        if not isinstance(choices, list) or not (2 <= len(choices) <= MAX_CHOICES) or any(not str(c).strip() for c in choices):
            return f"برای فیلدِ «انتخابی» ۲ تا {MAX_CHOICES} گزینه‌ی غیرخالی لازمه."
    try:
        lo, hi = int(raw.get("min_len", 0) or 0), int(raw.get("max_len", 200) or 200)
    except (TypeError, ValueError):
        return "حداقل/حداکثرِ طول باید عدد باشه."
    if lo < 0 or hi < 1 or lo > hi or hi > HARD_MAX_LEN:
        return f"محدوده‌ی طول نامعتبره (حداکثر {HARD_MAX_LEN})."
    return None


def validate_all(raw_fields: list) -> Optional[str]:
    if not isinstance(raw_fields, list) or not raw_fields:
        return "حداقل یک فیلد لازمه."
    if len(raw_fields) > MAX_FIELDS:
        return f"حداکثر {MAX_FIELDS} فیلد مجازه."
    seen: set = set()
    for item in raw_fields:
        error = validate_definition(item)
        if error:
            return error
        if item["id"] in seen:
            return f"شناسه‌ی «{item['id']}» تکراریه."
        seen.add(item["id"])
    return None


def _from_dict(raw: dict) -> CheckoutField:
    return CheckoutField(
        id=str(raw["id"]), label=str(raw["label"]).strip(), prompt=str(raw["prompt"]).strip(), type=raw.get("type", "text"),
        required=bool(raw.get("required", True)), applies_to=raw.get("applies_to", "all"), regex=str(raw.get("regex", "") or ""),
        choices=[str(c).strip() for c in (raw.get("choices") or [])], min_len=int(raw.get("min_len", 0) or 0),
        max_len=int(raw.get("max_len", 200) or 200),
    )


def load_fields(settings) -> list:
    """فیلدهای ذخیره‌شده (معتبر)؛ خالی/خراب ⇒ پیش‌فرض. (پرچم‌های قدیمیِ ``require_customer_*`` فقط جریانِ ``shop_ai`` رو هدایت می‌کنن.)"""
    raw = getattr(settings, "checkout_fields", None)
    if isinstance(raw, list) and raw and validate_all(raw) is None:
        return [_from_dict(item) for item in raw]
    lang = "en" if getattr(settings, "bot_language", "fa") == "en" else "fa"
    return default_fields(lang)


def fields_for_cart(fields: list, has_physical: bool, has_digital: bool) -> list:
    out = []
    for f in fields:
        if f.applies_to == "all" or (f.applies_to == "physical" and has_physical) or (f.applies_to == "digital" and has_digital):
            out.append(f)
    return out


# --------------------------------------------------------------- اعتبارسنجی ----


def validate_value(f: CheckoutField, raw: str) -> tuple:
    """``(True, مقدارِ نرمال)`` یا ``(False, پیامِ خطای فارسی)``."""
    text = normalize_input(raw, f.max_len or 200)
    if not text:
        return False, "لطفاً یه مقدار بفرست."
    if f.type == "phone":
        phone = normalize_phone(text)
        return (True, phone) if phone else (False, "شماره‌ی موبایل معتبر نیست؛ مثلاً 09123456789 بفرست.")
    if f.type == "number":
        digits = re.sub(r"[\s\-]", "", text)
        if not digits.isdigit():
            return False, "فقط عدد بفرست."
        text = digits
    elif f.type == "email":
        if not _EMAIL.match(text):
            return False, "ایمیل معتبر نیست؛ مثلاً name@example.com بفرست."
    elif f.type == "choice":
        if text in f.choices:
            return True, text
        if text.isdigit() and 1 <= int(text) <= len(f.choices):
            return True, f.choices[int(text) - 1]
        return False, "یکی از گزینه‌ها رو انتخاب کن."
    elif f.type == "location":
        pass  # «lat,lon» یا آدرسِ متنی — هر دو قابل‌قبوله
    if len(text) < (f.min_len or 0):
        return False, f"خیلی کوتاهه (حداقل {f.min_len} کاراکتر)."
    if f.regex:
        try:
            if not re.search(f.regex, text):
                return False, "فرمتِ واردشده درست نیست."
        except re.error:
            pass  # تعریفِ معیوب موقعِ ذخیره رد می‌شه؛ اینجا هرگز نباید بشکنه
    return True, text
