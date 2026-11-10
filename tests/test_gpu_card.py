"""قلم ۲ِ باگ‌هایِ تازه: کارتِ «شتابِ گرافیکی» در همان یک نصب.

صفحه هیچ عددی را خودش نمی‌سازد: وضعیت، اندازه‌ها و نتیجه را از ``gpu_pack`` می‌خواند (اینجا
با FakePack جایِ آن گذاشته می‌شود)، و هیچ‌وقت وانمود نمی‌کند GPU فعال شده است.
"""

from dataclasses import dataclass, field

import pytest
from fake_page import FakePage, collect_text, find, fire

from app.core import gpu_pack
from app.core.settings import AppSettings
from app.screens import bot_experience, gpu_card


def status(**kw):
    base = dict(cuda="cu12.4", state=gpu_pack.STATE_ABSENT, windows=True, supported=True, has_nvidia=True,
                gpu_model="NVIDIA GeForce RTX 3060", gpu_vram_gb=12.0, enabled=True)
    base.update(kw)
    return gpu_pack.PackStatus(**base)


@dataclass
class FakePack:
    st: gpu_pack.PackStatus = None
    result: gpu_pack.InstallResult = None
    error: str = ""
    uninstall_result: tuple = (True, "پاک شد")
    calls: list = field(default_factory=list)

    STATE_INSTALLED = gpu_pack.STATE_INSTALLED
    STATE_PARTIAL = gpu_pack.STATE_PARTIAL
    GpuPackError = gpu_pack.GpuPackError

    def status(self, settings=None, cuda="", hw=None):
        self.calls.append(("status",))
        return self.st

    def target_keys(self):
        return ("cu12.4", "cu13.5")

    def describe_sizes(self, cuda=""):
        self.calls.append(("sizes", cuda))
        return [("llama-bin.zip", 289.0), ("cudart.zip", 391.4)]

    def install(self, settings=None, cuda="", progress_cb=None, cancel_cb=None, hw=None, verify=True):
        self.calls.append(("install", cuda, bool(cancel_cb())))
        if self.error:
            raise self.GpuPackError(self.error)
        if progress_cb:
            progress_cb(1, 2)
        return self.result

    def uninstall(self, cuda="", settings=None, keep_cache=False):
        self.calls.append(("uninstall", cuda))
        return self.uninstall_result


def rig(st=None, result=None, error=""):
    page = FakePage()
    settings = AppSettings()
    pack = FakePack(st=st or status(), result=result or gpu_pack.InstallResult(ok=True, state=gpu_pack.STATE_INSTALLED,
                                                                              verified="gpu"), error=error)
    saves = []
    card = gpu_card.build(page, "fa", settings, lambda: saves.append(True), pack=pack)
    return page, settings, pack, card, saves


def note_of(page, card):
    n = find(card, "gpu_note")
    return (n.value or "") if n.visible else ""


# ─────────────────────────────────── وضعیت‌ها ───────────────────────────────────


def test_absent_pack_offers_install_and_shows_the_measured_sizes():
    _page, _s, pack, card, _saves = rig()
    assert find(card, "gpu_install").visible is True
    assert find(card, "gpu_uninstall").visible is False
    text = collect_text(card)
    assert "۰" not in text.split("حجمِ دانلود")[1][:6]  # عددِ ساختگی نیست
    assert "289.0" in text and "391.4" in text and "680.4" in text, text[:300]
    assert "RTX 3060" in text and "12 گیگابایت" in text
    assert "نصب نشده" in find(card, "gpu_state").value


def test_a_machine_without_nvidia_is_told_the_truth_and_gets_no_buttons():
    page, _s, _pack, card, _saves = rig(st=status(has_nvidia=False, gpu_model="", gpu_vram_gb=None))
    assert find(card, "gpu_install").visible is False
    assert "NVIDIA پیدا نشد" in find(card, "gpu_state").value
    assert find(card, "gpu_sizes").visible is False


def test_a_non_windows_or_unsupported_machine_says_so():
    _p, _s, _pack, card, _s = rig(st=status(windows=False))
    assert "فقط روی ویندوز" in find(card, "gpu_state").value


def test_partial_download_is_reported_as_resumable_not_broken():
    _p, _s, _pack, card, _s = rig(st=status(state=gpu_pack.STATE_PARTIAL, download_bytes=1234, files=("a.zip",)))
    assert find(card, "gpu_install").content == "ادامهٔ نصب"
    assert "۱ فایل" in find(card, "gpu_state").value or "1 فایل" in find(card, "gpu_state").value


def test_active_pack_is_named_and_install_disappears():
    _p, _s, _pack, card, _s = rig(st=status(state=gpu_pack.STATE_INSTALLED, verified="gpu"))
    assert find(card, "gpu_install").visible is False and find(card, "gpu_uninstall").visible is True
    assert "روی NVIDIA GeForce RTX 3060 محاسبه" in find(card, "gpu_state").value


def test_installed_but_rejected_by_the_engine_is_a_warning_not_a_success():
    _p, _s, _pack, card, _s = rig(st=status(state=gpu_pack.STATE_INSTALLED, verified="cpu"))
    assert "به CPU برگشت" in find(card, "gpu_state").value
    assert find(card, "gpu_install").visible is True  # هنوز می‌تواند دوباره تلاش کند


# ─────────────────────────────────── اقدام‌ها ───────────────────────────────────


def test_install_persists_the_cuda_choice_and_reports_the_restart_rule():
    page, settings, pack, card, saves = rig(result=gpu_pack.InstallResult(ok=True, state=gpu_pack.STATE_INSTALLED,
                                                                         verified="gpu", restart_needed=True))
    find(card, "gpu_cuda").value = "cu13.5"
    fire(find(card, "gpu_install"), "on_click")
    assert settings.gpu_pack_cuda == "cu13.5" and saves == [1]
    assert ("install", "cu13.5", False) in pack.calls
    assert "ببند و دوباره باز کن" in note_of(page, card)


def test_install_without_restart_is_reported_plainly():
    page, _s, _pack, card, _saves = rig(result=gpu_pack.InstallResult(ok=True, state=gpu_pack.STATE_INSTALLED, verified="gpu"))
    fire(find(card, "gpu_install"), "on_click")
    assert note_of(page, card) == "ذخیره شد."


def test_a_rollback_after_a_failed_probe_is_shown_as_a_failure():
    page, _s, _pack, card, _saves = rig(result=gpu_pack.InstallResult(ok=False, state=gpu_pack.STATE_ABSENT, verified="cpu",
                                                                     rolled_back=True, detail="بیلد GPU را نشناخت"))
    fire(find(card, "gpu_install"), "on_click")
    note = note_of(page, card)
    assert "به CPU برگشت" in note and "بیلد GPU را نشناخت" in note


def test_a_hard_refusal_is_shown_without_any_pretence():
    page, _s, pack, card, _saves = rig(error="کارتِ NVIDIA نداریم")
    fire(find(card, "gpu_install"), "on_click")
    assert note_of(page, card) == "کارتِ NVIDIA نداریم"
    assert find(card, "gpu_progress").visible is False


def test_cancel_is_passed_down_and_reported_as_cancelled():
    page, _s, pack, card, _saves = rig(result=gpu_pack.InstallResult(ok=False, state=gpu_pack.STATE_PARTIAL, cancelled=True))
    fire(find(card, "gpu_install"), "on_click")
    assert "لغو شد" in note_of(page, card)
    fire(find(card, "gpu_cancel"), "on_click")  # لغوِ دستی قبل از شروعِ دوباره، بی‌خطا
    assert "در حالِ دانلود" in note_of(page, card)


def test_a_second_click_while_a_download_is_running_is_ignored():
    """FakePage ترد را هم‌زمان اجرا می‌کند، پس می‌شود از *داخلِ* install دوباره دکمه را زد:
    اگر نگهبانِ busy نبود، دو دانلودِ هم‌زمان روی یک فایلِ .part می‌افتاد."""
    seen = {"installs": 0}

    class Reentrant(FakePack):
        def install(self, settings=None, cuda="", progress_cb=None, cancel_cb=None, hw=None, verify=True):
            seen["installs"] += 1
            fire(page_ref[0] and btn_ref[0], "on_click")  # همان کلیکِ دوم، وسطِ کار
            return gpu_pack.InstallResult(ok=True, state=gpu_pack.STATE_INSTALLED, verified="gpu")

    page, settings, _p, card, _saves = rig()
    pack = Reentrant(st=status(), result=None)
    page2 = FakePage()
    card2 = gpu_card.build(page2, "fa", settings, lambda: None, pack=pack)
    page_ref, btn_ref = [page2], [find(card2, "gpu_install")]
    fire(btn_ref[0], "on_click")
    assert seen["installs"] == 1, "کلیکِ دوم وسطِ کار نباید دانلودِ تازه شروع کند"


def test_uninstall_reports_what_the_module_said():
    page, _s, pack, card, _saves = rig(st=status(state=gpu_pack.STATE_INSTALLED, verified="gpu"))
    pack.uninstall_result = (True, "پاک شد")
    fire(find(card, "gpu_uninstall"), "on_click")
    assert "بسته برداشته شد" in note_of(page, card)
    assert ("uninstall", "cu12.4") in pack.calls


def test_enabled_switch_persists_immediately():
    _page, settings, _pack, card, saves = rig()
    sw = find(card, "gpu_enabled")
    sw.value = False
    fire(sw, "on_change")
    assert settings.gpu_pack_enabled is False and saves == [1]


# ─────────────────────────────── جایگیریِ کارت در برنامه ───────────────────────────────


def test_the_card_lives_in_the_advanced_tab_of_bot_experience(tmp_path):
    page = FakePage()
    settings = AppSettings()
    card = bot_experience.build(page, "fa", settings, lambda: None, None, None)
    assert find(card, "gpu_card") is not None
    assert find(card, "gpu_install") is not None
    assert "پردازنده" in collect_text(find(card, "perf_gpu"))  # خطِ صادقِ تبِ سرعت و هزینه سرِ جایش است


def test_gpu_pack_pinned_sizes_are_the_measured_ones():
    """عددِ وعده‌داده‌شده در UI باید همان اندازهٔ سنجیده‌شدهٔ فایلِ انتشار باشد."""
    sizes = dict(gpu_pack.describe_sizes("cu12.4"))
    assert round(sum(sizes.values()), 1) == 680.4
    assert all(mb > 0 for mb in sizes.values())
    for part in gpu_pack.get_target("cu12.4").parts:
        assert part.sha256 and len(part.sha256) == 64 and part.size_bytes > 10_000_000
        assert part.url.startswith("https://github.com/ggml-org/llama.cpp/releases/download/")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
