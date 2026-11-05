"""کمپین (N8): یک پیامِ همگانی (N7) که می‌تونه کدِ تخفیف همراهش بیاره و زمان‌بندی بشه.

ارسالِ واقعی همون موتورِ N7 است (حریمِ مشتری، /stop، سقفِ روزانه، نرخِ امن همه حفظ می‌شن) — این ماژول فقط
تعریفِ کمپین را در ``orders.db`` نگه می‌داره و در ``tick`` (هر چرخه‌ی نگه‌داری) کمپین‌های رسیده را به ``BroadcastService.start`` می‌ده.
اگه ارسالِ همگانیِ دیگه‌ای در جریان باشه یا سقفِ روزانه پر باشه، کمپین تا ۲۴ ساعت دوباره امتحان می‌شه و بعد «ناموفق» با دلیل.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from app.core import broadcast as bc
from app.core.discounts import DiscountError, DiscountStore

STATUS_SCHEDULED, STATUS_RUNNING, STATUS_DONE, STATUS_FAILED, STATUS_CANCELLED = "scheduled", "running", "done", "failed", "cancelled"
RETRY_WINDOW_SECONDS = 24 * 3600
NAME_MAX = 60
MAX_SCHEDULE_AHEAD = 365 * 86400


class CampaignError(ValueError):
    """پیامِ فارسیِ قابل‌نمایش."""


@dataclass
class Campaign:
    id: int
    name: str
    kind: str
    code_id: int
    text: str
    photo: str
    button_label: str
    button_url: str
    audience: bc.Audience
    start_ts: int
    status: str
    broadcast_id: int
    error: str
    created_ts: int
    launched_ts: int


@dataclass
class CampaignStats:
    audience: int = 0
    sent: int = 0
    unreachable: int = 0
    failed: int = 0
    code_uses: int = 0
    revenue_irr: int = 0


def _row(r) -> Campaign:
    return Campaign(
        id=r["id"], name=r["name"], kind=r["kind"], code_id=int(r["code_id"]), text=r["text"], photo=r["photo"],
        button_label=r["button_label"], button_url=r["button_url"], audience=bc.Audience.from_json(r["audience_json"]),
        start_ts=int(r["start_ts"]), status=r["status"], broadcast_id=int(r["broadcast_id"]), error=r["error"],
        created_ts=int(r["created_ts"]), launched_ts=int(r["launched_ts"]),
    )


class CampaignService:
    def __init__(self, order_store, discount_store: DiscountStore, broadcasts, settings_getter, clock=time.time):
        self._orders = order_store
        self._discounts = discount_store
        self._broadcasts = broadcasts  # BroadcastService
        self._get_settings = settings_getter
        self._clock = clock

    def _conn(self):
        return self._orders.connection()

    # ---------- ساخت
    def compose_content(self, text: str, code_id: int = 0, photo: str = "", button_label: str = "", button_url: str = "") -> bc.Content:
        """متنِ نهایی؛ اگه کد همراهه، سطرِ «🎟 کدِ تخفیف: …» ته‌ش اضافه می‌شه (پیامِ مشتری فارسی/انگلیسی نیست، خودِ کد لاتینه)."""
        body = (text or "").strip()
        if code_id:
            code = self._discounts.get(code_id)
            if code is None or not code.active:
                raise CampaignError("کدِ تخفیفِ انتخاب‌شده وجود نداره یا غیرفعاله.")
            body = f"{body}\n\n🎟 {code.code}"
        return bc.Content(body, photo, button_label, button_url)

    def create(self, name: str, text: str, audience: bc.Audience, code_id: int = 0, photo: str = "", button_label: str = "",
              button_url: str = "", start_ts: int = 0) -> int:
        name = " ".join(str(name or "").split())
        if not name or len(name) > NAME_MAX:
            raise CampaignError(f"نامِ کمپین لازمه (حداکثر {NAME_MAX} نویسه).")
        now = int(self._clock())
        if start_ts and (start_ts > now + MAX_SCHEDULE_AHEAD):
            raise CampaignError("زمانِ شروع خیلی دوره.")
        start_ts = max(int(start_ts or 0), now) if start_ts else now
        try:
            content = bc.validate_content(self.compose_content(text, code_id, photo, button_label, button_url), self._get_settings())
            audience = audience.normalized()
        except bc.BroadcastError as exc:
            raise CampaignError(str(exc)) from exc
        conn = self._conn()
        cur = conn.execute(
            """INSERT INTO campaigns (name, kind, code_id, text, photo, button_label, button_url, audience_json, start_ts, status, created_ts)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (name, "discount" if code_id else "announce", code_id, (text or "").strip(), content.photo, content.button_label,
             content.button_url, audience.to_json(), start_ts, STATUS_SCHEDULED, now),
        )
        conn.commit()
        return int(cur.lastrowid)

    # ---------- خواندن
    def get(self, cid: int) -> Optional[Campaign]:
        r = self._conn().execute("SELECT * FROM campaigns WHERE id=?", (cid,)).fetchone()
        return _row(r) if r else None

    def list(self, limit: int = 30) -> list:
        return [_row(r) for r in self._conn().execute("SELECT * FROM campaigns ORDER BY id DESC LIMIT ?", (max(1, int(limit)),)).fetchall()]

    def cancel(self, cid: int) -> bool:
        conn = self._conn()
        cur = conn.execute("UPDATE campaigns SET status=? WHERE id=? AND status=?", (STATUS_CANCELLED, cid, STATUS_SCHEDULED))
        conn.commit()
        return cur.rowcount == 1

    def stats(self, cid: int) -> CampaignStats:
        c = self.get(cid)
        out = CampaignStats()
        if c is None or not c.broadcast_id:
            return out
        counts = self._broadcasts.store.counts(c.broadcast_id)
        out.audience = sum(counts.values())
        out.sent, out.unreachable, out.failed = counts.get("sent", 0), counts.get("unreachable", 0), counts.get("failed", 0)
        if c.code_id:
            row = self._conn().execute(
                """SELECT COUNT(*) AS n, COALESCE(SUM(o.total_irr),0) AS rev FROM discount_usage u JOIN orders o ON o.id=u.order_id
                   WHERE u.code_id=? AND u.released=0 AND o.status IN ('paid','confirmed') AND u.created_ts>=?""",
                (c.code_id, c.launched_ts),
            ).fetchone()
            out.code_uses, out.revenue_irr = int(row["n"]), int(row["rev"])
        return out

    # ---------- چرخه‌ی نگه‌داری
    def tick(self, now: Optional[float] = None) -> list:
        """کمپین‌های رسیده را شروع می‌کنه و کمپین‌های تمام‌شده را می‌بنده. لیستِ ``(id, وضعیتِ تازه)`` تغییرها."""
        now = self._clock() if now is None else now
        changed = []
        conn = self._conn()
        for r in conn.execute("SELECT * FROM campaigns WHERE status IN (?, ?) ORDER BY start_ts, id", (STATUS_SCHEDULED, STATUS_RUNNING)).fetchall():
            c = _row(r)
            if c.status == STATUS_RUNNING:
                if self._broadcasts.store.status_of(c.broadcast_id) not in bc.ACTIVE_STATUSES:
                    self._set(c.id, STATUS_DONE)
                    changed.append((c.id, STATUS_DONE))
                continue
            if c.start_ts > now:
                continue
            try:
                content = self.compose_content(c.text, c.code_id, c.photo, c.button_label, c.button_url)
                bid = self._broadcasts.start(content, c.audience, created_by="campaign")
            except (bc.BroadcastError, CampaignError) as exc:
                if now - c.start_ts > RETRY_WINDOW_SECONDS or isinstance(exc, CampaignError):
                    self._set(c.id, STATUS_FAILED, error=str(exc)[:300])
                    changed.append((c.id, STATUS_FAILED))
                continue  # ارسالِ دیگه در جریانه/سقفِ روزانه پره ← چرخه‌ی بعد دوباره
            conn.execute("UPDATE campaigns SET status=?, broadcast_id=?, launched_ts=?, error='' WHERE id=?", (STATUS_RUNNING, bid, int(now), c.id))
            conn.commit()
            changed.append((c.id, STATUS_RUNNING))
        return changed

    def _set(self, cid: int, status: str, error: str = "") -> None:
        conn = self._conn()
        conn.execute("UPDATE campaigns SET status=?, error=? WHERE id=?", (status, error, cid))
        conn.commit()


__all__ = ["Campaign", "CampaignError", "CampaignService", "CampaignStats", "DiscountError"]
