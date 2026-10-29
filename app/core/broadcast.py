"""N7 — پیامِ همگانی (به همه‌ی مشتریان یا یک بخش از آن‌ها) با رعایتِ محدودیتِ پلتفرم‌ها و حریمِ مشتری.

قراردادها (هر کدام تست دارد):
* گیرنده = مشتریِ «ارتباط‌گرفته» (دست‌کم یک پیام داده) که بلاک/لغوکرده (/stop)/دسترس‌ناپذیر نیست — هم هنگامِ ساختنِ فهرست و
  **هم لحظه‌ی ارسال** (اگه وسطِ ارسال /stop بزنه یا بلاک بشه، همان‌جا کنار گذاشته می‌شه).
* صفِ پایدار: گیرنده‌ها snapshotِ لحظه‌ی شروع‌اند و بعد از ری‌استارت ادامه می‌دن. شمارش‌ها همیشه از لاگ محاسبه می‌شن.
* ارسال با ``send_strict``ِ آداپتر (بدونِ fallback/تلاشِ دوباره): ۴۲۹ ← صبر به‌اندازه‌ی retry_after و کند‌شدنِ نرخ؛ ۴۰۳ ← «دسترس‌ناپذیر»؛
  خطای شبکه ← تلاشِ دوباره (حداکثر ۳ بار) و بعد از چند خطای پیاپی ← توقفِ خودکارِ کل ارسال؛ بقیه ← «ناموفق».
* هر لحظه فقط یک ارسالِ فعال؛ سقفِ روزانه (پیش‌فرض ۳)؛ پانویسِ «برای توقف /stop» (پیش‌فرض روشن)؛ بدونِ ثبت در تاریخچه‌ی مشتری.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Optional

from app.core import shop_texts
from app.core.adapter_common import looks_unreachable
from app.core.conversations import ConversationStore
from app.core.customers import Customer, CustomerStore
from app.core.paths import get_app_data_dir
from app.core.ui import safe_url

logger = logging.getLogger(__name__)

PLATFORMS = ("telegram", "bale")

STATUS_RUNNING, STATUS_PAUSED, STATUS_DONE, STATUS_CANCELLED = "running", "paused", "done", "cancelled"
ACTIVE_STATUSES = (STATUS_RUNNING, STATUS_PAUSED)
ROW_PENDING, ROW_SENT, ROW_FAILED, ROW_UNREACHABLE, ROW_SKIPPED = "pending", "sent", "failed", "unreachable", "skipped"
ROW_STATUSES = (ROW_PENDING, ROW_SENT, ROW_FAILED, ROW_UNREACHABLE, ROW_SKIPPED)

MAX_TEXT = 3500  # محتاطانه (تلگرام ۴۰۹۶، بله هم‌مرتبه)
MAX_CAPTION = 1000  # کپشنِ عکس
MAX_BUTTON_LABEL = 28
MAX_URL = 512
MAX_PHOTO_BYTES = 5 * 1024 * 1024
PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
_MEDIA_DIR = "broadcast_media"

MAX_ATTEMPTS = 3  # خطای شبکه: بعد از این‌همه تلاش «ناموفق»
TRANSIENT_PAUSE_AFTER = 5  # این‌قدر خطای شبکه‌ی پیاپی (بینِ گیرنده‌های مختلف) ← توقفِ خودکارِ ارسال
FAILED_PAUSE_AFTER = 5  # این‌قدر «ناموفقِ دائمی»ِ پیاپی (مثلاً لینکِ دکمه/متن را پلتفرم رد می‌کنه) ← توقفِ خودکار
RATE_LIMIT_SLOW_AFTER = 3  # این‌قدر ۴۲۹ِ پیاپی ← نرخِ آن پلتفرم نصف می‌شه
MAX_RETRY_WAIT = 120.0
DEFAULT_RATES = {"telegram": 20.0, "bale": 5.0}
RATE_LIMITS = {"telegram": (1, 25), "bale": (1, 10)}
DAILY_CAP_RANGE = (1, 50)
DAILY_SECONDS = 86400

PURCHASE_ALL, PURCHASE_BUYERS, PURCHASE_NONE = "all", "buyers", "no_orders"
PURCHASES = (PURCHASE_ALL, PURCHASE_BUYERS, PURCHASE_NONE)
ACTIVITY_ALL, ACTIVITY_7D, ACTIVITY_30D, ACTIVITY_INACTIVE, ACTIVITY_NEW = "all", "active_7d", "active_30d", "inactive_30d", "new_7d"
ACTIVITIES = (ACTIVITY_ALL, ACTIVITY_7D, ACTIVITY_30D, ACTIVITY_INACTIVE, ACTIVITY_NEW)
LANG_ALL, LANG_FA, LANG_EN, LANG_OTHER = "", "fa", "en", "other"
LANGUAGES = (LANG_ALL, LANG_FA, LANG_EN, LANG_OTHER)
_DAY = 86400
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")  # همه‌ی کنترل‌ها به‌جز \n و \t


class BroadcastError(ValueError):
    """پیامِ فارسیِ قابل‌نمایش به مالک."""


# ------------------------------------------------------------------------------ محتوا ----


@dataclass(frozen=True)
class Content:
    text: str
    photo: str = ""  # مسیرِ فایلِ محلی (کپی‌شده در پوشه‌ی داده با ``store_photo``)
    button_label: str = ""
    button_url: str = ""
    footer: bool = True

    @property
    def button(self) -> Optional[tuple]:
        return (self.button_label, self.button_url) if self.button_label and self.button_url else None


def _clean_text(text) -> str:
    return _CONTROL.sub("", str(text or "").replace("\r\n", "\n").replace("\r", "\n")).strip()


def footer_text(settings, lang: str) -> str:
    return shop_texts.render(settings, "broadcast.footer", lang)


def _longest_footer(settings) -> int:
    return max(len(footer_text(settings, lang)) for lang in shop_texts.SUPPORTED_LANGS)


def compose(content: Content, settings, lang: str) -> str:
    """متنِ نهاییِ ارسال برای گیرنده‌ای با این زبان (پانویس به زبانِ خودِ گیرنده)."""
    if not content.footer:
        return content.text
    foot = footer_text(settings, lang)
    return f"{content.text}\n\n{foot}" if foot else content.text


def validate_content(content: Content, settings) -> Content:
    """محتوای پاک‌شده یا ``BroadcastError``. طولِ مجاز با «بلندترین پانویس» سنجیده می‌شه تا هیچ زبانی از سقف رد نشه."""
    text = _clean_text(content.text)
    if not text:
        raise BroadcastError("متنِ پیام خالیه.")
    photo = str(content.photo or "").strip()
    limit = MAX_CAPTION if photo else MAX_TEXT
    extra = (2 + _longest_footer(settings)) if content.footer else 0
    if len(text) + extra > limit:
        raise BroadcastError(
            f"متن بیش از حد بلنده (حداکثر {limit - extra} نویسه{' برای پیامِ عکس‌دار' if photo else ''}؛ الان {len(text)})."
        )
    label = " ".join(_clean_text(content.button_label).split())
    url = _clean_text(content.button_url).replace(" ", "")
    if label or url:
        if not (label and url):
            raise BroadcastError("برای دکمه هم عنوان و هم لینک لازمه.")
        if len(label) > MAX_BUTTON_LABEL:
            raise BroadcastError(f"عنوانِ دکمه حداکثر {MAX_BUTTON_LABEL} نویسه می‌تونه باشه.")
        if len(url) > MAX_URL or not safe_url(url):
            raise BroadcastError("لینکِ دکمه باید با http:// یا https:// شروع بشه.")
    if photo:
        path = Path(photo)
        if path.suffix.lower() not in PHOTO_EXTENSIONS:
            raise BroadcastError("فرمتِ عکس پشتیبانی نمی‌شه (jpg، png یا webp بده).")
        try:  # فقط واقعیت‌ها را اینجا جمع می‌کنیم؛ BroadcastError زیرکلاسِ ValueError است و نباید داخلِ این try پرتاب شود
            is_file = path.is_file()
            size = path.stat().st_size if is_file else 0
        except (OSError, ValueError) as exc:  # ValueError: مسیر با بایتِ NUL
            raise BroadcastError("فایلِ عکس خونده نشد.") from exc
        if not is_file:
            raise BroadcastError("فایلِ عکس پیدا نشد.")
        if size > MAX_PHOTO_BYTES:
            raise BroadcastError("حجمِ عکس بیشتر از ۵ مگابایته.")
    return Content(text=text, photo=photo, button_label=label, button_url=url, footer=bool(content.footer))


def store_photo(source_path: str) -> str:
    """عکسِ انتخاب‌شده را با نامِ یکتا در پوشه‌ی داده کپی می‌کند (اگه فایلِ اصلی جابه‌جا شد، ارسال نشکند)؛ مسیرِ جدید."""
    src = Path(source_path)
    if src.suffix.lower() not in PHOTO_EXTENSIONS:
        raise BroadcastError("فرمتِ عکس پشتیبانی نمی‌شه (jpg، png یا webp بده).")
    try:
        size = src.stat().st_size
    except (OSError, ValueError) as exc:
        raise BroadcastError("فایلِ عکس پیدا یا خونده نشد.") from exc
    if size > MAX_PHOTO_BYTES:
        raise BroadcastError("حجمِ عکس بیشتر از ۵ مگابایته.")
    try:
        dest_dir = get_app_data_dir() / _MEDIA_DIR
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{uuid.uuid4().hex}{src.suffix.lower()}"
        shutil.copyfile(src, dest)
    except (OSError, ValueError) as exc:
        raise BroadcastError("فایلِ عکس ذخیره نشد.") from exc
    return str(dest)


def delete_photo(path: str) -> None:
    if path:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass


# ------------------------------------------------------------------------------ مخاطب ----


@dataclass(frozen=True)
class Audience:
    platform: str = ""  # "" = هر دو
    purchase: str = PURCHASE_ALL
    activity: str = ACTIVITY_ALL
    tag: str = ""
    language: str = LANG_ALL

    def normalized(self) -> "Audience":
        if self.platform not in ("",) + PLATFORMS:
            raise BroadcastError("پیام‌رسانِ انتخاب‌شده معتبر نیست.")
        if self.purchase not in PURCHASES or self.activity not in ACTIVITIES or self.language not in LANGUAGES:
            raise BroadcastError("فیلترِ انتخاب‌شده معتبر نیست.")
        return Audience(self.platform, self.purchase, self.activity, " ".join(str(self.tag or "").split())[:64], self.language)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @staticmethod
    def from_json(text: str) -> "Audience":
        try:
            data = json.loads(text or "{}")
            return Audience(**{k: v for k, v in data.items() if k in {"platform", "purchase", "activity", "tag", "language"}}).normalized()
        except (ValueError, TypeError, AttributeError, BroadcastError):
            return Audience()


def _activity_ok(c: Customer, activity: str, now: float) -> bool:
    if activity == ACTIVITY_7D:
        return now - c.last_seen_ts <= 7 * _DAY
    if activity == ACTIVITY_30D:
        return now - c.last_seen_ts <= 30 * _DAY
    if activity == ACTIVITY_INACTIVE:
        return now - c.last_seen_ts > 30 * _DAY
    if activity == ACTIVITY_NEW:
        return now - c.first_seen_ts <= 7 * _DAY
    return True


def _language_ok(code: str, wanted: str) -> bool:
    code = (code or "").lower()
    if wanted == LANG_FA:
        return code.startswith("fa")
    if wanted == LANG_EN:
        return code.startswith("en")
    if wanted == LANG_OTHER:
        return not code.startswith(("fa", "en"))
    return True


def select_recipients(customers: CustomerStore, audience: Audience, now: Optional[float] = None) -> list:
    """مشتریانِ مجاز برای این مخاطب. هرگز: بلاک‌شده، لغوکرده (/stop)، دسترس‌ناپذیر، یا کسی که هنوز پیامی نداده."""
    audience = audience.normalized()
    now = time.time() if now is None else now
    out = []
    for c in customers.list(platform=audience.platform or None, tag=audience.tag or None, now=now):
        if c.blocked or c.opted_out or c.unreachable or c.msg_count < 1:
            continue
        if audience.purchase == PURCHASE_BUYERS and c.orders_count <= 0:
            continue
        if audience.purchase == PURCHASE_NONE and c.orders_count > 0:
            continue
        if _activity_ok(c, audience.activity, now) and _language_ok(c.language_code, audience.language):
            out.append(c)
    return out


@dataclass
class AudienceSummary:
    total: int = 0
    per_platform: dict = field(default_factory=dict)


# ------------------------------------------------------------------------------ ذخیره ----


@dataclass
class Broadcast:
    id: int
    created_ts: int
    started_ts: int
    finished_ts: int
    status: str
    text: str
    photo: str
    button_label: str
    button_url: str
    footer: bool
    audience: Audience
    created_by: str
    counts: dict = field(default_factory=dict)  # pending/sent/failed/unreachable/skipped

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def content(self) -> Content:
        return Content(self.text, self.photo, self.button_label, self.button_url, self.footer)

    @property
    def processed(self) -> int:
        return self.total - self.counts.get(ROW_PENDING, 0)


class BroadcastStore:
    def __init__(self, store: ConversationStore):
        self._store = store

    def _conn(self):
        return self._store.connection()

    def create(self, content: Content, audience: Audience, recipients: list, *, created_by: str = "app", now: Optional[float] = None) -> int:
        ts = int(time.time() if now is None else now)
        conn = self._conn()
        cur = conn.execute(
            "INSERT INTO broadcasts (created_ts, started_ts, status, text, photo, button_label, button_url, footer, filters, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, ts, STATUS_RUNNING, content.text, content.photo, content.button_label, content.button_url, 1 if content.footer else 0,
             audience.to_json(), created_by),
        )
        bid = int(cur.lastrowid)
        conn.executemany(
            "INSERT OR IGNORE INTO broadcast_log (broadcast_id, platform, user_id, status) VALUES (?, ?, ?, 'pending')",
            [(bid, str(p), str(u)) for p, u in recipients],
        )
        conn.commit()
        return bid

    def counts(self, bid: int) -> dict:
        out = {s: 0 for s in ROW_STATUSES}
        for row in self._conn().execute("SELECT status, COUNT(*) AS n FROM broadcast_log WHERE broadcast_id = ? GROUP BY status", (bid,)):
            out[row["status"]] = int(row["n"])
        return out

    def _row(self, row) -> Broadcast:
        return Broadcast(
            id=int(row["id"]), created_ts=int(row["created_ts"]), started_ts=int(row["started_ts"]), finished_ts=int(row["finished_ts"]),
            status=row["status"], text=row["text"], photo=row["photo"], button_label=row["button_label"], button_url=row["button_url"],
            footer=bool(row["footer"]), audience=Audience.from_json(row["filters"]), created_by=row["created_by"], counts=self.counts(int(row["id"])),
        )

    def get(self, bid: int) -> Optional[Broadcast]:
        row = self._conn().execute("SELECT * FROM broadcasts WHERE id = ?", (bid,)).fetchone()
        return self._row(row) if row else None

    def recent(self, limit: int = 20) -> list:
        rows = self._conn().execute("SELECT * FROM broadcasts ORDER BY id DESC LIMIT ?", (max(1, int(limit)),)).fetchall()
        return [self._row(r) for r in rows]

    def status_of(self, bid: int) -> str:
        row = self._conn().execute("SELECT status FROM broadcasts WHERE id = ?", (bid,)).fetchone()
        return row["status"] if row else ""

    def active_id(self) -> Optional[int]:
        row = self._conn().execute("SELECT id FROM broadcasts WHERE status IN ('running', 'paused') ORDER BY id LIMIT 1").fetchone()
        return int(row["id"]) if row else None

    def running_ids(self) -> list:
        return [int(r["id"]) for r in self._conn().execute("SELECT id FROM broadcasts WHERE status = 'running' ORDER BY id")]

    def started_since(self, ts: float) -> int:
        return int(self._conn().execute("SELECT COUNT(*) AS n FROM broadcasts WHERE started_ts >= ?", (int(ts),)).fetchone()["n"])

    def set_status(self, bid: int, status: str, now: Optional[float] = None) -> bool:
        """گذارهای مجاز: running↔paused؛ running/paused→done/cancelled. ``True`` فقط اگه واقعاً تغییر کرد."""
        allowed = {
            STATUS_RUNNING: (STATUS_PAUSED,),
            STATUS_PAUSED: (STATUS_RUNNING,),
            STATUS_DONE: (STATUS_RUNNING, STATUS_PAUSED),
            STATUS_CANCELLED: (STATUS_RUNNING, STATUS_PAUSED),
        }.get(status)
        if not allowed:
            return False
        ts = int(time.time() if now is None else now)
        finished = ts if status in (STATUS_DONE, STATUS_CANCELLED) else 0
        marks = ",".join("?" for _ in allowed)
        conn = self._conn()
        cur = conn.execute(f"UPDATE broadcasts SET status = ?, finished_ts = ? WHERE id = ? AND status IN ({marks})", (status, finished, bid, *allowed))  # noqa: S608 — فقط ?های ساخته‌ی خودمان
        conn.commit()
        return cur.rowcount == 1

    def pending(self, bid: int, limit: int, platforms=PLATFORMS) -> list:
        """گیرنده‌های در انتظار فقط روی پلتفرم‌های «آماده» (تا ربات خاموشِ یک پلتفرم، پلتفرمِ دیگر را گرسنه نکند)."""
        platforms = tuple(platforms)
        if not platforms:
            return []
        marks = ",".join("?" for _ in platforms)
        rows = self._conn().execute(
            f"SELECT platform, user_id, attempts FROM broadcast_log WHERE broadcast_id = ? AND status = 'pending' AND platform IN ({marks}) "  # noqa: S608
            "ORDER BY rowid LIMIT ?",
            (bid, *platforms, max(1, int(limit))),
        ).fetchall()
        return [(r["platform"], r["user_id"], int(r["attempts"])) for r in rows]

    def has_pending(self, bid: int) -> bool:
        return self._conn().execute("SELECT 1 FROM broadcast_log WHERE broadcast_id = ? AND status = 'pending' LIMIT 1", (bid,)).fetchone() is not None

    def mark(self, bid: int, platform: str, user_id: str, status: str, error: str = "", now: Optional[float] = None) -> None:
        conn = self._conn()
        conn.execute(
            "UPDATE broadcast_log SET status = ?, error = ?, ts = ? WHERE broadcast_id = ? AND platform = ? AND user_id = ?",
            (status, " ".join(str(error).split())[:200], int(time.time() if now is None else now), bid, platform, str(user_id)),
        )
        conn.commit()

    def bump_attempt(self, bid: int, platform: str, user_id: str, error: str = "") -> int:
        conn = self._conn()
        conn.execute(
            "UPDATE broadcast_log SET attempts = attempts + 1, error = ? WHERE broadcast_id = ? AND platform = ? AND user_id = ?",
            (" ".join(str(error).split())[:200], bid, platform, str(user_id)),
        )
        conn.commit()
        row = conn.execute("SELECT attempts FROM broadcast_log WHERE broadcast_id = ? AND platform = ? AND user_id = ?", (bid, platform, str(user_id))).fetchone()
        return int(row["attempts"]) if row else 0

    def skip_pending(self, bid: int, reason: str, now: Optional[float] = None) -> int:
        conn = self._conn()
        cur = conn.execute(
            "UPDATE broadcast_log SET status = 'skipped', error = ?, ts = ? WHERE broadcast_id = ? AND status = 'pending'",
            (reason, int(time.time() if now is None else now), bid),
        )
        conn.commit()
        return cur.rowcount

    def errors(self, bid: int, limit: int = 5) -> list:
        """خطاهای متمایز با تعداد: [(متن, تعداد)] — برای نمایش به مالک."""
        rows = self._conn().execute(
            "SELECT error, COUNT(*) AS n FROM broadcast_log WHERE broadcast_id = ? AND status IN ('failed', 'unreachable') AND error != '' "
            "GROUP BY error ORDER BY n DESC LIMIT ?",
            (bid, max(1, int(limit))),
        ).fetchall()
        return [(r["error"], int(r["n"])) for r in rows]


# ------------------------------------------------------------------------------ نرخ و خطا ----


class Pacer:
    """فاصله‌ی ثابت بینِ دو ارسال (۱/نرخ). ساعت و sleep تزریق‌پذیرند (تستِ بدونِ انتظارِ واقعی)."""

    def __init__(self, rate: float, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], Awaitable] = asyncio.sleep):
        self.rate = max(0.5, float(rate))
        self._clock, self._sleep = clock, sleep
        self._next = 0.0

    async def wait(self) -> None:
        now = self._clock()
        if now < self._next:
            await self._sleep(self._next - now)
            now = max(self._clock(), self._next)
        self._next = now + 1.0 / self.rate

    def slow_down(self, floor: float = 1.0) -> None:
        self.rate = max(floor, self.rate / 2)


KIND_RATE_LIMIT, KIND_UNREACHABLE, KIND_TRANSIENT, KIND_FAILED = "rate_limit", "unreachable", "transient", "failed"
_TRANSIENT_NAMES = ("TelegramNetworkError", "TelegramServerError", "ClientError")  # با MRO بررسی می‌شه (زیرکلاس‌هایی مثل ClientOSError هم)


def classify_error(exc: BaseException) -> tuple:
    """خطای ارسال ← (نوع، ثانیه‌ی صبر). ترتیبِ بررسی مهم است: ۴۲۹ و ۴۰۳ قبل از «شبکه»."""
    name = type(exc).__name__
    code = getattr(exc, "error_code", None)
    retry = getattr(exc, "retry_after", None)
    retry = float(retry) if isinstance(retry, (int, float)) and not isinstance(retry, bool) and retry >= 0 else None
    if name == "TelegramRetryAfter" or code == 429:
        return KIND_RATE_LIMIT, retry if retry is not None else 5.0
    if looks_unreachable(exc) or code == 403:
        return KIND_UNREACHABLE, 0.0
    if any(c.__name__ in _TRANSIENT_NAMES for c in type(exc).__mro__) or isinstance(exc, (asyncio.TimeoutError, TimeoutError, ConnectionError, OSError)):
        return KIND_TRANSIENT, 0.0
    if isinstance(code, int) and code >= 500:
        return KIND_TRANSIENT, 0.0
    if name == "BaleApiError" and code is None:  # شبکه/تایم‌اوت/پاسخِ نامفهوم (خطای پلتفرم همیشه کد دارد)
        return KIND_TRANSIENT, 0.0
    return KIND_FAILED, 0.0


def _short(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {' '.join(str(exc).split())}"[:200]


# ------------------------------------------------------------------------------ موتور ----

SendFn = Callable[..., Awaitable[str]]  # (platform, chat_id, text, photo, button) ← شناسه‌ی پیام؛ خطا = exception


class BroadcastEngine:
    """ارسالِ صفِ پایدار؛ داخلِ event loopِ ربات‌ها اجرا می‌شه. هر ``run_once`` یک دسته (پیش‌فرض ۲۰ گیرنده) را برای ارسالِ فعال پردازش می‌کند."""

    def __init__(
        self,
        store: BroadcastStore,
        customers: CustomerStore,
        get_settings: Callable[[], object],
        send: SendFn,
        *,
        ready: Callable[[str], bool] = lambda platform: True,
        notify: Optional[Callable[[str], Awaitable]] = None,
        alert: Optional[Callable[[int, str], None]] = None,  # توقفِ خودکار ← «نیاز به توجه» (bid, دلیلِ کوتاه)
        resolved: Optional[Callable[[int], None]] = None,  # تمام‌شدنِ ارسال ← رفعِ هشدار
        clock: Callable[[], float] = time.time,
        mono: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable] = asyncio.sleep,
        batch: int = 20,
    ):
        self._store, self._customers, self._get_settings, self._send = store, customers, get_settings, send
        self._ready, self._notify, self._alert, self._resolved = ready, notify, alert, resolved
        self._clock, self._mono, self._sleep = clock, mono, sleep
        self._batch = max(1, int(batch))
        self._pacers: dict = {}
        self._rl_streak: dict = {}
        self._transient_streak: dict = {}
        self._failed_streak: dict = {}

    # -- ابزارها --
    def _rate(self, platform: str) -> float:
        low, high = RATE_LIMITS.get(platform, (1, 10))
        raw = getattr(self._get_settings(), f"broadcast_rate_{platform}", DEFAULT_RATES.get(platform, 5.0))
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = DEFAULT_RATES.get(platform, 5.0)
        return min(max(value, low), high)

    def _pacer(self, platform: str) -> Pacer:
        pacer = self._pacers.get(platform)
        if pacer is None:
            pacer = self._pacers[platform] = Pacer(self._rate(platform), clock=self._mono, sleep=self._sleep)
        return pacer

    def _mark(self, bid: int, platform: str, user_id: str, status: str, error: str = "") -> None:
        self._store.mark(bid, platform, user_id, status, error, now=self._clock())

    def _set_status(self, bid: int, status: str) -> bool:
        return self._store.set_status(bid, status, now=self._clock())

    async def _say(self, text: str) -> None:
        if self._notify is None:
            return
        try:
            await self._notify(text)
        except Exception:  # noqa: BLE001 — خرابیِ اعلان هرگز ارسال را نمی‌خوابونه
            logger.debug("اعلانِ پیامِ همگانی به مالک ناموفق بود", exc_info=True)

    async def _auto_pause(self, bid: int, reason: str, message: str) -> bool:
        """توقفِ خودکار + اعلان + هشدارِ «نیاز به توجه» (فقط اگه واقعاً از «در حال اجرا» متوقف شد)."""
        if not self._set_status(bid, STATUS_PAUSED):
            return False
        if self._alert is not None:
            try:
                self._alert(bid, reason)
            except Exception:  # noqa: BLE001
                logger.debug("ثبتِ هشدارِ توقفِ ارسال ناموفق بود", exc_info=True)
        await self._say(message)
        return True

    async def _wait(self, bid: int, seconds: float) -> None:
        """صبر در تکه‌های ≤۱ ثانیه تا pause/cancel دیر اعمال نشود."""
        left = max(0.0, seconds)
        while left > 0 and self._store.status_of(bid) == STATUS_RUNNING:
            step = min(1.0, left)
            await self._sleep(step)
            left -= step

    # -- یک دور --
    def _resolve(self, bid: int) -> None:
        if self._resolved is not None:
            try:
                self._resolved(bid)
            except Exception:  # noqa: BLE001
                logger.debug("رفعِ هشدارِ ارسال ناموفق بود", exc_info=True)

    async def run_once(self) -> int:
        ids = self._store.running_ids()
        if not ids:  # بینِ دو ارسال: نرخ‌ها از تنظیماتِ تازه ساخته بشن و کندیِ ۴۲۹ِ قبلی به ارسالِ بعدی نرسه
            self._pacers.clear()
            self._rl_streak.clear()
            return 0
        processed = 0
        for bid in ids:
            processed += await self._step(bid)
        return processed

    async def run_forever(self, idle: float = 1.0) -> None:
        while True:
            try:
                worked = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — موتور هرگز نباید بمیرد
                logger.exception("خطا در موتورِ پیامِ همگانی")
                worked = 0
            await self._sleep(0 if worked else idle)

    async def _step(self, bid: int) -> int:
        b = self._store.get(bid)
        if b is None or b.status != STATUS_RUNNING:
            return 0
        if not self._store.has_pending(bid):
            await self._finish(b)
            return 0
        if b.photo and not Path(b.photo).is_file():
            await self._auto_pause(bid, "فایلِ عکسِ پیام پیدا نشد", f"⏸ ارسالِ همگانیِ #{bid} متوقف شد: فایلِ عکسِ پیام پیدا نشد. ارسال را لغو و دوباره بساز.")
            return 0
        settings = self._get_settings()
        ready = tuple(p for p in PLATFORMS if self._ready(p))
        rows = self._store.pending(bid, self._batch, ready)
        done = 0
        for platform, user_id, attempts in rows:
            if self._store.status_of(bid) != STATUS_RUNNING:  # وسطِ دسته pause/cancel شد
                break
            customer = self._customers.get(platform, user_id)
            skip = self._skip_reason(customer)
            if skip:
                self._mark(bid, platform, user_id, ROW_SKIPPED, skip)
                done += 1
                continue
            lang = shop_texts.resolve_lang(settings, customer.language_code)
            text = compose(b.content, settings, lang)
            await self._pacer(platform).wait()
            try:
                await self._send(platform, user_id, text, b.photo, b.content.button)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                kind, delay = classify_error(exc)
                if kind == KIND_RATE_LIMIT:
                    streak = self._rl_streak[platform] = self._rl_streak.get(platform, 0) + 1
                    if streak >= RATE_LIMIT_SLOW_AFTER:
                        self._pacer(platform).slow_down()
                        self._rl_streak[platform] = 0
                    await self._wait(bid, min(delay, MAX_RETRY_WAIT))
                    return done  # همین گیرنده در دورِ بعد دوباره امتحان می‌شه (تلاش حساب نشد)
                if kind == KIND_UNREACHABLE:
                    self._mark(bid, platform, user_id, ROW_UNREACHABLE, _short(exc))
                    self._mark_customer_unreachable(platform, user_id)
                    done += 1
                    continue
                if kind == KIND_TRANSIENT:
                    streak = self._transient_streak[bid] = self._transient_streak.get(bid, 0) + 1
                    if streak >= TRANSIENT_PAUSE_AFTER:
                        self._transient_streak[bid] = 0
                        await self._auto_pause(bid, "خطاهای پیاپیِ اتصال", f"⏸ ارسالِ همگانیِ #{bid} به‌خاطر خطاهای پیاپیِ اتصال متوقف شد. اینترنت/ربات‌ها را چک کن و «ادامه» را بزن.")
                        return done
                    if self._store.bump_attempt(bid, platform, user_id, _short(exc)) >= MAX_ATTEMPTS:
                        self._mark(bid, platform, user_id, ROW_FAILED, _short(exc))
                        done += 1
                    else:
                        await self._wait(bid, 2.0 ** (attempts + 1))
                        return done
                    continue
                self._mark(bid, platform, user_id, ROW_FAILED, _short(exc))
                done += 1
                streak = self._failed_streak[bid] = self._failed_streak.get(bid, 0) + 1
                if streak >= FAILED_PAUSE_AFTER:
                    self._failed_streak[bid] = 0
                    await self._auto_pause(
                        bid, f"{FAILED_PAUSE_AFTER} پیامِ پیاپی رد شد: {_short(exc)}",
                        f"⏸ ارسالِ همگانیِ #{bid} متوقف شد: {FAILED_PAUSE_AFTER} پیامِ پیاپی با این خطا رد شد: «{_short(exc)}». "
                        "احتمالاً متن، عکس یا دکمه مشکل دارد؛ ارسال را لغو کن و اصلاح‌شده دوباره بساز.",
                    )
                    return done
                continue
            self._mark(bid, platform, user_id, ROW_SENT)
            self._rl_streak[platform] = 0
            self._transient_streak[bid] = 0
            self._failed_streak[bid] = 0
            done += 1
        if not self._store.has_pending(bid):
            await self._finish(self._store.get(bid))
        return done

    @staticmethod
    def _skip_reason(customer: Optional[Customer]) -> str:
        if customer is None:
            return "forgotten"
        if customer.blocked:
            return "blocked"
        if customer.opted_out:
            return "opted_out"
        if customer.unreachable:
            return "unreachable"
        return ""

    def _mark_customer_unreachable(self, platform: str, user_id: str) -> None:
        try:
            self._customers.mark_unreachable(platform, str(user_id))
        except Exception:  # noqa: BLE001
            logger.debug("ثبتِ دسترس‌ناپذیریِ مشتری ناموفق بود", exc_info=True)

    async def _finish(self, b: Optional[Broadcast]) -> None:
        if b is None or not self._set_status(b.id, STATUS_DONE):
            return
        self._transient_streak.pop(b.id, None)
        self._failed_streak.pop(b.id, None)
        self._resolve(b.id)
        c = self._store.counts(b.id)
        await self._say(
            f"✅ ارسالِ همگانیِ #{b.id} تموم شد: {c[ROW_SENT]} رسید، {c[ROW_UNREACHABLE]} دسترس‌ناپذیر، "
            f"{c[ROW_FAILED]} ناموفق، {c[ROW_SKIPPED]} کنار گذاشته شد (لغو/بلاک)."
        )


# ------------------------------------------------------------------------------ سرویس ----


class BroadcastService:
    """همان چیزی که UI صدا می‌زند (فقط دیتابیس؛ موتور جدا در لوپِ ربات‌ها صف را می‌خونه)."""

    def __init__(
        self, store: BroadcastStore, customers: CustomerStore, get_settings: Callable[[], object], clock: Callable[[], float] = time.time,
        on_resolved: Optional[Callable[[int], None]] = None,
    ):
        self.store, self._customers, self._get_settings, self._clock = store, customers, get_settings, clock
        self._on_resolved = on_resolved  # ادامه/لغو ← رفعِ هشدارِ «نیاز به توجه»

    def cap(self) -> int:
        low, high = DAILY_CAP_RANGE
        try:
            value = int(getattr(self._get_settings(), "broadcast_daily_cap", 3))
        except (TypeError, ValueError):
            value = 3
        return min(max(value, low), high)

    def summary(self, audience: Audience) -> AudienceSummary:
        people = select_recipients(self._customers, audience, now=self._clock())
        per = {p: 0 for p in PLATFORMS}
        for c in people:
            per[c.platform] = per.get(c.platform, 0) + 1
        return AudienceSummary(total=len(people), per_platform={p: n for p, n in per.items() if n})

    def start(self, content: Content, audience: Audience, *, created_by: str = "app") -> int:
        content = validate_content(content, self._get_settings())
        audience = audience.normalized()
        active = self.store.active_id()
        if active is not None:
            raise BroadcastError(f"ارسالِ همگانیِ #{active} هنوز در جریانه؛ اول تمامش کن یا لغوش کن.")
        now = self._clock()
        cap = self.cap()
        if self.store.started_since(now - DAILY_SECONDS) >= cap:
            raise BroadcastError(f"سقفِ ارسالِ همگانی در هر ۲۴ ساعت ({cap}) پر شده؛ چند ساعتِ دیگر دوباره امتحان کن (سقف را می‌شه از تنظیمات عوض کرد).")
        recipients = select_recipients(self._customers, audience, now=now)
        if not recipients:
            raise BroadcastError("با این فیلترها هیچ مشتریِ مجازی پیدا نشد.")
        return self.store.create(content, audience, [(c.platform, c.user_id) for c in recipients], created_by=created_by, now=now)

    def pause(self, bid: int) -> bool:
        return self.store.set_status(bid, STATUS_PAUSED, now=self._clock())

    def _resolved(self, bid: int) -> None:
        if self._on_resolved is not None:
            try:
                self._on_resolved(bid)
            except Exception:  # noqa: BLE001
                logger.debug("رفعِ هشدارِ ارسال ناموفق بود", exc_info=True)

    def resume(self, bid: int) -> bool:
        ok = self.store.set_status(bid, STATUS_RUNNING, now=self._clock())
        if ok:
            self._resolved(bid)
        return ok

    def cancel(self, bid: int) -> bool:
        if not self.store.set_status(bid, STATUS_CANCELLED, now=self._clock()):
            return False
        self.store.skip_pending(bid, "cancelled", now=self._clock())
        self._resolved(bid)
        return True

    def history(self, limit: int = 20) -> list:
        return self.store.recent(limit)
