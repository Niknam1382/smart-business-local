"""تست صفحه‌های آنبوردینگ بعد از بازطراحی بصری — با Page جعلی، بدون مرورگر واقعی."""

import pytest
from fake_page import FakePage, collect_text, find, fire

from app.core import ai_engine, downloader, hardware, model_catalog
from app.core.settings import AppSettings
from app.screens import ai_select, mode_select, welcome


def test_welcome_build_and_submit_name(tmp_path):
    page = FakePage()
    captured = []
    control = welcome.build(page, "fa", "", lambda name: captured.append(name))
    field = find(control, "name_field")
    assert field is not None
    fire(field, "on_submit", value="  محمد مهدی  ")
    assert captured == ["محمد مهدی"]


def test_welcome_empty_name_shows_error_and_does_not_advance(tmp_path):
    page = FakePage()
    captured = []
    control = welcome.build(page, "fa", "", lambda name: captured.append(name))
    field = find(control, "name_field")
    fire(field, "on_submit", value="   ")
    assert captured == []
    assert page.update_count >= 1


def test_welcome_builds_in_english(tmp_path):
    page = FakePage()
    control = welcome.build(page, "en", "Sara", lambda name: None)
    field = find(control, "name_field")
    assert field.value == "Sara"


def test_mode_select_choose_enables_next_and_reports_choice(tmp_path):
    page = FakePage()
    chosen = []
    control = mode_select.build(page, "fa", None, lambda mode: chosen.append(mode), lambda: None)
    next_btn = find(control, "next_button")
    assert next_btn.disabled is True

    fire(find(control, "mode_card_store"), "on_click")
    assert find(control, "next_button").disabled is False
    fire(find(control, "next_button"), "on_click")
    assert chosen == ["store"]


def test_mode_select_back_button(tmp_path):
    page = FakePage()
    back_calls = []
    control = mode_select.build(page, "fa", "store", lambda mode: None, lambda: back_calls.append(1))
    fire(find(control, "back_button"), "on_click")
    assert back_calls == [1]


def test_mode_select_preselected_enables_next_immediately(tmp_path):
    page = FakePage()
    control = mode_select.build(page, "fa", "consultant", lambda mode: None, lambda: None)
    assert find(control, "next_button").disabled is False


def test_mode_select_switching_choice_updates_selection(tmp_path):
    page = FakePage()
    chosen = []
    control = mode_select.build(page, "fa", "store", lambda mode: chosen.append(mode), lambda: None)
    fire(find(control, "mode_card_consultant"), "on_click")
    fire(find(control, "next_button"), "on_click")
    assert chosen == ["consultant"]


def _hidden_descendants(control) -> list:
    """هر فرزندِ نامرئی داخلِ یک کارتِ مرئی (= همان «کادرِ خالیِ اضافه»ای که کاربر می‌دید)."""
    bad = []
    for child in [getattr(control, "content", None), *(getattr(control, "controls", None) or [])]:
        if child is None or isinstance(child, str):
            continue
        if getattr(child, "visible", True) is False:
            bad.append(child)
        bad += _hidden_descendants(child)
    return bad


@pytest.fixture(autouse=True)
def _local_only_env(monkeypatch):
    """سخت‌افزارِ ثابت + موتورِ بی‌نیاز از llama + دانلودرِ بی‌شبکه (همان الگوی test_ai_screens)."""
    hw = hardware.HardwareInfo(ram_gb=16.0, cpu_cores=12, cpu_model="Test CPU", gpu_model="", gpu_vram_gb=None, free_disk_gb=200.0)
    monkeypatch.setattr(hardware, "detect", lambda force=False, disk_path=None: hw)
    monkeypatch.setattr(hardware, "free_disk_gb_at", lambda path: 200.0)
    monkeypatch.setattr(ai_engine, "_llama_available", lambda: False)
    monkeypatch.setattr(downloader, "is_downloaded",
                        lambda path, expected_size=0: path.is_file() and path.read_bytes()[:4] == b"GGUF")


def _select_page():
    return AppSettings(business_mode="store", user_name="آزمون")


def test_ai_select_goes_straight_to_model_choice_no_api_toggle():
    """نسخه‌ی ۱.۰.۰: آنبوردینگ بدونِ سوالِ API/محلی — مستقیم فهرستِ مدل‌ها."""
    ctl = ai_select.build(FakePage(), "fa", _select_page(), lambda: None, lambda: None, lambda: None)
    assert find(ctl, "api_fields") is None and find(ctl, "ai_card_api") is None and find(ctl, "ai_card_local") is None
    assert "کلید API" not in collect_text(ctl)
    rec = model_catalog.recommend(hardware.detect(), path_free_gb=200.0)
    assert find(ctl, f"model_card_{rec.id}") is not None
    assert find(ctl, f"dl_btn_{rec.id}") is not None and find(ctl, "hw_card") is not None


def test_ai_select_visible_cards_are_never_empty_shells():
    """رگرسیونِ باگِ Flet: هیچ کنترلِ نامرئیِ تودرتو نباید داخلِ کارتِ مرئی باشه (کادرِ خالی)."""
    s = _select_page()
    ctl = ai_select.build(FakePage(), "fa", s, lambda: None, lambda: None, lambda: None)
    for key in ("hw_card", "model_hub"):
        node = find(ctl, key)
        assert node is not None and _hidden_descendants(node) == [], key


def test_ai_select_preselecting_model_enables_next_immediately():
    s = _select_page()
    s.model_id = "qwen35-4b"
    ctl = ai_select.build(FakePage(), "fa", s, lambda: None, lambda: None, lambda: None)
    assert find(ctl, "next_button").disabled is False


def test_ai_select_back_button(tmp_path):
    page = FakePage()
    back_calls = []
    ctl = ai_select.build(page, "fa", _select_page(), lambda: None, lambda: None, lambda: back_calls.append(1))
    fire(find(ctl, "back_button"), "on_click")
    assert back_calls == [1]
