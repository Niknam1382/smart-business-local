import threading

import pytest

from app.core.products import ProductError, ProductStore


def make_store(tmp_path):
    return ProductStore(db_path=tmp_path / "products.db")


def test_add_and_get(tmp_path):
    store = make_store(tmp_path)
    pid = store.add("گوشی X", 15_000_000, stock_quantity=10, description="توضیح")
    product = store.get(pid)
    assert product.name == "گوشی X"
    assert product.price_irr == 15_000_000
    assert product.stock_quantity == 10
    assert product.active is True
    assert product.in_stock is True


def test_get_missing_returns_none(tmp_path):
    store = make_store(tmp_path)
    assert store.get(999) is None


def test_validation_errors(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(ProductError, match="اسم"):
        store.add("   ", 1000, 1)
    with pytest.raises(ProductError, match="قیمت"):
        store.add("محصول", -1, 1)
    with pytest.raises(ProductError, match="موجودی"):
        store.add("محصول", 1000, -1)
    # هیچ‌کدوم از خطاها نباید چیزی ذخیره کرده باشن
    assert store.list() == []


def test_update(tmp_path):
    store = make_store(tmp_path)
    pid = store.add("قدیمی", 1000, 5)
    store.update(pid, "جدید", 2000, 8, description="توضیح جدید")
    product = store.get(pid)
    assert product.name == "جدید" and product.price_irr == 2000 and product.stock_quantity == 8
    assert product.description == "توضیح جدید"
    assert product.photo_path == ""  # photo_path=None یعنی دست‌نخورده بمونه


def test_update_photo_path_only_when_given(tmp_path):
    store = make_store(tmp_path)
    pid = store.add("محصول", 1000, 5, photo_path="old.jpg")
    store.update(pid, "محصول", 1000, 5, photo_path="new.jpg")
    assert store.get(pid).photo_path == "new.jpg"
    store.update(pid, "محصول ویرایش‌شده", 1500, 5)  # photo_path نداده -> دست‌نخورده
    assert store.get(pid).photo_path == "new.jpg"


def test_set_active_hides_from_default_list_but_keeps_record(tmp_path):
    store = make_store(tmp_path)
    pid = store.add("محصول", 1000, 5)
    store.set_active(pid, False)
    assert store.list() == []
    assert [p.id for p in store.list(include_inactive=True)] == [pid]
    assert store.get(pid).active is False
    store.set_active(pid, True)
    assert [p.id for p in store.list()] == [pid]


def test_adjust_stock_up_and_down(tmp_path):
    store = make_store(tmp_path)
    pid = store.add("محصول", 1000, 10)
    store.adjust_stock(pid, -3)
    assert store.get(pid).stock_quantity == 7
    store.adjust_stock(pid, 5)
    assert store.get(pid).stock_quantity == 12


def test_adjust_stock_rejects_going_negative(tmp_path):
    store = make_store(tmp_path)
    pid = store.add("محصول", 1000, 2)
    with pytest.raises(ProductError, match="موجودی کافی نیست"):
        store.adjust_stock(pid, -5)
    assert store.get(pid).stock_quantity == 2  # دست‌نخورده موند


def test_adjust_stock_missing_product(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(ProductError):
        store.adjust_stock(999, -1)


def test_list_ordered_newest_first(tmp_path):
    store = make_store(tmp_path)
    first = store.add("اول", 1000, 1)
    second = store.add("دوم", 1000, 1)
    assert [p.id for p in store.list()] == [second, first]


def test_concurrent_stock_adjustments_never_go_negative(tmp_path):
    """شبیه‌سازی دو سفارش هم‌زمان برای آخرین واحد موجودی — فقط یکی باید موفق بشه."""
    store = make_store(tmp_path)
    pid = store.add("کالای کمیاب", 1000, 1)
    results = []
    lock = threading.Lock()

    def try_buy():
        try:
            store.adjust_stock(pid, -1)
            with lock:
                results.append("ok")
        except Exception as exc:  # noqa: BLE001
            with lock:
                results.append(("err", exc))

    threads = [threading.Thread(target=try_buy) for _ in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert results.count("ok") == 1, results
    assert store.get(pid).stock_quantity == 0


def test_copy_photo_into_store_and_delete(tmp_path, monkeypatch):
    from app.core import products as products_mod

    monkeypatch.setattr(products_mod, "get_app_data_dir", lambda: tmp_path)
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    src_file = src_dir / "photo.JPG"
    src_file.write_bytes(b"fake-bytes")

    dest = products_mod.copy_photo_into_store(str(src_file))
    assert dest != str(src_file)
    from pathlib import Path

    assert Path(dest).read_bytes() == b"fake-bytes"
    assert Path(dest).parent.name == "product_photos"

    src_file.unlink()
    assert Path(dest).exists(), "حذف فایل اصلی نباید نسخه‌ی داخلی رو خراب کنه"

    products_mod.delete_photo_file(dest)
    assert not Path(dest).exists()
    products_mod.delete_photo_file("")  # نباید خطا بده
    products_mod.delete_photo_file(str(tmp_path / "nope.jpg"))  # نباید خطا بده


def test_copy_photo_rejects_unsupported_extension(tmp_path, monkeypatch):
    from app.core import products as products_mod

    monkeypatch.setattr(products_mod, "get_app_data_dir", lambda: tmp_path)
    bad = tmp_path / "virus.exe"
    bad.write_bytes(b"x")
    with pytest.raises(ProductError, match="فرمت"):
        products_mod.copy_photo_into_store(str(bad))
