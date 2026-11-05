"""۱.۰.۰ — صفحه‌ی «مدلِ محلی» (آنبوردینگ + صفحه‌ی AI + مصرف) با FakePage.

هیچ تستی شبکه نمی‌زند (دانلودر جعلی) و هیچ‌کدام llama_cpp نمی‌خواهد
(`_llama_available` دروغ‌پچ می‌شود). سخت‌افزار در هر تست ثابت patch می‌شه تا
پیشنهادِ کاتالوگ قطعی باشه.
"""

import types
from pathlib import Path

import pytest
from fake_page import FakePage, collect_text, find, fire

from app.core import ai_engine, downloader, hardware, model_catalog
from app.core.ai_usage import UsageStore
from app.core.conversations import ConversationStore
from app.core.settings import AppSettings, load_settings, save_settings
from app.screens import ai_select, ai_setup, usage

GGUF_OK = b"GGUF" + b"\0" * 1_100_000  # دروغِ GGUF با حجمِ بالای آستانه‌ی ۱ مگابایت


class QueuedPage(FakePage):
    """run_thread را صف می‌کند (نه هم‌زمان اجرا می‌کند) تا وضعیتِ «در حال دانلود» در درخت دیده بشه."""

    def __init__(self):
        super().__init__()
        self.pending = []

    def run_thread(self, handler, *a, **k):
        self.run_thread_calls += 1
        self.pending.append(handler)

    def drain(self):
        workers, self.pending = self.pending, []
        for worker in workers:
            worker()


def patch_hw(monkeypatch, ram_gb=16.0, cores=12, free_gb=200.0):
    hw = hardware.HardwareInfo(ram_gb=ram_gb, cpu_cores=cores, cpu_model="Test CPU X", gpu_model="",
                               gpu_vram_gb=None, free_disk_gb=free_gb)
    monkeypatch.setattr(hardware, "detect", lambda force=False, disk_path=None: hw)
    monkeypatch.setattr(hardware, "free_disk_gb_at", lambda path: free_gb)
    return hw


@pytest.fixture(autouse=True)
def no_llama(monkeypatch):
    """تست‌ها نباید به llama_cpp وابسته باشن؛ مسیرِ «نصب نیست» هم عمداً تست می‌شه."""
    monkeypatch.setattr(ai_engine, "_llama_available", lambda: False)


@pytest.fixture
def dl(monkeypatch):
    """دانلودرِ جعلیِ بدونِ شبکه؛ رفتار قابل‌تنظیم: ok/fail/cancel/verify_fail."""
    state = {"behavior": "ok", "calls": []}

    def fake_download(urls, dest, expected_sha256="", expected_size=0, on_progress=None, should_cancel=None, timeout=30, allowed_hosts=None):
        dest = Path(dest)
        state["calls"].append({"urls": list(urls), "dest": dest, "sha": expected_sha256, "allowed_hosts": set(allowed_hosts or ())})
        dest.parent.mkdir(parents=True, exist_ok=True)
        if state["behavior"] == "fail":
            raise downloader.DownloadError("قطعیِ تستیِ اینترنت")
        step = max(1, int(expected_size) // 3)
        done = 0
        while done < int(expected_size):
            if should_cancel and should_cancel():
                part = dest.with_name(dest.name + ".part")
                part.write_bytes(b"x" * max(1000, min(done, 500_000)))
                raise downloader.DownloadCancelled()
            done = min(done + step, int(expected_size))
            if on_progress:
                on_progress(done, int(expected_size))
        dest.write_bytes(GGUF_OK)
        for stale in (dest.with_name(dest.name + ".part"), dest.with_name(dest.name + ".part.meta")):
            stale.unlink(missing_ok=True)
        return dest

    def fake_is_downloaded(path, expected_size=0):
        try:
            return path.is_file() and path.stat().st_size >= 1_000_000 and path.read_bytes()[:4] == b"GGUF"
        except OSError:
            return False

    def fake_verify(path, expected_sha256):
        if state["behavior"] == "verify_fail":
            return False, "اثرانگشتِ فایل با نسخه‌ی اصلی نمی‌خونه"
        return True, ""

    monkeypatch.setattr(downloader, "download", fake_download)
    monkeypatch.setattr(downloader, "is_downloaded", fake_is_downloaded)
    monkeypatch.setattr(downloader, "verify_file", fake_verify)
    return state


@pytest.fixture
def s0():
    return AppSettings(business_mode="store", user_name="آزمون")


def rec_for(hw):
    return model_catalog.recommend(hw, path_free_gb=200.0)


def rec_path(settings, entry):
    return settings.get_model_storage_dir() / entry.filename


# ---------------------------------------------------------------- صفحه‌ی AI (سایدبار)


def test_ai_setup_has_no_api_language_and_shows_hw_card(monkeypatch, s0, dl):
    patch_hw(monkeypatch)
    ctl = ai_setup.build(FakePage(), "fa", s0, lambda: None)
    text = collect_text(ctl)
    assert find(ctl, "hw_card") is not None
    assert "CPU" in text  # یادداشتِ صادقانه: بیلدِ رسمی روی پردازنده حساب می‌کنه
    for banned in ("API", "کلید API", "Base URL"):
        assert banned not in text
    assert find(ctl, "api_fields") is None and find(ctl, "ai_card_api") is None


def test_ai_setup_model_cards_ranked_with_fit_badges(monkeypatch, s0, dl):
    hw = patch_hw(monkeypatch)
    ctl = ai_setup.build(FakePage(), "fa", s0, lambda: None)
    for entry, _state in model_catalog.ranked_for(hw, path_free_gb=200.0):
        assert find(ctl, f"model_card_{entry.id}") is not None, entry.id
    rec = rec_for(hw)
    assert find(ctl, f"badge_{rec.id}").content.value == "پیشنهادِ ما"
    assert find(ctl, f"dl_btn_{rec.id}").disabled is False
    assert find(ctl, "badge_qwen35-9b").content.value == "در مرز"  # ۱۶ گیگ: ۹B در مرزه ولی دانلودش مجازه


def test_ai_setup_disables_models_that_do_not_fit_ram(monkeypatch, s0, dl):
    patch_hw(monkeypatch, ram_gb=4.0)
    ctl = ai_setup.build(FakePage(), "fa", s0, lambda: None)
    assert find(ctl, "dl_btn_qwen35-2b").disabled is True
    card_text = collect_text(find(ctl, "model_card_qwen35-2b"))
    assert "جا نمی‌شه" in card_text and "رمِ این سیستم برایِ این مدل کمه" in card_text


def test_ai_setup_disables_models_with_no_disk_space(monkeypatch, s0, dl):
    patch_hw(monkeypatch, ram_gb=16.0, free_gb=0.5)
    ctl = ai_setup.build(FakePage(), "fa", s0, lambda: None)
    assert find(ctl, "dl_btn_qwen35-4b").disabled is True
    assert "فضایِ خالی" in collect_text(find(ctl, "model_card_qwen35-4b"))


def test_ai_setup_one_click_download_selects_and_completes(monkeypatch, s0, dl):
    hw = patch_hw(monkeypatch)
    rec = rec_for(hw)
    page = FakePage()  # run_thread هم‌زمان اجرا می‌شه ⇒ نتیجه بعدِ fire قطعی‌ه
    ctl = ai_setup.build(page, "fa", s0, lambda: save_settings(s0))
    fire(find(ctl, f"dl_btn_{rec.id}"), "on_click")
    assert s0.model_id == rec.id
    assert dl["calls"][0]["urls"][0] == rec.urls[0] and dl["calls"][0]["dest"].name == rec.filename
    assert dl["calls"][0]["sha"] == rec.sha256
    assert "hf.co" in dl["calls"][0]["allowed_hosts"]  # CDNِ اعلام‌شده باید ردِ گارد نشه
    card_text = collect_text(find(ctl, f"model_card_{rec.id}"))
    assert "کامل و آماده است" in card_text and "اکنون استفاده می‌شه" in card_text
    assert ai_engine.resolve_model_path(load_settings()) == rec_path(s0, rec)
    assert find(ctl, f"cancel_btn_{rec.id}") is None  # تموم شد ⇒ دکمه‌ی لغو دیگه نیست


def test_ai_setup_downloading_state_then_cancel_keeps_partial(monkeypatch, s0, dl):
    hw = patch_hw(monkeypatch)
    rec = rec_for(hw)
    page = QueuedPage()
    ctl = ai_setup.build(page, "fa", s0, lambda: None)
    fire(find(ctl, f"dl_btn_{rec.id}"), "on_click")
    assert find(ctl, f"cancel_btn_{rec.id}") is not None
    assert find(ctl, f"dl_btn_{rec.id}").disabled is True
    hub = find(ctl, "model_hub")
    hub.data["tick"]()  # پیشرفت از رکوردِ مشترک خونده می‌شه — بدونِ تردِ بی‌نهایت در تست
    assert "در حال دانلود" in find(ctl, f"prog_text_{rec.id}").value
    fire(find(ctl, f"cancel_btn_{rec.id}"), "on_click")
    page.drain()
    assert "ادامه‌ی دانلود" in collect_text(find(ctl, f"model_card_{rec.id}"))
    dest = rec_path(s0, rec)
    assert dest.with_name(dest.name + ".part").exists()


def test_ai_setup_failure_shows_honest_error_and_retry(monkeypatch, s0, dl):
    hw = patch_hw(monkeypatch)
    rec = rec_for(hw)
    dl["behavior"] = "fail"
    ctl = ai_setup.build(FakePage(), "fa", s0, lambda: None)
    fire(find(ctl, f"dl_btn_{rec.id}"), "on_click")
    assert "قطعیِ تستیِ اینترنت" in find(ctl, f"err_text_{rec.id}").value


def test_ai_setup_partial_resume_button_label(monkeypatch, s0, dl):
    hw = patch_hw(monkeypatch)
    rec = rec_for(hw)
    dest = rec_path(s0, rec)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.with_name(dest.name + ".part").write_bytes(b"x" * 4096)
    ctl = ai_setup.build(FakePage(), "fa", s0, lambda: None)
    assert "ادامه‌ی دانلود" in collect_text(find(ctl, f"model_card_{rec.id}"))
    fire(find(ctl, f"dl_btn_{rec.id}"), "on_click")
    assert dest.exists() and not dest.with_name(dest.name + ".part").exists()


def test_ai_setup_delete_needs_two_clicks_and_frees_space(monkeypatch, s0, dl):
    hw = patch_hw(monkeypatch)
    rec = rec_for(hw)
    ctl = ai_setup.build(FakePage(), "fa", s0, lambda: None)
    fire(find(ctl, f"dl_btn_{rec.id}"), "on_click")
    dest = rec_path(s0, rec)
    fire(find(ctl, f"del_btn_{rec.id}"), "on_click")
    assert dest.exists() and "مطمئنی" in find(ctl, f"del_btn_{rec.id}").content
    fire(find(ctl, f"del_btn_{rec.id}"), "on_click")
    assert not dest.exists()
    assert "دانلود" in collect_text(find(ctl, f"model_card_{rec.id}"))


def test_ai_setup_verify_reports_hash_ok_and_bad(monkeypatch, s0, dl):
    hw = patch_hw(monkeypatch)
    rec = rec_for(hw)
    ctl = ai_setup.build(FakePage(), "fa", s0, lambda: None)
    fire(find(ctl, f"dl_btn_{rec.id}"), "on_click")
    fire(find(ctl, f"verify_btn_{rec.id}"), "on_click")
    assert "اثرانگشت" in find(ctl, f"verify_text_{rec.id}").value
    dl["behavior"] = "verify_fail"
    fire(find(ctl, f"verify_btn_{rec.id}"), "on_click")
    assert "نمی‌خونه" in find(ctl, f"verify_text_{rec.id}").value


def test_ai_setup_invalid_file_offers_redownload(monkeypatch, s0, dl):
    hw = patch_hw(monkeypatch)
    rec = rec_for(hw)
    dest = rec_path(s0, rec)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"junk")  # هست ولی GGUF نیست ⇒ invalid
    ctl = ai_setup.build(FakePage(), "fa", s0, lambda: None)
    assert "ناقص یا خراب" in collect_text(find(ctl, f"model_card_{rec.id}"))
    assert find(ctl, f"dl_btn_{rec.id}").content == "دانلودِ دوباره"


# ---------------------------------------------------------------- وارد کردن فایل


def test_ai_setup_import_accepts_real_gguf_and_back_returns_to_catalog(monkeypatch, s0, dl, tmp_path):
    patch_hw(monkeypatch)
    good = tmp_path / "my-model.gguf"
    good.write_bytes(GGUF_OK)
    ctl = ai_setup.build(FakePage(), "fa", s0, lambda: save_settings(s0))
    find(ctl, "import_path_field").value = str(good)
    fire(find(ctl, "import_apply_btn"), "on_click")
    assert s0.model_file_path == str(good) and not s0.model_id
    assert find(ctl, "imported_card") is not None
    assert "پذیرفته شد" in find(ctl, "import_result").value
    assert ai_engine.resolve_model_path(s0) == good
    fire(find(ctl, "catalog_back_btn"), "on_click")
    assert s0.model_file_path == ""
    assert find(ctl, "imported_card") is None and find(ctl, "model_card_qwen35-2b") is not None


def test_ai_setup_import_rejects_non_gguf_files(monkeypatch, s0, dl, tmp_path):
    patch_hw(monkeypatch)
    bad = tmp_path / "notes.txt"
    bad.write_bytes(b"hello")
    ctl = ai_setup.build(FakePage(), "fa", s0, lambda: None)
    find(ctl, "import_path_field").value = str(bad)
    fire(find(ctl, "import_apply_btn"), "on_click")
    assert s0.model_file_path == ""
    assert "قابلِ قبول نیست" in find(ctl, "import_result").value
    find(ctl, "import_path_field").value = ""
    fire(find(ctl, "import_apply_btn"), "on_click")
    assert "اول مسیر" in find(ctl, "import_result").value


# ---------------------------------------------------------------- پیشرفته + آزمایشِ مدل


def test_ai_setup_advanced_collapses_and_saves(monkeypatch, s0, dl):
    patch_hw(monkeypatch)
    ctl = ai_setup.build(FakePage(), "fa", s0, lambda: save_settings(s0))
    adv = find(ctl, "adv_area")
    assert adv.visible is False
    fire(find(ctl, "adv_toggle"), "on_click")
    assert adv.visible is True and find(ctl, "adv_ctx") is not None
    assert "خودکار" in find(ctl, "adv_ctx_note").value  # ۰ = خودکار، با عددِ پیشنهادیِ سخت‌افزار
    find(ctl, "adv_ctx").value = "4096"
    find(ctl, "adv_threads").value = "6"
    find(ctl, "adv_cap_chat").value = "50"
    find(ctl, "adv_cap_total").value = "500"
    fire(find(ctl, "adv_save"), "on_click")
    fresh = load_settings()
    assert (fresh.ai_context_tokens, fresh.ai_threads, fresh.max_ai_messages_per_chat_per_day,
            fresh.max_ai_messages_per_day_total) == (4096, 6, 50, 500)
    assert "ذخیره شد" in find(ctl, "adv_notice").value
    find(ctl, "adv_ctx").value = "abc"
    fire(find(ctl, "adv_save"), "on_click")
    assert "عددِ معتبر" in find(ctl, "adv_notice").value


def test_ai_setup_kill_switch_saved(monkeypatch, s0, dl):
    patch_hw(monkeypatch)
    ctl = ai_setup.build(FakePage(), "fa", s0, lambda: save_settings(s0))
    fire(find(ctl, "adv_toggle"), "on_click")
    find(ctl, "adv_kill").value = True
    fire(find(ctl, "adv_save"), "on_click")
    assert load_settings().ai_kill_switch is True


def test_ai_setup_self_test_reports_honestly_without_llama(monkeypatch, s0, dl):
    patch_hw(monkeypatch)
    page = FakePage()  # run_thread هم‌زمان ⇒ نتیجه در همون fire دیده می‌شه
    ctl = ai_setup.build(page, "fa", s0, lambda: None)
    fire(find(ctl, "ai_test_btn"), "on_click")
    out = find(ctl, "ai_test_result").value
    assert "خطا" in out and "llama" in out.lower()  # صادقانه می‌گه موتور اجرا نصب نیست

    class FakeEngine:
        def self_test(self):
            return True, "✅ مدل پاسخ داد: آماده‌ام"

        def unload(self):
            pass

    monkeypatch.setattr(ai_engine, "build_engine_from_settings", lambda st: FakeEngine())
    fire(find(ctl, "ai_test_btn"), "on_click")
    assert find(ctl, "ai_test_result").value.startswith("✅")


# ---------------------------------------------------------------- آنبوردینگ (ai_select)


def test_ai_select_model_choice_enables_next_and_reports(monkeypatch, s0, dl):
    hw = patch_hw(monkeypatch)
    rec = rec_for(hw)
    page = FakePage()
    nxt, back = [], []
    ctl = ai_select.build(page, "fa", s0, lambda: None, lambda: nxt.append(1), lambda: back.append(1))
    assert find(ctl, "next_button").disabled is True
    fire(find(ctl, f"model_card_{rec.id}"), "on_click")
    assert s0.model_id == rec.id
    assert find(ctl, "next_button").disabled is False
    fire(find(ctl, "next_button"), "on_click")
    assert nxt == [1]
    fire(find(ctl, "back_button"), "on_click")
    assert back == [1]


def test_ai_select_download_from_onboarding_and_skip(monkeypatch, s0, dl):
    hw = patch_hw(monkeypatch)
    rec = rec_for(hw)
    page = FakePage()
    nxt = []
    ctl = ai_select.build(page, "fa", s0, lambda: None, lambda: nxt.append(1), lambda: None)
    fire(find(ctl, f"dl_btn_{rec.id}"), "on_click")
    assert s0.model_id == rec.id and find(ctl, "next_button").disabled is False
    fire(find(ctl, "skip_button"), "on_click")
    assert nxt == [1]  # رویِ سیستم‌هایِ خیلی ضعیف می‌شه بدونِ مدل رد شد


def test_the_skip_button_uses_the_skip_route_not_the_next_one(monkeypatch, s0, dl):
    """«بعداً انتخاب میکنم» باید مسیرِ *ردکردن* را صدا بزند؛ اگر همان «بعدی» را بزند،
    مسیریابِ برنامه چون مدلی نیست دوباره همین گام را می‌سازد و کلیک بی‌معنی می‌ماند."""
    patch_hw(monkeypatch)
    page = FakePage()
    nxt, skipped = [], []
    ctl = ai_select.build(page, "fa", s0, lambda: None, lambda: nxt.append(1), lambda: None,
                          on_skip=lambda: skipped.append(1))
    assert not s0.model_id and not (s0.model_file_path or "")  # هنوز هیچ مدلی انتخاب نشده
    fire(find(ctl, "skip_button"), "on_click")
    assert skipped == [1] and nxt == []
    assert find(ctl, "next_button").disabled is True  # بدونِ مدل، «بعدی» قفله و فقط «بعداً» راه دارد


def test_ai_select_onboarding_has_no_api_fields(monkeypatch, s0, dl):
    patch_hw(monkeypatch)
    ctl = ai_select.build(FakePage(), "fa", s0, lambda: None, lambda: None, lambda: None)
    assert find(ctl, "api_fields") is None and find(ctl, "api_key_field") is None
    assert "کلید API" not in collect_text(ctl)
    assert find(ctl, "hw_card") is not None and find(ctl, "model_hub") is not None


# ---------------------------------------------------------------- مصرف (فقط محلی)


def build_usage(settings, store):
    manager = types.SimpleNamespace(usage=UsageStore(store))
    return usage.build(FakePage(), "fa", settings, manager)


def test_usage_page_has_no_money_words(monkeypatch, s0, dl, tmp_path):
    patch_hw(monkeypatch)
    store = ConversationStore(db_path=tmp_path / "c.db")
    UsageStore(store).record(provider_id="local", model="qwen3-4b", prompt_tokens=1500, completion_tokens=300,
                             latency_ms=2200, platform="telegram", chat_id="1")
    text = collect_text(build_usage(s0, store))
    for banned in ("$", "تومان", "دلار", "ریال", "هزینه", "بودجه", "نرخ", "ارائه‌دهنده"):
        assert banned not in text, banned
    ctl = build_usage(s0, store)
    assert find(ctl, "us_wi_calc") is None and find(ctl, "us_rate") is None and find(ctl, "us_budget") is None


def test_usage_page_shows_counts_latency_and_time_per_1k(monkeypatch, s0, dl, tmp_path):
    patch_hw(monkeypatch)
    store = ConversationStore(db_path=tmp_path / "c.db")
    rec = UsageStore(store)
    for _ in range(3):
        rec.record(provider_id="local", model="qwen3-4b", prompt_tokens=1000, completion_tokens=200, latency_ms=3000,
                   platform="telegram", chat_id="7", sys_tokens=100, hist_tokens=900, msg_tokens=30)
    ctl = build_usage(s0, store)
    assert "3 پاسخ · 3,600 توکن" in find(ctl, "us_today").content.controls[1].value
    assert find(ctl, "us_avg").value != "هنوز مصرفی ثبت نشده."
    text = collect_text(ctl)
    assert "هر ۱٬۰۰۰ توکن ≈ 2.5 ثانیه" in text  # ۳۰۰۰ms / ۱۲۰۰ توکن ⇒ تخمینِ زمان روی همین سیستم
    assert "telegram:7" in text  # پرمصرف‌ترین گفتگوها


def test_usage_page_caps_and_kill_switch_save(monkeypatch, s0, dl, tmp_path):
    patch_hw(monkeypatch)
    store = ConversationStore(db_path=tmp_path / "c.db")
    ctl = build_usage(s0, store)
    assert find(ctl, "us_avg").value == "هنوز مصرفی ثبت نشده."
    find(ctl, "us_cap_chat").value = "x"
    fire(find(ctl, "us_save"), "on_click")
    assert "عددِ معتبر" in find(ctl, "us_notice").value
    find(ctl, "us_cap_chat").value = "30"
    find(ctl, "us_cap_total").value = "300"
    find(ctl, "us_kill").value = True
    fire(find(ctl, "us_save"), "on_click")
    fresh = load_settings()
    assert (fresh.max_ai_messages_per_chat_per_day, fresh.max_ai_messages_per_day_total, fresh.ai_kill_switch) == (30, 300, True)
    assert find(ctl, "us_kill_banner").visible is True
    assert find(ctl, "us_caps_status").value.startswith("امروز")


# ---------------------------------------------------------------- انگلیسی


def test_english_pages_build(monkeypatch, s0, dl, tmp_path):
    patch_hw(monkeypatch)
    en = AppSettings(business_mode="store", language="en")
    assert "Local AI" in collect_text(ai_setup.build(FakePage(), "en", en, lambda: None))
    assert "Choose your local AI model" in collect_text(
        ai_select.build(FakePage(), "en", en, lambda: None, lambda: None, lambda: None))
    manager = types.SimpleNamespace(usage=UsageStore(ConversationStore(db_path=tmp_path / "c.db")))
    assert "AI usage" in collect_text(usage.build(FakePage(), "en", en, manager))


# ---------------------------------------------------------------- CUDA


def test_the_gpu_field_warns_when_layers_are_asked_without_a_cuda_build(monkeypatch, s0, dl):
    """ابهامِ CUDA تمام شود: با بیلدِ بدونِ CUDA، عددِ بالا هیچ اثری ندارد و صفحه باید همین را
    صریح بگوید تا کاربر حدس نزند."""
    patch_hw(monkeypatch)
    monkeypatch.setattr(ai_engine, "gpu_offload_available", lambda: False)
    s0.ai_gpu_layers = 99
    note = collect_text(find(ai_setup.build(FakePage(), "fa", s0, lambda: None), "adv_gpu_note"))
    assert "CUDA ندارد" in note


def test_the_gpu_field_is_quiet_when_the_build_supports_gpu(monkeypatch, s0, dl):
    patch_hw(monkeypatch)
    monkeypatch.setattr(ai_engine, "gpu_offload_available", lambda: True)
    s0.ai_gpu_layers = 99
    note = collect_text(find(ai_setup.build(FakePage(), "fa", s0, lambda: None), "adv_gpu_note"))
    assert note and "CUDA ندارد" not in note


def test_the_gpu_field_stays_neutral_at_zero_layers(monkeypatch, s0, dl):
    """با ۰ (پیش‌فرض) کاربر چیزی را درخواست نکرده، پس هشدارِ GPU لازم نیست."""
    patch_hw(monkeypatch)
    monkeypatch.setattr(ai_engine, "gpu_offload_available", lambda: False)
    s0.ai_gpu_layers = 0
    note = collect_text(find(ai_setup.build(FakePage(), "fa", s0, lambda: None), "adv_gpu_note"))
    assert "CUDA ندارد" not in note


def test_the_hardware_card_reports_the_build_answer_not_the_card_name(monkeypatch, s0, dl):
    """کارتِ NVIDIA به‌تنهایی وعده‌ی شتاب نیست؛ پاسخِ خودِ llama.cpp نشان داده می‌شه."""
    nvidia = hardware.HardwareInfo(ram_gb=16.0, cpu_cores=12, cpu_model="Test CPU X", gpu_model="NVIDIA GeForce RTX 4060",
                                   gpu_vram_gb=8.0, free_disk_gb=200.0)
    monkeypatch.setattr(hardware, "detect", lambda force=False, disk_path=None: nvidia)
    monkeypatch.setattr(hardware, "free_disk_gb_at", lambda path: 200.0)
    monkeypatch.setattr(ai_engine, "gpu_offload_available", lambda: False)
    cpu_build = collect_text(ai_select.build(FakePage(), "fa", s0, lambda: None, lambda: None, lambda: None))
    assert "CPU" in cpu_build and "GPU را می‌شناسه" not in cpu_build
    monkeypatch.setattr(ai_engine, "gpu_offload_available", lambda: True)
    cuda_build = collect_text(ai_select.build(FakePage(), "fa", s0, lambda: None, lambda: None, lambda: None))
    assert "GPU را می‌شناسه" in cuda_build


def test_the_gpu_warning_is_bilingual(monkeypatch, s0, dl):
    """همه‌ی متن‌هایِ کاربر دوزبانه‌اند؛ هشدارِ CUDA هم در انگلیسی دیده می‌شه."""
    patch_hw(monkeypatch)
    monkeypatch.setattr(ai_engine, "gpu_offload_available", lambda: False)
    en = AppSettings(business_mode="store", language="en", ai_gpu_layers=99)
    note = collect_text(find(ai_setup.build(FakePage(), "en", en, lambda: None), "adv_gpu_note"))
    assert "no CUDA" in note
