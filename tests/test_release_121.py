"""۱.۲.۱ — دانلودِ چندمنبعه + پشتیبانِ curl، نقاشیِ روی حلقه‌یِ رابط، رنگ‌ها، نصب‌کننده و متن‌هایِ ساده."""

import hashlib
import re
from pathlib import Path

import pytest
from fake_page import FakePage

from app import i18n, theme
from app.core import bot_profile, downloader as dl
from app.screens import common

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
BLOB = b"GGUF" + bytes(range(256)) * 40


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ------------------------------------------------------------------ دانلود

class FakeProc:
    def __init__(self, code=0, on_start=None):
        self.returncode = code
        self._polls = 0
        if on_start:
            on_start()

    def poll(self):
        self._polls += 1
        return self.returncode if self._polls > 1 else None

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


def _patch_curl(monkeypatch, code=0, payload=BLOB):
    monkeypatch.setattr(dl, "_curl_path", lambda: "curl.exe")
    monkeypatch.setattr(dl.time, "sleep", lambda s: None)
    calls = []

    def fake_popen(command, **kw):
        calls.append(command)
        out = Path(command[command.index("-o") + 1])
        return FakeProc(code, on_start=(lambda: out.write_bytes(payload)) if code == 0 else None)

    monkeypatch.setattr(dl.subprocess, "Popen", fake_popen)
    return calls


DEAD = "https://localhost:1/models/m.gguf"


def test_curl_backup_downloads_when_the_main_method_fails(tmp_path, monkeypatch):
    calls = _patch_curl(monkeypatch)
    dest = tmp_path / "m.gguf"
    out = dl.download([DEAD], dest, expected_sha256=hashlib.sha256(BLOB).hexdigest(), timeout=1.0, use_curl_fallback=True)
    assert out == dest and dest.read_bytes() == BLOB
    assert "--proto" in calls[0] and "=https" in calls[0] and "-C" in calls[0]
    assert not dest.with_name(dest.name + ".part").exists()


def test_curl_backup_still_requires_the_pinned_hash(tmp_path, monkeypatch):
    _patch_curl(monkeypatch)
    dest = tmp_path / "m.gguf"
    with pytest.raises(dl.IntegrityError):
        dl.download([DEAD], dest, expected_sha256="0" * 64, timeout=1.0, use_curl_fallback=True)
    assert not dest.exists()


def test_curl_is_not_used_without_the_flag_or_without_a_hash(tmp_path, monkeypatch):
    calls = _patch_curl(monkeypatch)
    with pytest.raises(dl.DownloadError, match="هیچ منبعی"):
        dl.download([DEAD], tmp_path / "a.gguf", expected_sha256=hashlib.sha256(BLOB).hexdigest(), timeout=1.0)
    with pytest.raises(dl.DownloadError, match="هیچ منبعی"):
        dl.download([DEAD], tmp_path / "b.gguf", expected_sha256="", timeout=1.0, use_curl_fallback=True)
    assert calls == []


def test_curl_failure_is_named_in_the_final_message(tmp_path, monkeypatch):
    _patch_curl(monkeypatch, code=60)
    with pytest.raises(dl.DownloadError) as caught:
        dl.download([DEAD], tmp_path / "m.gguf", expected_sha256=hashlib.sha256(BLOB).hexdigest(), timeout=1.0, use_curl_fallback=True)
    text = str(caught.value)
    assert "curl" in text and "گواهی" in text and "localhost" in text
    assert "VPN" in text and "وارد کردن فایلِ مدل" in text


def test_curl_only_on_windows(monkeypatch):
    monkeypatch.setattr(dl.sys, "platform", "linux")
    assert dl._curl_path() is None  # noqa: SLF001


def test_curl_refuses_plain_http(tmp_path):
    with pytest.raises(dl.DownloadError, match="https"):
        dl._download_with_curl("curl", "http://x.example/a.gguf", tmp_path / "a", tmp_path / "a.part", "0" * 64, 0, None, None, 1.0)  # noqa: SLF001


def test_failure_text_lists_each_source_and_next_step():
    text = dl.failure_text(["huggingface.co: timeout", "hf-mirror.com: 403"])
    assert "huggingface.co" in text and "hf-mirror.com" in text and "اتصال اینترنت" in text


# ------------------------------------------------------------------ نقاشی روی حلقه‌یِ رابط

class LoopPage(FakePage):
    def __init__(self):
        super().__init__()
        self.tasks = []

    def run_task(self, coro_fn, *a, **k):
        self.tasks.append(coro_fn)


def test_run_on_ui_swallows_paint_errors_instead_of_killing_the_worker():
    page = FakePage()
    common.run_on_ui(page, lambda: 1 / 0)  # نباید پرتاب شود


@pytest.mark.parametrize("name", ["ai_setup", "about", "ai_select", "gpu_card", "gpu_offer", "orders", "products", "broadcast", "data_safety"])
def test_background_screens_paint_through_run_on_ui(name):
    assert "run_on_ui" in _read(APP / "screens" / f"{name}.py")


def test_ticker_and_live_refresher_paint_on_the_ui_loop():
    assert "run_on_ui(page, paint)" in _read(APP / "screens" / "common.py")
    assert "run_on_ui(self._page, self._run_tick)" in _read(APP / "screens" / "live.py")


# ------------------------------------------------------------------ رنگ‌ها

def test_no_handwritten_alpha_colors_outside_the_theme():
    bad = []
    pat = re.compile(r'#[0-9A-Fa-f]{8}\b|f"\{[^}]*\}[0-9A-Fa-f]{2}"')
    for path in APP.rglob("*.py"):
        if path.name in ("theme.py", "invoice_pdf.py"):
            continue
        for number, line in enumerate(_read(path).splitlines(), 1):
            if pat.search(line):
                bad.append(f"{path.name}:{number}")
    assert not bad, f"از theme.alpha استفاده کن: {bad}"


def test_alpha_puts_the_alpha_first():
    assert theme.alpha("#4F46E5", 0x14) == "#144F46E5"
    assert theme.alpha("#FFFFFF", 1.0) == "#FFFFFFFF"


# ------------------------------------------------------------------ بیوِ ربات

def test_bio_credit_is_the_repo_link_only():
    for lang in ("fa", "en"):
        credit = bot_profile.credit(lang)
        assert "github.com/Niknam1382/smart-business-local" in credit
        assert credit.count("github.com") == 1 and "niknam1382/" not in credit
        assert bot_profile.seller_limit(lang) >= 40


# ------------------------------------------------------------------ نصب‌کننده و داده

def test_installer_never_deletes_user_data_on_install_or_uninstall():
    iss = _read(ROOT / "installer" / "SmartBusinessLocal.iss")
    assert "[InstallDelete]" not in iss
    section = iss.split("[UninstallDelete]", 1)[1].split("[", 1)[0] if "[UninstallDelete]" in iss else ""
    assert not [ln for ln in section.splitlines() if ln.strip() and not ln.strip().startswith(";")]


# ------------------------------------------------------------------ متن‌هایِ ساده

def test_persian_texts_do_not_leak_technical_names():
    banned = ("createInvoiceLink", "llama.cpp", "llama-cpp", "بیلدِ CUDA", "Traceback")
    for key, value in i18n.STRINGS.items():
        fa = value.get("fa", "") if isinstance(value, dict) else ""
        assert not any(b in fa for b in banned), key


# ------------------------------------------------------------------ اجزایِ رابط

def test_ui_helpers_build():
    page = FakePage()
    row = common.label_value(page, "رم", "۱۶ GB")
    assert len(row.controls) == 2 and row.controls[0].width == common.LABEL_WIDTH
    assert common.empty_state(page, "inbox", "چیزی نیست") is not None
    assert common.error_note("خطا") is not None
    frame = common.screen_frame(page, row, [])
    assert frame.content.horizontal_alignment is not None


def test_release_body_is_rtl_and_names_real_files():
    flow = _read(ROOT / ".github" / "workflows" / "release.yml")
    body = flow.split("body: |", 1)[1]
    assert 'dir="rtl"' in body and "### دانلود" in body and "### نصب" in body and "### آپدیت" in body
    for name in ("windows-setup.exe", "windows.exe", "linux.tar.gz"):
        assert name in body
