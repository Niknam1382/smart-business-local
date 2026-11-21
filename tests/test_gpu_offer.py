"""۱٫۲٫۰ — پیشنهادِ خودکارِ شتابِ گرافیکی: فقط با کارتِ NVIDIA، فقط یک‌بار، و بدونِ اجازه‌ی صریح چیزی دانلود نمی‌شود."""

from types import SimpleNamespace

from app.screens import gpu_offer


def status(**kw):
    base = dict(windows=True, supported=True, has_nvidia=True, active=False, installed=False, gpu_model="RTX 3050", gpu_vram_gb=4)
    base.update(kw)
    return SimpleNamespace(**base)


def settings(**kw):
    base = dict(gpu_pack_enabled=True, gpu_offer_dismissed=False, model_id="qwen35-2b", model_file_path="", gpu_pack_cuda="")
    base.update(kw)
    return SimpleNamespace(**base)


class FakePack:
    def __init__(self, st):
        self.st = st
        self.installed_calls = 0

    def status(self, settings=None):
        return self.st

    def describe_sizes(self, cuda=""):
        return [("cudart", 288.9), ("llama", 391.4)]

    def install(self, **kw):
        self.installed_calls += 1


class Page:
    def __init__(self):
        self.overlay = []
        self.updates = 0

    def update(self):
        self.updates += 1

    def run_thread(self, fn):
        pass


def setup_function(_fn=None):
    gpu_offer._OFFERED["done"] = False  # noqa: SLF001


def test_offer_only_when_it_actually_helps():
    ok = gpu_offer.should_offer
    assert ok(settings(), status()) is True
    assert ok(settings(), status(has_nvidia=False)) is False  # بدونِ کارت: هیچ‌چیز
    assert ok(settings(), status(windows=False)) is False
    assert ok(settings(), status(active=True)) is False and ok(settings(), status(installed=True)) is False
    assert ok(settings(gpu_pack_enabled=False), status()) is False
    assert ok(settings(gpu_offer_dismissed=True), status()) is False  # «دیگر نپرس»
    assert ok(settings(model_id="", model_file_path=""), status()) is False  # هنوز مدلِ محلی انتخاب نشده


def test_dialog_is_shown_once_and_nothing_is_downloaded_without_consent(monkeypatch):
    monkeypatch.delenv("SMART_BUSINESS_NO_GPU_OFFER", raising=False)
    gpu_offer._OFFERED["done"] = False  # noqa: SLF001
    page, pack = Page(), FakePack(status())
    assert gpu_offer.maybe_offer(page, "fa", settings(), lambda: None, pack=pack) is True
    assert page.overlay and pack.installed_calls == 0  # فقط پرسش؛ دانلودی شروع نشده
    assert gpu_offer.maybe_offer(Page(), "fa", settings(), lambda: None, pack=pack) is False  # همان اجرا: دوباره نه


def test_a_broken_pack_never_breaks_the_app(monkeypatch):
    monkeypatch.delenv("SMART_BUSINESS_NO_GPU_OFFER", raising=False)
    gpu_offer._OFFERED["done"] = False  # noqa: SLF001

    class Broken(FakePack):
        def status(self, settings=None):
            raise RuntimeError("probe failed")

    assert gpu_offer.maybe_offer(Page(), "fa", settings(), lambda: None, pack=Broken(status())) is False


def test_the_offer_is_silent_when_the_test_switch_is_on(monkeypatch):
    monkeypatch.setenv("SMART_BUSINESS_NO_GPU_OFFER", "1")
    gpu_offer._OFFERED["done"] = False  # noqa: SLF001
    assert gpu_offer.maybe_offer(Page(), "fa", settings(), lambda: None, pack=FakePack(status())) is False
