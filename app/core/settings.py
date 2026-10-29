"""مدیریت تنظیمات محلی برنامه: بارگذاری، ذخیره، و رمزنگاری فیلدهای حساس."""

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


@dataclass
class AppSettings:
    user_name: str = ""
    language: str = "fa"
    business_mode: Optional[str] = None  # "store" | "consultant"
    ai_mode: Optional[str] = None  # "api" | "local"
    api_base_url: str = ""
    api_key_encrypted: str = ""
    api_model_name: str = "gpt-4o-mini"  # قابل تغییر توسط کاربر — سرویس‌های مختلف اسم مدل متفاوتی می‌خوان
    model_tier: Optional[str] = None  # "small" | "medium" | "large" (برای حالت محلی)
    model_storage_path: str = ""  # اگه خالی باشه، پیش‌فرض get_app_data_dir()/models استفاده می‌شه
    system_prompt: str = ""
    onboarding_complete: bool = False

    # --- فاز ۳: اتصال به تلگرام و بله (همه‌ی اسرار رمزنگاری‌شده روی دیسک) ---
    telegram_bot_token_encrypted: str = ""
    bale_bot_token_encrypted: str = ""
    telegram_enabled: bool = True
    bale_enabled: bool = True
    # پروکسی اختیاری تلگرام (تلگرام برای خیلی از کاربرای ایرانی بدون پروکسی/VPN
    # در دسترس نیست). آدرس می‌تونه user:pass داشته باشه، پس مثل توکن رمزنگاری می‌شه.
    telegram_proxy_encrypted: str = ""
    # --- ۱.۰.۰ (R6): اشتراکِ پروکسی — لینکِ خودِ کاربر؛ کش جدا از لیستِ دستی و رمزنگاری‌شده (credential داره) ---
    telegram_proxy_sub_url_encrypted: str = ""
    telegram_proxy_sub_cache_encrypted: str = ""
    telegram_proxy_sub_hours: int = 6  # ۰ = فقط دستی
    telegram_proxy_sub_updated_ts: int = 0
    telegram_proxy_sub_error: str = ""
    telegram_proxy_best_check_minutes: int = 10
    bot_autostart: bool = True  # با باز شدن برنامه، ربات‌های فعال خودکار روشن بشن

    # --- تنظیمات حافظه‌ی مکالمه (قابل‌تنظیم توسط کاربر، نه فقط روشن/خاموشِ هر مکالمه) ---
    memory_history_limit: int = 20  # چند پیام اخیر به‌عنوان زمینه به AI فرستاده بشه
    memory_expire_hours: int = 0  # ۰ = هیچ‌وقت؛ بعد از این‌همه ساعت بی‌فعالیتی، مکالمه انگار تازه شروع شده

    # --- فاز ۴: پرداخت (فقط حالت فروشگاه) ---
    # کارت‌به‌کارت دستی: شماره کارت قراره مستقیم به مشتری نشون داده بشه (نه
    # یه راز)، پس رمزنگاری نمی‌شه — دقیقاً مثل اینکه خودِ فروشنده شماره کارتش
    # رو توی یه کانال تلگرام پابلیک بذاره.
    card_to_card_number: str = ""
    card_to_card_holder_name: str = ""
    # provider_token واقعاً یه اعتبارنامه‌ست (مثل کلید API) -> رمزنگاری‌شده.
    bale_pay_provider_token_encrypted: str = ""
    bale_pay_enabled: bool = False
    # زرین‌پال: مرچنت‌کد (۳۶ کاراکتر) مثل توکن‌ها رمزنگاری می‌شه؛ پولِ مشتری مستقیم
    # به حسابِ زرین‌پالِ خودِ صاحب فروشگاه می‌ره
    zarinpal_merchant_id_encrypted: str = ""
    zarinpal_enabled: bool = False
    zarinpal_sandbox: bool = False  # حالت آزمایشی زرین‌پال (پرداختِ واقعی انجام نمی‌شه)
    zarinpal_callback_url: str = ""  # اختیاری؛ خالی = لینک خودِ ربات (t.me / ble.ir)
    # ادمینِ هوشمند / سفارش‌گیری
    reservation_minutes: int = 15  # مدت رزرو موجودی برای سفارشِ در انتظار پرداخت
    auto_confirm_gateway_payments: bool = True  # پرداختِ تاییدشده‌ی درگاه (بله‌پی/زرین‌پال) = تایید خودکار
    require_customer_phone: bool = False  # هوش مصنوعی قبل از ثبت سفارش شماره تماس بگیره
    require_customer_address: bool = False  # هوش مصنوعی قبل از ثبت سفارش آدرس تحویل بگیره
    # چتِ شخصیِ مالک روی هر پیام‌رسان ({"telegram": "123", "bale": "456"}) — برای اعلانِ سفارشِ
    # جدید/نیازمندِ تایید و فرمان‌های /confirm و /reject. با کدِ یک‌بارمصرف ثبت می‌شه (owner_console).
    owner_chats: dict = field(default_factory=dict)

    # --- ۱.۰.۰: متن‌ها و زبانِ ربات (R13) ---
    bot_language: str = "fa"  # fa | en | auto (بر اساسِ language_code کاربر)
    bot_texts: dict = field(default_factory=dict)  # override متن‌ها: {"fa": {کلید: متن}, "en": {...}}

    # --- ۱.۰.۰: حالت‌ها، فروشگاهِ دکمه‌ای، چک‌اوت و دکمه‌های سفارشی (R1–R5) ---
    shop_mode: str = "shop_buttons"  # shop_buttons | shop_ai | faq_support | lead_capture | advisor (مشاور همیشه advisor)
    shop_mode_overrides: dict = field(default_factory=dict)  # {"telegram": "shop_ai", ...}
    catalog_page_size: int = 6  # ۲..۱۲
    max_qty_per_item: int = 10  # سقفِ تعدادِ هر محصول در یک سفارش
    checkout_fields: list = field(default_factory=list)  # خالی = پیش‌فرض (checkout_fields.default_fields)
    custom_buttons: list = field(default_factory=list)  # R5
    faq_items: list = field(default_factory=list)  # [{"q": ..., "a": ...}]
    working_hours: dict = field(default_factory=dict)  # R5: فقط برای پیامِ مناسبِ پشتیبانی؛ working_hours.py
    handoff_timeout_hours: int = 24  # بسته‌شدنِ خودکارِ گفتگوی پشتیبانی بعد از بی‌فعالیتی

    # --- ۱.۰.۰: سقفِ مصرفِ AI (R10-۳)؛ ۰ = بدونِ سقف. فقط پاسخ‌های AI رو محدود می‌کنه، نه دکمه/پرداخت ---
    max_ai_messages_per_chat_per_day: int = 200
    max_ai_messages_per_day_total: int = 2000
    ai_kill_switch: bool = False  # قطعِ اضطراریِ AI برای همه

    # --- ۱.۰.۰: حریمِ خصوصی (R10-۴) ---
    retention_days: int = 0  # ۰ = نگه‌دار؛ N = حذفِ مکالمه‌های قدیمی‌تر از N روز و ناشناس‌سازیِ سفارش‌های بسته‌شده‌ی قدیمی
    ai_disclosure_enabled: bool = True  # خطِ «این ربات با هوش مصنوعی کار می‌کنه» در /start (متن: privacy.ai_disclosure)

    # --- ۱.۱: به‌روزرسانی (N14a): فقط GitHub، بدونِ سرور ---
    update_check_enabled: bool = True  # بررسیِ خودکارِ نسخه‌ی تازه (هنگامِ شروع و هر ۲۴ ساعتِ اجرا)
    update_dismissed_version: str = ""  # نسخه‌ای که کاربر «بعداً» زده؛ تا نسخه‌ی بعدی بنر نمی‌آید
    update_last_check_ts: int = 0

    # --- ۱.۱: شروعِ تازه (N2): بعد از انتخابِ «ادامه با داده‌ی قبلی» یا «شروعِ تازه» دیگه پرسیده نمی‌شه ---
    data_acknowledged: bool = False

    # --- ۱.۱: نشانِ سازنده در بیوگرافیِ ربات (N17) ---
    bot_bio_text: str = ""  # متنِ فروشنده (بدونِ خطِ اعتبار)؛ خطِ اعتبار همیشه بعدش اضافه می‌شه
    bot_bio_confirmed: bool = False  # بارِ اولِ اتصال، فروشنده بیوگرافیِ فعلی رو دید و تأیید کرد
    bale_bio_supported: Optional[bool] = None  # None = هنوز آزمایش نشده؛ False = بله setMyShortDescription رو پشتیبانی نمی‌کنه

    # --- ۱.۱ (فازِ ۳): عضویتِ اجباریِ کانال (N13) و پیامِ همگانی (N7) ---
    required_channels_enabled: bool = False
    required_channels: list = field(default_factory=list)  # [{platform, channel, title, link}] — اعتبارسنجی با channel_gate.normalize
    required_channels_scope: str = "both"  # "shop" (منو/سبد/سفارش) | "ai" (گفتگو با AI) | "both"
    broadcast_footer_enabled: bool = True  # پانویسِ «برای توقف /stop» (پیش‌فرض روشن)
    broadcast_daily_cap: int = 3  # حداکثرِ تعدادِ ارسالِ همگانی در هر ۲۴ ساعت
    broadcast_rate_telegram: int = 20  # پیام در ثانیه (امن)
    broadcast_rate_bale: int = 5  # بله: پیش‌فرضِ محتاطانه

    # --- ۱.۱ (فازِ ۵): چند API و مدلِ پشتیبان (N16)، مصرف و هزینه (N1)، بهینه‌سازیِ توکن (N18) ---
    # هر ارائه‌دهنده: {id, name, kind, base_url, api_key_encrypted, timeout, enabled, models:[{name, enabled, max_context_tokens,
    # tools_supported, price_in, price_out}]}. خالی = تنظیماتِ قدیمیِ تک‌API (api_*) خودکار ارائه‌دهنده‌ی ۱ حساب می‌شه (ai_providers.parse_providers).
    ai_providers: list = field(default_factory=list)
    ai_attempt_timeout: int = 15  # ثانیه، هر تلاش
    ai_total_timeout: int = 45  # ثانیه، کلِ یک پاسخ
    ai_max_targets: int = 3  # حداکثرِ (ارائه‌دهنده، مدل) که برای یک پاسخ امتحان می‌شه
    ai_provider_concurrency: int = 4  # درخواستِ هم‌زمانِ مجاز به‌ازای هر ارائه‌دهنده
    ai_local_fallback: bool = False  # مدلِ محلی آخرین پناهِ زنجیره (فقط اگه دانلود شده باشه)
    usd_to_irr_rate: str = ""  # تومان به‌ازای ۱ دلار (کاربر وارد می‌کنه؛ پیش‌فرضِ ساختگی نداریم)
    cost_display_unit: str = "usd"  # usd | irr | toman
    ai_budget_monthly_usd: str = ""  # خالی = بدونِ بودجه
    ai_budget_action: str = "warn"  # warn | stop | local
    token_opt_history_window: bool = True  # پنجره‌ی توکنیِ تاریخچه (نه کاراکتری)
    token_opt_max_tokens: bool = True  # سقفِ خروجی به‌تناسبِ پرسش
    token_opt_response_cache: bool = False  # کشِ پاسخِ یکسان (پیش‌فرض خاموش؛ ai_cache.py)
    token_opt_cache_ttl_minutes: int = 60  # ۱..۱۴۴۰

    # --- ۱.۱ (فازِ ۶): مالی و فاکتور (N19) — ابزارِ کمکی، نه جایگزینِ حسابدارِ رسمی ---
    invoice_seller_name: str = ""  # نامِ فروشگاه (روی فاکتور)
    invoice_seller_legal_name: str = ""  # نامِ حقیقی/حقوقی (اختیاری)
    invoice_seller_national_id: str = ""  # شناسه‌ی ملی/اقتصادی (اختیاری)
    invoice_seller_address: str = ""
    invoice_seller_phone: str = ""
    invoice_logo_path: str = ""  # PNG/JPG، حداکثر ۳۰۰ کیلوبایت (اختیاری)
    invoice_color: str = "#1F6FEB"
    invoice_footer: str = ""
    invoice_vat_enabled: bool = False
    invoice_vat_rate_bp: int = 1000  # ۱۰٪ (نرخِ عمومیِ ۱۴۰۵ طبقِ سازمانِ امورِ مالیاتی؛ قابل‌تغییر). قیمت‌ها «با مالیات» حساب می‌شن
    invoice_number_prefix: str = "F"
    invoice_number_start: int = 1
    invoice_number_use_year: bool = True  # سالِ جلالی در شماره (شمارنده هر سال از «شماره‌ی شروع» دوباره می‌شه)
    invoice_paper: str = "A4"  # A4 | A5
    invoice_digits: str = "fa"  # fa | en
    invoice_auto_send: str = "off"  # off | after_confirm
    invoice_send_owner_copy: bool = False
    finance_fee_bp_bale_pay: int = 0  # کارمزدِ درگاه (basis point؛ ۱٪ = ۱۰۰)
    finance_fee_bp_zarinpal: int = 0
    finance_unit: str = "toman"  # toman | irr (فقط نمایش)
    finance_manager_access: bool = False  # مالک می‌تونه دسترسیِ «مالی» را به نقشِ «مدیر» بده

    low_stock_threshold: int = 3  # A7: وقتی موجودیِ محصولِ فیزیکی بعد از تأیید به این عدد یا کمتر رسید «نیاز به توجه»؛ ۰ = خاموش
    quickstart_dismissed: bool = False  # N10: چک‌لیستِ «شروعِ سریع» بالای صفحه‌ی خانه بسته شد

    # --- کلید API: رمزنگاری‌شده روی دیسک، متن‌ساده فقط در حافظه ---
    def set_api_key(self, raw_key: str) -> None:
        self.api_key_encrypted = crypto.encrypt(raw_key) if raw_key else ""

    def get_api_key(self) -> str:
        return crypto.decrypt(self.api_key_encrypted) if self.api_key_encrypted else ""

    # --- توکن ربات‌ها و پروکسی: همون الگوی کلید API ---
    def set_telegram_token(self, raw: str) -> None:
        self.telegram_bot_token_encrypted = crypto.encrypt(raw.strip()) if raw and raw.strip() else ""

    def get_telegram_token(self) -> str:
        return crypto.decrypt(self.telegram_bot_token_encrypted) if self.telegram_bot_token_encrypted else ""

    def set_bale_token(self, raw: str) -> None:
        self.bale_bot_token_encrypted = crypto.encrypt(raw.strip()) if raw and raw.strip() else ""

    def get_bale_token(self) -> str:
        return crypto.decrypt(self.bale_bot_token_encrypted) if self.bale_bot_token_encrypted else ""

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

    def set_bale_pay_provider_token(self, raw: str) -> None:
        self.bale_pay_provider_token_encrypted = crypto.encrypt(raw.strip()) if raw and raw.strip() else ""

    def set_zarinpal_merchant_id(self, raw: str) -> None:
        self.zarinpal_merchant_id_encrypted = crypto.encrypt(raw.strip()) if raw and raw.strip() else ""

    def get_zarinpal_merchant_id(self) -> str:
        return crypto.decrypt(self.zarinpal_merchant_id_encrypted) if self.zarinpal_merchant_id_encrypted else ""

    def get_bale_pay_provider_token(self) -> str:
        return (
            crypto.decrypt(self.bale_pay_provider_token_encrypted)
            if self.bale_pay_provider_token_encrypted
            else ""
        )

    def ensure_default_prompt(self) -> None:
        if not self.system_prompt and self.business_mode:
            self.system_prompt = default_prompt(self.business_mode, self.language)

    def get_model_storage_dir(self) -> Path:
        if self.model_storage_path:
            return Path(self.model_storage_path)
        return get_app_data_dir() / "models"


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
    valid_keys = {f.name for f in fields(AppSettings)}
    known = {k: v for k, v in data.items() if k in valid_keys}
    return AppSettings(**known)


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
