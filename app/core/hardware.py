"""
تشخیص سبک مشخصات سخت‌افزاری سیستم کاربر — برای نمایش در صفحه‌ی انتخاب
هوش مصنوعی محلی، و بعداً (فاز ۲) برای انتخاب خودکار سایز مدل مناسب.

هر بخش مستقل و با try/except محافظت شده تا اگه یه روش تشخیص روی یه سیستم
خاص جواب نداد، بقیه‌ی مقادیر همچنان نمایش داده بشن (هیچ‌وقت کل صفحه به
خاطر این اطلاعات جانبی کرش نمی‌کنه). نتیجه در حافظه کش می‌شه چون بعضی
روش‌های تشخیص (به‌خصوص GPU/CPU از طریق PowerShell) کند هستن و نیازی نیست
هر بار که صفحه دوباره رسم می‌شه، دوباره اجرا بشن.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import psutil
except ImportError:  # اگه psutil در دسترس نبود، بی‌خطر رد شو
    psutil = None


@dataclass
class HardwareInfo:
    ram_gb: Optional[float] = None
    cpu_cores: Optional[int] = None
    cpu_model: str = ""
    gpu_model: str = ""
    gpu_vram_gb: Optional[float] = None
    free_disk_gb: Optional[float] = None


_cached: Optional[HardwareInfo] = None


def _run(cmd: list[str], timeout: float) -> str:
    try:
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # بدون پنجره‌ی سیاه کنسول
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, **kwargs
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _detect_ram_gb() -> Optional[float]:
    if psutil is None:
        return None
    try:
        return round(psutil.virtual_memory().total / (1024**3), 1)
    except Exception:
        return None


def _detect_cpu_model() -> str:
    if sys.platform == "win32":
        name = _run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name)",
            ],
            timeout=5,
        )
        if name:
            return name
    import platform as _platform

    return _platform.processor() or ""


def _detect_gpu() -> tuple[str, Optional[float]]:
    """برمی‌گردونه: (نام کارت گرافیک، مقدار VRAM به گیگابایت یا None)."""
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        out = _run(
            [nvidia_smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            timeout=3,
        )
        if out:
            first_line = out.splitlines()[0]
            parts = [p.strip() for p in first_line.split(",")]
            if len(parts) == 2:
                try:
                    return parts[0], round(float(parts[1]) / 1024, 1)
                except ValueError:
                    return parts[0], None
            return first_line, None

    if sys.platform == "win32":
        name = _run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_VideoController | Select-Object -First 1 -ExpandProperty Name)",
            ],
            timeout=5,
        )
        if name:
            return name, None

    return "", None


def _detect_free_disk_gb(path: Optional[Path] = None) -> Optional[float]:
    """فضای آزاد دیسک در مسیر داده‌شده (پیش‌فرض: پوشه‌ی خانه‌ی کاربر).

    توجه: این مسیر باید همون جایی باشه که مدل‌ها واقعاً توش ذخیره می‌شن
    (قابل تنظیم توسط کاربر در صفحه‌ی هوش مصنوعی محلی) — نه لزوماً درایو
    ویندوزی که برنامه ازش اجرا شده، چون ممکنه اون درایو جای کافی نداشته
    باشه در حالی که یه درایو دیگه آزادتره.
    """
    try:
        target = path if path is not None else Path.home()
        usage = shutil.disk_usage(str(target))
        return round(usage.free / (1024**3), 1)
    except Exception:
        return None


def detect(force: bool = False, disk_path: Optional[Path] = None) -> HardwareInfo:
    global _cached
    if _cached is not None and not force:
        return _cached

    info = HardwareInfo()
    info.ram_gb = _detect_ram_gb()
    info.cpu_cores = os.cpu_count()
    info.cpu_model = _detect_cpu_model()
    info.gpu_model, info.gpu_vram_gb = _detect_gpu()
    info.free_disk_gb = _detect_free_disk_gb(disk_path)

    _cached = info
    return info


def free_disk_gb_at(path: Path) -> Optional[float]:
    """فضای آزاد یه مسیر مشخص رو مستقل از کش اصلی برمی‌گردونه — برای وقتی
    کاربر مسیر ذخیره‌ی مدل رو عوض می‌کنه و باید فوراً فضای جدید نشون داده بشه."""
    return _detect_free_disk_gb(path)
