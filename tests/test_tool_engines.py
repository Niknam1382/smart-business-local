"""لایه‌ی tool-calling موتورها: OpenAI بومی، فالبک به پروتکل متنی، پارسر متنی، و
پیام‌هایی که به مدل می‌رسن."""

from app.core import tool_protocol as tp
from app.core.ai_engine import ChatMessage

SPECS = [
    tp.ToolSpec(
        "search_products",
        "جست‌وجوی محصول",
        {"type": "object", "properties": {"query": {"type": "string"}}},
    )
]


# ------------------------------------------------------------------ پارسر متنی


def test_parse_text_turn_plain_answer_has_no_calls():
    turn = tp.parse_text_turn("سلام! چه کمکی از من برمیاد؟")
    assert turn.tool_calls == [] and turn.text == "سلام! چه کمکی از من برمیاد؟"


def test_parse_text_turn_single_call():
    turn = tp.parse_text_turn('<tool_call>{"name": "search_products", "arguments": {"query": "گوشی"}}</tool_call>')
    assert [(c.name, c.arguments) for c in turn.tool_calls] == [("search_products", {"query": "گوشی"})]
    assert turn.text == ""


def test_parse_text_turn_unclosed_tag_from_stop_token_is_accepted():
    turn = tp.parse_text_turn('باشه، می‌گردم\n<tool_call>{"name": "search_products", "arguments": {"query": "x"}}')
    assert len(turn.tool_calls) == 1 and turn.text == "باشه، می‌گردم"


def test_parse_text_turn_fenced_json_and_trailing_chatter():
    raw = '<tool_call>```json\n{"name": "get_my_orders", "arguments": {}} پایان\n```</tool_call>'
    turn = tp.parse_text_turn(raw)
    assert [c.name for c in turn.tool_calls] == ["get_my_orders"]


def test_parse_text_turn_multiple_calls_and_bad_json_skipped():
    raw = (
        '<tool_call>{"name": "a", "arguments": {"x": 1}}</tool_call>'
        "<tool_call>{not json}</tool_call>"
        '<tool_call>{"name": "b"}</tool_call>'
    )
    turn = tp.parse_text_turn(raw)
    assert [(c.name, c.arguments) for c in turn.tool_calls] == [("a", {"x": 1}), ("b", {})]
    assert len({c.id for c in turn.tool_calls}) == 2


def test_parse_text_turn_nested_braces_in_arguments():
    raw = '<tool_call>{"name": "create_order", "arguments": {"items": [{"product_id": 1, "quantity": 2}]}} متن</tool_call>'
    turn = tp.parse_text_turn(raw)
    assert turn.tool_calls[0].arguments == {"items": [{"product_id": 1, "quantity": 2}]}


def test_text_messages_render_tool_exchange_and_protocol_prompt():
    hist = [ChatMessage("user", "سلام"), ChatMessage("assistant", "سلام!")]
    tool_msgs = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "name": "search_products", "arguments": {"query": "گوشی"}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "search_products", "content": '{"products": []}'},
    ]
    msgs = tp.to_text_messages("SYS", hist, "گوشی دارید؟", tool_msgs, SPECS)
    assert msgs[0]["role"] == "system" and msgs[0]["content"].startswith("SYS") and "<tool_call>" in msgs[0]["content"]
    assert "search_products" in msgs[0]["content"]
    assert [m["role"] for m in msgs[1:]] == ["user", "assistant", "user", "assistant", "user"]
    assert msgs[-2]["content"].startswith("<tool_call>")
    assert msgs[-1]["content"] == '<tool_result name="search_products">{"products": []}</tool_result>'


def test_text_messages_without_tools_leave_system_prompt_untouched():
    assert tp.to_text_messages("SYS", [], "hi", [], [])[0]["content"] == "SYS"


def test_protocol_tags_come_from_one_place():
    """برچسب‌های پروتکل یک‌جا تعریف شدن؛ موتورِ اجرا همان‌ها را به عنوان stop می‌دهد."""
    assert tp.OPEN_TAG == "<" + "tool_call" + ">"
    assert tp.CLOSE_TAG == "<" + "/" + "tool_call" + ">"
    assert tp.RESULT_OPEN.startswith("<" + "tool_result")
    assert tp.CLOSE_TAG in str(tp._CALL_RE.pattern) or "tool_call" in str(tp._CALL_RE.pattern)


def test_text_protocol_prompt_states_the_no_mutation_rule():
    """راهنمایِ ابزار در پرامپت باید صریح بگوید ابزارِ تغییرِ سبد/سفارش/پرداخت وجود ندارد."""
    prompt = tp.build_text_protocol_prompt(SPECS)
    assert "تغییرِ سبد" in prompt and "دکمه‌ها" in prompt
    assert "search_products" in prompt
