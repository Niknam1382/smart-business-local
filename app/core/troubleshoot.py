"""
عیب‌یابِ «ربات جواب نمی‌ده؟» (N10): چند بررسیِ خودکار، هر کدام با نتیجه و راه‌حلِ ساده (و لینک به مقاله‌ی راهنما).

همه‌ی پروب‌های شبکه تزریق‌پذیرن (تست بدونِ اینترنت)؛ هیچ توکنی در خروجی نمی‌آد؛ هر پروبِ خراب فقط همان یک ردیف را «نامشخص» می‌کنه.
"""

from __future__ import annotations

import asyncio
import shutil
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from app.core import jalali

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"
CLOCK_SKEW_SECONDS = 120
MIN_FREE_BYTES = 200 * 1024 * 1024
DATE_URLS = {"telegram": "https://api.telegram.org"}


@dataclass(frozen=True)
class Finding:
    key: str
    status: str
    title: str
    detail: str
    article: str = ""  # شناسه‌ی مقاله‌ی راهنما


async def http_server_time(url: str, timeout: float = 8.0) -> Optional[float]:
    """زمانِ سرور (UTC یونیکس) از هدرِ ``Date``؛ ``None`` اگه وصل نشد."""
    import calendar
    import email.utils

    import aiohttp

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.head(url, allow_redirects=False) as resp:
                parsed = email.utils.parsedate(resp.headers.get("Date", ""))
                return float(calendar.timegm(parsed)) if parsed else None
    except Exception:  # noqa: BLE001
        return None


def _finding_for_token(platform: str, status) -> Finding:
    art = "ts-token-invalid" if status.error_code == "invalid_token" else "ts-no-connection"
    if status.connected:
        return Finding(f"{platform}_token", OK, "توکنِ تلگرام", f"درسته؛ ربات «@{status.username}» شناسایی شد.")
    if status.error_code == "invalid_token":
        return Finding(f"{platform}_token", FAIL, "توکنِ تلگرام", "توکن نامعتبره؛ از BotFather دوباره کپی کن (بدونِ فاصله‌ی اضافه).", art)
    if status.error_code == "bad_proxy":
        return Finding(f"{platform}_token", FAIL, "پروکسیِ تلگرام", "آدرسِ پروکسی درست نیست؛ فقط SOCKS5 یا HTTP.", "ts-proxy")
    return Finding(f"{platform}_token", FAIL, "اتصال به تلگرام", "به سرورِ تلگرام وصل نشد؛ اینترنت/VPN/پروکسی را بررسی کن.", art)


async def run(
    settings,
    *,
    bots_running: bool = False,
    check_telegram: Optional[Callable[[str, list], Awaitable]] = None,
    webhook_probe: Optional[Callable[[str, str], Awaitable[str]]] = None,
    server_time: Optional[Callable[[str], Awaitable[Optional[float]]]] = None,
    proxy_probe: Optional[Callable[[str, str], Awaitable]] = None,
    data_dir=None,
    now: Callable[[], float] = time.time,
) -> list:
    """فهرستِ ``Finding``. پروب‌ها پیش‌فرض واقعی‌اند؛ تست‌ها جایگزین می‌کنن."""
    from app.core import proxy_pool, telegram_adapter

    check_telegram = check_telegram or (lambda tok, proxies: telegram_adapter.check_token_via_proxies(tok, proxies))
    webhook_probe = webhook_probe or (lambda tok, proxy: telegram_adapter.webhook_url(tok, proxy))
    proxy_probe = proxy_probe or (lambda tok, proxy: telegram_adapter.check_token(tok, proxy))
    server_time = server_time or http_server_time
    out: list = []

    # تلگرام و بله هر دو پیام‌رسانِ گفتگویند (قلم ۲۴)؛ «بله‌پی» درگاهِ پرداختِ جداست.
    tg_token = settings.get_telegram_token()
    wants_tg = bool(settings.telegram_enabled and tg_token)
    if not wants_tg:
        out.append(Finding("no_bot", FAIL, "ربات", "هیچ رباتی با توکنِ تلگرام فعال نشده؛ در صفحه‌ی «ربات‌ها» توکن را بزن و «تست اتصال».", "bot-token"))
    elif not bots_running:
        out.append(Finding("running", WARN, "روشن‌بودنِ ربات", "ربات الان خاموشه؛ مشتری جواب نمی‌گیره. در صفحه‌ی «ربات‌ها» روشنش کن و برنامه را باز نگه دار.", "ts-bot-silent"))
    else:
        out.append(Finding("running", OK, "روشن‌بودنِ ربات", "ربات روشنه."))

    # ساعتِ سیستم (اگه ساعت غلط باشه TLS/توکن‌ها عجیب خطا می‌دن)
    skew = None
    if wants_tg:
        server_ts = await server_time(DATE_URLS["telegram"])
        if server_ts is not None:
            skew = abs(now() - server_ts)
    if skew is not None and skew > CLOCK_SKEW_SECONDS:
        out.append(Finding("clock", FAIL, "ساعتِ سیستم", f"ساعتِ کامپیوترت حدودِ {jalali.fa_digits(int(skew // 60))} دقیقه با ساعتِ واقعی فرق داره؛ ساعت/منطقه‌ی زمانی را خودکار کن.", "ts-clock"))
    elif skew is not None:
        out.append(Finding("clock", OK, "ساعتِ سیستم", "درسته."))
    else:
        out.append(Finding("clock", SKIP, "ساعتِ سیستم", "بررسی نشد (اینترنت/سرور در دسترس نبود).", "ts-clock"))

    if wants_tg:
        proxies = proxy_pool.parse_proxy_text(settings.combined_telegram_proxy_text()).urls
        status = await check_telegram(tg_token, proxies)
        out.append(_finding_for_token("telegram", status))
        if status.connected:
            try:
                url = await webhook_probe(tg_token, proxies[0] if proxies else "")
            except Exception:  # noqa: BLE001
                url = None
            if url:
                out.append(Finding("webhook", FAIL, "تداخلِ webhook", "برای این ربات یک webhook فعاله و با دریافتِ پیام در برنامه تداخل داره (خطای ۴۰۹)؛ webhook را در BotFather/API حذف کن.", "ts-webhook"))
            elif url == "":
                out.append(Finding("webhook", OK, "تداخلِ webhook", "webhook‌ای فعال نیست."))
        elif status.error_code == "no_connection" and proxies:
            works = []
            for proxy in proxies[:6]:
                res = await proxy_probe(tg_token, proxy)
                if res.connected:
                    works.append(proxy)
            detail = f"{len(works)} از {min(len(proxies), 6)} پروکسی کار می‌کنه." if works else "هیچ‌کدام از پروکسی‌ها وصل نشد؛ یک پروکسی دیگر یا VPN را امتحان کن."
            out.append(Finding("proxy", OK if works else FAIL, "پروکسی‌ها", detail, "ts-proxy"))
        elif status.error_code == "no_connection" and not proxies:
            out.append(Finding("proxy", WARN, "پروکسی", "اگه تلگرام در کشورت بدونِ VPN باز نمی‌شه، در صفحه‌ی «ربات‌ها» پروکسی/اشتراکِ پروکسی بذار.", "ts-proxy"))
    # بله‌پی: فقط «درگاه» — اگر فعال است، توکن‌ها باید کامل باشند (سؤالِ شبکه نه، چون رباتِ پرداخت
    # روی loopِ خودش تست می‌شه؛ این‌جا فقط سنجشِ تنظیمات را می‌سنجیم)
    if getattr(settings, "bale_pay_enabled", False):
        missing = []
        if not settings.get_bale_pay_bot_token():
            missing.append("توکنِ رباتِ پرداختِ بله")
        if not settings.get_bale_pay_provider_token():
            missing.append("توکنِ درگاه (provider_token)")
        if missing:
            out.append(Finding("bale_pay", FAIL, "بله‌پی", "بله‌پی روشن است ولی این‌ها وارد نشده: " + "، ".join(missing) + ".", "pay-bale"))
        else:
            out.append(Finding("bale_pay", OK, "بله‌پی", "هر دو توکن ثبت شده؛ با «تست اتصال» در صفحهٔ پرداخت یک لینکِ آزمایشی بساز."))

    # هوش مصنوعی — فقط مدلِ محلی (هیچ API/سرویس بیرونی‌ای در کار نیست)
    from app.core import ai_engine

    ready, reason = ai_engine.engine_readiness(settings)
    if ready:
        out.append(Finding("ai", OK, "هوش مصنوعی", "مدلِ محلی انتخاب و دانلود شده و آماده‌ی پاسخ‌گویی‌ست.", "ai-local"))
    elif reason == "ai.ready.no_model_selected":
        out.append(Finding("ai", WARN, "هوش مصنوعی", "هنوز مدلی انتخاب نشده؛ ربات فقط دکمه‌ها را جواب می‌ده (پرسش‌های آزاد جواب نمی‌گیرن).", "ai-choose"))
    elif reason == "ai.ready.not_downloaded":
        out.append(Finding("ai", WARN, "هوش مصنوعی", "مدل انتخاب شده ولی فایلش هنوز دانلود نشده؛ از صفحه‌ی «هوش مصنوعی» دانلودش کن.", "ai-local"))
    elif reason == "ai.ready.llama_missing":
        out.append(Finding("ai", FAIL, "هوش مصنوعی", "ماشینِ اجرایِ مدل (llama-cpp-python) روی این سیستم نیست؛ اگر از سورس اجرا می‌کنی: pip install -r requirements.txt.", "ai-local"))
    elif reason == "ai.ready.file_invalid":
        out.append(Finding("ai", FAIL, "هوش مصنوعی", "فایلِ مدل نصفه‌نیمه یا دستکاری‌شده به نظر می‌رسه؛ دوباره دانلودش کن (دکمه‌ی «راستی‌آزمایی» در صفحه‌ی مدل).", "ai-local"))
    elif reason == "ai.ready.path_invalid":
        out.append(Finding("ai", FAIL, "هوش مصنوعی", "مسیرِ مدلی که در تنظیماتِ پیشرفته داده‌ای یک فایلِ GGUFِ واقعی نیست (نه پوشه، نه پیوندِ سمبولیک).", "ai-local"))
    else:  # هیچ تنظیماتی / مسیرِ فایلِ داده‌شده معتبر نیست
        out.append(Finding("ai", WARN, "هوش مصنوعی", "مسیرِ مدل معتبر نیست؛ یک فایلِ GGUFِ واقعی (نه پوشه یا پیوند) را انتخاب کن.", "ai-local"))

    # دیسک
    try:
        free = shutil.disk_usage(str(data_dir) if data_dir else ".").free
        out.append(Finding("disk", OK if free >= MIN_FREE_BYTES else WARN, "فضای دیسک", "کافیه." if free >= MIN_FREE_BYTES else "فضای خالیِ درایوِ داده‌ها کمتر از ۲۰۰ مگابایته؛ پایگاه‌داده‌ها ممکنه خراب شن.", "ts-disk"))
    except OSError:
        pass
    return out


def run_sync(settings, **kw) -> list:
    return asyncio.run(run(settings, **kw))
