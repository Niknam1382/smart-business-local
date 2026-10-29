import threading

from app.core.conversations import ConversationStore


def make_store(tmp_path):
    return ConversationStore(db_path=tmp_path / "test.db")


def test_new_conversation_defaults(tmp_path):
    store = make_store(tmp_path)
    store.ensure_conversation("telegram", "111", "علی")
    assert store.is_blocked("telegram", "111") is False
    assert store.is_memory_enabled("telegram", "111") is True
    # مکالمه‌ای که وجود نداره: بلاک نیست و حافظه پیش‌فرض روشنه
    assert store.is_blocked("telegram", "nope") is False
    assert store.is_memory_enabled("telegram", "nope") is True


def test_history_order_and_limit(tmp_path):
    store = make_store(tmp_path)
    store.ensure_conversation("telegram", "1", "علی")
    for i in range(6):
        store.add_message("telegram", "1", "user" if i % 2 == 0 else "assistant", f"پیام {i}")
    history = store.get_history("telegram", "1", limit=4)
    assert [m.content for m in history] == ["پیام 2", "پیام 3", "پیام 4", "پیام 5"]  # آخرین‌ها، به ترتیب زمانی
    assert history[0].role == "user" and history[1].role == "assistant"


def test_block_and_memory_toggle(tmp_path):
    store = make_store(tmp_path)
    store.ensure_conversation("bale", "9", "شرکت")
    store.set_blocked("bale", "9", True)
    store.set_memory_enabled("bale", "9", False)
    assert store.is_blocked("bale", "9") is True
    assert store.is_memory_enabled("bale", "9") is False
    store.set_blocked("bale", "9", False)
    assert store.is_blocked("bale", "9") is False


def test_display_name_not_overwritten_by_empty(tmp_path):
    store = make_store(tmp_path)
    store.ensure_conversation("telegram", "1", "علی")
    store.ensure_conversation("telegram", "1", "")
    assert store.list_conversations()[0].display_name == "علی"
    store.ensure_conversation("telegram", "1", "علی رضایی")
    assert store.list_conversations()[0].display_name == "علی رضایی"


def test_list_conversations_filter_and_preview(tmp_path):
    store = make_store(tmp_path)
    store.ensure_conversation("telegram", "1", "الف")
    store.ensure_conversation("bale", "2", "ب")
    store.add_message("bale", "2", "user", "پیام بله")
    all_convs = store.list_conversations()
    assert {c.platform for c in all_convs} == {"telegram", "bale"}
    previews = {c.chat_id: c.last_message_preview for c in all_convs}
    assert previews == {"1": "", "2": "پیام بله"}
    assert [c.chat_id for c in store.list_conversations(platform="telegram")] == ["1"]


def test_same_chat_id_on_two_platforms_is_independent(tmp_path):
    store = make_store(tmp_path)
    store.ensure_conversation("telegram", "5", "الف")
    store.ensure_conversation("bale", "5", "ب")
    store.set_blocked("telegram", "5", True)
    assert store.is_blocked("bale", "5") is False


def test_concurrent_read_write(tmp_path):
    store = make_store(tmp_path)
    store.ensure_conversation("telegram", "1", "علی")
    errors = []

    def writer():
        try:
            for i in range(60):
                store.add_message("telegram", "1", "user", f"پیام {i}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def reader():
        try:
            for _ in range(60):
                store.get_history("telegram", "1", limit=5)
                store.list_conversations()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer), threading.Thread(target=reader), threading.Thread(target=reader)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert len(store.get_messages("telegram", "1", limit=1000)) == 60


def test_list_conversations_orders_by_last_message_not_coarse_timestamp(tmp_path):
    """updated_at فقط دقت ثانیه داره؛ چند مکالمه که توی یه ثانیه فعالیت
    می‌کنن باید هنوزم به ترتیب واقعیِ آخرین پیام مرتب بشن (بر اساس id پیام،
    نه رشته‌ی زمان)."""
    store = make_store(tmp_path)
    store.ensure_conversation("telegram", "1", "علی")
    store.add_message("telegram", "1", "user", "سلام")
    store.add_message("telegram", "1", "assistant", "سلام علی")
    store.ensure_conversation("bale", "2", "سارا")
    store.add_message("bale", "2", "user", "پیام جدیدتر")  # آخرین پیام واقعی

    assert [c.chat_id for c in store.list_conversations()] == ["2", "1"]

    store.add_message("telegram", "1", "user", "الان من جدیدترم")
    assert [c.chat_id for c in store.list_conversations()] == ["1", "2"]


def test_conversation_with_no_messages_sorts_after_ones_with_messages(tmp_path):
    store = make_store(tmp_path)
    store.ensure_conversation("telegram", "1", "بدون پیام")  # مثلاً کاربر بلاک‌شده‌ای که پیامش ذخیره نشد
    store.ensure_conversation("telegram", "2", "با پیام")
    store.add_message("telegram", "2", "user", "سلام")
    assert [c.chat_id for c in store.list_conversations()] == ["2", "1"]


def test_time_since_last_message(tmp_path):
    store = make_store(tmp_path)
    assert store.time_since_last_message_seconds("telegram", "1") is None  # هیچ پیامی نیست
    store.ensure_conversation("telegram", "1", "علی")
    store.add_message("telegram", "1", "user", "سلام")
    idle = store.time_since_last_message_seconds("telegram", "1")
    assert idle is not None and 0 <= idle < 5  # همین الان نوشته شد


def test_clear_history_keeps_conversation_settings(tmp_path):
    store = make_store(tmp_path)
    store.ensure_conversation("telegram", "1", "علی")
    store.add_message("telegram", "1", "user", "سلام")
    store.add_message("telegram", "1", "assistant", "سلام علی")
    store.set_memory_enabled("telegram", "1", False)
    store.set_blocked("telegram", "1", True)

    store.clear_history("telegram", "1")

    assert store.get_messages("telegram", "1") == []
    assert store.get_history("telegram", "1") == []
    # تنظیمات خودِ مکالمه (حافظه/بلاک) نباید پاک بشن، فقط پیام‌ها
    assert store.is_memory_enabled("telegram", "1") is False
    assert store.is_blocked("telegram", "1") is True
    convs = store.list_conversations()
    assert len(convs) == 1 and convs[0].display_name == "علی"
