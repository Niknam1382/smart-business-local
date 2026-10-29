"""
سرور جعلی Bot API (شکل تلگرام/بله) روی loopback در یه ترد جدا — برای تست‌های
سرتاسری بدون شبکه‌ی واقعی. کلاینت‌های واقعی (aiogram و BaleClient) با HTTP واقعی
به این سرور وصل می‌شن، پس مسیرهای واقعی aiohttp/aiogram (پارس‌کردن پاسخ، کدهای
خطا، تایم‌اوت، لغو درخواست) هم تست می‌شن.

حالت‌های خطا (``server.mode``):
- ok                ‑ رفتار عادی
- unauthorized      ‑ همه‌ی متدها ۴۰۱
- conflict          ‑ getUpdates ۴۰۹ (نمونه‌ی دیگه‌ای هم‌زمان polling می‌کنه)
- webhook_conflict  ‑ getUpdates ۴۰۹ با پیام «وب‌هوک فعاله»
- html_502          ‑ همه‌ی متدها ۵۰۲ با صفحه‌ی HTML (نه JSON)
"""

import asyncio
import json
import socket
import threading
import time

from aiohttp import web


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeBotApiServer:
    def __init__(self, username: str = "test_bot", port: int = 0):
        self.username = username
        self.port = port or free_port()
        self.mode = "ok"
        self.sent: list = []  # [{chat_id, text}]
        self.calls: list = []  # نام متدهای صدا زده‌شده
        self._updates: list = []
        self._next_id = 100
        self.pre_checkout_answers: list = []  # [{pre_checkout_query_id, ok, error_message}]
        self.invoices: list = []  # هر sendInvoice
        self.invoice_link_mode = "string"  # "string" | "dict" | "error"
        self.invoice_mode = "ok"  # "ok" | "error" (sendInvoice رد می‌شه؛ مثلاً provider_token نامعتبر)
        self.reject_markup = False  # شبیه‌سازیِ رد شدنِ reply_markup توسط سرور
        self.reject_documents = False  # sendDocument ← 500 (قطعیِ شبکه/سرور)
        self.reject_tel_buttons = False  # دکمه‌ی url با tel:/javascript: → 400 BUTTON_URL_INVALID (مثلِ تلگرام واقعی)
        self.edit_mode = "ok"  # "ok" | "no_text" (ویرایشِ متنِ پیامِ عکس‌دار ← 400) | "not_modified"
        self.edits: list = []  # [{chat_id, message_id, text, reply_markup}] ← editMessageText
        self.markup_edits: list = []  # [{chat_id, message_id, reply_markup}] ← editMessageReplyMarkup
        self.callback_answers: list = []  # [{callback_query_id, text, show_alert}]
        self.deleted: list = []  # [{chat_id, message_id}]
        self._seq = 0  # ترتیبِ کلیِ رویدادهای خروجی (ارسال/ویرایش) برای callback_datas
        self.inquired_transactions: list = []
        self.transaction_status = "Successful"
        self.short_descriptions: dict = {}  # {کدِ زبان ("" = پیش‌فرض): متن} ← setMyShortDescription (N17)
        self.short_description_sets: list = []  # [(language_code, text)] به‌ترتیبِ فراخوانی
        self.short_description_mode = "ok"  # "ok" | "unsupported" (۴۰۴ مثلِ متدِ ناشناخته در بله) | "flood" (۴۲۹) | "error" (۵۰۰)
        self.short_description_max = 120
        # --- N13 (عضویتِ کانال) ---
        self.member_status: dict = {}  # {(channel, user_id) یا channel: وضعیت} ← getChatMember؛ پیش‌فرض = member_default
        self.member_default = "member"
        self.chat_member_mode = "ok"  # "ok" | "no_chat" (۴۰۰ chat not found) | "not_admin" (۴۰۳ ربات عضو نیست) | "flood" (۴۲۹) | "garbage" (پاسخِ نامعتبر)
        self.chat_member_calls: list = []  # [{chat_id, user_id}]
        self.chat_member_delay = 0.0  # ثانیه تأخیر در پاسخِ getChatMember (شبیه‌سازیِ شبکه‌ی گیرکرده)
        # --- N7 (پیامِ همگانی): تزریقِ خطای ارسال ---
        self.send_failures: dict = {}  # {chat_id: (status, description)} ← هر ارسال به آن چت همیشه خطا می‌دهد
        self.flood_sends = 0  # N ارسالِ بعدی (هر چت) ← ۴۲۹ با retry_after
        self.flood_retry_after = 1
        self.send_log: list = []  # [(chat_id, "ok"|"fail:<status>")] به‌ترتیبِ تلاش (حتی ناموفق)
        self._lock = threading.Lock()
        self._loop = None
        self._thread = None
        self._runner = None

    # ---- آدرس‌ها ----
    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def url_template(self) -> str:
        return self.base_url + "/bot{token}/{method}"

    # ---- کنترل تست ----
    def push_message(self, chat_id, text: str, first_name: str = "علی", reply_to=None, last_name: str = "", username: str = "", language_code: str = "") -> None:
        with self._lock:
            self._next_id += 1
            sender = {"id": int(chat_id), "is_bot": False, "first_name": first_name}
            for key, value in (("last_name", last_name), ("username", username), ("language_code", language_code)):
                if value:
                    sender[key] = value
            message = {
                "message_id": self._next_id,
                "date": int(time.time()),
                "chat": {"id": int(chat_id), "type": "private", "first_name": first_name},
                "from": sender,
                "text": text,
            }
            if reply_to is not None:  # Reply روی پیامِ ربات (مسیریابیِ جوابِ مالک)
                message["reply_to_message"] = {
                    "message_id": int(reply_to), "date": int(time.time()),
                    "chat": {"id": int(chat_id), "type": "private"}, "from": {"id": 1, "is_bot": True, "first_name": "bot"}, "text": "x",
                }
            self._updates.append({"update_id": self._next_id, "message": message})

    def push_media(self, chat_id, kind: str = "photo", caption: str = "", first_name: str = "علی") -> None:
        """پیامِ غیرمتنی (عکس/فایل/صدا) با کپشنِ اختیاری — مثل «عکسِ رسید»."""
        payloads = {
            "photo": {"photo": [{"file_id": "f1", "file_unique_id": "u1", "width": 10, "height": 10}]},
            "document": {"document": {"file_id": "f2", "file_unique_id": "u2"}},
            "voice": {"voice": {"file_id": "f3", "file_unique_id": "u3", "duration": 3}},
        }
        with self._lock:
            self._next_id += 1
            message = {
                "message_id": self._next_id,
                "date": int(time.time()),
                "chat": {"id": int(chat_id), "type": "private", "first_name": first_name},
                "from": {"id": int(chat_id), "is_bot": False, "first_name": first_name},
                **payloads[kind],
            }
            if caption:
                message["caption"] = caption
            self._updates.append({"update_id": self._next_id, "message": message})

    def push_callback_query(self, chat_id, data: str, message_id: int = 1, first_name: str = "علی") -> str:
        """کلیکِ دکمه‌ی شیشه‌ای روی پیامِ ``message_id``؛ شناسه‌ی callback رو برمی‌گردونه."""
        with self._lock:
            self._next_id += 1
            cb_id = f"cb{self._next_id}"
            self._updates.append(
                {
                    "update_id": self._next_id,
                    "callback_query": {
                        "id": cb_id,
                        "from": {"id": int(chat_id), "is_bot": False, "first_name": first_name, "language_code": "fa"},
                        "chat_instance": "ci1",
                        "message": {
                            "message_id": int(message_id),
                            "date": int(time.time()),
                            "chat": {"id": int(chat_id), "type": "private", "first_name": first_name},
                            "text": "x",
                        },
                        "data": data,
                    },
                }
            )
        return cb_id

    def push_contact(self, chat_id, phone: str, first_name: str = "علی") -> None:
        with self._lock:
            self._next_id += 1
            self._updates.append(
                {
                    "update_id": self._next_id,
                    "message": {
                        "message_id": self._next_id,
                        "date": int(time.time()),
                        "chat": {"id": int(chat_id), "type": "private", "first_name": first_name},
                        "from": {"id": int(chat_id), "is_bot": False, "first_name": first_name},
                        "contact": {"phone_number": phone, "first_name": first_name, "user_id": int(chat_id)},
                    },
                }
            )

    def last_message(self, chat_id) -> dict:
        rows = [m for m in self.sent if m["chat_id"] == str(chat_id)]
        return rows[-1] if rows else {}

    def callback_datas(self, chat_id) -> list:
        """callback_dataهای کیبوردِ شیشه‌ایِ *تازه‌ترین رویدادِ خروجی* (ارسال یا ویرایش) برای این چت."""
        events = [e for e in self.sent + self.edits + self.markup_edits if e["chat_id"] == str(chat_id)]
        if not events:
            return []
        markup = max(events, key=lambda e: e["seq"]).get("reply_markup")
        return [b.get("callback_data") for row in (markup or {}).get("inline_keyboard", []) for b in row if b.get("callback_data")]

    def sent_to(self, chat_id) -> list:
        return [m["text"] for m in self.sent if m["chat_id"] == str(chat_id)]

    def buttons_to(self, chat_id) -> list:
        """همه‌ی دکمه‌های (برچسب, url) که به این چت رفته."""
        out = []
        for m in self.sent:
            if m["chat_id"] == str(chat_id) and m.get("reply_markup"):
                for row in m["reply_markup"].get("inline_keyboard", []):
                    out.extend((b.get("text"), b.get("url")) for b in row)
        return out

    def push_pre_checkout_query(self, query_id, user_id, invoice_payload: str, total_amount: int) -> None:
        with self._lock:
            self._next_id += 1
            self._updates.append(
                {
                    "update_id": self._next_id,
                    "pre_checkout_query": {
                        "id": str(query_id),
                        "from": {"id": int(user_id)},
                        "invoice_payload": invoice_payload,
                        "total_amount": total_amount,
                        "currency": "IRR",
                    },
                }
            )

    def push_successful_payment(self, chat_id, invoice_payload: str, total_amount: int, provider_charge_id: str) -> None:
        with self._lock:
            self._next_id += 1
            self._updates.append(
                {
                    "update_id": self._next_id,
                    "message": {
                        "chat": {"id": int(chat_id)},
                        "successful_payment": {
                            "currency": "IRR",
                            "total_amount": total_amount,
                            "invoice_payload": invoice_payload,
                            "telegram_payment_charge_id": f"tg_{provider_charge_id}",
                            "provider_payment_charge_id": provider_charge_id,
                        },
                    },
                }
            )

    # ---- سرور ----
    @staticmethod
    def _ok(result):
        return web.json_response({"ok": True, "result": result})

    @staticmethod
    def _markup(raw):
        if isinstance(raw, str):  # aiogram فرم می‌فرسته و reply_markup رو JSON-رشته‌ای می‌ده
            try:
                return json.loads(raw)
            except ValueError:
                return None
        return raw

    def _bad_button(self, markup) -> bool:
        if not (self.reject_tel_buttons and isinstance(markup, dict)):
            return False
        for row in markup.get("inline_keyboard", []):
            for b in row:
                url = str(b.get("url") or "").lower()
                if url.startswith(("tel:", "javascript:")):
                    return True
        return False

    @staticmethod
    def _err(status: int, description: str):
        return web.json_response({"ok": False, "error_code": status, "description": description}, status=status)

    @staticmethod
    async def _params(request) -> dict:
        if "json" in (request.content_type or ""):
            try:
                return await request.json()
            except Exception:  # noqa: BLE001
                return {}
        return dict(await request.post())

    async def _handle(self, request):
        method = request.match_info["method"]
        self.calls.append(method)
        if self.mode == "html_502":
            return web.Response(status=502, text="<html>Bad Gateway</html>", content_type="text/html")
        if self.mode == "unauthorized":
            return self._err(401, "Unauthorized")
        params = await self._params(request)

        if method == "getMe":
            return self._ok({"id": 123456, "is_bot": True, "first_name": "Shop Bot", "username": self.username})

        if method == "getWebhookInfo":  # N10: عیب‌یابِ «تداخلِ webhook»
            return self._ok({"url": "https://example.com/hook" if self.mode == "webhook_conflict" else "", "has_custom_certificate": False, "pending_update_count": 0})

        if method == "getChatMember":
            channel, user = str(params.get("chat_id")), str(params.get("user_id"))
            self.chat_member_calls.append({"chat_id": channel, "user_id": user})
            if self.chat_member_delay:
                await asyncio.sleep(self.chat_member_delay)
            if self.chat_member_mode == "no_chat":
                return self._err(400, "Bad Request: chat not found")
            if self.chat_member_mode == "not_admin":
                return self._err(403, "Forbidden: bot is not a member of the channel chat")
            if self.chat_member_mode == "flood":
                return web.json_response({"ok": False, "error_code": 429, "description": "Too Many Requests: retry after 1", "parameters": {"retry_after": 1}}, status=429)
            if self.chat_member_mode == "garbage":
                return self._ok({"nothing": "useful"})
            status = self.member_status.get((channel, user), self.member_status.get(channel, self.member_default))
            result = {"status": status, "user": {"id": int(user) if user.lstrip("-").isdigit() else 0, "is_bot": False, "first_name": "u"}}
            # شکلِ کاملِ واقعی (مدل‌های aiogram همه‌ی فیلدهای الزامی را سخت‌گیرانه اعتبارسنجی می‌کنند)
            if status == "creator":
                result["is_anonymous"] = False
            elif status == "administrator":
                result.update({k: False for k in (
                    "can_be_edited", "is_anonymous", "can_manage_chat", "can_delete_messages", "can_manage_video_chats", "can_restrict_members",
                    "can_promote_members", "can_change_info", "can_invite_users", "can_post_stories", "can_edit_stories", "can_delete_stories",
                    "can_send_welcome_messages")})
            elif status == "restricted":
                result.update({k: False for k in (
                    "can_send_messages", "can_send_audios", "can_send_documents", "can_send_photos", "can_send_videos", "can_send_video_notes",
                    "can_send_voice_notes", "can_send_polls", "can_send_other_messages", "can_add_web_page_previews", "can_react_to_messages",
                    "can_edit_tag", "can_change_info", "can_invite_users", "can_pin_messages", "can_manage_topics")})
                result.update({"until_date": 0, "is_member": bool(self.member_status.get((channel, user, "is_member"), True))})
            elif status == "kicked":
                result["until_date"] = 0
            return self._ok(result)

        if method == "getUpdates":
            if self.mode == "conflict":
                return self._err(409, "Conflict: terminated by other getUpdates request; make sure that only one bot instance is running")
            if self.mode == "webhook_conflict":
                return self._err(409, "Conflict: can't use getUpdates method while webhook is active; use deleteWebhook to delete the webhook first")
            offset = int(params.get("offset") or 0)
            with self._lock:
                self._updates = [u for u in self._updates if u["update_id"] >= offset]
                pending = list(self._updates)
            if not pending:
                await asyncio.sleep(0.15)  # شبیه‌سازی long-poll
                with self._lock:
                    pending = [u for u in self._updates if u["update_id"] >= offset]
            return self._ok(pending)

        if method in ("setMyShortDescription", "getMyShortDescription"):
            if self.short_description_mode == "unsupported":
                return self._err(404, "Not Found")
            if self.short_description_mode == "flood":
                return web.json_response(
                    {"ok": False, "error_code": 429, "description": "Too Many Requests: retry after 1", "parameters": {"retry_after": 1}}, status=429
                )
            if self.short_description_mode == "error":
                return self._err(500, "Internal Server Error")
            code = str(params.get("language_code") or "")
            if method == "getMyShortDescription":
                # مثلِ تلگرام: زبانِ بدونِ توضیحِ جدا همان پیش‌فرض را می‌گیرد
                text = self.short_descriptions.get(code, self.short_descriptions.get("", ""))
                return self._ok({"short_description": text})
            text = str(params.get("short_description") or "")
            if len(text.encode("utf-16-le")) // 2 > self.short_description_max:
                return self._err(400, "Bad Request: short description is too long")
            self.short_description_sets.append((code, text))
            if text:
                self.short_descriptions[code] = text
            else:
                self.short_descriptions.pop(code, None)
            return self._ok(True)

        if method == "sendInvoice":
            self.invoices.append(params)
            if self.invoice_mode == "error":
                return self._err(400, "Bad Request: invalid provider_token")
            return self._ok({"message_id": len(self.invoices)})

        if method == "answerPreCheckoutQuery":
            self.pre_checkout_answers.append(params)
            return self._ok(True)

        if method == "inquireTransaction":
            self.inquired_transactions.append(params.get("transaction_id"))
            return self._ok({"status": self.transaction_status, "transaction_id": params.get("transaction_id")})

        if method in ("sendMessage", "sendPhoto", "sendDocument", "sendContact"):
            if method == "sendDocument" and self.reject_documents:
                return self._err(500, "Internal Server Error")
            chat_id = params.get("chat_id")
            failure = self.send_failures.get(str(chat_id))
            if failure:
                self.send_log.append((str(chat_id), f"fail:{failure[0]}"))
                return self._err(failure[0], failure[1])
            if self.flood_sends > 0:
                self.flood_sends -= 1
                self.send_log.append((str(chat_id), "fail:429"))
                retry = self.flood_retry_after
                return web.json_response(
                    {"ok": False, "error_code": 429, "description": f"Too Many Requests: retry after {retry}", "parameters": {"retry_after": retry}}, status=429
                )
            self.send_log.append((str(chat_id), "ok"))
            text = params.get("text") if method == "sendMessage" else (params.get("caption") or "")
            markup = self._markup(params.get("reply_markup"))
            if self.reject_markup and markup:
                return self._err(400, "Bad Request: can't parse reply markup")
            bad = self._bad_button(markup)
            if bad:
                return self._err(400, "Bad Request: BUTTON_URL_INVALID")
            self._seq += 1
            entry = {"chat_id": str(chat_id), "text": text, "reply_markup": markup, "kind": method, "message_id": len(self.sent) + 1, "seq": self._seq}
            if method == "sendDocument":
                doc = params.get("document")
                if isinstance(doc, str) and doc.startswith("attach://"):  # aiogram: فایل زیرِ کلیدِ جدا می‌آید
                    doc = params.get(doc[len("attach://"):])
                entry["document"] = {"filename": getattr(doc, "filename", ""), "size": len(doc.file.read()) if hasattr(doc, "file") else 0}
            if method == "sendContact":
                entry["contact"] = {"phone_number": params.get("phone_number"), "first_name": params.get("first_name")}
                entry["text"] = f"[contact] {params.get('phone_number')}"
            self.sent.append(entry)
            return self._ok(
                {"message_id": entry["message_id"], "date": int(time.time()), "chat": {"id": int(chat_id), "type": "private"}, "text": entry["text"]}
            )

        if method == "editMessageText":
            markup = self._markup(params.get("reply_markup"))
            if self.edit_mode == "no_text":
                return self._err(400, "Bad Request: there is no text in the message to edit")
            if self.edit_mode == "not_modified":
                return self._err(400, "Bad Request: message is not modified: specified new message content and reply markup are exactly the same")
            if self.reject_markup and markup:
                return self._err(400, "Bad Request: can't parse reply markup")
            if self._bad_button(markup):
                return self._err(400, "Bad Request: BUTTON_URL_INVALID")
            self._seq += 1
            self.edits.append({"chat_id": str(params.get("chat_id")), "message_id": params.get("message_id"), "text": params.get("text"), "reply_markup": markup, "seq": self._seq})
            return self._ok({"message_id": int(params.get("message_id") or 0), "date": int(time.time()), "chat": {"id": int(params.get("chat_id") or 0), "type": "private"}, "text": params.get("text")})

        if method == "editMessageReplyMarkup":
            markup = self._markup(params.get("reply_markup"))
            self._seq += 1
            self.markup_edits.append({"chat_id": str(params.get("chat_id")), "message_id": params.get("message_id"), "reply_markup": markup, "seq": self._seq})
            return self._ok(True)

        if method == "answerCallbackQuery":
            self.callback_answers.append(params)
            return self._ok(True)

        if method == "deleteMessage":
            self.deleted.append({"chat_id": str(params.get("chat_id")), "message_id": params.get("message_id")})
            return self._ok(True)
        return self._ok(True)

    def start(self) -> "FakeBotApiServer":
        ready = threading.Event()

        def run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            app = web.Application()
            app.router.add_post("/bot{token}/{method}", self._handle)
            runner = web.AppRunner(app, shutdown_timeout=0.5, access_log=None)
            loop.run_until_complete(runner.setup())
            loop.run_until_complete(web.TCPSite(runner, "127.0.0.1", self.port).start())
            self._runner = runner
            ready.set()
            loop.run_forever()
            loop.run_until_complete(runner.cleanup())
            loop.close()

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        assert ready.wait(5), "سرور جعلی بالا نیومد"
        return self

    def stop(self) -> None:
        if self._loop is not None and self._thread is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)
            self._loop = None
            self._thread = None
