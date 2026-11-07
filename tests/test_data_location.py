"""محلِ پیش‌فرضِ داده: نصبِ تازه‌ی ویندوز روی درایوِ محلِ نصب می‌رود (نه C:)، کاربرِ قدیمی
داده‌اش همان‌جا می‌ماند، و متغیر محیطی بر همه اولویت دارد."""

import sys
from pathlib import Path

from app.core import paths


def win_install(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.delenv(paths.ENV_DATA_DIR, raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(paths, "app_anchor", lambda: Path(r"D:\Program Files\SmartBusinessLocal"))
    return tmp_path


def test_fresh_windows_install_puts_data_on_the_install_drive(monkeypatch, tmp_path):
    win_install(monkeypatch, tmp_path)
    directory, mode = paths.resolve_data_dir()
    assert mode == paths.MODE_INSTALL
    assert directory == Path("D:\\") / paths.APP_DIR_NAME and directory.drive == "D:"


def test_existing_user_data_is_never_stranded_on_c(monkeypatch, tmp_path):
    win_install(monkeypatch, tmp_path)
    old = Path(paths._system_default_dir())
    old.mkdir(parents=True)
    (old / "settings.json").write_text("{}", encoding="utf-8")
    directory, mode = paths.resolve_data_dir()
    assert mode == paths.MODE_SYSTEM and directory == old


def test_env_override_beats_the_install_drive(monkeypatch, tmp_path):
    win_install(monkeypatch, tmp_path)
    target = tmp_path / "custom"
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(target))
    directory, mode = paths.resolve_data_dir()
    assert mode == paths.MODE_ENV and directory == target


def test_source_run_keeps_the_system_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.delenv(paths.ENV_DATA_DIR, raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    directory, mode = paths.resolve_data_dir()
    assert mode == paths.MODE_SYSTEM and directory == Path(paths._system_default_dir())


def test_linux_install_has_no_drive_letter_and_stays_system(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv(paths.ENV_DATA_DIR, raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(paths, "app_anchor", lambda: Path("/opt/sbl"))
    directory, mode = paths.resolve_data_dir()
    assert mode == paths.MODE_SYSTEM and directory == tmp_path / "xdg" / paths.APP_DIR_NAME


def test_get_app_data_dir_creates_the_install_drive_folder(monkeypatch, tmp_path):
    win_install(monkeypatch, tmp_path)
    directory = paths.get_app_data_dir()
    assert directory.is_dir() and directory.drive == "D:"
    assert paths.data_dir_mode() == paths.MODE_INSTALL
