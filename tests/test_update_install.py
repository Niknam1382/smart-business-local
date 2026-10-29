"""نصبِ یک‌کلیکیِ به‌روزرسانی (N14b): تشخیصِ نوع، دانلودِ محافظت‌شده، امضا/هش، پشتیبان، پلانِ helper و سناریوهای شکست."""

import base64
import hashlib
import io
import json
import os
import stat
import threading
import time
import zipfile
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from helpers import wait_until

from app.core import update_apply, update_install as ui
from app.core.updater import Asset, UpdateInfo


# ----------------------------------------------------------------- زیرساختِ تست ----

@dataclass
class Route:
    body: bytes = b""
    status: int = 200
    length: object = "auto"  # "auto" | None (بدونِ Content-Length) | عدد (اعلامِ دروغ)
    location: str = ""
    gate: object = None  # Event: نیمه‌ی اول را می‌فرسته، بعد منتظرِ gate می‌مونه


@pytest.fixture
def server():
    state = {"routes": {}, "hits": []}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass

        def do_GET(self):  # noqa: N802
            state["hits"].append(self.path)
            route = state["routes"].get(self.path)
            if route is None:
                route = Route(status=404)
            if isinstance(route, bytes):
                route = Route(route)
            self.send_response(route.status)
            if route.location:
                self.send_header("Location", route.location)
            length = len(route.body) if route.length == "auto" else route.length
            if length is not None:
                self.send_header("Content-Length", str(length))
            else:
                self.close_connection = True
            self.end_headers()
            if route.gate is not None:
                half = len(route.body) // 2
                self.wfile.write(route.body[:half])
                self.wfile.flush()
                route.gate.wait(15)
                self.wfile.write(route.body[half:])
            else:
                self.wfile.write(route.body)
            self.close_connection = True

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: httpd.serve_forever(poll_interval=0.02), daemon=True)
    thread.start()
    state["base"] = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield state
    httpd.shutdown()
    httpd.server_close()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_key():
    key = Ed25519PrivateKey.generate()
    return key, base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()


def release(server, key, assets, version="1.2.0", sums=None, sig_key=None):
    """فایل‌ها را روی سرورِ محلی می‌گذاره و ``UpdateInfo`` می‌سازه (هم‌شکلِ نسخه‌ی GitHub)."""
    sums_bytes = sums if sums is not None else "".join(f"{sha(d)}  {n}\n" for n, d in assets.items()).encode()
    sig = base64.b64encode((sig_key or key).sign(sums_bytes)).decode().encode()
    files = {**assets, "SHA256SUMS.txt": sums_bytes, "SHA256SUMS.txt.sig": sig}
    for name, data in files.items():
        server["routes"]["/" + name] = data
    return UpdateInfo(
        version=version, tag=f"v{version}", html_url=f"https://github.com/x/y/releases/tag/v{version}",
        assets=tuple(Asset(n, f"{server['base']}/{n}", len(d)) for n, d in files.items()),
    )


def portable_zip(os_files, root_files=None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in (root_files or {"portable.flag": b"", "README-PORTABLE.txt": b"readme", "SmartBusinessData/": b""}).items():
            zf.writestr(f"{ui.PORTABLE_ROOT}/{name}", data)
        for name, data in os_files.items():
            zf.writestr(f"{ui.PORTABLE_ROOT}/{name}", data)
    return buf.getvalue()


@pytest.fixture
def env(tmp_path, server):
    data = tmp_path / "data"
    data.mkdir()
    (data / "settings.json").write_text('{"user_name": "سارا"}', encoding="utf-8")
    (tmp_path / "tmp").mkdir()
    exe_dir = tmp_path / "app"
    exe_dir.mkdir()
    exe = exe_dir / "SmartBusinessLocal.exe"
    exe.write_bytes(b"OLD-EXE")
    key, pub = make_key()
    handed = []

    def installer(kind=ui.KIND_WINDOWS_EXE, os_name="windows", **over):
        kwargs = dict(
            target=ui.InstallTarget(kind, os_name, str(exe), ui.REASON_PLATFORM if kind == ui.KIND_MANUAL else ui.REASON_OK),
            public_key=pub, data_dir=data, temp_root=tmp_path / "tmp", downloads_dir=tmp_path / "downloads",
            url_ok=lambda url: True, spawn_helper=handed.append, wait_pids=lambda: [4242],
        )
        kwargs.update(over)
        return ui.UpdateInstaller(**kwargs)

    def data_snapshot():
        return {str(p.relative_to(data)): p.read_bytes() for p in data.rglob("*") if p.is_file() and "backups" not in p.parts}

    return type("Env", (), dict(data=data, exe=exe, key=key, pub=pub, server=server, handed=handed, installer=staticmethod(installer), snapshot=staticmethod(data_snapshot), tmp=tmp_path / "tmp", root=tmp_path))


def staging_dirs(env):
    return [p for p in env.tmp.iterdir() if p.name.startswith(ui.STAGING_PREFIX)]


# ---------------------------------------------------------------- تشخیصِ نوعِ نصب ----

def test_detect_target_matrix(tmp_path):
    exe = tmp_path / "SmartBusinessLocal.exe"
    base = dict(exe_path=str(exe), portable_dir=None, writable=lambda p: True)
    assert ui.detect_target(frozen=True, platform="win32", headless=True, **base).reason == ui.REASON_HEADLESS
    assert ui.detect_target(frozen=False, platform="win32", **base).reason == ui.REASON_SOURCE
    mac = ui.detect_target(frozen=True, platform="darwin", **base)
    assert (mac.kind, mac.os_name, mac.reason) == (ui.KIND_MANUAL, "macos", ui.REASON_PLATFORM)
    assert ui.detect_target(frozen=True, platform="linux", **base).os_name == "linux"
    assert ui.detect_target(frozen=True, platform="win32", exists=lambda p: False, **base).kind == ui.KIND_WINDOWS_EXE
    setup = ui.detect_target(frozen=True, platform="win32", exists=lambda p: p.name == "unins000.exe", **base)
    assert setup.kind == ui.KIND_WINDOWS_SETUP
    portable = ui.detect_target(frozen=True, platform="win32", exe_path=str(exe), portable_dir=tmp_path, writable=lambda p: True)
    assert portable.kind == ui.KIND_PORTABLE


def test_not_writable_folder_disables_auto_install_except_for_the_installer_kind(tmp_path):
    exe = str(tmp_path / "SmartBusinessLocal.exe")
    locked = dict(frozen=True, platform="win32", exe_path=exe, writable=lambda p: False)
    assert ui.detect_target(portable_dir=None, exists=lambda p: False, **locked).reason == ui.REASON_NOT_WRITABLE
    assert ui.detect_target(portable_dir=tmp_path, **locked).reason == ui.REASON_NOT_WRITABLE
    assert ui.detect_target(portable_dir=None, exists=lambda p: p.name == "unins000.exe", **locked).kind == ui.KIND_WINDOWS_SETUP  # نصب‌کننده خودش در پوشه‌ی کاربر می‌نویسه


def test_asset_names_match_what_the_release_script_builds():
    import importlib.util

    spec = importlib.util.spec_from_file_location("package_release", Path(__file__).parent.parent / "scripts" / "package_release.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.APP_NAME == ui.APP_FILE_PREFIX
    assert script.PORTABLE_ROOT == ui.PORTABLE_ROOT
    assert script.OS_FOLDERS == ui.OS_FOLDERS
    assert ui.asset_name_for(ui.KIND_WINDOWS_SETUP, "v1.2.0", "windows") == "SmartBusinessLocal-1.2.0-windows-setup.exe"
    assert ui.asset_name_for(ui.KIND_WINDOWS_EXE, "1.2.0", "windows") == "SmartBusinessLocal-1.2.0-windows.exe"
    assert ui.asset_name_for(ui.KIND_PORTABLE, "1.2.0", "windows") == "SmartBusinessLocal-1.2.0-windows-portable.zip"
    assert ui.asset_name_for(ui.KIND_MANUAL, "1.2.0", "macos") == "SmartBusinessLocal-1.2.0-macos-portable.zip"
    assert ui.asset_name_for("nope", "1.2.0", "windows") == ""


def info_with(*names, signed=True, version="1.2.0"):
    assets = [Asset(n, f"https://github.com/x/y/releases/download/v{version}/{n}", 10) for n in names]
    if signed:
        assets += [Asset("SHA256SUMS.txt", "https://github.com/x/y/s", 5), Asset("SHA256SUMS.txt.sig", "https://github.com/x/y/g", 5)]
    return UpdateInfo(version=version, tag=f"v{version}", html_url="https://github.com/x/y/releases/tag/v1.2.0", assets=tuple(assets))


def test_assess_modes_and_reasons():
    win_exe = ui.InstallTarget(ui.KIND_WINDOWS_EXE, "windows", "x.exe")
    good = info_with("SmartBusinessLocal-1.2.0-windows.exe")
    assert ui.assess(good, win_exe, "KEY").mode == ui.MODE_AUTO
    assert ui.assess(good, win_exe, "").reason == ui.REASON_NO_KEY  # کلیدِ عمومی هنوز ساخته نشده ⇒ دستی
    assert ui.assess(info_with("SmartBusinessLocal-1.2.0-windows.exe", signed=False), win_exe, "KEY").reason == ui.REASON_UNSIGNED
    assert ui.assess(info_with("other.zip"), win_exe, "KEY").reason == ui.REASON_NO_ASSET
    setup = ui.InstallTarget(ui.KIND_WINDOWS_SETUP, "windows", "x.exe")
    assert ui.assess(info_with("SmartBusinessLocal-1.2.0-windows-setup.exe"), setup, "KEY").mode == ui.MODE_AUTO
    assert ui.assess(good, setup, "KEY").reason == ui.REASON_NO_ASSET  # exeِ تکی به درد نصب‌کننده نمی‌خوره
    portable = ui.InstallTarget(ui.KIND_PORTABLE, "windows", "x.exe")
    assert ui.assess(info_with("SmartBusinessLocal-1.2.0-windows-portable.zip"), portable, "KEY").mode == ui.MODE_AUTO
    mac = ui.InstallTarget(ui.KIND_MANUAL, "macos", "x", ui.REASON_PLATFORM)
    av = ui.assess(info_with("SmartBusinessLocal-1.2.0-macos-portable.zip"), mac, "KEY")
    assert av.mode == ui.MODE_DOWNLOAD and av.asset.name.endswith("macos-portable.zip")
    for reason in (ui.REASON_SOURCE, ui.REASON_HEADLESS, ui.REASON_NOT_WRITABLE):
        assert ui.assess(good, ui.InstallTarget(ui.KIND_MANUAL, "windows", "x", reason), "KEY").mode == ui.MODE_MANUAL


# -------------------------------------------------------------------------- دانلود ----

def test_download_streams_with_progress_and_leaves_no_part_file(server, tmp_path):
    body = os.urandom(700_000)
    server["routes"]["/f.bin"] = body
    seen = []
    dest = tmp_path / "f.bin"
    size = ui.download_file(f"{server['base']}/f.bin", dest, expected_size=len(body), progress=lambda d, t: seen.append((d, t)), url_ok=lambda u: True)
    assert size == len(body) and dest.read_bytes() == body and not (tmp_path / "f.bin.part").exists()
    assert seen[-1] == (len(body), len(body)) and len(seen) >= 3 and [d for d, _ in seen] == sorted(d for d, _ in seen)


def test_default_url_guard_rejects_non_github_and_non_https(server, tmp_path):
    for bad in ("http://github.com/x", "https://evil.example.com/x", "ftp://github.com/x", "file:///etc/passwd", "https://github.com.evil.com/x"):
        with pytest.raises(ui.InstallError) as err:
            ui.download_bytes(bad, max_bytes=100)
        assert err.value.code == "unsafe_url", bad


def test_redirect_to_an_untrusted_host_is_blocked(server):
    server["routes"]["/start"] = Route(status=302, location=f"{server['base']}/evil", length=0)
    server["routes"]["/evil"] = b"payload"
    with pytest.raises(ui.InstallError) as err:
        ui.download_bytes(f"{server['base']}/start", max_bytes=100, url_ok=lambda u: "/evil" not in u)
    assert err.value.code == "network" and "/evil" not in server["hits"]


def test_redirect_to_an_allowed_host_is_followed(server):
    server["routes"]["/start"] = Route(status=302, location=f"{server['base']}/real", length=0)
    server["routes"]["/real"] = b"payload"
    assert ui.download_bytes(f"{server['base']}/start", max_bytes=100, url_ok=lambda u: True) == b"payload"


def test_http_errors_and_dead_servers_become_network_errors(server):
    with pytest.raises(ui.InstallError) as err:
        ui.download_bytes(f"{server['base']}/missing", max_bytes=100, url_ok=lambda u: True)
    assert err.value.code == "network" and "404" in err.value.detail
    with pytest.raises(ui.InstallError) as err2:
        ui.download_bytes("http://127.0.0.1:1/x", max_bytes=100, url_ok=lambda u: True, timeout=2)
    assert err2.value.code == "network"


def test_size_limits_declared_and_streamed(server):
    server["routes"]["/big"] = b"x" * 5000
    with pytest.raises(ui.InstallError) as err:
        ui.download_bytes(f"{server['base']}/big", max_bytes=1000, url_ok=lambda u: True)
    assert err.value.code == "too_large"
    server["routes"]["/nolen"] = Route(b"y" * 5000, length=None)  # سرور طولِ فایل را اعلام نمی‌کنه
    with pytest.raises(ui.InstallError) as err2:
        ui.download_bytes(f"{server['base']}/nolen", max_bytes=1000, url_ok=lambda u: True)
    assert err2.value.code == "too_large"
    with pytest.raises(ui.InstallError) as err3:
        ui.download_bytes(f"{server['base']}/big", max_bytes=10_000, expected_size=10**9, url_ok=lambda u: True)
    assert err3.value.code == "too_large"  # اندازه‌ی اعلامیِ API هم سقف دارد


def test_size_mismatch_against_api_size_or_truncated_body(server, tmp_path):
    server["routes"]["/f"] = b"z" * 2000
    dest = tmp_path / "f"
    with pytest.raises(ui.InstallError) as err:
        ui.download_file(f"{server['base']}/f", dest, expected_size=1999, url_ok=lambda u: True)
    assert err.value.code == "size_mismatch" and not dest.exists() and not (tmp_path / "f.part").exists()
    server["routes"]["/cut"] = Route(b"z" * 2000, length=3000)  # وعده‌ی ۳۰۰۰ بایت، ارسالِ ۲۰۰۰
    with pytest.raises(ui.InstallError) as err2:
        ui.download_file(f"{server['base']}/cut", tmp_path / "cut", url_ok=lambda u: True)
    assert err2.value.code in ("size_mismatch", "network") and not (tmp_path / "cut.part").exists()


def test_cancel_stops_the_download_and_removes_the_part_file(server, tmp_path):
    server["routes"]["/f"] = os.urandom(3 * ui.CHUNK_BYTES + 5)
    cancel = threading.Event()
    with pytest.raises(ui.InstallError) as err:
        ui.download_file(f"{server['base']}/f", tmp_path / "f", cancel=cancel, url_ok=lambda u: True, progress=lambda d, t: cancel.set())
    assert err.value.code == "cancelled" and list(tmp_path.glob("f*")) == []


# ---------------------------------------------------------------- بازکردنِ زیپ ----

def test_extract_takes_only_the_os_folder_never_data_or_flag(tmp_path):
    archive = tmp_path / "p.zip"
    archive.write_bytes(portable_zip({"Windows/SmartBusinessLocal.exe": b"WIN", "Windows/lib/x.dll": b"DLL", "macOS/SmartBusinessLocal": b"MAC", "SmartBusinessData/settings.json": b"USER"}))
    manifest = ui.extract_portable_tree(archive, "windows", tmp_path / "tree")
    assert dict(manifest) == {"SmartBusinessLocal.exe": sha(b"WIN"), "lib/x.dll": sha(b"DLL")}
    assert sorted(p.relative_to(tmp_path / "tree").as_posix() for p in (tmp_path / "tree").rglob("*") if p.is_file()) == ["SmartBusinessLocal.exe", "lib/x.dll"]


def test_extract_rejects_zip_slip_symlinks_oversize_and_bad_archives(tmp_path, monkeypatch):
    def attempt(build):
        archive = tmp_path / "bad.zip"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            build(zf)
        archive.write_bytes(buf.getvalue())
        with pytest.raises(ui.InstallError) as err:
            ui.extract_portable_tree(archive, "windows", tmp_path / "t")
        return err.value

    assert attempt(lambda zf: zf.writestr(f"{ui.PORTABLE_ROOT}/Windows/../../evil.txt", b"x")).code == "unpack"
    assert attempt(lambda zf: zf.writestr(f"{ui.PORTABLE_ROOT}/Windows//etc/passwd", b"x")).code == "unpack"
    assert not (tmp_path.parent / "evil.txt").exists()

    def symlink(zf):
        info = zipfile.ZipInfo(f"{ui.PORTABLE_ROOT}/Windows/link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "/etc/passwd")

    assert attempt(symlink).detail == "symlink"
    assert attempt(lambda zf: zf.writestr(f"{ui.PORTABLE_ROOT}/macOS/only-mac", b"x")).detail == "empty"
    monkeypatch.setattr(ui, "MAX_UNPACK_BYTES", 10)
    assert attempt(lambda zf: zf.writestr(f"{ui.PORTABLE_ROOT}/Windows/big.bin", b"x" * 100)).detail == "too_big"
    monkeypatch.setattr(ui, "MAX_UNPACK_BYTES", 10**9)
    monkeypatch.setattr(ui, "MAX_UNPACK_FILES", 1)
    assert attempt(lambda zf: (zf.writestr(f"{ui.PORTABLE_ROOT}/Windows/a", b"1"), zf.writestr(f"{ui.PORTABLE_ROOT}/Windows/b", b"2"))).detail == "too_big"
    garbage = tmp_path / "garbage.zip"
    garbage.write_bytes(b"not a zip")
    with pytest.raises(ui.InstallError) as err:
        ui.extract_portable_tree(garbage, "windows", tmp_path / "t2")
    assert err.value.detail == "bad_zip"


# ------------------------------------------------------- نصبِ کامل (exe تکی) ----

def run_install(env, assets, kind=ui.KIND_WINDOWS_EXE, **kw):
    info = release(env.server, env.key, assets, **kw.pop("release_kw", {}))
    events = []
    installer = env.installer(kind)
    result = installer.install(info, lambda phase, frac: events.append((phase, frac)), before_handoff=lambda: events.append(("before_handoff", None)))
    return installer, info, result, events


def test_full_exe_install_verifies_backs_up_and_hands_off_to_the_helper(env):
    new = os.urandom(300_000)
    before = env.snapshot()
    _inst, _info, result, events = run_install(env, {"SmartBusinessLocal-1.2.0-windows.exe": new})
    assert result.status == "restart" and Path(result.backup).is_file() and Path(result.backup).parent.name == "backups"
    assert Path(result.backup).name.startswith("before-update-")
    phases = [e[0] for e in events]
    assert phases[:2] == ["signature", "download"]
    assert phases.index("verify") < phases.index("prepare") < phases.index("backup") < phases.index("before_handoff") < phases.index("handoff")
    assert any(p == "download" and f == 1.0 for p, f in events)
    (plan_path,) = env.handed
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    update_apply.validate_plan(plan)
    assert plan["kind"] == ui.KIND_WINDOWS_EXE and plan["version_to"] == "1.2.0" and plan["wait_pids"] == [4242]
    assert plan["current_exe"] == str(env.exe) and plan["relaunch_exe"] == str(env.exe) and plan["target_dir"] == str(env.exe.parent)
    (entry,) = plan["files"]
    assert entry["dst"] == "SmartBusinessLocal.exe" and entry["sha256"] == sha(new)
    assert (Path(plan["src_dir"]) / entry["src"]).read_bytes() == new
    assert plan["result_file"] == str(env.data / "update_result.json")
    assert env.snapshot() == before  # پوشه‌ی داده (غیر از backups/) دست‌نخورده
    assert env.exe.read_bytes() == b"OLD-EXE"  # خودِ جایگزینی کارِ helper است، نه ما
    assert len(staging_dirs(env)) == 1  # helper هنوز به آن نیاز داره


def test_a_renamed_exe_keeps_its_own_name(env):
    renamed = env.exe.with_name("MyShop.exe")
    env.exe.rename(renamed)
    env.exe = renamed
    info = release(env.server, env.key, {"SmartBusinessLocal-1.2.0-windows.exe": b"NEW"})
    installer = ui.UpdateInstaller(
        target=ui.InstallTarget(ui.KIND_WINDOWS_EXE, "windows", str(renamed)), public_key=env.pub, data_dir=env.data, temp_root=env.tmp,
        url_ok=lambda u: True, spawn_helper=env.handed.append, wait_pids=lambda: [1],
    )
    installer.install(info)
    plan = json.loads(env.handed[0].read_text(encoding="utf-8"))
    assert plan["files"][0]["dst"] == "MyShop.exe"


def test_installer_kind_plan_references_the_setup_file(env):
    setup = b"SETUP-BYTES" * 1000
    _i, _inf, result, _e = run_install(env, {"SmartBusinessLocal-1.2.0-windows-setup.exe": setup}, kind=ui.KIND_WINDOWS_SETUP)
    plan = json.loads(env.handed[0].read_text(encoding="utf-8"))
    update_apply.validate_plan(plan)
    assert plan["kind"] == ui.KIND_WINDOWS_SETUP and plan["setup_sha256"] == sha(setup) and result.status == "restart"
    assert (Path(plan["src_dir"]) / plan["setup_file"]).read_bytes() == setup


def test_portable_install_extracts_only_the_app_files_and_maps_the_exe_name(env):
    archive = portable_zip({"Windows/SmartBusinessLocal.exe": b"NEW-WIN", "Windows/extra/lib.dll": b"DLL", "macOS/SmartBusinessLocal": b"MAC", "SmartBusinessData/settings.json": b"USER-DATA"})
    _i, _inf, result, _e = run_install(env, {"SmartBusinessLocal-1.2.0-windows-portable.zip": archive}, kind=ui.KIND_PORTABLE)
    plan = json.loads(env.handed[0].read_text(encoding="utf-8"))
    update_apply.validate_plan(plan)
    assert plan["kind"] == ui.KIND_PORTABLE and result.status == "restart"
    assert {f["dst"] for f in plan["files"]} == {"SmartBusinessLocal.exe", "extra/lib.dll"}
    assert plan["target_dir"] == str(env.exe.parent) and plan["relaunch_exe"] == str(env.exe)
    for f in plan["files"]:
        assert sha((Path(plan["src_dir"]) / f["src"]).read_bytes()) == f["sha256"]


def test_portable_zip_without_the_exe_is_rejected(env):
    archive = portable_zip({"Windows/readme.txt": b"no exe here"})
    info = release(env.server, env.key, {"SmartBusinessLocal-1.2.0-windows-portable.zip": archive})
    with pytest.raises(ui.InstallError) as err:
        env.installer(ui.KIND_PORTABLE).install(info)
    assert err.value.detail == "no_exe" and env.handed == [] and staging_dirs(env) == []


def test_macos_linux_download_only_saves_a_verified_zip_without_backup_or_helper(env):
    archive = portable_zip({"macOS/SmartBusinessLocal": b"MAC"})
    info = release(env.server, env.key, {"SmartBusinessLocal-1.2.0-macos-portable.zip": archive})
    result = env.installer(ui.KIND_MANUAL, "macos").install(info)
    assert result.status == "downloaded" and Path(result.path).read_bytes() == archive
    assert Path(result.path).parent == env.root / "downloads"
    assert env.handed == [] and not (env.data / "backups").exists() and staging_dirs(env) == []


# --------------------------------------------------------- سناریوهای شکست/حمله ----

def test_wrong_signature_fails_before_the_big_download_and_changes_nothing(env):
    attacker, _ = make_key()
    info = release(env.server, env.key, {"SmartBusinessLocal-1.2.0-windows.exe": b"EVIL"}, sig_key=attacker)
    before = env.snapshot()
    with pytest.raises(ui.InstallError) as err:
        env.installer().install(info, before_handoff=lambda: pytest.fail("نباید به مرحله‌ی تحویل برسه"))
    assert err.value.code == "verify"
    assert "/SmartBusinessLocal-1.2.0-windows.exe" not in env.server["hits"]  # فایلِ اصلی اصلاً دانلود نشد
    assert env.handed == [] and not (env.data / "backups").exists() and staging_dirs(env) == []
    assert env.snapshot() == before and env.exe.read_bytes() == b"OLD-EXE"


def test_tampered_asset_with_valid_signature_is_rejected(env):
    real = b"REAL-BINARY"
    sums = f"{sha(real)}  SmartBusinessLocal-1.2.0-windows.exe\n".encode()
    info = release(env.server, env.key, {"SmartBusinessLocal-1.2.0-windows.exe": b"TAMPERED!!!"}, sums=sums)
    with pytest.raises(ui.InstallError) as err:
        env.installer().install(info)
    assert err.value.code in ("verify", "size_mismatch") and env.handed == [] and staging_dirs(env) == [] and not (env.data / "backups").exists()


def test_tampered_asset_same_size_hits_the_hash_check(env):
    real = b"A" * 64
    sums = f"{sha(real)}  SmartBusinessLocal-1.2.0-windows.exe\n".encode()
    info = release(env.server, env.key, {"SmartBusinessLocal-1.2.0-windows.exe": b"B" * 64}, sums=sums)
    with pytest.raises(ui.InstallError) as err:
        env.installer().install(info)
    assert err.value.code == "verify" and env.handed == [] and staging_dirs(env) == []


def test_asset_missing_from_the_signed_sums_is_rejected(env):
    sums = f"{sha(b'other')}  something-else.exe\n".encode()
    info = release(env.server, env.key, {"SmartBusinessLocal-1.2.0-windows.exe": b"NEW"}, sums=sums)
    with pytest.raises(ui.InstallError) as err:
        env.installer().install(info)
    assert err.value.code == "verify" and env.handed == []


def test_no_public_key_or_unsigned_release_is_manual_only(env):
    info = release(env.server, env.key, {"SmartBusinessLocal-1.2.0-windows.exe": b"NEW"})
    with pytest.raises(ui.InstallError) as err:
        env.installer(public_key="").install(info)
    assert err.value.code == "unsupported" and env.server["hits"] == []  # حتی یک درخواستِ شبکه هم نزد
    unsigned = UpdateInfo(version="1.2.0", tag="v1.2.0", html_url="https://github.com/x/y", assets=(Asset("SmartBusinessLocal-1.2.0-windows.exe", env.server["base"] + "/x", 3),))
    with pytest.raises(ui.InstallError):
        env.installer().install(unsigned)


def test_backup_failure_aborts_before_stopping_bots_or_starting_the_helper(env):
    def broken_backup(dest, **kw):
        raise OSError("disk full")

    info = release(env.server, env.key, {"SmartBusinessLocal-1.2.0-windows.exe": b"NEW"})
    with pytest.raises(ui.InstallError) as err:
        env.installer(backup_fn=broken_backup).install(info, before_handoff=lambda: pytest.fail("ربات‌ها نباید خاموش بشن"))
    assert err.value.code == "backup" and env.handed == [] and staging_dirs(env) == []


def test_helper_launch_failure_is_reported_and_cleaned_up(env):
    def cannot_spawn(plan_path):
        raise OSError("blocked")

    info = release(env.server, env.key, {"SmartBusinessLocal-1.2.0-windows.exe": b"NEW"})
    with pytest.raises(ui.InstallError) as err:
        env.installer(spawn_helper=cannot_spawn).install(info)
    assert err.value.code == "launch" and staging_dirs(env) == []


def test_before_handoff_errors_do_not_break_a_verified_install(env):
    info = release(env.server, env.key, {"SmartBusinessLocal-1.2.0-windows.exe": b"NEW"})

    def bad_hook():
        raise RuntimeError("manager.stop failed")

    assert env.installer().install(info, before_handoff=bad_hook).status == "restart" and len(env.handed) == 1


def test_cancel_during_download_aborts_cleanly(env):
    body = os.urandom(3 * ui.CHUNK_BYTES + 7)
    info = release(env.server, env.key, {"SmartBusinessLocal-1.2.0-windows.exe": body})
    installer = env.installer()

    def progress(phase, frac):
        if phase == "download" and frac:
            installer.cancel()

    with pytest.raises(ui.InstallError) as err:
        installer.install(info, progress)
    assert err.value.code == "cancelled" and env.handed == [] and staging_dirs(env) == [] and not installer.busy
    # بعد از لغو می‌شه دوباره امتحان کرد
    assert installer.install(info).status == "restart"


def test_second_install_while_one_is_running_is_refused_and_the_lock_is_released(env):
    gate = threading.Event()
    body = b"Q" * 400_000
    info = release(env.server, env.key, {"SmartBusinessLocal-1.2.0-windows.exe": body})
    env.server["routes"]["/SmartBusinessLocal-1.2.0-windows.exe"] = Route(body, gate=gate)
    installer = env.installer()
    outcome = {}
    worker = threading.Thread(target=lambda: outcome.update(result=installer.install(info)), daemon=True)
    worker.start()
    assert wait_until(lambda: "/SmartBusinessLocal-1.2.0-windows.exe" in env.server["hits"] and installer.busy, timeout=10)
    with pytest.raises(ui.InstallError) as err:
        installer.install(info)
    assert err.value.code == "busy"
    gate.set()
    worker.join(30)
    assert outcome["result"].status == "restart" and not installer.busy
    assert len(env.handed) == 1  # فقط یک helper


def test_unexpected_errors_are_wrapped_and_release_the_lock(env, monkeypatch):
    info = release(env.server, env.key, {"SmartBusinessLocal-1.2.0-windows.exe": b"NEW"})
    installer = env.installer()
    monkeypatch.setattr(ui.UpdateInstaller, "_make_backup", lambda self, progress: (_ for _ in ()).throw(ZeroDivisionError("bug")))
    with pytest.raises(ui.InstallError) as err:
        installer.install(info)
    assert err.value.code == "unexpected" and not installer.busy and staging_dirs(env) == []


# ---------------------------------------------------- پشتیبان‌ها، نتیجه و پاک‌سازی ----

def test_update_backups_are_pruned_to_the_newest_three(tmp_path):
    folder = tmp_path / "backups"
    folder.mkdir()
    for i in range(6):
        f = folder / f"before-update-2026010{i}-000000.zip"
        f.write_bytes(b"z")
        os.utime(f, (1_000_000 + i, 1_000_000 + i))
    manual = folder / "my-manual-backup.zip"
    manual.write_bytes(b"z")
    ui.prune_update_backups(tmp_path, keep=3)
    left = sorted(p.name for p in folder.iterdir())
    assert left == ["before-update-20260103-000000.zip", "before-update-20260104-000000.zip", "before-update-20260105-000000.zip", "my-manual-backup.zip"]


@pytest.mark.parametrize(
    "payload,version,expected",
    [
        ({"status": "ok", "from": "1.1.0", "to": "1.2.0"}, "1.2.0", "ok"),
        ({"status": "ok", "from": "1.1.0", "to": "v1.2.0"}, "1.2.0", "ok"),
        ({"status": "ok", "from": "1.1.0", "to": "1.2.0"}, "1.1.0", None),  # نسخه‌ی قدیمی دستی باز شده
        ({"status": "rolled_back", "from": "1.1.0", "to": "1.2.0", "detail": "unhealthy"}, "1.1.0", "rolled_back"),
        ({"status": "failed", "detail": "swap_failed"}, "1.1.0", "failed"),
        ({"status": "weird"}, "1.1.0", None),
        ([1, 2], "1.1.0", None),
    ],
)
def test_consume_update_result_is_one_shot_and_version_aware(tmp_path, payload, version, expected):
    (tmp_path / ui.RESULT_FILE).write_text(json.dumps(payload), encoding="utf-8")
    result = ui.consume_update_result(tmp_path, version)
    assert (result or {}).get("status") == expected
    assert not (tmp_path / ui.RESULT_FILE).exists()  # همیشه مصرف می‌شه
    assert ui.consume_update_result(tmp_path, version) is None


def test_consume_update_result_handles_missing_and_corrupt_files(tmp_path):
    assert ui.consume_update_result(tmp_path) is None
    (tmp_path / ui.RESULT_FILE).write_text("{oops", encoding="utf-8")
    assert ui.consume_update_result(tmp_path) is None and not (tmp_path / ui.RESULT_FILE).exists()


def test_stale_staging_folders_are_removed_but_fresh_ones_kept(tmp_path):
    old, fresh, other = tmp_path / f"{ui.STAGING_PREFIX}old", tmp_path / f"{ui.STAGING_PREFIX}fresh", tmp_path / "unrelated"
    for folder in (old, fresh, other):
        folder.mkdir()
        (folder / "f").write_bytes(b"x")
    two_hours_ago = time.time() - 7200
    os.utime(old, (two_hours_ago, two_hours_ago))
    os.utime(other, (two_hours_ago, two_hours_ago))
    assert ui.cleanup_stale_staging(tmp_path) == 1
    assert not old.exists() and fresh.exists() and other.exists()


def test_launch_helper_copies_the_exe_and_runs_the_copy_with_the_plan(tmp_path):
    exe = tmp_path / "SmartBusinessLocal.exe"
    exe.write_bytes(b"EXE-BYTES")
    plan = tmp_path / "stage" / "plan.json"
    plan.parent.mkdir()
    plan.write_text("{}", encoding="utf-8")
    calls = []
    ui.launch_helper(plan, exe=str(exe), spawn=lambda argv, cwd=None: calls.append((argv, cwd)))
    ((argv, cwd),) = calls
    helper = plan.parent / "helper" / "SmartBusinessLocal.exe"
    assert helper.read_bytes() == b"EXE-BYTES" and argv == [helper, "--apply-update", str(plan)] and cwd == helper.parent
    assert helper != exe  # خودِ exeِ اصلی بعد از خروج آزاد می‌مونه


def test_default_wait_pids_contains_the_current_process():
    assert os.getpid() in ui._wait_pids()


def test_installer_inno_script_has_the_directives_the_silent_update_relies_on():
    text = (Path(__file__).parent.parent / "installer" / "SmartBusinessLocal.iss").read_text(encoding="utf-8")
    from app.core import app_mutex

    assert f"AppMutex={app_mutex.MUTEX_NAME}" in text
    assert "CloseApplications=yes" in text and "RestartApplications=yes" in text
    assert "PrivilegesRequired=lowest" in text  # نصبِ بی‌صدا بدونِ UAC


def test_app_mutex_is_a_safe_noop_off_windows():
    from app.core import app_mutex

    assert app_mutex.acquire() is (os.name == "nt" and app_mutex._handle is not None)
