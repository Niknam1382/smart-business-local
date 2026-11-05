"""نمونه‌پرامپت‌ها فقط «شخصیت و اطلاعات کسب‌وکار» رو می‌گن؛ قوانین سفارش‌گیری رو
خودِ برنامه (store_agent) پایین هر پرامپتِ فروشگاهی اضافه می‌کنه. پس نمونه‌ها نباید
مشتری رو به دستور/کلمه‌ی خاصی ارجاع بدن و نباید خودشون مراحل پرداخت بسازن."""

from app.data.prompt_templates import TEMPLATES, default_prompt, templates_for_category


def test_no_template_sends_customers_to_commands_or_invents_payment_steps():
    for tpl in TEMPLATES:
        for lang, body in tpl["body"].items():
            assert "«فروشگاه»" not in body and "/shop" not in body, (tpl["id"], lang)
            assert "مراحل پرداخت رو قدم‌به‌قدم" not in body, (tpl["id"], lang)
            assert "walk them through payment" not in body, (tpl["id"], lang)


def test_store_and_consultant_templates_still_exist():
    assert [t["id"] for t in templates_for_category("store")] == [
        "store_general", "store_clothing", "store_electronics", "store_cafe", "store_digital", "store_rules",
    ]
    assert [t["id"] for t in templates_for_category("consultant")] == [
        "consultant_general", "consultant_real_estate", "consultant_education",
        "consultant_appointments", "consultant_beauty", "consultant_tax",
    ]


def test_rules_template_keeps_the_blanks_and_forbids_making_up_exceptions():
    """قالبِ قوانین بدونِ جای‌خالی بی‌فایده است؛ و باید همان خطِ قرصِ «استثنا نساز» را داشته باشد."""
    rules = next(t for t in TEMPLATES if t["id"] == "store_rules")
    for lang in ("fa", "en"):
        body = rules["body"][lang]
        assert body.count("[") >= 8, (lang, body.count("["))
        assert "ریال" in body if lang == "fa" else "currency" in body
    fa = rules["body"]["fa"]
    assert "قانون جدید یا استثنا نساز" in fa and "وعده نده" in fa
    en = rules["body"]["en"]
    assert "never invent a new rule or exception" in en and "only discount codes the shop owner created" in en


def test_default_prompts_exist_for_both_modes_and_languages():
    for mode in ("store", "consultant"):
        for lang in ("fa", "en"):
            assert default_prompt(mode, lang).strip()
