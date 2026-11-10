"""جدولِ توصیفیِ «تنظیماتِ عملیاتی» که پنلِ دکمه‌ایِ داخلِ پیام‌رسان از آن می‌خواند (قلم ۳).

چرا یک جدول و نه کدِ پخش‌شده: هر مقدارِ قابل‌عوض‌کردنِ از تلگرام/بله باید **یک‌جا** تعریف شده
باشد تا (۱) برچسبِ فارسی/انگلیسیِ همان‌جا باشد، (۲) کرانه‌ها و نوعِ مقدار یک‌بار نوشته شود و
(۳) هیچ‌جا نتوان مسیرِ «متنِ callback ← setattr» را دور زد.

قاعده‌ی امنیتیِ این ماژول: **هیچ ورودی‌ای از callback باور نمی‌شود.** ``validate`` هر چیزی را
(رشته، عدد، بولِ ساختگی، ``None``، فهرست، مقدارِ بیرون‌ازکرانه) از نو می‌سنجد و یا مقدارِ درستِ
تایپ‌شده برمی‌گرداند یا ``FieldError``. ``apply`` هم فقط از همان‌جا رد می‌شود.

دو قابلیت لازم است (``app/core/admins.py``):
* خواندن: ``settings.view`` (مالک و مدیر؛ به پشتیبان/ناظر هرگز داده نمی‌شود).
* نوشتن:  ``settings.edit`` (پیش‌فرض فقط مالک؛ مدیر فقط وقتی ``managers_can_edit_settings`` روشن باشد).
* قلم‌های «اعطایِ دسترسی» (``finance_manager_access``، ``managers_can_edit_settings``) برایِ نوشتن
  ``admins.manage`` می‌خواهند — یعنی **همیشه فقط مالک**؛ وگرنه مدیری که «ویرایشِ تنظیمات» دارد
  می‌تواند با یک دکمه دسترسیِ مالیِ خودش را باز کند (تشدیدِ مجوز).

فیلدهای مشتق (دارای ``reader``/``writer``) چیزهایی‌اند که در ``AppSettings`` کلیدِ مستقیم ندارند:
روشن/خاموش‌بودنِ هر «روشِ ارسال» درونِ فهرستِ ``shipping_methods`` است و «ساعتِ کاری» درونِ
``working_hours``. همین‌طور «فهرستِ روش‌هایِ ارسال» با داده‌یِ خودِ مالک معنا دارد، پس فیلدهایش
از پیش نمی‌سازیم؛ ``shipping_fields(settings)`` در همان لحظه می‌سازدشان.

هر فیلدی که اثرش بیرونِ ``settings.json`` چیزِ دیگری را هم لازم دارد (راه‌اندازیِ دوباره‌ی ربات،
بازخوانیِ استخرِ پروکسی، …) ``needs_restart`` دارد؛ ``bot_manager`` باید
``settings_fields.set_change_listener(...)`` را به ``self.restart`` وصل کند. تا آن، مقدار ذخیره
می‌شود و از دورِ بعدیِ ربات اثر می‌کند — و پنل همان را به مدیر می‌گوید.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as _dc_field
from typing import Callable, Optional

from app.core import admins as am
from app.core.settings import normalize_shipping_methods

# ------------------------------------------------------------------ مجوزها ----

PERM_VIEW = am.CAP_SETTINGS_VIEW  # خواندنِ هر تنظیم
PERM_WRITE = am.CAP_SETTINGS_EDIT  # عوض‌کردنِ تنظیماتِ عملیاتی (مالک + مدیرِ با اعطایِ صریح)
PERM_GRANT = am.CAP_ADMINS_MANAGE  # فقط مالک: اعطایِ دسترسی به نقشِ «مدیر»

KIND_BOOL = "bool"
KIND_INT = "int"
KIND_FLOAT = "float"
KIND_CHOICE = "choice"
KIND_TEXT = "text"

_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_TRUE = frozenset({"1", "true", "yes", "y", "on", "t", "روشن", "فعال", "بله"})
_FALSE = frozenset({"0", "false", "no", "n", "off", "f", "خاموش", "غیرفعال", "نه"})

# گروه‌ها: (شناسه، برچسبِ فارسی، برچسبِ انگلیسی)
GROUPS: tuple = (
    ("pay", "💳 پرداخت و تأییدِ سفارش", "Payment & order confirmation"),
    ("ship", "🚚 روش‌هایِ ارسال", "Shipping methods"),
    ("ai", "🧠 هوش مصنوعی و مصرف", "AI & usage limits"),
    ("bot", "🤖 رفتارِ ربات و پشتیبانی", "Bot experience & support"),
    ("msg", "📣 پیامِ همگانی", "Broadcasting"),
    ("privacy", "🔒 حریمِ خصوصی", "Privacy"),
    ("grant", "🎚 دسترسیِ مدیران", "Manager grants"),
)

_PHONE = r"[+0-9\- ()]{7,20}"
_INT_RE = re.compile(r"-?\d+")
_FLOAT_RE = re.compile(r"-?\d+(\.\d+)?")
_STEP_RE = re.compile(r"-?(?:\d+|\d*\.\d+)")


@dataclass(frozen=True)
class SettingField:
    """یک تنظیمِ عملیاتی + همه‌چیزی که پنل برای نمایش/سنجیدن لازم دارد."""

    key: str
    group: str
    fa: str
    en: str
    kind: str = KIND_BOOL
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    steps: tuple = ()
    choices: tuple = ()  # ((مقدار، برچسبِ فارسی), ...)
    max_length: int = 0
    unit: str = ""
    permission: str = PERM_WRITE  # قابلیتِ لازم برایِ نوشتن
    needs_restart: bool = False
    hint_fa: str = ""
    pattern: str = ""  # فقط text: عبارتِ باقِ کاملِ python re
    redact: bool = False  # مقدارش به پیام‌رسان نشان داده نمی‌شه (فقط «تنظیم شد»)
    reader: Optional[Callable[[object], object]] = _dc_field(default=None, compare=False, repr=False)
    writer: Optional[Callable[[object, object], None]] = _dc_field(default=None, compare=False, repr=False)
    extra_check: Optional[Callable[[object, object], str]] = _dc_field(default=None, compare=False, repr=False)

    @property
    def is_derived(self) -> bool:
        return self.reader is not None or self.writer is not None

    def label(self, lang: str = "fa") -> str:
        return self.fa if (lang or "fa").startswith("fa") else self.en

    def bounds(self) -> str:
        """متنِ کرانه‌ها در کارتِ فیلد («۱..۲۴۰ دقیقه») — همان چیزی که مدیر قبل از تایپ می‌بیند."""
        if self.kind in (KIND_INT, KIND_FLOAT) and self.minimum is not None and self.maximum is not None:
            return f"مجاز: {self.minimum:g} تا {self.maximum}{self.unit}"
        if self.kind == KIND_TEXT:
            return f"حداکثر {self.max_length} نویسه"
        return ""


# --------------------------------------------------------------- سازنده‌ها ----


def _bool(key, group, fa, en, **kw) -> SettingField:
    return SettingField(key, group, fa, en, KIND_BOOL, **kw)


def _int(key, group, fa, en, minimum, maximum, steps, **kw) -> SettingField:
    return SettingField(key, group, fa, en, KIND_INT, minimum=minimum, maximum=maximum, steps=steps, **kw)


def _float(key, group, fa, en, minimum, maximum, steps, **kw) -> SettingField:
    return SettingField(key, group, fa, en, KIND_FLOAT, minimum=minimum, maximum=maximum, steps=steps, **kw)


def _choice(key, group, fa, en, choices, **kw) -> SettingField:
    return SettingField(key, group, fa, en, KIND_CHOICE, choices=tuple(choices), **kw)


def _text(key, group, fa, en, max_length, **kw) -> SettingField:
    return SettingField(key, group, fa, en, KIND_TEXT, max_length=max_length, **kw)


# --------------------------------------------- سنجش‌هایِ مشترکِ چند فیلد ----


def _check_cache_minutes(settings, value) -> str:
    """عمرِ ۰ دقیقه یعنی «بدونِ کش»؛ فقط وقتی معنا دارد که خودِ کش خاموش باشد."""
    if int(value) == 0 and bool(getattr(settings, "ai_response_cache", True)):
        return "کشِ پاسخ روشن است ولی عمرش صفر دقیقه — یا کش را خاموش کن یا عمرش را بیشتر از صفر بگذار."
    return ""


def _check_debounce_cap(settings, value) -> str:
    wait = float(getattr(settings, "debounce_wait_seconds", 3.0) or 0.0)
    if float(value) < wait:
        return f"«سقفِ انتظار» باید دستِ کم {wait:g} ثانیه باشد (مقدارِ «سکوتِ لازم»)."
    return ""


def _check_debounce_wait(settings, value) -> str:
    cap = float(getattr(settings, "debounce_max_wait_seconds", 10.0) or 0.0)
    if cap and float(value) > cap:
        return f"«سکوتِ لازم» نباید بیشتر از «سقفِ انتظار» ({cap:g} ثانیه) باشد."
    return ""


# ------------------------------------------------- پرداخت و تأییدِ سفارش ----

_PAY_FIELDS = (
    _bool("receipt_check_enabled", "pay", "رسیدِ کارت‌به‌کارت", "Ask for a receipt",
          hint_fa="بعد از «پرداخت کردم» ربات از مشتری رسید می‌خواهد (متن یا عکس)."),
    _bool("receipt_amount_check", "pay", "مطابقتِ مبلغِ رسید", "Match receipt amount",
          hint_fa="اگر مبلغِ رسید با سفارش نخواند، اختلاف در اعلان برجسته می‌شود."),
    _bool("alert_on_payment_claim", "pay", "هشدارِ فوریِ «پرداخت کردم»", "Instant payment-claim alarm",
          hint_fa="با روشن بودن، به محض اعلامِ پرداخت، مالک و مدیرانِ تصمیم‌گیرنده خبردار می‌شوند."),
    _bool("auto_confirm_gateway_payments", "pay", "تأییدِ خودکارِ پرداختِ درگاه", "Auto-confirm gateway payments",
          hint_fa="پرداختِ موفقِ بله‌پی بدونِ دکمه‌ی مالک تأیید می‌شود (کارت‌به‌کارت همیشه دستی می‌ماند)."),
    _int("reservation_minutes", "pay", "مهلتِ پرداخت (رزروِ موجودی)", "Reservation window", 1, 240, (1, 5, 15), unit=" دقیقه",
         hint_fa="موجودیِ سفارشِ «در انتظار پرداخت» بعد از این مهلت آزاد می‌شود."),
)


# ------------------------------------------------- روش‌هایِ ارسال (مشتق) ----


def _ship_reader(method_id: str) -> Callable[[object], object]:
    def read(settings) -> bool:
        for m in normalize_shipping_methods(getattr(settings, "shipping_methods", []) or []):
            if m["id"] == method_id:
                return bool(m["active"])
        return False  # روشِ حذف‌شده ⇒ «خاموش»، تا دکمه‌ی قدیمیِ جعلی چیزی ننویسد

    return read


def _ship_writer(method_id: str) -> Callable[[object, object], None]:
    def write(settings, value) -> None:
        methods = normalize_shipping_methods(getattr(settings, "shipping_methods", []) or [])
        for m in methods:
            if m["id"] == method_id:
                m["active"] = bool(value)
        settings.shipping_methods = methods

    return write


def shipping_fields(settings) -> tuple:
    """فیلدهای مشتقِ «روشن/خاموشِ هر روشِ ارسال» برایِ فهرستِ فعلیِ مالک.

    کلیدِ فیلد ``ship_<id>`` است: جداکننده‌ی callback دو‌نقطه (``:``) است، پس idِ روشِ
    «m:2» باید به ``ship_m_2`` درآید تا آرگومانِ مسیر بشکند."""
    out: list = []
    for m in normalize_shipping_methods(getattr(settings, "shipping_methods", []) or []):
        name = str(m["name"])[:30]
        price = int(m["price_irr"] or 0)
        title = f"ارسال: {name}" + (f" ({price:,} ریال)" if price else " (رایگان)")
        out.append(
            _bool(
                "ship_" + str(m["id"]).replace(":", "_").replace("/", "_"), "ship",
                title, f"Shipping: {name}",
                hint_fa="اگر خاموش باشد، مشتری این گزینه را در «انتخابِ ارسال» نمی‌بیند.",
                reader=_ship_reader(m["id"]), writer=_ship_writer(m["id"]),
            )
        )
    return tuple(out)


def shipping_summary(settings) -> str:
    methods = normalize_shipping_methods(getattr(settings, "shipping_methods", []) or [])
    if not methods:
        return "هیچ روشِ ارسالی نساخته‌ای؛ مرحله‌ی «انتخابِ ارسال» به مشتری نشان داده نمی‌شود."
    on = sum(1 for m in methods if m["active"])
    return f"روش‌هایِ ارسال: {len(methods)} ساخته‌شده، {on} روشن."


# ---------------------------------------------------- هوش مصنوعی و مصرف ----

_AI_FIELDS = (
    _bool("telegram_ai", "ai", "هوشِ ربات روی تلگرام", "AI on Telegram",
          hint_fa="خاموش ⇒ تلگرام فقط دکمه/سفارش/متنِ آماده دارد؛ مدل صدا زده نمی‌شود."),
    _bool("bale_chat_ai", "ai", "هوشِ ربات روی بله", "AI on Bale",
          hint_fa="مستقل از تلگرام است؛ روی یکی روشن و روی دیگری خاموش ممکن است."),
    _bool("ai_kill_switch", "ai", "قطعِ اضطراریِ هوش مصنوعی", "AI kill switch",
          hint_fa="با یک دکمه هوش مصنوعی را برایِ همه‌ی پیام‌رسان‌ها خاموش می‌کند."),
    _bool("ai_response_cache", "ai", "کشِ پاسخ‌هایِ تکراری", "Response cache",
          hint_fa="پاسخِ تکراری چند دقیقه در حافظه می‌ماند و مدل دوباره صدا زده نمی‌شود."),
    _int("ai_response_cache_minutes", "ai", "عمرِ کشِ پاسخ", "Cache lifetime", 0, 1440, (5, 15, 60), unit=" دقیقه",
         extra_check=_check_cache_minutes, hint_fa="۰ = بدونِ کش."),
    _int("max_ai_messages_per_chat_per_day", "ai", "سقفِ پاسخِ هوشمند به هر گفتگو در روز", "AI cap per chat per day",
         0, 100000, (5, 20, 100), hint_fa="۰ = بدونِ سقف. فقط پاسخِ مدل را محدود می‌کند، نه دکمه و پرداخت."),
    _int("max_ai_messages_per_day_total", "ai", "سقفِ پاسخِ هوشمند در روز (همه‌ی گفتگوها)", "AI cap per day, total",
         0, 1000000, (50, 200, 1000), hint_fa="۰ = بدونِ سقف؛ با پر شدنش اعلانِ «سقف تموم شد» می‌آید."),
    _float("debounce_wait_seconds", "ai", "سکوتِ لازم قبل از ارسالِ پیام‌هایِ پشتِ‌سرهم", "Debounce wait",
           0.0, 30.0, (0.5, 1.0, 2.0), unit=" ثانیه", needs_restart=True, extra_check=_check_debounce_wait,
           hint_fa="۰ = هر پیام جدا به مدل می‌رود."),
    _float("debounce_max_wait_seconds", "ai", "سقفِ انتظارِ ادغامِ پیام‌ها", "Debounce max wait",
           1.0, 60.0, (1.0, 2.0, 5.0), unit=" ثانیه", needs_restart=True, extra_check=_check_debounce_cap,
           hint_fa="حتی اگر مشتری سکوت نکند بیشتر معطل نمی‌شود؛ باید مساوی یا بزرگ‌تر از «سکوتِ لازم» باشد."),
)


# --------------------------------------------- رفتارِ ربات و پشتیبانی ----


def _wh_reader(settings) -> bool:
    raw = getattr(settings, "working_hours", None)
    return bool(raw.get("enabled")) if isinstance(raw, dict) else False


def _wh_writer(settings, value) -> None:
    """فقط کلیدِ ``enabled`` ساعتِ کاری را عوض می‌کند و بقیه‌ی ساعت‌ها را دست می‌زند؛
    همان شکلِ استانداردِ ``working_hours.validate`` (dictِ سالم، هرگز داده‌یِ خام)."""
    raw = getattr(settings, "working_hours", None)
    hours = dict(raw) if isinstance(raw, dict) else {}
    hours["enabled"] = bool(value)
    hours["tz"] = str(hours.get("tz") or "Asia/Tehran")
    if not isinstance(hours.get("days"), dict):
        hours["days"] = {}
    hours["message"] = str(hours.get("message") or "")[:200]
    settings.working_hours = hours


_BOT_FIELDS = (
    _choice("business_mode", "bot", "حالتِ کاریِ ربات", "Business mode",
            choices=(("store", "فروشگاهی 🛍"), ("consultant", "مشاوره‌ای 💬")), needs_restart=True,
            hint_fa="تغییرِ حالت رفتارِ ربات را از پایه عوض می‌کند و به راه‌اندازیِ دوباره نیاز دارد."),
    _bool("working_hours_enabled", "bot", "پیامِ خارج از ساعتِ کاری", "Out-of-hours message",
          hint_fa="روشن/خاموشِ همان پیام؛ ویرایشِ خودِ ساعت‌ها در برنامه‌ی دسکتاپ است.",
          reader=_wh_reader, writer=_wh_writer),
    _text("support_phone", "bot", "شماره/متنِ تماسِ پشتیبانی", "Support phone", 40, pattern=_PHONE,
          hint_fa="در صفحه‌ی پشتیبانیِ ربات به مشتری نشان داده می‌شود."),
    _text("support_direct_note", "bot", "یادداشتِ تماسِ مستقیم", "Direct-contact note", 300,
          hint_fa="متنِ کوتاهِ «چطور با ما تماس بگیری» در همان صفحه."),
    _int("handoff_timeout_hours", "bot", "مهلتِ بی‌فعالیتیِ گفتگویِ پشتیبانی", "Handoff idle timeout", 1, 720, (1, 6, 24), unit=" ساعت",
         hint_fa="بعد از این همه ساعت بی‌فعالیتی، گفتگویِ پشتیبانی خودکار بسته می‌شود."),
)


# ---------------------------------------------------------- پیامِ همگانی ----

_MSG_FIELDS = (
    _int("broadcast_daily_cap", "msg", "سقفِ ارسالِ همگانی در ۲۴ ساعت", "Broadcast daily cap", 1, 50, (1, 2, 5), unit=" کمپین"),
    _int("broadcast_rate_telegram", "msg", "سرعتِ ارسال روی تلگرام", "Telegram send rate", 1, 25, (1, 5, 10), unit=" پیام/ثانیه"),
    _int("broadcast_rate_bale", "msg", "سرعتِ ارسال روی بله", "Bale send rate", 1, 10, (1, 2, 5), unit=" پیام/ثانیه",
         hint_fa="روی بله محافظه‌کارانه: حدِّ مستندشده‌ای منتشر نشده."),
    _bool("broadcast_footer_enabled", "msg", "پانویسِ «برای توقف /stop»", "Broadcast footer",
          hint_fa="خاموش‌کردنش راهِ ترکِ اشتراکِ پیامِ همگانی را از پیام‌ها برمی‌دارد؛ پیش‌فرض روشن است."),
)


# --------------------------------------------------------- حریمِ خصوصی ----

_PRIVACY_FIELDS = (
    _int("retention_days", "privacy", "نگهداریِ گفتگوها", "Conversation retention", 0, 3650, (7, 30, 90), unit=" روز",
         hint_fa="۰ = هیچ‌وقت پاک نشود؛ N = گفتگوهای قدیمی‌تر از N روز پاک و سفارش‌های بسته‌شده‌ی قدیمی ناشناس می‌شوند."),
)


# ------------------------------------------------- اعطایِ دسترسیِ مدیران ----

_GRANT_FIELDS = (
    _bool("managers_can_edit_settings", "grant", "مدیران بتوانند تنظیماتِ عملیاتی را عوض کنند", "Managers may edit operational settings",
          permission=PERM_GRANT, hint_fa="خاموش ⇒ مدیر فقط می‌بیند؛ نوشتن با «دسترسی نداری» رد می‌شود."),
    _bool("finance_manager_access", "grant", "مدیران خلاصه‌ی مالی را ببینند", "Managers may see the finance summary",
          permission=PERM_GRANT, hint_fa="فقط «دیدنِ» مالی؛ دفترنویسی هرگز به مدیر داده نمی‌شود."),
)


# -------------------------------------------------------------- فهرست ----

FIELDS: dict = {}
for _group_fields in (_PAY_FIELDS, _AI_FIELDS, _BOT_FIELDS, _MSG_FIELDS, _PRIVACY_FIELDS, _GRANT_FIELDS):
    for _f in _group_fields:
        FIELDS[_f.key] = _f
del _f, _group_fields  # نامِ حلقه در سطحِ ماژول نمی‌مونه

STATIC_FIELDS: tuple = tuple(FIELDS.values())
GROUP_IDS: tuple = tuple(gid for gid, _fa, _en in GROUPS)


def groups() -> tuple:
    return GROUPS


def group_label(group: str, lang: str = "fa") -> str:
    for gid, fa, en in GROUPS:
        if gid == group:
            return fa if (lang or "fa").startswith("fa") else en
    return group


def get_field(key: str) -> Optional[SettingField]:
    """فیلدِ ثابت با این کلید (فیلدهایِ مشتقِ «روشِ ارسال» را ``find_field`` می‌سنجد)."""
    if not key:
        return None
    return FIELDS.get(str(key))


def find_field(settings, key: str) -> Optional[SettingField]:
    """کلیدِ callback را اول در جدولِ ثابت و بعد در فیلدهایِ مشتقِ روشِ ارسال می‌جوید.

    روشِ ارسال با این id که دیگر در فهرست نیست ⇒ None ⇒ پنل «این تنظیم پیدا نشد» می‌دهد
    (دکمه‌ی قدیمیِ جعلی روی روشِ حذف‌شده چیزی نمی‌نویسد)."""
    f = get_field(key)
    if f is not None:
        return f
    for candidate in shipping_fields(settings):
        if candidate.key == str(key):
            return candidate
    return None


def fields_for(settings, group: str) -> tuple:
    """فیلدهایِ یک گروه برایِ این مالک: فیلدهایِ ثابت + فیلدهایِ مشتقِ روشِ ارسال."""
    out = [f for f in STATIC_FIELDS if f.group == group]
    if group == "ship":
        out = list(shipping_fields(settings))
    return tuple(out)


# ------------------------------------------------------------------ خواندن ----


def read(settings, f: SettingField):
    """مقدارِ فعلی؛ نبودِ کلید/خطایِ داده = None (هیچ‌وقت استثنا نمی‌دهد)."""
    if settings is None:
        return None
    if f.reader is not None:
        try:
            return f.reader(settings)
        except Exception:  # noqa: BLE001 — نمایشِ یک تنظیم نباید پنل را بشکنه
            return None
    return getattr(settings, f.key, None)


def format_value(f: SettingField, value) -> str:
    """نمایشِ کوتاهِ مقدار در متنِ پیام (عددِ لاتین — در callback هم لاتین خوانده می‌شود)."""
    if value is None:
        return "—"
    if f.kind == KIND_BOOL:
        return "روشن" if value else "خاموش"
    if f.kind == KIND_FLOAT:
        return f"{float(value):g}"
    if f.kind == KIND_CHOICE:
        return _choice_label(f, value)
    if f.kind == KIND_TEXT:
        text = str(value)
        if f.redact:
            return "(تنظیم شده)" if text.strip() else "(خالی)"
        return text[:60] if text.strip() else "(خالی)"
    return str(int(value))


def _choice_label(f: SettingField, value) -> str:
    for option, label in f.choices:
        if option == value:
            return label
    return "(انتخاب نشده)" if not value else str(value)


def chip(f: SettingField, value) -> str:
    """✅/⛔ برایِ بول‌ها؛ برایِ بقیه همان مقدارِ جاری — چیزی که در فهرستِ گروه نشان داده می‌شه."""
    if f.kind == KIND_BOOL:
        return "✅ روشن" if value else "⛔ خاموش"
    return format_value(f, value) + (f.unit if f.unit else "")


# ------------------------------------------------------------------ سنجش ----


class FieldError(ValueError):
    """مقدارِ نامعتبر/بی‌اجازه — پیامش فارسی است و مستقیم به مدیر نشان داده می‌شود."""


def _number_text(raw) -> str:
    """رشته/عددِ خام → عددِ لاتینِ خالص. ``True``/فهرست/دیکشنری/«روشن» هیچ‌وقت عدد حساب نمی‌شن
    (و «۱۵» فارسی هم ۱۵ می‌شه)؛ هیچ مقدارِ دیگری حدس زده نمی‌شه."""
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        raise FieldError("مقدارِ این تنظیم باید عدد باشد.")
    text = str(raw).strip().translate(_DIGIT_MAP).replace("٬", "").replace(",", "").replace("،", ".")
    if not text or not re.fullmatch(r"-?\d+(\.\d+)?", text):
        raise FieldError("مقدارِ این تنظیم باید عدد باشد.")
    return text


def validate(settings, f: SettingField, raw):
    """**تنها دروازه‌ی نوشتن.** مقدارِ خامِ callback (یا مقدارِ تایپ‌شده) را می‌گیرد و یا مقدارِ
    درستِ تایپ‌شده برمی‌گرداند یا ``FieldError``. حدس نمی‌زند: ``True`` برایِ یک عدد، رشته‌ی
    بی‌شکل، گزینه‌ی ناخواسته، عددِ بیرون از کرانه‌ها و متنِ بی‌شکل همه رد می‌شوند.
    «clamp» عمدی نیست: عددِ خارج از کرانه اشتباه است، نه نزدیک‌ترین مقدارِ مجاز."""
    if f.kind == KIND_BOOL:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            token = raw.strip().lower()
            if token in _TRUE:
                return True
            if token in _FALSE:
                return False
        raise FieldError("برای این تنظیم فقط «روشن» یا «خاموش» می‌شود نوشت.")

    if f.kind == KIND_CHOICE:
        value = raw if isinstance(raw, str) else ""
        value = value.strip()
        allowed = [option for option, _label in f.choices]
        if value in allowed:
            return value
        raise FieldError("این گزینه از فهرستِ این تنظیم نیست: " + " / ".join(allowed))

    if f.kind == KIND_TEXT:
        if not isinstance(raw, str):
            raise FieldError("برای این تنظیم باید متن بنویسی.")
        text = " ".join(raw.split())  # فاصله‌هایِ اضافی/خط جدید از بین می‌رود
        if f.max_length:
            text = text[: f.max_length]
        if not text:
            raise FieldError("متنِ این تنظیم نمی‌تواند خالی باشد (پاک‌کردنش در برنامه‌ی دسکتاپ است).")
        if f.pattern:
            text = text.translate(_DIGIT_MAP)  # رقمِ فارسی/عربی → لاتین (همان کاری که صفحهٔ دسکتاپ می‌کند)
            if not re.fullmatch(f.pattern, text):
                raise FieldError("شکلِ این مقدار درست نیست (فقط رقم و + − پرانتز و فاصله).")
        return text

    text = _number_text(raw)
    pattern = _INT_RE if f.kind == KIND_INT else _FLOAT_RE
    if not re.fullmatch(pattern, text):
        raise FieldError(f"«{text[:20]}» عددِ {'صحیح' if f.kind == KIND_INT else 'اعشاری'} نیست.")
    value = int(text) if f.kind == KIND_INT else float(text)
    if f.minimum is not None and value < f.minimum:
        raise FieldError(f"کمینهٔ این تنظیم {f.minimum:g}{f.unit} است.")
    if f.maximum is not None and value > f.maximum:
        raise FieldError(f"بیشینهٔ این تنظیم {f.maximum:g}{f.unit} است.")
    if f.extra_check is not None:
        try:
            error = f.extra_check(settings, value) or ""
        except Exception:  # noqa: BLE001 — سنجشِ ناکام یعنی «ننویس»
            error = "این مقدار با تنظیمِ دیگری نمی‌خواند."
        if error:
            raise FieldError(error)
    return value


def parse_step(f: SettingField, raw) -> object:
    """گامِ دکمه‌های ‎+N/−N: باید یکی از گام‌هایِ اعلام‌شدهٔ خودِ فیلد باشد — دکمه‌ی جعلی با
    ``+9999`` رد می‌شود (نه اینکه به نزدیک‌ترین گام تبدیل شود)."""
    text = str(raw or "").strip().translate(_DIGIT_MAP)
    if not _STEP_RE.fullmatch(text):
        raise FieldError("گامِ این دکمه شناخته‌شده نیست.")
    value = int(text) if f.kind == KIND_INT else float(text)
    allowed = {abs(s) for s in f.steps}
    if value == 0 or abs(value) not in allowed:
        raise FieldError("گامِ این دکمه مجاز نیست.")
    return int(value) if f.kind == KIND_INT else float(value)


def next_value(settings, f: SettingField, delta):
    """مقدارِ بعدیِ دکمه‌های +N/−N، با نگهبانیِ کرانه‌ها و سنجشِ دوباره (``extra_check`` هم روی
    همان مقدارِ تازه اجرا می‌شود؛ اگر نخواند ``FieldError``)."""
    if f.kind not in (KIND_INT, KIND_FLOAT):
        raise FieldError("این تنظیم با دکمه‌ی عددی عوض نمی‌شود.")
    current = read(settings, f)
    base = float(current) if f.kind == KIND_FLOAT else int(current or 0)
    candidate = base + delta
    candidate = int(round(candidate)) if f.kind == KIND_INT else round(candidate, 3)
    if f.minimum is not None and candidate < f.minimum:
        candidate = int(f.minimum) if f.kind == KIND_INT else float(f.minimum)
    if f.maximum is not None and candidate > f.maximum:
        candidate = int(f.maximum) if f.kind == KIND_INT else float(f.maximum)
    return validate(settings, f, candidate)


# ------------------------------------------------------------------ نوشتن ----


def apply(settings, f: SettingField, raw):
    """اعتبارسنجی ⇒ نوشتن در نمونهٔ تنظیماتِ زنده. ذخیرهٔ دیسک و ممیزی کارِ پنل است تا اگر
    هر کدام ناموفق بود، معلوم باشد چه نوشته شده است."""
    value = validate(settings, f, raw)
    if settings is None:
        raise FieldError("تنظیماتِ برنامه در دسترس نیست.")
    if f.writer is not None:
        f.writer(settings, value)
    else:
        setattr(settings, f.key, value)
    return value


def audit_detail(f: SettingField, value) -> str:
    """خطِ ممیزی: ``key=مقدارِ تازه`` کوتاه و بی‌راز."""
    if f.kind == KIND_BOOL:
        return f"{f.key}={'روشن' if value else 'خاموش'}"
    if f.kind == KIND_TEXT and f.redact:
        return f"{f.key}={'تنظیم شد' if str(value or '').strip() else 'خالی شد'}"
    return f"{f.key}={format_value(f, value)}"[:120]


# ------------------------------------------------------- قلاب‌هایِ تزریق‌شده ----

_change_listener: Optional[Callable[[str, object], None]] = None


def set_change_listener(listener: Optional[Callable[[str, object], None]]) -> None:
    """تزریقِ ``bot_manager`` (گوشِ تغییرِ تنظیم): ``lambda key, s: manager.restart()`` یا
    هر بازخوانیِ جزئی‌تر. نباشد هم مقدار ذخیره می‌شود و از دورِ بعدیِ ربات اثر می‌کند."""
    global _change_listener
    _change_listener = listener


def after_change(f: SettingField, settings) -> bool:
    """بعد از ذخیره + ممیزی صدا زده می‌شود. ``True`` یعنی گوشِ تغییر اجرا شد
    (پنل همان را در تأییدِ فارسی می‌گوید: «ربات راه‌اندازیِ دوباره شد»)."""
    if _change_listener is None or not f.needs_restart:
        return False
    try:
        _change_listener(f.key, settings)
    except Exception:  # noqa: BLE001 — تنظیم ذخیره شد؛ فقط اثرِ فوری نیفتاد
        return False
    return True
