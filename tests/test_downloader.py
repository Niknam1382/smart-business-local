"""دانلودِ مدلِ GGUF: ادامه‌دادن (Range/206)، اثرانگشت، کنسل‌کردن و آینه‌ها.

سرورِ جعلی روی 127.0.0.1 اجرا می‌شه (همان سبکِ ``tests/fake_servers.py``) — نه اینترنت، نه مدلِ واقعی.
"""

import hashlib
import json
import re
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.core import downloader as dl

FAST_CHUNK = 32 * 1024
DEAD_URL = "http://127.0.0.1:1/models/gone.gguf"  # هیچ سرویسی پشت این پورت نیست ⇒ URLError


def make_blob(size: int) -> bytes:
    """بدنه‌ی قطعیِ با امضای GGUF در ابتدا (هرگز تصادفی، تا اثرانگشتِ تست ثابت بماند)."""
    body = bytearray(b"GGUF")
    block = bytes(range(251))
    while len(body) < size:
        body.extend(block)
    return bytes(body[:size])


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # سکوت در تست
        pass

    def do_GET(self):  # noqa: N802
        srv = self.server.owner
        srv.requests.append({"path": self.path, "range": self.headers.get("Range")})
        if srv.redirect_to:
            self.send_response(302)
            self.send_header("Location", srv.redirect_to)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if srv.oversize_stream:
            # Content-Length نمی‌فرستد و بی‌وقفه با chunked ادامه می‌دهد: هدف، پرکردنِ دیسک است
            self.send_response(200)
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            block = srv.data[:FAST_CHUNK] or b"\0" * 1024
            sent = 0
            limit = len(srv.data) * 4
            try:
                while sent < limit:
                    self.wfile.write(b"%x\r\n" % len(block) + block + b"\r\n")
                    sent += len(block)
                self.wfile.write(b"0\r\n\r\n")
            except (ConnectionError, OSError):  # کلاینت همان‌جا قطع کرده — همان چیزی که تست می‌خواهیم
                pass
            return
        if srv.status_error:
            self.send_response(srv.status_error)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        start = 0
        header = srv.requests[-1]["range"]
        if header and srv.accept_range:
            match = re.match(r"bytes=(\d+)-(\d*)", header)
            if match:
                start = int(match.group(1))
            if start >= len(srv.data):
                start = 0  # Range نامعتبر ⇒ همان پاسخِ کاملِ ۲۰۰ (سردرِ بی‌تفاوت)
        payload = srv.data[start:]
        if start and srv.accept_range:
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(srv.data) - 1}/{len(srv.data)}")
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (ConnectionError, OSError):  # کنسل‌کردنِ سمتِ کلاینت
            pass


class FakeFileServer:
    """یک فایلِ باینری روی حلقه‌ی لوکال؛ ``accept_range=False`` یعنی سرور «ادامه» را قبول نمی‌کند."""

    def __init__(self, data: bytes, *, accept_range=True, status_error=0, oversize_stream=False, redirect_to=""):
        self.data = data
        self.accept_range = accept_range
        self.status_error = status_error
        self.oversize_stream = oversize_stream  # بدونِ Content-Length، بی‌وقفه می‌فرستد (حمله‌ی پرکردنِ دیسک)
        self.redirect_to = redirect_to  # هدایتِ بعدی به هوستِ ناشناخته
        self.requests: list = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.owner = self
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._server.shutdown()
        self._server.server_close()

    def url(self, name="model.gguf"):
        return f"http://127.0.0.1:{self._server.server_address[1]}/models/{name}"

    @property
    def ranges(self) -> list:
        return [r["range"] for r in self.requests]


@pytest.fixture
def blob():
    return make_blob(160 * 1024)  # پنج قطعه در تست


@pytest.fixture
def small_chunk(monkeypatch):
    monkeypatch.setattr(dl, "CHUNK_SIZE", FAST_CHUNK)


@pytest.fixture
def serve(blob):
    started: list = []

    def _serve(data=None, **kw):
        srv = FakeFileServer(data if data is not None else blob, **kw).start()
        started.append(srv)
        return srv

    yield _serve
    for srv in started:
        srv.stop()


def part_of(dest):
    return dest.with_name(dest.name + ".part")


def meta_of(dest):
    return dest.with_name(dest.name + ".part.meta")


# ------------------------------------------------------------------ مسیرِ عادی ----


def test_download_writes_a_verified_file_and_leaves_no_temp_files(tmp_path, blob, small_chunk, serve):
    srv = serve()
    dest = tmp_path / "models" / "qwen.gguf"
    seen: list = []

    result = dl.download([srv.url()], dest, expected_sha256=hashlib.sha256(blob).hexdigest(), expected_size=len(blob),
                         on_progress=lambda done, total: seen.append((done, total)))

    assert result == dest and dest.read_bytes() == blob
    assert not part_of(dest).exists() and not meta_of(dest).exists()
    assert seen[0][0] == FAST_CHUNK and seen[-1] == (len(blob), len(blob))
    assert all(total == len(blob) for _d, total in seen)


def test_download_without_sha_only_needs_the_size_to_match(tmp_path, blob, small_chunk, serve):
    dest = tmp_path / "m.gguf"
    dl.download([serve().url()], dest, expected_size=len(blob))
    assert dest.read_bytes() == blob


def test_no_sources_and_bad_size_are_rejected(tmp_path, blob, small_chunk, serve):
    with pytest.raises(dl.DownloadError, match="نشانی"):
        dl.download([], tmp_path / "x.gguf")
    # بدونِ اثرانگشت ولی با حجمِ وعده‌داده‌شده‌ی خیلی متفاوت ⇒ دانلود باطل می‌شه (مدلِ اشتباه بارگذاری نشه)
    dest = tmp_path / "wrong.gguf"
    with pytest.raises(dl.DownloadError, match="حجم"):
        dl.download([serve().url()], dest, expected_size=len(blob) * 3)
    assert not dest.exists() and not part_of(dest).exists()


# ------------------------------------------------------------------ ادامه‌دادن ----


def test_resume_asks_the_server_for_the_missing_bytes(tmp_path, blob, small_chunk, serve):
    srv = serve()
    url = srv.url()
    sha = hashlib.sha256(blob).hexdigest()
    dest = tmp_path / "m.gguf"
    first = len(blob) // 2
    part_of(dest).write_bytes(blob[:first])
    meta_of(dest).write_text(json.dumps({"url": url, "sha256": sha, "total": len(blob)}), encoding="utf-8")

    dl.download([url], dest, expected_sha256=sha, expected_size=len(blob))

    assert dest.read_bytes() == blob
    assert srv.ranges == [f"bytes={first}-"]  # فقط نیمه‌ی دوم درخواست شد
    assert not part_of(dest).exists() and not meta_of(dest).exists()


def test_resume_is_refused_when_the_part_belongs_to_another_file(tmp_path, blob, small_chunk, serve):
    srv = serve()
    dest = tmp_path / "m.gguf"
    part_of(dest).write_bytes(b"xxxxxxxx" * 100)  # از اثرانگشت/آدرسِ دیگری
    meta_of(dest).write_text(json.dumps({"url": "http://other.example/v1/m.gguf", "sha256": "0" * 64, "total": 999}), encoding="utf-8")

    dl.download([srv.url()], dest, expected_sha256=hashlib.sha256(blob).hexdigest())

    assert dest.read_bytes() == blob and srv.ranges == [None]  # از صفر، بدونِ Range


def test_server_that_ignores_range_falls_back_to_a_full_download(tmp_path, blob, small_chunk, serve):
    srv = serve(accept_range=False)
    dest = tmp_path / "m.gguf"
    half = len(blob) // 2
    part_of(dest).write_bytes(blob[:half])
    meta_of(dest).write_text(json.dumps({"url": srv.url(), "sha256": hashlib.sha256(blob).hexdigest(), "total": len(blob)}), encoding="utf-8")

    dl.download([srv.url()], dest, expected_sha256=hashlib.sha256(blob).hexdigest(), expected_size=len(blob))

    assert srv.ranges == [f"bytes={half}-"]  # Range زده شد…
    assert dest.read_bytes() == blob  # … و چون ۲۰۰ آمد، از سرِ نو کامل شد


def test_part_longer_than_the_real_file_is_reset(tmp_path, blob, small_chunk, serve):
    srv = serve()
    dest = tmp_path / "m.gguf"
    part_of(dest).write_bytes(blob + b"junk")  # .part خراب/دستکاری‌شده
    meta_of(dest).write_text(json.dumps({"url": srv.url(), "sha256": hashlib.sha256(blob).hexdigest(), "total": len(blob)}), encoding="utf-8")
    dl.download([srv.url()], dest, expected_sha256=hashlib.sha256(blob).hexdigest())
    assert dest.read_bytes() == blob


# ------------------------------------------------------------- اثرانگشت و کنسل ----


def test_wrong_sha_is_integrity_error_and_the_part_is_dropped(tmp_path, blob, small_chunk, serve):
    good_sha = hashlib.sha256(blob).hexdigest()
    mirror = serve(make_blob(2048))
    bad = serve(blob + b"tampered")  # آینه‌ی دوم هم همان فایلِ باطل را می‌دهد
    dest = tmp_path / "m.gguf"

    with pytest.raises(dl.IntegrityError, match="اثرانگشت") as exc:
        dl.download([bad.url(), mirror.url()], dest, expected_sha256=good_sha, expected_size=len(blob))

    assert not dest.exists() and not part_of(dest).exists() and not meta_of(dest).exists()
    assert len(bad.requests) == 1 and mirror.requests == []  # اثرانگشتِ باطل ⇒ دانلودِ دوباره بی‌فایده است
    assert good_sha not in str(exc.value)  # اثرانگشتِ موردِ انتظار در پیام نمی‌آید


def test_cancel_keeps_the_part_and_meta_for_the_next_try(tmp_path, blob, small_chunk, serve):
    srv = serve()
    dest = tmp_path / "m.gguf"
    sha = hashlib.sha256(blob).hexdigest()
    state = {"n": 0}

    def should_cancel():
        state["n"] += 1
        return state["n"] > 3  # بعدِ سه قطعه کاربر «توقف» را می‌زند

    with pytest.raises(dl.DownloadCancelled):
        dl.download([srv.url()], dest, expected_sha256=sha, should_cancel=should_cancel)

    assert not dest.exists()
    partial = part_of(dest).read_bytes()
    assert 0 < len(partial) < len(blob)
    meta = json.loads(meta_of(dest).read_text(encoding="utf-8"))
    assert meta == {"url": srv.url(), "sha256": sha, "total": len(blob)}
    assert dl.partial_bytes(dest) == len(partial)

    # ادامه: همان فایل، فقط باقی‌مانده‌ی بایت‌ها
    dl.download([srv.url()], dest, expected_sha256=sha)
    assert dest.read_bytes() == blob
    assert srv.ranges[-1] == f"bytes={len(partial)}-"


def test_progress_can_be_omitted_and_cancel_none_means_no_cancel(tmp_path, blob, small_chunk, serve):
    dest = tmp_path / "m.gguf"
    assert dl.download([serve().url()], dest, should_cancel=lambda: False) == dest


# --------------------------------------------------------------------- آینه‌ها ----


def test_falls_back_to_the_next_mirror_when_the_first_is_down(tmp_path, blob, small_chunk, serve):
    srv = serve()
    dest = tmp_path / "m.gguf"
    result = dl.download([DEAD_URL, srv.url()], dest, expected_sha256=hashlib.sha256(blob).hexdigest())
    assert result == dest and dest.read_bytes() == blob and len(srv.requests) == 1


def test_http_error_on_the_primary_moves_to_the_mirror(tmp_path, blob, small_chunk, serve):
    broken = serve(status_error=500)
    good = serve()
    dest = tmp_path / "m.gguf"
    dl.download([broken.url(), good.url()], dest, expected_sha256=hashlib.sha256(blob).hexdigest())
    assert dest.read_bytes() == blob and len(broken.requests) == 1 and len(good.requests) == 1


def test_when_every_mirror_fails_the_message_is_persian_and_actionable(tmp_path, small_chunk):
    with pytest.raises(dl.DownloadError, match="هیچ منبعی") as exc:
        dl.download([DEAD_URL, DEAD_URL + "2"], tmp_path / "m.gguf", timeout=2.0)
    assert "اتصال اینترنت" in str(exc.value)  # راه‌حل، نه جزئیاتِ فنی


# ------------------------------------------------------- ابزارهایِ کنارِ دانلود ----


def test_sha256_file_matches_hashlib(tmp_path, blob):
    path = tmp_path / "f.bin"
    path.write_bytes(blob)
    assert dl.sha256_file(path) == hashlib.sha256(blob).hexdigest()


def test_verify_file_reports_honesty(tmp_path, blob):
    good = tmp_path / "good.gguf"
    good.write_bytes(blob)
    sha = hashlib.sha256(blob).hexdigest()
    assert dl.verify_file(good, sha) == (True, "")
    assert dl.verify_file(good, "0" * 64)[0] is False and "دوباره دانلود" in dl.verify_file(good, "0" * 64)[1]
    missing = tmp_path / "none.gguf"
    assert dl.verify_file(missing, sha) == (False, "فایل پیدا نشد.")
    assert "0" * 64 not in str(dl.verify_file(good, "0" * 64))  # اثرانگشتِ موردِ انتظار لو نمی‌ره


def test_is_downloaded_needs_a_real_gguf_of_the_right_size(tmp_path, blob):
    big = make_blob(2 * 1024 * 1024)
    good = tmp_path / "m.gguf"
    good.write_bytes(big)
    assert dl.is_downloaded(good) is True
    assert dl.is_downloaded(good, expected_size=len(big)) is True
    assert dl.is_downloaded(good, expected_size=len(big) + 40 * 1024 * 1024) is False  # سایزِ کاتالوگ نمی‌خونه
    tiny = tmp_path / "tiny.gguf"
    tiny.write_bytes(big[:1000])  # کمتر از یک مگا ⇒ «آماده نیست»
    assert dl.is_downloaded(tiny) is False
    not_gguf = tmp_path / "bad.gguf"
    not_gguf.write_bytes(b"XXXX" + big[4:])
    assert dl.is_downloaded(not_gguf) is False
    assert dl.is_downloaded(tmp_path / "absent.gguf") is False


def test_partial_bytes_and_delete_model(tmp_path, blob):
    dest = tmp_path / "m.gguf"
    assert dl.partial_bytes(dest) == 0
    part_of(dest).write_bytes(blob[:1000])
    meta_of(dest).write_text("{}", encoding="utf-8")
    dest.write_bytes(blob)
    assert dl.partial_bytes(dest) == 1000
    assert dl.delete_model(dest) is True
    assert not dest.exists() and not part_of(dest).exists() and not meta_of(dest).exists()
    assert dl.delete_model(tmp_path / "never-existed.gguf") is True  # چیزی برای پاک‌کردن نیست ⇒ خطا نمی‌ده


def test_a_server_that_sends_more_than_the_expected_size_is_stopped_mid_stream(tmp_path, blob, small_chunk, serve):
    """سقفِ جریانی: آینه‌ای که Content-Length نمی‌فرستد و بی‌وقفه داده می‌ریزد نباید بتواند
    دیسکِ فروشنده را پر کند؛ دانلود همان‌جا می‌ایستد و فایلِ «کامل» حساب نمی‌شه."""
    srv = serve(blob, oversize_stream=True)
    dest = tmp_path / "model.gguf"
    with pytest.raises(dl.DownloadError, match="بیش از حجم"):
        dl.download([srv.url()], dest, expected_sha256=hashlib.sha256(blob).hexdigest(), expected_size=len(blob))
    assert not dest.exists()


def test_a_redirect_to_an_unknown_host_is_refused(tmp_path, blob, small_chunk, serve):
    """کاتالوگ فقط هاست‌هایِ معرفی‌شده را مجاز می‌داند؛ هدایتِ بعدی به «localhost»
    (همان IP، هوستِ دیگر) باید رد بشه و اصلاً درخواست نزده بشه."""
    srv = serve(blob)
    dest = tmp_path / "model.gguf"
    evil = f"http://localhost:{srv._server.server_address[1]}/evil.gguf"  # noqa: SLF001
    srv.redirect_to = evil
    with pytest.raises(dl.DownloadError, match="هیچ منبعی"):
        dl.download([srv.url()], dest, expected_sha256=hashlib.sha256(blob).hexdigest(), expected_size=len(blob))
    assert [r["path"] for r in srv.requests] == ["/models/model.gguf"], "درخواستِ هدایت‌شده نباید ارسال می‌شد"
    assert not dest.exists()


def test_a_redirect_inside_the_allowed_host_is_still_followed(tmp_path, blob, small_chunk, serve):
    """همانِ allowlist نباید دانلودِ عادی را بشکند: هدایت به همان هوستِ مجاز پذیرفته می‌شه."""
    primary = serve(blob, redirect_to="")
    holder = serve(blob)
    dest = tmp_path / "model.gguf"
    primary.redirect_to = holder.url()  # هر دو روی 127.0.0.1 ⇒ مجاز
    dl.download([primary.url()], dest, expected_sha256=hashlib.sha256(blob).hexdigest(), expected_size=len(blob))
    assert dest.read_bytes() == blob


def test_a_redirect_to_a_declared_extra_host_is_followed(tmp_path, blob, small_chunk, serve):
    """CDNهایِ اعلام‌شده باید از same-hostِ سخت‌گیرانه رد بشوند: هر دو منبعِ واقعیِ کاتالوگ
    فایلِ GGUF را با ۳۰۲/۳۰۸ به دامنه‌ی CDN خودشان می‌فرستند، پس بدونِ این، **هیچ** مدلی
    دانلود نمی‌شد (باگِ اندازه‌گیری‌شده در نسخه‌ی ۱.۰.۰)."""
    primary = serve(blob, redirect_to="")
    holder = serve(blob)
    dest = tmp_path / "model.gguf"
    port = holder._server.server_address[1]  # noqa: SLF001
    primary.redirect_to = f"http://localhost:{port}/models/model.gguf"  # هوستِ دیگر، همان فایل
    with pytest.raises(dl.DownloadError, match="هیچ منبعی"):
        dl.download([primary.url()], dest, expected_sha256=hashlib.sha256(blob).hexdigest(), expected_size=len(blob))
    assert not dest.exists()
    dl.download([primary.url()], dest, expected_sha256=hashlib.sha256(blob).hexdigest(), expected_size=len(blob),
                allowed_hosts={"localhost"})
    assert dest.read_bytes() == blob


def test_host_matching_is_by_name_not_by_ip():
    """``evil-hf.co`` یا ``huggingface.co.evil.io`` نباید به‌خاطرِ شباهتِ متنی رد بشوند؛
    زیردامنه‌یِ دامنه‌یِ اعلام‌شده بله. ``localhost`` هم IPِ خودش نیست ⇒ رد."""
    allowed = {"hf.co", "huggingface.co"}
    assert dl.host_allowed("us.aws.cdn.hf.co", allowed)
    assert dl.host_allowed("CDN.HF.CO", allowed)
    assert dl.host_allowed("huggingface.co", allowed)
    assert not dl.host_allowed("evil-hf.co", allowed)
    assert not dl.host_allowed("huggingface.co.evil.io", allowed)
    assert not dl.host_allowed("localhost", allowed)
    assert not dl.host_allowed("", allowed)


def test_the_failure_text_names_every_source_instead_of_blaming_the_last_one(tmp_path, blob, small_chunk, serve):
    """پیامِ «از هیچ منبعی ممکن نشد» باید علتِ **هر** منبع را بگوید؛ در باگِ نسخه‌ی ۱.۰.۰
    خطایِ آخرینِ منبع (DNSِ آینه‌ی مرده) جایِ علتِ واقعی را می‌گرفت."""
    srv = serve(blob, status_error=500)
    dead = "http://localhost:1/models/gone.gguf"  # هیچ سرویسی پشتش نیست
    dest = tmp_path / "model.gguf"
    with pytest.raises(dl.DownloadError) as caught:
        dl.download([srv.url(), dead], dest, expected_sha256=hashlib.sha256(blob).hexdigest(), expected_size=len(blob))
    text = str(caught.value)
    assert "127.0.0.1" in text and "localhost" in text, text
    assert "وارد کردن فایلِ مدل" in text  # راهِ جایگزین همان‌جا گفته می‌شه


def test_the_reason_helper_strips_python_noise():
    assert dl._reason(urllib.error.URLError("[Errno 11001] getaddrinfo failed")) == "getaddrinfo failed"  # noqa: SLF001
    assert dl._reason(TimeoutError()) == "TimeoutError"  # noqa: SLF001
