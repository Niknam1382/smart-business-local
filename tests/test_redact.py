from app.core.redact import redact

TOKEN = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"


def test_redacts_explicit_secret():
    assert redact("خطا برای abcd1234secret رخ داد", "abcd1234secret") == "خطا برای *** رخ داد"


def test_redacts_token_inside_url_even_without_being_told():
    text = f"404, url='https://tapi.bale.ai/bot{TOKEN}/getMe'"
    out = redact(text)
    assert TOKEN not in out and "***" in out


def test_redacts_proxy_credentials():
    out = redact("proxy socks5://user:pa55word@127.0.0.1:1080 failed")
    assert "pa55word" not in out and "user" not in out
    assert "socks5://***@127.0.0.1:1080" in out


def test_short_or_empty_secrets_are_ignored():
    assert redact("abc", "", "a") == "abc"
    assert redact("") == ""
