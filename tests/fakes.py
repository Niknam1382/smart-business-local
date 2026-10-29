"""شیءهای جعلی مشترک: تنظیمات ساده و موتور AI جعلی."""

import threading
import time
from pathlib import Path


class FakeSettings:
    """همون رابطی از AppSettings که پایپ‌لاین می‌خونه."""

    def __init__(self, tmp_dir: Path):
        self.ai_mode = "api"
        self.api_base_url = "https://example.com/v1"
        self.api_model_name = "gpt-4o-mini"
        self.model_tier = None
        self.system_prompt = "تو یک فروشنده‌ی مفید هستی."
        self.memory_history_limit = 20
        self.memory_expire_hours = 0
        self._tmp = tmp_dir

    def get_api_key(self):
        return "sk-test"

    def get_model_storage_dir(self):
        return self._tmp


class FakeEngine:
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
