"""
ذخیره‌سازی مکالمه‌های ربات (تلگرام/بله) — تاریخچه‌ی پیام‌ها، تنظیم «حافظه»ی
هر مکالمه (که تعیین می‌کنه پیام‌های قبلی به‌عنوان context به AI فرستاده بشه
یا نه)، و وضعیت بلاک هر کاربر.

چرا SQLite و نه JSON مثل settings.py: تعداد پیام‌ها می‌تونه زیاد و رو به رشد
باشه؛ append روی JSON یعنی بازنویسی کل فایل هر بار، ولی SQLite این مشکل رو
نداره و کوئری‌هایی مثل «۲۰ مکالمه‌ی اخیر» یا «تاریخچه‌ی یه مکالمه» رو با یه
ایندکس ساده انجام می‌ده. هیچ وابستگی جدیدی هم لازم نداره — sqlite3 استاندارد
پایتونه.

Thread-safety: bot (روی ترد پس‌زمینه‌ی خودش) و UI (روی صفحه‌ی چت) هر دو به
همین فایل دسترسی دارن. یک شیء sqlite3.Connection نباید بین تردها به‌اشتراک
بره؛ برای همین هر ترد کانکشن خودش رو می‌سازه (threading.local) و WAL فعاله
تا خوندن از یه ترد، نوشتن از تردِ دیگه رو قفل نکنه.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core import migrations
from app.core.ai_engine import ChatMessage
from app.core.paths import get_app_data_dir

_DB_FILE_NAME = "conversations.db"

def _m1_baseline(conn: sqlite3.Connection) -> None:
    """وضعیتِ ۰.۵.۰ (idempotent)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            platform TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            display_name TEXT NOT NULL DEFAULT '',
            memory_enabled INTEGER NOT NULL DEFAULT 1,
            blocked INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (platform, chat_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(platform, chat_id, id)")


def _m2_shop_schema(conn: sqlite3.Connection) -> None:
    """۱.۰.۰: مصرفِ روزانه‌ی AI، پشتیبانیِ انسانی (handoff + نگاشتِ پیامِ مالک)، صندوقِ «نیاز به توجه»."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS usage (
            day TEXT NOT NULL,
            platform TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            messages INTEGER NOT NULL DEFAULT 0,
            ai_calls INTEGER NOT NULL DEFAULT 0,
            tokens_est INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (day, platform, chat_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS handoff_sessions (
            platform TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            customer_label TEXT NOT NULL DEFAULT '',
            started_ts INTEGER NOT NULL,
            last_activity_ts INTEGER NOT NULL,
            closed_reason TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (platform, chat_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS relay_map (
            owner_platform TEXT NOT NULL,
            owner_chat_id TEXT NOT NULL,
            owner_message_id TEXT NOT NULL,
            customer_platform TEXT NOT NULL,
            customer_chat_id TEXT NOT NULL,
            created_ts INTEGER NOT NULL,
            PRIMARY KEY (owner_platform, owner_chat_id, owner_message_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attention_inbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            ref TEXT NOT NULL DEFAULT '',
            detail TEXT NOT NULL DEFAULT '',
            created_ts INTEGER NOT NULL,
            handled INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_attention_open ON attention_inbox(handled, id)")


def _m3_customers(conn: sqlite3.Connection) -> None:
    """N12 (CRM): پروفایلِ مشتری. آمارِ سفارش‌ها اینجا ذخیره نمی‌شه؛ همیشه از دیتابیسِ سفارش‌ها محاسبه می‌شه (بدونِ ناهم‌خوانی).
    پرکردنِ اولیه از مکالمه‌های موجود (نام = نامِ نمایشی، زمان‌ها از ردیفِ مکالمه، تعدادِ پیام از پیام‌های «user»)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS customers (
            platform TEXT NOT NULL,
            user_id TEXT NOT NULL,
            first_name TEXT NOT NULL DEFAULT '',
            last_name TEXT NOT NULL DEFAULT '',
            username TEXT NOT NULL DEFAULT '',
            language_code TEXT NOT NULL DEFAULT '',
            is_premium INTEGER NOT NULL DEFAULT 0,
            phone TEXT NOT NULL DEFAULT '',
            first_seen_ts INTEGER NOT NULL DEFAULT 0,
            last_seen_ts INTEGER NOT NULL DEFAULT 0,
            msg_count INTEGER NOT NULL DEFAULT 0,
            tags TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            opted_out INTEGER NOT NULL DEFAULT 0,
            unreachable INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (platform, user_id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_customers_last_seen ON customers(last_seen_ts)")
    conn.execute(
        """
        INSERT OR IGNORE INTO customers (platform, user_id, first_name, first_seen_ts, last_seen_ts, msg_count)
        SELECT c.platform, c.chat_id,
               CASE WHEN c.display_name = c.chat_id THEN '' ELSE c.display_name END,
               COALESCE(CAST(strftime('%s', c.created_at) AS INTEGER), 0),
               COALESCE(CAST(strftime('%s', c.updated_at) AS INTEGER), 0),
               (SELECT COUNT(*) FROM messages m WHERE m.platform = c.platform AND m.chat_id = c.chat_id AND m.role = 'user')
        FROM conversations c
        WHERE c.platform != 'preview'
        """
    )


def _m4_admins(conn: sqlite3.Connection) -> None:
    """N11: مدیرانِ ربات (نقش‌ها)، دعوت‌های یک‌بارمصرف (فقط هشِ توکن) و لاگِ ممیزی."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS admins (
            platform TEXT NOT NULL,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            username TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'viewer',
            status TEXT NOT NULL DEFAULT 'active',
            added_by TEXT NOT NULL DEFAULT '',
            added_ts INTEGER NOT NULL DEFAULT 0,
            last_active_ts INTEGER NOT NULL DEFAULT 0,
            pending_expires_ts INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (platform, user_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_invites (
            token_hash TEXT PRIMARY KEY,
            platform TEXT NOT NULL,
            role TEXT NOT NULL,
            created_ts INTEGER NOT NULL,
            expires_ts INTEGER NOT NULL,
            used_ts INTEGER NOT NULL DEFAULT 0,
            used_by TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            platform TEXT NOT NULL DEFAULT '',
            user_id TEXT NOT NULL DEFAULT '',
            actor TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_audit_ts ON admin_audit(ts)")


def _m5_broadcasts(conn: sqlite3.Connection) -> None:
    """N7 (پیامِ همگانی): صفِ پایدار. متنِ پیام یک‌بار در ``broadcasts`` می‌مونه؛ گیرنده‌ها snapshotِ لحظه‌ی شروع‌اند
    (``broadcast_log``) تا بعد از ری‌استارت ادامه بده. شمارش‌ها همیشه از همین لاگ محاسبه می‌شن، نه شمارنده‌ی جدا."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS broadcasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_ts INTEGER NOT NULL DEFAULT 0,
            started_ts INTEGER NOT NULL DEFAULT 0,
            finished_ts INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'running',
            text TEXT NOT NULL DEFAULT '',
            photo TEXT NOT NULL DEFAULT '',
            button_label TEXT NOT NULL DEFAULT '',
            button_url TEXT NOT NULL DEFAULT '',
            footer INTEGER NOT NULL DEFAULT 1,
            filters TEXT NOT NULL DEFAULT '{}',
            created_by TEXT NOT NULL DEFAULT 'app'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS broadcast_log (
            broadcast_id INTEGER NOT NULL,
            platform TEXT NOT NULL,
            user_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            error TEXT NOT NULL DEFAULT '',
            attempts INTEGER NOT NULL DEFAULT 0,
            ts INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (broadcast_id, platform, user_id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_broadcast_log_state ON broadcast_log(broadcast_id, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_broadcast_log_user ON broadcast_log(platform, user_id)")


def _m6_ai_calls(conn: sqlite3.Connection) -> None:
    """N1: ثبتِ هر تماسِ AI (توکنِ واقعی/تخمینی، مدلِ پاسخ‌دهنده، تلاش/علتِ جابه‌جایی) + جمع‌بندیِ روزانه برای داده‌ی قدیمی‌تر از ۹۰ روز."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            platform TEXT NOT NULL DEFAULT '',
            chat_id TEXT NOT NULL DEFAULT '',
            provider_id TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            attempt INTEGER NOT NULL DEFAULT 1,
            failover_reason TEXT NOT NULL DEFAULT '',
            prompt_tokens INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            cached_tokens INTEGER NOT NULL DEFAULT 0,
            kind TEXT NOT NULL DEFAULT 'chat',
            source TEXT NOT NULL DEFAULT 'chat',
            latency_ms INTEGER NOT NULL DEFAULT 0,
            ok INTEGER NOT NULL DEFAULT 1,
            estimated INTEGER NOT NULL DEFAULT 0,
            saved_tokens INTEGER NOT NULL DEFAULT 0,
            sys_tokens INTEGER NOT NULL DEFAULT 0,
            hist_tokens INTEGER NOT NULL DEFAULT 0,
            msg_tokens INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_calls_ts ON ai_calls(ts)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_usage_daily (
            day TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            model TEXT NOT NULL,
            calls INTEGER NOT NULL DEFAULT 0,
            ok_calls INTEGER NOT NULL DEFAULT 0,
            prompt_tokens INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            cached_tokens INTEGER NOT NULL DEFAULT 0,
            saved_tokens INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (day, provider_id, model)
        )
        """
    )


MIGRATIONS = [_m1_baseline, _m2_shop_schema, _m3_customers, _m4_admins, _m5_broadcasts, _m6_ai_calls]

# N6: پیامِ شخصیِ مالک با نقشِ «owner» ذخیره می‌شه (در صفحه‌ی گفتگوها «شما»)؛ برای AI به‌صورتِ پیامِ فروشگاه (assistant) می‌رسه
OWNER_ROLE = "owner"
OWNER_NOTE = "[فروشگاه] "


@dataclass
class ConversationSummary:
    platform: str
    chat_id: str
    display_name: str
    memory_enabled: bool
    blocked: bool
    updated_at: str
    last_message_preview: str = ""


@dataclass
class StoredMessage:
    role: str
    content: str
    created_at: str = field(default="")


class ConversationStore:
    """یک نمونه از این کلاس برای کل برنامه کافیه. متدهاش از هر تردی قابل
    صدا زدنن (هر ترد کانکشن sqlite3 خودش رو lazy می‌سازه)."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (get_app_data_dir() / _DB_FILE_NAME)
        self._local = threading.local()

    def _connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.db_path), timeout=15)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            migrations.prepare(conn, self.db_path, MIGRATIONS)
            self._local.conn = conn
        return conn

    def connection(self) -> sqlite3.Connection:
        """اتصالِ همین تردِ دیتابیسِ مکالمه‌ها (برای ماژول‌های هم‌خانواده: مصرف، handoff، صندوق)."""
        return self._connection()

    # ---------------- مکالمه‌ها ----------------

    def ensure_conversation(self, platform: str, chat_id: str, display_name: str = "") -> None:
        conn = self._connection()
        conn.execute(
            """
            INSERT INTO conversations (platform, chat_id, display_name)
            VALUES (?, ?, ?)
            ON CONFLICT(platform, chat_id) DO UPDATE SET
                display_name = CASE WHEN excluded.display_name != ''
                                     THEN excluded.display_name
                                     ELSE conversations.display_name END
            """,
            (platform, chat_id, display_name),
        )
        conn.commit()

    def get_display_name(self, platform: str, chat_id: str) -> str:
        row = self._connection().execute(
            "SELECT display_name FROM conversations WHERE platform = ? AND chat_id = ?", (platform, chat_id)
        ).fetchone()
        return row["display_name"] if row else ""

    def is_blocked(self, platform: str, chat_id: str) -> bool:
        row = self._connection().execute(
            "SELECT blocked FROM conversations WHERE platform = ? AND chat_id = ?",
            (platform, chat_id),
        ).fetchone()
        return bool(row["blocked"]) if row else False

    def set_blocked(self, platform: str, chat_id: str, blocked: bool) -> None:
        conn = self._connection()
        conn.execute(
            "UPDATE conversations SET blocked = ? WHERE platform = ? AND chat_id = ?",
            (1 if blocked else 0, platform, chat_id),
        )
        conn.commit()

    def is_memory_enabled(self, platform: str, chat_id: str) -> bool:
        row = self._connection().execute(
            "SELECT memory_enabled FROM conversations WHERE platform = ? AND chat_id = ?",
            (platform, chat_id),
        ).fetchone()
        return bool(row["memory_enabled"]) if row else True

    def set_memory_enabled(self, platform: str, chat_id: str, enabled: bool) -> None:
        conn = self._connection()
        conn.execute(
            "UPDATE conversations SET memory_enabled = ? WHERE platform = ? AND chat_id = ?",
            (1 if enabled else 0, platform, chat_id),
        )
        conn.commit()

    def list_conversations(self, platform: Optional[str] = None) -> list[ConversationSummary]:
        # چرا اینجوری پیچیده‌ست: ``updated_at`` فقط با دقت ثانیه‌ست
        # (``datetime('now')`` توی SQLite)، پس وقتی چند پیام توی یه ثانیه
        # می‌رسن (کاملاً معمولیه — یه burst پیام، یا حتی تست خودکار)، مرتب‌سازی
        # فقط بر اساس اون می‌تونه ترتیب اشتباه بده. ``messages.id`` یه
        # autoincrement واقعیه و هیچ‌وقت تساوی نداره، پس معیار اصلی ترتیب
        # همونه؛ مکالمه‌ای که هنوز پیامی نداره (مثلاً یه کاربر بلاک‌شده که اولین
        # پیامش هیچ‌وقت ذخیره نشد) با rowid خودش (ترتیب ساخته‌شدن) و همیشه
        # بعد از مکالمه‌های دارای پیام قرار می‌گیره.
        conn = self._connection()
        query = """
            SELECT c.*, (
                SELECT MAX(m.id) FROM messages m
                WHERE m.platform = c.platform AND m.chat_id = c.chat_id
            ) AS last_msg_id
            FROM conversations c
        """
        params: tuple = ()
        if platform:
            query += " WHERE c.platform = ?"
            params = (platform,)
        query += " ORDER BY (last_msg_id IS NULL) ASC, last_msg_id DESC, c.rowid DESC"
        rows = conn.execute(query, params).fetchall()
        result = []
        for r in rows:
            preview = conn.execute(
                "SELECT content FROM messages WHERE platform = ? AND chat_id = ? ORDER BY id DESC LIMIT 1",
                (r["platform"], r["chat_id"]),
            ).fetchone()
            result.append(
                ConversationSummary(
                    platform=r["platform"],
                    chat_id=r["chat_id"],
                    display_name=r["display_name"],
                    memory_enabled=bool(r["memory_enabled"]),
                    blocked=bool(r["blocked"]),
                    updated_at=r["updated_at"],
                    last_message_preview=(preview["content"] if preview else ""),
                )
            )
        return result

    # ---------------- پیام‌ها ----------------

    def add_message(self, platform: str, chat_id: str, role: str, content: str) -> None:
        conn = self._connection()
        conn.execute(
            "INSERT INTO messages (platform, chat_id, role, content) VALUES (?, ?, ?, ?)",
            (platform, chat_id, role, content),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = datetime('now') WHERE platform = ? AND chat_id = ?",
            (platform, chat_id),
        )
        conn.commit()

    def get_history(self, platform: str, chat_id: str, limit: int = 20) -> list[ChatMessage]:
        """آخرین `limit` پیام رو برای استفاده به‌عنوان context برمی‌گردونه —
        صرف‌نظر از تنظیم حافظه (تصمیم اینکه از این تاریخچه استفاده بشه یا نه
        با صدازننده‌ست، معمولاً با چک کردن is_memory_enabled)."""
        rows = self._connection().execute(
            """
            SELECT role, content FROM messages
            WHERE platform = ? AND chat_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (platform, chat_id, limit),
        ).fetchall()
        return [
            ChatMessage(role="assistant", content=OWNER_NOTE + r["content"]) if r["role"] == OWNER_ROLE else ChatMessage(role=r["role"], content=r["content"])
            for r in reversed(rows)
        ]

    def get_messages(self, platform: str, chat_id: str, limit: int = 300) -> list[StoredMessage]:
        """تاریخچه‌ی کامل برای نمایش در صفحه‌ی چت (با زمان)، صرف‌نظر از حافظه."""
        rows = self._connection().execute(
            """
            SELECT role, content, created_at FROM messages
            WHERE platform = ? AND chat_id = ?
            ORDER BY id ASC LIMIT ?
            """,
            (platform, chat_id, limit),
        ).fetchall()
        return [StoredMessage(role=r["role"], content=r["content"], created_at=r["created_at"]) for r in rows]

    def time_since_last_message_seconds(self, platform: str, chat_id: str) -> Optional[float]:
        """چند ثانیه از آخرین پیام (کاربر یا ربات) این مکالمه گذشته؛ None یعنی
        هنوز هیچ پیامی نداره. برای تصمیم «این مکالمه خیلی قدیمیه، انگار تازه‌ست»."""
        row = self._connection().execute(
            "SELECT created_at FROM messages WHERE platform = ? AND chat_id = ? ORDER BY id DESC LIMIT 1",
            (platform, chat_id),
        ).fetchone()
        if row is None:
            return None
        try:
            last = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return None
        return (datetime.now(timezone.utc) - last).total_seconds()

    def purge_older_than(self, days: int) -> int:
        """پیام‌های قدیمی‌تر از ``days`` روز + مکالمه‌های بدونِ پیام و قدیمی (به‌جز بلاک‌شده‌ها: فهرستِ بلاک باید بمونه).
        تعدادِ پیام‌های حذف‌شده رو برمی‌گردونه. ``days <= 0`` = کاری نمی‌کنه."""
        if days <= 0:
            return 0
        conn = self._connection()
        cutoff = f"-{int(days)} day"
        cur = conn.execute("DELETE FROM messages WHERE created_at < datetime('now', ?)", (cutoff,))
        removed = cur.rowcount
        conn.execute(
            "DELETE FROM conversations WHERE blocked = 0 AND updated_at < datetime('now', ?) "
            "AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.platform = conversations.platform AND m.chat_id = conversations.chat_id)",
            (cutoff,),
        )
        conn.execute("DELETE FROM handoff_sessions WHERE status = 'closed' AND last_activity_ts < CAST(strftime('%s','now', ?) AS INTEGER)", (cutoff,))
        conn.execute(  # N12: مشتریِ قدیمی (به‌جز بلاک‌شده‌ها) از CRM هم پاک می‌شه؛ آمارِ سفارش‌ها جداست و دست‌نخورده می‌مونه
            "DELETE FROM customers WHERE opted_out = 0 AND last_seen_ts < CAST(strftime('%s','now', ?) AS INTEGER) "
            "AND NOT EXISTS (SELECT 1 FROM conversations c WHERE c.platform = customers.platform AND c.chat_id = customers.user_id AND c.blocked = 1)",
            (cutoff,),
        )
        conn.execute("DELETE FROM broadcast_log WHERE ts > 0 AND ts < CAST(strftime('%s','now', ?) AS INTEGER)", (cutoff,))  # N7: لاگِ گیرنده‌های قدیمی
        conn.commit()
        return removed

    def forget_chat(self, platform: str, chat_id: str) -> None:
        """«حذفِ داده‌ی من» (/forget): پیام‌ها + ردیفِ مکالمه + نگاشتِ Reply. اگه چت بلاک بوده، ردیفِ بلاک می‌مونه
        (فقط نامِ نمایشی پاک می‌شه) — /forget نباید بلاک رو دور بزنه."""
        conn = self._connection()
        conn.execute("DELETE FROM messages WHERE platform = ? AND chat_id = ?", (platform, str(chat_id)))
        conn.execute("DELETE FROM relay_map WHERE customer_platform = ? AND customer_chat_id = ?", (platform, str(chat_id)))
        conn.execute("DELETE FROM handoff_sessions WHERE platform = ? AND chat_id = ?", (platform, str(chat_id)))
        conn.execute("DELETE FROM conversations WHERE platform = ? AND chat_id = ? AND blocked = 0", (platform, str(chat_id)))
        conn.execute("UPDATE conversations SET display_name = '' WHERE platform = ? AND chat_id = ?", (platform, str(chat_id)))
        # N12: نام/یوزرنیم/شماره/یادداشت هم پاک. N7: اگه مشتری /stop زده بود فقط «علامتِ لغو» (شناسه + پرچم، بدونِ هیچ مشخصاتی)
        # می‌مونه تا /forget ترکِ اشتراکِ پیامِ همگانی رو دور نزنه.
        conn.execute("DELETE FROM customers WHERE platform = ? AND user_id = ? AND opted_out = 0", (platform, str(chat_id)))
        conn.execute(
            "UPDATE customers SET first_name = '', last_name = '', username = '', language_code = '', is_premium = 0, phone = '', "
            "msg_count = 0, tags = '', notes = '', unreachable = 0, first_seen_ts = 0, last_seen_ts = 0 "
            "WHERE platform = ? AND user_id = ? AND opted_out = 1",
            (platform, str(chat_id)),
        )
        conn.execute("DELETE FROM broadcast_log WHERE platform = ? AND user_id = ?", (platform, str(chat_id)))
        conn.commit()

    def clear_history(self, platform: str, chat_id: str) -> None:
        """فقط پیام‌های یه مکالمه رو پاک می‌کنه (نه خودِ مکالمه — تنظیم حافظه و
        وضعیت بلاک دست‌نخورده می‌مونن). برای دکمه‌ی «پاک‌کردن تاریخچه» توی UI،
        جدا از سوییچ «حافظه»: سوییچ یعنی از این به بعد تاریخچه استفاده نشه،
        این یعنی خودِ تاریخچه‌ی قبلی پاک بشه."""
        conn = self._connection()
        conn.execute("DELETE FROM messages WHERE platform = ? AND chat_id = ?", (platform, chat_id))
        conn.commit()
