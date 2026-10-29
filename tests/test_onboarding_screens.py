"""تست صفحه‌های آنبوردینگ بعد از بازطراحی بصری — با Page جعلی، بدون مرورگر واقعی."""

from fake_page import FakePage, find, fire

from app.screens import ai_select, mode_select, welcome


def test_welcome_build_and_submit_name(tmp_path):
    page = FakePage()
    captured = []
    control = welcome.build(page, "fa", "", lambda name: captured.append(name))
    field = find(control, "name_field")
    assert field is not None
    fire(field, "on_submit", value="  محمد مهدی  ")
    assert captured == ["محمد مهدی"]


def test_welcome_empty_name_shows_error_and_does_not_advance(tmp_path):
    page = FakePage()
    captured = []
    control = welcome.build(page, "fa", "", lambda name: captured.append(name))
    field = find(control, "name_field")
    fire(field, "on_submit", value="   ")
    assert captured == []
    assert page.update_count >= 1


def test_welcome_builds_in_english(tmp_path):
    page = FakePage()
    control = welcome.build(page, "en", "Sara", lambda name: None)
    field = find(control, "name_field")
    assert field.value == "Sara"


def test_mode_select_choose_enables_next_and_reports_choice(tmp_path):
    page = FakePage()
    chosen = []
    control = mode_select.build(page, "fa", None, lambda mode: chosen.append(mode), lambda: None)
    next_btn = find(control, "next_button")
    assert next_btn.disabled is True

    fire(find(control, "mode_card_store"), "on_click")
    assert find(control, "next_button").disabled is False
    fire(find(control, "next_button"), "on_click")
    assert chosen == ["store"]


def test_mode_select_back_button(tmp_path):
    page = FakePage()
    back_calls = []
    control = mode_select.build(page, "fa", "store", lambda mode: None, lambda: back_calls.append(1))
    fire(find(control, "back_button"), "on_click")
    assert back_calls == [1]


def test_mode_select_preselected_enables_next_immediately(tmp_path):
    page = FakePage()
    control = mode_select.build(page, "fa", "consultant", lambda mode: None, lambda: None)
    assert find(control, "next_button").disabled is False


def test_mode_select_switching_choice_updates_selection(tmp_path):
    page = FakePage()
    chosen = []
    control = mode_select.build(page, "fa", "store", lambda mode: chosen.append(mode), lambda: None)
    fire(find(control, "mode_card_consultant"), "on_click")
    fire(find(control, "next_button"), "on_click")
    assert chosen == ["consultant"]


def test_ai_select_switching_toggles_field_sections(tmp_path):
    page = FakePage()
    control = ai_select.build(page, "fa", None, "", "", "", lambda *a: None, lambda: None)
    assert find(control, "api_fields").visible is False
    assert find(control, "local_info").visible is False

    fire(find(control, "ai_card_api"), "on_click")
    assert find(control, "api_fields").visible is True
    assert find(control, "local_info").visible is False

    fire(find(control, "ai_card_local"), "on_click")
    assert find(control, "api_fields").visible is False
    assert find(control, "local_info").visible is True


def test_ai_select_next_reports_api_fields(tmp_path):
    page = FakePage()
    captured = []
    control = ai_select.build(
        page, "fa", "api", "https://old.example/v1", "sk-old", "gpt-old",
        lambda *a: captured.append(a), lambda: None,
    )
    find(control, "base_url_field").value = "https://api.example.com/v1"
    find(control, "api_key_field").value = "sk-test"
    find(control, "model_name_field").value = "gpt-4o-mini"
    fire(find(control, "next_button"), "on_click")
    assert captured == [("api", "https://api.example.com/v1", "sk-test", "gpt-4o-mini")]


def test_ai_select_builds_with_local_preselected(tmp_path):
    page = FakePage()
    control = ai_select.build(page, "fa", "local", "", "", "", lambda *a: None, lambda: None)
    assert find(control, "local_info").visible is True
    assert find(control, "api_fields").visible is False
    assert find(control, "next_button").disabled is False


def test_ai_select_back_button(tmp_path):
    page = FakePage()
    back_calls = []
    control = ai_select.build(page, "fa", "api", "", "", "", lambda *a: None, lambda: back_calls.append(1))
    fire(find(control, "back_button"), "on_click")
    assert back_calls == [1]
