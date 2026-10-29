"""چک‌لیستِ «شروعِ سریع» صفحه‌ی خانه (N10): هر گام از وضعیتِ واقعیِ تنظیمات حساب می‌شه، نه از یک تیکِ دستی."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Step:
    key: str
    title_fa: str
    title_en: str
    done: bool
    article: str  # مقاله‌ی راهنما
    target: str  # کلیدِ صفحه‌ی نوارِ کناری برای «برو»


def steps(settings, product_count: Optional[int] = None, bots_running: bool = False) -> list:
    """``product_count=None`` ⇒ حالتِ بدونِ فروشگاه (گامِ محصول/پرداخت نمایش داده نمی‌شه)."""
    has_bot = bool((settings.telegram_enabled and settings.get_telegram_token()) or (settings.bale_enabled and settings.get_bale_token()))
    has_ai = bool(settings.ai_mode) and bool(settings.get_api_key() or getattr(settings, "ai_providers", None) or settings.ai_mode == "local")
    out = [
        Step("bot", "ساختِ ربات و وارد کردنِ توکن", "Create a bot and enter its token", has_bot, "bot-token", "bots"),
        Step("ai", "انتخابِ هوش مصنوعی (اختیاری ولی پیشنهادی)", "Choose an AI (optional but recommended)", has_ai, "ai-choose", "ai"),
    ]
    if product_count is not None:
        pay = bool(settings.card_to_card_number or settings.bale_pay_enabled or settings.zarinpal_enabled)
        out += [
            Step("product", "افزودنِ اولین محصول", "Add your first product", product_count > 0, "products-basics", "products"),
            Step("payment", "تنظیمِ روشِ پرداخت", "Set a payment method", pay, "payments-overview", "orders"),
        ]
    out.append(Step("run", "روشن‌کردنِ ربات و یک سفارشِ آزمایشی", "Turn the bot on and place a test order", bool(bots_running), "start-quick", "bots"))
    return out


def progress(items: list) -> tuple:
    return sum(1 for s in items if s.done), len(items)
