"""جایِ ذخیره‌ی مدل: پیش‌فرض روی درایوِ نصب، قابلِ تغییر توسط مالک، و هرگز جابه‌جایِ مدلِ موجود.

هیچ تستی چیزی روی درایوِ واقعی نمی‌سازد: ``install_drive_models_dir`` فقط مسیر حساب می‌کند
(بدونِ نوشتن روی دیسک) و برایِ قاعده‌ی «بساز و برو آنجا» از پوشه‌ی موقتِ خودِ تست استفاده می‌شود.
"""

import os
import sys

import pytest
from fake_page import FakePage, collect_text, find

from app.core import hardware, paths, quickstart, settings as settings_module
from app.screens import ai_select

FILE = "Qwen3.5-2B-Q4_K_S.gguf"


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """پوشه‌ی داده‌ی جدا برایِ هر تست (همان چیزی که ``get_app_data_dir`` می‌سازد)."""
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(paths, "get_app_data_dir", lambda: d)
    return d


# --------------------------------------------------------------- قاعده‌یِ پیش‌فرض


def test_running_from_source_keeps_models_in_the_data_dir(data_dir, monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert paths.default_model_dir() == data_dir / "models"


@pytest.mark.skipif(os.name != "nt", reason="حرفِ درایو فقط روی ویندوز وجود دارد")
def test_packaged_windows_install_targets_the_install_drive(monkeypatch):
    """ویندوز روی C:، برنامه روی D: ⇒ مدل روی D: و بیرون از پوشه‌ی نصب (حذفِ برنامه آن را پاک نمی‌کند)."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    got = paths.install_drive_models_dir(
        r"D:\Apps\SmartBusinessLocal\SmartBusinessLocal.exe",
        r"C:\Users\me\AppData\Roaming\SmartBusinessLocal",
    )
    assert got is not None
    assert got.name == "models" and got.parent.name == paths.APP_DIR_NAME
    assert str(got).upper().startswith("D:")


@pytest.mark.skipif(os.name != "nt", reason="مقایسه‌ی دو درایوِ هم‌حرف فقط روی ویندوز معنا دارد")
def test_windows_install_on_the_windows_drive_changes_nothing(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert paths.install_drive_models_dir(
        r"C:\Apps\SmartBusinessLocal\SmartBusinessLocal.exe",
        r"C:\Users\me\AppData\Roaming\SmartBusinessLocal",
    ) is None


def test_paths_without_a_drive_letter_never_relocate(monkeypatch):
    """این شاخه روی هر سه سیستم‌عامل اجرا می‌شه: لینوکس و مک حرفِ درایو ندارند، پس جای مدل
    هرگز خودبه‌خود عوض نمی‌شه (و روی ویندوز هم همین مسیرها بی‌درایو خوانده می‌شن)."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert paths.install_drive_models_dir(
        "/opt/SmartBusinessLocal/SmartBusinessLocal",
        "/home/me/.local/share/SmartBusinessLocal",
    ) is None


def test_a_model_that_is_already_downloaded_is_never_relocated(data_dir, monkeypatch, tmp_path):
    """کاربری که مدلی دارد، با این تغییرِ پیش‌فرض آن را «گم» نمی‌کند (و ۱۲ گیگ دوباره دانلود نمی‌کند)."""
    old = data_dir / "models"
    old.mkdir(parents=True)
    (old / FILE).write_bytes(b"GGUF")
    monkeypatch.setattr(paths, "install_drive_models_dir", lambda: tmp_path / "other-drive" / "models")
    assert paths.default_model_dir() == old


def test_a_half_downloaded_file_also_keeps_the_old_place(data_dir, monkeypatch, tmp_path):
    old = data_dir / "models"
    old.mkdir(parents=True)
    (old / (FILE + ".part")).write_bytes(b"x")
    monkeypatch.setattr(paths, "install_drive_models_dir", lambda: tmp_path / "other-drive" / "models")
    assert paths.default_model_dir() == old


def test_empty_install_moves_to_the_install_drive(data_dir, monkeypatch, tmp_path):
    target = tmp_path / "D-root" / "SmartBusinessLocal" / "models"
    monkeypatch.setattr(paths, "install_drive_models_dir", lambda: target)
    assert paths.default_model_dir() == target
    assert target.is_dir()  # تا «فضایِ آزادِ این مسیر» و برچسبِ «جا می‌شه» عددِ درست بدهند


def test_an_unwritable_target_falls_back_to_the_data_dir(data_dir, monkeypatch, tmp_path):
    blocked = tmp_path / "afile"
    blocked.write_bytes(b"not a folder")
    monkeypatch.setattr(paths, "install_drive_models_dir", lambda: blocked / "models")
    assert paths.default_model_dir() == data_dir / "models"


def test_the_owner_choice_beats_every_rule(data_dir, monkeypatch, tmp_path):
    mine = tmp_path / "E" / "models"
    monkeypatch.setattr(paths, "install_drive_models_dir", lambda: tmp_path / "elsewhere")
    s = settings_module.AppSettings(model_storage_path=str(mine))
    assert s.get_model_storage_dir() == mine


def test_changing_the_location_does_not_move_an_existing_model(data_dir, tmp_path):
    """راهنما همین را می‌گوید: مدلِ دانلودشده جابه‌جا نمی‌شه، پس عوض‌کردنِ مسیر فایل را گم می‌کند."""
    from app.core import ai_engine

    old = data_dir / "models"
    old.mkdir(parents=True)
    (old / FILE).write_bytes(b"GGUF")
    s = settings_module.AppSettings(model_id="qwen35-2b")
    assert s.get_model_storage_dir() == old
    assert ai_engine.resolve_model_path(s) == old / FILE

    s.model_storage_path = str(tmp_path / "elsewhere")
    assert ai_engine.resolve_model_path(s) == tmp_path / "elsewhere" / FILE
    assert not (tmp_path / "elsewhere" / FILE).exists()  # همان‌جا چیزی نیست؛ برنامه «دانلود نشده» می‌گوید


# ------------------------------------------------------------ دیده‌شدنِ مسیر در UI


def _calm_hardware(monkeypatch):
    """بدونِ subprocess و بدونِ psutil؛ همان کاری که تست‌هایِ صفحه‌های AI می‌کنند."""
    hw = hardware.HardwareInfo(ram_gb=16.0, cpu_cores=12, cpu_model="Test CPU X", gpu_model="",
                               gpu_vram_gb=None, free_disk_gb=200.0)
    monkeypatch.setattr(hardware, "detect", lambda force=False, disk_path=None: hw)
    monkeypatch.setattr(hardware, "free_disk_gb_at", lambda path: 200.0)


def test_the_model_step_shows_where_the_model_will_be_saved(monkeypatch, data_dir, tmp_path):
    _calm_hardware(monkeypatch)
    monkeypatch.setattr(paths, "install_drive_models_dir", lambda: tmp_path / "D-root" / "models")
    s = settings_module.AppSettings()
    page = FakePage()
    ctl = ai_select.build(page, "fa", s, lambda: None, lambda: None, lambda: None)
    line = collect_text(find(ctl, "ai_storage_line"))
    assert "D-root" in line
    assert "پیشرفته" in line  # راهِ عوض‌کردن همان‌جا گفته می‌شه


def test_the_storage_line_is_english_too(monkeypatch, data_dir, tmp_path):
    _calm_hardware(monkeypatch)
    monkeypatch.setattr(paths, "install_drive_models_dir", lambda: tmp_path / "D-root" / "models")
    s = settings_module.AppSettings(language="en")
    ctl = ai_select.build(FakePage(), "en", s, lambda: None, lambda: None, lambda: None)
    assert "Advanced" in collect_text(find(ctl, "ai_storage_line"))


# ------------------------------------------------------- متنِ گامِ «مدل» در چک‌لیست


def test_the_checklist_no_longer_calls_the_model_optional_but_recommended():
    """«اختیاری ولی پیشنهادی» گمراه‌کننده بود: بدونِ مدل هیچ سؤالِ نوشتاری جواب نمی‌گیرد."""
    step = {s.key: s for s in quickstart.steps(settings_module.AppSettings(business_mode="store"), product_count=0)}["ai"]
    assert "اختیاری ولی پیشنهادی" not in step.title_fa and "optional but recommended" not in step.title_en
    assert "نوشتاری" in step.title_fa and "written" in step.title_en.lower()


def test_the_model_step_is_still_marked_undone_without_a_model():
    """متنِ درست یعنی چه: گامِ مدل تا دانلود/واردکردنِ مدل انجام‌شده حساب نمی‌شود، ولی هیچ‌چیز را قفل نمی‌کند."""
    steps = {st.key: st for st in quickstart.steps(settings_module.AppSettings(business_mode="store"), product_count=0)}
    assert steps["ai"].done is False
    assert steps["bot"].done is False
