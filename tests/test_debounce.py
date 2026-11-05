import asyncio
import time

import pytest

from app.core.debounce import Debouncer


def run(coro):
    return asyncio.run(coro)


def test_invalid_config():
    async def noop(k, t):
        pass

    with pytest.raises(ValueError):
        Debouncer(noop, wait_seconds=0)
    with pytest.raises(ValueError):
        Debouncer(noop, wait_seconds=2, max_wait_seconds=1)


def test_merges_rapid_messages_after_quiet_period():
    async def go():
        results = []

        async def on_flush(key, text):
            results.append((key, text, time.monotonic()))

        d = Debouncer(on_flush, wait_seconds=0.2, max_wait_seconds=0.6)
        start = time.monotonic()
        d.feed("c", "سلام")
        await asyncio.sleep(0.05)
        d.feed("c", "قیمت؟")
        await asyncio.sleep(0.05)
        d.feed("c", "جواب بده")
        await asyncio.sleep(0.1)
        assert results == []  # هنوز سکوت کامل نشده
        await asyncio.sleep(0.25)
        assert len(results) == 1
        assert results[0][1] == "سلام\nقیمت؟\nجواب بده"
        assert 0.25 <= results[0][2] - start <= 0.45

    run(go())


def test_max_wait_cap_forces_flush_even_if_user_keeps_typing():
    async def go():
        results = []

        async def on_flush(key, text):
            results.append(time.monotonic())

        d = Debouncer(on_flush, wait_seconds=0.3, max_wait_seconds=0.6)
        start = time.monotonic()
        for i in range(20):
            d.feed("c", f"m{i}")
            await asyncio.sleep(0.08)  # کمتر از wait -> هیچ‌وقت طبیعی ساکت نمی‌شه
            if results:
                break
        assert len(results) == 1
        assert 0.55 <= results[0] - start <= 0.85

    run(go())


def test_independent_keys():
    async def go():
        got = {}

        async def on_flush(key, text):
            got[key] = text

        d = Debouncer(on_flush, wait_seconds=0.15, max_wait_seconds=1.0)
        d.feed("A", "A1")
        d.feed("B", "B1")
        await asyncio.sleep(0.05)
        d.feed("A", "A2")
        await asyncio.sleep(0.25)
        assert got == {"A": "A1\nA2", "B": "B1"}

    run(go())


def test_exception_in_flush_does_not_break_other_keys(capsys):
    async def go():
        calls = []

        async def on_flush(key, text):
            calls.append(key)
            if key == "bad":
                raise RuntimeError("boom")

        d = Debouncer(on_flush, wait_seconds=0.1, max_wait_seconds=0.5)
        d.feed("bad", "x")
        d.feed("good", "y")
        await asyncio.sleep(0.25)
        assert set(calls) == {"bad", "good"}
        assert d.pending_count() == 0

    run(go())


def test_cancel_all_prevents_flush():
    async def go():
        got = []

        async def on_flush(key, text):
            got.append(text)

        d = Debouncer(on_flush, wait_seconds=0.1, max_wait_seconds=1.0)
        d.feed("c", "x")
        assert d.pending_count() == 1 and d.is_pending("c")
        await d.cancel_all()
        await asyncio.sleep(0.2)
        assert got == [] and d.pending_count() == 0

    run(go())
