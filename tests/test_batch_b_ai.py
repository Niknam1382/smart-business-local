"""باچ B از مستر‌پرامپت (قلم‌های ۹، ۱۱، ۱۴، ۱۷، ۱۸): پرامپتِ سبک، پاسخِ کامل و تمیز،
شتابِ گرافیکیِ واقعی، کشِ پاسخ و ادغامِ پیام‌های مشتری.

هر قلم یک تستِ مستقل دارد تا اگر روزی رفتار برگردد، همان‌جا قرمز شود.
"""

import asyncio

import pytest
from fakes import FakeEngine, FakeLlama, FakeSettings, ScriptedToolEngine, say

from app.core import ai_engine, prompt_kit
from app.core.ai_engine import ChatMessage, LocalEngine
from app.core.answer_cache import AnswerCache
from app.core.bot_pipeline import ConversationPipeline, IncomingMessage
from app.core.conversations import ConversationStore
from app.core.hardware import HardwareInfo
from app.core.qa_agent import QaAgent
from app.core.settings import AppSettings
from tests.shop_harness import Harness

FAST = dict(debounce_wait=0.05, debounce_max_wait=0.2)
HEADINGS = ("## قوانینِ تغییرناپذیر", "## سبکِ پاسخ", "## حریمِ خصوصی", "## مرزها")


def run(coro):
    return asyncio.run(coro)


def msg(chat_id, text, name="سارا"):
    return IncomingMessage(platform="telegram", chat_id=str(chat_id), display_name=name, text=text)


def drive(pipeline, messages):
    """چند پیام را پشت‌سرهم می‌فرستد و پاسخ‌ها را برمی‌گرداند."""
    sent = []

    async def go():
        async def send(text):
            sent.append(text)

        for one in messages:
            await pipeline.handle_incoming(one, send)
            await asyncio.sleep(0.4)
        await pipeline.shutdown()

    run(go())
    return sent


@pytest.fixture
def one_engine(monkeypatch):
    def _install(engine):
        monkeypatch.setattr(ai_engine, "build_engine_from_settings", lambda s: engine)
        return engine

    return _install


# ============================================ ۱۱) پرامپت یک‌بار چیده می‌شود، نه دوباره ====


def store_env(tmp_path):
    h = Harness(tmp_path)
    h.settings.system_prompt = "فروشگاهِ کتابِ ما"
    h.settings.faq_items = [{"q": "ارسال چقدره؟", "a": "پست"}]
    h.products.add("کتاب", 5000, 3)
    store = ConversationStore(db_path=tmp_path / "conv.db")
    agent = QaAgent(h.products, h.orders, h.flow)
    return h, ConversationPipeline(h.settings, store=store, shop_flow=h.flow, qa_agent=agent, **FAST)


def test_store_prompt_is_assembled_exactly_once(tmp_path, one_engine):
    """پیش‌تر پایپ‌لاین پرامپت را می‌ساخت و ایجنت دوباره گاردریل/FAQ را به آن می‌چسباند."""
    engine = one_engine(ScriptedToolEngine({"قیمت کتاب؟": [say("کتاب ۵۰۰۰ ریال است.")]}))
    _h, pipeline = store_env(tmp_path)
    sent = drive(pipeline, [msg(1, "قیمت کتاب؟")])
    prompt = engine.calls[0]["system_prompt"]

    assert sent == ["کتاب ۵۰۰۰ ریال است."]
    assert prompt.startswith("فروشگاهِ کتابِ ما")
    for heading in (*HEADINGS, "## سؤالات متداول", "## کاتالوگ", "نامِ نمایشیِ مشتری (متنِ اعتمادناپذیر): سارا"):
        assert prompt.count(heading) == 1, heading


def test_advisor_prompt_keeps_one_copy_and_no_catalog(tmp_path, one_engine):
    engine = one_engine(FakeEngine())
    settings = FakeSettings(tmp_path)
    settings.business_mode = "consultant"
    pipeline = ConversationPipeline(settings, store=ConversationStore(db_path=tmp_path / "c.db"), **FAST)
    drive(pipeline, [msg(1, "سلام")])
    prompt = engine.calls[0][0]
    assert all(prompt.count(head) == 1 for head in HEADINGS)
    assert "## کاتالوگ" not in prompt


def test_small_context_window_shrinks_the_catalog_but_not_the_rules(tmp_path):
    """۱۱+۱۴: پنجره‌ی تنگ ⇒ کاتالوگ/FAQ کوتاه می‌شن، گاردریل‌ها هرگز."""
    h = Harness(tmp_path)
    for i in range(30):
        h.products.add(f"کالا {i}", 1000 * (i + 1), 5, description="توضیحِ بلندي " * 20)
    tight = prompt_kit.build_system_prompt(h.settings, store_mode=True, product_store=h.products,
                                           order_store=h.orders, context_tokens=1500)
    loose = prompt_kit.build_system_prompt(h.settings, store_mode=True, product_store=h.products,
                                           order_store=h.orders, context_tokens=0)
    assert tight.count("شناسه=") < loose.count("شناسه=") >= 30 - 1
    assert tight.count("شناسه=") >= prompt_kit.CATALOG_MIN_LINES
    for heading in HEADINGS:
        assert heading in tight


def test_faq_item_caps_are_documented(tmp_path):
    h = Harness(tmp_path)
    h.settings.faq_items = [{"q": "پ" * 500, "a": "ت" * 900}]
    out = prompt_kit.faq_lines(h.settings)
    assert "پ" * prompt_kit.MAX_FAQ_QUESTION in out and "پ" * (prompt_kit.MAX_FAQ_QUESTION + 1) not in out
    assert "ت" * prompt_kit.MAX_FAQ_ANSWER in out and "ت" * (prompt_kit.MAX_FAQ_ANSWER + 1) not in out


# ==================================== ۹) پاسخِ کامل و بدونِ ستاره برای مشتری ====


def test_markdown_never_reaches_the_customer(tmp_path, one_engine):
    one_engine(FakeEngine(reply=lambda q: "**کتاب**: ۵۰۰۰ ریال\n* ارسالِ پستی\n`کدِ رهگیری`"))
    store = ConversationStore(db_path=tmp_path / "c.db")
    pipeline = ConversationPipeline(AppSettings(), store=store, **FAST)
    sent = drive(pipeline, [msg(1, "قیمت؟")])
    assert sent == ["کتاب: ۵۰۰۰ ریال\n- ارسالِ پستی\nکدِ رهگیری"]
    history = store.get_history("telegram", "1", limit=10)
    assert history[1].content == sent[0], "آنچه در تاریخچه می‌ماند هم باید تمیز باشد"


def test_plain_answer_rules():
    from app.core.agent_common import plain_answer

    assert plain_answer("## سرِصفحه") == "سرِصفحه"
    assert plain_answer("**مهم** و *کوتاه* و `کد`") == "مهم و کوتاه و کد"
    assert plain_answer("+ قیمت\n- ارسال") == "- قیمت\n- ارسال"
    assert plain_answer("قیمت 5,000 ریال است") == "قیمت 5,000 ریال است"
    assert plain_answer("") == ""


@pytest.fixture
def llama(monkeypatch):
    def _install(*responses, usage=None, error=None, finish_reasons=()):
        fake = FakeLlama(list(responses), usage=usage, error=error, finish_reasons=finish_reasons)
        fake.install(monkeypatch)
        return fake

    return _install


def engine_with(tmp_path, llama, *responses, usage=None, finish_reasons=(), n_ctx=4096, **engine_kw):
    path = tmp_path / "m.gguf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"GGUF" + b"\0" * 4096)
    fake = llama(*responses, usage=usage, finish_reasons=finish_reasons)
    return LocalEngine(path, n_ctx=n_ctx, model_id="qwen35-4b", **engine_kw), fake


def test_cut_answer_is_retried_with_double_budget(tmp_path, llama):
    """۹: finish_reason=length ⇒ یک تلاشِ دوباره با سقفِ دوبله، تا پاسخ نصفه نماند."""
    engine, fake = engine_with(tmp_path, llama, "نیمه‌کاره", "پاسخِ کامل", finish_reasons=("length", "stop"))
    answer = engine.chat("S", [], "کتاب رو توضیح بده")
    assert answer == "پاسخِ کامل"
    first, second = fake.requests
    assert second["max_tokens"] == first["max_tokens"] * 2


def test_finished_answer_is_not_retried(tmp_path, llama):
    engine, fake = engine_with(tmp_path, llama, "پاسخِ کامل", finish_reasons=("stop",))
    assert engine.chat("S", [], "قیمت؟") == "پاسخِ کامل"
    assert len(fake.requests) == 1


def test_reply_budget_follows_the_question_and_the_window(tmp_path, llama):
    engine, _fake = engine_with(tmp_path, llama, "x", n_ctx=4096)
    short = engine.reply_tokens("سلام")
    long = engine.reply_tokens("س" * 300)
    assert short < long
    tiny = LocalEngine(tmp_path / "m.gguf", n_ctx=300)
    assert tiny.reply_tokens("س" * 300) <= 150  # نصفِ پنجره، وگرنه جای تاریخچه نمی‌ماند


def test_flat_tokens_when_optimisation_switched_off(tmp_path, llama):
    engine, fake = engine_with(tmp_path, llama, "پ", adaptive_tokens=False)
    engine.chat("S", [], "س" * 300)
    assert fake.requests[0]["max_tokens"] == LocalEngine.FLAT_REPLY_TOKENS


def test_tool_path_gets_more_room_than_plain_chat(tmp_path, llama):
    from app.core.tool_protocol import ToolSpec

    engine, fake = engine_with(tmp_path, llama, "متن")
    ask = "س" * 300
    engine.chat_tools("S", [], ask, [ToolSpec("suggest_products", "d", {"type": "object"})], [])
    assert fake.requests[0]["max_tokens"] == engine.reply_tokens(ask, tools=True)
    assert fake.requests[0]["max_tokens"] > engine.reply_tokens(ask)


# ============================================ ۱۴) شتابِ گرافیکی: پرس‌وجو، نه حدس ====


def test_gpu_layers_are_asked_from_the_engine_not_guessed(monkeypatch):
    """۱۴: «خودکار» یعنی از خودِ بیلدِ llama-cpp پرسیده شود؛ بیلدِ رسمیِ برنامه CPU است ⇒ ۰."""
    monkeypatch.setattr(ai_engine, "gpu_offload_available", lambda force=False: False)
    assert ai_engine.auto_gpu_layers(HardwareInfo(gpu_model="RTX 4060", gpu_vram_gb=8.0), 2 * 1024**3) == 0

    monkeypatch.setattr(ai_engine, "gpu_offload_available", lambda force=False: True)
    big = HardwareInfo(gpu_model="RTX 4060", gpu_vram_gb=8.0)
    assert ai_engine.auto_gpu_layers(big, 2 * 1024**3) == -1  # VRAM بیش از مدل ⇒ همه‌ی لایه‌ها
    small = HardwareInfo(gpu_model="MX150", gpu_vram_gb=3.0)
    assert ai_engine.auto_gpu_layers(small, 2 * 1024**3) == -11  # جا نمی‌شه ⇒ جز ده لایه‌ی آخر
    assert ai_engine.auto_gpu_layers(HardwareInfo(gpu_model="GTX 710", gpu_vram_gb=1.0), 2 * 1024**3) == 0
    assert ai_engine.auto_gpu_layers(HardwareInfo(gpu_vram_gb=None), 2 * 1024**3) == 0


def engine_settings_env(tmp_path, monkeypatch, *, offload: bool, vram: float):
    """محیطِ ساختِ موتور: GGUFِ جعلی + سخت‌افزارِ ساختگی + «llama هست».

    سطرِ آخر لازم است: `build_engine_from_settings` اول موجودیِ llama-cpp را می‌پرسد و در CIِ
    سالم (که llama-cpp-python نصب نیست) پیش از هر چیزی AiEngineError می‌دهد."""
    path = tmp_path / "models" / "m.gguf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"GGUF" + b"\0" * 1024)
    monkeypatch.setattr(ai_engine, "_llama_available", lambda: True)
    monkeypatch.setattr(ai_engine, "gpu_offload_available", lambda force=False: offload)
    monkeypatch.setattr("app.core.hardware.detect",
                        lambda *a, **k: HardwareInfo(ram_gb=16, cpu_cores=8, gpu_model="RTX" if vram else "", gpu_vram_gb=vram))
    return path


def test_settings_value_beats_the_auto_choice(tmp_path, monkeypatch):
    path = engine_settings_env(tmp_path, monkeypatch, offload=True, vram=8.0)
    base = dict(model_storage_path=str(tmp_path / "models"), model_file_path=str(path))

    assert ai_engine.build_engine_from_settings(AppSettings(**base)).n_gpu_layers == -1  # ۰ = خودکار
    assert ai_engine.build_engine_from_settings(AppSettings(ai_gpu_layers=7, **base)).n_gpu_layers == 7


# ==================================================== ۱۷) کشِ پاسخ ====


def cache_key(model="qwen35-4b", prompt="P", history=(), text="قیمت؟"):
    return AnswerCache.key(model, prompt, list(history), text)


def test_cache_hits_only_for_the_identical_context():
    cache = AnswerCache(ttl_seconds=60)
    cache.put(cache_key(), "پاسخ")
    assert cache.get(cache_key()) == "پاسخ"
    assert cache.get(cache_key(text="موجودی؟")) is None  # سؤالِ دیگر
    assert cache.get(cache_key(model="other")) is None  # مدلِ دیگر
    assert cache.get(cache_key(prompt="P2")) is None  # پرامپتِ دیگر (مثلاً قیمت عوض شده)
    assert cache.get(cache_key(history=[ChatMessage("user", "سلام")])) is None  # گفتگوی تازه‌شده


def test_cache_respects_ttl_lru_and_off_switch():
    clock = {"t": 100.0}
    cache = AnswerCache(ttl_seconds=30, max_entries=2, clock=lambda: clock["t"])
    cache.put("a", "الف")
    clock["t"] = 120.0
    assert cache.get("a") == "الف"
    clock["t"] = 200.0
    assert cache.get("a") is None  # از مدتِ خودش گذشت

    cache.put("b", "ب")
    lru = AnswerCache(ttl_seconds=600, max_entries=2, clock=lambda: clock["t"])
    lru.put("x", "ایکس")
    lru.put("y", "ایگریک")
    assert lru.get("x") == "ایکس"  # دیدنِ x آن را در LRU تازه می‌کند
    lru.put("z", "زد")
    assert lru.size() == 2 and lru.get("y") is None and lru.get("z") == "زد"

    lru.set_ttl(0)
    lru.put("d", "د")
    assert lru.size() == 0 and lru.get("d") is None  # خاموش = هیچ

    lru.set_ttl(300)
    lru.put("d", "د")
    assert lru.get("d") == "د"


def test_pipeline_answers_a_repeated_question_without_the_model(tmp_path, one_engine):
    """۱۷: دو مشتری، همان سؤال، همان زمینه ⇒ مدل یک‌بار صدا زده می‌شه."""
    engine = one_engine(FakeEngine())
    settings = AppSettings(business_mode="consultant")
    pipeline = ConversationPipeline(settings, store=ConversationStore(db_path=tmp_path / "c.db"), **FAST)
    sent = drive(pipeline, [msg(1, "قیمت؟"), msg(2, "قیمت؟")])
    assert sent == ["پاسخ: قیمت؟", "پاسخ: قیمت؟"]
    assert len(engine.calls) == 1


def test_token_switches_reach_the_engine(tmp_path, monkeypatch):
    """۱۴: کلیدهایِ خاموش‌شدنیِ «بهینه‌سازیِ توکن» واقعاً به موتور می‌رسند (پیش‌تر مرده بودند)."""
    path = engine_settings_env(tmp_path, monkeypatch, offload=False, vram=0.0)
    s = AppSettings(model_storage_path=str(tmp_path / "models"), model_file_path=str(path))
    assert s.token_opt_max_tokens is True and s.token_opt_history_window is True
    engine = ai_engine.build_engine_from_settings(s)
    assert engine.adaptive_tokens is True and engine.token_history is True
    s.token_opt_max_tokens, s.token_opt_history_window = False, False
    engine = ai_engine.build_engine_from_settings(s)
    assert engine.adaptive_tokens is False and engine.token_history is False


def test_cache_can_be_switched_off_by_the_owner(tmp_path, one_engine):
    settings = AppSettings(business_mode="consultant", ai_response_cache=False)
    engine = one_engine(FakeEngine())
    pipeline = ConversationPipeline(settings, store=ConversationStore(db_path=tmp_path / "c.db"), **FAST)
    drive(pipeline, [msg(1, "قیمت؟"), msg(2, "قیمت؟")])
    assert len(engine.calls) == 2


def test_cache_ttl_follows_settings(tmp_path, one_engine):
    settings = AppSettings(business_mode="consultant", ai_response_cache_minutes=0)
    engine = one_engine(FakeEngine())
    pipeline = ConversationPipeline(settings, store=ConversationStore(db_path=tmp_path / "c.db"), **FAST)
    assert pipeline._cache.enabled is False
    drive(pipeline, [msg(1, "قیمت؟"), msg(2, "قیمت؟")])
    assert len(engine.calls) == 2


# ==================================================== ۱۸) ادغامِ پیام‌ها ====


def test_debounce_window_comes_from_settings(tmp_path, one_engine):
    engine = one_engine(FakeEngine())
    settings = AppSettings(business_mode="consultant", debounce_wait_seconds=0.6, debounce_max_wait_seconds=5)
    pipeline = ConversationPipeline(settings, store=ConversationStore(db_path=tmp_path / "c.db"))

    async def go():
        sent = []

        async def send(text):
            sent.append(text)

        await pipeline.handle_incoming(msg(1, "سلام"), send)
        await asyncio.sleep(0.2)
        await pipeline.handle_incoming(msg(1, "قیمت کتاب؟"), send)
        await asyncio.sleep(1.0)
        await pipeline.shutdown()
        return sent

    sent = run(go())
    assert len(engine.calls) == 1  # دو پیام = یک درخواست
    assert engine.calls[0][2] == "سلام\nقیمت کتاب؟"
    assert len(sent) == 1


def test_zero_wait_answers_every_message(tmp_path, one_engine):
    engine = one_engine(FakeEngine())
    settings = AppSettings(business_mode="consultant", debounce_wait_seconds=0.0, debounce_max_wait_seconds=5)
    pipeline = ConversationPipeline(settings, store=ConversationStore(db_path=tmp_path / "c.db"))

    async def go():
        sent = []

        async def send(text):
            sent.append(text)

        await pipeline.handle_incoming(msg(1, "سلام"), send)
        await asyncio.sleep(0.2)
        await pipeline.handle_incoming(msg(1, "قیمت؟"), send)
        await asyncio.sleep(0.2)
        await pipeline.shutdown()
        return sent

    run(go())
    assert [call[2] for call in engine.calls] == ["سلام", "قیمت؟"]


# ═══════════════ کران‌دار‌بودنِ رکوردهایِ هر گفتگو (بازبینیِ عملکرد، قلم ۲۵) ═══════════


def test_pipeline_forgets_the_oldest_chats_under_pressure(tmp_path, one_engine):
    """یک رباتِ پرمشتری نباید هر گفتگو را تا ابد در حافظه نگه دارد."""
    from app.core import bot_pipeline as bp

    engine = one_engine(FakeEngine())
    settings = AppSettings(business_mode="consultant", ai_response_cache=False)
    pipeline = ConversationPipeline(settings, store=ConversationStore(db_path=tmp_path / "leak.db"), debounce_wait=0.01, debounce_max_wait=0.05)

    async def go():
        async def send(text):
            pass

        for index in range(bp.MAX_TRACKED_CHATS + 40):
            await pipeline.handle_incoming(msg(index + 1, "سلام"), send)
        await asyncio.sleep(1.2)
        await pipeline.shutdown()

    run(go())
    assert len(pipeline._send_fns) <= bp.MAX_TRACKED_CHATS
    assert len(pipeline._transports) <= bp.MAX_TRACKED_CHATS
    assert len(pipeline._chat_locks) <= bp.MAX_TRACKED_CHATS
    assert engine.calls, "با وجودِ فشار، پیام‌ها پردازش شده‌اند"


def test_remember_never_drops_a_lock_that_is_in_use():
    import asyncio

    from app.core.bot_pipeline import _remember

    async def go():
        held = asyncio.Lock()
        await held.acquire()
        table = {("old",): asyncio.Lock(), ("held",): held}
        _remember(table, ("new",), asyncio.Lock())
        assert ("held",) in table and not table[("old",)].locked()
        held.release()

    run(go())
