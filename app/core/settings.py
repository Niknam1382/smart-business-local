"""مدیریت تنظیمات محلی برنامه: بارگذاری، ذخیره، و رمزنگاری فیلدهای حساس.

نسخه‌ی ۱.۰.۰: هوش مصنوعی فقط محلی است (هیچ API/سرویس بیرونی)، تلگرام تنها پیام‌رسانِ گفتگو
است و بله فقط به‌عنوانِ درگاهِ پرداختِ «بله‌پی» می‌ماند.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, asdict, field, fields
from pathlib import Path
from typing import Optional

from app.core.paths import get_app_data_dir
from app.core import crypto
from app.data.prompt_templates import default_prompt

logger = logging.getLogger(__name__)

_SETTINGS_FILE_NAME = "settings.json"

# نامِ کلیدهایِ تغییرکرده (تا کاربرِ نسخه‌هایِ قبلی توکن/مدلش را از دست ندهد)
_LEGACY_RENAMES = {
    "bale_bot_token_encrypted": "bale_pay_bot_token_encrypted",
    "model_tier": "model_id",
}
# سایزهایِ قدیمی (small/medium/large) به مدل‌هایِ equivalentsِ کاتالوگِ ۱.۰.۰ نگاشت می‌شن،
# وگرنه کاربرِ قدیمی بعد از ارتقا «مدلی انتخاب نشده» می‌دید.
_LEGACY_TIERS = {"small": "qwen25-3b", "medium": "qwen35-4b", "large": "qwen25-7b"}
# این کلیدها در ۱.۰.۰ عمداً حذف شده‌اند (API، زرین‌پال، حالت قابل‌حمل، overrides) و بی‌صدا نادیده گرفته می‌شن.
_LEGACY_IGNORED = (
    "ai_mode",
    "api_base_url",
    "api_key_encrypted",
    "api_model_name",
    "ai_providers",
    "ai_attempt_timeout",
    "ai_total_timeout",
    "ai_max_targets",
    "ai_provider_concurrency",
    "ai_local_fallback",
    "usd_to_irr_rate",
    "cost_display_unit",
    "ai_budget_monthly_usd",
    "ai_budget_action",
    "token_opt_response_cache",
    "token_opt_cache_ttl_minutes",
    "zarinpal_merchant_id_encrypted",
    "zarinpal_enabled",
    "zarinpal_sandbox",
    "zarinpal_callback_url",
    "finance_fee_bp_zarinpal",
    "bale_enabled",
    "bale_bio_supported",
    "shop_mode",
    "shop_mode_overrides",
)


@dataclass
class AppSettings:
    user_name: str = ""
    language: str = "fa"
    business_mode: Optional[str] = None  # "store" | "consultant"
    model_id: Optional[str] = None  # شناسهٔ مدلِ انتخاب‌شده از کاتالوگ (app/core/model_catalog.py)
    model_file_path: str = ""  # مسیر فایلِ GGUFِ آماده (وقتی کاربر خودش فایل می‌دهد)؛ خالی = از کاتالوگ
    model_storage_path: str = ""  # اگه خالی باشه، پیش‌فرض get_app_data_dir()/models استفاده می‌شه
    system_prompt: str = ""
    onboarding_complete: bool = False

    # --- موتورِ مدلِ محلی (پیش‌فرض‌ها خودکار از سخت‌افزار حساب می‌شن؛ عدد > ۰ یعنی دستورِ کاربر) ---
    ai_threads: int = 0  # ۰ = خودکار (تعداد هسته‌ها)
    ai_context_tokens: int = 0  # ۰ = خودکار بر پایهٔ سایز مدل و رم
    ai_gpu_layers: int = 0  # ۰ = فقط CPU؛ پیشرفته: اگر بیلدِ CUDA نصب باشد، تعداد لایه‌های GPU

    # --- اتصال به تلگرام (بله فقط درگاهِ پرداخت است؛ اسرار همه رمزنگاری‌شده روی دیسک) ---
    telegram_bot_token_encrypted: str = ""
    telegram_enabled: bool = True
    # پروکسی اختیاری تلگرام (تلگرام برای خیلی از کاربرای ایرانی بدون پروکسی/VPN
    # در دسترس نیست). آدرس می‌تونه user:pass داشته باشه، پس مثل توکن رمزنگاری می‌شه.
    telegram_proxy_encrypted: str = ""
    # --- اشتراکِ پروکسی — لینکِ خودِ کاربر؛ کش جدا از لیستِ دستی و رمزنگاری‌شده (credential داره) ---
    telegram_proxy_sub_url_encrypted: str = ""
    telegram_proxy_sub_cache_encrypted: str = ""
    telegram_proxy_sub_hours: int = 6  # ۰ = فقط دستی
    telegram_proxy_sub_updated_ts: int = 0
    telegram_proxy_sub_error: str = ""
    telegram_proxy_best_check_minutes: int = 10
    bot_autostart: bool = True  # با باز شدن برنامه، رباتِ فعال خودکار روشن بشه

    # --- تنظیمات حافظه‌ی مکالمه (قابل‌تنظیم توسط کاربر، نه فقط روشن/خاموشِ هر مکالمه) ---
    memory_history_limit: int = 20  # چند پیام اخیر به‌عنوان زمینه به مدل محلی فرستاده بشه
    memory_expire_hours: int = 0  # ۰ = هیچ‌وقت؛ بعد از این‌همه ساعت بی‌فعالیتی، مکالمه انگار تازه شروع شده

    # --- پرداخت ---
    # کارت‌به‌کارت دستی: شماره کارت قراره مستقیم به مشتری نشون داده بشه (نه
    # یه راز)، پس رمزنگاری نمی‌شه — دقیقاً مثل اینکه خودِ فروشنده شماره کارتش
    # رو توی یه کانال تلگرام پابلیک بذاره.
    card_to_card_number: str = ""
    card_to_card_holder_name: str = ""
    # --- بله‌پی: رباتِ بله فقط برایِ پرداختِ است (هیچ چتی را پاسخ نمی‌دهد) ---
    # توکنِ رباتِ بله و provider_token هر دو اعتبارنامه‌ان -> رمزنگاری‌شده.
    bale_pay_bot_token_encrypted: str = ""
    bale_pay_provider_token_encrypted: str = ""
    bale_pay_enabled: bool = False
    bale_pay_link_mode: str = "auto"  # auto = اول لینکِ مستقیم، نه → دیپ‌لینکِ ربات
    # رسیدِ کارت‌به‌کارت: تأیید همیشه دستی است؛ برنامه فقط هشدار می‌دهد و رسید را نشان می‌دهد.
    receipt_check_enabled: bool = True  # مشتری بعد از «پرداخت کردم» رسید بفرستد (متنی یا عکس)
    receipt_amount_check: bool = True  # مبلغِ رسید با مبلغِ سفارش تطبیق داده بشه و اختلاف برجسته بشه

    reservation_minutes: int = 15  # مدت رزرو موجودی برای سفارشِ در انتظار پرداخت
    auto_confirm_gateway_payments: bool = True  # پرداختِ تاییدشده‌ی درگاه (بله‌پی) = تایید خودکار
    # اعلانِ فوری به مالک/مدیرها وقتی مشتری پرداخت را اعلام یا رسید فرستاد (۱.۰.۰: خواستهٔ مالک)
    alert_on_payment_claim: bool = True
    # پیامِ کوتاهِ «🚚 ارسال شد (+کد رهگیری)» به مشتری وقتی مالک سفارشِ تأییدشده را ارسال می‌زند.
    # پیش‌فرض خاموش — ربات بی‌اراده‌ی مالک پیامِ پیش‌قدم نمی‌ده؛ فقط یک سوییچِ ساده، نه راز.
    notify_on_shipment: bool = False

    # روش‌هایِ ارسالِ مالک — ``[{id, name, price_irr, free_over_irr, active}]``. خالی (پیش‌فرض)
    # یعنی هیچ‌وقت از مشتری «انتخابِ ارسال» پرسیده نمی‌شه و مبلغ هیچ سفارشی عوض نمی‌شه؛ مثلِ شماره
    # کارت، تنظیماتی است و رمزنگاری نمی‌شه.
    shipping_methods: list = field(default_factory=list)

    # چتِ شخصیِ مالک روی تلگرام — برای اعلانِ سفارشِ جدید/نیازمندِ تایید و فرمان‌های
    # /confirm و /reject. با کدِ یک‌بارمصرف ثبت می‌شه (owner_console).
    owner_chats: dict = field(default_factory=dict)

    # --- متن‌ها و زبانِ ربات ---
    bot_language: str = "fa"  # fa | en | auto (بر اساسِ language_code کاربر)
    bot_texts: dict = field(default_factory=dict)  # override متن‌ها: {"fa": {کلید: متن}, "en": {...}}

    # --- فروشگاهِ دکمه‌ای، چک‌اوت و دکمه‌های سفارشی ---
    catalog_page_size: int = 6  # ۲..۱۲
    max_qty_per_item: int = 10  # سقفِ تعدادِ هر محصول در یک سفارش
    checkout_fields: list = field(default_factory=list)  # خالی = پیش‌فرض (checkout_fields.default_fields)
    custom_buttons: list = field(default_factory=list)
    faq_items: list = field(default_factory=list)  # [{"q": ..., "a": ...}]
    working_hours: dict = field(default_factory=dict)  # فقط برای پیامِ مناسبِ پشتیبانی؛ working_hours.py
    handoff_timeout_hours: int = 24  # بسته‌شدنِ خودکارِ گفتگوی پشتیبانی بعد از بی‌فعالیتی

    # --- سقفِ مصرفِ AI؛ ۰ = بدونِ سقف. فقط پاسخ‌های مدل رو محدود می‌کنه، نه دکمه/پرداخت ---
    max_ai_messages_per_chat_per_day: int = 200
    max_ai_messages_per_day_total: int = 2000
    ai_kill_switch: bool = False  # قطعِ اضطراریِ AI برای همه

    # --- حریمِ خصوصی ---
    retention_days: int = 0  # ۰ = نگه‌دار؛ N = حذفِ مکالمه‌های قدیمی‌تر از N روز و ناشناس‌سازیِ سفارش‌های بسته‌شده‌ی قدیمی
    ai_disclosure_enabled: bool = True  # خطِ «این ربات با هوش مصنوعی کار می‌کنه» در /start (متن: privacy.ai_disclosure)

    # --- به‌روزرسانی: فقط GitHub، بدونِ سرور ---
    update_check_enabled: bool = True  # بررسیِ خودکارِ نسخه‌ی تازه (هنگامِ شروع و هر ۲۴ ساعتِ اجرا)
    update_dismissed_version: str = ""  # نسخه‌ای که کاربر «بعداً» زده؛ تا نسخه‌ی بعدی بنر نمی‌آید
    update_last_check_ts: int = 0

    # --- شروعِ تازه: بعد از انتخابِ «ادامه با داده‌ی قبلی» یا «شروعِ تازه» دیگه پرسیده نمی‌شه ---
    data_acknowledged: bool = False

    # --- نشانِ سازنده در بیوگرافیِ ربات ---
    bot_bio_text: str = ""  # متنِ فروشنده (بدونِ خطِ اعتبار)؛ خطِ اعتبار همیشه بعدش اضافه می‌شه
    bot_bio_confirmed: bool = False  # بارِ اولِ اتصال، فروشنده بیوگرافیِ فعلی رو دید و تأیید کرد

    # --- عضویتِ اجباریِ کانال و پیامِ همگانی ---
    required_channels_enabled: bool = False
    required_channels: list = field(default_factory=list)  # [{platform, channel, title, link}] — channel_gate.normalize
    required_channels_scope: str = "both"  # "shop" (منو/سبد/سفارش) | "ai" (گفتگو با AI) | "both"
    broadcast_footer_enabled: bool = True  # پانویسِ «برای توقف /stop» (پیش‌فرض روشن)
    broadcast_daily_cap: int = 3  # حداکثرِ تعدادِ ارسالِ همگانی در هر ۲۴ ساعت
    broadcast_rate_telegram: int = 20  # پیام در ثانیه (امن)

    # --- بهینه‌سازیِ توکن (مدلِ محلی روی سخت‌افزارِ ضعیف حساس‌ه) ---
    token_opt_history_window: bool = True  # پنجره‌ی توکنیِ تاریخچه (نه کاراکتری)
    token_opt_max_tokens: bool = True  # سقفِ خروجی به‌تناسبِ پرسش

    # --- مالی و فاکتور — ابزارِ کمکی، نه جایگزینِ حسابدارِ رسمی ---
    invoice_seller_name: str = ""
    invoice_seller_legal_name: str = ""
    invoice_seller_national_id: str = ""
    invoice_seller_address: str = ""
    invoice_seller_phone: str = ""
    invoice_logo_path: str = ""  # PNG/JPG، حداکثر ۳۰۰ کیلوبایت (اختیاری)
    invoice_color: str = "#1F6FEB"
    invoice_footer: str = ""
    invoice_vat_enabled: bool = False
    invoice_vat_rate_bp: int = 1000  # ۱۰٪ (نرخِ عمومیِ ۱۴۰۵؛ قابل‌تغییر). قیمت‌ها «با مالیات» حساب می‌شن
    invoice_number_prefix: str = "F"
    invoice_number_start: int = 1
    invoice_number_use_year: bool = True
    invoice_paper: str = "A4"  # A4 | A5
    invoice_digits: str = "fa"  # fa | en
    invoice_auto_send: str = "after_confirm"  # off | after_confirm (پیش‌فرض: فاکتورِ PDF بعد از تأییدِ سفارش برای مشتری می‌رود)
    invoice_send_owner_copy: bool = False
    finance_fee_bp_bale_pay: int = 0  # کارمزدِ درگاه (basis point؛ ۱٪ = ۱۰۰)
    finance_unit: str = "toman"  # toman | irr (فقط نمایش)
    finance_manager_access: bool = False  # مالک می‌تونه دسترسیِ «مالی» را به نقشِ «مدیر» بده

    low_stock_threshold: int = 3  # موجودیِ کم ⇒ «نیاز به توجه»؛ ۰ = خاموش
    quickstart_dismissed: bool = False  # چک‌لیستِ «شروعِ سریع» بالای صفحه‌ی خانه بسته شد

    # --- توکن ربات تلگرام: رمزنگاری‌شده روی دیسک، متن‌ساده فقط در حافظه ---
    def set_telegram_token(self, raw: str) -> None:
        self.telegram_bot_token_encrypted = crypto.encrypt(raw.strip()) if raw and raw.strip() else ""

    def get_telegram_token(self) -> str:
        return crypto.decrypt(self.telegram_bot_token_encrypted) if self.telegram_bot_token_encrypted else ""

    def set_telegram_proxy(self, raw: str) -> None:
        self.telegram_proxy_encrypted = crypto.encrypt(raw.strip()) if raw and raw.strip() else ""

    def get_telegram_proxy(self) -> str:
        return crypto.decrypt(self.telegram_proxy_encrypted) if self.telegram_proxy_encrypted else ""

    def set_telegram_proxy_sub_url(self, url: str) -> None:
        self.telegram_proxy_sub_url_encrypted = crypto.encrypt(url.strip()) if url and url.strip() else ""

    def get_telegram_proxy_sub_url(self) -> str:
        return crypto.decrypt(self.telegram_proxy_sub_url_encrypted) if self.telegram_proxy_sub_url_encrypted else ""

    def set_telegram_proxy_sub_cache(self, text: str) -> None:
        self.telegram_proxy_sub_cache_encrypted = crypto.encrypt(text) if text and text.strip() else ""

    def get_telegram_proxy_sub_cache(self) -> str:
        return crypto.decrypt(self.telegram_proxy_sub_cache_encrypted) if self.telegram_proxy_sub_cache_encrypted else ""

    def combined_telegram_proxy_text(self) -> str:
        """لیستِ دستیِ کاربر + کشِ اشتراک — استخرِ واقعیِ ربات تلگرام."""
        manual, cache = self.get_telegram_proxy(), self.get_telegram_proxy_sub_cache()
        return "\n".join(p for p in (manual.strip(), cache.strip()) if p)

    # --- اعتبارنامه‌های بله‌پی ---
    def set_bale_pay_bot_token(self, raw: str) -> None:
        self.bale_pay_bot_token_encrypted = crypto.encrypt(raw.strip()) if raw and raw.strip() else ""

    def get_bale_pay_bot_token(self) -> str:
        return crypto.decrypt(self.bale_pay_bot_token_encrypted) if self.bale_pay_bot_token_encrypted else ""

    def set_bale_pay_provider_token(self, raw: str) -> None:
        self.bale_pay_provider_token_encrypted = crypto.encrypt(raw.strip()) if raw and raw.strip() else ""

    def get_bale_pay_provider_token(self) -> str:
        return (
            crypto.decrypt(self.bale_pay_provider_token_encrypted)
            if self.bale_pay_provider_token_encrypted
            else ""
        )

    def bale_pay_configured(self) -> bool:
        """هر دو اعتبارنامه لازم است: توکنِ رباتِ پرداخت + توکنِ درگاه."""
        return bool(self.bale_pay_enabled and self.get_bale_pay_bot_token() and self.get_bale_pay_provider_token())

    def ensure_default_prompt(self) -> None:
        if not self.system_prompt and self.business_mode:
            self.system_prompt = default_prompt(self.business_mode, self.language)

    def get_model_storage_dir(self) -> Path:
        if self.model_storage_path:
            return Path(self.model_storage_path)
        return get_app_data_dir() / "models"


def _nonneg_int(value) -> int:
    """هر ورودیِ نامعتبر/منفی → ۰ (سقفِ پایینِ هر مبلغِ ریالیِ این قابلیت)."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def normalize_shipping_methods(raw: list) -> list:
    """فهرستِ روش‌هایِ ارسال را به شکلِ استانداردِ ``{id, name, price_irr, free_over_irr, active}`` درمی‌آورد.

    هر ردیفِ بی‌نام حذف می‌شه؛ ``id``هایِ تکراری (دست‌کاریِ settings.json) یکی می‌شن؛ مبالغ به عددِ
    صحیحِ غیرمنفی clamp می‌شن. هیچ‌وقت داده‌یِ خامِ صفحه یا دیسک مستقیم به سبد/سفارش نمی‌رسه."""
    if not isinstance(raw, list):
        return []
    out: list = []
    seen: set = set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:60]
        if not name:
            continue
        method_id = str(item.get("id") or "").strip()[:32] or f"m{i + 1}"
        if method_id in seen:
            continue
        seen.add(method_id)
        out.append({
            "id": method_id,
            "name": name,
            "price_irr": _nonneg_int(item.get("price_irr")),
            "free_over_irr": _nonneg_int(item.get("free_over_irr")),
            "active": bool(item.get("active", True)),
        })
    return out


def active_shipping_methods(settings) -> list:
    """فقط روش‌هایِ روشن — معیارِ اینکه اصلاً مرحله‌ی «انتخابِ ارسال» به مشتری نشان داده بشه یا نه."""
    return [m for m in normalize_shipping_methods(getattr(settings, "shipping_methods", []) or []) if m["active"]]


def find_shipping_method(settings, method_id: str) -> Optional[dict]:
    """روشِ فعالِ با این ``id``، یا None (حذف/غیرفعال‌شدنِ میانه‌ی راه یعنی دیگر قابل‌انتخاب نیست)."""
    wanted = str(method_id or "")
    for m in active_shipping_methods(settings):
        if m["id"] == wanted:
            return m
    return None


def shipping_cost_irr(method: dict, subtotal_after_discount: int) -> int:
    """هزینه‌ی واقعیِ این روش برای این سبد — ``free_over_irr`` با جمعِ کلِ *بعد از تخفیف* سنجیده می‌شه."""
    free_over = int(method.get("free_over_irr") or 0)
    if free_over > 0 and subtotal_after_discount >= free_over:
        return 0
    return int(method.get("price_irr") or 0)


def _settings_path() -> Path:
    return get_app_data_dir() / _SETTINGS_FILE_NAME


def _quarantine_corrupt(path: Path) -> None:
    """settings.json خراب بود: به‌جای اینکه بی‌صدا با پیش‌فرض‌ها جایگزین (و با اولین ذخیره‌ی بعدی
    برای همیشه گم) بشه، کنارش می‌ذاریم تا کاربر بتونه بازیابیش کنه."""
    target = path.with_name(f"settings.corrupt-{time.strftime('%Y%m%d-%H%M%S')}.json")
    try:
        os.replace(path, target)
        logger.warning("settings.json خراب بود؛ نسخه‌ی خراب کنارِ برنامه ذخیره شد: %s", target.name)
    except OSError:
        logger.warning("settings.json خراب بود و جابه‌جا نشد", exc_info=True)


def _migrate_keys(data: dict) -> dict:
    """کلیدهایِ نسخه‌هایِ قدیمی: نام‌هایِ تغییرکرده منتقل می‌شن، حذف‌شده‌ها رد می‌شن.
    کلیدِ تازه اگه از قبل مقدارِ غیرپیش‌فرض داشت، بازنویسی نمی‌شه (دستِ کاربر بالاتر از ارتقا)."""
    for old, new in _LEGACY_RENAMES.items():
        if old not in data:
            continue
        value = data.pop(old)
        if value and not data.get(new):
            data[new] = value
    if data.get("model_id") in _LEGACY_TIERS:
        data["model_id"] = _LEGACY_TIERS[data["model_id"]]
    for gone in _LEGACY_IGNORED:
        data.pop(gone, None)
    return data


def load_settings() -> AppSettings:
    path = _settings_path()
    if not path.exists():
        return AppSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("settings.json باید یه شیء JSON باشه")
    except (ValueError, UnicodeDecodeError):  # JSONDecodeError زیرمجموعه‌ی ValueError‌ه
        _quarantine_corrupt(path)
        return AppSettings()
    except OSError:
        return AppSettings()
    data = _migrate_keys(data)
    valid_keys = {f.name for f in fields(AppSettings)}
    known = {k: v for k, v in data.items() if k in valid_keys}
    settings = AppSettings(**known)
    settings.shipping_methods = normalize_shipping_methods(settings.shipping_methods)  # ورودیِ خامِ دیسک هرگز به سبد/سفارش نمی‌رسه
    return settings


def save_settings(settings: AppSettings) -> None:
    """ذخیره‌ی اتمیک: اول فایل موقت، بعد جایگزینی — قطعِ برق/کرش وسط نوشتن، فایلِ سالمِ قبلی
    رو نیمه‌کاره نمی‌ذاره."""
    path = _settings_path()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def reload_into(state: AppSettings) -> None:
    """تنظیماتِ دیسک رو دوباره می‌خونه و *همون نمونه‌ی* ``state`` رو به‌روز می‌کنه (بقیه‌ی برنامه —
    مدیر ربات‌ها، سرویس پرداخت — به همین نمونه ارجاع دارن، پس جایگزینی‌اش ممکن نیست)."""
    fresh = load_settings()
    for f in fields(fresh):
        setattr(state, f.name, getattr(fresh, f.name))
