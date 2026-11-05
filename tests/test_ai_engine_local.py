"""موتورِ محلی (نسخه‌ی ۱.۰.۰): دروازه‌هایِ «آماده‌بودن»، ساختِ موتور از تنظیمات، و ``LocalEngine`` با
``llama_cppِ`` جعلیِ تزریق‌شده در ``sys.modules`` — بدونِ مدلِ واقعی، بدونِ llamaِ واقعی، بدونِ شبکه.
"""

import sys
import types
from pathlib import Path

import pytest
from fakes import FakeLlama

from app.core import ai_engine, ai_usage, hardware, model_catalog
from app.core.ai_engine import AiEngineError, ChatMessage, LocalEngine
from app.core.settings import AppSettings
from app.core.tool_protocol import CLOSE_TAG, RESULT_OPEN, ToolSpec

GGUF_MAGIC = b"GGUF"
SPECS = [ToolSpec("suggest_products", "کارتِ محصول نشان بده", {"type": "object", "properties": {"product_ids": {"type": "array"}}})]


def gguf_file(path: Path, size: int = 2 * 1024 * 1024) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(GGUF_MAGIC + b"\0" * (size - len(GGUF_MAGIC)))
    return path


def settings_with(tmp_path, **kw) -> AppSettings:
    s = AppSettings(model_storage_path=str(tmp_path / "models"))
    for key, value in kw.items():
        setattr(s, key, value)
    return s


def fake_hw(ram=16.0, cores=8):
    return hardware.HardwareInfo(ram_gb=ram, cpu_cores=cores, free_disk_gb=200.0)


@pytest.fixture
def llama(monkeypatch):
    """llama_cppِ جعلی را جا می‌زند (هرگز نسخه‌ی واقعی import نمی‌شه)."""

    def _install(*responses, usage=None, error=None):
        fake = FakeLlama(list(responses), usage=usage, error=error)
        fake.install(monkeypatch)
        return fake

    return _install


@pytest.fixture
def detector(monkeypatch):
    def _patch(info):
        monkeypatch.setattr(hardware, "detect", lambda *a, **k: info)

    return _patch


@pytest.fixture
def recorder():
    class Capture:
        def __init__(self):
            self.rows: list = []

        def record(self, **fields):
            self.rows.append(fields)

    cap = Capture()
    previous = ai_usage.RECORDER
    ai_usage.RECORDER = cap
    try:
        yield cap
    finally:
        ai_usage.RECORDER = previous


def engine_with(tmp_path, llama, *responses, usage=None, error=None, n_ctx=4096, model_id="qwen35-4b", name="m.gguf"):
    """یک LocalEngine ساخته‌شده روی فایلِ GGUFِ جعلی + ثبتِ llamaِ آن."""
    fake = llama(*responses, usage=usage, error=error)
    return LocalEngine(gguf_file(tmp_path / "models" / name, size=2 * 1024 * 1024), n_ctx=n_ctx, model_id=model_id), fake


# --------------------------------------------------------------- resolve_model_path ----


def test_no_model_selected_has_no_path(tmp_path):
    assert ai_engine.resolve_model_path(settings_with(tmp_path)) is None
    assert ai_engine.resolve_model_path(settings_with(tmp_path, model_id="not-in-catalog")) is None


def test_catalog_model_path_is_under_the_storage_dir(tmp_path):
    entry = model_catalog.get_entry("qwen35-4b")
    path = ai_engine.resolve_model_path(settings_with(tmp_path, model_id=entry.id))
    assert path == tmp_path / "models" / entry.filename


def test_imported_file_path_must_be_a_real_gguf_not_a_folder_or_symlink(tmp_path):
    good = gguf_file(tmp_path / "mine.gguf")
    assert ai_engine.resolve_model_path(settings_with(tmp_path, model_file_path=str(good))) == good

    wrong_suffix = tmp_path / "model.bin"
    wrong_suffix.write_bytes(GGUF_MAGIC + b"\0" * 5000)
    assert ai_engine.resolve_model_path(settings_with(tmp_path, model_file_path=str(wrong_suffix))) is None

    folder = tmp_path / "a-folder.gguf"
    folder.mkdir()
    assert ai_engine.resolve_model_path(settings_with(tmp_path, model_file_path=str(folder))) is None

    missing = tmp_path / "never.gguf"
    assert ai_engine.resolve_model_path(settings_with(tmp_path, model_file_path=str(missing))) is None

    link = tmp_path / "linked.gguf"
    try:
        link.symlink_to(good)
    except (OSError, NotImplementedError):  # ویندوز بدونِ Developer Mode
        pytest.skip("این سیستم/کاربر اجازه‌ی ساختِ symlink ندارد")
    assert ai_engine.resolve_model_path(settings_with(tmp_path, model_file_path=str(link))) is None


def test_explicit_file_wins_over_the_catalog(tmp_path):
    imported = gguf_file(tmp_path / "chosen.gguf")
    s = settings_with(tmp_path, model_id="qwen35-4b", model_file_path=str(imported))
    assert ai_engine.resolve_model_path(s) == imported


# ------------------------------------------------------------------ engine_readiness ----


def test_readiness_keys_walk_the_whole_gate(tmp_path, llama):
    llama("x")  # موتورِ اجرا در دسترس است

    s = settings_with(tmp_path)
    assert ai_engine.engine_readiness(s) == (False, "ai.ready.no_model_selected")

    s.model_id = "qwen35-2b"
    assert ai_engine.engine_readiness(s) == (False, "ai.ready.not_downloaded")

    gguf_file(tmp_path / "models" / model_catalog.get_entry("qwen35-2b").filename)  # سایز با کاتالوگ نمی‌خونه
    assert ai_engine.engine_readiness(s) == (False, "ai.ready.file_invalid")

    imported = gguf_file(tmp_path / "own.gguf")  # بدونِ model_id ⇒ راستی‌آزماییِ سایز لازم نیست
    assert ai_engine.engine_readiness(settings_with(tmp_path, model_file_path=str(imported))) == (True, "ai.ready.ok")
    assert ai_engine.engine_readiness(None) == (False, "ai.ready.none")


def test_readiness_reports_missing_llama_before_the_file(tmp_path, monkeypatch):
    monkeypatch.delitem(sys.modules, "llama_cpp", raising=False)
    monkeypatch.setattr(ai_engine, "_llama_available", lambda: False)
    s = settings_with(tmp_path, model_id="qwen35-2b")
    gguf_file(tmp_path / "models" / model_catalog.get_entry("qwen35-2b").filename, size=6 * 1024 * 1024)
    assert ai_engine.engine_readiness(s) == (False, "ai.ready.llama_missing")


# ------------------------------------------------------------ build_engine_from_settings ----


def test_build_refuses_without_llama_or_model(tmp_path, monkeypatch):
    monkeypatch.delitem(sys.modules, "llama_cpp", raising=False)
    monkeypatch.setattr(ai_engine, "_llama_available", lambda: False)
    with pytest.raises(AiEngineError, match="llama-cpp"):
        ai_engine.build_engine_from_settings(settings_with(tmp_path, model_id="qwen35-2b"))

    monkeypatch.setattr(ai_engine, "_llama_available", lambda: True)
    with pytest.raises(AiEngineError, match="انتخاب یا دانلود نشده"):
        ai_engine.build_engine_from_settings(settings_with(tmp_path))

    with pytest.raises(AiEngineError, match="پیدا نشد"):
        ai_engine.build_engine_from_settings(settings_with(tmp_path, model_id="qwen35-2b"))


def test_build_uses_catalog_defaults_and_respects_user_numbers(tmp_path, llama, detector):
    llama("ok")
    detector(fake_hw(ram=16.0, cores=8))
    entry = model_catalog.get_entry("qwen35-2b")
    s = settings_with(tmp_path, model_id=entry.id)
    gguf_file(tmp_path / "models" / entry.filename)

    engine = ai_engine.build_engine_from_settings(s)
    assert isinstance(engine, LocalEngine) and engine.n_ctx == model_catalog.auto_context_tokens(fake_hw(16.0, 8), entry)
    assert engine.n_threads == model_catalog.auto_threads(fake_hw(16.0, 8)) == 7 and engine.n_gpu_layers == 0
    assert engine.model_id == entry.id and engine.concurrent_safe is False

    s.ai_context_tokens, s.ai_threads, s.ai_gpu_layers = 3072, 2, 99  # دستورِ کاربر بالاتر از خودکار
    forced = ai_engine.build_engine_from_settings(s)
    assert (forced.n_ctx, forced.n_threads, forced.n_gpu_layers) == (3072, 2, 99)


def test_build_with_an_imported_file_chooses_context_by_size(tmp_path, llama, detector):
    llama("ok")
    detector(fake_hw(ram=4.0))
    imported = gguf_file(tmp_path / "small.gguf", size=2 * 1024 * 1024)
    engine = ai_engine.build_engine_from_settings(settings_with(tmp_path, model_file_path=str(imported)))
    assert engine.n_ctx == 4096 and engine.model_id == "small.gguf"


# ------------------------------------------------------------------------- LocalEngine ----


def test_model_is_loaded_lazily_with_the_right_numbers(tmp_path, llama):
    fake = llama("جواب")
    path = gguf_file(tmp_path / "m.gguf")
    engine = LocalEngine(path, n_ctx=2048, n_gpu_layers=0, n_threads=4, model_id="qwen35-2b")
    assert fake.instances == []  # هیچ چیزی لود نشده
    assert engine.chat("S", [], "سلام") == "جواب"
    [instance] = fake.instances
    assert instance.kwargs["model_path"] == str(path) and instance.kwargs["n_ctx"] == 2048
    assert instance.kwargs["n_threads"] == 4 and instance.kwargs["verbose"] is False
    assert instance.kwargs["n_gpu_layers"] == 0
    engine.unload()
    assert instance.closed is True
    engine.unload()  # دوباره بی‌خطر


def test_chat_builds_system_history_and_user_messages(tmp_path, llama):
    engine, fake = engine_with(tmp_path, llama, "پاسخِ نهایی")
    history = [ChatMessage("user", "سلام"), ChatMessage("assistant", "سلام!")]
    assert engine.chat("پرامپتِ سیستم", history, "قیمت چنده؟") == "پاسخِ نهایی"
    sent = fake.instances[0].requests[0]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert sent[0]["content"] == "پرامپتِ سیستم" and sent[-1]["content"] == "قیمت چنده؟"


def test_chat_drops_oldest_history_when_the_window_is_tight(tmp_path, llama):
    engine, fake = engine_with(tmp_path, llama, "کوتاه", n_ctx=200)  # ~۶۰۰ کاراکتر جا هست
    history = [ChatMessage("user" if i % 2 == 0 else "assistant", "ا" * 120) for i in range(30)]
    engine.chat("S", history, "سوال")
    sent = fake.instances[0].requests[0]["messages"]
    assert len(sent) < len(history) + 2 and sent[-1]["content"] == "سوال"
    assert [m["content"] for m in sent[1:-1]] == [m.content for m in history][-len(sent) + 2:]  # قدیمی‌ترها رفته‌اند


def test_think_block_never_reaches_the_customer(tmp_path, llama):
    engine, _fake = engine_with(tmp_path, llama, "<think>اینجا فکر کردم</think>\n\nپاسخِ فارسی")
    assert engine.chat("S", [], "سوال") == "پاسخِ فارسی"

def test_half_open_think_block_is_dropped_entirely(tmp_path, llama):
    """اگر قالبِ گفتگو بلوکِ تفکر را نبندد (تقطیع وسطِ تفکر)، هیچِ آن به مشتری نمی‌رسد."""
    engine, _fake = engine_with(tmp_path, llama, "پاسخ\n<think>ادامهٔ تفکر که بسته نشد")
    assert engine.chat("S", [], "سوال") == "پاسخ"

def test_plain_two_paragraph_answer_is_not_mangled(tmp_path, llama):
    """پاک‌سازیِ تفکر نباید پاراگرافِ اولِ یک پاسخِ عادی را ببلعد."""
    engine, _fake = engine_with(tmp_path, llama, "اینجا فکر کردم\n\nپاسخِ فارسی")
    assert engine.chat("S", [], "سوال") == "اینجا فکر کردم\n\nپاسخِ فارسی"

def test_think_block_inside_a_tool_turn_is_stripped_before_parsing(tmp_path, llama):
    engine, fake = engine_with(tmp_path, llama, 'محصول را پیدا کردم\n<tool_call>{"name": "suggest_products", "arguments": {"product_ids": [7]}}')
    turn = engine.chat_tools("S", [], "چی داری؟", SPECS, [])
    assert [c.name for c in turn.tool_calls] == ["suggest_products"] and turn.tool_calls[0].arguments == {"product_ids": [7]}
    assert "think" not in turn.text
    sent = fake.instances[0].requests[0]
    assert sent["stop"] == [CLOSE_TAG, RESULT_OPEN]  # حدس‌زدنِ نتیجه‌ی ابزار ممنوع
    assert "suggest_products" in sent["messages"][0]["content"]  # پروتکلِ متنی در پرامپتِ سیستم


def test_chat_tools_renders_the_tool_exchange_as_text(tmp_path, llama):
    engine, fake = engine_with(tmp_path, llama, "با توجه به نتیجه، سه مدل داریم")
    tool_messages = [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "name": "suggest_products", "arguments": {"product_ids": [1, 2]}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "suggest_products", "content": '{"shown": 2}'},
    ]
    turn = engine.chat_tools("S", [], "چی داری؟", SPECS, tool_messages)
    assert turn.text == "با توجه به نتیجه، سه مدل داریم" and turn.tool_calls == []
    messages = fake.instances[0].requests[0]["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert "<tool_call>" in messages[-2]["content"]
    assert messages[-1]["content"] == '<tool_result name="suggest_products">{"shown": 2}</tool_result>'


def test_usage_is_recorded_and_estimated_when_the_model_gives_nothing(tmp_path, llama, recorder):
    engine, _fake = engine_with(tmp_path, llama, "جواب", usage={"prompt_tokens": 40, "completion_tokens": 9})
    engine.chat("S", [], "سلام")
    [row] = recorder.rows
    assert row["provider_id"] == "local" and row["model"] == "qwen35-4b" and row["kind"] == "chat"
    assert (row["prompt_tokens"], row["completion_tokens"], row["estimated"], row["ok"]) == (40, 9, False, True)
    assert row["latency_ms"] >= 0
    assert engine.last_usage == {"prompt_tokens": 40, "completion_tokens": 9}

    quiet, _q = engine_with(tmp_path, llama, "جوابِ دوم", usage={}, name="quiet.gguf")
    quiet.chat("S", [], "سلام")
    assert quiet.last_usage == {}
    row = recorder.rows[-1]
    assert row["estimated"] is True and row["prompt_tokens"] > 0  # تخمین با برچسب، هرگز بی‌برچسب

    quiet.record_usage = False
    quiet.chat("S", [], "سلام")
    assert len(recorder.rows) == 2  # خاموش‌کردنِ ثبتِ مصرف


def test_model_failures_become_persian_engine_errors(tmp_path, llama):
    engine, _fake = engine_with(tmp_path, llama, error=RuntimeError("bad allocation"))
    with pytest.raises(AiEngineError, match="اجرای مدل محلی شکست خورد"):
        engine.chat("S", [], "سلام")
    ok, message = engine.self_test()
    assert ok is False and "اجرای مدل محلی شکست خورد" in message


def test_missing_file_on_disk_is_a_clear_error(tmp_path, llama):
    llama("هیچ‌وقت به اینجا نمی‌رسیم")
    engine = LocalEngine(tmp_path / "absent.gguf")
    with pytest.raises(AiEngineError, match="هنوز دانلود نشده"):
        engine.chat("S", [], "سلام")


def test_self_test_asks_once_and_reports_the_answer(tmp_path, llama):
    engine, fake = engine_with(tmp_path, llama, "آماده‌ام")
    assert engine.self_test() == (True, "✅ مدل پاسخ داد: آماده‌ام")
    assert len(fake.instances[0].requests) == 1
    empty, _q = engine_with(tmp_path, llama, "   ", name="empty.gguf")
    ok, message = empty.self_test()
    assert ok is False and "رم" in message


def test_engine_surface_has_no_api_left(tmp_path):
    surface = {n for n in dir(ai_engine) if not n.startswith("_")}
    for gone in ("ApiEngine", "FailoverEngine", "API", "api_key"):
        assert gone not in surface, gone
    path = gguf_file(tmp_path / "m.gguf")
    engine = LocalEngine(path)
    assert engine.model_path == path and engine.record_usage is True


# ------------------------------------------------- پرس‌وجویِ توانِ GPU (ابهامِ CUDA)


def fake_llama_module(**attrs):
    module = types.ModuleType("llama_cpp")
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def test_gpu_offload_asks_the_installed_build_and_caches_the_answer(monkeypatch):
    """«آیا GPU کار می‌کنه؟» پاسخِ llama.cpp است، نه نامِ کارتِ گرافیک."""
    ai_engine.reset_gpu_offload_cache()
    try:
        monkeypatch.setitem(sys.modules, "llama_cpp", fake_llama_module(llama_supports_gpu_offload=lambda: True))
        assert ai_engine.gpu_offload_available() is True
        # پاسخِ اول کش می‌شه؛ پس یک بیلدِ دیگر در همان اجرا جوابِ قبلی را می‌دهد
        monkeypatch.setitem(sys.modules, "llama_cpp", fake_llama_module(llama_supports_gpu_offload=lambda: False))
        assert ai_engine.gpu_offload_available() is True
        ai_engine.reset_gpu_offload_cache()
        assert ai_engine.gpu_offload_available() is False
    finally:
        ai_engine.reset_gpu_offload_cache()


def test_gpu_offload_is_false_when_the_build_cannot_answer(monkeypatch):
    """نبودِ llama_cpp، نبودِ سمبل، یا crashِ خودِ سمبل = همان «CPU-only» بودن (نه خطایِ کاربر)."""
    ai_engine.reset_gpu_offload_cache()
    try:
        monkeypatch.setitem(sys.modules, "llama_cpp", fake_llama_module())  # سمبل نیست
        assert ai_engine.gpu_offload_available() is False
        ai_engine.reset_gpu_offload_cache()

        def boom():
            raise RuntimeError("no native library")

        monkeypatch.setitem(sys.modules, "llama_cpp", fake_llama_module(llama_supports_gpu_offload=boom))
        assert ai_engine.gpu_offload_available() is False
        ai_engine.reset_gpu_offload_cache()

        monkeypatch.delitem(sys.modules, "llama_cpp", raising=False)
        assert ai_engine.gpu_offload_available() is False
    finally:
        ai_engine.reset_gpu_offload_cache()
