"""قلم ۳ مستر‌پرامپت: پیش‌نمایش باید پاسخِ هوش مصنوعی و دکمه‌هایش را نشان بدهد — همان
پایپ‌لاینِ واقعیِ ربات، نه یک شبیه‌سازیِ نصفه‌نیمه.
"""

import flet as ft
from fake_page import FakePage, collect_text, find, fire

from app.core import ai_engine
from app.core.orders import OrderStore
from app.core.products import ProductStore
from app.core.settings import AppSettings
from fakes import ScriptedToolEngine, say, tool
from app.screens import customer_preview


def build_preview(tmp_path, monkeypatch, engine=None):
    """پیش‌نمایشِ ساخته‌شده با مدلِ «آماده» (یا بی‌مدل) و موتورِ ساختگی."""
    monkeypatch.setattr(
        ai_engine, "engine_readiness",
        lambda s: (True, "ai.ready.ok") if engine is not None else (False, "ai.ready.no_model_selected"),
    )
    if engine is not None:
        monkeypatch.setattr(ai_engine, "build_engine_from_settings", lambda s: engine)
    settings = AppSettings(business_mode="store", card_to_card_number="6037991234567890", card_to_card_holder_name="علی رضایی")
    products = ProductStore(tmp_path / "p.db")
    orders = OrderStore(tmp_path / "o.db", product_store=products)
    control = customer_preview.build(FakePage(), "fa", settings, products, orders)
    return control, products, orders


def say_something(control, text) -> str:
    find(control, "preview_input").value = text
    fire(find(control, "preview_send"), "on_click")
    return collect_text(find(control, "preview_chat"))


def test_ai_answer_and_its_product_buttons_appear_in_the_preview(tmp_path, monkeypatch):
    engine = ScriptedToolEngine({"کتاب چنده؟": [tool("suggest_products", product_ids=[1]), say("کتاب ۵۰۰۰ ریال است، موجوده.")]})
    control, products, _orders = build_preview(tmp_path, monkeypatch, engine)
    products.add("کتاب", 5000, 3)

    bubbles = say_something(control, "کتاب چنده؟")
    assert "کتاب ۵۰۰۰ ریال است" in bubbles  # پاسخِ مدل در پیش‌نمایش
    assert "کتاب" in bubbles and "جزئیات" in bubbles  # کارتِ محصول با دکمه‌ی «جزئیات» هم فرستاده شد

    card = find(control, "cb:c:p:1:-:1")
    assert isinstance(card, ft.OutlinedButton), "دکمه‌ی «جزئیات» روی کارتِ AI باید زده بشه"
    fire(card, "on_click")
    after = collect_text(find(control, "preview_chat"))
    assert "افزودن" in after or "سبد" in after  # همان صفحه‌ی محصولِ واقعی


def test_preview_answers_menu_buttons_without_a_model(tmp_path, monkeypatch):
    """بی‌مدل: دکمه‌ها و منو کار می‌کنن و متنِ آزاد صادق است (نه پاسخِ ساختگی)."""
    control, products, _orders = build_preview(tmp_path, monkeypatch, None)
    products.add("کتاب", 5000, 3)

    say_something(control, "/start")
    assert "محصولات" in collect_text(find(control, "preview_menu"))

    text = say_something(control, "سؤالِ آزاد")
    assert "AI" in text and "دانلود نشده" in text


def test_preview_reset_clears_the_conversation_and_rebuilds_the_brain(tmp_path, monkeypatch):
    engine = ScriptedToolEngine({"قیمت؟": [say("۵۰۰۰ ریال")]}, default=say("…"))
    control, products, _orders = build_preview(tmp_path, monkeypatch, engine)
    products.add("کتاب", 5000, 3)
    assert "۵۰۰۰ ریال" in say_something(control, "قیمت؟")

    fire(find(control, "preview_reset"), "on_click")
    assert find(control, "preview_chat").controls == []
    assert find(control, "preview_menu").controls == []

    assert "۵۰۰۰ ریال" in say_something(control, "قیمت؟")  # مغزِ پیش‌نمایش از نو ساخته می‌شه
