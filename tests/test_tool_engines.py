"""لایه‌ی tool-calling موتورها: OpenAI بومی، فالبک به پروتکل متنی، پارسر متنی، و
پیام‌هایی که به مدل می‌رسن."""

import pytest
from fake_openai import FakeOpenAIServer, message_reply, native_call

from app.core import tool_protocol as tp
from app.core.ai_engine import AiEngineError, ApiEngine, ChatMessage

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


# ------------------------------------------------------------------ ApiEngine


def make_engine(server):
    return ApiEngine(server.base_url, "sk-test", "gpt-test", timeout=10)


def test_native_tool_call_roundtrip():
    server = FakeOpenAIServer(lambda p: message_reply(None, [native_call("search_products", {"query": "گوشی"}, "abc")])).start()
    try:
        turn = make_engine(server).chat_tools("SYS", [], "گوشی دارید؟", SPECS, [])
    finally:
        server.stop()
    assert [(c.id, c.name, c.arguments) for c in turn.tool_calls] == [("abc", "search_products", {"query": "گوشی"})]
    sent = server.requests[0]
    assert sent["auth"] == "Bearer sk-test" and sent["path"].endswith("/chat/completions")
    assert sent["payload"]["tools"][0]["function"]["name"] == "search_products"
    assert sent["payload"]["tool_choice"] == "auto"


def test_native_final_answer_and_tool_result_messages_follow_openai_shape():
    server = FakeOpenAIServer(lambda p: message_reply("سه مدل داریم")).start()
    tool_msgs = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "abc", "name": "search_products", "arguments": {"query": "x"}}]},
        {"role": "tool", "tool_call_id": "abc", "name": "search_products", "content": '{"ok": true}'},
    ]
    try:
        turn = make_engine(server).chat_tools("SYS", [], "q", SPECS, tool_msgs)
    finally:
        server.stop()
    assert turn.text == "سه مدل داریم" and turn.tool_calls == []
    msgs = server.requests[0]["payload"]["messages"]
    assert msgs[-2]["role"] == "assistant" and msgs[-2]["tool_calls"][0]["function"]["arguments"] == '{"query": "x"}'
    assert msgs[-1] == {"role": "tool", "tool_call_id": "abc", "content": '{"ok": true}'}


def test_malformed_native_arguments_become_empty_dict():
    bad = {"id": "z", "type": "function", "function": {"name": "search_products", "arguments": "{oops"}}
    server = FakeOpenAIServer(lambda p: message_reply(None, [bad])).start()
    try:
        turn = make_engine(server).chat_tools("SYS", [], "q", SPECS, [])
    finally:
        server.stop()
    assert turn.tool_calls[0].arguments == {}


def test_falls_back_to_text_protocol_when_service_rejects_tools_and_remembers():
    def handler(payload):
        if "tools" in payload:
            return 400, {"error": {"message": "Unrecognized request argument supplied: tools"}}
        return message_reply('<tool_call>{"name": "search_products", "arguments": {"query": "هدفون"}}</tool_call>')

    server = FakeOpenAIServer(handler).start()
    try:
        engine = make_engine(server)
        turn = engine.chat_tools("SYS", [], "هدفون دارید؟", SPECS, [])
        assert [(c.name, c.arguments) for c in turn.tool_calls] == [("search_products", {"query": "هدفون"})]
        assert engine._native_tools is False
        n_before = len(server.requests)
        engine.chat_tools("SYS", [], "یه سوال دیگه", SPECS, [])
        assert len(server.requests) == n_before + 1, "بعد از فالبک دیگه تلاش بومیِ بی‌فایده نمی‌کنه"
    finally:
        server.stop()
    assert "tools" not in server.requests[-1]["payload"]
    assert "<tool_call>" in server.requests[-1]["payload"]["messages"][0]["content"]


def test_unrelated_http_error_is_not_swallowed():
    server = FakeOpenAIServer(lambda p: (401, {"error": {"message": "invalid api key"}})).start()
    try:
        with pytest.raises(AiEngineError, match="401"):
            make_engine(server).chat_tools("SYS", [], "q", SPECS, [])
    finally:
        server.stop()


def test_no_tools_means_plain_chat_without_tool_fields():
    server = FakeOpenAIServer(lambda p: message_reply("جواب نهایی")).start()
    try:
        turn = make_engine(server).chat_tools("SYS", [], "q", [], [])
    finally:
        server.stop()
    assert turn.text == "جواب نهایی"
    assert "tools" not in server.requests[0]["payload"]


# ------------------------------------------------------------------ بودجه‌ی زمینه


def test_tool_exchange_size_is_deducted_from_history_budget():
    from app.core.ai_engine import _tool_messages_chars

    big = {"role": "tool", "tool_call_id": "c", "name": "search_products", "content": "x" * 5000}
    call = {"role": "assistant", "content": "", "tool_calls": [{"id": "c", "name": "search_products", "arguments": {"query": "گوشی"}}]}
    assert _tool_messages_chars([]) == 0
    assert _tool_messages_chars([call, big]) > 5000


def test_api_engine_keeps_more_history_in_tool_mode_than_plain_chat():
    server = FakeOpenAIServer(lambda p: message_reply("ok")).start()
    try:
        history = [ChatMessage("user" if i % 2 == 0 else "assistant", f"پیام {i} " + "ا" * 400) for i in range(40)]
        make_engine(server).chat_tools("S" * 5000, history, "سوال", SPECS, [])
        sent = server.requests[0]["payload"]["messages"]
    finally:
        server.stop()
    kept = len(sent) - 2  # system + user
    assert kept > 20, "پرامپتِ بلندِ ایجنت نباید حافظه‌ی گفتگو رو تقریباً صفر کنه"


def test_local_store_mode_uses_bigger_context_window():
    from app.core.ai_engine import LocalEngine, build_engine_from_settings
    from app.core.settings import AppSettings

    s = AppSettings()
    s.ai_mode = "local"
    s.model_tier = "medium"
    s.business_mode = "store"
    assert isinstance(build_engine_from_settings(s), LocalEngine) and build_engine_from_settings(s).n_ctx == 8192
    s.business_mode = "consultant"
    assert build_engine_from_settings(s).n_ctx == 4096
