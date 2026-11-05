"""
ایجنتِ پرسش‌وپاسخِ *فقط‌خواندنی* برای حالت‌های دکمه‌ای (R2): AI به سؤال‌های مشتری جواب می‌ده (کاتالوگ + سؤالات
متداول + پرامپتِ صاحب فروشگاه) و می‌تونه با ابزارِ ``suggest_products`` «کارتِ محصول با دکمه‌ی جزئیات» نشون بده.
AI هرگز سبد/سفارش/پرداخت رو تغییر نمی‌ده (نه افزودن، نه کم‌کردن، نه حذف) — مشتری فقط از دکمه‌ها استفاده می‌کنه.
"""

from __future__ import annotations

import json
import logging

from app.core import ai_engine, shop_texts
from app.core.agent_common import AgentReply
from app.core.tool_protocol import ToolSpec

logger = logging.getLogger(__name__)

MAX_STEPS = 3
MAX_SUGGEST = 4
MAX_PROMPT_PRODUCTS = 40
MAX_FAQ_IN_PROMPT = 20

SUGGEST_SPEC = ToolSpec(
    name="suggest_products",
    description=(
        "Show product cards (with a 'Details' button) to the customer. Use it when the customer asks about products "
        "or you recommend something. You cannot add or remove cart items or place orders; the customer uses the menu buttons."
    ),
    parameters={
        "type": "object",
        "properties": {"product_ids": {"type": "array", "items": {"type": "integer"}, "description": "ids from the catalog list"}},
        "required": ["product_ids"],
    },
)

# RULES/RULES_NO_SHOP در ۱.۰.۰ به «سیستمِ پرامپتِ مرکزی» (prompt_kit) منتقل شدن؛ همان‌جا
# گاردهایِ تغییرناپذیر یک‌جا نوشته می‌شن تا پرامپتِ پیش‌نمایش‌شده در UI دقیقاً همان چیزی باشد
# که مدل می‌گیرد.

def build_prompt(base_prompt: str, settings, products, orders, display_name: str, can_suggest: bool) -> str:
    """پرامپتِ سیستمِ این نوبت — از راهِ «سیستمِ پرامپتِ مرکزی» (``prompt_kit``).

    ``base_prompt`` متنِ صاحب فروشگاه است (همان ``settings.system_prompt``؛ اگر پایپ‌لاین
    چیز دیگری بدهد، جایش اینجا است). گاردریل‌هایِ تغییرناپذیر، کاتالوگِ فقط‌خواندنی،
    سؤالات متداول و نامِ اعتمادناپذیرِ مشتری را همان ماژول می‌چیند — پس چیزی که در صفحه‌ی
    «سیستم پرامپت» پیش‌نمایش می‌شود، دقیقاً همان چیزی است که مدل می‌گیرد.
    """
    from app.core import prompt_kit

    return prompt_kit.build_system_prompt(
        settings,
        store_mode=bool(can_suggest),
        product_store=products if can_suggest else None,
        order_store=orders if can_suggest else None,
        display_name=display_name,
        include_catalog=bool(can_suggest),
        owner_prompt=base_prompt or "",
    )


class QaAgent:
    def __init__(self, product_store, order_store, shop_flow=None):
        self._products = product_store
        self._orders = order_store
        self._flow = shop_flow

    async def respond(self, call_engine, settings, platform, chat_id, display_name, base_prompt, history, user_message, can_suggest=True) -> AgentReply:
        can_suggest = bool(can_suggest and self._flow is not None)
        system_prompt = build_prompt(base_prompt, settings, self._products, self._orders, display_name, can_suggest)
        specs = [SUGGEST_SPEC] if can_suggest else []
        tool_messages: list = []
        outbox: list = []
        final = ""
        try:
            for _ in range(MAX_STEPS):
                turn = await call_engine(system_prompt, history, user_message, specs, tool_messages)
                if not turn.tool_calls or not specs:
                    final = turn.text
                    break
                tool_messages.append(
                    {
                        "role": "assistant", "content": turn.text,
                        "tool_calls": [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in turn.tool_calls[:2]],
                    }
                )
                for call in turn.tool_calls[:2]:
                    result = self._suggest(call, platform, chat_id, outbox) if call.name == "suggest_products" else {"ok": False, "error": "unknown tool"}
                    tool_messages.append({"role": "tool", "tool_call_id": call.id, "name": call.name, "content": json.dumps(result, ensure_ascii=False)})
        except ai_engine.AiEngineError:
            if not outbox:
                raise
            logger.exception("خطای AI بعد از نمایشِ کارت‌ها؛ فقط کارت‌ها فرستاده می‌شن")
            return AgentReply("", outbox)
        text = (final or "").strip()
        if not text and not outbox:
            text = shop_texts.t("ai.fallback")
        return AgentReply(text, outbox)

    def _suggest(self, call, platform: str, chat_id: str, outbox: list) -> dict:
        raw = call.arguments.get("product_ids") if isinstance(call.arguments, dict) else None
        ids = []
        for item in raw if isinstance(raw, list) else []:
            if isinstance(item, (int, str)) and str(item).isdigit() and int(item) not in ids:
                ids.append(int(item))
        cards = self._flow.suggestion_cards(platform, chat_id, ids[:MAX_SUGGEST])
        outbox.extend(cards)
        return {"ok": True, "shown": len(cards), "note": "Cards were shown to the customer. Do not repeat all their details; add a short helpful comment."}
