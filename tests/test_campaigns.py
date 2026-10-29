"""N8 — کمپین: ساخت، زمان‌بندی، شروع روی موتورِ N7، تلاشِ دوباره، ناموفق‌شدن و آمار."""

import pytest

from app.core import broadcast as bc
from app.core.campaigns import CampaignError, CampaignService
from app.core.discounts import DiscountCode, DiscountStore
from tests.test_broadcast import NOW, Rig


@pytest.fixture
def rig(tmp_path):
    r = Rig(tmp_path)
    r.add("1"); r.add("2"); r.add("3", platform="bale")
    r.disc = DiscountStore(r.orders, clock=lambda: NOW)
    r.camps = CampaignService(r.orders, r.disc, r.service, lambda: r.settings, clock=lambda: NOW)
    return r


def new_code(rig, code="SPRING", **kw):
    return rig.disc.create(DiscountCode(0, code, "percent", 10, **kw))


def test_create_validates_name_text_and_code(rig):
    with pytest.raises(CampaignError):
        rig.camps.create("", "سلام", bc.Audience())
    with pytest.raises(CampaignError):
        rig.camps.create("x" * 61, "سلام", bc.Audience())
    with pytest.raises(CampaignError):
        rig.camps.create("خالی", "   ", bc.Audience())
    with pytest.raises(CampaignError):
        rig.camps.create("بی‌کد", "سلام", bc.Audience(), code_id=999)
    with pytest.raises(CampaignError):
        rig.camps.create("دور", "سلام", bc.Audience(), start_ts=NOW + 400 * 86400)
    cid = rig.camps.create("بهار", "تخفیفِ بهاری!", bc.Audience(), code_id=new_code(rig))
    c = rig.camps.get(cid)
    assert c.kind == "discount" and c.status == "scheduled" and c.start_ts == NOW


def test_due_campaign_launches_with_code_in_text_and_finishes(rig):
    cid = rig.camps.create("بهار", "تخفیفِ بهاری!", bc.Audience(), code_id=new_code(rig))
    assert rig.camps.tick(NOW) == [(cid, "running")]
    rig.drain()
    assert rig.delivered and all("🎟 SPRING" in d[2] and "تخفیفِ بهاری" in d[2] for d in rig.delivered)
    assert rig.camps.tick(NOW) == [(cid, "done")]
    st = rig.camps.stats(cid)
    assert st.sent == 3 and st.audience == 3 and st.code_uses == 0


def test_future_campaign_waits_and_can_be_cancelled(rig):
    cid = rig.camps.create("بعداً", "سلام", bc.Audience(), start_ts=NOW + 3600)
    assert rig.camps.tick(NOW) == []
    assert rig.camps.get(cid).status == "scheduled"
    assert rig.camps.cancel(cid) is True and rig.camps.cancel(cid) is False
    assert rig.camps.tick(NOW + 7200) == [] and not rig.attempts


def test_busy_engine_retries_then_fails_after_a_day(rig):
    rig.start(bc.Content("ارسالِ دیگه"))  # یه ارسالِ همگانیِ در جریان
    cid = rig.camps.create("منتظر", "سلام", bc.Audience())
    assert rig.camps.tick(NOW + 60) == []  # هنوز در صف
    assert rig.camps.get(cid).status == "scheduled"
    assert rig.camps.tick(NOW + 90_000) == [(cid, "failed")]
    assert "در جریانه" in rig.camps.get(cid).error


def test_code_deactivated_before_launch_fails_cleanly(rig):
    code_id = new_code(rig)
    cid = rig.camps.create("بهار", "سلام", bc.Audience(), code_id=code_id, start_ts=NOW + 10)
    rig.disc.set_active(code_id, False)
    assert rig.camps.tick(NOW + 20) == [(cid, "failed")]
    assert "غیرفعال" in rig.camps.get(cid).error and not rig.attempts


def test_code_uses_after_launch_are_counted_in_stats(rig):
    code_id = new_code(rig)
    cid = rig.camps.create("بهار", "سلام", bc.Audience(), code_id=code_id)
    rig.camps.tick(NOW)
    pid = rig.orders._products.add("کالا", 100_000, 5)
    oid = rig.orders.create("telegram", "1", [(pid, 1)], discount_code="SPRING")
    rig.orders.mark_paid(oid, "card_to_card")
    rig.orders._connection().execute("UPDATE discount_usage SET created_ts=?", (NOW + 5,))
    rig.orders._connection().commit()
    st = rig.camps.stats(cid)
    assert (st.code_uses, st.revenue_irr) == (1, 90_000)
