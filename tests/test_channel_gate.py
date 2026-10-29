"""N13 — منطقِ خالصِ دروازه‌ی عضویتِ کانال (بدونِ شبکه): تجزیه‌ی نام، اعتبارسنجی، کش، fail-open و هشدارِ یک‌باره."""

import asyncio
from types import SimpleNamespace

import pytest

from app.core import channel_gate as cg
from app.core.channel_gate import Channel, ChannelError, ChannelGate


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------- تجزیه‌ی نامِ کانال ----


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("@mychannel", "@mychannel"),
        ("mychannel", "@mychannel"),
        ("  @MyChannel_1  ", "@MyChannel_1"),
        ("https://t.me/mychannel", "@mychannel"),
        ("t.me/mychannel/", "@mychannel"),
        ("http://telegram.me/mychannel?start=1", "@mychannel"),
        ("https://ble.ir/mychannel", "@mychannel"),
        ("ble.ir/@mychannel", "@mychannel"),
        ("-1001234567890", "-1001234567890"),
        ("1234567", "1234567"),
    ],
)
def test_parse_channel_ref_accepts_public_forms(raw, expected):
    assert cg.parse_channel_ref(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "@abc", "@@mychannel", "hello world", "5abcde", "https://example.com/mychannel", "javascript:alert(1)", "-12", "@my-channel"],
)
def test_parse_channel_ref_rejects_garbage(raw):
    with pytest.raises(ChannelError):
        cg.parse_channel_ref(raw)


@pytest.mark.parametrize("raw", ["https://t.me/+AbCdEfGhIj", "t.me/joinchat/AAAAAEx", "https://t.me/joinchat/xyz"])
def test_private_invite_links_cannot_be_resolved_to_a_channel(raw):
    with pytest.raises(ChannelError, match="دعوتِ خصوصی"):
        cg.parse_channel_ref(raw)


# ----------------------------------------------------------------------- اعتبارسنجی ----


def test_normalize_builds_the_public_link_per_platform_and_cleans_the_title():
    tg = cg.normalize({"platform": "telegram", "channel": "mychannel", "title": "  کانال\n فروشگاه  "})
    assert tg == Channel("telegram", "@mychannel", "کانال فروشگاه", "https://t.me/mychannel")
    bale = cg.normalize({"platform": "BALE", "channel": "https://ble.ir/mychannel"})
    assert bale.link == "https://ble.ir/mychannel" and bale.platform == "bale" and bale.title == ""
    assert cg.normalize({"platform": "telegram", "channel": "@mychannel", "title": "x" * 200}).title == "x" * cg.MAX_TITLE


def test_numeric_channels_need_an_explicit_invite_link():
    with pytest.raises(ChannelError, match="لینکِ دعوت"):
        cg.normalize({"platform": "telegram", "channel": "-1001234567890"})
    ch = cg.normalize({"platform": "telegram", "channel": "-1001234567890", "link": "https://t.me/+AbCdEfGhIj", "title": "VIP"})
    assert ch.channel == "-1001234567890" and ch.link == "https://t.me/+AbCdEfGhIj" and ch.label == "VIP"


@pytest.mark.parametrize("link", ["javascript:alert(1)", "tel:+98912", "ftp://x.y/z", "t.me/mychannel", "https://", "data:text/html,hi"])
def test_only_http_links_are_accepted_for_the_button(link):
    with pytest.raises(ChannelError, match="http"):
        cg.normalize({"platform": "telegram", "channel": "@mychannel", "link": link})


@pytest.mark.parametrize("raw", [None, "x", 5, [], {"platform": "eitaa", "channel": "@mychannel"}, {"platform": "telegram"}])
def test_normalize_rejects_bad_shapes_and_platforms(raw):
    with pytest.raises(ChannelError):
        cg.normalize(raw)


def test_validate_list_dedupes_and_caps_and_returns_plain_dicts():
    rows = cg.validate_list([
        {"platform": "telegram", "channel": "@mychannel"},
        {"platform": "telegram", "channel": "https://t.me/mychannel", "title": "dup"},
        {"platform": "bale", "channel": "@mychannel"},
    ])
    assert [r["platform"] for r in rows] == ["telegram", "bale"] and all(isinstance(r, dict) for r in rows)
    too_many = [{"platform": "telegram", "channel": f"@channel{i:03d}"} for i in range(cg.MAX_CHANNELS + 1)]
    with pytest.raises(ChannelError, match="حداکثر"):
        cg.validate_list(too_many)
    with pytest.raises(ChannelError):
        cg.validate_list([{"platform": "telegram", "channel": "@ok_channel"}, {"platform": "telegram", "channel": "!!"}])


def test_load_skips_corrupt_rows_silently_and_never_raises():
    settings = SimpleNamespace(required_channels=[
        {"platform": "telegram", "channel": "@good_one"}, "garbage", None, {"platform": "x"}, {"platform": "bale", "channel": "@good_two"},
        {"platform": "telegram", "channel": "@good_one", "title": "dup"},
    ])
    assert [c.ref for c in cg.load(settings)] == ["telegram:@good_one", "bale:@good_two"]
    assert cg.load(SimpleNamespace()) == [] and cg.load(SimpleNamespace(required_channels="oops")) == []


def test_scope_covers_defaults_to_both_for_unknown_values():
    for scope, shop, ai in (("shop", True, False), ("ai", False, True), ("both", True, True), ("weird", True, True)):
        s = SimpleNamespace(required_channels_scope=scope)
        assert (cg.scope_covers(s, "shop"), cg.scope_covers(s, "ai")) == (shop, ai), scope
    assert cg.scope_covers(SimpleNamespace(), "ai") is True


# ------------------------------------------------------------------------- دروازه ----


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Env:
    """checker جعلی با وضعیتِ قابلِ‌تنظیم + شمارشِ تماس‌ها."""

    def __init__(self, channels=None, **settings):
        self.settings = SimpleNamespace(
            required_channels_enabled=True, required_channels_scope="both",
            required_channels=channels if channels is not None else [{"platform": "telegram", "channel": "@shop_channel", "title": "فروشگاه"}],
            **settings,
        )
        self.status = {}  # (channel, user_id) → وضعیت یا Exception
        self.default = "member"
        self.calls = []
        self.errors, self.recovered = [], []
        self.clock = Clock()

        async def checker(platform, channel, user_id):
            self.calls.append((platform, channel, user_id))
            value = self.status.get((channel, user_id), self.status.get(channel, self.default))
            if isinstance(value, BaseException):
                raise value
            return value

        self.gate = ChannelGate(
            lambda: self.settings, checker, clock=self.clock,
            on_error=lambda ch, exc: self.errors.append((ch.ref, str(exc))),
            on_recovered=lambda ch: self.recovered.append(ch.ref),
        )

    def check(self, user_id="1", platform="telegram", **kw):
        return run(self.gate.check(platform, user_id, **kw))


def test_members_pass_and_the_result_is_cached_until_the_ttl_expires():
    env = Env()
    assert env.check().allowed and env.check().allowed and len(env.calls) == 1
    env.clock.now += cg.CACHE_TTL_SECONDS - 1
    env.check()
    assert len(env.calls) == 1
    env.clock.now += 2
    env.check()
    assert len(env.calls) == 2


@pytest.mark.parametrize("status", ["creator", "administrator", "member", " Member "])
def test_all_member_like_statuses_pass(status):
    env = Env()
    env.default = status
    assert env.check().allowed


@pytest.mark.parametrize("status", ["left", "kicked"])
def test_non_members_are_blocked_with_the_missing_channels(status):
    env = Env()
    env.default = status
    verdict = env.check()
    assert verdict.blocked and not verdict.degraded
    assert [c.ref for c in verdict.missing] == ["telegram:@shop_channel"] and verdict.missing[0].label == "فروشگاه"


def test_force_bypasses_the_cache_and_a_user_who_joined_gets_in_immediately():
    env = Env()
    env.default = "left"
    assert env.check().blocked
    env.default = "member"
    assert env.check().blocked  # کشِ کوتاهِ «عضو نیست» هنوز اعتبار دارد
    assert env.check(force=True).allowed
    assert env.check().allowed and len(env.calls) == 2  # نتیجه‌ی تازه کش شد


def test_miss_cache_expires_quickly_without_force():
    env = Env()
    env.default = "left"
    assert env.check().blocked
    env.default = "member"
    env.clock.now += cg.MISS_TTL_SECONDS + 0.1
    assert env.check().allowed


@pytest.mark.parametrize("failure", [RuntimeError("chat not found"), asyncio.TimeoutError(), "restricted?", "", None])
def test_any_failure_or_unknown_status_fails_open(failure):
    env = Env()
    env.default = failure
    verdict = env.check()
    assert verdict.allowed and verdict.degraded and verdict.missing == []


def test_failures_alert_once_per_outage_and_recovery_resets_it():
    env = Env()
    env.default = RuntimeError("bot is not a member of the channel chat")
    for user in ("1", "2", "3"):
        assert env.check(user).allowed
    assert len(env.errors) == 1 and env.errors[0][0] == "telegram:@shop_channel" and "not a member" in env.errors[0][1]
    assert env.recovered == []
    env.default = "member"
    env.check("4")
    assert env.recovered == ["telegram:@shop_channel"]
    env.default = RuntimeError("again")
    env.check("5")
    assert len(env.errors) == 2  # خرابیِ تازه = هشدارِ تازه


def test_degraded_results_are_cached_briefly_to_spare_a_broken_api():
    env = Env()
    env.default = RuntimeError("down")
    env.check()
    env.check()
    assert len(env.calls) == 1
    env.clock.now += cg.ERROR_TTL_SECONDS + 1
    env.check()
    assert len(env.calls) == 2


def test_every_required_channel_must_be_joined_and_only_missing_ones_are_reported():
    env = Env(channels=[
        {"platform": "telegram", "channel": "@first_chan", "title": "اول"},
        {"platform": "telegram", "channel": "@second_chan", "title": "دوم"},
        {"platform": "telegram", "channel": "@third_chan", "title": "سوم"},
    ])
    env.status = {"@first_chan": "member", "@second_chan": "left", "@third_chan": "kicked"}
    verdict = env.check()
    assert [c.title for c in verdict.missing] == ["دوم", "سوم"] and verdict.blocked


def test_a_broken_channel_never_hides_a_channel_the_user_is_known_to_have_left():
    env = Env(channels=[{"platform": "telegram", "channel": "@broken_one"}, {"platform": "telegram", "channel": "@real_one"}])
    env.status = {"@broken_one": RuntimeError("no rights"), "@real_one": "left"}
    verdict = env.check()
    assert verdict.blocked and verdict.degraded and [c.channel for c in verdict.missing] == ["@real_one"]


def test_channels_are_per_platform_and_only_the_matching_ones_are_checked():
    env = Env(channels=[{"platform": "telegram", "channel": "@tg_channel"}, {"platform": "bale", "channel": "@bale_channel"}])
    env.default = "left"
    assert env.check(platform="bale").missing[0].channel == "@bale_channel"
    assert env.calls == [("bale", "@bale_channel", "1")]
    env.settings.required_channels = [{"platform": "telegram", "channel": "@tg_channel"}]
    env.gate.clear_cache()
    assert env.check(platform="bale").allowed and len(env.calls) == 1  # بله کانالی ندارد ← بدونِ تماس


def test_disabled_or_empty_configuration_never_calls_the_checker():
    env = Env()
    env.settings.required_channels_enabled = False
    assert env.check().allowed and env.calls == [] and env.gate.channels("telegram") == []
    assert not env.gate.enabled_for("telegram", "shop")
    env.settings.required_channels_enabled, env.settings.required_channels = True, []
    assert env.check().allowed and env.calls == [] and not env.gate.enabled_for("telegram", "ai")


def test_changing_the_channel_set_invalidates_the_cache_automatically():
    env = Env()
    assert env.check().allowed and len(env.calls) == 1
    env.settings.required_channels = [{"platform": "telegram", "channel": "@new_channel"}]
    env.default = "left"
    assert env.check().blocked and env.calls[-1][1] == "@new_channel"


def test_enabled_for_follows_the_scope_per_pipeline_point():
    env = Env()
    for scope, shop, ai in (("shop", True, False), ("ai", False, True), ("both", True, True)):
        env.settings.required_channels_scope = scope
        assert (env.gate.enabled_for("telegram", "shop"), env.gate.enabled_for("telegram", "ai")) == (shop, ai), scope
    assert not env.gate.enabled_for("bale", "shop")  # کانالی برای بله نیست


def test_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(cg, "MAX_CACHE_ENTRIES", 5)
    env = Env()
    for user in range(30):
        env.check(str(user))
    assert len(env.gate._cache) <= 5  # noqa: SLF001


def test_failing_or_async_callbacks_never_break_a_check():
    env = Env()
    seen = []

    async def async_on_error(ch, exc):
        seen.append(ch.ref)

    env.gate._on_error = async_on_error  # noqa: SLF001
    env.default = RuntimeError("x")
    assert env.check().allowed and seen == ["telegram:@shop_channel"]

    def boom(*_a):
        raise RuntimeError("callback bug")

    env2 = Env()
    env2.gate._on_error = boom  # noqa: SLF001
    env2.default = RuntimeError("x")
    assert env2.check().allowed
