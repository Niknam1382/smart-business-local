"""
نقطه‌ی اجرای «کسب‌وکار هوشمند» (نسخه‌ی محلی).

اجرای توسعه:      python run.py                (پنجره‌ی دسکتاپ، حالت پیش‌فرض)
                   python run.py --web          (برای تست در مرورگر، بدون نیاز به دسکتاپ)
                   python run.py --web -p 8550  (پورت دلخواه)
                   python run.py --headless     (فقط ربات‌ها، بدونِ پنجره: سرور/Docker؛ --healthcheck برای بررسیِ سلامت)
همین فایل، نقطه‌ی ورودی‌ای‌ست که build.spec هم برای ساخت exe استفاده می‌کند؛
در exe نهایی همیشه به‌صورت پنجره‌ی دسکتاپ بالا می‌آید.
"""

import argparse
import os
import sys


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="اجرای کسب‌وکار هوشمند (نسخه‌ی محلی)", add_help=True)
    parser.add_argument("--headless", action="store_true", help="فقط ربات‌ها، بدونِ پنجره (سرور/Docker)؛ گزینه‌ها: --data-dir، --status-interval")
    parser.add_argument("--healthcheck", action="store_true", help="بررسیِ سلامتِ پردازشِ headless (کدِ خروج ۰/۱)")
    parser.add_argument("--data-dir", default="", help="پوشه‌ی داده (headless)")
    parser.add_argument("--status-interval", type=float, default=60.0, help=argparse.SUPPRESS)
    parser.add_argument("--log-level", default="INFO", help=argparse.SUPPRESS)
    parser.add_argument("--apply-update", default="", metavar="PLAN", help=argparse.SUPPRESS)  # فقط برای helperِ به‌روزرسانی (N14b)
    parser.add_argument(
        "--web", action="store_true", help="اجرا در مرورگر به‌جای پنجره‌ی دسکتاپ (برای تست)"
    )
    parser.add_argument("-p", "--port", type=int, default=0, help="پورت وب (فقط با --web)")
    return parser.parse_args()


def _assets_dir() -> str:
    """مسیر پوشه‌ی assets؛ هم در اجرای معمولی و هم داخل exe ساخته‌شده با PyInstaller."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = sys._MEIPASS  # مسیر موقتی‌ای که PyInstaller در exe تک‌فایلی ازش اجرا می‌کنه
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "assets")


if __name__ == "__main__":
    args = _parse_args()
    if args.apply_update:  # helperِ به‌روزرسانی: بدونِ flet و بدونِ پنجره (app/core/update_apply.py)
        from app.core.update_apply import main as apply_update_main

        sys.exit(apply_update_main(args.apply_update))
    if args.headless or args.healthcheck:  # بدونِ import کردنِ flet (روی سرور/Docker نصب نیست)
        from app.headless import main as headless_main

        sys.exit(headless_main(sys.argv[1:]))
    import flet as ft

    from app.core import app_mutex
    from app.main import main

    app_mutex.acquire()  # نشانه برای نصب‌کننده‌ی ویندوز (AppMutex)؛ در بقیه‌ی سیستم‌ها بی‌اثر
    ft.run(
        main,
        assets_dir=_assets_dir(),
        view=ft.AppView.WEB_BROWSER if args.web else ft.AppView.FLET_APP,
        port=args.port,
    )
