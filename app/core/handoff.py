"""
پشتیبانیِ انسانی (R5 «handoff»): مشتری درخواست می‌ده ⇒ از آن لحظه پیام‌هاش *به‌جای AI* به مالک می‌رسه و جواب مالک
(Reply روی پیام یا ``/reply <ref> متن``) به مشتری برمی‌گرده. بعد از بی‌فعالیتی خودکار بسته می‌شه.

``ref`` = حرفِ اولِ پلتفرم + شناسه‌ی چت (مثلاً ``t123456``) — کوتاه، یکتا و قابل‌تایپ.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from app.core import shop_texts, working_hours
from app.core.store_agent import sanitize_display_name
from app.core.ui import Btn, FlowResult, UiMessage

logger = logging.getLogger(__name__)

RELAY_TTL_SECONDS = 7 * 24 * 3600
_PLATFORMS = {"t": "telegram", "b": "bale"}
_REF = re.compile(r"^([tb])(\d{1,20})$")
MAX_RELAY_CHARS = 3000


@dataclass
class HandoffSession:
    platform: str
    chat_id: str
    status: str
    customer_label: str
    started_ts: int
    last_activity_ts: int
    closed_reason: str = ""

    @property
    def ref(self) -> str:
        return make_ref(self.platform, self.chat_id)


def make_ref(platform: str, chat_id: str) -> str:
    return f"{platform[:1]}{chat_id}"


def parse_ref(ref: str) -> Optional[tuple]:
    match = _REF.match((ref or "").strip().lower())
    return (_PLATFORMS[match.group(1)], match.group(2)) if match else None


class HandoffService:
    def __init__(
        self,
        conv_store,
        get_settings: Callable[[], object],
        send_owner: Callable[[str], Awaitable[list]],
        send_customer: Callable[[str, str, str], Awaitable[bool]],
        clock: Callable[[], float] = time.time,
        on_no_owner: Optional[Callable[[str, str], None]] = None,
    ):
        self._on_no_owner = on_no_owner  # صندوقِ «نیاز به توجه»
        self._conv = conv_store
        self._get_settings = get_settings
        self._send_owner = send_owner  # async (text) -> [(platform, chat_id, message_id)]
        self._send_customer = send_customer  # async (platform, chat_id, text) -> bool
        self._clock = clock

    def _conn(self):
        return self._conv.connection()

    def _t(self, key: str, **params) -> str:
        settings = self._get_settings()
        return shop_texts.render(settings, key, shop_texts.resolve_lang(settings), **params)

    # ---------------------------------------------------------------- وضعیت ----

    def get(self, platform: str, chat_id: str) -> Optional[HandoffSession]:
        row = self._conn().execute("SELECT * FROM handoff_sessions WHERE platform=? AND chat_id=?", (platform, str(chat_id))).fetchone()
        return self._row(row) if row else None

    @staticmethod
    def _row(r) -> HandoffSession:
        return HandoffSession(r["platform"], r["chat_id"], r["status"], r["customer_label"], r["started_ts"], r["last_activity_ts"], r["closed_reason"])

    def is_open(self, platform: str, chat_id: str) -> bool:
        session = self.get(platform, chat_id)
        return session is not None and session.status == "open"

    def open(self, platform: str, chat_id: str, label: str) -> bool:
        """``True`` اگه همین الان باز شد (نه از قبل باز بود)."""
        already = self.is_open(platform, chat_id)
        now = int(self._clock())
        conn = self._conn()
        conn.execute(
            "INSERT INTO handoff_sessions (platform, chat_id, status, customer_label, started_ts, last_activity_ts, closed_reason) "
            "VALUES (?, ?, 'open', ?, ?, ?, '') ON CONFLICT(platform, chat_id) DO UPDATE SET status='open', customer_label=excluded.customer_label, "
            "started_ts=CASE WHEN handoff_sessions.status='open' THEN handoff_sessions.started_ts ELSE excluded.started_ts END, "
            "last_activity_ts=excluded.last_activity_ts, closed_reason=''",
            (platform, str(chat_id), label, now, now),
        )
        conn.commit()
        return not already

    def touch(self, platform: str, chat_id: str) -> None:
        conn = self._conn()
        conn.execute("UPDATE handoff_sessions SET last_activity_ts=? WHERE platform=? AND chat_id=? AND status='open'", (int(self._clock()), platform, str(chat_id)))
        conn.commit()

    def close(self, platform: str, chat_id: str, reason: str = "closed") -> bool:
        conn = self._conn()
        cur = conn.execute(
            "UPDATE handoff_sessions SET status='closed', closed_reason=?, last_activity_ts=? WHERE platform=? AND chat_id=? AND status='open'",
            (reason, int(self._clock()), platform, str(chat_id)),
        )
        conn.commit()
        return cur.rowcount == 1

    def list_open(self) -> list:
        rows = self._conn().execute("SELECT * FROM handoff_sessions WHERE status='open' ORDER BY last_activity_ts DESC").fetchall()
        return [self._row(r) for r in rows]

    def expire_stale(self, max_age_seconds: int) -> list:
        cutoff = int(self._clock()) - int(max_age_seconds)
        stale = [s for s in self.list_open() if s.last_activity_ts <= cutoff]
        for session in stale:
            self.close(session.platform, session.chat_id, "timeout")
        return stale

    # ------------------------------------------------- نگاشتِ Reply (relay_map) ----

    def remember(self, owner_platform: str, owner_chat_id: str, owner_message_id: str, platform: str, chat_id: str) -> None:
        if not owner_message_id:
            return
        conn = self._conn()
        now = int(self._clock())
        conn.execute("DELETE FROM relay_map WHERE created_ts < ?", (now - RELAY_TTL_SECONDS,))
        conn.execute(
            "INSERT OR REPLACE INTO relay_map (owner_platform, owner_chat_id, owner_message_id, customer_platform, customer_chat_id, created_ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (owner_platform, str(owner_chat_id), str(owner_message_id), platform, str(chat_id), now),
        )
        conn.commit()

    def lookup(self, owner_platform: str, owner_chat_id: str, owner_message_id: str) -> Optional[tuple]:
        row = self._conn().execute(
            "SELECT customer_platform, customer_chat_id FROM relay_map WHERE owner_platform=? AND owner_chat_id=? AND owner_message_id=?",
            (owner_platform, str(owner_chat_id), str(owner_message_id)),
        ).fetchone()
        return (row["customer_platform"], row["customer_chat_id"]) if row else None

    # ----------------------------------------------------------- سمتِ مشتری ----

    async def flow_handler(self, ev) -> FlowResult:
        """دکمه‌ی «پشتیبانی» (ShopFlow.support_handler)."""
        settings = self._get_settings()
        if not (getattr(settings, "owner_chats", None) or {}):
            if self._on_no_owner is not None:
                self._on_no_owner(ev.platform, str(ev.chat_id))
            return FlowResult([UiMessage(self._t("ui.no_support"))])
        label = sanitize_display_name(ev.display_name) or str(ev.chat_id)
        newly = self.open(ev.platform, str(ev.chat_id), label)
        ref = make_ref(ev.platform, str(ev.chat_id))
        if newly:
            await self._notify_owner(
                f"🙋 درخواستِ پشتیبانی از «{label}» [{ref}] ({ev.platform}).\n"
                f"از الان پیام‌هاش همین‌جا می‌رسه؛ روی پیام‌ها Reply کن یا بنویس: /reply {ref} متنِ جواب\nبستن: /close {ref}",
                ev.platform, str(ev.chat_id),
            )
        text = self._t("handoff.started")
        if not working_hours.is_open(getattr(settings, "working_hours", None)):
            custom = str((getattr(settings, "working_hours", None) or {}).get("message", "")).strip()
            text += "\n\n" + (custom or self._t("handoff.offhours"))
        return FlowResult([UiMessage(text, [[Btn(self._t("handoff.end"), "c:hx")]], log=True)])

    async def end_handler(self, ev) -> FlowResult:
        """دکمه‌ی «پایان گفتگو» از سمتِ مشتری."""
        if self.close(ev.platform, str(ev.chat_id), "customer"):
            await self._notify_owner(f"✖️ مشتری گفتگوی پشتیبانی [{make_ref(ev.platform, str(ev.chat_id))}] رو بست.")
        return FlowResult([UiMessage(self._t("handoff.ended"), edit=True)], answer=self._t("handoff.ended"))

    async def relay_customer(self, message) -> None:
        session = self.get(message.platform, message.chat_id)
        label = session.customer_label if session else (sanitize_display_name(message.display_name) or message.chat_id)
        self.touch(message.platform, message.chat_id)
        text = f"💬 {label} [{make_ref(message.platform, message.chat_id)}]:\n{message.text[:MAX_RELAY_CHARS]}"
        await self._notify_owner(text, message.platform, message.chat_id)

    async def _notify_owner(self, text: str, platform: str = "", chat_id: str = "") -> None:
        try:
            sent = await self._send_owner(text)
        except Exception:  # noqa: BLE001
            logger.exception("ارسال به مالک ناموفق بود")
            return
        if platform:
            for owner_platform, owner_chat, message_id in sent:
                self.remember(owner_platform, owner_chat, message_id, platform, chat_id)

    # ------------------------------------------------------------ سمتِ مالک ----

    async def owner_reply(self, platform: str, chat_id: str, text: str) -> str:
        """جوابِ مالک رو به مشتری می‌رسونه؛ پیامِ فارسیِ نتیجه برای مالک."""
        session = self.get(platform, chat_id)
        if session is None or session.status != "open":
            return "❌ این گفتگوی پشتیبانی بسته شده یا وجود نداره."
        ok = await self._send_customer(platform, chat_id, self._t("handoff.owner_reply", text=text.strip()[:MAX_RELAY_CHARS]))
        self.touch(platform, chat_id)
        return f"✅ برای «{session.customer_label}» فرستاده شد." if ok else "⚠️ پیام به مشتری نرسید (ربات آن پلتفرم وصل نیست؟)."

    async def owner_close(self, platform: str, chat_id: str) -> str:
        session = self.get(platform, chat_id)
        if not self.close(platform, chat_id, "owner"):
            return "این گفتگو از قبل بسته بوده."
        await self._send_customer(platform, chat_id, self._t("handoff.ended"))
        return f"✅ گفتگوی «{session.customer_label if session else chat_id}» بسته شد."

    def owner_list(self) -> str:
        sessions = self.list_open()
        if not sessions:
            return "گفتگوی پشتیبانیِ بازی نداری. ✅"
        return "🙋 گفتگوهای پشتیبانیِ باز:\n" + "\n".join(f"• {s.customer_label} — /reply {s.ref} متن — /close {s.ref}" for s in sessions[:20])
