"""N14a: تشخیصِ نسخه‌ی تازه از GitHub (semver، draft/prerelease، «بعداً»، آفلاین) + اعتبارِ امضا و هش."""

import base64
import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app import branding
from app.core import update_verify as uv
from app.core import updater
from app.core.settings import AppSettings
from app.core.updater import STATUS_CURRENT, STATUS_ERROR, STATUS_SKIPPED, STATUS_UPDATE, UpdateChecker, is_newer, parse_release, parse_version

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def keygen():
    return load_script("make_signing_key")


@pytest.fixture(scope="module")
def signer():
    return load_script("sign_release")


def release(tag="v1.2.0", **over):
    base = {
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "html_url": f"https://github.com/niknam1382/smart-business-local/releases/tag/{tag}",
        "body": "تغییرات",
        "published_at": "2026-10-20T10:00:00Z",
        "assets": [
            {"name": "SmartBusinessLocal-1.2.0-windows-setup.exe", "browser_download_url": "https://github.com/x/y/releases/download/v1.2.0/setup.exe", "size": 123},
            {"name": "SHA256SUMS.txt", "browser_download_url": "https://github.com/x/y/releases/download/v1.2.0/SHA256SUMS.txt", "size": 5},
            {"name": "SHA256SUMS.txt.sig", "browser_download_url": "https://github.com/x/y/releases/download/v1.2.0/SHA256SUMS.txt.sig", "size": 5},
        ],
    }
    base.update(over)
    return base


# ------------------------------------------------------------------ semver ----

@pytest.mark.parametrize(
    "newer,older",
    [
        ("1.1.0", "1.0.0"), ("1.10.0", "1.9.0"), ("v2.0.0", "1.99.99"), ("1.1.0", "1.1.0-alpha.1"), ("1.1.0-alpha.2", "1.1.0-alpha.1"),
        ("1.1.0-alpha.10", "1.1.0-alpha.2"), ("1.1.0-beta", "1.1.0-alpha"), ("1.1.0-alpha.1", "1.1.0-alpha"), ("1.0.1", "1.0.0+build5"),
    ],
)
def test_semver_ordering(newer, older):
    assert is_newer(newer, older) and not is_newer(older, newer)


def test_semver_equal_invalid_and_build_metadata():
    assert not is_newer("1.0.0", "1.0.0") and not is_newer("1.0.0+abc", "1.0.0")
    assert parse_version("1.2") == parse_version("1.2.0")
    for bad in ("", "abc", "1", "1.x.0", "latest", None, "1.0.0.0"):
        assert parse_version(bad) is None
        assert not is_newer(bad or "", "1.0.0") and not is_newer("1.0.1", bad or "")


# ------------------------------------------------------------- parse_release ----

def test_parse_release_reads_version_assets_and_signature_flag():
    info = parse_release(release())
    assert info.version == "1.2.0" and info.tag == "v1.2.0" and info.signed is True and len(info.assets) == 3
    assert info.asset("SHA256SUMS.txt").url.startswith("https://github.com/")
    unsigned = parse_release(release(assets=release()["assets"][:2]))
    assert unsigned.signed is False


@pytest.mark.parametrize("payload", [release(draft=True), release(prerelease=True), release(tag="v1.2.0-rc.1"), release(tag="nightly"), [], "x", None, 5, {}])
def test_draft_prerelease_and_garbage_are_ignored(payload):
    assert parse_release(payload) is None


def test_unsafe_urls_are_dropped_from_the_release():
    payload = release(
        html_url="http://evil.example/phish",
        assets=[
            {"name": "ok.exe", "browser_download_url": "https://github.com/a/b/releases/download/v1.2.0/ok.exe"},
            {"name": "http.exe", "browser_download_url": "http://github.com/a/b/http.exe"},
            {"name": "evil.exe", "browser_download_url": "https://github.com.evil.example/evil.exe"},
            {"name": "../trav.exe", "browser_download_url": "https://github.com/a/b/trav.exe"},
            {"name": "js", "browser_download_url": "javascript:alert(1)"},
            "not-a-dict",
        ],
    )
    info = parse_release(payload)
    assert [a.name for a in info.assets] == ["ok.exe"]
    assert info.html_url == branding.github_releases_url()  # آدرسِ نامطمئن ⇒ صفحه‌ی Releasesِ خودمان


# ----------------------------------------------------------------- بررسی‌گر ----

class Rig:
    def __init__(self, payload, current="1.1.0", **kw):
        self.settings = AppSettings()
        self.saves = 0
        self.now = 1_000_000.0
        self.calls = 0
        self.payload = payload

        def fetch(url, timeout):
            self.calls += 1
            if self.payload is None:
                return None
            return self.payload if isinstance(self.payload, bytes) else json.dumps(self.payload).encode()

        self.checker = UpdateChecker(lambda: self.settings, self._save, current_version=current, fetcher=fetch, clock=lambda: self.now, **kw)

    def _save(self):
        self.saves += 1


def test_newer_release_becomes_pending_and_dismiss_persists_until_next_version():
    rig = Rig(release("v1.2.0"))
    res = rig.checker.check()
    assert res.status == STATUS_UPDATE and res.info.version == "1.2.0"
    assert rig.checker.pending().version == "1.2.0"
    rig.checker.dismiss("v1.2.0")
    assert rig.settings.update_dismissed_version == "1.2.0" and rig.checker.pending() is None
    rig.now += 7200
    again = rig.checker.check()
    assert again.status == STATUS_UPDATE and again.dismissed is True and rig.checker.pending() is None  # بنر برنمی‌گرده
    rig.payload = release("v1.3.0")
    rig.now += 7200
    rig.checker.check()
    assert rig.checker.pending().version == "1.3.0"  # نسخه‌ی تازه‌تر دوباره خبر می‌دهد


def test_same_or_older_release_means_current():
    for tag in ("v1.1.0", "v1.0.0"):
        rig = Rig(release(tag), current="1.1.0")
        assert rig.checker.check().status == STATUS_CURRENT and rig.checker.pending() is None


def test_prerelease_is_never_offered_even_if_newer():
    rig = Rig(release("v9.0.0", prerelease=True))
    assert rig.checker.check().status == STATUS_CURRENT


def test_offline_or_garbage_is_silent_error_and_keeps_previous_state():
    rig = Rig(release("v1.2.0"))
    rig.checker.check()
    rig.payload = None
    rig.now += 7200
    assert rig.checker.check().status == STATUS_ERROR
    assert rig.checker.pending().version == "1.2.0"  # نتیجه‌ی خوبِ قبلی پاک نمی‌شه
    for junk in (b"<html>502</html>", b"[]", b'{"tag_name": 5}'):
        rig.payload = junk
        rig.now += 7200
        assert rig.checker.check().status in (STATUS_ERROR, STATUS_CURRENT)


def test_auto_check_respects_setting_and_minimum_gap_but_force_does_not():
    rig = Rig(release("v1.2.0"))
    rig.settings.update_check_enabled = False
    assert rig.checker.check().status == STATUS_SKIPPED and rig.calls == 0
    assert rig.checker.check(force=True).status == STATUS_UPDATE and rig.calls == 1  # «بررسیِ الان»
    rig.settings.update_check_enabled = True
    assert rig.checker.check().status == STATUS_UPDATE and rig.calls == 1  # فاصله‌ی حداقلی: دوباره نزد
    rig.now += updater.MIN_GAP_SECONDS + 1
    rig.checker.check()
    assert rig.calls == 2
    assert rig.settings.update_last_check_ts == int(rig.now) and rig.saves >= 2


def test_run_periodic_checks_once_at_start_then_waits(monkeypatch):
    rig = Rig(release("v1.2.0"))
    got, stop = [], threading.Event()

    def on_result(result):
        got.append(result.status)
        stop.set()

    thread = threading.Thread(target=updater.run_periodic, args=(rig.checker, on_result, stop, 0.01), daemon=True)
    thread.start()
    thread.join(3)
    assert got == [STATUS_UPDATE] and not thread.is_alive()


# ------------------------------------------------- fetcher واقعی با سرورِ جعلی ----

@pytest.fixture
def fake_github():
    state = {"status": 200, "body": json.dumps(release("v1.5.0")).encode(), "hits": 0, "ua": ""}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            state["hits"] += 1
            state["ua"] = self.headers.get("User-Agent", "")
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(state["body"])

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{server.server_address[1]}/repos/x/releases/latest"
    yield state
    server.shutdown()


def test_default_fetcher_against_a_real_http_server(fake_github):
    settings = AppSettings()
    checker = UpdateChecker(lambda: settings, lambda: None, current_version="1.1.0", api_url=fake_github["url"])
    res = checker.check(force=True)
    assert res.status == STATUS_UPDATE and res.info.version == "1.5.0"
    assert fake_github["ua"].startswith("SmartBusinessLocal/")  # فقط یک GET؛ بدونِ داده‌ی کاربر


def test_default_fetcher_returns_none_on_http_error_and_closed_port(fake_github):
    fake_github["status"] = 403  # سقفِ API گیت‌هاب
    assert updater.default_fetcher(fake_github["url"], 5) is None
    assert updater.default_fetcher("http://127.0.0.1:9/x", 1) is None


def test_oversized_response_is_rejected(fake_github):
    fake_github["body"] = b"x" * (updater.MAX_RESPONSE_BYTES + 10)
    assert updater.default_fetcher(fake_github["url"], 5) is None


# ------------------------------------------------------------- امضا و هش ----

def test_generate_sign_and_verify_roundtrip(tmp_path, keygen, signer):
    key_path = tmp_path / "keys" / "k.pem"
    pub = keygen.generate_key(key_path)
    assert len(base64.b64decode(pub)) == 32
    key = signer.load_private_key(key_path)
    sums = b"abc  file.exe\n"
    sig = signer.sign_sums(key, sums)
    assert uv.verify_signature(sums, sig, pub) is True
    assert uv.verify_signature(sums + b" ", sig, pub) is False  # حتی یک بایتِ تغییر
    assert uv.verify_signature(sums, "  " + sig + "\n", pub) is True  # فاصله‌ی اطراف مجاز
    other = keygen.generate_key(tmp_path / "k2.pem")
    assert uv.verify_signature(sums, sig, other) is False
    for junk in ("", "not base64!!", base64.b64encode(b"short").decode(), base64.b64encode(b"x" * 64).decode()):
        assert uv.verify_signature(sums, junk, pub) is False


def test_verification_is_impossible_without_a_public_key(monkeypatch):
    monkeypatch.setattr(branding, "UPDATE_PUBLIC_KEY_B64", "")
    assert uv.verify_signature(b"x", base64.b64encode(b"x" * 64).decode()) is False
    assert uv.verify_signature(b"x", "sig", "") is False
    assert uv.verify_signature(b"x", "sig", "garbage") is False


def test_parse_sha256sums_formats_and_hostile_names():
    h = "a" * 64
    text = f"{h}  setup.exe\n{h.upper()} *app.zip\nshort  x\n{h}  ../evil.exe\n{h}  dir/inner.exe\n\n{h}\n"
    assert uv.parse_sha256sums(text) == {"setup.exe": h, "app.zip": h}


def test_verify_asset_requires_good_signature_listed_name_and_matching_hash(tmp_path, keygen, signer):
    pub = keygen.generate_key(tmp_path / "k.pem")
    key = signer.load_private_key(tmp_path / "k.pem")
    asset = tmp_path / "setup.exe"
    asset.write_bytes(b"binary-bytes")
    digest = uv.sha256_file(asset)
    sums = f"{digest}  setup.exe\n".encode()
    sig = signer.sign_sums(key, sums)
    uv.verify_asset(asset, "setup.exe", sums, sig, pub)  # درست = بی‌صدا
    with pytest.raises(uv.VerifyError):
        uv.verify_asset(asset, "setup.exe", sums, "AAAA", pub)  # امضای بد
    with pytest.raises(uv.VerifyError):
        uv.verify_asset(asset, "other.exe", sums, sig, pub)  # در فهرست نیست
    asset.write_bytes(b"tampered")
    with pytest.raises(uv.VerifyError):
        uv.verify_asset(asset, "setup.exe", sums, sig, pub)  # هشِ نادرست
    forged = f"{uv.sha256_file(asset)}  setup.exe\n".encode()
    with pytest.raises(uv.VerifyError):
        uv.verify_asset(asset, "setup.exe", forged, sig, pub)  # فهرستِ دست‌کاری‌شده با امضای قدیمی


# ---------------------------------------------------------------- اسکریپت‌ها ----

def test_make_signing_key_refuses_repo_paths_and_overwrite(tmp_path, keygen):
    repo_root = Path(keygen.__file__).resolve().parents[1]
    with pytest.raises(SystemExit):
        keygen.generate_key(repo_root / "secret.pem")
    target = tmp_path / "k.pem"
    keygen.generate_key(target)
    before = target.read_bytes()
    with pytest.raises(SystemExit):
        keygen.generate_key(target)
    assert target.read_bytes() == before
    keygen.generate_key(target, force=True)
    assert target.read_bytes() != before
    if hasattr(target, "stat") and not str(target).startswith("\\"):
        assert (target.stat().st_mode & 0o077) == 0  # فقط مالک (یونیکس)


def test_passphrase_protected_key_needs_the_right_passphrase(tmp_path, keygen, signer):
    target = tmp_path / "enc.pem"
    pub = keygen.generate_key(target, passphrase="راز-قوی")
    assert signer.public_b64(signer.load_private_key(target, "راز-قوی")) == pub
    with pytest.raises(signer.SignError):
        signer.load_private_key(target, "غلط")
    with pytest.raises(signer.SignError):
        signer.load_private_key(target, "")
    with pytest.raises(signer.SignError):
        signer.load_private_key(tmp_path / "missing.pem")


def test_sign_release_script_end_to_end_and_key_mismatch_guard(tmp_path, keygen, signer, monkeypatch, capsys):
    pub = keygen.generate_key(tmp_path / "k.pem")
    sums = tmp_path / "SHA256SUMS.txt"
    sums.write_text(f"{'b' * 64}  setup.exe\n", encoding="utf-8")
    out = tmp_path / "out"
    argv = ["v1.1.0", "--key", str(tmp_path / "k.pem"), "--sums-file", str(sums), "--out-dir", str(out)]
    monkeypatch.setattr(branding, "UPDATE_PUBLIC_KEY_B64", pub)
    assert signer.main(argv) == 0
    sig = (out / "SHA256SUMS.txt.sig").read_text(encoding="ascii")
    assert uv.verify_signature(sums.read_bytes(), sig, pub)
    # کلیدِ دیگر در branding ⇒ امضا ساخته نمی‌شه (برنامه رد می‌کرد)
    monkeypatch.setattr(branding, "UPDATE_PUBLIC_KEY_B64", keygen.generate_key(tmp_path / "other.pem"))
    (out / "SHA256SUMS.txt.sig").unlink()
    assert signer.main(argv) == 1 and not (out / "SHA256SUMS.txt.sig").exists()
    # branding خالی ⇒ هشدار ولی امضا ساخته می‌شه
    monkeypatch.setattr(branding, "UPDATE_PUBLIC_KEY_B64", "")
    assert signer.main(argv) == 0 and "خالیه" in capsys.readouterr().out
    # فایلِ خالی/خراب رد می‌شه
    sums.write_text("junk", encoding="utf-8")
    assert signer.main(argv) == 1


def test_release_workflow_publishes_checksums_and_marks_prereleases():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "SHA256SUMS.txt" in workflow and "prerelease:" in workflow
