"""اسکریپتِ بسته‌بندیِ ۱.۰.۰: سه آرتیفکتِ واقعی (تک‌فایل + نصب‌کننده / zipِ مک / tar.gzِ لینوکس)،
بدونِ هیچ اثری از نسخه‌ی قابل‌حمل، با بیتِ اجرایی حفظ‌شده و با گاردِ «هیچ داده‌ی کاربر/مدلی داخلِ بسته»."""

import hashlib
import importlib.util
import io
import os
import stat
import tarfile
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "package_release.py"

MACHO_MAGIC = b"\xcf\xfa\xed\xfe"  # Mach-O 64-bit little-endian (جادوی واقعی، تا تشخیصِ اجرایی روی میزبانِ ویندوز هم کار کنه)

SPEC = importlib.util.spec_from_file_location("package_release", SCRIPT)


@pytest.fixture(scope="module")
def pkg():
    module = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(module)
    return module


def try_symlink(target: str, link: Path) -> bool:
    """ساختِ symlink روی ویندوزِ بدونِ Developer Mode ممکن نیست؛ در آن صورت تستِ مربوط رد می‌شه."""
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        return False
    return True


def make_dist(tmp_path, os_name):
    dist = tmp_path / "dist"
    dist.mkdir()
    if os_name == "windows":
        (dist / "SmartBusinessLocal.exe").write_bytes(b"MZ-fake-exe")
    elif os_name == "linux":
        binary = dist / "SmartBusinessLocal"
        binary.write_bytes(b"\x7fELF-fake")  # ELF واقعی؛ بیتِ اجرایی از محتوا تشخیص داده می‌شه
        binary.chmod(0o644)  # عمداً بدونِ +x: میزبانِ ویندوزی هرگز +x نمی‌دهد
    else:
        app = dist / "SmartBusinessLocal.app" / "Contents" / "MacOS"
        app.mkdir(parents=True)
        (app / "SmartBusinessLocal").write_bytes(MACHO_MAGIC + b"-fake")
        frameworks = dist / "SmartBusinessLocal.app" / "Contents" / "Frameworks"
        frameworks.mkdir()
        (frameworks / "libreal.dylib").write_bytes(b"lib")
        if not try_symlink("libreal.dylib", frameworks / "liblink.dylib"):
            (frameworks / "liblink.dylib").write_bytes(b"not-a-symlink-here")
    return dist


def names(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        return zf.namelist()


# ------------------------------------------------------------------ چیدمانِ تحویل ----------------


def test_windows_outputs_single_exe_installer_and_sums(pkg, tmp_path):
    dist = make_dist(tmp_path, "windows")
    out = tmp_path / "release"
    out.mkdir()
    setup = out / "SmartBusinessLocal-1.2.3-windows-setup.exe"  # خروجیِ Inno Setup (OutputDir=..\release)
    setup.write_bytes(b"MZ-setup")
    assert pkg.main(["--os", "windows", "--dist", str(dist), "--out", str(out), "--version", "1.2.3"]) == 0
    assert sorted(p.name for p in out.iterdir()) == [
        "SHA256SUMS.txt",
        "SmartBusinessLocal-1.2.3-windows-setup.exe",
        "SmartBusinessLocal-1.2.3-windows.exe",
    ]
    assert (out / "SmartBusinessLocal-1.2.3-windows.exe").read_bytes() == b"MZ-fake-exe"
    assert setup.read_bytes() == b"MZ-setup"  # نصب‌کننده دست‌نخورده و در فهرستِ هش هست


def test_windows_without_installer_still_ships_exe(pkg, tmp_path):
    dist = make_dist(tmp_path, "windows")
    out = tmp_path / "release"
    pkg.main(["--os", "windows", "--dist", str(dist), "--out", str(out), "--version", "1.0.0"])
    assert sorted(p.name for p in out.iterdir()) == ["SHA256SUMS.txt", "SmartBusinessLocal-1.0.0-windows.exe"]


def test_macos_delivers_a_zip_and_linux_a_tar_gz(pkg, tmp_path):
    for os_name, filename, builder in (
        ("macos", "SmartBusinessLocal-9.9.9-macos.zip", zipfile.ZipFile),
        ("linux", "SmartBusinessLocal-9.9.9-linux.tar.gz", tarfile.open),
    ):
        workdir = tmp_path / os_name
        workdir.mkdir()
        dist = make_dist(workdir, os_name)
        out = tmp_path / f"release-{os_name}"
        pkg.main(["--os", os_name, "--dist", str(dist), "--out", str(out), "--version", "9.9.9"])
        assert sorted(p.name for p in out.iterdir()) == ["SHA256SUMS.txt", filename]
        if os_name == "macos":
            with builder(out / filename) as archive:
                assert archive.testzip() is None
        else:
            with builder(out / filename, "r:gz") as archive:
                assert [m.name for m in archive.getmembers() if m.isfile()] == ["SmartBusinessLocal"]


def test_no_portable_edition_left_anywhere(pkg, tmp_path):
    """نسخه‌ی فلش حذف شده: نه portable.flag، نه SmartBusinessData، نه README-PORTABLE، نه زیپِ portable."""
    dist = make_dist(tmp_path, "windows")
    out = tmp_path / "release"
    pkg.build("windows", dist, out, "1.0.0")
    listing = [p.name for p in out.iterdir()]
    assert not any("portable" in n.lower() for n in listing)
    assert not any(n.endswith(".zip") for n in listing)

    # درونِ بسته‌های مک/لینوکس هم نباید اثری از چیدمانِ قابل‌حمل باشه
    workdir = tmp_path / "mac"
    workdir.mkdir()
    mac_zip = pkg.build_zip(pkg.find_artifact("macos", make_dist(workdir, "macos")), "1.0.0", workdir / "out", "macos")
    assert not any("portable" in n.lower() or "SmartBusinessData" in n for n in names(mac_zip))

    src = SCRIPT.read_text(encoding="utf-8")
    for gone in ("PORTABLE_DIR_NAME", "PORTABLE_FLAG_NAME", "MODE_PORTABLE", "is_portable", "find_portable_dir", "build_portable_zip", "SmartBusinessLocal-Portable"):
        assert gone not in src, f"{gone} هنوز در اسکریپتِ بسته‌بندی هست در حالی که نسخه‌ی قابل‌حمل حذف شده"
    for attr in ("build_portable_zip", "README_PORTABLE", "PORTABLE_ROOT", "OS_FOLDERS"):
        assert not hasattr(pkg, attr)


# ----------------------------------------------------------- بیتِ اجرایی و symlinkها ---------------


def test_linux_executable_bit_survives_the_tar(pkg, tmp_path):
    dist = make_dist(tmp_path, "linux")
    tar_path = pkg.build_tar_gz(pkg.find_artifact("linux", dist), "1.0.0", tmp_path / "out")
    with tarfile.open(tar_path, "r:gz") as tf:
        member = tf.getmember("SmartBusinessLocal")
    assert member.mode & 0o111, "بدونِ بیتِ اجرایی، کاربرِ لینوکس باید chmod بزنه"
    assert member.isfile() and not member.issym()


def test_macos_app_bundle_keeps_the_exec_bit(pkg, tmp_path):
    dist = make_dist(tmp_path, "macos")
    artifact = pkg.find_artifact("macos", dist)
    assert artifact.name == "SmartBusinessLocal.app"
    zip_path = pkg.build_zip(artifact, "1.0.0", tmp_path / "out", "macos")
    root = "SmartBusinessLocal.app/Contents"
    with zipfile.ZipFile(zip_path) as zf:
        assert (zf.getinfo(f"{root}/MacOS/SmartBusinessLocal").external_attr >> 16) & 0o111, "باندلِ بدونِ +x اجرا نمی‌شه"
        assert f"{root}/Frameworks/libreal.dylib" in zf.namelist()


def test_macos_app_bundle_keeps_symlinks_as_symlinks(pkg, tmp_path):
    """باندلِ مک پر از symlink است؛ باید symlink بمونند (دنبال‌کردنشان باندل را خراب و چندبرابر می‌کند)."""
    dist = make_dist(tmp_path, "macos")
    link = dist / "SmartBusinessLocal.app" / "Contents" / "Frameworks" / "liblink.dylib"
    if not link.is_symlink():
        pytest.skip("ساختِ symlink روی این میزبان (ویندوزِ بدونِ Developer Mode) ممکن نیست")
    zip_path = pkg.build_zip(pkg.find_artifact("macos", dist), "1.0.0", tmp_path / "out", "macos")
    with zipfile.ZipFile(zip_path) as zf:
        info = zf.getinfo("SmartBusinessLocal.app/Contents/Frameworks/liblink.dylib")
        assert stat.S_ISLNK(info.external_attr >> 16)
        assert zf.read(info).decode() == "libreal.dylib"


def test_zip_stores_symlinks_without_needing_privileges(pkg, tmp_path, monkeypatch):
    """همین مسیرِ کد روی ویندوز (که تستِ symlinkِ واقعی skip می‌شه) را می‌پوشونه:
    ``_add_symlink`` باید نوعِ unix-symlink را بنویسه، نه محتوای فایل."""
    monkeypatch.setattr(pkg.os, "readlink", lambda _p: "Versions/A/libreal.dylib")
    zip_path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        pkg._add_symlink(zf, tmp_path / "whatever", "Frameworks/libreal.dylib")
    with zipfile.ZipFile(zip_path) as zf:
        info = zf.getinfo("Frameworks/libreal.dylib")
        assert stat.S_ISLNK(info.external_attr >> 16)
        assert zf.read(info).decode() == "Versions/A/libreal.dylib"


def test_exec_bit_is_decided_by_content_not_the_build_host(pkg, tmp_path):
    """میزبانِ ویندوزی هیچ‌وقت +x ندارد (st_mode=۰o666)؛ پس تشخیص از جادوی فایل انجام می‌شه."""
    binary = tmp_path / "dist" / "SmartBusinessLocal"
    binary.parent.mkdir()
    binary.write_bytes(b"\x7fELF-binary")
    binary.chmod(0o644)
    assert pkg.effective_mode(binary, "SmartBusinessLocal") & 0o111
    text = tmp_path / "dist" / "README.txt"
    text.write_text("hello", encoding="utf-8")
    assert not pkg.effective_mode(text, "README.txt") & 0o111


# ------------------------------------------------------------------------- SHA256SUMS -----------


def test_sha256sums_covers_every_produced_file(pkg, tmp_path):
    dist = make_dist(tmp_path, "linux")
    out = tmp_path / "release"
    pkg.build("linux", dist, out, "1.0.0")
    sums = (out / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    listed = {line.split("  ", 1)[1] for line in sums}
    assert listed == {"SmartBusinessLocal-1.0.0-linux.tar.gz"}, "فهرستِ هش نباید خودش را دربربگیره"
    for line in sums:
        digest, name = line.split("  ", 1)
        assert digest == hashlib.sha256((out / name).read_bytes()).hexdigest()


def test_sums_name_can_be_per_platform_for_ci(pkg, tmp_path):
    dist = make_dist(tmp_path, "macos")
    out = tmp_path / "release"
    created = pkg.build("macos", dist, out, "1.0.0", sums_name="SHA256SUMS-macos.txt")
    assert (out / "SHA256SUMS-macos.txt").is_file()
    assert created[-1].name == "SHA256SUMS-macos.txt"


def test_installer_can_be_given_explicitly(pkg, tmp_path):
    dist = make_dist(tmp_path, "windows")
    other = tmp_path / "elsewhere" / "setup.exe"
    other.parent.mkdir()
    other.write_bytes(b"MZ-setup")
    out = tmp_path / "release"
    created = pkg.build("windows", dist, out, "1.0.0", installer=other)
    assert other in created
    with pytest.raises(SystemExit):
        pkg.find_windows_installer(out, "1.0.0", tmp_path / "missing.exe")


# ------------------------------------------------- گاردِ «داده‌ی کاربر/مدل داخلِ بسته نباشد» --------


def test_user_data_violations_flags_data_receipts_and_models(pkg):
    ok = [
        "dist/SmartBusinessLocal.exe",
        "dist/_internal/lib/x.so",
        "SmartBusinessLocal.app/Contents/MacOS/SmartBusinessLocal",
        "SmartBusinessLocal.app/Contents/Resources/assets/fonts/Vazirmatn-Regular.ttf",
    ]
    assert pkg.user_data_violations(ok) == []
    bad = [
        "root/receipts/",
        "root/receipts/order-1789.jpg",  # پوشه‌ی جدیدِ تصاویرِ رسید (app/core/bot_manager.py)
        "root/models/qwen.gguf",
        "root/models/qwen.gguf.part",  # دانلودِ نیمه‌کاره هم نباید بسته بشه
        "root/settings.json",
        "root/secret.key",
        "root/x/conversations.db",
        "root/x/orders.db-wal",
        "root/backups/",
        "root/backups/SmartBusiness-backup-1.zip",
        "root/product_photos/",
        "root/product_photos/1.png",
        "root/invoices/invoice-1.pdf",
        "root/bot.log",
        "root/heartbeat.json",
    ]
    assert pkg.user_data_violations(bad) == bad


def test_a_lone_gguf_anywhere_in_the_tree_is_refused(pkg, tmp_path):
    """رگرسیون: مدل هرگز داخلِ نصب‌کننده نمی‌ره — برنامه آن را در زمانِ اجرا دانلود می‌کنه.
    حتی اگر کاربر/توسعه‌دهنده مدل را کنارِ کد گذاشته باشه، ساخت باید بشکنه نه اینکه ۴ گیگ دانلود شود."""
    bundle = tmp_path / "SmartBusinessLocal"
    (bundle / "_internal" / "models").mkdir(parents=True)
    (bundle / "_internal" / "model.py").write_text("x = 1", encoding="utf-8")
    (bundle / "_internal" / "models" / "qwen.gguf").write_bytes(b"GGUF-fake")
    with pytest.raises(SystemExit) as info:
        pkg.verify_tree_has_no_user_data(bundle)
    assert "qwen.gguf" in str(info.value)


def test_receipt_images_in_the_tree_are_refused(pkg, tmp_path):
    bundle = tmp_path / "SmartBusinessLocal"
    (bundle / "receipts").mkdir(parents=True)
    (bundle / "receipts" / "order-42.jpg").write_bytes(b"jpeg")
    with pytest.raises(SystemExit) as info:
        pkg.verify_tree_has_no_user_data(bundle)
    assert "receipts" in str(info.value)


def test_shipped_archives_are_verified_and_dirty_ones_rejected(pkg, tmp_path):
    exe = tmp_path / "SmartBusinessLocal.exe"
    exe.write_bytes(b"MZ")
    clean = pkg.build_zip(exe, "1.1.0", tmp_path / "out", "macos")
    pkg.verify_zip_has_no_user_data(clean)
    clean_tar = pkg.build_tar_gz(exe, "1.1.0", tmp_path / "out2", "linux")
    pkg.verify_tar_has_no_user_data(clean_tar)

    dirty = tmp_path / "dirty.zip"
    with zipfile.ZipFile(dirty, "w") as zf:
        zf.writestr("root/receipts/order-1.jpg", "x")
    with pytest.raises(SystemExit):
        pkg.verify_zip_has_no_user_data(dirty)

    dirty_tar = tmp_path / "dirty.tar.gz"
    with tarfile.open(dirty_tar, "w:gz") as tf:
        info = tarfile.TarInfo("root/models/qwen.gguf")
        info.size = 1
        tf.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(SystemExit):
        pkg.verify_tar_has_no_user_data(dirty_tar)


def test_missing_artifact_gives_a_clear_error(pkg, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "something-else.txt").write_text("x")
    with pytest.raises(SystemExit) as info:
        pkg.find_artifact("windows", dist)
    assert "something-else.txt" in str(info.value)
    with pytest.raises(SystemExit):
        pkg.find_artifact("linux", tmp_path / "does-not-exist")


def test_unknown_os_is_rejected(pkg, tmp_path):
    with pytest.raises(SystemExit):
        pkg.build("android", tmp_path, tmp_path / "out", "1.0.0")


def test_the_real_app_and_assets_trees_are_clean(pkg):
    pkg.verify_tree_has_no_user_data(pkg.ROOT / "app")
    assets = pkg.ROOT / "assets"
    if assets.is_dir():
        pkg.verify_tree_has_no_user_data(assets)
