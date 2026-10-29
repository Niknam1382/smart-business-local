"""تنظیمات مشترک تست‌ها.

هیچ تستی نباید به پوشه‌ی داده‌ی واقعی برنامه (تنظیمات، secret.key، دیتابیس
مکالمه‌ها) دست بزنه — پس همه‌ی مسیرها به یه پوشه‌ی موقت هدایت می‌شن.
"""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_appdata(tmp_path, monkeypatch):
    data = tmp_path / "appdata"
    data.mkdir()
    monkeypatch.setenv("APPDATA", str(data))  # ویندوز
    monkeypatch.setenv("XDG_DATA_HOME", str(data))  # لینوکس
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: data))  # مک
    # حالت قابل‌حمل نباید به محیطِ توسعه‌دهنده وابسته باشه (متغیر محیطی/فایل portable.flag کنارِ پروژه)
    monkeypatch.delenv("SMART_BUSINESS_DATA_DIR", raising=False)
    anchor = tmp_path / "app_anchor"
    anchor.mkdir()
    monkeypatch.setattr("app.core.paths.app_anchor", lambda: anchor)
    return data


@pytest.fixture(autouse=True)
def _no_network_update_check(monkeypatch):
    """بررسیِ خودکارِ نسخه‌ی تازه (GitHub) در تست‌ها هرگز نباید شبکه بزنه؛ تست‌های خودش ``UpdateChecker`` جعلی می‌دن."""
    monkeypatch.setenv("SMART_BUSINESS_NO_UPDATE_CHECK", "1")


@pytest.fixture(autouse=True)
def _reset_shop_texts():
    """متن‌های ربات ارائه‌دهنده‌ی تنظیماتِ سراسری دارن؛ بینِ تست‌ها نشت نکنه."""
    from app.core import shop_texts

    shop_texts.configure(None)
    yield
    shop_texts.configure(None)
