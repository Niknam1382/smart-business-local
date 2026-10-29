import asyncio
import json

import aiohttp
import pytest
from fake_servers import FakeBotApiServer

from app.core.bale_client import BaleApiError, BaleClient, BaleUpdateBatch, _split_text

TOKEN = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"


def run(coro):
    return asyncio.run(coro)


def patched(client, fake):
    client._post_json = fake
    return client


# ---------------------------------------------------------------- واحد ----


def test_get_me_ok_and_bad_token():
    async def go():
        async def ok(url, payload, timeout):
            assert url == f"https://tapi.bale.ai/bot{TOKEN}/getMe"
            return {"ok": True, "result": {"id": 1, "username": "shop_bot"}}

        assert (await patched(BaleClient(TOKEN), ok).get_me())["username"] == "shop_bot"

        async def unauthorized(url, payload, timeout):
            return {"ok": False, "error_code": 401, "description": "Unauthorized"}

        with pytest.raises(BaleApiError) as exc:
            await patched(BaleClient(TOKEN), unauthorized).get_me()
        assert exc.value.is_auth_error and exc.value.error_code == 401

    run(go())


def test_error_codes_classification():
    assert BaleApiError("x", 403).is_auth_error
    assert BaleApiError("x", 404).is_auth_error
    assert not BaleApiError("x", 500).is_auth_error
    assert not BaleApiError("x").is_auth_error  # خطای شبکه: کد ندارد


def test_send_message_chunks_long_text():
    async def go():
        calls = []

        async def fake(url, payload, timeout):
            calls.append(payload)
            return {"ok": True, "result": {}}

        client = patched(BaleClient(TOKEN), fake)
        await client.send_message("5", "سلام")
        assert calls == [{"chat_id": "5", "text": "سلام"}]
        calls.clear()
        long_text = "الف" * 5000  # ۱۵۰۰۰ کاراکتر → ۵ تکه‌ی حداکثر ۳۵۰۰ تایی
        await client.send_message("5", long_text)
        assert len(calls) == 5 and all(len(c["text"]) <= 3500 for c in calls)
        assert "".join(c["text"] for c in calls) == long_text

    run(go())


def test_get_updates_parsing_and_offset_advance():
    async def go():
        seen = []
        batch = {
            "ok": True,
            "result": [
                {"update_id": 100, "message": {"from": {"id": 9, "first_name": "علی", "last_name": "رضایی"}, "chat": {"id": 9}, "text": "سلام"}},
                {"update_id": 101, "message": {"chat": {"id": 9}, "text": ""}},  # متن خالی
                {"update_id": 102, "edited_message": {"chat": {"id": 9}, "text": "x"}},  # نوع دیگه
            ],
        }

        async def fake(url, payload, timeout):
            seen.append((dict(payload), timeout))
            return batch if len(seen) == 1 else {"ok": True, "result": []}

        client = patched(BaleClient(TOKEN), fake)
        batch = await client.get_updates(timeout=15)
        assert "offset" not in seen[0][0] and seen[0][0]["timeout"] == 15
        assert seen[0][1] > 15  # مهلت HTTP از long-poll بلندتره
        assert [(m.chat_id, m.text, m.from_display_name) for m in batch.messages] == [("9", "سلام", "علی رضایی")]
        await client.get_updates()
        assert seen[1][0]["offset"] == 103  # حتی برای آپدیت‌های بی‌ربط جلو رفت

    run(go())


def test_network_and_format_errors_become_persian_errors():
    async def go():
        async def timeout_(url, payload, t):
            raise asyncio.TimeoutError()

        with pytest.raises(BaleApiError, match="تایم‌اوت"):
            await patched(BaleClient(TOKEN), timeout_).get_me()

        async def non_json(url, payload, t):
            raise json.JSONDecodeError("Expecting value", "<html>", 0)

        with pytest.raises(BaleApiError, match="غیر JSON"):
            await patched(BaleClient(TOKEN), non_json).get_me()

        async def not_dict(url, payload, t):
            return ["x"]

        with pytest.raises(BaleApiError, match="غیرمنتظره"):
            await patched(BaleClient(TOKEN), not_dict).get_me()

    run(go())


def test_token_never_leaks_in_error_message():
    async def go():
        async def leaky(url, payload, t):
            raise aiohttp.ClientConnectionError(f"Cannot connect to https://tapi.bale.ai/bot{TOKEN}/getMe")

        with pytest.raises(BaleApiError) as exc:
            await patched(BaleClient(TOKEN), leaky).get_me()
        assert TOKEN not in str(exc.value) and "***" in str(exc.value)

        async def leaky_api(url, payload, t):
            return {"ok": False, "error_code": 500, "description": f"oops {TOKEN}"}

        with pytest.raises(BaleApiError) as exc2:
            await patched(BaleClient(TOKEN), leaky_api).get_me()
        assert TOKEN not in str(exc2.value)

    run(go())


def test_split_text_edges():
    assert _split_text("", 10) == [""]
    assert _split_text("abc", 10) == ["abc"]
    assert _split_text("abcdefghij", 3) == ["abc", "def", "ghi", "j"]


# -------------------------------------------- HTTP واقعی روی loopback ----


@pytest.fixture
def server():
    srv = FakeBotApiServer(username="bale_shop_bot").start()
    yield srv
    srv.stop()


def test_real_http_roundtrip(server):
    async def go():
        client = BaleClient(TOKEN, base_url_template=server.url_template)
        try:
            assert (await client.get_me())["username"] == "bale_shop_bot"
            server.push_message(42, "سلام از مشتری", first_name="سارا")
            batch = await client.get_updates(timeout=1)
            assert [(m.chat_id, m.text, m.from_display_name) for m in batch.messages] == [("42", "سلام از مشتری", "سارا")]
            assert not await client.get_updates(timeout=1)  # offset تأیید شد؛ تکراری نمی‌آد
            await client.send_message("42", "پاسخ فروشگاه")
            assert server.sent_to(42) == ["پاسخ فروشگاه"]
        finally:
            await client.close()

    run(go())


def test_real_http_error_modes(server):
    async def go():
        client = BaleClient(TOKEN, base_url_template=server.url_template)
        try:
            server.mode = "unauthorized"
            with pytest.raises(BaleApiError) as exc:
                await client.get_me()
            assert exc.value.is_auth_error

            server.mode = "html_502"  # صفحه‌ی HTML به‌جای JSON، مثل یه پروکسی خراب
            with pytest.raises(BaleApiError, match="غیر JSON") as exc2:
                await client.get_me()
            assert not exc2.value.is_auth_error
        finally:
            await client.close()

    run(go())


def test_real_http_connection_refused_is_persian_error():
    async def go():
        dead = FakeBotApiServer()  # هیچ‌وقت start نمی‌شه → پورت بسته
        client = BaleClient(TOKEN, base_url_template=dead.url_template)
        try:
            with pytest.raises(BaleApiError, match="ناموفق") as exc:
                await client.get_me()
            assert TOKEN not in str(exc.value)
        finally:
            await client.close()

    run(go())


# -------------------------------------------------- رویدادهای پرداخت ----


def test_get_updates_parses_pre_checkout_query():
    async def go():
        batch = {
            "ok": True,
            "result": [
                {
                    "update_id": 200,
                    "pre_checkout_query": {
                        "id": "pcq_1",
                        "from": {"id": 55},
                        "invoice_payload": "order:42",
                        "total_amount": 150000,
                        "currency": "IRR",
                    },
                }
            ],
        }

        async def fake(url, payload, timeout):
            return batch

        client = patched(BaleClient(TOKEN), fake)
        result = await client.get_updates()
        assert result.messages == [] and result.successful_payments == []
        assert len(result.pre_checkout_queries) == 1
        q = result.pre_checkout_queries[0]
        assert q.query_id == "pcq_1" and q.from_user_id == "55" and q.invoice_payload == "order:42"
        assert q.total_amount == 150000

    run(go())


def test_get_updates_parses_successful_payment():
    async def go():
        batch = {
            "ok": True,
            "result": [
                {
                    "update_id": 201,
                    "message": {
                        "chat": {"id": 9},
                        "successful_payment": {
                            "currency": "IRR",
                            "total_amount": 150000,
                            "invoice_payload": "order:42",
                            "telegram_payment_charge_id": "tg_charge_1",
                            "provider_payment_charge_id": "prov_charge_1",
                        },
                    },
                }
            ],
        }

        async def fake(url, payload, timeout):
            return batch

        client = patched(BaleClient(TOKEN), fake)
        result = await client.get_updates()
        assert result.messages == [] and result.pre_checkout_queries == []
        assert len(result.successful_payments) == 1
        p = result.successful_payments[0]
        assert p.chat_id == "9" and p.invoice_payload == "order:42" and p.total_amount == 150000
        assert p.provider_payment_charge_id == "prov_charge_1"

    run(go())


def test_bale_update_batch_is_falsy_when_empty_and_truthy_otherwise():
    empty = BaleUpdateBatch()
    assert not empty
    empty.messages.append(object())
    assert empty


def test_answer_pre_checkout_query_payload_shapes():
    async def go():
        seen = []

        async def fake(url, payload, timeout):
            seen.append((dict(payload), timeout))
            return {"ok": True, "result": True}

        client = patched(BaleClient(TOKEN), fake)
        await client.answer_pre_checkout_query("q1", True)
        assert seen[0][0] == {"pre_checkout_query_id": "q1", "ok": True}
        assert seen[0][1] <= 10.0, "باید به‌خوبی زیر مهلت ۱۰ ثانیه‌ی بله بمونه"

        await client.answer_pre_checkout_query("q2", False, "موجود نیست")
        assert seen[1][0] == {"pre_checkout_query_id": "q2", "ok": False, "error_message": "موجود نیست"}

    run(go())


def test_inquire_transaction():
    async def go():
        async def fake(url, payload, timeout):
            assert payload == {"transaction_id": "tx1"}
            return {"ok": True, "result": {"status": "Successful", "amount": 150000}}

        client = patched(BaleClient(TOKEN), fake)
        tx = await client.inquire_transaction("tx1")
        assert tx["status"] == "Successful"

    run(go())


def test_real_http_payment_roundtrip(server):
    async def go():
        client = BaleClient(TOKEN, base_url_template=server.url_template)
        try:
            server.push_pre_checkout_query("pcq1", 55, "order:7", 10000)
            batch = await client.get_updates(timeout=1)
            assert len(batch.pre_checkout_queries) == 1
            await client.answer_pre_checkout_query(batch.pre_checkout_queries[0].query_id, True)
            assert server.pre_checkout_answers[-1] == {"pre_checkout_query_id": "pcq1", "ok": True}

            server.push_successful_payment(55, "order:7", 10000, "prov_1")
            batch2 = await client.get_updates(timeout=1)
            assert len(batch2.successful_payments) == 1
            payment = batch2.successful_payments[0]

            tx = await client.inquire_transaction(payment.provider_payment_charge_id)
            assert tx["status"] == "Successful"
            assert server.inquired_transactions == ["prov_1"]
        finally:
            await client.close()

    run(go())
