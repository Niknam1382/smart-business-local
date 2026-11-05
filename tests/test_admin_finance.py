"""N19: پنلِ دکمه‌ایِ مدیران — «خلاصه‌ی مالی» و «ارسالِ مجددِ فاکتور»: مجوزِ سمتِ سرور (نه فقط مخفی‌کردنِ دکمه)."""

import asyncio

import pytest
from test_admins import Rig as AdminRig

from app.core import admins as am
from app.core.finance import FinanceStore
from app.core.invoice_service import InvoiceService


class Rig(AdminRig):
    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self.settings.invoice_seller_name = "فروشگاه"
        self.fin = FinanceStore(self.orders, self.products)
        self.docs = []

        async def doc(platform, chat, path, caption):
            self.docs.append((platform, chat))

        self.svc = InvoiceService(self.orders, lambda: self.settings, doc_sender=doc, directory=lambda: tmp_path / "inv")
        self.panel.attach_finance(self.fin, self.svc)
        self.panel._get_settings = lambda: self.settings  # noqa: SLF001

    def confirmed(self, chat="10"):
        pid, oid = self.paid_order(chat)
        self.orders.confirm(oid)
        return oid


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def denied(rig):
    return any(alert and "⛔" in text for _id, text, alert in rig.t.answers)


@pytest.mark.parametrize("role", [am.ROLE_MANAGER, am.ROLE_SUPPORT, am.ROLE_VIEWER])
def test_finance_summary_denied_by_default_for_non_owner(rig, role):
    uid = rig.admin(role)
    rig.say(uid, "/admin")
    assert "💰 خلاصه‌ی مالی" not in rig.t.labels()
    rig.tap(uid, "adm:fin")
    assert denied(rig) and "فروشِ خالص" not in rig.t.texts()


def test_owner_sees_summary_and_manager_only_with_grant(rig):
    rig.fin.post_order(rig.orders.get(rig.confirmed()))
    rig.say("900", "/admin")
    assert "💰 خلاصه‌ی مالی" in rig.t.labels()
    rig.tap("900", "adm:fin")
    text = rig.t.texts()
    assert "فروشِ خالص: 2,000,000" in text.replace("٬", ",") and "جایگزینِ حسابدارِ رسمی" in text
    mgr = rig.admin(am.ROLE_MANAGER)
    rig.tap(mgr, "adm:fin")
    assert denied(rig)
    rig.settings.finance_manager_access = True
    rig.say(mgr, "/admin")
    assert "💰 خلاصه‌ی مالی" in rig.t.labels()
    rig.tap(mgr, "adm:fin")
    assert "فروشِ خالص" in rig.t.texts()
    for n, role in enumerate((am.ROLE_SUPPORT, am.ROLE_VIEWER)):  # اعطای مالک به نقشِ دیگری سرایت نمی‌کند
        other = rig.admin(role, uid=str(500 + n))
        rig.tap(other, "adm:fin")
        assert denied(rig)


def test_resend_invoice_permissions_and_guards(rig):
    oid = rig.confirmed()
    mgr, viewer, support = rig.admin(am.ROLE_MANAGER, "1"), rig.admin(am.ROLE_VIEWER, "2"), rig.admin(am.ROLE_SUPPORT, "3")
    for uid in (viewer, support):
        rig.tap(uid, f"adm:inv:{oid}")
        assert denied(rig) and rig.docs == []
    rig.tap(mgr, f"adm:od:{oid}")
    assert f"adm:inv:{oid}" in rig.t.buttons()
    rig.tap(mgr, f"adm:inv:{oid}")
    assert rig.docs == [("telegram", "10")] and any("فرستاده شد" in text for _id, text, _a in rig.t.answers)
    rig.tap("900", f"adm:inv:{oid}")  # مالک هم می‌تونه؛ «ارسالِ مجدد» = force
    assert len(rig.docs) == 2
    # آرگومانِ کم/زیاد و سفارشِ نامعتبر/تاییدنشده بی‌اثر
    for bad in ("adm:inv", f"adm:inv:{oid}:1", "adm:inv:999", "adm:inv:abc"):
        rig.tap("900", bad)
    assert len(rig.docs) == 2
    _pid, paid_only = rig.paid_order("11")
    rig.tap("900", f"adm:inv:{paid_only}")
    assert len(rig.docs) == 2 and any(alert for _i, _t, alert in rig.t.answers)
    rig.tap(viewer, f"adm:od:{oid}")
    assert f"adm:inv:{oid}" not in rig.t.buttons()


def test_resend_refused_for_blocked_customer_message(rig):
    oid = rig.confirmed("12")
    rig.svc._can = lambda platform, chat: "blocked"  # noqa: SLF001
    rig.tap("900", f"adm:inv:{oid}")
    assert rig.docs == [] and any("بلاک" in text for _i, text, _a in rig.t.answers)
    assert asyncio  # noqa: F401
