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
    assert len(templates_for_category("store")) == 4
    assert templates_for_category("consultant")


def test_default_prompts_exist_for_both_modes_and_languages():
    for mode in ("store", "consultant"):
        for lang in ("fa", "en"):
            assert default_prompt(mode, lang).strip()
