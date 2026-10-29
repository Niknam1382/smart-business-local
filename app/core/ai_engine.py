"""
موتور یکپارچه‌ی هوش مصنوعی — یک رابط مشترک (متد chat) برای هر دو حالت
(محلی/API) که بقیه‌ی برنامه، و بعداً ربات تلگرام/بله در فاز ۳، بدون دونستن
اینکه پشت صحنه کدوم حالته، ازش استفاده می‌کنن.

- ApiEngine: کلاینت HTTP ساده (فقط urllib، بدون وابستگی جانبی) برای هر
  سرویس سازگار با OpenAI Chat Completions API.
- LocalEngine: کلاس Llama از llama-cpp-python رو لود و اجرا می‌کنه. ایمپورت
  llama_cpp عمداً «تنبل» (داخل متد، نه بالای فایل) انجام می‌شه تا بقیه‌ی
  برنامه بدون نیاز به نصب این کتابخونه‌ی سنگین هم کار کنه و تست بشه.

کشِ پاسخ دیگه داخلِ موتورها نیست: کشِ قبلی (فقط روی پرامپتِ سیستم + پیامِ کاربر، بدونِ تاریخچه) ممکن بود پاسخِ مشتریِ
دیگه/نوبتِ دیگه را برگردونه. جایگزینش ``ai_cache.py`` است (کلید = هشِ کلِ payload، پیش‌فرض خاموش).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core import tool_protocol


class AiEngineError(Exception):
    """خطای قابل‌نمایش به کاربر (فارسی) برای هر مشکلی در تماس با AI."""


@dataclass
class ChatMessage:
    role: str  # "user" یا "assistant"
    content: str


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
    """حجمِ تبادل‌های ابزارِ همین نوبت (نتیجه‌ی جست‌وجو و ...) — از بودجه‌ی تاریخچه کم
    می‌شه تا پرامپتِ نهایی از پنجره‌ی زمینه‌ی مدل بیرون نزنه."""
    total = 0
    for m in tool_messages:
        total += len(m.get("content") or "")
        for call in m.get("tool_calls") or []:
            total += len(call["name"]) + len(json.dumps(call["arguments"], ensure_ascii=False)) + 40
    return total


class ApiEngine:
    # چند مکالمه می‌تونن هم‌زمان از یه ApiEngine استفاده کنن (هر تماس یه
    # درخواست HTTP مستقله). پایپ‌لاین ربات از این پرچم برای تصمیم‌گیری درباره‌ی
    # سریالی‌کردن تماس‌ها استفاده می‌کنه.
    concurrent_safe = True

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = "gpt-4o-mini",
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def chat(self, system_prompt: str, history: list[ChatMessage], user_message: str) -> str:
        trimmed = _trim_history(system_prompt, history, user_message, max_chars=8000)
        messages = [{"role": "system", "content": system_prompt}]
        messages += [{"role": m.role, "content": m.content} for m in trimmed]
        messages.append({"role": "user", "content": user_message})

        payload = json.dumps(
            {"model": self.model, "messages": messages, "temperature": 0.4}
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise AiEngineError(f"سرور خطای HTTP {exc.code} برگردوند: {body[:300]}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AiEngineError(f"اتصال به API ناموفق بود: {exc}") from exc

        try:
            answer = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AiEngineError(f"پاسخ سرور فرمت غیرمنتظره‌ای داشت: {data}") from exc

        return answer

    # ---- ابزارمحور (ایجنتِ فروشگاه) ----
    _native_tools = True  # اگه سرویس ``tools`` رو نفهمید، خودکار به پروتکل متنی برمی‌گردیم

    def _post_chat(self, payload: dict) -> dict:
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            error = AiEngineError(f"سرور خطای HTTP {exc.code} برگردوند: {body[:300]}")
            error.http_status = exc.code  # type: ignore[attr-defined]
            error.body = body  # type: ignore[attr-defined]
            raise error from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AiEngineError(f"اتصال به API ناموفق بود: {exc}") from exc

    def chat_tools(
        self, system_prompt: str, history: list[ChatMessage], user_message: str, tools: list, tool_messages: list
    ) -> tool_protocol.ToolTurn:
        """یک نوبتِ ابزارمحور. اول tool-callingِ بومیِ OpenAI؛ اگه سرویس ردش کرد
        (HTTP 400/422 با اشاره به tools/function) برای همیشه به پروتکل متنی
        برمی‌گردیم. کش نداره: نتیجه به وضعیتِ لحظه‌ایِ موجودی/سفارش وابسته‌ست."""
        # پرامپتِ ایجنتِ فروشگاه (قوانین + کاتالوگ) بلنده؛ مدل‌های API زمینه‌ی بزرگ دارن
        trimmed = _trim_history(
            system_prompt, history, user_message, max_chars=24000 - _tool_messages_chars(tool_messages)
        )
        if self._native_tools and tools:
            payload = {
                "model": self.model,
                "messages": tool_protocol.to_openai_messages(system_prompt, trimmed, user_message, tool_messages),
                "tools": tool_protocol.to_openai_tools(tools),
                "tool_choice": "auto",
                "temperature": 0.3,
            }
            try:
                data = self._post_chat(payload)
                return tool_protocol.parse_openai_message(self._first_message(data))
            except AiEngineError as exc:
                status = getattr(exc, "http_status", 0)
                body = (getattr(exc, "body", "") or "").lower()
                if status in (400, 404, 422) and ("tool" in body or "function" in body):
                    self._native_tools = False  # از این به بعد متنی
                else:
                    raise
        messages = tool_protocol.to_text_messages(system_prompt, trimmed, user_message, tool_messages, tools)
        data = self._post_chat({"model": self.model, "messages": messages, "temperature": 0.3})
        return tool_protocol.parse_text_turn(self._first_message(data).get("content") or "")

    @staticmethod
    def _first_message(data: dict) -> dict:
        try:
            return data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AiEngineError(f"پاسخ سرور فرمت غیرمنتظره‌ای داشت: {data}") from exc


class LocalEngine:
    # یه نمونه‌ی Llama نباید هم‌زمان از چند ترد صدا زده بشه (حالت داخلیش خراب
    # می‌شه) — پایپ‌لاین ربات تماس‌های محلی رو پشت یه قفل سریالی می‌کنه.
    concurrent_safe = False

    def __init__(
        self,
        model_path: Path,
        n_ctx: int = 4096,
        n_gpu_layers: int = -1,  # روی build فقط-CPU بی‌اثره؛ اگه بعداً GPU اضافه بشه خودکار فعال می‌شه
        n_threads: Optional[int] = None,
    ):
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers
        self.n_threads = n_threads
        self._llm = None
        self.record_usage = True  # داخلِ FailoverEngine خاموش می‌شه (خودش ثبت می‌کنه)
        self.last_usage: dict = {}

    def _ensure_loaded(self) -> None:
        if self._llm is not None:
            return
        if not self.model_path.exists():
            raise AiEngineError(f"فایل مدل پیدا نشد: {self.model_path}")
        try:
            from llama_cpp import Llama  # ایمپورت تنبل — عمداً همین‌جا، نه بالای فایل
        except ImportError as exc:
            raise AiEngineError("کتابخونه‌ی llama-cpp-python نصب نیست.") from exc

        kwargs = dict(
            model_path=str(self.model_path),
            n_ctx=self.n_ctx,
            n_gpu_layers=self.n_gpu_layers,
            verbose=False,
        )
        if self.n_threads:
            kwargs["n_threads"] = self.n_threads
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
            result = self._llm.create_chat_completion(
                messages=messages, temperature=0.4, max_tokens=512
            )
        except Exception as exc:
            raise AiEngineError(f"اجرای مدل محلی شکست خورد: {exc}") from exc

        answer = result["choices"][0]["message"]["content"]
        self._note_usage(result, messages, answer, began, "chat")
        return answer

    def _note_usage(self, result, messages: list, answer: str, began: float, kind: str) -> None:
        usage = result.get("usage") if isinstance(result, dict) else None
        self.last_usage = dict(usage) if isinstance(usage, dict) and "prompt_tokens" in usage else {}
        if not self.record_usage:
            return
        from app.core import ai_usage, token_budget

        est = not self.last_usage
        ai_usage.record_call(
            provider_id="local", model=self.model_path.name, kind=kind, latency_ms=int((time.monotonic() - began) * 1000), estimated=est,
            prompt_tokens=self.last_usage.get("prompt_tokens") or token_budget.messages_tokens(messages),
            completion_tokens=self.last_usage.get("completion_tokens") or token_budget.estimate_tokens(answer or ""),
        )

    def chat_tools(
        self, system_prompt: str, history: list[ChatMessage], user_message: str, tools: list, tool_messages: list
    ) -> tool_protocol.ToolTurn:
        """مدل‌های محلی همیشه با پروتکل متنی (<tool_call>) کار می‌کنن — بدون وابستگی
        به chat_formatِ خاصِ llama-cpp. ``stop`` جلوی حدس‌زدنِ نتیجه‌ی ابزار رو می‌گیره
        (پارسر تگِ بسته‌نشده رو هم می‌پذیره)."""
        self._ensure_loaded()
        trimmed = _trim_history(
            system_prompt, history, user_message, max_chars=self.n_ctx * 2 - _tool_messages_chars(tool_messages)
        )
        messages = tool_protocol.to_text_messages(system_prompt, trimmed, user_message, tool_messages, tools)
        began = time.monotonic()
        try:
            result = self._llm.create_chat_completion(
                messages=messages, temperature=0.3, max_tokens=700, stop=["</tool_call>", "<tool_result"]
            )
        except Exception as exc:
            raise AiEngineError(f"اجرای مدل محلی شکست خورد: {exc}") from exc
        content = result["choices"][0]["message"].get("content") or ""
        self._note_usage(result, messages, content, began, "tools")
        return tool_protocol.parse_text_turn(content)

    def unload(self) -> None:
        self._llm = None


def build_engine_from_settings(settings):
    """با توجه به AppSettings کاربر، موتور مناسب رو می‌سازه. جدا از UI تا
    فاز ۳ (ربات تلگرام/بله) هم بتونه دقیقاً همین تابع رو صدا بزنه."""
    from app.core import model_catalog

    if settings.ai_mode == "api":
        from app.core import ai_providers

        return ai_providers.FailoverEngine(settings, local_factory=lambda: _local_engine(settings), budget=_budget(settings), persist=_persist_callback(settings))

    tier = model_catalog.get_tier(settings.model_tier or "medium")
    if tier is None:
        raise AiEngineError("سایز مدل تنظیم‌نشده یا نامعتبره.")
    # حالت فروشگاه: پرامپتِ ایجنت (قوانین + کاتالوگ + شِمای ابزارها) حدود ۴ هزار توکنِ
    # فارسیه؛ با پنجره‌ی ۴۰۹۶ جا نمی‌شه، پس ۸۱۹۲ (حافظه‌ی بیشتر، ولی کارکرد درست)
    n_ctx = 8192 if getattr(settings, "business_mode", "") == "store" else 4096
    return LocalEngine(model_path=settings.get_model_storage_dir() / tier.filename, n_ctx=n_ctx)


def _local_engine(settings):
    from app.core import model_catalog

    tier = model_catalog.get_tier(settings.model_tier or "medium")
    if tier is None:
        raise AiEngineError("سایز مدل تنظیم‌نشده یا نامعتبره.")
    n_ctx = 8192 if getattr(settings, "business_mode", "") == "store" else 4096
    return LocalEngine(model_path=settings.get_model_storage_dir() / tier.filename, n_ctx=n_ctx)


def _budget(settings):
    """بودجه‌ی ماهانه (N1) — فقط وقتی ثبتِ مصرف فعال است."""
    from app.core import ai_usage

    return ai_usage.Budget(ai_usage.RECORDER, lambda: settings) if ai_usage.RECORDER is not None else None


def _persist_callback(settings):
    def persist() -> None:
        from app.core import settings as settings_module

        settings_module.save_settings(settings)

    return persist
