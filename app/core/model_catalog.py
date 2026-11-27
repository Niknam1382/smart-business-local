"""
کاتالوگِ مدل‌هایِ محلی + پیشنهاد بر پایه‌ی سخت‌افزار.

چرا این مدل‌ها: همهِ GGUF و قابل‌اجرا با llama.cpp، همهِ «بدونِ تفکرِ اجباری» (قالبِ گفتگوی
Qwen3.5 فقط وقتی `enable_thinking is true` فرستاده بشه بلوکِ تفکر می‌سازد؛ llama-cpp-python آن را
نمی‌فرستد، پس پاسخِ مستقیم می‌گیریم — برای رباتِ فروشگاهیِ روی CPU مهمه)، و کیفیتِ فارسی‌شان در
معیارهای ۲۰۲۶ (MEA/DivanBench) خوب گزارش شده. مجوز: Apache-2.0.

هرِ فایل با `sha256` و حجمِ دقیقِ قفل‌شده می‌آید (گرفته‌شده از API عمومیِ Hugging Face).
آدرس‌ها با دسترس‌پذیریِ کاربرِ ایرانی در نظر گرفته شدن: منبعِ اصلی + یک آینه؛ اگه هیچ‌کدام کار
نکرد، کاربر می‌تونه فایلِ GGUF را خودش از جای دیگر بگیره و به برنامه نشون بده.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.core.hardware import HardwareInfo

_GIB = 1024**3

# ترتیبِ تلاشِ دانلود. ``cache.fuyuan.top`` (آینه‌ی سومِ قبلی) حذف شد: اسمش در هیچ
# شبکه‌ای resolve نمی‌شد و فقط علتِ خطایِ منبع‌هایِ سالم را می‌پوشاند.
SOURCE_HOSTS = ("huggingface.co", "hf-mirror.com")

# دامنه‌هایی که فایلِ GGUF *واقعاً* از آن‌ها سرو می‌شه: هر منبعِ بالا با ۳۰۲/۳۰۸ به CDN
# خودش هدایت می‌کنه (اندازه‌گیری‌شده: ``us.aws.cdn.hf.co``). ریدایرکت به بیرونِ این
# دامنه‌ها رد می‌شه — آینه‌ها شخصِ ثالث‌ان و نباید هر مقصدی را پذیرفت.
CDN_DOMAINS = ("hf.co", "huggingface.co", "hf-mirror.com")


@dataclass(frozen=True)
class ModelEntry:
    id: str
    family: str  # نمایشی: "Qwen3.5"
    params: str  # نمایشی: "4B"
    quant: str  # "Q4_K_M"
    label: dict  # {"fa": "...", "en": "..."} — برچسبِ کوتاهِ کارت
    blurb: dict  # {"fa": "...", "en": "..."} — چرا این مدل
    quality: int  # ۱..۵ کیفیتِ پاسخِ فارسی (نسبت به بقیه‌ی کاتالوگ)
    speed: int  # ۱..۵ سرعتِ پاسخ روی پردازنده‌ی معمولی
    repo: str
    filename: str
    sha256: str
    size_bytes: int
    min_ram_gb: float  # کمتر از این، عملاً اجرا نمی‌شه
    good_ram_gb: float  # از این به بالا راحت و با زمینه‌ی کامل
    license: str = "apache-2.0"
    # ۱٫۲٫۰: ``verified=False`` یعنی نام/لینکِ مخزن از منبعِ رسمی است ولی SHA-256 و حجمِ دقیقِ فایل از پیش اندازه‌گیری
    # نشده؛ حجم تقریبی است، هشِ مرجع نداریم و فقط از منبعِ رسمی (یا آینه‌ی شخصیِ خودِ کاربر) دانلود می‌شود.
    verified: bool = True

    @property
    def size_gb(self) -> float:
        return round(self.size_bytes / _GIB, 2)

    @property
    def expected_size(self) -> int:
        """حجمی که برای «دانلود شده؟» به‌کار می‌رود؛ برای مدلِ تأییدنشده (حجمِ تقریبی) صفر = بررسی نشود."""
        return self.size_bytes if self.verified else 0

    def _hosts(self, extra_hosts=()) -> list:
        base = list(SOURCE_HOSTS) if self.verified else [SOURCE_HOSTS[0]]
        for host in extra_hosts or ():
            if host and host not in base:
                base.append(host)
        return base

    @property
    def urls(self) -> list:
        """ترتیبِ تلاش: هاستِ اصلی، بعدِ آینه (برای کاربرهایی که به Hugging Face دسترسی ندارند)."""
        return self.urls_with(())

    def urls_with(self, extra_hosts=()) -> list:
        """آدرس‌هایِ کاتالوگ + آینه‌های شخصیِ کاربر (فقط هاستِ معتبر؛ ساختارِ ``/<repo>/resolve/main/<file>``)."""
        tail = f"{self.repo}/resolve/main/{self.filename}"
        return [f"https://{host}/{tail}" for host in self._hosts(extra_hosts)]

    @property
    def allowed_hosts(self) -> set:
        """هرچه دانلودِ این فایل مجاز است به آن وصل شود: منابعِ کاتالوگ + دامنه‌هایِ CDNشان."""
        return self.allowed_hosts_with(())

    def allowed_hosts_with(self, extra_hosts=()) -> set:
        hosts = set(self._hosts(extra_hosts))
        if self.verified:
            hosts |= set(CDN_DOMAINS)
        else:
            hosts |= {"hf.co", "huggingface.co"}  # CDNِ رسمی؛ آینه‌ی ثالث برای فایلِ بی‌هشِ مرجع پذیرفته نمی‌شود
        return hosts

    def weight_ram_gb(self) -> float:
        """رمِ لازمِ تقریبی: وزنِ مدل + ~۲۵٪ سربارِ اجرایِ GGUF + ۰٫۸ گیگ برایِ زمینه."""
        return round(self.size_bytes / _GIB * 1.25 + 0.8, 1)


ENTRIES: list[ModelEntry] = [
    ModelEntry(
        id="qwen35-2b",
        family="Qwen3.5",
        params="2B",
        quant="Q4_K_S",
        label={"fa": "سبکِ سریع", "en": "Light & fast"},
        blurb={
            "fa": "برای لپ‌تاپ‌های قدیمی و سیستم‌های ۴ گیگابایتی. جواب‌ها کوتاه و سریع‌ان؛ برای مشاوره‌ی ساده و پرسش‌های پرتکرار خوبه.",
            "en": "For older laptops and 4 GB systems. Short, fast replies; fine for simple advisory and common questions.",
        },
        quality=2,
        speed=5,
        repo="unsloth/Qwen3.5-2B-GGUF",
        filename="Qwen3.5-2B-Q4_K_S.gguf",
        sha256="56eee7b85a2023ba393c5f9a5a5e372e3645e7925a13adb4d13723fc5bc14124",
        size_bytes=1217757440,
        min_ram_gb=3.5,
        good_ram_gb=6.0,
    ),
    ModelEntry(
        id="qwen25-3b",
        family="Qwen2.5",
        params="3B",
        quant="Q4_K_M",
        label={"fa": "اقتصادی", "en": "Budget"},
        blurb={
            "fa": "یک پله قوی‌تر از مدلِ ۲B با حجمِ کم. گزینه‌ی خوب وقتی رم ۶ تا ۸ گیگابایت داری و می‌خوای پاسخِ دقیق‌تری بگیری.",
            "en": "One step stronger than the 2B at a small size. Good with 6–8 GB RAM when you want more accurate answers.",
        },
        quality=3,
        speed=4,
        repo="bartowski/Qwen2.5-3B-Instruct-GGUF",
        filename="Qwen2.5-3B-Instruct-Q4_K_M.gguf",
        sha256="9c9f56a391a3abbd5b89d0245bf6106081bcc3173119d4229235dd9d23253f94",
        size_bytes=1929903264,
        min_ram_gb=5.0,
        good_ram_gb=8.0,
        license="qwen-research (کاربردِ تجاری را خودت بررسی کن)",
    ),
    ModelEntry(
        id="qwen35-4b",
        family="Qwen3.5",
        params="4B",
        quant="Q4_K_M",
        label={"fa": "پیشنهادِ ما", "en": "Recommended"},
        blurb={
            "fa": "بهترین تعادلِ کیفیتِ فارسی و سرعت روی بیشترِ کامپیوترهای خانگی. انتخابِ پیش‌فرض برای فروشگاه و مشاوره.",
            "en": "The best balance of Persian quality and speed on most home computers. Default choice for shops and advisory.",
        },
        quality=4,
        speed=4,
        repo="unsloth/Qwen3.5-4B-GGUF",
        filename="Qwen3.5-4B-Q4_K_M.gguf",
        sha256="00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4",
        size_bytes=2740937888,
        min_ram_gb=6.5,
        good_ram_gb=10.0,
    ),
    ModelEntry(
        id="qwen3-4b-instruct",
        family="Qwen3",
        params="4B",
        quant="Q4_K_M",
        label={"fa": "دستورپذیرِ قوی", "en": "Strong instruction follower"},
        blurb={
            "fa": "نسخه‌ی «فقط پاسخ»ِ Qwen3؛ پایبندیِ خیلی خوب به قوانینِ ربات و فرمتِ درخواستی. هم‌سایزِ مدلِ پیشنهادی.",
            "en": "The answer-only Qwen3 build; follows bot rules and requested formats very well. Same size class as the recommended one.",
        },
        quality=4,
        speed=4,
        repo="lmstudio-community/Qwen3-4B-Instruct-2507-GGUF",
        filename="Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
        sha256="8cdb57cbb880d313736a9bc4e3d3d2485f145b5e19cf33783746e753e82641fc",
        size_bytes=2497280448,
        min_ram_gb=6.5,
        good_ram_gb=10.0,
    ),
    ModelEntry(
        id="qwen25-7b",
        family="Qwen2.5",
        params="7B",
        quant="Q4_K_M",
        label={"fa": "کیفیتِ بالا", "en": "High quality"},
        blurb={
            "fa": "تجربه‌ی گفتگوی کامل‌تر و پاسخ‌های دقیق‌تر؛ روی سیستم‌های ۱۲ گیگابایت به بالا. کندتر از ۴B جواب می‌ده.",
            "en": "Richer conversation and more accurate answers on 12 GB+ systems. Slower than 4B.",
        },
        quality=4,
        speed=3,
        repo="bartowski/Qwen2.5-7B-Instruct-GGUF",
        filename="Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        sha256="65b8fcd92af6b4fefa935c625d1ac27ea29dcb6ee14589c55a8f115ceaaa1423",
        size_bytes=4683074240,
        min_ram_gb=9.0,
        good_ram_gb=14.0,
    ),
    ModelEntry(
        id="qwen35-9b",
        family="Qwen3.5",
        params="9B",
        quant="Q4_K_M",
        label={"fa": "بهترینِ پاسخ", "en": "Best answers"},
        blurb={
            "fa": "قوی‌ترینِ فارسی در این کاتالوگ (رتبه‌ی نخستِ معیارِ چندزبانه‌ی ۲۰۲۶). برای سیستمِ ۱۶ گیگابایت یا کارت گرافیک با حافظه‌ی زیاد.",
            "en": "The strongest Persian in this catalog (top of the 2026 multilingual benchmark). Needs 16 GB RAM or a roomy GPU.",
        },
        quality=5,
        speed=2,
        repo="unsloth/Qwen3.5-9B-GGUF",
        filename="Qwen3.5-9B-Q4_K_M.gguf",
        sha256="03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8",
        size_bytes=5680522464,
        min_ram_gb=11.0,
        good_ram_gb=16.0,
    ),
    # ------------------------------------------------------------------ مدل‌هایِ متنوع‌ترِ تأییدنشده (۱٫۲٫۰)
    # نام و مخزن از منابعِ رسمیِ Hugging Face است ولی SHA-256 و حجمِ دقیقِ فایل را این‌جا اندازه نگرفته‌ایم
    # (حجم تقریبی). کارتشان «تأییدنشده» نشان داده می‌شود، پیشنهادِ خودکار نمی‌شوند و هشِ واقعیِ فایل پس از دانلود
    # با «راستی‌آزمایی» نمایش داده می‌شود تا با صفحه‌ی مخزن مقایسه کنی.
    ModelEntry(
        id="qwen25-05b",
        family="Qwen2.5",
        params="0.5B",
        quant="Q4_K_M",
        label={"fa": "فوق‌سبک", "en": "Ultra-light"},
        blurb={
            "fa": "فقط برایِ امتحانِ سریعِ نصب و سیستم‌هایِ خیلی ضعیف (زیرِ ۱ میلیارد پارامتر). "
                  "برایِ ربات فروشگاه کافی نیست: فارسی‌اش ضعیف است، سؤالِ قیمت و موجودی را اغلب اشتباه جواب می‌دهد و جدی نباید به مشتری جواب بدهد.",
            "en": "Only for a quick install test or very weak PCs (under 1 billion parameters). "
                  "Not enough for a shop bot: weak Persian, often wrong on price and stock questions, not meant to answer customers.",
        },
        quality=1,
        speed=5,
        repo="Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        filename="qwen2.5-0.5b-instruct-q4_k_m.gguf",
        sha256="",
        size_bytes=400_000_000,
        min_ram_gb=2.0,
        good_ram_gb=3.0,
        verified=False,
    ),
    ModelEntry(
        id="qwen3-06b",
        family="Qwen3",
        params="0.6B",
        quant="Q8_0",
        label={"fa": "فوق‌سبک", "en": "Ultra-light"},
        blurb={
            "fa": "مدلِ کوچکِ نسلِ تازه‌یِ Qwen (زیرِ ۱ میلیارد پارامتر)؛ کمی دقیق‌تر از ۰٫۵B ولی باز هم فقط برایِ امتحان. "
                  "برایِ ربات فروشگاه کافی نیست و ممکن است پیش از پاسخ «فکر» کند؛ برنامه آن بخش را حذف می‌کند.",
            "en": "A small current-generation Qwen (under 1 billion parameters); a bit sharper than 0.5B but still for testing only. "
                  "Not enough for a shop bot, and it may “think” before answering; the app strips that part.",
        },
        quality=1,
        speed=5,
        repo="Qwen/Qwen3-0.6B-GGUF",
        filename="Qwen3-0.6B-Q8_0.gguf",
        sha256="",
        size_bytes=640_000_000,
        min_ram_gb=2.5,
        good_ram_gb=4.0,
        verified=False,
    ),
    ModelEntry(
        id="qwen25-15b",
        family="Qwen2.5",
        params="1.5B",
        quant="Q4_K_M",
        label={"fa": "فوق‌سبک", "en": "Ultra-light"},
        blurb={
            "fa": "کوچک‌ترین و سریع‌ترین گزینه برای سیستم‌هایِ بسیار ضعیف (۴ گیگ رم). فارسی‌اش ساده است؛ فقط برایِ پاسخ‌هایِ کوتاه و تکراری.",
            "en": "The smallest and fastest option for very weak PCs (4 GB RAM). Basic Persian; only for short, repetitive answers.",
        },
        quality=1,
        speed=5,
        repo="Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        filename="qwen2.5-1.5b-instruct-q4_k_m.gguf",
        sha256="",
        size_bytes=1_120_000_000,
        min_ram_gb=3.0,
        good_ram_gb=5.0,
        verified=False,
    ),
    ModelEntry(
        id="gemma2-2b",
        family="Gemma 2",
        params="2B",
        quant="Q4_K_M",
        label={"fa": "گوگل، سبک", "en": "Google, light"},
        blurb={
            "fa": "مدلِ سبکِ گوگل با چندزبانگیِ قابل‌قبول؛ جایگزینِ متفاوت برای ۲B قوی‌تر شدن در پاسخ‌هایِ کوتاهِ فارسی.",
            "en": "Google's light model with acceptable multilingual ability; a different alternative to the 2B class.",
        },
        quality=2,
        speed=4,
        repo="bartowski/gemma-2-2b-it-GGUF",
        filename="gemma-2-2b-it-Q4_K_M.gguf",
        sha256="",
        size_bytes=1_710_000_000,
        min_ram_gb=4.0,
        good_ram_gb=6.0,
        license="gemma (شرایطِ استفاده‌ی گوگل)",
        verified=False,
    ),
    ModelEntry(
        id="llama32-3b",
        family="Llama 3.2",
        params="3B",
        quant="Q4_K_M",
        label={"fa": "متا، متعادل", "en": "Meta, balanced"},
        blurb={
            "fa": "مدلِ ۳B متا؛ انگلیسی‌اش قوی است و فارسی‌اش متوسط. اگر مشتری‌هایت بیشتر انگلیسی می‌نویسند انتخابِ خوبی است.",
            "en": "Meta's 3B model; strong English, average Persian. A good pick if your customers mostly write English.",
        },
        quality=2,
        speed=4,
        repo="bartowski/Llama-3.2-3B-Instruct-GGUF",
        filename="Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        sha256="",
        size_bytes=2_020_000_000,
        min_ram_gb=5.0,
        good_ram_gb=8.0,
        license="llama3.2 (شرایطِ استفاده‌ی متا)",
        verified=False,
    ),
    ModelEntry(
        id="gemma2-9b",
        family="Gemma 2",
        params="9B",
        quant="Q4_K_M",
        label={"fa": "گوگل، قوی", "en": "Google, strong"},
        blurb={
            "fa": "چندزبانگیِ خوب و پاسخ‌هایِ روان‌تر؛ برای سیستم‌هایِ ۱۶ گیگابایتی یا کارت گرافیکِ ۸ گیگ به بالا. کندتر از مدل‌هایِ ۴B است.",
            "en": "Good multilingual ability and smoother replies; for 16 GB systems or 8 GB+ GPUs. Slower than 4B models.",
        },
        quality=4,
        speed=2,
        repo="bartowski/gemma-2-9b-it-GGUF",
        filename="gemma-2-9b-it-Q4_K_M.gguf",
        sha256="",
        size_bytes=5_760_000_000,
        min_ram_gb=10.0,
        good_ram_gb=16.0,
        license="gemma (شرایطِ استفاده‌ی گوگل)",
        verified=False,
    ),
    ModelEntry(
        id="aya-expanse-8b",
        family="Aya Expanse",
        params="8B",
        quant="Q4_K_M",
        label={"fa": "چندزبانه (غیرتجاری)", "en": "Multilingual (non-commercial)"},
        blurb={
            "fa": "برای ۲۳ زبان از جمله فارسی ساخته شده و در متنِ فارسی خوب عمل می‌کند. ⚠️ مجوزش غیرتجاری است؛ برای فروشگاهِ واقعی پیش از استفاده مجوز را بررسی کن.",
            "en": "Built for 23 languages including Persian. ⚠️ Licensed non-commercial; check the license before using it for a real shop.",
        },
        quality=4,
        speed=2,
        repo="bartowski/aya-expanse-8b-GGUF",
        filename="aya-expanse-8b-Q4_K_M.gguf",
        sha256="",
        size_bytes=5_060_000_000,
        min_ram_gb=9.0,
        good_ram_gb=14.0,
        license="cc-by-nc-4.0 (غیرتجاری)",
        verified=False,
    ),
    ModelEntry(
        id="qwen25-14b",
        family="Qwen2.5",
        params="14B",
        quant="Q4_K_M",
        label={"fa": "سنگین و دقیق", "en": "Heavy & accurate"},
        blurb={
            "fa": "برای سیستم‌هایِ قوی (۲۴ گیگ رم یا کارت گرافیکِ ۱۲ گیگ به بالا). دقیق‌تر از مدل‌هایِ کوچک ولی کند روی پردازنده.",
            "en": "For powerful systems (24 GB RAM or a 12 GB+ GPU). More accurate than small models but slow on CPU.",
        },
        quality=4,
        speed=1,
        repo="bartowski/Qwen2.5-14B-Instruct-GGUF",
        filename="Qwen2.5-14B-Instruct-Q4_K_M.gguf",
        sha256="",
        size_bytes=8_990_000_000,
        min_ram_gb=15.0,
        good_ram_gb=24.0,
        verified=False,
    ),
]


# ۱٫۲٫۱: فهرست همیشه «از کوچک به بزرگ» است (اول رمِ لازم، بعد حجمِ فایل) تا کاربر بداند از کجا شروع کند.
ENTRIES.sort(key=lambda e: (e.min_ram_gb, e.size_bytes))


def entries() -> list:
    return list(ENTRIES)


def ordered_for(hw: HardwareInfo, path_free_gb: Optional[float] = None) -> list:
    """همه‌ی مدل‌ها از کوچک به بزرگ، هرکدام با وضعیتِ برازش: ``[(ModelEntry, state), ...]``."""
    return [(e, fit_state(hw, e, path_free_gb)) for e in ENTRIES]


def is_trial_only(entry: Optional[ModelEntry]) -> bool:
    """مدل‌هایِ زیرِ ۱ میلیارد پارامتر فقط «امتحانِ نصب» هستند، نه جواب‌دادن به مشتریِ واقعی (۱٫۲٫۲)."""
    if entry is None:
        return False
    match = re.match(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([BbMm])", entry.params or "")
    if not match:
        return False
    value = float(match.group(1))
    return value < 1.0 if match.group(2).lower() == "b" else True


def vram_hint_gb(entry: ModelEntry) -> float:
    """حافظه‌ی گرافیکیِ تقریبی که برایِ اجرایِ کاملِ مدل روی کارت لازم است (وزن + ~۲۰٪ + زمینه)؛ رُندشده به ۰٫۵."""
    need = entry.size_bytes / _GIB * 1.2 + 0.6
    return max(1.0, round(need * 2) / 2)


_HOST_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")


def parse_mirror_hosts(text: str) -> list:
    """آینه‌های شخصیِ کاربر: هر خط/ویرگول یک نامِ دامنه (بدونِ http و مسیر). موارد نامعتبر نادیده گرفته می‌شود
    (جلوگیری از آدرسِ محلی/IP/مسیرِ شبکه). فقط HTTPS ساخته می‌شود."""
    found: list = []
    for raw in re.split(r"[\s,;]+", (text or "").strip().lower()):
        host = raw.removeprefix("https://").removeprefix("http://").strip("/ ")
        if host and "/" not in host and ":" not in host and _HOST_RE.match(host) and host not in found:
            found.append(host)
    return found[:3]


def get_entry(model_id: str) -> Optional[ModelEntry]:
    for entry in ENTRIES:
        if entry.id == model_id:
            return entry
    return None


# ------------------------------------------------------------------ برازشِ سخت‌افزار

def available_ram_gb(hw: HardwareInfo) -> float:
    """رمِ قابل‌استفاده برای مدل. عمداً محافظه‌کارانه: ویندوز/برنامه‌ها همیشه چیزی
    اشغال دارن، پس ۸۵٪ِ رمِ فیزیکی را حساب می‌کنیم (هیچ‌وقت مدلی را « جا می‌شه» نگوییم
    که وسطِ کار سیستم قفل کند)."""
    if not hw.ram_gb:
        return 0.0
    return round(hw.ram_gb * 0.85, 1)


def free_disk_ok(hw: HardwareInfo, entry: ModelEntry, path_free_gb: Optional[float] = None) -> bool:
    free = path_free_gb if path_free_gb is not None else hw.free_disk_gb
    if free is None:
        return True  # نمی‌دونیم؛ پس مانع نمی‌شیم (برنامه خودش قبلِ دانلود چک می‌کنه)
    return free >= entry.size_bytes / _GIB + 1.0


def fit_state(hw: HardwareInfo, entry: ModelEntry, path_free_gb: Optional[float] = None) -> str:
    """«recommended» | «ok» | «tight» | «no» — وضعیتِ این مدل روی این سیستم.

    ملاک، رمِ سیستم است (نه VRAM): بیلدِ رسمیِ برنامه llama.cppِ فقط-CPU است و مدل در رمِ سیستم
    جا می‌شه؛ شتابِ گرافیکی فقط وقتی واقعی است که کاربر خودش بیلدِ CUDA را نصب کرده باشه."""
    if not free_disk_ok(hw, entry, path_free_gb):
        return "no"
    ram = available_ram_gb(hw)
    if ram == 0.0:  # رم شناسایی نشد: فقط گزینه‌هایِ سبک را جا می‌دونیم
        return "ok" if entry.size_bytes <= 2 * _GIB else "tight"
    if ram >= entry.good_ram_gb:
        return "recommended" if ram >= entry.good_ram_gb * 1.15 else "ok"
    if ram >= entry.min_ram_gb:
        return "tight"
    return "no"


def ranked_for(hw: HardwareInfo, path_free_gb: Optional[float] = None) -> list:
    """همه‌ی مدل‌ها، از مناسبِ این سیستم به سمتِ نامناسب: ``[(ModelEntry, state), ...]``."""
    order = {"recommended": 0, "ok": 1, "tight": 2, "no": 3}
    scored = [(0 if e.verified else 1, order[fit_state(hw, e, path_free_gb)], -e.quality, e.size_bytes, e) for e in ENTRIES]
    scored.sort(key=lambda row: row[:4])  # اول مدل‌هایِ تأییدشده، بعد تأییدنشده‌ها (هر گروه از مناسب‌تر به نامناسب)
    return [(e, fit_state(hw, e, path_free_gb)) for _v, _s, _q, _z, e in scored]


def recommend(hw: HardwareInfo, path_free_gb: Optional[float] = None) -> Optional[ModelEntry]:
    """پیشنهادِ اصلی: بهترینِ کیفیتی که روی این سیستم راحت جا می‌شه.

    روی سیستم‌هایِ مرزی، کم‌حجم‌ترینِ گزینه‌ی «جا شونده» پیشنهاد می‌شه؛ اگه رم شناسایی نشد هم
    هرگز چیزی سنگین‌تر از توانِ واقعی سیستم پیشنهاد نمی‌شه."""
    for state in ("recommended", "ok", "tight"):
        candidates = [e for e in ENTRIES if e.verified and fit_state(hw, e, path_free_gb) == state]
        if candidates:
            if state == "tight":
                candidates.sort(key=lambda e: e.size_bytes)
            else:
                candidates.sort(key=lambda e: (-e.quality, -e.speed, e.size_bytes))
            return candidates[0]
    return None


def reason_for(hw: HardwareInfo, entry: ModelEntry, path_free_gb: Optional[float] = None) -> str:
    """یک خطِ توضیحِ صادقانه برای کنارِ پیشنهاد (کلیدِ i18n برمی‌گردونه؛ پارامترها عدد)."""
    state = fit_state(hw, entry, path_free_gb)
    if state == "recommended":
        return "ai.local.rec_recommended"
    if state == "ok":
        return "ai.local.rec_ok"
    if state == "tight":
        return "ai.local.rec_tight"
    if not free_disk_ok(hw, entry, path_free_gb):
        return "ai.local.rec_no_disk"
    return "ai.local.rec_no_ram"


def gpu_acceleration_note(hw: HardwareInfo, cuda_available: bool = False) -> str:
    """کلیدِ i18nِ وضعیتِ شتابِ گرافیکی — برایِ نمایشِ شفاف اینکه آیا GPU به کار می‌ره یا نه.

    ``cuda_available`` از خودِ بیلدِ نصب‌شده پرسیده می‌شه (``ai_engine.gpu_offload_available``)،
    نه از نامِ کارت: بیلدِ رسمیِ برنامه llama-cpp-python نسخه‌ی CPU است، پس حتی با کارتِ NVIDIA
    محاسبه روی پردازنده انجام می‌شه. کاربرِ حرفه‌ای می‌تونه بیلدِ CUDA را خودش نصب کنه
    (راهنمایِ «CUDA» در صفحه‌ی هوش مصنوعی)."""
    if not hw.gpu_model:
        return "ai.local.gpu_note_none"
    name = hw.gpu_model.lower()
    nvidia = "nvidia" in name or "geforce" in name or "rtx" in name or "gtx" in name
    if nvidia and cuda_available:
        return "ai.local.gpu_note_ready"
    if nvidia:
        return "ai.local.gpu_note_nvidia"
    return "ai.local.gpu_note_other"


# --------------------------------------------------------------- اندازه‌هایِ خودکار

def auto_context_tokens(hw: HardwareInfo, entry: ModelEntry) -> int:
    """پنجره‌ی زمینه بر پایه‌ی رمِ موجود؛ هرگز آن‌قدر بزرگ که سیستم قفل کنه.

    فروشگاه به زمینه‌ی بزرگ‌تری نیاز داره (کاتالوگ + قوانین ~۴٬۰۰۰ توکنِ فارسی)."""
    ram = available_ram_gb(hw) or entry.good_ram_gb
    headroom = max(0.0, ram - entry.weight_ram_gb())
    budget = int(headroom * 350)  # ~۳۵۰ توکن به‌ازای هر گیگابایتِ آزاد
    return max(2048, min(8192, budget // 1024 * 1024))


def auto_threads(hw: HardwareInfo) -> int:
    """تعدادِ ترد: همه‌ی هسته‌ها منهای یکی (ویندوز خودش یه هسته می‌خواد)، حداقلِ ۲."""
    cores = hw.cpu_cores or 0
    if cores <= 0:
        return 0  # خودِ llama.cpp تصمیم می‌گیره
    physical = getattr(hw, "cpu_physical", None) or 0
    if 0 < physical < cores:
        # تولیدِ توکن به پهنای باندِ حافظه وابسته است؛ ترد روی هسته‌ی منطقی (hyper-thread/هسته‌ی E)
        # معمولاً کُندتر می‌کند و رابط را قفل می‌کند. فقط هسته‌های فیزیکی، منهای یکی برای سیستم.
        return max(2, min(physical - 1 if physical > 4 else physical, 8))
    return max(2, cores - 1)
