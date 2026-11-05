"""تنظیمات مشترک تست‌ها.

هیچ تستی نباید به پوشه‌ی داده‌ی واقعی برنامه (تنظیمات، secret.key، دیتابیس
مکالمه‌ها) دست بزنه — پس همه‌ی مسیرها به یه پوشه‌ی موقت هدایت می‌شن.

نسخه‌ی ۱.۰.۰: «حالتِ قابل‌حمل» حذف شده (app/core/paths.py فقط env/system می‌شناسد)، پس
این fixture فقط متغیرِ محیطیِ داده را پاک می‌کنه تا هیچ تستی به پوشه‌ی واقعیِ توسعه‌دهنده
ننویسد.
"""

from pathlib import Path

import pytest
from fake_servers import FakeBotApiServer


@pytest.fixture
def bale(monkeypatch):
    """سرورِ جعلیِ *پرداختِ* بله + وصل‌کردنِ BalePayClientِ واقعی به آن (بدونِ شبکه).

    رباتِ بله در نسخه‌ی ۱.۰.۰ گفتگو نمی‌کند؛ تنها چیزی که از آن می‌آید رویدادِ پرداخت و
    فرمانِ /pay است. این fixture در conftest نشسته چون چند ماژول تست به آن نیاز دارند و
    importِ نامِ fixture از یک فایلِ تست دیگر، با ruff (F811) می‌جنگد."""
    srv = FakeBotApiServer(username="bale_pay_bot").start()
    from app.core import bot_manager

    real = bot_manager.BalePayClient
    monkeypatch.setattr(bot_manager, "BalePayClient", lambda token, *a, **kw: real(token, base_url_template=srv.url_template))
    yield srv
    srv.stop()


@pytest.fixture(autouse=True)
def isolated_appdata(tmp_path, monkeypatch):
    data = tmp_path / "appdata"
    data.mkdir()
    monkeypatch.setenv("APPDATA", str(data))  # ویندوز
    monkeypatch.setenv("XDG_DATA_HOME", str(data))  # لینوکس
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: data))  # مک
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
