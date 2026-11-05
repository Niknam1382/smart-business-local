"""تستِ صفحه‌ی «خانه»: چه چیزی باید روی صفحه باشد و هر کارت به کجا می‌برد.

قانونِ صفحه: خانه فقط می‌خواند و می‌بَرَد؛ هیچ تصمیمی (تأییدِ سفارش، ذخیره‌ی تنظیمات) اینجا
گرفته نمی‌شه. پس این تست دقیقاً همان «دیدنِ درست» را می‌سنجد: آلارمِ رسید، وضعیتِ ربات و مدل،
و پرش‌ها.
"""

from fake_page import FakePage, collect_text, find, fire

from app.core import bot_manager, settings as settings_module
from app.core.orders import METHOD_CARD_TO_CARD, OrderStore
from app.core.products import ProductStore
from app.main import main


def _state(**kw):
    state = settings_module.load_settings()
    state.user_name = "سارا"
    state.business_mode = kw.pop("business_mode", "store")
    state.model_id = kw.pop("model_id", "qwen35-4b")  # آنبوردینگ با انتخابِ مدل تمام می‌شه (دانلودش در تست لازم نیست)
    state.onboarding_complete = True
    state.data_acknowledged = True
    for key, value in kw.items():
        setattr(state, key, value)
    state.ensure_default_prompt()
    settings_module.save_settings(state)
    return state


def _boot(state):
    bot_manager._manager = None  # noqa: SLF001 — تک‌نمونه‌ی سراسری بین تست‌ها نشت نکنه
    page = FakePage()
    main(page)
    return page, page.controls[0].content


def _add_paid_order_with_receipt(tmp_path, amount=500_000, receipt_amount=500_000, kind="text", state=None):
    products = ProductStore()
    orders = OrderStore(product_store=products)
    pid = products.add("هدفون", amount, 5)
    oid = orders.create("telegram", "55", [(pid, 1)])
    orders.mark_paid(oid, METHOD_CARD_TO_CARD)
    body = f"مبلغ {receipt_amount:,} ریال کد پیگیری ۱۲۳۴۵۶۷۸۹۰" if kind == "text" else ""
    orders.add_receipt(oid, kind=kind, body=body, file_path="C:/data/receipts/x.jpg" if kind == "image" else "",
                       amount_irr=receipt_amount, trace_code="1234567890" if kind == "text" else "",
                       match_state="amount_ok" if receipt_amount == amount else "amount_mismatch")
    return orders, oid


def test_home_replaces_the_ai_page_as_the_landing_screen():
    page, root = _boot(_state())
    assert find(root, "nav_home") is not None, "خانه باید در نوار کناری باشد"
    assert find(root, "home_frame") is not None
    text = collect_text(root)
    assert "ربات" in text and "مدل" in text  # دونامِ وضعیتِ ربات و مدل، بی‌آنکه کاربر جایی برود


def test_support_nav_item_is_in_the_sidebar():
    """«حمایت از سازنده» باید از منو پیدا بشه، نه فقط پایینِ صفحه‌ی «درباره»."""
    page, root = _boot(_state())
    assert find(root, "nav_support") is not None
    assert "حمایت از سازنده" in collect_text(find(root, "sidebar"))
    fire(find(root, "nav_support"), "on_click")
    # set_content پوسته‌ی تازه‌ای داخلِ همان body می‌گذارد؛ باید از ظرفِ اصلی بخوانیم نه از rootِ کهنه
    screen = find(page.controls[0].content, "support_tile")
    assert screen is not None and screen.expanded is True


def test_home_warns_when_the_bot_and_the_model_are_not_ready(tmp_path):
    page, root = _boot(_state())
    bot_pill = find(root, "home_pill_bot")
    ai_pill = find(root, "home_pill_ai")
    assert bot_pill is not None and ai_pill is not None
    assert "خاموش" in collect_text(bot_pill)
    assert "آماده نیست" in collect_text(ai_pill)


def test_home_shows_the_card_to_card_claim_that_needs_checking(tmp_path):
    state = _state(card_to_card_number="6037-9911-2233-4455")
    _add_paid_order_with_receipt(tmp_path, amount=500_000, receipt_amount=400_000)
    page, root = _boot(state)
    rows = [k for k in ("home_wait_1",) if find(root, k) is not None]
    assert rows, "سفارشِ پرداخت‌شده‌ی کارت‌به‌کارت باید در خانه دیده بشه"
    body = collect_text(find(root, "home_wait_1"))
    assert "نمی‌خونه" in body, "اختلافِ مبلغ باید همان‌جا گفته بشه، نه فقط عددِ سفارش"
    fire(find(root, "home_wait_1").controls[-1], "on_click")
    assert find(page.controls[0].content, "status_filter") is not None, "دکمه‌ی بررسی باید به صفحه‌ی سفارش‌ها بره"


def test_home_photo_receipt_is_labelled_as_a_photo(tmp_path):
    state = _state(card_to_card_number="6037-9911-2233-4455")
    _add_paid_order_with_receipt(tmp_path, kind="image")
    page, root = _boot(state)
    assert "عکس" in collect_text(find(root, "home_wait_1"))


def test_consultant_home_has_no_shop_numbers(tmp_path):
    page, root = _boot(_state(business_mode="consultant"))
    for key in ("home_kpi_sales", "home_kpi_low", "home_kpi_waiting"):
        assert find(root, key) is None, f"{key} نباید برای مشاوره نمایش داده بشه"
    assert find(root, "home_kpi_chats") is not None
    assert find(root, "home_kpi_ai") is not None


def test_home_kpi_clicks_go_to_the_right_pages(tmp_path):
    state = _state(card_to_card_number="6037-9911-2233-4455")
    page, root = _boot(state)
    for key, marker in (("home_kpi_sales", "finance_page"), ("home_kpi_low", "product_name"),
                        ("home_kpi_customers", "customers_search")):
        card = find(root, key)
        assert card is not None, key
        fire(card, "on_click")
        area = page.controls[0].content
        assert find(area, marker) is not None, f"{key} باید به {marker} بره"
