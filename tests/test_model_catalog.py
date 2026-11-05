"""کاتالوگِ مدل‌هایِ محلی — انتخابِ مدل بر پایه‌ی سخت‌افزار.

همه‌ی تست‌ها با ``HardwareInfoِ`` ساختگی کار می‌کنن: هیچ subprocess، هیچ psutil، هیچ اینترنتی.
"""

import pytest

from app.core import model_catalog as mc
from app.core.hardware import HardwareInfo

GIB = 1024**3


def hw(ram=None, cores=None, disk=None, gpu=""):
    return HardwareInfo(ram_gb=ram, cpu_cores=cores, gpu_model=gpu, free_disk_gb=disk)


# ------------------------------------------------------------------- خودِ کاتالوگ


def test_entries_are_complete_and_ids_unique():
    ids = [e.id for e in mc.entries()]
    assert len(ids) == len(set(ids)) == 6
    for e in mc.entries():
        assert len(e.sha256) == 64 and e.size_bytes > 0 and 0 < e.min_ram_gb < e.good_ram_gb
        assert e.label["fa"] and e.label["en"] and e.blurb["fa"] and e.blurb["en"]
        assert e.urls[0].startswith("https://huggingface.co/") and len(e.urls) >= 2  # منبعِ اصلی + آینه
        assert e.urls[0].endswith(e.filename)
        assert e.license == "apache-2.0"


def test_entries_returns_a_copy_so_callers_cannot_mutate_the_catalog():
    items = mc.entries()
    items.clear()
    assert mc.entries()  # کاتالوگِ اصلی دست‌نخورده


def test_get_entry_unknown_is_none_and_size_helpers_round():
    entry = mc.get_entry("qwen35-4b")
    assert entry is not None and entry.params == "4B"
    assert mc.get_entry("gpt-4o-mini") is None and mc.get_entry("") is None
    assert entry.size_gb == round(entry.size_bytes / GIB, 2)
    # وزن + ~۲۵٪ سربار + ۰٫۸ گیگ زمینه
    assert entry.weight_ram_gb() == pytest.approx(entry.size_bytes / GIB * 1.25 + 0.8, abs=0.06)


# --------------------------------------------------------------- رمِ قابل‌استفاده


def test_available_ram_is_conservative():
    assert mc.available_ram_gb(hw(ram=16)) == 13.6  # ۸۵٪ — «جا می‌شه» دروغ نگو
    assert mc.available_ram_gb(hw(ram=8)) == 6.8
    assert mc.available_ram_gb(hw(ram=None)) == 0.0 and mc.available_ram_gb(hw(ram=0)) == 0.0


def test_free_disk_need_is_size_plus_one_gig_margin():
    entry = mc.get_entry("qwen35-2b")
    assert mc.free_disk_ok(hw(disk=20), entry) is True
    assert mc.free_disk_ok(hw(disk=entry.size_gb), entry) is False  # دقیقاً اندازه‌ی فایل کافی نیست
    assert mc.free_disk_ok(hw(disk=round(entry.size_gb + 1.1, 1)), entry) is True
    assert mc.free_disk_ok(hw(disk=None), entry) is True  # نمی‌دونیم ⇒ مانع نمی‌شیم
    assert mc.free_disk_ok(hw(disk=1), entry, path_free_gb=50) is True  # مسیرِ واقعی مهم‌تر از کشِ سیستم


# -------------------------------------------------------------------- وضعیتِ برازش


def test_fit_state_buckets():
    entry = mc.get_entry("qwen35-4b")  # min 6.5 / good 10
    assert mc.fit_state(hw(ram=24), entry) == "recommended"  # ۲۰٫۴ رمِ قابل‌استفاده
    assert mc.fit_state(hw(ram=12), entry) == "ok"  # ۱۰٫۲: بهِ good رسیده ولی از ۱۱۵٪ کمتر
    assert mc.fit_state(hw(ram=8), entry) == "tight"  # ۶٫۸: بینِ min و good
    assert mc.fit_state(hw(ram=4), entry) == "no"  # ۳٫۴: زیرِ min
    assert mc.fit_state(hw(ram=24), entry, path_free_gb=0.5) == "no"  # دیسک کم ⇒ هر رمی فایده ندارد


def test_fit_state_without_detected_ram_only_trusts_light_models():
    small, big = mc.get_entry("qwen35-2b"), mc.get_entry("qwen35-9b")
    assert mc.fit_state(hw(ram=None), small) == "ok"  # ≤۲ گیگ: «شاید جا شه»
    assert mc.fit_state(hw(ram=None), big) == "tight"  # سنگین: هرگز ادعایِ راحتِ‌جا‌شدن نمی‌کنیم


def test_ranked_for_is_best_first_and_marks_every_state():
    ranked = mc.ranked_for(hw(ram=16), path_free_gb=100)
    assert {e.id for e, _s in ranked} == {e.id for e in mc.entries()}  # هیچ مدلی حذف نمی‌شه
    order = {"recommended": 0, "ok": 1, "tight": 2, "no": 3}
    states = [order[s] for _e, s in ranked]
    assert states == sorted(states) and all(s in order for _e, s in ranked)
    # در یک رده، باکیفیت‌تر جلو می‌آید
    assert ranked[0][1] == "recommended" and max(e.quality for e, s in ranked if s == "recommended") == ranked[0][0].quality


def test_recommend_picks_comfortable_quality_then_the_smallest_tight_option():
    assert mc.recommend(hw(ram=32, disk=60)).id == "qwen35-9b"  # رمِ زیاد ⇒ بهترینِ کیفیت
    assert mc.recommend(hw(ram=16, disk=60)).id in {"qwen35-4b", "qwen3-4b-instruct", "qwen25-7b"}
    assert mc.recommend(hw(ram=8, disk=20)).id == "qwen35-2b"  # فقط «ok» این مدل است
    # سیستمِ ۶ گیگ: گزینه‌هایِ تنگ هستن ⇒ کم‌حجم‌ترینِ جا‌شونده، نه سنگین‌ترین
    assert mc.recommend(hw(ram=6.5, disk=20)).id == "qwen35-2b"
    assert mc.recommend(hw(ram=4, disk=20)) is None  # هیچ‌کدام جا نمی‌شن
    assert mc.recommend(hw(ram=32, disk=2)) is None  # رمِ عالی، دیسکِ نمی‌خوره
    # رمِ نامعلوم ⇒ هر مدلِ ≤۲ گیگ «جا می‌شه» و کیفیّت‌ترینشان پیشنهاد می‌شه (نه مدلِ سنگین)
    assert mc.recommend(hw(ram=None, disk=20)).id in {"qwen35-2b", "qwen25-3b"}
    assert mc.get_entry(mc.recommend(hw(ram=None, disk=20)).id).size_bytes <= 2 * 1024**3


def test_reason_for_returns_only_known_i18n_keys():
    big, small = mc.get_entry("qwen35-9b"), mc.get_entry("qwen35-2b")
    assert mc.reason_for(hw(ram=32), big) == "ai.local.rec_recommended"
    assert mc.reason_for(hw(ram=16), big) == "ai.local.rec_tight"  # ۱۳٫۶: بینِ min و good
    assert mc.reason_for(hw(ram=19), big) == "ai.local.rec_ok"  # ۱۶٫۱: بهِ good رسیده ولی نه ۱۱۵٪
    assert mc.reason_for(hw(ram=8), big) == "ai.local.rec_no_ram"
    assert mc.reason_for(hw(ram=32, disk=1), big) == "ai.local.rec_no_disk"
    assert mc.reason_for(hw(ram=32), small) == "ai.local.rec_recommended"
    known = {
        "ai.local.rec_recommended", "ai.local.rec_ok", "ai.local.rec_tight",
        "ai.local.rec_no_disk", "ai.local.rec_no_ram",
    }
    machine = hw(ram=10, disk=30)
    assert {mc.reason_for(machine, e, path_free_gb=30) for e in mc.entries()} <= known


def test_gpu_note_is_honest_about_cpu_only_builds():
    assert mc.gpu_acceleration_note(hw(gpu="")) == "ai.local.gpu_note_none"
    assert mc.gpu_acceleration_note(hw(gpu="NVIDIA GeForce RTX 4060")) == "ai.local.gpu_note_nvidia"
    assert mc.gpu_acceleration_note(hw(gpu="NVIDIA T4")) == "ai.local.gpu_note_nvidia"
    assert mc.gpu_acceleration_note(hw(gpu="Intel Iris Xe")) == "ai.local.gpu_note_other"


# ------------------------------------------------------------ اندازه‌هایِ خودکار


def test_auto_context_tokens_grows_with_free_ram_and_stays_clamped():
    entry = mc.get_entry("qwen35-4b")
    tiny = mc.auto_context_tokens(hw(ram=4), entry)
    mid = mc.auto_context_tokens(hw(ram=16), entry)
    huge = mc.auto_context_tokens(hw(ram=128), entry)
    assert tiny == 2048 and mid > tiny and huge == 8192  # هرگز آن‌قدر بزرگ که سیستم قفل کنه
    assert mid % 1024 == 0
    # رمِ نامعلوم ⇒ به good_ramِ خودِ مدل اعتماد می‌کنیم، نه صفر
    assert mc.auto_context_tokens(hw(ram=None), entry) >= 2048


def test_auto_context_is_smaller_for_heavier_models_on_the_same_machine():
    machine = hw(ram=16)
    assert mc.auto_context_tokens(machine, mc.get_entry("qwen35-9b")) <= mc.auto_context_tokens(
        machine, mc.get_entry("qwen35-2b")
    )


def test_auto_threads_leaves_windows_a_core_but_never_goes_below_two():
    assert mc.auto_threads(hw(cores=8)) == 7
    assert mc.auto_threads(hw(cores=2)) == 2
    assert mc.auto_threads(hw(cores=1)) == 2
    assert mc.auto_threads(hw(cores=None)) == 0 and mc.auto_threads(hw(cores=0)) == 0  # تصمیمِ llama.cpp


# --------------------------------------------------------- آزمونِ سازگاریِ کلی


def test_every_entry_is_recommended_somewhere_and_no_entry_is_impossible():
    # یک سیستمِ غول‌پیکر باید همه‌ی مدل‌ها را «recommended» ببینه (حداقل از نظرِ رم)
    monster = hw(ram=128, cores=32, disk=2000)
    assert {mc.fit_state(monster, e) for e in mc.entries()} == {"recommended"}
    # و یک سیستمِ ۳۲ گیگی هیچ مدلی را «no» نمی‌بیند
    assert "no" not in {s for _e, s in mc.ranked_for(hw(ram=32), path_free_gb=100)}


def test_no_api_or_tier_left_in_the_catalog_surface():
    """نسخه‌ی ۱.۰.۰ فقط مدلِ محلی دارد: TIERS/get_tier/recommend_tier_id و هیچ متنِ «API» نیست."""
    for gone in ("TIERS", "get_tier", "recommend_tier_id", "API", "api_key"):
        assert not hasattr(mc, gone), gone
    for entry in mc.entries():
        blob = repr(entry)
        assert "api.openai" not in blob and "sk-" not in blob
