"""شیءهای جعلی مشترک: تنظیمِ ساده و موتورِ AIِ محلیِ جعلی (بدونِ شبکه، بدونِ llama)."""

import threading
import time
from pathlib import Path


class FakeSettings:
    """همون رابطی از AppSettings که پایپ‌لاین می‌خونه (نسخه‌ی ۱.۰.۰: فقط مدلِ محلی)."""

    def __init__(self, tmp_dir: Path):
        self.model_id = "qwen35-4b"  # شناسهٔ مدلِ کاتالوگ
        self.model_file_path = ""  # خالی = از پوشهٔ مدل‌ها
        self.model_storage_path = str(tmp_dir)
        self.ai_threads = 0
        self.ai_context_tokens = 0
        self.ai_gpu_layers = 0
        self.system_prompt = "تو یک فروشنده‌ی مفید هستی."
        self.memory_history_limit = 20
        self.memory_expire_hours = 0
        self._tmp = tmp_dir

    def get_model_storage_dir(self):
        return self._tmp


class FakeEngine:
    """جای ``LocalEngine``: پاسخِ ثابت، بدونِ مدل. مثلِ موتورِ محلی «هم‌زمان‌امن» نیست مگر بخواهیم."""

    def __init__(self, delay: float = 0.0, concurrent_safe: bool = True, reply=None):
        self.delay = delay
        self.concurrent_safe = concurrent_safe
        self.calls = []  # (system_prompt, history, user_message)
        self.unloaded = False
        self._reply = reply
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def chat(self, system_prompt, history, user_message):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.calls.append((system_prompt, list(history), user_message))
        try:
            if self.delay:
                time.sleep(self.delay)
            if callable(self._reply):
                return self._reply(user_message)
            return f"پاسخ: {user_message}"
        finally:
            with self._lock:
                self.active -= 1

    def unload(self):
        self.unloaded = True


# --------------------------------------------------- موتور ابزارمحورِ سناریویی ---

import json  # noqa: E402

from app.core.tool_protocol import ToolCall, ToolTurn  # noqa: E402


def tool(name, **arguments):
    """یه نوبتِ مدل: «این ابزار رو با این پارامترها صدا بزن»."""
    return ToolTurn(text="", tool_calls=[ToolCall(id=f"call_{name}", name=name, arguments=arguments)])


def say(text):
    """یه نوبتِ مدل: جوابِ نهاییِ متنی به مشتری."""
    return ToolTurn(text=text, tool_calls=[])


class ScriptedToolEngine:
    """جای مدلِ زبانیِ واقعی: برای هر «پیام کاربر» یه لیست قدم می‌دیم. هر قدم یا یه
    ToolTurn ثابته یا تابعی از نتیجه‌ی ابزارهای قبلیِ همین پیام (لیست دیکشنری). قدمِ
    n-ام وقتی اجرا می‌شه که n نتیجه‌ی ابزار تا حالا برگشته باشه."""

    concurrent_safe = True

    def __init__(self, scripts: dict, default=None):
        self.scripts = scripts
        self.default = default
        self.calls = []  # هر تماس: {system_prompt, history, user_message, tools, tool_messages}
        self._lock = threading.Lock()

    def chat(self, system_prompt, history, user_message):  # برای حالت‌های غیرفروشگاهی
        return f"پاسخ: {user_message}"

    def chat_tools(self, system_prompt, history, user_message, tools, tool_messages):
        with self._lock:
            self.calls.append(
                dict(
                    system_prompt=system_prompt,
                    history=list(history),
                    user_message=user_message,
                    tools=[t.name for t in tools],
                    tool_messages=list(tool_messages),
                )
            )
        steps = self.scripts.get(user_message)
        if steps is None:
            if self.default is not None:
                return self.default
            raise AssertionError(f"سناریویی برای پیام {user_message!r} تعریف نشده")
        results = [json.loads(m["content"]) for m in tool_messages if m["role"] == "tool"]
        index = len(results)
        if index >= len(steps):
            raise AssertionError(f"قدمِ {index} برای {user_message!r} تعریف نشده (نتایج: {results})")
        step = steps[index]
        return step(results) if callable(step) else step

    def unload(self):
        pass


# ------------------------------------------------- llama_cppِ جعلی (برای LocalEngine) ---

import sys  # noqa: E402
import types  # noqa: E402


class FakeLlama:
    """جایِ کتابخونه‌ی سنگینِ llama.cpp: هر تماس یه پاسخِ از‌پیش‌تعریف‌شده می‌دهد.

    با ``install(monkeypatch)`` داخل ``sys.modules`` می‌نشیند، پس ``LocalEngine`` بدونِ مدلِ واقعی
    و بدونِ شبکه تست می‌شه. هیچ‌وقت نباید در تست‌ها ``llama_cpp`` واقعی import بشه."""

    def __init__(self, responses=(), usage=None, error=None, finish_reasons=()):
        self.responses = list(responses)
        self.usage = dict(usage) if usage is not None else {"prompt_tokens": 11, "completion_tokens": 7}
        self.error = error  # اگر بدهیم، create_chat_completion این استثنا را می‌دهد
        self.finish_reasons = list(finish_reasons)  # مثلاً ("length", "stop") برایِ تستِ «پاسخ نصفه ماند»
        self.instances: list = []
        outer = self

        class Llama:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.requests: list = []
                self.closed = False
                outer.instances.append(self)

            def create_chat_completion(self, messages, **options):
                if outer.error is not None:
                    raise outer.error
                self.requests.append(dict(messages=messages, **options))
                index = len(self.requests) - 1
                text = outer.responses.pop(0) if outer.responses else ""
                reason = outer.finish_reasons[index] if index < len(outer.finish_reasons) else "stop"
                return {"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": reason}], "usage": dict(outer.usage)}

            def close(self):
                self.closed = True

        self._llama_cls = Llama

    @property
    def requests(self) -> list:
        return [r for inst in self.instances for r in inst.requests]

    def install(self, monkeypatch):
        module = types.ModuleType("llama_cpp")
        module.Llama = self._llama_cls
        # find_spec() روی ماژولِ تزریق‌شده به __spec__ نیاز دارد (بدونِ آن ValueError می‌دهد)
        module.__spec__ = types.SimpleNamespace(name="llama_cpp", loader=None, submodule_search_locations=None)
        monkeypatch.setitem(sys.modules, "llama_cpp", module)
        return module
