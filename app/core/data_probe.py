"""تشخیصِ «داده‌ی قبلی» در پوشه‌ی داده (N2) — فقط‌خواندنی، بدونِ هیچ اثری.

دلیل: نسخه‌ی تازه‌ی نصب‌شده روی سیستمی که قبلاً نسخه‌ی دیگری (یا اجرای توسعه) داده‌ای ساخته، همان داده‌ها را می‌بیند. کاربر باید
*یک‌بار* بفهمه و انتخاب کنه: «ادامه با داده‌ی قبلی» یا «شروعِ تازه» (با پشتیبانِ خودکارِ قبل از پاک‌کردن).

هیچ‌چیز نوشته/مهاجرت داده نمی‌شه: دیتابیس‌ها با ``mode=ro`` باز می‌شن و فایلِ تنظیمات فقط پارس می‌شه. محتوا (نام، پیام، سفارش)
هرگز خوانده یا نشان داده نمی‌شه؛ فقط تعدادها.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core import paths

_COUNTS = (
    ("products", "products.db", "products"),
    ("orders", "orders.db", "orders"),
    ("conversations", "conversations.db", "conversations"),
)


@dataclass(frozen=True)
class DataFootprint:
    data_dir: Path
    has_settings: bool = False
    user_name_set: bool = False
    onboarding_complete: bool = False
    products: int = 0
    orders: int = 0
    conversations: int = 0

    @property
    def has_data(self) -> bool:
        """هر نشانه‌ای از اینکه این پوشه قبلاً استفاده شده."""
        return bool(self.user_name_set or self.onboarding_complete or self.products or self.orders or self.conversations)


def _count_rows(db: Path, table: str) -> int:
    if not db.is_file():
        return 0
    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=2.0)
    except sqlite3.Error:
        return 0
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608 — نامِ جدول از فهرستِ ثابتِ بالا
        return int(row[0]) if row else 0
    except sqlite3.Error:
        return 0  # جدول/نسخه‌ی ناشناخته
    finally:
        conn.close()


def probe(data_dir: Optional[Path] = None) -> DataFootprint:
    """وضعیتِ داده‌ی موجود را (بدونِ تغییر) برمی‌گردونه. هرگز exception نمی‌ده؛ پوشه‌ی ناموجود = بدونِ داده."""
    try:
        base = Path(data_dir) if data_dir is not None else paths.resolve_data_dir()[0]
    except OSError:
        return DataFootprint(data_dir=Path("."))
    has_settings = user_name_set = onboarding_complete = False
    settings_file = base / "settings.json"
    if settings_file.is_file():
        try:
            data = json.loads(settings_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                has_settings = True
                user_name_set = bool(str(data.get("user_name") or "").strip())
                onboarding_complete = bool(data.get("onboarding_complete"))
        except (OSError, ValueError):
            pass
    counts = {name: _count_rows(base / filename, table) for name, filename, table in _COUNTS}
    return DataFootprint(
        data_dir=base,
        has_settings=has_settings,
        user_name_set=user_name_set,
        onboarding_complete=onboarding_complete,
        **counts,
    )
