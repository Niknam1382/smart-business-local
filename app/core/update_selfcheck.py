"""خودآزمونِ حفظِ اطلاعات هنگامِ آپدیت (۱٫۲٫۰).

هر اجرا، «اثرانگشتِ داده» (تعدادِ محصول/سفارش، تعدادِ کلیدهایِ تنظیمات، وجودِ کلیدِ رمزنگاری، مدلِ انتخاب‌شده و حجمِ
فایلش، تعدادِ پشتیبان‌ها) در ``update_fingerprint.json`` ذخیره می‌شود. در اولین اجرایِ یک نسخه‌یِ *تازه*، اثرانگشتِ نسخه‌یِ
قبلی در ``update_previous.json`` نگه داشته می‌شود؛ صفحه‌یِ «درباره» قبل و بعد را کنارِ هم می‌گذارد تا ببینی آپدیت چیزی را
کم کرده یا نه. فقط شمارش می‌کند؛ هیچ محتوایی (نام مشتری، قیمت، توکن) ذخیره یا نمایش داده نمی‌شود. فقط stdlib، هرگز استثنا
نمی‌اندازد و به داده‌ی کاربر دست نمی‌زند.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

from app.core import paths
from app.version import __version__

FILE_CURRENT = "update_fingerprint.json"
FILE_PREVIOUS = "update_previous.json"


def _base(data_dir) -> Path:
    return Path(data_dir) if data_dir is not None else paths.get_app_data_dir()


def _count(db: Path, table: str) -> Optional[int]:
    if not db.is_file():
        return None
    try:
        conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True, timeout=1.0)
        try:
            return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # نامِ جدول ثابت است، نه ورودیِ کاربر
        finally:
            conn.close()
    except (sqlite3.Error, OSError, ValueError):
        return None


def _settings_keys(base: Path) -> Optional[int]:
    try:
        data = json.loads((base / "settings.json").read_text(encoding="utf-8"))
        return len(data) if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _model_facts(settings) -> dict:
    """نامِ فایل + حجمِ مدلِ انتخاب‌شده (اگر روی دیسک باشد)."""
    if settings is None:
        return {"model_name": None, "model_bytes": None}
    try:
        explicit = (getattr(settings, "model_file_path", "") or "").strip()
        if explicit:
            path = Path(explicit)
        else:
            from app.core import model_catalog

            entry = model_catalog.get_entry(getattr(settings, "model_id", "") or "")
            if entry is None:
                return {"model_name": None, "model_bytes": None}
            path = Path(settings.get_model_storage_dir()) / entry.filename
        if path.is_file():
            return {"model_name": path.name, "model_bytes": path.stat().st_size}
        return {"model_name": path.name, "model_bytes": 0}
    except Exception:  # noqa: BLE001 — فقط یک خودآزمون است
        return {"model_name": None, "model_bytes": None}


def collect(settings=None, data_dir=None, version: Optional[str] = None) -> dict:
    base = _base(data_dir)
    facts = {
        "version": version or __version__,
        "taken_at": int(time.time()),
        "data_dir": str(base),
        "settings_keys": _settings_keys(base),
        "secret_key": (base / "secret.key").is_file(),
        "products": _count(base / "products.db", "products"),
        "orders": _count(base / "orders.db", "orders"),
        "backups": len(list((base / "backups").glob("*.zip"))) if (base / "backups").is_dir() else 0,
    }
    facts.update(_model_facts(settings))
    return facts


def _load(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _save(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def record_startup(settings=None, data_dir=None, version: Optional[str] = None) -> None:
    """اثرانگشتِ این اجرا را می‌نویسد؛ اگر نسخه عوض شده بود، اثرانگشتِ قبلی را نگه می‌دارد. هرگز استثنا نمی‌اندازد."""
    try:
        base = _base(data_dir)
        if not (base / "settings.json").is_file():
            return  # نصبِ تازه: چیزی برای مقایسه نیست
        now = collect(settings, base, version)
        previous = _load(base / FILE_CURRENT)
        if previous and previous.get("version") != now["version"]:
            _save(base / FILE_PREVIOUS, previous)
        _save(base / FILE_CURRENT, now)
    except Exception:  # noqa: BLE001
        return


def compare(settings=None, data_dir=None, version: Optional[str] = None) -> Optional[dict]:
    """قبل (آخرین اجرایِ نسخه‌یِ پیشین) در برابرِ اکنون. ``None`` اگر هنوز آپدیتی دیده نشده."""
    try:
        base = _base(data_dir)
        before = _load(base / FILE_PREVIOUS)
        if not before:
            return None
        now = collect(settings, base, version)
        if before.get("version") == now["version"]:
            return None
        rows = []

        def count_row(key: str) -> None:
            b, a = before.get(key), now.get(key)
            if b is None:
                return  # آن موقع وجود نداشت/خوانده نشد
            rows.append({"key": key, "before": b, "after": a, "ok": a is not None and a >= b})

        for key in ("products", "orders", "settings_keys", "backups"):
            count_row(key)
        if before.get("secret_key"):
            rows.append({"key": "secret_key", "before": True, "after": now["secret_key"], "ok": bool(now["secret_key"])})
        if before.get("model_name"):
            same = now.get("model_name") == before.get("model_name") and (now.get("model_bytes") or 0) == (before.get("model_bytes") or 0)
            rows.append({"key": "model", "before": before.get("model_name"), "after": now.get("model_name"), "ok": same and bool(now.get("model_bytes"))})
        return {"before_version": before.get("version"), "now_version": now["version"], "rows": rows, "all_ok": all(r["ok"] for r in rows)}
    except Exception:  # noqa: BLE001
        return None
