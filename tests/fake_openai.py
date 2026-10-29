"""سرور جعلیِ سازگار با OpenAI Chat Completions روی 127.0.0.1 (برای تست ApiEngine)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeOpenAIServer:
    """``handler(payload) -> (status, dict)`` برای هر درخواست صدا زده می‌شه؛ همه‌ی
    درخواست‌ها توی ``requests`` ثبت می‌شن."""

    def __init__(self, handler):
        self.requests = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("content-length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
                outer.requests.append({"path": self.path, "auth": self.headers.get("authorization"), "payload": payload})
                result = handler(payload)
                status, body = result[0], result[1]
                extra = result[2] if len(result) > 2 else {}
                if extra.get("sleep"):
                    import time as _t
                    _t.sleep(extra["sleep"])
                raw = body.encode() if isinstance(body, str) else json.dumps(body).encode()
                self.send_response(status)
                for k, v in (extra.get("headers") or {}).items():
                    self.send_header(k, v)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._server.shutdown()
        self._server.server_close()


def message_reply(content=None, tool_calls=None):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return 200, {"choices": [{"message": msg}]}


def native_call(name, args, call_id="call_1"):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def usage_reply(content, prompt=11, completion=7, cached=0, finish="stop", with_usage=True):
    body = {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}]}
    if with_usage:
        body["usage"] = {"prompt_tokens": prompt, "completion_tokens": completion, "prompt_tokens_details": {"cached_tokens": cached}}
    return 200, body


def error_reply(status, message="err", code="", headers=None):
    return status, {"error": {"message": message, "code": code, "type": code}}, {"headers": headers or {}}
