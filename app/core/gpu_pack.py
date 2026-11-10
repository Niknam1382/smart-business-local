"""
بستهٔ **شتابِ گرافیکی** در همان یک نصبِ برنامه (قلم ۲).

مسئله: فایلِ نصبیِ رسمی روی GitHub Actions ساخته می‌شود و آنجا هیچ رانرِ GPU‌دار نیست، پس
``llama-cpp-python`` از شاخهٔ CPU نصب می‌شود و ``llama.dll``ِ داخلِ بسته هیچ پشتیبانیِ گرافیکی
ندارد (اندازه‌گیری‌شده: ``llama_cpp.llama_supports_gpu_offload()`` روی چنین بیلدی ``False`` است).
راه‌حلِ انتخاب‌شده با مالک: **یک** نصب‌کننده، و اگر کارتِ NVIDIA پیدا شد خودِ برنامه بستهٔ
شتابِ رسمیِ llama.cpp را دانلود می‌کند (با اثرانگشتِ قفل‌شده) و موتور را روی آن می‌برد.

چطور کار می‌کند (نکتهٔ کلیدی — روی همین ماشین راستی‌آزمایی شد)
    ``llama-cpp-python`` یک بستهٔ ``ctypes`` است، نه افزونهٔ کامپایل‌شده: در زمانِ ``import``
    فایلِ ``llama.dll`` را با مسیرِ کامل بارگذاری می‌کند. آن تابع یک پوشهٔ پایه دارد که
    **با متغیرِ محیطیِ ``LLAMA_CPP_LIB_PATH`` عوض می‌شود** (``llama_cpp/llama_cpp.py``،
    همان چیزی که خودِ پروژهٔ upstream نگه داشته). پس لازم نیست هیچ فایلی در پوشهٔ نصب
    دستکاری شود: ما آدرسِ پوشهٔ بسته را به همان متغیر می‌دهیم و ``os.add_dll_directory`` را صدا
    می‌زنیم تا خودِ ``llama.dll`` و وابستگیِ ``ggml.dll`` آن از همان پوشه بیایند؛ ``ggml.dll`` هم
    بک‌اند‌هایِ پویا (``ggml-cuda.dll`` و ``cudart*.dll``) را از **پوشهٔ خودش** برمی‌دارد. پس همهٔ DLLها
    پس در یک پوشهٔ تخت می‌نشینند.
    اندازه‌گیریِ محلی: با یک پوشهٔ جایگزینِ سالم، ``llama_cpp.llama_cpp._lib._name`` دقیقاً به
    ``<پوشهٔ بسته>/llama.dll`` رفت؛ با پوشه‌ای که فقط ``llama.dll`` داشت، بارگذاری **رد** شد
    («or one of its dependencies») — یعنی هیچ قطعه‌بندیِ خاموشی بینِ دو بیلد وجود ندارد.

صادق بودن: ``verified`` در ``status()`` سه حالت دارد — ``gpu`` (پrobe گفت بیلدِ بسته GPU را
می‌شناسد)، ``cpu`` (پrobe گفت نه ⇒ بسته خودکار پاک شده) و ``not_run`` (هنوز راستی‌آزماییِ
اجرایِ واقعی روی این ماشین انجام نشده؛ مثلاً موتورِ llama از قبل در این نشست بارگذاری شده و
برنامه باید یک‌بار بسته/باز شود). هیچ‌وقت «فعال شد» بدونِ پrobe گفته نمی‌شود.

شبکه فقط از طریقِ ``app.core.downloader`` (ادامه‌پذیر، اثرانگشت، محدودهٔ ریدایرکت) انجام می‌شود.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from app.core import downloader, hardware
from app.core.paths import get_app_data_dir

# --------------------------------------------------------------------------------- کاتالوگ

LLAMA_REPO = "ggml-org/llama.cpp"
LLAMA_BUILD = "b12236"  # همان تگی که هش‌های زیر از APIِ همان انتشار گرفته شده‌اند
ASSET_URL = "https://github.com/ggml-org/llama.cpp/releases/download/{tag}/{name}"

# ریدایرکتِ فایل‌هایِ انتشارِ GitHub به اشیاءِ CDN خودش می‌رود؛ بدونِ این دوم هیچ دانلودی
# از نگهبانِ ``downloader`` رد نمی‌شد (همان درسی که برای CDNهایِ Hugging Face گرفته شد).
ALLOWED_HOSTS = frozenset({"github.com", "objects.githubusercontent.com", "githubusercontent.com"})

MB = 1024 * 1024  # برایِ سقف‌هایِ داخلی
DECIMAL_MB = 1_000_000  # «MB» همان‌طور که GitHub و مالک اندازه گرفته‌اند


@dataclass(frozen=True)
class PackPart:
    """یک زیپِ رسمیِ llama.cpp (یا ``cudart``) که بخشی از بستهٔ شتاب است."""

    key: str
    filename: str
    sha256: str
    size_bytes: int

    @property
    def url(self) -> str:
        return ASSET_URL.format(tag=LLAMA_BUILD, name=self.filename)

    @property
    def size_mb(self) -> float:
        return round(self.size_bytes / DECIMAL_MB, 1)


@dataclass(frozen=True)
class CudaTarget:
    """جفتِ «موتورِ CUDA + زمان‌اجرای CUDA» برایِ یک نسخهٔ ابزار."""

    key: str
    label: dict
    parts: tuple[PackPart, ...]

    @property
    def size_bytes(self) -> int:
        return sum(p.size_bytes for p in self.parts)

    @property
    def size_mb(self) -> float:
        return round(self.size_bytes / DECIMAL_MB, 1)


TARGETS: dict[str, CudaTarget] = {
    "cu12.4": CudaTarget(
        key="cu12.4",
        label={"fa": "CUDA 12.4 (پیشنهادِ ما)", "en": "CUDA 12.4 (recommended)"},
        parts=(
            PackPart(
                key="llama",
                filename=f"llama-{LLAMA_BUILD}-bin-win-cuda-12.4-x64.zip",
                sha256="652c0372dd5720c613c08ededf56716d258cc6b8865e1d021d696970f4ab4148",
                size_bytes=288953615,
            ),
            PackPart(
                key="cudart",
                filename="cudart-llama-bin-win-cuda-12.4-x64.zip",
                sha256="8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
                size_bytes=391443627,
            ),
        ),
    ),
    "cu13.5": CudaTarget(
        key="cu13.5",
        label={"fa": "CUDA 13.5 (درایورهایِ تازه)", "en": "CUDA 13.5 (newer drivers)"},
        parts=(
            PackPart(
                key="llama",
                filename=f"llama-{LLAMA_BUILD}-bin-win-cuda-13.5-x64.zip",
                sha256="162dcfa0205f0c12cefc40be9a0191cc08c653b860115687dda5ac8223fae454",
                size_bytes=170983241,
            ),
            PackPart(
                key="cudart",
                filename="cudart-llama-bin-win-cuda-13.5-x64.zip",
                sha256="c2bf4cc202bfbaaa7a0b75f5082457c3811326947bb216059b72839d844e9cba",
                size_bytes=426314199,
            ),
        ),
    ),
}

DEFAULT_CUDA = "cu12.4"

# آنچه «نصب‌شده» حساب می‌شود: این‌ها نبودند یعنی بستهٔ نصفه است (بارگذاریِ llama.dll بدونِ
# ggml.dll شکست می‌خورد — اندازه‌گیری‌شده — پس نصفه‌کاره هرگز «آماده» گزارش نمی‌شود).
REQUIRED_DLLS = ("llama.dll", "ggml.dll", "ggml-base.dll")
BACKEND_HINT = ("ggml-cuda.dll",)

DIR_NAME = "gpu_packs"
CACHE_NAME = "downloads"
META_NAME = "pack.json"
STATE_NAME = "state.json"
ENV_LIB_PATH = "LLAMA_CPP_LIB_PATH"
SCHEMA = 1

MAX_EXTRACT_BYTES = 3 * 1024**3  # سقفِ چیزی که یک زیپ اجازه دارد روی دیسک باز کند
MAX_EXTRACT_FILES = 400

STATE_ABSENT = "absent"
STATE_PARTIAL = "partial"
STATE_INSTALLED = "installed"

_PROGRESS = Callable[[int, int, str], None]
_CANCEL = Callable[[], bool]


class GpuPackError(Exception):
    """خطای قابل‌نمایش (فارسی) در کارِ بستهٔ شتاب."""


@dataclass(frozen=True)
class PackStatus:
    """راستیِ فایل‌سیستمیِ بسته + آخرین پاسخِ خودِ موتور."""

    cuda: str
    state: str
    windows: bool
    supported: bool
    has_nvidia: bool
    gpu_model: str
    gpu_vram_gb: Optional[float]
    enabled: bool
    files: tuple = ()
    missing: tuple = ()
    build: str = ""
    verified: str = "not_run"  # gpu | cpu | not_run
    loaded_here: bool = False  # llama_cppِ همین نشست واقعاً از پوشهٔ بسته آمده
    restart_needed: bool = False
    engine_broken: bool = False
    detail: str = ""
    download_bytes: int = 0
    size_bytes: int = 0

    @property
    def installed(self) -> bool:
        return self.state == STATE_INSTALLED

    @property
    def active(self) -> bool:
        """«روی گرافیک است» فقط وقتی بسته کامل است و خودِ بیلد GPU را شناخته."""
        return self.installed and self.verified == "gpu"

    @property
    def will_activate(self) -> bool:
        return self.installed and self.verified != "cpu"

    @property
    def backend(self) -> str:
        return "cuda" if self.active else "cpu"

    @property
    def resumable(self) -> bool:
        return self.download_bytes > 0


@dataclass
class InstallResult:
    """خروجیِ install() — هرگز استثنای خام به UI نمی‌دهد، جز GpuPackError برایِ «نشود»."""

    ok: bool
    state: str
    verified: str = "not_run"
    build: str = ""
    detail: str = ""
    cancelled: bool = False
    rolled_back: bool = False
    restart_needed: bool = False
    bytes_downloaded: int = 0
    files: tuple = ()
    log: list = field(default_factory=list)


# --------------------------------------------------------------------------------- مسیرها

def target_keys() -> tuple:
    return tuple(TARGETS)


def get_target(cuda: str = "") -> CudaTarget:
    key = (cuda or "").strip() or DEFAULT_CUDA
    if key not in TARGETS:
        raise GpuPackError(f"نسخهٔ CUDAیِ ناشناخته: {key} (مجاز: {' · '.join(target_keys())})")
    return TARGETS[key]


def root_dir() -> Path:
    return get_app_data_dir() / DIR_NAME


def pack_dir(cuda: str = "") -> Path:
    return root_dir() / get_target(cuda).key


def cache_dir(cuda: str = "") -> Path:
    return root_dir() / CACHE_NAME / get_target(cuda).key


def _state_path() -> Path:
    return root_dir() / STATE_NAME


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".writing")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _cuda_block(cuda: str) -> dict:
    return dict(_read_json(_state_path()).get(cuda) or {})


def _record(cuda: str, **fields) -> None:
    """آخرین نتیجه را بیرون از خودِ بسته نگه می‌دارد؛ بعدِ rollback هم باید قابل‌خواندن باشد."""
    path = _state_path()
    all_state = _read_json(path)
    block = dict(all_state.get(cuda) or {})
    block.update(fields)
    block["at"] = int(time.time())
    all_state[cuda] = block
    try:
        _write_json(path, all_state)
    except OSError:
        pass


# ---------------------------------------------------------------------------------- پلتفرم

def is_windows() -> bool:
    return sys.platform == "win32"


def nvidia_info(hw=None) -> tuple:
    """(کارتِ NVIDIA هست؟, نام, VRAM به گیگ) — از همان ``hardware.detect()`` (کش‌شده)."""
    info = hw if hw is not None else hardware.detect()
    name = (getattr(info, "gpu_model", "") or "").strip()
    low = name.lower()
    nvidia = bool(name) and any(k in low for k in ("nvidia", "geforce", "rtx", "gtx", "quadro", "tesla"))
    return nvidia, name, getattr(info, "gpu_vram_gb", None)


def _free_gb(path: Path) -> Optional[float]:
    try:
        return hardware.free_disk_gb_at(path)
    except Exception:  # noqa: BLE001 — نشد که نشد؛ مانعِ نصب نمی‌شیم (دقیقاً مثلِ مدل‌ها)
        return None


def block_reason(settings=None, hw=None) -> str:
    """علتِ «نصب نشود» (فارسی) یا رشتهٔ خالی وقتی همه‌چیز مهیاست."""
    if not is_windows():
        return (
            "بستهٔ شتابِ گرافیکی فقط برایِ ویندوزِ ۶۴-بیت ساخته شده است؛ روی لینوکس و مک همین "
            "را از بسته‌بندِ خودِ سیستم نصب کن. برنامه روی این سیستم همان‌طور که هست (با CPU) کار می‌کند."
        )
    nvidia, name, _vram = nvidia_info(hw)
    if not nvidia:
        return (
            f"کارتِ NVIDIA پیدا نشد (کارتِ فعلی: {name or 'نامشخص'}). بستهٔ CUDA هیچ سودی برایِ AMD یا Intel "
            "ندارد و فقط فضایِ دیسک می‌گیرد، پس نصب نمی‌شود."
        )
    free = _free_gb(get_app_data_dir())
    if free is not None and free < MIN_FREE_GB:
        return (
            f"فضایِ آزادِ دیسک کم است ({free:.1f} گیگ از {MIN_FREE_GB:.1f} گیگ لازم). "
            "اول کمی جا باز کن؛ برنامه تا وقتی بسته نصب نشده همان‌طور که هست (با CPU) کار می‌کند."
        )
    return ""


# ------------------------------------------------------------------------------ وضعیتِ بسته

def _dll_names(d: Path) -> tuple:
    try:
        return tuple(sorted(p.name for p in d.glob("*.dll") if p.is_file()))
    except OSError:
        return ()


def _meta(cuda: str) -> dict:
    return _read_json(pack_dir(cuda) / META_NAME)


def is_installed(cuda: str = "") -> bool:
    return status(cuda=cuda).installed


def status(settings=None, cuda: str = "", hw=None) -> PackStatus:
    """هیچ شبکه‌ای نمی‌زند و ``llama_cpp`` را import نمی‌کند — فقط فایل‌سیستم + آخرین پاسخِ موتور."""
    target = get_target(cuda or getattr(settings, "gpu_pack_cuda", "") or "")
    d = pack_dir(target.key)
    files = _dll_names(d)
    missing = tuple(n for n in REQUIRED_DLLS if n not in files)
    cuda_backend = any(n in files for n in BACKEND_HINT)
    has_cuda_dlls = any(f.startswith("ggml-cuda") or f.startswith("cudnn") or f.startswith("cublas") or f.startswith("cudart") for f in files)
    if not files and not (d / META_NAME).exists():
        state = STATE_ABSENT
    elif missing or not (cuda_backend or has_cuda_dlls):
        state = STATE_PARTIAL
    else:
        state = STATE_INSTALLED

    recorded = _cuda_block(target.key)
    loaded_here = _loaded_from(d)
    verified = str(recorded.get("verified") or "not_run")
    if loaded_here:
        # بیلدِ بسته همین حالا در این نشست بارگذاری شده: می‌توانیم بی‌هزینه از خودِ آن بپرسیم.
        fresh = _probe_loaded_module()
        if fresh is not None:
            verified = "gpu" if fresh else "cpu"

    download_bytes = 0
    try:
        for part in target.parts:
            download_bytes += downloader.partial_bytes(cache_dir(target.key) / part.filename)
    except GpuPackError:
        download_bytes = 0

    nvidia, name, vram = nvidia_info(hw)
    build = str(recorded.get("build") or (_meta(target.key).get("build") if state != STATE_ABSENT else "") or "")
    if state != STATE_INSTALLED:
        build = ""
    return PackStatus(
        cuda=target.key,
        state=state,
        windows=is_windows(),
        supported=is_windows(),
        has_nvidia=nvidia,
        gpu_model=name,
        gpu_vram_gb=vram,
        enabled=bool(getattr(settings, "gpu_pack_enabled", True)),
        files=files,
        missing=tuple(n for n in (*REQUIRED_DLLS, *BACKEND_HINT) if n not in files),
        build=build or (LLAMA_BUILD if state == STATE_INSTALLED else ""),
        verified=verified if state == STATE_INSTALLED else "not_run",
        loaded_here=loaded_here,
        restart_needed=bool(state == STATE_INSTALLED and not loaded_here and _llama_imported()),
        engine_broken=bool(recorded.get("engine_broken")) and state != STATE_INSTALLED,
        detail=str(recorded.get("detail") or ""),
        download_bytes=download_bytes,
        size_bytes=target.size_bytes,
    )


def _llama_imported() -> bool:
    return "llama_cpp" in sys.modules


def _loaded_from(d: Path) -> bool:
    """آیا ``llama.dll``ِ بارگذاری‌شده در این نشست از همین پوشه آمده؟ (پوشهٔ بسته نه site-packages)."""
    mod = sys.modules.get("llama_cpp.llama_cpp")
    lib = getattr(mod, "_lib", None)
    name = str(getattr(lib, "_name", "") or "")
    if not name:
        return False
    try:
        return Path(name).resolve().parent == Path(d).resolve()
    except OSError:
        return False


def _probe_loaded_module() -> Optional[bool]:
    """پاسخِ خودِ بیلدِ بارگذاری‌شده (بدونِ importِ تازه). اگر چیزی بارگذاری نشده باشد ``None``."""
    mod = sys.modules.get("llama_cpp")
    fn = getattr(mod, "llama_supports_gpu_offload", None)
    if mod is None or fn is None:
        return None
    try:
        return bool(fn())
    except Exception:  # noqa: BLE001 — پاسخِ ندادنِ سمبل همان «CPU-only» بودن است
        return False


# ------------------------------------------------------------------- راستی‌آزماییِ موتورِ بسته

# کدی که در زیرفرآیند اجرا می‌شود: llama_cpp را *با پوشهٔ بسته* بارگذاری می‌کند و می‌گوید
# آن بیلد GPU را می‌شناسد یا نه. چرا زیرفرآیند: import شدنِ llama_cpp در خودِ برنامه، فرآیندِ
# گرافیکی را به یک بیلد قفل می‌کند؛ اگر همان‌جا شکست بخورد موتورِ برنامه خراب می‌ماند.
_PROBE_SRC = """
import json, os
out = {"ok": False, "gpu": False, "build": "", "system_info": "", "lib": "", "api": False,
       "model_ok": None, "model_cpu_ok": None, "model_note": "", "error": ""}
try:
    import llama_cpp as L
    import llama_cpp.llama_cpp as LC
    out["ok"] = True
    out["lib"] = str(getattr(LC._lib, "_name", "") or "")
    out["gpu"] = bool(L.llama_supports_gpu_offload())
    try:
        out["build"] = "b%d" % int(L.llama_version())
    except Exception:
        pass
    try:
        raw = L.llama_print_system_info() or b""
        out["system_info"] = (raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw))[:400]
    except Exception:
        pass
    try:
        # سمبل‌هایی که بارگذاریِ مدل به آن‌ها دست می‌زند: اگر بیلدِ بسته با binding‌هایِ
        # نصب‌شده هم‌ABI نباشد همین‌جا (نه وسطِ چتِ مشتری) معلوم می‌شود.
        L.llama_backend_init()
        L.llama_model_default_params()
        L.llama_context_default_params()
        out["api"] = True
    except Exception as exc:
        out["error"] = "api: " + (type(exc).__name__ + " " + str(exc))[:160]
    model = (os.environ.get("SBL_GPU_PROBE_MODEL") or "").strip()
    if model and out["api"]:
        layers = int(os.environ.get("SBL_GPU_PROBE_LAYERS") or "-11")
        try:
            from llama_cpp import Llama
            llm = Llama(model_path=model, n_ctx=512, n_gpu_layers=layers, verbose=False, temperature=0.0)
            llm.create_completion("سلام", max_tokens=4)
            llm.close()
            out["model_ok"] = True
        except Exception as exc:
            out["model_ok"] = False
            out["model_note"] = (type(exc).__name__ + " " + str(exc))[:220]
            try:
                llm = Llama(model_path=model, n_ctx=512, n_gpu_layers=0, verbose=False)
                llm.create_completion("سلام", max_tokens=4)
                llm.close()
                out["model_cpu_ok"] = True
            except Exception as exc2:
                out["model_cpu_ok"] = False
                out["model_note"] += " | cpu-retry: " + (type(exc2).__name__ + " " + str(exc2))[:120]
except Exception as exc:
    out["error"] = (type(exc).__name__ + ": " + str(exc))[:240]
print("@@GPU_PACK_PROBE@@" + json.dumps(out) + "@@END@@")
""".strip()

# مدل‌هایِ بزرگ را برایِ «آزمایشِ دودِ موتور» بار نمی‌کنیم: ۶۰ ثانیه صبر و ریسکِ کم‌آوردنِ رم
# در برابرِ اطلاعاتِ اضافه‌ای که نمی‌دهد (پرسشِ توانِ GPU همان‌جا پاسخ شده است).
SMOKE_MODEL_MAX_BYTES = 3 * 1024**3


@dataclass
class ProbeResult:
    ran: bool
    gpu: bool = False
    build: str = ""
    detail: str = ""
    in_process: bool = False
    loaded: bool = False
    api_ok: bool = True
    model_ok: Optional[bool] = None


def _smoke_model(settings=None) -> tuple:
    """(مسیرِ مدلِ واقعی برایِ بارگذاری، عددِ لایه‌ای که موتورِ تولیدی هم می‌داد).

    همان ``ai_engine.gpu_layer_tier`` صدا زده می‌شود، پس آنچه نصبِ بسته می‌آزماید دقیقاً همان
    پیکربندیِ چتِ واقعی است — نه یک عددِ دلخواه."""
    try:
        from app.core import ai_engine  # noqa: PLC0415 — چرخهٔ import

        path = ai_engine.resolve_model_path(settings) if settings is not None else None
        if path is not None and path.is_file() and path.stat().st_size <= SMOKE_MODEL_MAX_BYTES:
            vram = nvidia_info()[2]
            return str(path), int(ai_engine.gpu_layer_tier(vram or 0.0, path.stat().st_size))
    except Exception:  # noqa: BLE001 — نبودِ مدل فقط یعنی «آزمایشِ دود انجام نشد»
        pass
    return "", 0


def _can_spawn() -> bool:
    return not bool(getattr(sys, "frozen", False)) and bool(sys.executable)


def _probe_subprocess(d: Path, model: str = "", layers: int = 0, timeout: float = 600.0) -> Optional[ProbeResult]:
    if not _can_spawn():
        return None
    env = dict(os.environ)
    env[ENV_LIB_PATH] = str(d)
    if model:
        env["SBL_GPU_PROBE_MODEL"] = model
        env["SBL_GPU_PROBE_LAYERS"] = str(int(layers))
    else:
        env.pop("SBL_GPU_PROBE_MODEL", None)
    try:
        proc = subprocess.run(  # noqa: S603 — مفسرِ خودِ برنامه، کدِ ثابتِ بالا، بدونِ shell
            [sys.executable, "-c", _PROBE_SRC], capture_output=True, text=True, timeout=timeout, env=env, cwd=str(d)
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ProbeResult(ran=False, detail=f"زیرفرآیندِ بررسی بالا نیامد: {type(exc).__name__}")
    marker = "@@GPU_PACK_PROBE@@"
    out = proc.stdout or ""
    if marker not in out:
        return ProbeResult(ran=False, detail=(proc.stderr or out or "پاسخی برنگشت")[-300:].strip())
    body = out.split(marker, 1)[1].split("@@END@@", 1)[0]
    try:
        data = json.loads(body)
    except ValueError:
        return ProbeResult(ran=False, detail="پاسخِ بررسی خوانا نبود")
    note = str(data.get("model_note") or data.get("error") or "")
    return ProbeResult(
        ran=True,
        loaded=bool(data.get("ok")),
        gpu=bool(data.get("gpu")),
        build=str(data.get("build") or ""),
        api_ok=bool(data.get("api")),
        model_ok=data.get("model_ok") if isinstance(data.get("model_ok"), bool) else None,
        detail=(str(data.get("system_info") or "") + (" | " + note if note else ""))[:300],
    )


def _probe_in_process(d: Path) -> Optional[ProbeResult]:
    """فقط وقتی که ``llama_cpp`` هنوز بارگذاری نشده باشد — وگرنه پاسخ از بیلدِ دیگری است."""
    if _llama_imported():
        return None
    os.environ[ENV_LIB_PATH] = str(d)
    _add_dll_dir(d)
    try:
        import llama_cpp as L  # noqa: PLC0415 — عمداً همین‌جا: با envِ تازه باید بارگذاری شود
    except Exception as exc:  # noqa: BLE001 — نبودِ DLL = همان «موتورِ گرافیکی نشد»
        _purge_llama_modules()
        os.environ.pop(ENV_LIB_PATH, None)
        return ProbeResult(ran=True, loaded=False, gpu=False, detail=f"{type(exc).__name__}: {str(exc)[:200]}")
    try:
        gpu = bool(L.llama_supports_gpu_offload())
    except Exception as exc:  # noqa: BLE001
        gpu = False
        note = f"{type(exc).__name__}: {str(exc)[:200]}"
    else:
        note = "in-process"
    build = ""
    try:
        build = "b%d" % int(L.llama_version())
    except Exception:  # noqa: BLE001
        build = LLAMA_BUILD
    if not gpu:
        # بیلدِ بسته در این نشست بارگذاری شده و پاسخ «CPU» داده: پاک‌کردنِ sys.modules دی‌ال‌ال را
        # از حافظه درنمی‌آورد، پس راستش را می‌گوییم (یک‌بار بستن و بازکردنِ برنامه) و rollback را
        # به عهدهٔ فراخوان می‌گذاریم.
        _purge_llama_modules()
        os.environ.pop(ENV_LIB_PATH, None)
        note += " · بسته را پاک می‌کنیم؛ برایِ برگشتِ قطعیِ موتور به CPU برنامه را یک‌بار ببند و باز کن."
    return ProbeResult(ran=True, loaded=True, gpu=gpu, build=build, detail=note, in_process=True)


def _purge_llama_modules() -> None:
    for name in [n for n in list(sys.modules) if n == "llama_cpp" or n.startswith("llama_cpp.")]:
        sys.modules.pop(name, None)


def probe(d: Optional[Path] = None, cuda: str = "", settings=None) -> ProbeResult:
    """از خودِ بیلدِ بسته می‌پرسد GPU را می‌شناسد یا نه. ``ran=False`` یعنی «نپرسیدیم» (حدس نه)."""
    d = Path(d) if d is not None else pack_dir(cuda)
    model, layers = _smoke_model(settings)
    got = _probe_subprocess(d, model=model, layers=layers)
    if got is not None:
        return got
    mine = _probe_in_process(d)
    if mine is not None:
        return mine
    return ProbeResult(ran=False, detail="موتورِ llama در این نشست از قبل بارگذاری است؛ برنامه را دوباره باز کن.")


# ------------------------------------------------------------------- فعال‌سازی (کشفِ DLLها)

_dll_handles: list = []  # هندلِ add_dll_directory باید زنده بماند، وگرنه پوشه از مسیرِ جست‌وجو می‌رود
_activated_dir: str = ""


def _add_dll_dir(d: Path) -> None:
    if not is_windows() or not hasattr(os, "add_dll_directory"):
        return
    text = str(d)
    try:
        _dll_handles.append(os.add_dll_directory(text))
    except OSError:
        pass  # پوشه رفته/خواندنی — همان چیزی که probe بعداً صادقانه می‌گوید
    path = os.environ.get("PATH", "")
    if text not in path.split(os.pathsep):
        os.environ["PATH"] = text + os.pathsep + path


def activate(cuda: str = "") -> bool:
    """مسیرِ کشفِ کتابخانه را به پوشهٔ بسته می‌برد. ``True`` یعنی «موتورِ llama از همین پوشه می‌آید».

    فقط تا پیشِ اولین ``import llama_cpp`` اثر دارد؛ اگر بیلدِ دیگری از قبل بارگذاری شده باشد
    دروغ نمی‌گوییم و ``False`` برمی‌گردانیم (راه‌حل: یک‌بار بستن و بازکردنِ برنامه)."""
    global _activated_dir
    if not status(cuda=cuda).installed:
        return False
    d = pack_dir(get_target(cuda).key)
    if _llama_imported():
        return _loaded_from(d)
    os.environ[ENV_LIB_PATH] = str(d)
    if _activated_dir != str(d):
        _add_dll_dir(d)
        _activated_dir = str(d)
    return True


def deactivate(cuda: str = "") -> None:
    """برگشت به CPU: متغیرِ محیطی پاک می‌شود تا ``llama_cpp`` دوباره از بیلدِ خودِ بسته بیاید."""
    global _activated_dir
    current = os.environ.get(ENV_LIB_PATH, "")
    try:
        if current and Path(current).resolve().parent == root_dir().resolve():
            os.environ.pop(ENV_LIB_PATH, None)
    except OSError:
        os.environ.pop(ENV_LIB_PATH, None)
    if _activated_dir and current == _activated_dir:
        _activated_dir = ""


def ensure_active(settings=None) -> bool:
    """قلابِ ``ai_engine``: اگر مالک بسته را خاموش نکرده باشد و بسته نصب باشد، موتور را روی آن می‌برد."""
    if settings is not None and not bool(getattr(settings, "gpu_pack_enabled", True)):
        return False
    return bool(activate(getattr(settings, "gpu_pack_cuda", "") or ""))


# -------------------------------------------------------------------------------- دانلود/بازکردن

def _parts_with_overrides(target: CudaTarget, settings=None) -> tuple:
    """``gpu_pack_urls`` (پیشرفته): هر خط یک آدرسِ جایگزین، به ترتیبِ همان اجزایِ کاتالوگ.

    اگر همان خط هش هم بدهد (``<url> <sha256>``) همان جایگزینِ پین‌شده می‌شود؛ اگر ندهد،
    **هشِ قفل‌شدهٔ کاتالوگ** بررسی می‌ماند — آدرسِ تازه هیچ‌وقت مجوزِ «فایلِ هر جور» نمی‌گیرد."""
    raw = str(getattr(settings, "gpu_pack_urls", "") or "").strip()
    out = []
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    for index, part in enumerate(target.parts):
        extra_url, extra_sha = "", ""
        if index < len(lines):
            pieces = lines[index].split()
            extra_url = pieces[0]
            if len(pieces) > 1 and len(pieces[1]) == 64:
                extra_sha = pieces[1].lower()
        urls = ([extra_url] if extra_url else []) + [part.url]
        out.append({"part": part, "urls": urls, "sha256": extra_sha or part.sha256})
    return tuple(out)


# آنچه از زیپ روی دیسک می‌آید: فقط DLLهایی که ``llama.dll``/``ggml.dll`` واقعاً لازم دارند.
# بقیه (llama-server.exe و …) برایِ برنامه بی‌فایده‌اند و ~۱۴۰ مگابایت جا می‌گیرند.
_EXTRACT_EXACT = frozenset({"llama.dll", "ggml.dll", "ggml-base.dll", "mtmd.dll", "libomp.dll", "ggml-cuda.dll"})
_EXTRACT_PREFIX = ("ggml-cpu-", "cudart", "cublas", "cudnn")

# ~۱٫۲ گیگ باز می‌شود + یک زیپِ ۳۹۱ مگابایتیِ موقت (اندازه‌گیری‌شده از همین بسته‌ها).
MIN_FREE_GB = 2.5


def _wanted_dll(base: str) -> bool:
    low = base.lower()
    if not low.endswith(".dll"):
        return False
    if low in _EXTRACT_EXACT:
        return True
    return any(low.startswith(p) for p in _EXTRACT_PREFIX)


def _entry_basename(info: zipfile.ZipInfo) -> str:
    """نامِ داخلِ زیپ را نرمال‌سازی می‌کند و فقط یک *نامِ ساده* برمی‌گرداند.

    هر ``..``، مسیرِ مطلق یا درایو ⇒ خطا (نگهبانِ zip-slip؛ نیمه‌کاره گذاشتنِ بستهٔ
    ناشناخته از پذیرفتنِ آن خطرناک‌تر نیست، پس سخت رد می‌شود)."""
    raw = str(info.filename).replace("\\", "/")
    segments = [s for s in raw.split("/") if s not in ("", ".")]
    base = segments[-1] if segments else ""
    if (
        not segments
        or not base
        or any(s == ".." for s in segments)
        or ":" in base
        or raw.startswith("//")
        or base != Path(base).name
        or Path(base).is_absolute()
    ):
        raise GpuPackError(f"نامِ فایلِ داخلِ زیپِ بسته مجاز نیست: {info.filename!r}")
    return base


def _extract_dlls(zip_path: Path, dest: Path) -> tuple:
    """فقط DLLهایِ لازم را بیرون می‌ریزد (تخت، داخلِ ``dest``). برمی‌گرداند: (نام‌ها، بایتِ باز شده)."""
    dest.mkdir(parents=True, exist_ok=True)
    resolved_root = dest.resolve()
    names: list = []
    written = 0
    with zipfile.ZipFile(zip_path) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > MAX_EXTRACT_FILES:
            raise GpuPackError("زیپ بیش از حد فایل داشت؛ نصب متوقف شد.")
        for info in infos:
            base = _entry_basename(info)
            if not _wanted_dll(base):
                continue
            written += max(0, int(info.file_size))
            if written > MAX_EXTRACT_BYTES:
                raise GpuPackError("زیپ از سقفِ حجمِ مجاز بزرگ‌تر شد (فایلِ دستکاری‌شده؟).")
            target = resolved_root / base
            if os.path.commonpath([str(resolved_root), str(target.resolve())]) != str(resolved_root):
                raise GpuPackError(f"فایلِ داخلِ زیپ از پوشهٔ بسته بیرون می‌زند: {info.filename}")
            tmp = target.with_name(target.name + ".part")
            with zf.open(info) as src, open(tmp, "wb") as out:
                for block in iter(lambda: src.read(1024 * 512), b""):
                    out.write(block)
            os.replace(tmp, target)
            names.append(base)
    return tuple(names), written


def _rollback(cuda: str, detail: str) -> None:
    """بسته را کامل پاک می‌کند تا موتورِ بعدی دوباره بیلدِ سالمِ خودِ برنامه باشد."""
    uninstall(cuda=cuda, keep_cache=True)
    _record(cuda, verified="cpu", build="", detail=detail, engine_broken=False, restart_needed=False)

# --------------------------------------------------------------------------------- کارها

def install(
    settings=None,
    cuda: str = "",
    progress_cb: Optional[_PROGRESS] = None,
    cancel_cb: Optional[_CANCEL] = None,
    hw=None,
    verify: bool = True,
) -> InstallResult:
    """دانلود + راستی‌آزمایی + بازکردن + فعال‌سازی و در پایان **پرسیدن از خودِ بیلد**.

    اگر آن پرسش بگوید «GPU نه»، همان‌جا rollback می‌شود (بسته پاک، CPU برمی‌گردد) و علت
    در ``detail`` می‌آید. هیچ حالتی نیست که موتورِ خراب انتخاب شده بماند."""
    target = get_target(cuda or getattr(settings, "gpu_pack_cuda", "") or "")
    reason = block_reason(settings=settings, hw=hw)
    if reason:
        raise GpuPackError(reason)

    plan = _parts_with_overrides(target, settings)
    total = sum(int(p["part"].size_bytes) for p in plan)
    done_before = 0
    got: list = []
    extracted: list = []
    where = cache_dir(target.key)
    where.mkdir(parents=True, exist_ok=True)

    def emit(done: int, phase: str) -> None:
        if progress_cb is not None:
            progress_cb(min(done, total) if total else done, total, phase)

    try:
        for item in plan:
            part: PackPart = item["part"]
            dest_zip = where / part.filename
            base = done_before
            if cancel_cb is not None and cancel_cb():
                raise downloader.DownloadCancelled()

            def on_progress(got_bytes: int, _total: int, _base: int = base, _name=part.filename) -> None:
                got.append(got_bytes)
                emit(_base + got_bytes, "download")

            emit(base + downloader.partial_bytes(dest_zip), "download")

            if dest_zip.is_file():
                # زیپِ کاملِ راستی‌آزمایی‌شده از کارِ قبلی مانده: دوباره دانلود نمی‌کنیم
                # (۶۸۰ مگابایت در هر بارِ «نصب» بی‌رحمانه است).
                ok_file, _msg = downloader.verify_file(dest_zip, item["sha256"])
                if ok_file:
                    got.append(part.size_bytes)
                    emit(base + part.size_bytes, "extract")
                    names, _bytes = _extract_dlls(dest_zip, pack_dir(target.key))
                    extracted.extend(names)
                    done_before = base + part.size_bytes
                    continue
                dest_zip.unlink(missing_ok=True)

            downloader.download(
                item["urls"], dest_zip,
                expected_sha256=item["sha256"], expected_size=part.size_bytes,
                on_progress=on_progress, should_cancel=cancel_cb, allowed_hosts=set(ALLOWED_HOSTS),
            )
            done_before = base + part.size_bytes
            names, _bytes = _extract_dlls(dest_zip, pack_dir(target.key))
            extracted.extend(names)
            try:
                dest_zip.unlink(missing_ok=True)  # زیپ لازم نیست؛ جایِ ۶۰۰ مگابایت را روی دیسکِ فروشنده نگه نداریم
            except OSError:
                pass
            emit(done_before, "extract")
    except downloader.DownloadCancelled:
        _record(target.key, verified="not_run", detail="نصب نیمه‌کاره ماند (لغوِ کاربر)؛ دانلود از همان‌جا ادامه می‌کند.")
        return InstallResult(ok=False, state=status(cuda=target.key).state, cancelled=True,
                             detail="نصب نیمه‌کاره ماند؛ فایل‌هایِ آمده پاک نشده‌اند و با «نصبِ دوباره» از همان‌جا ادامه می‌شه.",
                             bytes_downloaded=done_before)
    except (downloader.DownloadError, zipfile.BadZipFile, OSError) as exc:
        _record(target.key, verified="not_run", detail=str(exc)[:300])
        raise GpuPackError(str(exc)) from exc

    files = _dll_names(pack_dir(target.key))
    missing = [n for n in REQUIRED_DLLS if n not in files]
    if missing:
        _rollback(target.key, f"باز نشد: نبودِ {', '.join(missing)}")
        raise GpuPackError("بسته کامل باز نشد (" + "، ".join(missing) + ")؛ هیچ چیزی عوض نشد و برنامه با CPU کار می‌کند.")

    _write_json(pack_dir(target.key) / META_NAME, {
        "schema": SCHEMA, "cuda": target.key, "build": LLAMA_BUILD, "files": list(files),
        "verified": "not_run", "installed_at": int(time.time()),
    })
    _record(target.key, detail="بسته دانلود و باز شد؛ در حالِ پرسیدن از خودِ موتور…")

    if not verify:
        return InstallResult(ok=True, state=STATE_INSTALLED, build=LLAMA_BUILD, files=files, bytes_downloaded=done_before)

    emit(total, "verify")
    result = probe(pack_dir(target.key), cuda=target.key, settings=settings)
    if not result.ran:
        # نتوانستیم بپرسیم ⇒ rollback نه (شاید بسته سالم باشد)، «فعال شد» هم نه.
        _record(target.key, verified="not_run", build=result.build or LLAMA_BUILD,
                detail=result.detail, restart_needed=True)
        return InstallResult(ok=True, state=STATE_INSTALLED, verified="not_run", build=LLAMA_BUILD, detail=result.detail,
                             restart_needed=True, bytes_downloaded=done_before, files=files,
                             log=["بررسی در این نشست ممکن نشد؛ برنامه را ببند و دوباره باز کن."])
    smoke_failed = result.model_ok is False
    if not result.loaded or not result.api_ok or not result.gpu or smoke_failed:
        if not result.loaded:
            why = "موتورِ گرافیکی روی این سیستم بالا نیامد (DLL بارگذاری نشد)"
        elif not result.api_ok:
            why = "بیلدِ بسته با ماشینیِ اجرایِ برنامه (llama-cpp-python) سازگار نبود"
        elif not result.gpu:
            why = "خودِ موتور گفت لایه‌ای روی گرافیک نمی‌گذارد (درایور؟ نسخهٔ CUDA؟)"
        else:
            why = "مدل با بیلدِ گرافیکی بارگذاری نشد"
        detail = f"{why}. ({result.detail[:160]})"
        _rollback(target.key, detail)
        return InstallResult(ok=False, state=STATE_ABSENT, verified="cpu", rolled_back=True, bytes_downloaded=done_before,
                             detail=detail + " بسته پاک شد و برنامه با CPU ادامه می‌دهد.")
    build = result.build or LLAMA_BUILD
    note = result.detail or "ok"
    if result.model_ok is None:
        note += " · بارگذاریِ مدلِ واقعی آزموده نشد (مدلِ آماده‌یِ کوچک در دسترس نبود)"
    _record(target.key, verified="gpu", build=build, detail=note, engine_broken=False,
            restart_needed=bool(result.in_process))
    from app.core import ai_engine  # noqa: PLC0415 — چرخهٔ import: ai_engine هم gpu_pack را می‌شناسد

    ai_engine.reset_gpu_offload_cache()
    return InstallResult(ok=True, state=STATE_INSTALLED, verified="gpu", build=build, bytes_downloaded=done_before,
                         files=files, restart_needed=bool(result.in_process),
                         detail="فعال شد: پاسخ‌ها روی گرافیک." if not result.in_process else
                                "بسته بررسی شد و GPU را می‌شناسد؛ از راه‌اندازیِ دوباره‌ی برنامه قطعی می‌شود.")


def uninstall(cuda: str = "", settings=None, keep_cache: bool = False) -> tuple:
    """contentsِ پوشهٔ بسته را می‌برد (هیچ‌وقت بیرون از آن چیزی پاک نمی‌شود)."""
    target = get_target(cuda or getattr(settings, "gpu_pack_cuda", "") or "")
    ok = True
    d = pack_dir(target.key)
    resolved = d.resolve()
    root = root_dir().resolve()
    if resolved == root or not str(resolved).startswith(str(root)):
        return False, "مسیرِ بسته غیرمنتظره است؛ چیزی پاک نشد."
    if d.exists():
        for item in sorted(d.iterdir()):
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            except OSError:
                ok = False
    if not keep_cache:
        cache = cache_dir(target.key)
        if cache.exists():
            for item in sorted(cache.iterdir()):
                try:
                    item.unlink()
                except OSError:
                    ok = False
    deactivate(target.key)
    _record(target.key, verified="not_run", build="", detail="بستهٔ شتاب حذف شد؛ موتورِ CPUیِ خودِ برنامه به کار می‌آید.",
            restart_needed=False, engine_broken=not ok)
    from app.core import ai_engine  # noqa: PLC0415

    ai_engine.reset_gpu_offload_cache()
    if ok:
        try:
            d.rmdir()
        except OSError:
            pass
    return ok, ("بسته حذف شد." if ok else "بعضی فایل‌ها پاک نشدند (شاید مدل همین حالا روی گرافیک باز باشد)؛ "
                                       "ربات را خاموش کن و دوباره امتحان کن.")


def describe_sizes(cuda: str = "") -> tuple:
    """[(نامِ فایل, مگابایتِ اندازه‌گیری‌شده)] — همان اعدادی که در UI وعده داده می‌شود."""
    target = get_target(cuda)
    return [(p.filename, p.size_mb) for p in target.parts]
