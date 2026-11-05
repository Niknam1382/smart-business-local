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

    @property
    def size_gb(self) -> float:
        return round(self.size_bytes / _GIB, 2)

    @property
    def urls(self) -> list:
        """ترتیبِ تلاش: هاستِ اصلی، بعدِ آینه (برای کاربرهایی که به Hugging Face دسترسی ندارند)."""
        tail = f"{self.repo}/resolve/main/{self.filename}"
        return [f"https://{host}/{tail}" for host in SOURCE_HOSTS]

    @property
    def allowed_hosts(self) -> set:
        """هرچه دانلودِ این فایل مجاز است به آن وصل شود: منابعِ کاتالوگ + دامنه‌هایِ CDNشان."""
        return set(SOURCE_HOSTS) | set(CDN_DOMAINS)

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
]


def entries() -> list:
    return list(ENTRIES)


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
    scored = [(order[fit_state(hw, e, path_free_gb)], -e.quality, e.size_bytes, e) for e in ENTRIES]
    scored.sort(key=lambda row: row[:3])
    return [(e, fit_state(hw, e, path_free_gb)) for _s, _q, _z, e in scored]


def recommend(hw: HardwareInfo, path_free_gb: Optional[float] = None) -> Optional[ModelEntry]:
    """پیشنهادِ اصلی: بهترینِ کیفیتی که روی این سیستم راحت جا می‌شه.

    روی سیستم‌هایِ مرزی، کم‌حجم‌ترینِ گزینه‌ی «جا شونده» پیشنهاد می‌شه؛ اگه رم شناسایی نشد هم
    هرگز چیزی سنگین‌تر از توانِ واقعی سیستم پیشنهاد نمی‌شه."""
    for state in ("recommended", "ok", "tight"):
        candidates = [e for e in ENTRIES if fit_state(hw, e, path_free_gb) == state]
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
    return max(2, cores - 1)
