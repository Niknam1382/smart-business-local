"""چند API و مدلِ پشتیبان با جابه‌جاییِ خودکار (N16).

* **زنجیره**: ارائه‌دهنده‌ها و مدل‌های مرتب ⇒ ``API۱/مدل۱ ← API۱/مدل۲ ← API۲/مدل۱ … ← مدلِ محلی``؛ هر درخواست از *سرِ زنجیره* شروع می‌شود، پس
  برگشت به API اصلی خودکار است (مدارشکن مهلتش که تمام شد یک درخواستِ آزمایشی می‌فرستد).
* **حافظه سالم می‌ماند**: گفتگو در دیتابیسِ خودِ برنامه است؛ هر تلاش «پرامپت + تاریخچه + پیام» را از نو و به اندازه‌ی context همان مدل می‌سازد.
* **طبقه‌بندیِ شکست**: هر خطا رفتارِ خودش را دارد (``classify``)؛ کلیدِ API هرگز در لاگ/خطا نمی‌آید.
* ``base_url`` فقط ``https://`` (به‌جز localhost/شبکه‌ی داخلی برای موتورهای محلی مثلِ Ollama).
"""

from __future__ import annotations

import ipaddress
import json
import logging
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

from app.core import ai_cache, ai_usage, token_budget, tool_protocol
from app.core.ai_engine import AiEngineError, ChatMessage, _tool_messages_chars, _trim_history

logger = logging.getLogger(__name__)

KIND_API, KIND_LOCAL = "openai_compatible", "local"
LOCAL_PROVIDER_ID = "local"
BREAKER_THRESHOLD = 3
BREAKER_BACKOFF = (30, 120, 600, 1800, 3600)  # ثانیه؛ سقفِ ۱ ساعت
QUOTA_BLOCK_SECONDS = 3600
SHORT_RETRY_CAP = 2.0

REASON_FA = {
    "transient": "جوابِ سرور کند/قطع بود", "auth": "کلیدِ API نامعتبره", "quota": "اعتبار/سهمیه‌ی حساب تموم شده", "model_gone": "این مدل دیگه وجود نداره",
    "context": "پیام برای پنجره‌ی مدل خیلی بلند بود", "tools": "این مدل ابزار رو نمی‌فهمه", "other": "سرور خطای نامعتبر داد", "breaker": "چند خطای پیاپی؛ موقتاً کنار گذاشته شد",
}


# ------------------------------------------------------------------------------ پیکربندی ----


@dataclass
class ModelCfg:
    name: str
    enabled: bool = True
    max_context_tokens: int = 0  # ۰ = پیش‌فرض
    tools_supported: Optional[bool] = None  # None = نامشخص (امتحان می‌شه)
    price_in: str = ""  # دلار به‌ازای ۱ میلیون توکنِ ورودی (کاربر وارد می‌کند)
    price_out: str = ""


@dataclass
class ProviderCfg:
    id: str
    name: str
    kind: str = KIND_API
    base_url: str = ""
    api_key: str = ""  # رمزگشایی‌شده؛ فقط در حافظه
    timeout: int = 0  # ۰ = ai_attempt_timeout
    enabled: bool = True
    models: list = field(default_factory=list)


@dataclass(frozen=True)
class Target:
    provider: ProviderCfg
    model: ModelCfg

    @property
    def key(self) -> str:
        return f"{self.provider.id}/{self.model.name}"

    @property
    def is_local(self) -> bool:
        return self.provider.kind == KIND_LOCAL


def validate_base_url(url: str) -> str:
    """``https://`` الزامی؛ ``http://`` فقط برای localhost/شبکه‌ی داخلی. خروجی بدونِ ``/`` انتها. نامعتبر ⇒ ``ValueError`` فارسی."""
    raw = (url or "").strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("آدرس باید مثلِ https://api.example.com/v1 باشه.")
    if parsed.scheme == "https":
        return raw
    host = parsed.hostname.lower()
    local = host == "localhost" or host.endswith(".local")
    if not local:
        try:
            ip = ipaddress.ip_address(host)
            local = ip.is_loopback or ip.is_private
        except ValueError:
            local = False
    if not local:
        raise ValueError("برای امنیتِ کلیدت آدرس باید با https:// شروع بشه (http فقط برای localhost و شبکه‌ی داخلی مجازه).")
    return raw


def new_provider_id() -> str:
    return "p" + uuid.uuid4().hex[:8]


def parse_providers(settings) -> list:
    """ارائه‌دهنده‌ها از تنظیمات؛ تنظیماتِ قدیمیِ تک‌API (``api_*``) خودکار می‌شود ارائه‌دهنده‌ی ۱ (مهاجرتِ بی‌صدا)."""
    from app.core import crypto

    out = []
    for raw in getattr(settings, "ai_providers", None) or []:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        models = []
        for m in raw.get("models") or []:
            if isinstance(m, dict) and str(m.get("name", "")).strip():
                ts = m.get("tools_supported")
                models.append(ModelCfg(str(m["name"]).strip(), bool(m.get("enabled", True)), int(m.get("max_context_tokens") or 0),
                                       ts if isinstance(ts, bool) else None, str(m.get("price_in", "")), str(m.get("price_out", ""))))
        enc = raw.get("api_key_encrypted", "")
        try:
            key = crypto.decrypt(enc) if enc else ""
        except Exception:  # noqa: BLE001
            key = ""
        out.append(ProviderCfg(str(raw["id"]), str(raw.get("name") or raw["id"]), raw.get("kind", KIND_API), str(raw.get("base_url", "")), key,
                               int(raw.get("timeout") or 0), bool(raw.get("enabled", True)), models))
    if not out and getattr(settings, "ai_mode", None) == "api" and getattr(settings, "api_base_url", ""):
        out.append(ProviderCfg("api-1", "API اصلی", KIND_API, settings.api_base_url, settings.get_api_key(), 0, True,
                               [ModelCfg(settings.api_model_name or "gpt-4o-mini")]))
    return out


def provider_to_dict(p: ProviderCfg, encrypted_key: str) -> dict:
    return {"id": p.id, "name": p.name, "kind": p.kind, "base_url": p.base_url, "api_key_encrypted": encrypted_key, "timeout": p.timeout, "enabled": p.enabled,
            "models": [{"name": m.name, "enabled": m.enabled, "max_context_tokens": m.max_context_tokens, "tools_supported": m.tools_supported,
                        "price_in": m.price_in, "price_out": m.price_out} for m in p.models]}


def build_chain(providers: list, local_model: str = "") -> list:
    chain = [Target(p, m) for p in providers if p.enabled and p.kind == KIND_API for m in p.models if m.enabled]
    if local_model:
        chain.append(Target(ProviderCfg(LOCAL_PROVIDER_ID, "مدلِ محلی", KIND_LOCAL), ModelCfg(local_model)))
    return chain


# ------------------------------------------------------------------------------ HTTP و طبقه‌بندی ----


class AiHttpError(AiEngineError):
    def __init__(self, message: str, status: int = 0, body: str = "", retry_after: float = 0.0, kind: str = "http"):
        super().__init__(message)
        self.status, self.body, self.retry_after, self.kind = status, body, retry_after, kind


def post_chat(base_url: str, api_key: str, payload: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=max(0.5, timeout)) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1000]
        try:
            retry_after = float(exc.headers.get("Retry-After", "") or 0)
        except ValueError:
            retry_after = 0.0
        raise AiHttpError(f"سرور خطای HTTP {exc.code} برگردوند", exc.code, body, retry_after) from None
    except (socket.timeout, TimeoutError):
        raise AiHttpError("پاسخِ سرور دیر رسید", kind="timeout") from None
    except urllib.error.URLError as exc:
        kind = "timeout" if isinstance(exc.reason, (socket.timeout, TimeoutError)) else "network"
        raise AiHttpError("اتصال به API ناموفق بود", kind=kind) from None
    except OSError:
        raise AiHttpError("اتصال به API ناموفق بود", kind="network") from None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError
    except ValueError:
        raise AiHttpError("پاسخِ سرور JSON معتبر نبود", kind="format") from None
    return data


def classify(exc: AiEngineError) -> str:
    status = getattr(exc, "status", 0)
    body = (getattr(exc, "body", "") or "").lower()
    if not status:
        return "transient"
    if status in (401, 403) and "quota" not in body and "balance" not in body:
        return "auth"
    if status == 402 or "insufficient_quota" in body or "insufficient_balance" in body or "billing" in body and status in (403, 429):
        return "quota"
    if "context_length" in body or "maximum context" in body or "context window" in body or "too many tokens" in body:
        return "context"
    if status == 404 or "model_not_found" in body or "decommission" in body or ("model" in body and ("does not exist" in body or "deprecated" in body)):
        return "model_gone"
    if status in (400, 422) and ("tool" in body or "function" in body):
        return "tools"
    if "content_filter" in body or "content_policy" in body:
        return "filter"
    if status == 429 or status >= 500:
        return "transient"
    return "other"


# ------------------------------------------------------------------------------ سلامت و مدارشکن ----


class _Breaker:
    __slots__ = ("failures", "level", "open_until", "probe_until")

    def __init__(self):
        self.failures = 0
        self.level = 0
        self.open_until = 0.0
        self.probe_until = 0.0


class AiHealth:
    """وضعیتِ زنده‌ی زنجیره (فقط حافظه). نخ‌امن."""

    def __init__(self):
        self.clock = time.monotonic
        self.notifier = None  # callable(text) — BotManager وصل می‌کند
        self.reset()

    def reset(self) -> None:
        self._lock = threading.RLock()
        self._breakers: dict = {}
        self._provider_block: dict = {}  # pid → (reason, until)
        self._model_block: dict = {}  # key → reason
        self._tools_off: set = set()
        self._latency: dict = {}
        self._alerted: set = set()
        self.events: deque = deque(maxlen=20)

    # ---- مدار
    def usable(self, t: Target) -> bool:
        now = self.clock()
        with self._lock:
            block = self._provider_block.get(t.provider.id)
            if block and block[1] > now:
                return False
            if t.key in self._model_block:
                return False
            b = self._breakers.get(t.key)
            if b is None or b.open_until == 0:
                return True  # بسته (فقط شمارشِ شکست)
            if b.open_until > now or b.probe_until > now:
                return False  # باز، یا یک درخواستِ آزمایشی در راه است
            b.probe_until = now + 30  # half-open: دقیقاً یک درخواستِ آزمایشی
            return True

    def success(self, t: Target, latency: float = 0.0) -> None:
        with self._lock:
            b = self._breakers.get(t.key)
            was_down = b is not None and (b.level > 0 or b.open_until > 0)
            self._breakers.pop(t.key, None)
            self._latency[t.key] = latency if t.key not in self._latency else 0.7 * self._latency[t.key] + 0.3 * latency
            self._provider_block.pop(t.provider.id, None) if self._provider_block.get(t.provider.id, ("", 0))[1] <= self.clock() else None
        if was_down:
            self.alert_clear(f"down:{t.key}", f"✅ «{t.provider.name} / {t.model.name}» دوباره وصل شد.")
        self.alert_clear("all_down", "✅ هوش مصنوعی دوباره پاسخ می‌دهد.")

    def failure(self, t: Target, reason: str) -> None:
        now = self.clock()
        with self._lock:
            b = self._breakers.setdefault(t.key, _Breaker())
            b.failures += 1
            if b.failures >= BREAKER_THRESHOLD or b.open_until:
                b.open_until = now + BREAKER_BACKOFF[min(b.level, len(BREAKER_BACKOFF) - 1)]
                b.level += 1
                b.failures = 0
                b.probe_until = 0.0
                opened = True
            else:
                opened = False
        if opened:
            self.alert(f"down:{t.key}", f"⚠️ «{t.provider.name} / {t.model.name}» جواب نمی‌ده ({REASON_FA.get(reason, reason)}). ربات خودکار سراغِ گزینه‌ی بعدی می‌ره.")

    def block_provider(self, t: Target, reason: str, seconds: float) -> None:
        with self._lock:
            self._provider_block[t.provider.id] = (reason, self.clock() + seconds)
        self.alert(f"{reason}:{t.provider.id}", f"⚠️ «{t.provider.name}»: {REASON_FA.get(reason, reason)}. تا اصلاح، کنار گذاشته شد.")

    def block_model(self, t: Target, reason: str) -> None:
        with self._lock:
            self._model_block[t.key] = reason
        self.alert(f"{reason}:{t.key}", f"⚠️ مدلِ «{t.model.name}» در «{t.provider.name}» دیگه وجود نداره و غیرفعال شد.")

    def tools_off(self, t: Target) -> None:
        with self._lock:
            self._tools_off.add(t.key)

    def tools_disabled(self, t: Target) -> bool:
        return t.key in self._tools_off or t.model.tools_supported is False

    def note_failover(self, frm: Target, reason: str, to: Optional[Target]) -> None:
        with self._lock:
            self.events.appendleft({"ts": int(time.time()), "from": frm.key, "to": to.key if to else "", "reason": reason})

    def status(self, t: Target, attempt_timeout: float = 15.0) -> tuple:
        """``(وضعیت، علتِ فارسی)`` — وضعیت ∈ ok | slow | down | disabled."""
        now = self.clock()
        with self._lock:
            if not t.provider.enabled or not t.model.enabled:
                return "disabled", "غیرفعال"
            block = self._provider_block.get(t.provider.id)
            if block and block[1] > now:
                return "down", REASON_FA.get(block[0], block[0])
            if t.key in self._model_block:
                return "disabled", REASON_FA["model_gone"]
            b = self._breakers.get(t.key)
            if b is not None and b.open_until > now:
                return "down", REASON_FA["breaker"]
            lat = self._latency.get(t.key, 0.0)
            if lat and lat > 0.7 * attempt_timeout:
                return "slow", "پاسخ‌ها کنده"
        return "ok", ""

    # ---- هشدارِ یک‌باره
    def alert(self, key: str, text: str) -> None:
        with self._lock:
            if key in self._alerted:
                return
            self._alerted.add(key)
        self._send(text)

    def alert_clear(self, key: str, text: str) -> None:
        with self._lock:
            if key not in self._alerted:
                return
            self._alerted.discard(key)
        self._send(text)

    def _send(self, text: str) -> None:
        notifier = self.notifier
        if notifier is None:
            return
        try:
            notifier(text)
        except Exception:  # noqa: BLE001
            logger.debug("ارسالِ هشدارِ AI ناموفق بود", exc_info=True)


HEALTH = AiHealth()


# ------------------------------------------------------------------------------ موتورِ زنجیره‌ای ----


@dataclass
class _Attempt:
    text: str = ""
    turn: object = None
    finish: str = ""
    prompt: int = 0
    completion: int = 0
    cached: int = 0
    estimated: bool = False


class FailoverEngine:
    """همان رابطِ ``chat`` / ``chat_tools`` ِ موتورهای قبلی؛ پشتش زنجیره‌ی (ارائه‌دهنده، مدل)."""

    concurrent_safe = True

    def __init__(self, settings, targets: Optional[list] = None, local_factory=None, budget=None, persist=None, sleep=time.sleep, clock=time.monotonic, health: AiHealth = None):
        self.settings = settings
        self.health = health or HEALTH
        self._local_factory = local_factory
        self._local = None
        self._local_lock = threading.Lock()
        self.budget = budget
        self.persist = persist  # callable() — ذخیره‌ی تنظیمات وقتی مدلی ماندگار غیرفعال شد
        self._sleep, self._clock = sleep, clock
        self._sems: dict = {}
        self.targets = targets if targets is not None else self._targets_from_settings()

    def _targets_from_settings(self) -> list:
        local_model = "local" if getattr(self.settings, "ai_local_fallback", False) and self._local_factory else ""
        return build_chain(parse_providers(self.settings), local_model)

    def _sem(self, pid: str) -> threading.BoundedSemaphore:
        if pid not in self._sems:
            self._sems[pid] = threading.BoundedSemaphore(max(1, int(getattr(self.settings, "ai_provider_concurrency", 4))))
        return self._sems[pid]

    # ---------- رابطِ عمومی
    def chat(self, system_prompt: str, history: list, user_message: str) -> str:
        return self._run(system_prompt, history, user_message, None, []).text

    def chat_tools(self, system_prompt: str, history: list, user_message: str, tools: list, tool_messages: list):
        res = self._run(system_prompt, history, user_message, tools, tool_messages)
        return res.turn

    def unload(self) -> None:
        if self._local is not None and hasattr(self._local, "unload"):
            self._local.unload()
        self._local = None

    # ---------- هسته
    def _run(self, system_prompt, history, user_message, tools, tool_messages) -> _Attempt:
        s = self.settings
        started = self._clock()
        total = float(getattr(s, "ai_total_timeout", 45))
        max_targets = max(1, int(getattr(s, "ai_max_targets", 3)))
        candidates = list(self.targets)
        if self.budget is not None:
            state = self.budget.status()
            action = getattr(s, "ai_budget_action", "warn")
            month = time.strftime("%Y-%m")
            if state == "exceeded":
                self.health.alert(f"budget:{month}", "⚠️ بودجه‌ی ماهانه‌ی هوش مصنوعی تموم شد.")
                if action == "stop":
                    raise AiEngineError("بودجه‌ی ماهانه‌ی AI تموم شده")
                if action == "local":
                    candidates = [t for t in candidates if t.is_local]
                    if not candidates:
                        raise AiEngineError("بودجه‌ی ماهانه‌ی AI تموم شده و مدلِ محلی در دسترس نیست")
            elif state == "warn":
                self.health.alert(f"budget80:{month}", "ℹ️ ۸۰٪ بودجه‌ی ماهانه‌ی هوش مصنوعی مصرف شده.")
        tried = 0
        last_reason, last_target = "", None
        for target in candidates:
            if tried >= max_targets or self._clock() - started >= total:
                break
            if not self.health.usable(target):
                continue
            if last_target is not None:
                self.health.note_failover(last_target, last_reason, target)
            tried += 1
            try:
                result = self._try_target(target, system_prompt, history, user_message, tools, tool_messages, started, total, tried, last_reason)
            except _Skip as skip:
                last_reason, last_target = skip.reason, target
                continue
            self.health.success(target, self._clock() - started)
            return result
        self.health.alert("all_down", "🚨 هیچ‌کدام از APIهای هوش مصنوعی جواب نمی‌دهند؛ مشتری‌ها پیامِ «الان نمی‌تونم» می‌بینن. تنظیماتِ ارائه‌دهنده‌ها رو چک کن.")
        raise AiEngineError("هیچ ارائه‌دهنده‌ی AI در دسترس نیست" + (f" ({REASON_FA.get(last_reason, last_reason)})" if last_reason else ""))

    def _try_target(self, t: Target, system_prompt, history, user_message, tools, tool_messages, started, total, attempt_no, failover_reason) -> _Attempt:
        s = self.settings
        attempt_timeout = float(t.provider.timeout or getattr(s, "ai_attempt_timeout", 15))
        native = bool(tools) and not self.health.tools_disabled(t)
        ctx_scale, retried_short, retried_ctx, length_bumped = 1.0, False, False, False
        max_tokens = token_budget.pick_max_tokens(user_message, bool(tools)) if getattr(s, "token_opt_max_tokens", True) else None
        reason = failover_reason
        while True:
            remaining = total - (self._clock() - started)
            if remaining <= 0.3:
                raise _Skip("transient")
            payload, parts = self._payload(t, system_prompt, history, user_message, tools, tool_messages, native, max_tokens, ctx_scale)
            cache_key = None
            if not t.is_local and not tools and getattr(s, "token_opt_response_cache", False) and ai_cache.is_cacheable(payload, len(history), user_message):
                cache_key = ai_cache.payload_key({"t": t.key, "p": payload})
                hit = ai_cache.CACHE.get(cache_key)
                if hit is not None:
                    ai_usage.record_call(provider_id="cache", model=t.model.name, attempt=0, kind="chat", saved_tokens=parts["prompt_est"] + token_budget.estimate_tokens(hit), estimated=True)
                    return _Attempt(text=hit)
            sem = None if t.is_local else self._sem(t.provider.id)
            if sem is not None and not sem.acquire(timeout=min(remaining, 3.0)):
                raise _Skip("transient")
            began = self._clock()
            try:
                res = self._call(t, payload, native, tools, min(attempt_timeout, remaining), system_prompt, history, user_message, tool_messages)
            except AiEngineError as exc:
                latency = int((self._clock() - began) * 1000)
                kind = classify(exc)
                ai_usage.record_call(provider_id=t.provider.id, model=t.model.name, attempt=attempt_no, failover_reason=kind, kind="tools" if tools else "chat", latency_ms=latency, ok=False, estimated=True)
                if kind == "filter":
                    return _Attempt(text=_safe_reply(), turn=tool_protocol.ToolTurn(text=_safe_reply(), tool_calls=[]) if tools else None)
                if kind == "transient":
                    wait = getattr(exc, "retry_after", 0.0) or 0.5
                    if not retried_short and wait <= SHORT_RETRY_CAP and (total - (self._clock() - started)) > wait + 1:
                        retried_short = True
                        self._sleep(wait)
                        continue
                    self.health.failure(t, kind)
                    raise _Skip(kind) from None
                if kind == "auth":
                    self.health.block_provider(t, "auth", 10 * 365 * 86400)
                    raise _Skip(kind) from None
                if kind == "quota":
                    self.health.block_provider(t, "quota", QUOTA_BLOCK_SECONDS)
                    raise _Skip(kind) from None
                if kind == "model_gone":
                    self.health.block_model(t, "model_gone")
                    self._persist_model_disabled(t)
                    raise _Skip(kind) from None
                if kind == "context" and not retried_ctx:
                    retried_ctx, ctx_scale = True, ctx_scale * 0.5
                    continue
                if kind == "tools" and native:
                    native = False
                    self.health.tools_off(t)
                    self._persist_tools_off(t)
                    continue
                self.health.failure(t, kind)
                raise _Skip(kind) from None
            finally:
                if sem is not None:
                    sem.release()
            latency = int((self._clock() - began) * 1000)
            if res.finish == "length" and max_tokens and not length_bumped:
                length_bumped, max_tokens = True, min(max_tokens * 2, 4096)
                ai_usage.record_call(provider_id=t.provider.id, model=t.model.name, attempt=attempt_no, failover_reason="length", prompt_tokens=res.prompt, completion_tokens=res.completion, cached_tokens=res.cached, kind="tools" if tools else "chat", latency_ms=latency, estimated=res.estimated, **{k: parts[k] for k in ("sys_tokens", "hist_tokens", "msg_tokens")})
                continue
            ai_usage.record_call(provider_id=t.provider.id, model=t.model.name, attempt=attempt_no, failover_reason=reason if reason else "", prompt_tokens=res.prompt, completion_tokens=res.completion,
                                 cached_tokens=res.cached, kind="tools" if tools else "chat", latency_ms=latency, estimated=res.estimated, saved_tokens=parts["saved"],
                                 **{k: parts[k] for k in ("sys_tokens", "hist_tokens", "msg_tokens")})
            if cache_key and res.finish in ("", "stop") and res.text:
                ai_cache.CACHE.put(cache_key, res.text, max(1, min(int(getattr(s, "token_opt_cache_ttl_minutes", 60)), 1440)) * 60, res.prompt + res.completion)
            return res

    # ---------- ساختِ payload (حافظه از دیتابیسِ خودمان، هر بار از نو)
    def _payload(self, t: Target, system_prompt, history, user_message, tools, tool_messages, native, max_tokens, ctx_scale):
        s = self.settings
        ctx = int((t.model.max_context_tokens or token_budget.DEFAULT_CONTEXT_TOKENS) * ctx_scale)
        extra = _tool_messages_chars(tool_messages) // 3
        if getattr(s, "token_opt_history_window", True):
            kept = token_budget.fit_history(system_prompt, history, user_message, ctx, reply_tokens=max_tokens or 700, extra_tokens=extra)
        else:
            kept = _trim_history(system_prompt, history, user_message, max_chars=(24000 if tools else 8000) - _tool_messages_chars(tool_messages))
        if tools and native:
            messages = tool_protocol.to_openai_messages(system_prompt, kept, user_message, tool_messages)
        elif tools:
            messages = tool_protocol.to_text_messages(system_prompt, kept, user_message, tool_messages, tools)
        else:
            messages = [{"role": "system", "content": system_prompt}, *({"role": m.role, "content": m.content} for m in kept), {"role": "user", "content": user_message}]
        payload = {"model": t.model.name, "messages": messages, "temperature": 0.3 if tools else 0.4}
        if tools and native:
            payload["tools"], payload["tool_choice"] = tool_protocol.to_openai_tools(tools), "auto"
        if max_tokens:
            payload["max_tokens"] = max_tokens
        dropped = token_budget.messages_tokens(history) - token_budget.messages_tokens(kept) if getattr(s, "token_opt_history_window", True) else 0
        parts = {"sys_tokens": token_budget.estimate_tokens(system_prompt), "hist_tokens": token_budget.messages_tokens(kept), "msg_tokens": token_budget.estimate_tokens(user_message),
                 "saved": max(0, dropped), "prompt_est": token_budget.messages_tokens(messages)}
        return payload, parts

    # ---------- تماس
    def _call(self, t: Target, payload, native, tools, timeout, system_prompt, history, user_message, tool_messages) -> _Attempt:
        if t.is_local:
            return self._call_local(system_prompt, history, user_message, tools, tool_messages)
        data = post_chat(t.provider.base_url, t.provider.api_key, payload, timeout)
        try:
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError):
            raise AiHttpError("پاسخِ سرور فرمتِ غیرمنتظره داشت", kind="format") from None
        finish = str(choice.get("finish_reason") or "")
        if finish == "content_filter":
            raise AiHttpError("فیلترِ محتوا", 400, "content_filter")
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
        if "prompt_tokens" in usage or "completion_tokens" in usage:
            prompt, completion, estimated = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0), False
        else:
            prompt, estimated = token_budget.messages_tokens(payload["messages"]), True
            completion = token_budget.estimate_tokens(message.get("content") or "")
        cached = int(details.get("cached_tokens") or usage.get("cached_tokens") or 0)
        if tools:
            turn = tool_protocol.parse_openai_message(message) if native else tool_protocol.parse_text_turn(message.get("content") or "")
            return _Attempt(text=getattr(turn, "text", "") or "", turn=turn, finish=finish, prompt=prompt, completion=completion, cached=cached, estimated=estimated)
        text = message.get("content")
        if not isinstance(text, str) or not text.strip():
            raise AiHttpError("پاسخِ خالی", kind="format")
        return _Attempt(text=text, finish=finish, prompt=prompt, completion=completion, cached=cached, estimated=estimated)

    def _call_local(self, system_prompt, history, user_message, tools, tool_messages) -> _Attempt:
        if self._local is None:
            self._local = self._local_factory()
            self._local.record_usage = False
        with self._local_lock:
            try:
                if tools:
                    turn = self._local.chat_tools(system_prompt, history, user_message, tools, tool_messages)
                    text = getattr(turn, "text", "") or ""
                else:
                    turn, text = None, self._local.chat(system_prompt, history, user_message)
            except AiEngineError as exc:
                raise AiHttpError(str(exc), kind="network") from None
        usage = getattr(self._local, "last_usage", None) or {}
        est = not usage
        prompt = int(usage.get("prompt_tokens") or token_budget.estimate_tokens(system_prompt) + token_budget.messages_tokens(history) + token_budget.estimate_tokens(user_message))
        completion = int(usage.get("completion_tokens") or token_budget.estimate_tokens(text))
        return _Attempt(text=text, turn=turn, finish="stop", prompt=prompt, completion=completion, estimated=est)

    # ---------- ماندگاری
    def _mutate_model(self, t: Target, **changes) -> None:
        changed = False
        for p in getattr(self.settings, "ai_providers", None) or []:
            if isinstance(p, dict) and p.get("id") == t.provider.id:
                for m in p.get("models") or []:
                    if isinstance(m, dict) and m.get("name") == t.model.name:
                        m.update(changes)
                        changed = True
        if changed and self.persist is not None:
            try:
                self.persist()
            except Exception:  # noqa: BLE001
                logger.debug("ذخیره‌ی تنظیماتِ مدل ناموفق بود", exc_info=True)

    def _persist_model_disabled(self, t: Target) -> None:
        self._mutate_model(t, enabled=False)

    def _persist_tools_off(self, t: Target) -> None:
        self._mutate_model(t, tools_supported=False)


def test_target(provider: ProviderCfg, model: ModelCfg, timeout: float = 15.0) -> dict:
    """دکمه‌ی «تست»: یک درخواستِ کوتاه (تأخیر + توکن) و یکی با ابزار (پشتیبانیِ tool-calling). هرگز استثنا نمی‌دهد؛ خطا فارسی و بدونِ کلید است."""
    out = {"ok": False, "latency_ms": 0, "tokens": 0, "tools_supported": None, "error": ""}
    base = {"model": model.name, "messages": [{"role": "user", "content": "Reply with the single word: OK"}], "max_tokens": 8}
    began = time.monotonic()
    try:
        data = post_chat(provider.base_url, provider.api_key, base, timeout)
        out["latency_ms"] = int((time.monotonic() - began) * 1000)
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        out["tokens"] = int(usage.get("total_tokens") or (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0))
        data["choices"][0]["message"]  # noqa: B018 — ساختارِ پاسخ را راستی‌آزمایی می‌کند
        out["ok"] = True
    except AiHttpError as exc:
        kind = classify(exc)
        out["error"] = REASON_FA.get(kind, "خطای ناشناخته") + (f" (HTTP {exc.status})" if exc.status else "")
        return out
    except (KeyError, IndexError, TypeError):
        out["error"] = "پاسخِ سرور فرمتِ غیرمنتظره داشت"
        return out
    probe = dict(base, tools=tool_protocol.to_openai_tools([tool_protocol.ToolSpec("ping", "test", {"type": "object", "properties": {}})]), tool_choice="auto", max_tokens=16)
    try:
        post_chat(provider.base_url, provider.api_key, probe, timeout)
        out["tools_supported"] = True
    except AiHttpError as exc:
        out["tools_supported"] = False if classify(exc) in ("tools", "other") else None
    return out


class _Skip(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _safe_reply() -> str:
    from app.core import shop_texts

    return shop_texts.t("ai.filtered")


__all__ = ["FailoverEngine", "HEALTH", "ProviderCfg", "ModelCfg", "Target", "parse_providers", "build_chain", "validate_base_url", "classify", "ChatMessage"]
