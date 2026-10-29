"""
کاتالوگ مدل‌های محلی + منطق پیشنهاد سایز مناسب بر اساس سخت‌افزار.

مدل‌ها از خانواده‌ی Qwen2.5 (مجوز Apache-2.0، پشتیبانی چندزبانه‌ی خوب) در
فرمت GGUF با کوانتیزاسیون Q4_K_M (تعادل خوب بین کیفیت و حجم) انتخاب شدن.
آدرس دانلود مستقیم از مخزن عمومی bartowski روی Hugging Face — این یکی از
پراستفاده‌ترین و معتبرترین منابع GGUF عمومیه.

قانون سرانگشتی حجم رم لازم: تقریباً ۱.۳ برابر حجم فایل مدل (برای جا دادن
مدل در رم + فضای context/KV-cache).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.core.hardware import HardwareInfo


@dataclass(frozen=True)
class ModelTier:
    id: str
    title: dict  # {"fa": ..., "en": ...} — برچسب ساده (کوچک/متوسط/بزرگ)
    why: dict  # {"fa": ..., "en": ...} — توضیح ساده‌ی چرا/کِی این سایز مناسبه
    model_name: str  # اسم واقعی مدل، مثلاً "Qwen2.5-1.5B-Instruct"
    params: str  # نمایشی، مثلاً "1.5B"
    approx_size_gb: float
    min_ram_gb: float
    repo: str
    filename: str

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/main/{self.filename}"

    @property
    def approx_size_bytes(self) -> int:
        return int(self.approx_size_gb * (1024**3))


TIERS: list[ModelTier] = [
    ModelTier(
        id="small",
        title={"fa": "کوچک", "en": "Small"},
        why={
            "fa": "سریع‌ترین گزینه؛ برای سیستم‌های با رم کمتر یا وقتی سرعت پاسخ مهم‌تر از کیفیت پاسخه.",
            "en": "The fastest option; for systems with less RAM, or when reply speed matters more than quality.",
        },
        model_name="Qwen2.5-1.5B-Instruct",
        params="1.5B",
        approx_size_gb=0.98,
        min_ram_gb=3.0,
        repo="bartowski/Qwen2.5-1.5B-Instruct-GGUF",
        filename="Qwen2.5-1.5B-Instruct-Q4_K_M.gguf",
    ),
    ModelTier(
        id="medium",
        title={"fa": "متوسط", "en": "Medium"},
        why={
            "fa": "تعادل خوب بین کیفیت و سرعت؛ پیشنهاد پیش‌فرض ما برای اکثر سیستم‌ها.",
            "en": "A good balance of quality and speed; our default recommendation for most systems.",
        },
        model_name="Qwen2.5-3B-Instruct",
        params="3B",
        approx_size_gb=1.93,
        min_ram_gb=4.5,
        repo="bartowski/Qwen2.5-3B-Instruct-GGUF",
        filename="Qwen2.5-3B-Instruct-Q4_K_M.gguf",
    ),
    ModelTier(
        id="large",
        title={"fa": "بزرگ", "en": "Large"},
        why={
            "fa": "بهترین کیفیت پاسخ؛ کندتر جواب می‌ده و به رم و پردازنده‌ی قوی‌تری نیاز داره.",
            "en": "The best answer quality; responds more slowly and needs stronger RAM and CPU.",
        },
        model_name="Qwen2.5-7B-Instruct",
        params="7B",
        approx_size_gb=4.68,
        min_ram_gb=8.0,
        repo="bartowski/Qwen2.5-7B-Instruct-GGUF",
        filename="Qwen2.5-7B-Instruct-Q4_K_M.gguf",
    ),
]


def get_tier(tier_id: str) -> Optional[ModelTier]:
    for tier in TIERS:
        if tier.id == tier_id:
            return tier
    return None


def recommend_tier_id(hw: HardwareInfo) -> str:
    """بر اساس رم شناسایی‌شده، یکی از سه سایز رو پیشنهاد می‌ده.

    محافظه‌کارانه عمل می‌کنه: اگه رم شناسایی نشد، فرض می‌کنیم سیستم ضعیفه
    (پیشنهاد «کوچک») تا هیچ‌وقت چیزی سنگین‌تر از توان واقعی سیستم پیشنهاد
    نشه.
    """
    ram = hw.ram_gb
    if ram is None:
        return "small"
    if ram >= 8.5:
        return "large"
    if ram >= 4.5:
        return "medium"
    return "small"


def gpu_acceleration_note(hw: HardwareInfo) -> str:
    """یه کلید i18n برمی‌گردونه که وضعیت شتاب‌دهی گرافیکی رو توصیف می‌کنه —
    برای نمایش شفاف به کاربر که آیا از GPU استفاده می‌شه یا نه و چرا."""
    if not hw.gpu_model:
        return "ai.local.gpu_note_none"
    name = hw.gpu_model.lower()
    if "nvidia" in name or "geforce" in name or "rtx" in name or "gtx" in name:
        return "ai.local.gpu_note_nvidia"
    return "ai.local.gpu_note_other"
