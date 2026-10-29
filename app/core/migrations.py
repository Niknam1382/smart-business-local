"""
مهاجرتِ نسخه‌دارِ اسکیمای SQLite (R11).

هر دیتابیس (``products.db`` / ``orders.db`` / ``conversations.db``) یک لیستِ مرتب از
«مهاجرت» دارد؛ هر مهاجرت یک تابعِ ``(conn) -> None`` است و شماره‌اش = جایگاهش در لیست
(از ۱). نسخه‌ی اسکیمای هر فایل در ``PRAGMA user_version`` نگه‌داری می‌شه.

قواعد:
- هر مهاجرت داخلِ **یک تراکنش** اجرا می‌شه (``BEGIN IMMEDIATE``)؛ شکست = rollback + خطای روشن.
  پس داخلِ مهاجرت‌ها فقط ``conn.execute`` بزن (``executescript`` تراکنش رو commit می‌کنه).
- مهاجرتِ ۱ = وضعیتِ ۰.۵.۰ و **idempotent** است: دیتابیسِ ۰.۵.۰ (با ``user_version=0`` و
  جدول‌های موجود) و دیتابیسِ تازه هر دو به همون وضعیت می‌رسن.
- دیتابیسِ جدیدتر از برنامه (``user_version`` بزرگ‌تر) = ``SchemaTooNewError`` («برنامه رو به‌روز کن»).
- قبل از مهاجرتِ دیتابیسِ دارای داده، یک پشتیبانِ خودکار (``backup.create_backup``) گرفته می‌شه
  (برای هر پوشه‌ی داده فقط یک‌بار در هر اجرا).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable, Optional, Sequence

logger = logging.getLogger(__name__)

Migration = Callable[[sqlite3.Connection], None]


class MigrationError(Exception):
    """مهاجرت ناموفق بود (پیامِ فارسی؛ تراکنش rollback شده)."""


class SchemaTooNewError(MigrationError):
    """دیتابیس با نسخه‌ی جدیدتری از برنامه ساخته شده."""


_guard = threading.Lock()
_path_locks: dict = {}
_backed_up_dirs: set = set()


def _lock_for(key: str) -> threading.Lock:
    with _guard:
        lock = _path_locks.get(key)
        if lock is None:
            lock = _path_locks[key] = threading.Lock()
        return lock


# ------------------------------------------------------------------ کمکی‌ها ----


def current_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def table_columns(conn: sqlite3.Connection, table: str) -> set:
    return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}


def add_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> bool:
    """ستون رو فقط اگه نباشه اضافه می‌کنه (idempotent). ``True`` اگه اضافه شد."""
    if column in table_columns(conn, table):
        return False
    conn.execute(f'ALTER TABLE "{table}" ADD COLUMN {column} {ddl}')
    return True


def has_user_rows(conn: sqlite3.Connection) -> bool:
    """آیا دیتابیس حداقل یک ردیفِ کاربر داره؟ (برای تصمیمِ پشتیبانِ پیش از مهاجرت)."""
    tables = [
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    ]
    for table in tables:
        if conn.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone():
            return True
    return False


def _auto_backup(data_dir: Path) -> None:
    key = str(data_dir.resolve())
    with _guard:
        if key in _backed_up_dirs:
            return
        _backed_up_dirs.add(key)
    try:
        from app.core import backup  # import تنبل: جلوگیری از چرخه

        dest = data_dir / backup.BACKUP_DIR_NAME / f"before-upgrade-{time.strftime('%Y%m%d-%H%M%S')}.zip"
        backup.create_backup(dest, data_dir=data_dir)
        logger.info("پشتیبانِ پیش از مهاجرت ساخته شد: %s", dest.name)
    except Exception:  # noqa: BLE001 — شکستِ پشتیبان نباید مهاجرتِ تراکنشی رو متوقف کنه
        logger.warning("ساختنِ پشتیبانِ پیش از مهاجرت ناموفق بود", exc_info=True)


# ------------------------------------------------------------- اجرای مهاجرت ----


def apply_migrations(
    conn: sqlite3.Connection,
    migrations: Sequence[Migration],
    *,
    name: str = "db",
    before_upgrade: Optional[Callable[[], None]] = None,
) -> int:
    """اسکیما رو به آخرین نسخه می‌رسونه و نسخه‌ی نهایی رو برمی‌گردونه."""
    target = len(migrations)
    version = current_version(conn)
    if version == target:
        return version
    if version > target:
        raise SchemaTooNewError(
            f"دیتابیسِ «{name}» با نسخه‌ی جدیدتری از برنامه ساخته شده (نسخه‌ی اسکیما {version}؛ این برنامه تا {target} رو می‌شناسه). "
            "برنامه رو به‌روز کن."
        )
    if before_upgrade is not None and has_user_rows(conn):
        before_upgrade()
    for number in range(version + 1, target + 1):
        conn.execute("BEGIN IMMEDIATE")
        try:
            if current_version(conn) >= number:  # کسِ دیگه‌ای (ترد/پردازش) همین مهاجرت رو انجام داده
                conn.rollback()
                continue
            migrations[number - 1](conn)
            conn.execute(f"PRAGMA user_version = {int(number)}")
            conn.commit()
        except BaseException as exc:
            conn.rollback()
            raise MigrationError(f"مهاجرتِ «{name}» به نسخه‌ی {number} ناموفق بود و هیچ تغییری اعمال نشد: {exc}") from exc
    return target


def prepare(conn: sqlite3.Connection, db_path: Path, migrations: Sequence[Migration]) -> int:
    """نقطه‌ی ورودِ فروشگاه‌ها: قفلِ هر مسیر + پشتیبانِ خودکار + اجرای مهاجرت‌ها."""
    db_path = Path(db_path)
    with _lock_for(str(db_path.resolve())):
        return apply_migrations(
            conn,
            migrations,
            name=db_path.name,
            before_upgrade=lambda: _auto_backup(db_path.parent),
        )


# ------------------------------------------------------------------- رجیستری ----


def registry() -> dict:
    """نگاشتِ نامِ فایل ← لیستِ مهاجرت‌ها (import تنبل تا چرخه‌ی وابستگی نسازه)."""
    from app.core import conversations, orders, products

    return {
        "products.db": products.MIGRATIONS,
        "orders.db": orders.MIGRATIONS,
        "conversations.db": conversations.MIGRATIONS,
    }


def latest_version(name: str) -> int:
    return len(registry()[name])


def file_version(path: Path) -> int:
    """نسخه‌ی اسکیمای یه فایلِ SQLite (بدونِ تغییرش)."""
    conn = sqlite3.connect(str(path))
    try:
        return current_version(conn)
    finally:
        conn.close()


def ensure_schema(path: Path, *, backup_first: bool = True) -> int:
    """فایلِ ``path`` (با نامِ استانداردِ یکی از سه دیتابیس) رو به آخرین نسخه می‌رسونه.
    بعد از ``backup.restore_backup`` صدا زده می‌شه تا پشتیبانِ قدیمی‌تر هم ارتقا پیدا کنه؛
    اتصال‌های بازِ فروشگاه‌ها تغییر رو خودشون می‌بینن."""
    path = Path(path)
    migrations = registry().get(path.name)
    if migrations is None:
        raise MigrationError(f"«{path.name}» دیتابیسِ شناخته‌شده‌ای نیست.")
    conn = sqlite3.connect(str(path), timeout=15)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        with _lock_for(str(path.resolve())):
            return apply_migrations(
                conn,
                migrations,
                name=path.name,
                before_upgrade=(lambda: _auto_backup(path.parent)) if backup_first else None,
            )
    finally:
        conn.close()
