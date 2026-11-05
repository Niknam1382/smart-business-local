"""
موتورِ هوش مصنوعیِ **فقط محلی**.

از نسخه‌ی ۱.۰.۰ هیچ تماسی با سرویس بیرونی گرفته نمی‌شه: مدلِ GGUF روی کامپیوترِ خودِ فروشنده
اجرا می‌شه (llama-cpp-python) و هیچ پیامِ مشتری از دستگاه بیرون نمی‌ره.

`LocalEngine` عمداً llama_cpp را «تنبل» (داخلِ متد، نه بالای فایل) ایمپورت می‌کنه تا بقیه‌ی
برنامه — و تست‌های CI که llama ندارند — بدونِ این کتابخونه‌ی سنگین هم کار و تست بشن.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core import tool_protocol

# بعضی قالب‌های گفتگو بلوکِ «تفکر» می‌سازن. مدل‌هایِ کاتالوگ ما در حالتِ بدونِ تفکر اجرا
# می‌شن، ولی این پاک‌سازیِ خروجی عمداً می‌مونه: اگر روزی قالبی بلوکِ تفکر را داخلِ content
# بریزه، هرگز توی چتِ مشتری چاپ نمی‌شه.
_THINK_OPEN = "<" + "think"
_THINK_CLOSE = "<" + "/" + "think" + ">"
_THINK_BLOCK = re.compile(re.escape(_THINK_OPEN) + r"\b[^>]*>.*?" + re.escape(_THINK_CLOSE), re.DOTALL)


class AiEngineError(Exception):
    """خطای قابل‌نمایش به کاربر (فارسی) برای هر مشکلی در اجرای مدل."""


@dataclass
class ChatMessage:
    role: str  # "user" یا "assistant"
    content: str


def _strip_think(text: str) -> str:
    """بلوکِ «تفکر» را کامل می‌بردارد، حتی اگر برچسب‌ها نصفه باشند.

    چرا این‌قدر وسوس: اگر قالبِ گفتگوی مدلی بلوکِ تفکر را داخلِ content بریزد و ما فقط
    برچسب‌ها را پاک کنیم، استدلالِ خامِ مدل برای مشتری می‌رود. پس: جفت‌هایِ کامل حذف
    می‌شن، هر برچسبِ بازِ بی‌بست هم تا پایانِ متن دور ریخته می‌شه، و برچسبِ بستِ یتیم
    پاک می‌شه تا چیزی شبیه تگ در پاسخِ مشتری نماند."""
    if _THINK_OPEN not in text and _THINK_CLOSE not in text:
        return text.strip()
    cleaned = _THINK_BLOCK.sub("", text)
    open_at = cleaned.find(_THINK_OPEN)
    if open_at != -1 and cleaned.find(_THINK_CLOSE, open_at) == -1:
        cleaned = cleaned[:open_at]  # بازِ بی‌بست: هرچه از اینجا آمد تفکرِ نیمه‌کاره بود
    cleaned = cleaned.replace(_THINK_CLOSE, "").replace(_THINK_OPEN, "")
    return cleaned.strip()


def _trim_history(
    system_prompt: str, history: list[ChatMessage], new_message: str, max_chars: int
) -> list[ChatMessage]:
    """پیام‌های قدیمی‌تر رو از ابتدا کنار می‌ذاره تا کل مکالمه از max_chars
    کاراکتر رد نشه. تخمین کاراکتر به‌جای توکن — ساده و برای این فاز کافیه."""
    budget = max_chars - len(system_prompt) - len(new_message)
    trimmed: list[ChatMessage] = []
    used = 0
    for msg in reversed(history):
        cost = len(msg.content) + 20  # کمی حاشیه برای فرمت هر پیام
        if used + cost > budget:
            break
        trimmed.insert(0, msg)
        used += cost
    return trimmed


def _tool_messages_chars(tool_messages: list) -> int:
    """حجمِ تبادل‌های ابزارِ همین نوبت (نتیجه‌ی کارِ ایجنت) — از بودجه‌ی تاریخچه کم
    می‌شه تا پرامپتِ نهایی از پنجره‌ی زمینه‌ی مدل بیرون نزنه."""
    total = 0
    for m in tool_messages:
        total += len(m.get("content") or "")
        for call in m.get("tool_calls") or []:
            total += len(call["name"]) + len(json.dumps(call["arguments"], ensure_ascii=False)) + 40
    return total


class LocalEngine:
    # یه نمونه‌ی Llama نباید هم‌زمان از چند ترد صدا زده بشه (حالتِ داخلیش خراب
    # می‌شه) — پایپ‌لاین ربات تماس‌های محلی رو پشت یه قفل سریالی می‌کنه.
    concurrent_safe = False

    def __init__(
        self,
        model_path: Path,
        n_ctx: int = 4096,
        n_gpu_layers: int = 0,  # بیلدِ رسمیِ برنامه فقط-CPUه؛ ۰ = درست. کاربرِ حرفه‌ای می‌تونه بالا ببره.
        n_threads: Optional[int] = None,
        model_id: str = "",
    ):
        self.model_path = Path(model_path)
        self.n_ctx = int(n_ctx)
        self.n_gpu_layers = int(n_gpu_layers)
        self.n_threads = n_threads
        self.model_id = model_id
        self._llm = None
        self.record_usage = True
        self.last_usage: dict = {}

    def _ensure_loaded(self) -> None:
        if self._llm is not None:
            return
        if not self.model_path.exists():
            raise AiEngineError("فایلِ مدل هنوز دانلود نشده. از صفحه‌ی «هوش مصنوعی» دانلودش کن.")
        try:
            from llama_cpp import Llama  # ایمپورت تنبل — عمداً همین‌جا، نه بالای فایل
        except ImportError as exc:
            raise AiEngineError("کتابخونه‌ی llama-cpp-python روی این سیستم نصب نیست.") from exc

        kwargs = dict(
            model_path=str(self.model_path),
            n_ctx=self.n_ctx,
            n_gpu_layers=self.n_gpu_layers,
            verbose=False,
        )
        if self.n_threads:
            kwargs["n_threads"] = int(self.n_threads)
        try:
            self._llm = Llama(**kwargs)
        except Exception as exc:
            raise AiEngineError(f"بارگذاری مدل شکست خورد: {exc}") from exc

    def chat(self, system_prompt: str, history: list[ChatMessage], user_message: str) -> str:
        self._ensure_loaded()
        trimmed = _trim_history(system_prompt, history, user_message, max_chars=self.n_ctx * 3)
        messages = [{"role": "system", "content": system_prompt}]
        messages += [{"role": m.role, "content": m.content} for m in trimmed]
        messages.append({"role": "user", "content": user_message})

        began = time.monotonic()
        try:
            result = self._llm.create_chat_completion(messages=messages, temperature=0.4, max_tokens=512)
        except Exception as exc:
            self._note_failure(messages, user_message, began)
            raise AiEngineError(f"اجرای مدل محلی شکست خورد: {exc}") from exc

        answer = _strip_think(result["choices"][0]["message"].get("content") or "")
        self._note_usage(result, messages, answer, began, "chat")
        return answer

    def _note_usage(self, result, messages: list, answer: str, began: float, kind: str) -> None:
        usage = result.get("usage") if isinstance(result, dict) else None
        self.last_usage = dict(usage) if isinstance(usage, dict) and "prompt_tokens" in usage else {}
        if not self.record_usage:
            return
        from app.core import ai_usage, token_budget

        ai_usage.record_call(
            provider_id="local",
            model=self.model_id or self.model_path.name,
            kind=kind,
            ok=True,
            latency_ms=int((time.monotonic() - began) * 1000),
            estimated=not self.last_usage,
            prompt_tokens=self.last_usage.get("prompt_tokens") or token_budget.messages_tokens(messages),
            completion_tokens=self.last_usage.get("completion_tokens") or token_budget.estimate_tokens(answer or ""),
        )

    def _note_failure(self, messages: list, user_message: str, began: float) -> None:
        """ردیفِ «ناموفق» برای اینکه صفحهٔ مصرف و عیب‌یاب ببینند مدل واقعاً جواب نداده (هزینهٔ رم هم سوخته است)."""
        if not self.record_usage:
            return
        from app.core import ai_usage, token_budget

        ai_usage.record_call(
            provider_id="local", model=self.model_id or self.model_path.name, kind="chat", ok=False,
            latency_ms=int((time.monotonic() - began) * 1000), estimated=True,
            prompt_tokens=token_budget.messages_tokens(messages), completion_tokens=token_budget.estimate_tokens(user_message or ""),
        )

    def chat_tools(
        self, system_prompt: str, history: list[ChatMessage], user_message: str, tools: list, tool_messages: list
    ) -> tool_protocol.ToolTurn:
        """مدل‌هایِ محلی همیشه با پروتکلِ متنی کار می‌کنن — بدونِ وابستگی به chat_formatِ
        خاصِ llama-cpp. ``stop`` جلوی حدس‌زدنِ نتیجه‌ی ابزار رو می‌گیره (پارسر تگِ
        بسته‌نشده رو هم می‌پذیره)."""
        self._ensure_loaded()
        trimmed = _trim_history(
            system_prompt, history, user_message, max_chars=self.n_ctx * 2 - _tool_messages_chars(tool_messages)
        )
        messages = tool_protocol.to_text_messages(system_prompt, trimmed, user_message, tool_messages, tools)
        began = time.monotonic()
        try:
            result = self._llm.create_chat_completion(
                messages=messages, temperature=0.3, max_tokens=700, stop=[tool_protocol.CLOSE_TAG, tool_protocol.RESULT_OPEN]
            )
        except Exception as exc:
            self._note_failure(messages, user_message, began)
            raise AiEngineError(f"اجرای مدل محلی شکست خورد: {exc}") from exc
        content = _strip_think(result["choices"][0]["message"].get("content") or "")
        self._note_usage(result, messages, content, began, "tools")
        return tool_protocol.parse_text_turn(content)

    def unload(self) -> None:
        """حافظه‌ی مدل را آزاد می‌کنه (برنامه روی لپ‌تاپِ ۴ گیگ اجرا می‌شه؛ نگه‌داشتنِ مدل
        وقتی ربات خاموشه بی‌رحمانه‌ست)."""
        llm, self._llm = self._llm, None
        if llm is not None:
            try:
                llm.close()
            except Exception:  # noqa: BLE001
                llm = None
            del llm

    # --------------------------------------------- آزمایش (برایِ UI و عیب‌یاب)

    def self_test(self) -> tuple:
        """(ok, پیام) — یک پرسشِ ثابتِ فارسی؛ نشان می‌ده مدل واقعاً لود و پاسخ می‌ده."""
        try:
            answer = self.chat(
                "تو یک دستیار فارسی‌زبانی. فقط جوابِ کوتاهِ خواسته‌شده را بنویس.",
                [],
                "فقط این عبارت را تکرار کن: آماده‌ام",
            )
        except AiEngineError as exc:
            return False, str(exc)
        if not answer:
            return False, "مدل پاس نداد؛ ممکنه رمِ سیستم کافی نباشه."
        return True, f"✅ مدل پاسخ داد: {answer[:80]}"


def engine_readiness(settings) -> tuple:
    """(آماده است؟, کلیدِ i18nِ علت) — دروازه‌ی یکسان برایِ صفحه‌ی خانه، راهنمای شروع و عیب‌یاب."""
    from app.core import model_catalog

    if settings is None:
        return False, "ai.ready.none"
    explicit = (getattr(settings, "model_file_path", "") or "").strip()
    path = resolve_model_path(settings)
    if path is None:
        if explicit:
            # مالک مسیری داده ولی فایلِ معتبرِ GGUF نیست؛ «مدلی انتخاب نشده» گفتنِ این را گمراه‌کننده می‌کند.
            return False, "ai.ready.path_invalid"
        return False, "ai.ready.no_model_selected"
    if not path.is_file():
        return False, "ai.ready.not_downloaded"
    if not _llama_available():
        return False, "ai.ready.llama_missing"
    # اگر مسیرِ فایلِ صریحِ کاربر معتبر باشد، آن مسیر بر انتخابِ مدلِ قدیمی/غیرفعال برتری دارد.
    # فقط در حالتِ انتخابِ خودکار از کاتالوگ است که اعتبارِ سایز/فایلِ مدل باید به‌صورتِ دقیق بررسی شود.
    if explicit:
        return True, "ai.ready.ok"
    entry = model_catalog.get_entry(getattr(settings, "model_id", "") or "")
    if entry and not downloader_ok(path, entry):
        return False, "ai.ready.file_invalid"
    return True, "ai.ready.ok"


def downloader_ok(path: Path, entry) -> bool:
    from app.core import downloader

    return downloader.is_downloaded(path, entry.size_bytes)


def _llama_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("llama_cpp") is not None


_gpu_offload_cache: Optional[bool] = None


def gpu_offload_available(force: bool = False) -> bool:
    """آیا *همین* بیلدِ llama-cpp می‌تواند لایه روی GPU بگذارد؟ حدس نه، پرس‌وجو.

    بیلدِ رسمیِ برنامه (و بسته‌هایِ آماده) از شاخه‌ی CPU installed می‌شود، پس پاسخِ این تابع
    False است و «لایه‌هایِ GPU» هیچ اثری ندارد — دقیقاً همان ابهامی که کاربر باید پیش از
    تغییرِ عدد بداند. اگر llama_cpp نباشد یا تابع را نداشته باشد هم False برمی‌گردد."""
    global _gpu_offload_cache
    if _gpu_offload_cache is not None and not force:
        return _gpu_offload_cache
    supported = False
    try:
        import llama_cpp

        supported = bool(llama_cpp.llama_supports_gpu_offload())
    except Exception:  # noqa: BLE001 — نبودِ کتابخانه/سمبل = همان «CPU-only» بودن
        supported = False
    _gpu_offload_cache = supported
    return supported


def reset_gpu_offload_cache() -> None:
    """برایِ تست‌ها و بعدِ نصبِ دوباره‌ی موتور."""
    global _gpu_offload_cache
    _gpu_offload_cache = None


def resolve_model_path(settings) -> Optional[Path]:
    """مسیرِ فایلِ GGUFِ انتخاب‌شده.

    اولویت با فایلِ واردشده‌ی خودِ کاربر (`model_file_path`) است؛ بعدِ مدلِ کاتالوگ در
    پوشه‌ی مدل‌ها. هیچ مسیرِ دلخواهی بدونِ بررسی پذیرفته نمی‌شه: باید یک فایلِ GGUFِ معمولی
    (نه پوشه، نه پیوندِ سمبولیک) باشه و پسوندِ .gguf داشته باشه."""
    from app.core import model_catalog

    explicit = (getattr(settings, "model_file_path", "") or "").strip()
    if explicit:
        candidate = Path(expanded_user(explicit))
        if candidate.is_file() and not candidate.is_symlink() and candidate.suffix.lower() == ".gguf":
            return candidate
        return None
    entry = model_catalog.get_entry(getattr(settings, "model_id", "") or "")
    if entry is None:
        return None
    return Path(settings.get_model_storage_dir()) / entry.filename


def expanded_user(text: str) -> str:
    from pathlib import Path as _P

    return str(_P(text).expanduser())


def build_engine_from_settings(settings) -> LocalEngine:
    """موتور را از AppSettings می‌سازد (بارگذاریِ واقعی تنبل و در اولین تماس است)."""
    from app.core import hardware, model_catalog

    if not _llama_available():
        raise AiEngineError(
            "ماشیینِ اجرایِ مدل (llama-cpp-python) روی این سیستم نیست. اگر از فایلِ نصبی استفاده "
            "می‌کنی باید همین باشد؛ اگر از سورس اجرا می‌کنی: pip install -r requirements.txt"
        )
    path = resolve_model_path(settings)
    if path is None:
        raise AiEngineError("هیچ مدلِ هوش مصنوعی انتخاب یا دانلود نشده.")
    if not path.is_file():
        raise AiEngineError(f"فایلِ مدل پیدا نشد: {path.name}")

    hw = hardware.detect()
    entry = model_catalog.get_entry(getattr(settings, "model_id", "") or "")
    size_bytes = path.stat().st_size
    n_ctx = int(getattr(settings, "ai_context_tokens", 0) or 0)
    if n_ctx <= 0:
        if entry is not None:
            n_ctx = model_catalog.auto_context_tokens(hw, entry)
        else:
            n_ctx = 4096 if size_bytes < 3 * (1024**3) else 8192
    threads = int(getattr(settings, "ai_threads", 0) or 0) or model_catalog.auto_threads(hw)
    return LocalEngine(
        model_path=path,
        n_ctx=n_ctx,
        n_gpu_layers=int(getattr(settings, "ai_gpu_layers", 0) or 0),
        n_threads=threads,
        model_id=getattr(settings, "model_id", "") or path.name,
    )
