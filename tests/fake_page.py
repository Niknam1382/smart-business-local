"""
یه Page جعلیِ سبک برای تست build() صفحه‌ها بدون بالا آوردن یه session واقعی
Flet (که نیاز به مرورگر متصل داره — طبق نکته‌ی فنی ۲ در MASTER_PROMPT).

فقط چیزهایی که کد صفحه‌ها واقعاً بهشون دست می‌زنن رو پیاده می‌کنه:
rtl/theme_mode (برای توابع theme.py)، update() (شمارشگر، بدون شبکه)،
run_thread() (همزمان اجرا می‌شه تا نتیجه فوری قابل‌بررسی باشه، نه روی
یه ترد واقعی — برای تست قطعی/بدون race بهتره).
"""

from types import SimpleNamespace

import flet as ft


class FakePage:
    """کافیه برای اجرای build() تک‌صفحه‌ها *و* کل app.main.main(page) — چون
    ft.Page() واقعی بدون یه session زنده اصلاً ساخته نمی‌شه
    (``TypeError: missing 'sess'``), دقیقاً همون چیزی که یادداشت فنی ۲ در
    MASTER_PROMPT درباره‌ش هشدار می‌ده."""

    def __init__(self):
        self.rtl = False
        self.theme_mode = ft.ThemeMode.LIGHT
        self.services: list = []
        self.overlay: list = []
        self.update_count = 0
        self.run_thread_calls = 0
        # فقط برای main.py: خصلت‌هایی که موقع راه‌اندازی صفحه ست می‌شن
        self.title = None
        self.padding = None
        self.fonts = None
        self.theme = None
        self.dark_theme = None
        self.window = SimpleNamespace(width=0, height=0, min_width=0, min_height=0)
        self.controls: list = []

    def add(self, *controls) -> None:
        self.controls.extend(controls)

    def update(self, *controls) -> None:
        self.update_count += 1

    def run_thread(self, handler, *args, **kwargs) -> None:
        self.run_thread_calls += 1
        handler(*args, **kwargs)


def find(control, key):
    """یه کنترل رو با key توی درخت کنترل‌های برگردونده‌شده از build() پیدا می‌کنه."""
    if getattr(control, "key", None) == key:
        return control
    for attr in ("controls", "content", "tabs", "actions", "title", "subtitle", "leading"):
        val = getattr(control, attr, None)
        if val is None:
            continue
        items = val if isinstance(val, list) else [val]
        for item in items:
            found = find(item, key)
            if found is not None:
                return found
    return None


def collect_text(control) -> str:
    """همه‌ی متن‌های ft.Text/دکمه‌ها رو از زیردرخت جمع می‌کنه و با \\n یکی
    می‌کنه — چون str(control) توی Flet 1.0 محتوای فرزندان رو چاپ نمی‌کنه،
    برای بررسی «آیا این متن جایی توی صفحه هست» لازمه به‌جای str() از این
    استفاده بشه."""
    found: list[str] = []

    def walk(c) -> None:
        val = getattr(c, "value", None)
        if isinstance(val, str) and val:
            found.append(val)
        content = getattr(c, "content", None)
        if isinstance(content, str) and content:
            found.append(content)
        for attr in ("controls", "content", "tabs", "actions", "title", "subtitle", "leading"):
            v = getattr(c, attr, None)
            if v is None or isinstance(v, str):
                continue
            for item in v if isinstance(v, list) else [v]:
                walk(item)

    walk(control)
    return "\n".join(found)


def fire(control, handler_name: str, value=None):
    """یه هندلر (on_click/on_change/on_blur/...) رو با یه Event ساختگی صدا می‌زنه."""
    handler = getattr(control, handler_name)
    if value is not None:
        control.value = value
    event = type("FakeEvent", (), {"control": control, "data": value})()
    return handler(event)
