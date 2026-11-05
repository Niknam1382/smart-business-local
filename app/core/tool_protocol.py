"""
قراردادِ «فراخوانیِ ابزار» برای مدلِ محلی.

از نسخه‌ی ۱.۰.۰ فقط یک زبان هست: **پروتکلِ متنی** (همان شکلی که Qwen/Hermes بلدند) — چون هیچ API
بیرونی‌ای در برنامه نیست و مدل، llama.cpp است. ابزارهای امروز *فقط‌خواندنی*اند (پیشنهادِ
محصول)؛ هیچ ابزاری سبد/سفارش/پرداخت را تغییر نمی‌دهد (ناوردا ۱).

پیام‌های حلقه‌ی ایجنت این شکل را دارند:

    {"role": "assistant", "content": str, "tool_calls": [{"id","name","arguments"}]}
    {"role": "tool", "tool_call_id": str, "name": str, "content": str(JSON)}
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

# برچسب‌های پروتکل یک‌جا تعریف می‌شن تا موتورِ اجرا (stop sequences) و پارسر همان‌ها را بزنند
OPEN_TAG = "<" + "tool_call" + ">"
CLOSE_TAG = "<" + "/" + "tool_call" + ">"
RESULT_OPEN = "<" + "tool_result"
RESULT_CLOSE = "<" + "/" + "tool_result" + ">"


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON Schema


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ToolTurn:
    """یک نوبتِ مدل: یا متنِ نهایی (بدون tool_calls)، یا درخواستِ اجرای ابزار."""

    text: str = ""
    tool_calls: list = field(default_factory=list)  # list[ToolCall]


# ------------------------------------------------------------------ پروتکل متنی

_CALL_RE = re.compile(re.escape(OPEN_TAG) + r"\s*(.*?)\s*(?:" + re.escape(CLOSE_TAG) + r"|$)", re.DOTALL)
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def build_text_protocol_prompt(specs: list) -> str:
    lines = [
        "## ابزارها (TOOLS)",
        "اگر لازم شد قیمت/موجودیِ تازه ببینی، از ابزار استفاده کن.",
        "برای صدازدن یک ابزار، *فقط و فقط* این قالب رو بنویس و بعدش هیچ متنِ دیگه‌ای ننویس:",
        OPEN_TAG + '{"name": "نام_ابزار", "arguments": {"پارامتر": "مقدار"}}' + CLOSE_TAG,
        "نتیجه‌ی ابزار توی پیام بعدی با قالب " + RESULT_OPEN + ">...</" + "tool_result> بهت داده می‌شه؛ بعدش یا ابزار دیگه‌ای",
        "صدا بزن یا جوابِ نهایی رو به مشتری بنویس (جوابِ نهایی هیچ " + OPEN_TAG + "ی نداره).",
        "نتیجه‌ی ابزار رو هیچ‌وقت خودت حدس نزن یا ننویس.",
        "هیچ ابزاری برای تغییرِ سبد، ثبتِ سفارش یا پرداخت وجود نداره؛ این‌ها فقط با دکمه‌ها انجام می‌شن.",
        "",
        "ابزارهای موجود:",
]
    for s in specs:
        lines.append(f"- {s.name}: {s.description}")
        lines.append(f"  پارامترها (JSON Schema): {json.dumps(s.parameters, ensure_ascii=False)}")
    return "\n".join(lines)


def to_text_messages(system_prompt: str, history: list, user_message: str, tool_messages: list, specs: list) -> list:
    system = system_prompt + "\n\n" + build_text_protocol_prompt(specs) if specs else system_prompt
    messages = [{"role": "system", "content": system}]
    messages += [{"role": m.role, "content": m.content} for m in history]
    messages.append({"role": "user", "content": user_message})
    for m in tool_messages:
        if m["role"] == "assistant":
            parts = []
            if m.get("content"):
                parts.append(m["content"])
            for c in m.get("tool_calls") or []:
                parts.append("<tool_call>" + json.dumps({"name": c["name"], "arguments": c["arguments"]}, ensure_ascii=False) + "</tool_call>")
            messages.append({"role": "assistant", "content": "\n".join(parts)})
        else:
            messages.append({"role": "user", "content": f"<tool_result name=\"{m['name']}\">{m['content']}</tool_result>"})
    return messages


def _loads_lenient(raw: str) -> Optional[dict]:
    raw = _FENCE_RE.sub("", raw.strip()).strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    # اولین شیء JSONِ متعادل رو بردار (مدل‌ها گاهی بعدش متن اضافه می‌نویسن)
    start = raw.find("{")
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(raw[start : i + 1])
                    return data if isinstance(data, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def parse_text_turn(text: str) -> ToolTurn:
    """متنِ خامِ مدل رو به ToolTurn تبدیل می‌کنه: بلوک‌های <tool_call> (حتی بدون
    تگِ بسته‌کننده) ابزار حساب می‌شن و بقیه‌ی متن، جوابِ مشتریه."""
    text = text or ""
    calls = []
    for i, match in enumerate(_CALL_RE.finditer(text)):
        data = _loads_lenient(match.group(1))
        if not data or not isinstance(data.get("name"), str):
            continue
        args = data.get("arguments", data.get("parameters", {}))
        calls.append(ToolCall(id=f"text_{i}", name=data["name"], arguments=args if isinstance(args, dict) else {}))
    clean = _CALL_RE.sub("", text).strip()
    return ToolTurn(text=clean, tool_calls=calls)
