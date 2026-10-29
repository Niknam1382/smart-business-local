"""A7 — فیلدِ «هشدارِ موجودیِ کم» در صفحه‌ی محصولات."""

from fake_page import FakePage, find, fire

from app.core.products import ProductStore
from app.core.settings import AppSettings
from app.screens import products


def make(tmp_path, with_settings=True):
    s, saved = AppSettings(), []
    page = FakePage()
    root = products.build(page, "fa", ProductStore(tmp_path / "p.db"), s if with_settings else None, lambda: saved.append(s.low_stock_threshold))
    return s, saved, root


def test_field_saves_valid_values_and_rejects_bad_ones(tmp_path):
    s, saved, root = make(tmp_path)
    field = find(root, "low_stock_field")
    assert field.value == "3"
    for good, expect in (("۱۰", 10), ("0", 0), ("100000", 100000)):
        field.value = good
        fire(field, "on_submit")
        assert s.low_stock_threshold == expect
    assert saved == [10, 0, 100000]
    for bad in ("", "-1", "abc", "1.5", "100001"):
        field.value = bad
        fire(field, "on_blur")
        assert find(root, "low_stock_note").visible and "عددِ صحیح" in find(root, "low_stock_note").value
    assert s.low_stock_threshold == 100000 and saved == [10, 0, 100000]  # مقدارِ بد چیزی را ذخیره نکرد


def test_field_absent_without_settings(tmp_path):
    _s, _saved, root = make(tmp_path, with_settings=False)
    assert find(root, "low_stock_field") is None
