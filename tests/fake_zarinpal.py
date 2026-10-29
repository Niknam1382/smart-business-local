"""سرور جعلیِ زرین‌پال (v4) روی 127.0.0.1 — همون شکل JSONِ مستندات رسمی."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeZarinpalServer:
    def __init__(self, merchant_id="12345678-1234-1234-1234-123456789012"):
        self.merchant_id = merchant_id
        self.requests = []  # بدنه‌ی درخواست‌های ساخت پرداخت
        self.verifies = []  # بدنه‌ی درخواست‌های verify
        self.paid = set()  # authorityهایی که مشتری «پرداخت کرده»
        self.verified = set()
        self.amounts = {}
        self.fail_request_with = None  # مثلاً {"code": -9, "message": "..."}
        self.down = False  # شبیه‌سازی قطعیِ شبکه (اتصال بسته می‌شه)
        self._n = 0
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # ساکت
                pass

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("content-length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                if outer.down:
                    self.connection.close()
                    return
                if self.path.endswith("/request.json"):
                    resp = outer._request(body)
                elif self.path.endswith("/verify.json"):
                    resp = outer._verify(body)
                else:
                    resp = {"data": [], "errors": {"code": -1, "message": "bad path"}}
                raw = json.dumps(resp).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._server.shutdown()
        self._server.server_close()

    # ---- منطق
    def _request(self, body):
        with self._lock:
            self.requests.append(body)
            if self.fail_request_with:
                return {"data": [], "errors": dict(self.fail_request_with)}
            if body.get("merchant_id") != self.merchant_id:
                return {"data": [], "errors": {"code": -10, "message": "Terminal is not valid"}}
            self._n += 1
            authority = f"A{self._n:035d}"
            self.amounts[authority] = body["amount"]
            return {"data": {"code": 100, "message": "Success", "authority": authority, "fee_type": "Merchant", "fee": 100}, "errors": []}

    def _verify(self, body):
        with self._lock:
            self.verifies.append(body)
            authority = body.get("authority")
            if authority not in self.amounts:
                return {"data": [], "errors": {"code": -54, "message": "Invalid authority"}}
            if self.amounts[authority] != body.get("amount"):
                return {"data": [], "errors": {"code": -50, "message": "Amount mismatch"}}
            if authority not in self.paid:
                return {"data": [], "errors": {"code": -51, "message": "Session is not valid"}}
            code = 101 if authority in self.verified else 100
            self.verified.add(authority)
            return {"data": {"code": code, "message": "Paid", "ref_id": 201, "card_pan": "502229******5995"}, "errors": []}

    # ---- کمک‌ها برای تست
    def pay(self, authority):
        with self._lock:
            self.paid.add(authority)

    @property
    def last_authority(self):
        return list(self.amounts)[-1] if self.amounts else None
