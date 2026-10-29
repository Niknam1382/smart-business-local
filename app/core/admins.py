"""مدیرانِ ربات (N11): نقش‌ها، دعوتِ یک‌بارمصرف (لینکِ عمیق/QR)، افزودن با شناسه‌ی عددی و لاگِ ممیزی.

* **مالک** همان چتِ ثبت‌شده با ``/owner <کد>`` است (``settings.owner_chats``) و همه‌کاره؛ در جدولِ ``admins`` نیست.
* **نقش‌ها**: ``manager`` (سفارش/گفتگو/محصول) · ``support`` (گفتگو/پشتیبانی) · ``viewer`` (فقط‌مشاهده).
* **دعوت**: توکنِ تصادفیِ ۹۶ بیتی، فقط هشِ SHA-256 ذخیره می‌شه، ۱۰ دقیقه اعتبار، **یک‌بارمصرف** (اتمیک)، و فقط روی همان پلتفرم.
* **با شناسه‌ی عددی**: ردیفِ «در انتظار» (۷ روز) ساخته می‌شه و با *اولین پیامِ همان شناسه* فعال می‌شه. (اشتباهِ تایپیِ شناسه یعنی
  غریبه‌ای با آن شناسه ادمین می‌شه؛ برای همین فقط شناسه‌ی خودِ فرد را وارد کنید — در UI هم هشدار داده می‌شه.)
* هر کنترلِ دسترسی **سمتِ سرور** با ``can(role, capability)`` انجام می‌شه؛ داده‌ی callbackِ دکمه هرگز مرجعِ مجوز نیست.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Callable, Optional

from app.core.conversations import ConversationStore

ROLE_OWNER = "owner"
ROLE_MANAGER = "manager"
ROLE_SUPPORT = "support"
ROLE_VIEWER = "viewer"
ASSIGNABLE_ROLES = (ROLE_MANAGER, ROLE_SUPPORT, ROLE_VIEWER)
ROLE_LABEL_FA = {ROLE_OWNER: "مالک", ROLE_MANAGER: "مدیر", ROLE_SUPPORT: "پشتیبان", ROLE_VIEWER: "ناظر"}

STATUS_ACTIVE = "active"
STATUS_PENDING = "pending"
STATUS_DISABLED = "disabled"

# قابلیت‌ها
CAP_PANEL = "panel.open"
CAP_ORDERS_VIEW = "orders.view"
CAP_ORDERS_DECIDE = "orders.decide"
CAP_STOCK_VIEW = "stock.view"
CAP_STOCK_EDIT = "stock.edit"
CAP_PRODUCTS_TOGGLE = "products.toggle"
CAP_STATS_VIEW = "stats.view"
CAP_SUPPORT_VIEW = "support.view"
CAP_SUPPORT_REPLY = "support.reply"
CAP_ADMINS_MANAGE = "admins.manage"
CAP_OWNER_UNLINK = "owner.unlink"
CAP_DISCOUNTS_TOGGLE = "discounts.toggle"  # N8: فعال/غیرفعال‌کردنِ کدِ تخفیف (فقط مالک/مدیر)
CAP_FINANCE_VIEW = "finance.view"  # N19: خلاصه‌ی مالی (پیش‌فرض فقط مالک؛ مالک می‌تونه به «مدیر» بده: finance_manager_access)
CAP_FINANCE_EDIT = "finance.edit"  # N19: ثبت/اصلاحِ دفتر (فقط مالک؛ در برنامه‌ی دسکتاپ)
CAP_INVOICE_RESEND = "invoice.resend"  # N19: ارسالِ مجددِ فاکتور برای مشتری (مالک/مدیر)

CAPABILITIES = {
    ROLE_OWNER: frozenset({
        CAP_PANEL, CAP_ORDERS_VIEW, CAP_ORDERS_DECIDE, CAP_STOCK_VIEW, CAP_STOCK_EDIT, CAP_PRODUCTS_TOGGLE,
        CAP_STATS_VIEW, CAP_SUPPORT_VIEW, CAP_SUPPORT_REPLY, CAP_ADMINS_MANAGE, CAP_OWNER_UNLINK, CAP_DISCOUNTS_TOGGLE,
        CAP_FINANCE_VIEW, CAP_FINANCE_EDIT, CAP_INVOICE_RESEND,
    }),
    ROLE_MANAGER: frozenset({
        CAP_PANEL, CAP_ORDERS_VIEW, CAP_ORDERS_DECIDE, CAP_STOCK_VIEW, CAP_STOCK_EDIT, CAP_PRODUCTS_TOGGLE,
        CAP_STATS_VIEW, CAP_SUPPORT_VIEW, CAP_SUPPORT_REPLY, CAP_DISCOUNTS_TOGGLE, CAP_INVOICE_RESEND,
    }),
    ROLE_SUPPORT: frozenset({CAP_PANEL, CAP_SUPPORT_VIEW, CAP_SUPPORT_REPLY}),
    ROLE_VIEWER: frozenset({CAP_PANEL, CAP_ORDERS_VIEW, CAP_STOCK_VIEW, CAP_STATS_VIEW, CAP_SUPPORT_VIEW}),
}

INVITE_TTL_SECONDS = 600
PENDING_TTL_SECONDS = 7 * 86400
INVITE_PREFIX = "admin_"
MAX_AUDIT_ROWS = 2000
_MAX_NAME = 128


_DEEP_LINKS = {
    "telegram": "https://t.me/{username}?start=admin_{token}",
    "bale": "https://ble.ir/{username}?start=admin_{token}",
}


def invite_link(platform: str, username: str, token: str) -> str:
    """لینکِ عمیقِ دعوت (یا ``""`` اگه نامِ کاربریِ ربات/پلتفرم معلوم نیست). اگه لینک باز نشد، فرستادنِ
    ``start_command(token)`` به ربات همان کار را می‌کنه."""
    template = _DEEP_LINKS.get(platform)
    clean = (username or "").strip().lstrip("@")
    return template.format(username=clean, token=token) if (template and clean) else ""


def start_command(token: str) -> str:
    return f"/start {INVITE_PREFIX}{token}"


def can(role: str, capability: str) -> bool:
    return capability in CAPABILITIES.get(role, frozenset())


# مالک می‌تونه این قابلیت‌ها را (با تنظیم) به نقشِ «مدیر» هم بده؛ به هیچ نقشِ دیگری هرگز.
MANAGER_GRANTABLE = frozenset({CAP_FINANCE_VIEW})


def can_effective(role: str, capability: str, manager_finance_access: bool = False) -> bool:
    """``can`` + اعطای اختیاریِ مالک (``finance_manager_access``) به «مدیر»."""
    if can(role, capability):
        return True
    return role == ROLE_MANAGER and manager_finance_access and capability in MANAGER_GRANTABLE


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _clean(text, limit: int = _MAX_NAME) -> str:
    return "".join(ch if ch >= " " and ch != "\x7f" else " " for ch in str(text or "")).strip()[:limit]


@dataclass
class Admin:
    platform: str
    user_id: str
    name: str = ""
    username: str = ""
    role: str = ROLE_VIEWER
    status: str = STATUS_ACTIVE
    added_by: str = ""
    added_ts: int = 0
    last_active_ts: int = 0
    pending_expires_ts: int = 0

    @property
    def display_name(self) -> str:
        return self.name or (f"@{self.username}" if self.username else self.user_id)


@dataclass(frozen=True)
class InviteResult:
    status: str  # ok | owner | unknown | expired | used | wrong_platform
    admin: Optional[Admin] = None
    role: str = ""


def _row_to_admin(row) -> Admin:
    return Admin(
        platform=row["platform"], user_id=row["user_id"], name=row["name"], username=row["username"], role=row["role"],
        status=row["status"], added_by=row["added_by"], added_ts=int(row["added_ts"]), last_active_ts=int(row["last_active_ts"]),
        pending_expires_ts=int(row["pending_expires_ts"]),
    )


class AdminStore:
    """جدولِ ``admins`` + دعوت‌ها + لاگِ ممیزی در دیتابیسِ مکالمه‌ها. ``get_owner_chats`` → ``{platform: chat_id}`` مالک."""

    def __init__(self, store: ConversationStore, get_owner_chats: Callable[[], dict] = lambda: {}):
        self._store = store
        self._owner_chats = get_owner_chats

    def _conn(self):
        return self._store.connection()

    # ---------------------------------------------------------------- نقش ----

    def is_owner(self, platform: str, user_id: str) -> bool:
        chats = self._owner_chats() or {}
        return chats.get(platform) == str(user_id)

    def role_of(self, platform: str, user_id: str, now: Optional[float] = None) -> str:
        """``owner``/``manager``/``support``/``viewer`` یا ``""`` (ادمین نیست؛ در انتظار/غیرفعال/منقضی هم ادمین حساب نمی‌شه)."""
        if self.is_owner(platform, user_id):
            return ROLE_OWNER
        row = self._conn().execute("SELECT role, status FROM admins WHERE platform = ? AND user_id = ?", (platform, str(user_id))).fetchone()
        if row and row["status"] == STATUS_ACTIVE and row["role"] in ASSIGNABLE_ROLES:
            return row["role"]
        return ""

    def can(self, platform: str, user_id: str, capability: str) -> bool:
        return can(self.role_of(platform, user_id), capability)

    def get(self, platform: str, user_id: str) -> Optional[Admin]:
        row = self._conn().execute("SELECT * FROM admins WHERE platform = ? AND user_id = ?", (platform, str(user_id))).fetchone()
        return _row_to_admin(row) if row else None

    def list(self, now: Optional[float] = None) -> list:
        """همه‌ی مدیران (فعال/غیرفعال/در انتظار)؛ «در انتظار»های منقضی‌شده پاک می‌شن."""
        ts = int(now if now is not None else time.time())
        self._conn().execute("DELETE FROM admins WHERE status = ? AND pending_expires_ts < ?", (STATUS_PENDING, ts))
        self._conn().commit()
        rows = self._conn().execute("SELECT * FROM admins ORDER BY (status = 'active') DESC, added_ts, user_id").fetchall()
        return [_row_to_admin(r) for r in rows]

    def active_with(self, capability: str) -> list:
        """مدیرانِ فعالی که این قابلیت را دارن (برای اعلان‌ها)؛ مالک جدا از ``owner_chats`` می‌آد."""
        return [a for a in self.list() if a.status == STATUS_ACTIVE and can(a.role, capability)]

    # ---------------------------------------------------------------- دعوت ----

    def create_invite(self, platform: str, role: str, now: Optional[float] = None, ttl: int = INVITE_TTL_SECONDS) -> str:
        """توکنِ یک‌بارمصرف می‌سازه (فقط هشش ذخیره می‌شه). ``start=admin_<token>`` را در لینکِ عمیق بگذار."""
        if role not in ASSIGNABLE_ROLES:
            raise ValueError("نقشِ نامعتبر")
        token = secrets.token_urlsafe(12)
        ts = int(now if now is not None else time.time())
        self._conn().execute(
            "INSERT INTO admin_invites (token_hash, platform, role, created_ts, expires_ts) VALUES (?, ?, ?, ?, ?)",
            (_hash(token), platform, role, ts, ts + ttl),
        )
        self._conn().commit()
        self.audit("invite_created", actor="app", detail=f"{platform}:{role}")
        return token

    def accept_invite(self, token: str, platform: str, user_id: str, name: str = "", username: str = "", now: Optional[float] = None) -> InviteResult:
        ts = int(now if now is not None else time.time())
        token = (token or "").strip()
        row = self._conn().execute("SELECT * FROM admin_invites WHERE token_hash = ?", (_hash(token),)).fetchone() if token else None
        if row is None:
            return InviteResult("unknown")
        if row["platform"] != platform:
            return InviteResult("wrong_platform")
        if row["used_ts"]:
            return InviteResult("used")
        if row["expires_ts"] < ts:
            return InviteResult("expired")
        if self.is_owner(platform, user_id):
            return InviteResult("owner")
        # مصرفِ اتمیک: اگه دو نفر هم‌زمان بزنن فقط یکی برنده‌ست
        claim = self._conn().execute(
            "UPDATE admin_invites SET used_ts = ?, used_by = ? WHERE token_hash = ? AND used_ts = 0 AND expires_ts >= ?",
            (ts, f"{platform}:{user_id}", _hash(token), ts),
        )
        self._conn().commit()
        if claim.rowcount != 1:
            return InviteResult("used")
        admin = self._upsert(platform, str(user_id), row["role"], name, username, added_by="invite", now=ts)
        self.audit("admin_added", platform=platform, user_id=str(user_id), actor="invite", detail=f"role={row['role']}")
        return InviteResult("ok", admin, row["role"])

    # ----------------------------------------------------- افزودن با شناسه ----

    def add_by_id(self, platform: str, user_id: str, role: str, name: str = "", now: Optional[float] = None) -> Admin:
        """ردیفِ «در انتظار» (۷ روز): با اولین پیامِ همان شناسه فعال می‌شه."""
        uid = str(user_id).strip()
        if not uid.isdigit():
            raise ValueError("شناسه باید عدد باشد")
        if role not in ASSIGNABLE_ROLES:
            raise ValueError("نقشِ نامعتبر")
        if self.is_owner(platform, uid):
            raise ValueError("این شناسه مالک است")
        ts = int(now if now is not None else time.time())
        existing = self.get(platform, uid)
        status = existing.status if existing and existing.status == STATUS_ACTIVE else STATUS_PENDING
        admin = self._upsert(platform, uid, role, name, "", added_by="app", now=ts, status=status, pending_expires=ts + PENDING_TTL_SECONDS)
        self.audit("admin_added", platform=platform, user_id=uid, actor="app", detail=f"role={role} by_id")
        return admin

    def activate_if_pending(self, platform: str, user_id: str, name: str = "", username: str = "", now: Optional[float] = None) -> Optional[Admin]:
        """اولین پیامِ یک شناسه‌ی «در انتظار» ⇒ فعال. ``None`` اگه کسی در انتظار نبود/منقضی بود."""
        ts = int(now if now is not None else time.time())
        admin = self.get(platform, user_id)
        if admin is None or admin.status != STATUS_PENDING or admin.pending_expires_ts < ts:
            return None
        self._conn().execute(
            "UPDATE admins SET status = ?, pending_expires_ts = 0, name = CASE WHEN name = '' THEN ? ELSE name END, username = ?, last_active_ts = ? "
            "WHERE platform = ? AND user_id = ? AND status = ?",
            (STATUS_ACTIVE, _clean(name), _clean(username, 64).lstrip("@"), ts, platform, str(user_id), STATUS_PENDING),
        )
        self._conn().commit()
        self.audit("admin_activated", platform=platform, user_id=str(user_id), actor="self", detail=f"role={admin.role}")
        return self.get(platform, user_id)

    def _upsert(self, platform, user_id, role, name, username, *, added_by, now, status=STATUS_ACTIVE, pending_expires=0) -> Admin:
        self._conn().execute(
            """
            INSERT INTO admins (platform, user_id, name, username, role, status, added_by, added_ts, last_active_ts, pending_expires_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(platform, user_id) DO UPDATE SET
                role = excluded.role, status = excluded.status, added_by = excluded.added_by,
                name = CASE WHEN excluded.name != '' THEN excluded.name ELSE admins.name END,
                username = CASE WHEN excluded.username != '' THEN excluded.username ELSE admins.username END,
                pending_expires_ts = excluded.pending_expires_ts,
                last_active_ts = CASE WHEN excluded.status = 'active' THEN excluded.last_active_ts ELSE admins.last_active_ts END
            """,
            (platform, user_id, _clean(name), _clean(username, 64).lstrip("@"), role, status, added_by, now, now if status == STATUS_ACTIVE else 0, pending_expires),
        )
        self._conn().commit()
        return self.get(platform, user_id)

    # ---------------------------------------------------------- مدیریت (UI) ----

    def set_role(self, platform: str, user_id: str, role: str, actor: str = "app") -> bool:
        if role not in ASSIGNABLE_ROLES:
            raise ValueError("نقشِ نامعتبر")
        cur = self._conn().execute("UPDATE admins SET role = ? WHERE platform = ? AND user_id = ?", (role, platform, str(user_id)))
        self._conn().commit()
        if cur.rowcount:
            self.audit("role_changed", platform=platform, user_id=str(user_id), actor=actor, detail=f"role={role}")
        return cur.rowcount > 0

    def set_active(self, platform: str, user_id: str, active: bool, actor: str = "app") -> bool:
        cur = self._conn().execute(
            "UPDATE admins SET status = ? WHERE platform = ? AND user_id = ? AND status != ?",
            (STATUS_ACTIVE if active else STATUS_DISABLED, platform, str(user_id), STATUS_PENDING),
        )
        self._conn().commit()
        if cur.rowcount:
            self.audit("admin_enabled" if active else "admin_disabled", platform=platform, user_id=str(user_id), actor=actor)
        return cur.rowcount > 0

    def remove(self, platform: str, user_id: str, actor: str = "app") -> bool:
        cur = self._conn().execute("DELETE FROM admins WHERE platform = ? AND user_id = ?", (platform, str(user_id)))
        self._conn().commit()
        if cur.rowcount:
            self.audit("admin_removed", platform=platform, user_id=str(user_id), actor=actor)
        return cur.rowcount > 0

    def touch(self, platform: str, user_id: str, name: str = "", username: str = "", now: Optional[float] = None) -> None:
        """آخرین فعالیتِ یک مدیرِ فعال (و به‌روزرسانیِ نام/یوزرنیم از پلتفرم)."""
        ts = int(now if now is not None else time.time())
        self._conn().execute(
            "UPDATE admins SET last_active_ts = ?, name = CASE WHEN name = '' THEN ? ELSE name END, "
            "username = CASE WHEN ? != '' THEN ? ELSE username END WHERE platform = ? AND user_id = ? AND status = ?",
            (ts, _clean(name), _clean(username, 64).lstrip("@"), _clean(username, 64).lstrip("@"), platform, str(user_id), STATUS_ACTIVE),
        )
        self._conn().commit()

    # ---------------------------------------------------------------- ممیزی ----

    def audit(self, action: str, *, platform: str = "", user_id: str = "", actor: str = "", detail: str = "", now: Optional[float] = None) -> None:
        conn = self._conn()
        conn.execute(
            "INSERT INTO admin_audit (ts, platform, user_id, actor, action, detail) VALUES (?, ?, ?, ?, ?, ?)",
            (int(now if now is not None else time.time()), platform, str(user_id), _clean(actor, 96), action, _clean(detail, 300)),
        )
        conn.execute("DELETE FROM admin_audit WHERE id <= (SELECT MAX(id) FROM admin_audit) - ?", (MAX_AUDIT_ROWS,))
        conn.commit()

    def recent_audit(self, limit: int = 50) -> list:
        rows = self._conn().execute("SELECT ts, platform, user_id, actor, action, detail FROM admin_audit ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        return [dict(r) for r in rows]

    def actor_label(self, platform: str, user_id: str) -> str:
        """برچسبِ «چه کسی» برای ممیزی/``confirmed_by``: ``owner:telegram:123`` یا ``manager:bale:456``."""
        return f"{self.role_of(platform, user_id) or 'unknown'}:{platform}:{user_id}"
