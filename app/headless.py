"""
حالتِ headless (R7): ربات‌ها بدونِ پنجره — برای سرور، Docker و Raspberry Pi. همان ``BotManager``ِ برنامه، فقط بدونِ UI و بدونِ
نیاز به flet. تنظیمات و داده از پوشه‌ی داده می‌آد (``--data-dir`` یا ``SMART_BUSINESS_DATA_DIR`` یا حالتِ قابل‌حمل).

    python run.py --headless [--data-dir DIR] [--status-interval 60]
    python run.py --healthcheck [--data-dir DIR]       # کدِ خروج ۰ = سالم (برای HEALTHCHECKِ Docker)

کدهای خروج: ۰ توقفِ عادی · ۱ ربات ناگهانی متوقف شد (Docker با ``restart: unless-stopped`` دوباره بالا میاره) ·
۲ هیچ رباتی تنظیم/فعال نیست · ۳ نسخه‌ی دیتابیس/تنظیمات سازگار نیست.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

HEARTBEAT_FILE = "heartbeat.json"
HEALTH_MAX_AGE_SECONDS = 120
EXIT_OK, EXIT_DIED, EXIT_NO_PLATFORM, EXIT_INCOMPATIBLE = 0, 1, 2, 3

logger = logging.getLogger("app.headless")


def _parse(argv) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="run.py --headless", description="اجرای ربات‌های کسب‌وکار هوشمند بدونِ UI")
    parser.add_argument("--headless", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--healthcheck", action="store_true", help="فقط سلامتِ پردازشِ headless رو بررسی کن (کدِ خروج ۰/۱)")
    parser.add_argument("--data-dir", default="", help="پوشه‌ی داده (به‌جای SMART_BUSINESS_DATA_DIR)")
    parser.add_argument("--status-interval", type=float, default=60.0, help="هر چند ثانیه وضعیت چاپ و heartbeat نوشته بشه")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


# ----------------------------------------------------------------- سلامت ----


def heartbeat_path(data_dir: Path) -> Path:
    return Path(data_dir) / HEARTBEAT_FILE


def write_heartbeat(manager, data_dir: Path, now: Optional[float] = None) -> None:
    status = manager.get_status()
    payload = {
        "ts": now if now is not None else time.time(),
        "running": status.running,
        "platforms": {name: {"connected": st.connected, "error": bool(st.error)} for name, st in status.platforms.items()},
    }
    path = heartbeat_path(data_dir)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, path)  # اتمیک: خواننده هرگز نیمه‌فایل نمی‌بینه


def check_health(data_dir: Path, max_age: float = HEALTH_MAX_AGE_SECONDS, now: Optional[float] = None) -> tuple:
    """``(سالم؟, پیام)`` — سالم یعنی heartbeat تازه است و مدیر در حالِ اجراست."""
    path = heartbeat_path(data_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, "heartbeat پیدا نشد (پردازشِ headless بالا نیست؟)"
    age = (now if now is not None else time.time()) - float(data.get("ts", 0))
    if age > max_age:
        return False, f"heartbeat قدیمیه ({int(age)} ثانیه)"
    if not data.get("running"):
        return False, "مدیرِ ربات‌ها در حال اجرا نیست"
    return True, "ok"


# -------------------------------------------------------------------- اجرا ----


def _setup_console_logging(secrets: list, level: str) -> None:
    from app.core.bot_manager import RedactingFormatter

    handler = logging.StreamHandler(sys.stdout)
    formatter = RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    formatter.secrets = [s for s in secrets if s]
    handler.setFormatter(formatter)
    for name in ("app", "aiogram"):
        lg = logging.getLogger(name)
        lg.addHandler(handler)
        lg.setLevel(getattr(logging, level.upper(), logging.INFO))


def run(manager, data_dir: Path, status_interval: float, stop_event: threading.Event, out: Callable[[str], None] = print) -> int:
    """مدیر رو روشن می‌کنه و تا ``stop_event`` (SIGINT/SIGTERM) یا مرگِ ناگهانیِ مدیر منتظر می‌مونه."""
    from app.core.bot_manager import BotManagerError

    platforms = manager.enabled_platforms()
    if not platforms:
        out("هیچ رباتی فعال نیست: توکنِ تلگرام/بله رو توی برنامه‌ی دسکتاپ (یا فایلِ settings.json) تنظیم و فعال کن.")
        return EXIT_NO_PLATFORM
    try:
        manager.start()
    except BotManagerError as exc:
        out(f"شروعِ ربات‌ها ممکن نشد: {exc}")
        return EXIT_NO_PLATFORM
    out(f"ربات‌ها روشن شدن: {', '.join(platforms)} — برای توقف Ctrl+C یا SIGTERM")
    code = EXIT_OK
    next_status = 0.0
    try:
        while not stop_event.wait(min(1.0, max(0.05, status_interval))):
            if not manager.is_running():
                out("⚠️ مدیرِ ربات‌ها ناگهانی متوقف شد.")
                code = EXIT_DIED
                break
            now = time.monotonic()
            if now >= next_status:
                next_status = now + max(0.05, status_interval)
                write_heartbeat(manager, data_dir)
                status = manager.get_status()
                out("وضعیت: " + " · ".join(f"{n}={'وصل' if s.connected else 'قطع'}" for n, s in status.platforms.items() if n in platforms))
    finally:
        manager.stop()
        try:
            heartbeat_path(data_dir).unlink()
        except OSError:
            pass
    return code


def main(argv=None, *, manager_factory=None, stop_event: Optional[threading.Event] = None) -> int:
    args = _parse(argv)
    if args.data_dir:
        os.environ["SMART_BUSINESS_DATA_DIR"] = args.data_dir
    from app.core.paths import get_app_data_dir

    data_dir = get_app_data_dir()
    if args.healthcheck:
        ok, message = check_health(data_dir)
        print(message)
        return EXIT_OK if ok else EXIT_DIED

    from app.core import settings as settings_module
    from app.core.migrations import MigrationError

    settings = settings_module.load_settings()
    _setup_console_logging(
        [settings.get_telegram_token(), settings.get_bale_token(), settings.get_telegram_proxy(), settings.get_telegram_proxy_sub_url(),
         settings.get_bale_pay_provider_token(), settings.get_zarinpal_merchant_id()],
        args.log_level,
    )
    try:
        if manager_factory is not None:
            manager = manager_factory(settings)
        else:
            from app.core import bot_manager
            from app.core.orders import OrderStore
            from app.core.products import ProductStore

            product_store = ProductStore()
            order_store = OrderStore(product_store=product_store)
            product_store.list()  # اسکیما همین‌جا (و پشتیبانِ پیش از مهاجرت) آماده می‌شه
            order_store.list()
            manager = bot_manager.get_manager(settings, product_store=product_store, order_store=order_store)
    except MigrationError as exc:
        print(f"داده با این نسخه سازگار نیست: {exc}")
        return EXIT_INCOMPATIBLE

    event = stop_event or threading.Event()
    if stop_event is None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, lambda *_: event.set())
            except (ValueError, OSError):  # تردِ غیرِ اصلی/پلتفرمِ بدونِ SIGTERM
                pass
    return run(manager, data_dir, args.status_interval, event)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
