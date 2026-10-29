"""اسکریپتِ بسته‌بندی: چیدمانِ zip باید *واقعاً* حالتِ قابل‌حمل رو فعال کنه."""

import importlib.util
import os
import stat
import sys
import zipfile
from pathlib import Path

import pytest

from app.core import paths

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "package_release.py"


@pytest.fixture(scope="module")
def pkg():
    spec = importlib.util.spec_from_file_location("package_release", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_dist(tmp_path, os_name):
    dist = tmp_path / "dist"
    dist.mkdir()
    if os_name == "windows":
        (dist / "SmartBusinessLocal.exe").write_bytes(b"MZ-fake-exe")
    elif os_name == "linux":
        binary = dist / "SmartBusinessLocal"
        binary.write_bytes(b"\x7fELF-fake")
        binary.chmod(0o755)
    else:
        app = dist / "SmartBusinessLocal.app" / "Contents" / "MacOS"
        app.mkdir(parents=True)
        (app / "SmartBusinessLocal").write_bytes(b"macho-fake")
        (app / "SmartBusinessLocal").chmod(0o755)
        frameworks = dist / "SmartBusinessLocal.app" / "Contents" / "Frameworks"
        frameworks.mkdir()
        (frameworks / "libreal.dylib").write_bytes(b"lib")
        os.symlink("libreal.dylib", frameworks / "liblink.dylib")  # bundleهای مک پر از symlink‌ان
    return dist


def names(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        return zf.namelist()


def test_windows_outputs_portable_zip_and_raw_exe(pkg, tmp_path):
    dist = make_dist(tmp_path, "windows")
    out = tmp_path / "release"
    assert pkg.main(["--os", "windows", "--dist", str(dist), "--out", str(out), "--version", "1.2.3"]) == 0
    assert sorted(p.name for p in out.iterdir()) == [
        "SmartBusinessLocal-1.2.3-windows-portable.zip",
        "SmartBusinessLocal-1.2.3-windows.exe",
    ]
    assert (out / "SmartBusinessLocal-1.2.3-windows.exe").read_bytes() == b"MZ-fake-exe"
    listing = names(out / "SmartBusinessLocal-1.2.3-windows-portable.zip")
    assert "SmartBusinessLocal-Portable/portable.flag" in listing
    assert "SmartBusinessLocal-Portable/README-PORTABLE.txt" in listing
    assert "SmartBusinessLocal-Portable/SmartBusinessData/" in listing
    assert "SmartBusinessLocal-Portable/Windows/SmartBusinessLocal.exe" in listing


def test_linux_and_macos_have_no_raw_asset_only_portable_zip(pkg, tmp_path):
    for os_name in ("linux", "macos"):
        workdir = tmp_path / os_name
        workdir.mkdir()
        dist = make_dist(workdir, os_name)
        out = tmp_path / f"release-{os_name}"
        pkg.main(["--os", os_name, "--dist", str(dist), "--out", str(out), "--version", "9.9.9"])
        assert [p.name for p in out.iterdir()] == [f"SmartBusinessLocal-9.9.9-{os_name}-portable.zip"]


def test_linux_executable_bit_survives_the_zip(pkg, tmp_path):
    dist = make_dist(tmp_path, "linux")
    zip_path = pkg.build_portable_zip("linux", pkg.find_artifact("linux", dist), "1.0.0", tmp_path / "out")
    with zipfile.ZipFile(zip_path) as zf:
        info = zf.getinfo("SmartBusinessLocal-Portable/Linux/SmartBusinessLocal")
    assert (info.external_attr >> 16) & 0o111, "بدونِ بیتِ اجرایی، کاربرِ لینوکس باید chmod بزنه"


def test_macos_app_bundle_keeps_symlinks_and_exec_bit(pkg, tmp_path):
    dist = make_dist(tmp_path, "macos")
    artifact = pkg.find_artifact("macos", dist)
    assert artifact.name == "SmartBusinessLocal.app"
    zip_path = pkg.build_portable_zip("macos", artifact, "1.0.0", tmp_path / "out")
    root = "SmartBusinessLocal-Portable/macOS/SmartBusinessLocal.app/Contents"
    with zipfile.ZipFile(zip_path) as zf:
        link = zf.getinfo(f"{root}/Frameworks/liblink.dylib")
        assert stat.S_ISLNK(link.external_attr >> 16)
        assert zf.read(link).decode() == "libreal.dylib"
        assert (zf.getinfo(f"{root}/MacOS/SmartBusinessLocal").external_attr >> 16) & 0o111


def test_missing_artifact_gives_a_clear_error(pkg, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "something-else.txt").write_text("x")
    with pytest.raises(SystemExit) as info:
        pkg.find_artifact("windows", dist)
    assert "something-else.txt" in str(info.value)
    with pytest.raises(SystemExit):
        pkg.find_artifact("linux", tmp_path / "does-not-exist")


def test_shipped_layout_really_activates_portable_mode(pkg, tmp_path, monkeypatch):
    """پایانی‌ترین تست: zip رو باز می‌کنیم، «اجرا از داخلِ پوشه‌ی Windows» رو شبیه‌سازی می‌کنیم و
    می‌بینیم برنامه واقعاً SmartBusinessData کنارِ پوشه‌ی سیستم‌عامل رو انتخاب می‌کنه."""
    dist = make_dist(tmp_path, "windows")
    zip_path = pkg.build_portable_zip("windows", pkg.find_artifact("windows", dist), "1.0.0", tmp_path / "out")
    drive = tmp_path / "usb"
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(drive)
    root = drive / "SmartBusinessLocal-Portable"
    exe_dir = root / "Windows"
    assert (exe_dir / "SmartBusinessLocal.exe").is_file()

    monkeypatch.setattr(paths, "app_anchor", lambda: exe_dir)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert paths.is_portable()
    assert paths.get_app_data_dir() == (root / "SmartBusinessData").resolve()


def test_two_systems_share_one_data_folder_when_extracted_together(pkg, tmp_path, monkeypatch):
    drive = tmp_path / "usb"
    for os_name in ("windows", "linux"):
        sub = tmp_path / f"build-{os_name}"
        sub.mkdir()
        dist = make_dist(sub, os_name)
        zip_path = pkg.build_portable_zip(os_name, pkg.find_artifact(os_name, dist), "1.0.0", tmp_path / f"out-{os_name}")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(drive)
    root = drive / "SmartBusinessLocal-Portable"
    assert (root / "Windows" / "SmartBusinessLocal.exe").is_file() and (root / "Linux" / "SmartBusinessLocal").is_file()

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    results = set()
    for folder in ("Windows", "Linux"):
        monkeypatch.setattr(paths, "app_anchor", lambda folder=folder: root / folder)
        results.add(paths.get_app_data_dir())
    assert results == {(root / "SmartBusinessData").resolve()}, "هر دو سیستم‌عامل یه پوشه‌ی داده‌ی مشترک می‌بینن"


def test_readme_is_bilingual_english_first(pkg):
    text = pkg.README_PORTABLE
    assert text.index("ENGLISH") < text.index("فارسی")
    assert "SmartBusinessData" in text and "chmod +x" in text


# ----------------------------------------------- N2: بسته‌ی انتشار = کاملاً خالی از داده‌ی کاربر ----

def test_user_data_violations_flags_data_but_allows_the_empty_portable_data_folder(pkg):
    ok = ["Root/", "Root/SmartBusinessData/", "Root/portable.flag", "Root/Windows/SmartBusinessLocal.exe", "Root/Windows/_internal/lib/x.so"]
    assert pkg.user_data_violations(ok) == []
    bad = [
        "Root/SmartBusinessData/settings.json",
        "Root/SmartBusinessData/sub/",
        "Root/x/conversations.db",
        "Root/x/orders.db-wal",
        "Root/models/qwen.gguf",
        "Root/secret.key",
        "Root/backups/",
        "Root/backups/SmartBusiness-backup-1.zip",
        "Root/bot.log",
    ]
    assert pkg.user_data_violations(bad) == bad


def test_portable_zip_is_verified_clean_and_a_dirty_zip_is_rejected(pkg, tmp_path):
    exe = tmp_path / "SmartBusinessLocal.exe"
    exe.write_bytes(b"MZ")
    clean = pkg.build_portable_zip("windows", exe, "1.1.0", tmp_path / "out")
    pkg.verify_zip_has_no_user_data(clean)  # بی‌صدا
    dirty = tmp_path / "dirty.zip"
    with zipfile.ZipFile(dirty, "w") as zf:
        zf.writestr("Root/SmartBusinessData/settings.json", "{}")
    with pytest.raises(SystemExit):
        pkg.verify_zip_has_no_user_data(dirty)


def test_source_tree_check_rejects_data_files_that_would_be_bundled(pkg, tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("x = 1", encoding="utf-8")
    pkg.verify_tree_has_no_user_data(tmp_path)  # تمیز
    (tmp_path / "pkg" / "conversations.db").write_bytes(b"x")
    with pytest.raises(SystemExit):
        pkg.verify_tree_has_no_user_data(tmp_path)


def test_the_real_app_and_assets_trees_are_clean(pkg):
    pkg.verify_tree_has_no_user_data(pkg.ROOT / "app")
    assets = pkg.ROOT / "assets"
    if assets.is_dir():
        pkg.verify_tree_has_no_user_data(assets)
