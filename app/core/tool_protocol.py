"""
قراردادِ مشترکِ «فراخوانیِ ابزار» (tool calling) برای موتورهای AI.

ادمینِ هوشمندِ فروشگاه (store_agent.py) با ابزار کار می‌کنه، نه با متنِ آزاد؛
این ماژول ساختارها و دو «زبان» رو تعریف می‌کنه:

1. **بومیِ OpenAI** (``tools`` / ``tool_calls`` / نقشِ ``tool``): برای ApiEngine —
   مطمئن‌ترین حالت وقتی سرویس پشتیبانی کنه.
2. **پروتکل متنی** (``<tool_call>{...}</tool_call>``): برای مدل‌های محلی
   (llama-cpp) و سرویس‌های سازگاری که ``tools`` رو نمی‌فهمن. هر مدلِ
   instruct کم‌وبیش از پسش برمیاد (فرمتش همونیه که Qwen/Hermes بلدن).

پیام‌های حلقه‌ی ایجنت، مستقل از ارائه‌دهنده، این شکل رو دارن:

    {"role": "assistant", "content": str, "tool_calls": [{"id","name","arguments"}]}
    {"role": "tool", "tool_call_id": str, "name": str, "content": str(JSON)}
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional


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


# ------------------------------------------------------------------ بومیِ OpenAI


def to_openai_tools(specs: list) -> list:
    return [
        {"type": "function", "function": {"name": s.name, "description": s.description, "parameters": s.parameters}}
        for s in specs
    ]


def to_openai_messages(system_prompt: str, history: list, user_message: str, tool_messages: list) -> list:
    messages = [{"role": "system", "content": system_prompt}]
    messages += [{"role": m.role, "content": m.content} for m in history]
    messages.append({"role": "user", "content": user_message})
    for m in tool_messages:
        if m["role"] == "assistant":
            out = {"role": "assistant", "content": m.get("content") or None}
            if m.get("tool_calls"):
                out["tool_calls"] = [
                    {
                        "id": c["id"],
                        "type": "function",
                        "function": {"name": c["name"], "arguments": json.dumps(c["arguments"], ensure_ascii=False)},
                    }
                    for c in m["tool_calls"]
                ]
            messages.append(out)
        else:
            messages.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
    return messages


def parse_openai_message(message: dict) -> ToolTurn:
    calls = []
    for raw in message.get("tool_calls") or []:
        fn = raw.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except (json.JSONDecodeError, TypeError):
            args = {}
        if not isinstance(args, dict):
            args = {}
        calls.append(ToolCall(id=str(raw.get("id") or f"call_{len(calls)}"), name=str(fn.get("name", "")), arguments=args))
    return ToolTurn(text=(message.get("content") or "").strip(), tool_calls=calls)


# ------------------------------------------------------------------ پروتکل متنی

_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*(?:</tool_call>|$)", re.DOTALL)
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def build_text_protocol_prompt(specs: list) -> str:
    lines = [
        "## ابزارها (TOOLS)",
        "برای انجام هر کاری (دیدن محصول/موجودی، ثبت سفارش، پرداخت، ...) باید از ابزار استفاده کنی.",
        "برای صدازدن یک ابزار، *فقط و فقط* این قالب رو بنویس و بعدش هیچ متنِ دیگه‌ای ننویس:",
        '<tool_call>{"name": "نام_ابزار", "arguments": {"پارامتر": "مقدار"}}</tool_call>',
        "نتیجه‌ی ابزار توی پیام بعدی با قالب <tool_result>...</tool_result> بهت داده می‌شه؛ بعدش یا ابزار دیگه‌ای",
        "صدا بزن یا جوابِ نهایی رو به مشتری بنویس (جواب نهایی هیچ <tool_call>ی نداره).",
        "نتیجه‌ی ابزار رو هیچ‌وقت خودت حدس نزن یا ننویس.",
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
