"""۱.۲.۱ — دانلودِ چندمنبعه + پشتیبانِ curl، نقاشیِ روی حلقه‌یِ رابط، رنگ‌ها، نصب‌کننده و متن‌هایِ ساده."""

import hashlib
import re
from pathlib import Path

import pytest
from fake_page import FakePage

from app import branding, i18n, theme
from app.core import bot_profile, downloader as dl
from app.screens import common

ROOT = Path(__file__).resolve().parents[1]
V = ".".join(("9", "8", "7"))  # نسخه‌یِ نمونه برایِ تست؛ عددِ واقعیِ نسخه فقط در app/version.py است
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

def test_bio_credit_is_only_the_repo_link():
    link = "github.com/Niknam1382/smart-business-local"
    assert branding.CREDIT_FA == link and branding.CREDIT_EN == link
    for lang in ("fa", "en"):
        assert bot_profile.credit(lang) == link
        assert bot_profile.seller_limit(lang) == bot_profile.SHORT_MAX - len(link) - len(branding.CREDIT_SEPARATOR)
    assert bot_profile.compose("", "fa") == link
    assert bot_profile.compose("فروشگاه من", "fa") == "فروشگاه من" + branding.CREDIT_SEPARATOR + link
    assert not any("\u0600" <= ch <= "\u06ff" for ch in bot_profile.compose("", "fa"))


def test_old_credit_lines_are_recognised_and_replaced():
    for legacy in branding.LEGACY_CREDITS:
        text = "فروشگاه من" + branding.CREDIT_SEPARATOR + legacy
        assert bot_profile.has_credit(text)
        assert bot_profile.strip_credit(text) == "فروشگاه من"
        assert bot_profile.strip_credit(legacy) == ""


def test_bale_is_never_asked_for_a_bio():
    source = _read(APP / "core" / "bot_manager.py")
    assert 'if platform != "telegram"' in source.split("async def _sync_profile_for", 1)[1][:400]


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


# ------------------------------------------------------------------ ۱٫۲٫۲: کارگرِ پس‌زمینه مستقیم کنترل را تغییر نمی‌دهد

_UI_ATTRS = {"value", "visible", "color", "disabled", "controls", "content", "text", "bgcolor", "icon", "label", "data"}


def _worker_violations():
    import ast

    found = []
    for path in sorted((APP / "screens").glob("*.py")):
        tree = ast.parse(_read(path))
        defs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        targets = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = getattr(func, "attr", getattr(func, "id", ""))
                if name == "run_thread" and node.args and isinstance(node.args[0], ast.Name):
                    targets.add(node.args[0].id)
                if name == "Thread":
                    for kw in node.keywords:
                        if kw.arg == "target" and isinstance(kw.value, ast.Name):
                            targets.add(kw.value.id)
        for name in targets:
            worker = defs.get(name)
            if worker is None:
                continue
            stack = list(worker.body)
            while stack:
                node = stack.pop()
                if isinstance(node, (ast.FunctionDef, ast.Lambda, ast.AsyncFunctionDef)):
                    continue  # paint() و lambdaهایِ تودرتو روی حلقه‌ی رابط اجرا می‌شوند
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Attribute) and target.attr in _UI_ATTRS:
                            found.append(f"{path.name}:{node.lineno} {name}: .{target.attr} = …")
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "update":
                    found.append(f"{path.name}:{node.lineno} {name}: .update()")
                stack.extend(ast.iter_child_nodes(node))
    return found


def test_background_workers_never_touch_controls_directly():
    assert _worker_violations() == []


# ------------------------------------------------------------------ ۱٫۲٫۲: سقفِ زمانِ پاسخِ مدل

def test_slow_model_reply_times_out_without_releasing_the_engine_lock():
    import asyncio

    from app.core import bot_pipeline as bp

    class Fake:
        def _reply_timeout(self):
            return 0.05

    finished = []

    async def scenario():
        lock = asyncio.Lock()

        async def slow():
            async with lock:  # مثلِ _engine_lock: تا پایانِ کارِ مدل نگه داشته می‌شود
                await asyncio.sleep(0.3)
                finished.append(True)
                return "late", []

        started = asyncio.ensure_future(bp.ConversationPipeline._bounded(Fake(), slow()))
        with pytest.raises(bp.AiReplyTimeout):
            await started
        await asyncio.sleep(0.01)
        assert lock.locked()  # تایم‌اوت قفل را آزاد نکرد؛ دو فراخوانیِ هم‌زمانِ موتور ممکن نیست
        await asyncio.sleep(0.4)
        assert finished and not lock.locked()

    asyncio.run(scenario())


def test_fast_model_reply_passes_through_the_bound():
    import asyncio

    from app.core import bot_pipeline as bp

    class Fake:
        def _reply_timeout(self):
            return 1.0

    async def quick():
        return "ok", []

    assert asyncio.run(bp.ConversationPipeline._bounded(Fake(), quick())) == ("ok", [])


def test_busy_reply_is_plain_persian_and_has_no_technical_words():
    from app.core import bot_pipeline as bp

    assert "🙏" in bp.BUSY_REPLY and "timeout" not in bp.BUSY_REPLY.lower()


# ------------------------------------------------------------------ ۱٫۲٫۲: قراردادِ callbackها با شکلِ واقعی

_CALLBACK_ARITY = {"progress_cb": 3, "on_progress": 2, "cancel_cb": 0, "should_cancel": 0}


def _arity_ok(args, given: int) -> bool:
    positional = list(args.posonlyargs) + list(args.args)
    if args.vararg is not None:
        return given >= len(positional) - len(args.defaults)
    return len(positional) - len(args.defaults) <= given <= len(positional)


def _callback_mismatches():
    import ast

    bad = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(_read(path))
        defs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                given = _CALLBACK_ARITY.get(kw.arg or "")
                if given is None:
                    continue
                value = kw.value
                if isinstance(value, ast.Lambda):
                    args = value.args
                elif isinstance(value, ast.Name) and value.id in defs:
                    args = defs[value.id].args
                    if args.args and args.args[0].arg == "self":
                        args = type("A", (), {"posonlyargs": args.posonlyargs, "args": args.args[1:], "vararg": args.vararg,
                                               "defaults": args.defaults})()
                else:
                    continue
                if not _arity_ok(args, given):
                    bad.append(f"{path.name}:{node.lineno} {kw.arg} باید {given} آرگومان بپذیرد")
    return bad


def test_callbacks_accept_the_exact_shape_the_real_callers_send():
    assert _callback_mismatches() == []


def test_gpu_pack_sends_three_progress_values():
    import ast

    tree = ast.parse(_read(APP / "core" / "gpu_pack.py"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "progress_cb"]
    assert calls and all(len(call.args) == 3 for call in calls)


# ------------------------------------------------------------------ ۱٫۲٫۲: بررسیِ Release

def _load_check_release():
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_release", ROOT / "scripts" / "check_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_check_release_reports_missing_signature_in_plain_words():
    cr = _load_check_release()
    names = [n for n, _k in cr.expected_assets(V) if n != cr.SIG_NAME]
    present, missing = cr.evaluate("v" + V, names)
    assert [n for n, _h in missing] == [cr.SIG_NAME]
    text = cr.render("v" + V, present, missing)
    assert "sign_release.py" in text and "❌" in text


def test_check_release_names_match_what_the_updater_downloads():
    from app.core import update_install

    cr = _load_check_release()
    expected = {name for name, _k in cr.expected_assets(V)}
    assert update_install.asset_name_for(update_install.KIND_WINDOWS_SETUP, V, "windows") in expected
    assert update_install.asset_name_for(update_install.KIND_WINDOWS_EXE, V, "windows") in expected


def test_check_release_exit_codes():
    import io
    import json as _json

    cr = _load_check_release()

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener_for(names):
        payload = _json.dumps({"assets": [{"name": n} for n in names]}).encode("utf-8")
        return lambda request, timeout=0: Resp(payload)

    full = [n for n, _k in cr.expected_assets(V)]
    assert cr.main(["v" + V], opener=opener_for(full)) == 0
    assert cr.main(["v" + V], opener=opener_for(full[:-1])) == 1

    def boom(request, timeout=0):
        raise OSError("offline")

    assert cr.main(["v" + V], opener=boom) == 2


# ------------------------------------------------------------------ ۱٫۲٫۲: قفلِ تک‌نمونه

def test_single_instance_second_copy_is_refused_and_released_on_close(tmp_path):
    from app.core import single_instance as si

    first = si.acquire(tmp_path)
    assert first not in (None, si.BUSY)
    try:
        assert si.acquire(tmp_path) == si.BUSY  # نسخه‌ی دوم
    finally:
        si.release()
    again = si.acquire(tmp_path)  # بعد از بسته‌شدنِ اولی قفل آزاد است
    assert again not in (None, si.BUSY)
    si.release()


def test_single_instance_never_blocks_the_app_on_unexpected_errors(tmp_path, monkeypatch):
    from app.core import single_instance as si

    monkeypatch.setattr(si, "_try_lock", lambda handle: (_ for _ in ()).throw(RuntimeError("boom")))
    assert si.acquire(tmp_path) is None  # None = «ادامه بده»، نه BUSY


def test_run_py_checks_the_lock_before_the_window():
    text = _read(ROOT / "run.py")
    assert text.index("single_instance.acquire()") < text.index("ft.run(")


# ------------------------------------------------------------------ ۱٫۲٫۲: کلیدِ رمزنگاری

def _fresh_crypto(tmp_path, monkeypatch):
    from app.core import crypto

    monkeypatch.setattr(crypto, "get_app_data_dir", lambda: tmp_path)
    crypto.clear_problem()
    return crypto


def test_empty_key_file_is_repaired_instead_of_crashing(tmp_path, monkeypatch):
    crypto = _fresh_crypto(tmp_path, monkeypatch)
    (tmp_path / "secret.key").write_bytes(b"")
    token = crypto.encrypt("abc")  # قبلاً ValueError می‌داد
    assert crypto.decrypt(token) == "abc"
    assert crypto.problem() == crypto.PROBLEM_KEY_RESET
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith("secret.key.bad-")]  # کلیدِ خراب نگه داشته شد


def test_garbage_key_is_quarantined_and_old_secrets_read_as_empty(tmp_path, monkeypatch):
    crypto = _fresh_crypto(tmp_path, monkeypatch)
    good = crypto.encrypt("token-1")
    (tmp_path / "secret.key").write_bytes(b"not-a-valid-key")
    crypto.clear_problem()
    assert crypto.decrypt(good) == ""  # با کلیدِ تازه باز نمی‌شود، ولی برنامه نمی‌شکند
    assert crypto.problem() in (crypto.PROBLEM_KEY_RESET, crypto.PROBLEM_UNREADABLE)


def test_valid_key_is_untouched_and_written_atomically(tmp_path, monkeypatch):
    crypto = _fresh_crypto(tmp_path, monkeypatch)
    first = crypto.get_or_create_key()
    assert crypto.get_or_create_key() == first and crypto.problem() == ""
    assert not (tmp_path / "secret.key.tmp").exists()


def test_backup_with_secrets_is_off_by_default_in_the_ui():
    source = _read(APP / "screens" / "data_safety.py")
    assert 'key="backup_secrets"' in source and "value=False" in source.split('key="backup_secrets"', 1)[1][:200]


# ------------------------------------------------------------------ ۱٫۲٫۲: نصبِ خودکار، چرا نیست؟

def test_update_banner_explains_why_auto_install_is_off():
    for reason in ("unsigned", "no_asset", "no_key", "source", "not_writable"):
        entry = i18n.STRINGS[f"update.manual_reason.{reason}"]
        assert entry["fa"] and entry["en"]
    assert "امضا" in i18n.STRINGS["update.manual_reason.unsigned"]["fa"]
    source = _read(APP / "screens" / "update_banner.py")
    assert "update.manual_reason." in source


# ------------------------------------------------------------------ ۱٫۲٫۲: curl و میزبانِ مجاز

def test_curl_rejects_a_final_url_outside_the_allowed_hosts(tmp_path, monkeypatch):
    import io

    calls = _patch_curl(monkeypatch)
    original = dl.subprocess.Popen

    def popen_with_stdout(command, **kw):
        proc = original(command, **kw)
        proc.stdout = io.BytesIO(b"https://evil.example/m.gguf")
        return proc

    monkeypatch.setattr(dl.subprocess, "Popen", popen_with_stdout)
    dest = tmp_path / "m.gguf"
    with pytest.raises(dl.DownloadError, match="evil.example"):
        dl.download([DEAD], dest, expected_sha256=hashlib.sha256(BLOB).hexdigest(), timeout=1.0,
                    use_curl_fallback=True, allowed_hosts={"localhost"})
    assert not dest.exists() and calls


def test_curl_accepts_an_allowed_final_url(tmp_path, monkeypatch):
    import io

    _patch_curl(monkeypatch)
    original = dl.subprocess.Popen

    def popen_with_stdout(command, **kw):
        proc = original(command, **kw)
        proc.stdout = io.BytesIO(b"https://localhost/models/m.gguf")
        return proc

    monkeypatch.setattr(dl.subprocess, "Popen", popen_with_stdout)
    dest = tmp_path / "m.gguf"
    out = dl.download([DEAD], dest, expected_sha256=hashlib.sha256(BLOB).hexdigest(), timeout=1.0,
                      use_curl_fallback=True, allowed_hosts={"localhost"})
    assert out == dest


# ------------------------------------------------------------------ ۱٫۲٫۲: کارت گرافیک و مدلِ آزمایشی

def test_best_gpu_is_chosen_on_hybrid_laptops():
    from app.core import hardware

    assert hardware.pick_best_gpu(["Intel(R) UHD Graphics", "NVIDIA GeForce RTX 3050 Laptop GPU"]) == "NVIDIA GeForce RTX 3050 Laptop GPU"
    assert hardware.pick_best_gpu(["AMD Radeon(TM) Graphics", "AMD Radeon RX 6600M"]) == "AMD Radeon RX 6600M"
    assert hardware.pick_best_gpu(["Microsoft Basic Display Adapter", "Intel(R) Iris Xe Graphics"]) == "Intel(R) Iris Xe Graphics"
    assert hardware.pick_best_gpu(["", "  "]) == ""


def test_only_models_under_one_billion_are_trial_only():
    from app.core import model_catalog as mc

    trial = {e.id for e in mc.entries() if mc.is_trial_only(e)}
    assert trial == {"qwen25-05b", "qwen3-06b"}
    assert not mc.is_trial_only(None)
    assert "trial_model_warning" in _read(APP / "screens" / "bot_connect.py")


# ------------------------------------------------------------------ ۱٫۲٫۲: فاکتورِ PDF برایِ خریدار و فروشنده

def test_invoice_goes_to_buyer_and_seller_by_default_and_migrates_once():
    from app.core import settings as settings_module

    assert settings_module.AppSettings().invoice_send_owner_copy is True
    assert settings_module.AppSettings().invoice_auto_send == "after_confirm"
    old = {"invoice_auto_send": "off", "invoice_send_owner_copy": False}
    migrated = settings_module._migrate_keys(dict(old))  # noqa: SLF001
    assert migrated["invoice_auto_send"] == "after_confirm" and migrated["invoice_send_owner_copy"] is True
    assert migrated["invoice_defaults_v122"] is True
    chosen = {"invoice_auto_send": "off", "invoice_send_owner_copy": False, "invoice_defaults_v122": True}
    assert settings_module._migrate_keys(dict(chosen))["invoice_send_owner_copy"] is False  # انتخابِ بعدیِ مالک محترم است


def test_invoice_pdf_design_helpers():
    from app.core import invoice_pdf as ip

    assert ip._darken((100, 200, 250), 0.5) == (50, 100, 125)  # noqa: SLF001
    assert all(0 <= c <= 255 for c in ip._darken((255, 255, 255), 2.0))  # noqa: SLF001
    assert set(ip._STATUS_LABEL) == {"paid", "refund"}  # noqa: SLF001
