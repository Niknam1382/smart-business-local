"""جابه‌جاییِ امنِ فایلِ مدل بین پوشه‌ها (۱٫۲٫۰).

قرارداد: ``move_model`` فقط *کپیِ تأییدشده* می‌سازد (حجم + امضای GGUF + هشِ SHA-256 مبدأ و مقصد) و **هرگز مبدأ را پاک
نمی‌کند**؛ پاک‌کردنِ مبدأ کارِ جدایِ ``delete_source`` است که فقط بعد از اجازه‌ی صریحِ کاربر صدا زده می‌شود. نیمه‌کاره‌ماندن
(لغو، قطعِ برق، کمبودِ فضا) فقط یک ``.part`` به‌جا می‌گذارد که پاک می‌شود؛ مبدأ و مقصدِ قبلی سالم می‌مانند.
مسیرِ فاصله‌دار/فارسی و درایوِ دیگر پشتیبانی می‌شود. فقط stdlib.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
from pathlib import Path
from typing import Callable, Optional

CHUNK = 4 * 1024 * 1024
MARGIN_BYTES = 256 * 1024 * 1024
PART_SUFFIX = ".part"
GGUF_MAGIC = b"GGUF"

Progress = Callable[[int, int], None]


class MoveError(Exception):
    """``code``: not_found | not_gguf | not_writable | no_space | cancelled | verify | io"""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _is_gguf(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            return handle.read(4) == GGUF_MAGIC
    except OSError:
        return False


def _sha256(path: Path, cancel: Optional[threading.Event]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            if cancel is not None and cancel.is_set():
                raise MoveError("cancelled")
            digest.update(block)
    return digest.hexdigest()


def _writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".sbl-write-test"
        probe.write_bytes(b"x")
        probe.unlink()
        return True
    except OSError:
        return False


def move_model(src, dst_dir, *, cancel: Optional[threading.Event] = None, progress: Optional[Progress] = None) -> Path:
    """مدلِ ``src`` را در ``dst_dir`` کپیِ تأییدشده می‌کند و مسیرِ مقصد را برمی‌گرداند. مبدأ دست‌نخورده می‌ماند."""
    src, dst_dir = Path(src), Path(dst_dir)
    if not src.is_file() or src.is_symlink():
        raise MoveError("not_found", str(src))
    if not _is_gguf(src):
        raise MoveError("not_gguf", str(src))
    size = src.stat().st_size
    target = dst_dir / src.name
    try:
        if target.exists() and target.resolve() == src.resolve():
            return target  # همان فایل است؛ کاری لازم نیست
    except OSError:
        pass
    if not _writable(dst_dir):
        raise MoveError("not_writable", str(dst_dir))
    if target.exists() and target.stat().st_size == size and _is_gguf(target):
        if _sha256(target, cancel) == _sha256(src, cancel):
            return target  # قبلاً با همین محتوا آنجاست؛ دوباره کپی نمی‌کنیم
    try:
        free = shutil.disk_usage(dst_dir).free
    except OSError:
        free = None
    if free is not None and free < size + MARGIN_BYTES:
        raise MoveError("no_space", f"free={free} need={size + MARGIN_BYTES}")

    part = target.with_name(target.name + PART_SUFFIX)
    digest = hashlib.sha256()
    done = 0
    try:
        with open(src, "rb") as reader, open(part, "wb") as writer:
            for block in iter(lambda: reader.read(CHUNK), b""):
                if cancel is not None and cancel.is_set():
                    raise MoveError("cancelled")
                writer.write(block)
                digest.update(block)
                done += len(block)
                if progress is not None:
                    progress(done, size)
            writer.flush()
            os.fsync(writer.fileno())
        if part.stat().st_size != size or not _is_gguf(part):
            raise MoveError("verify", "size_or_magic")
        if _sha256(part, cancel) != digest.hexdigest():
            raise MoveError("verify", "sha256")
        os.replace(part, target)
        return target
    except MoveError:
        _silent_unlink(part)
        raise
    except OSError as exc:
        _silent_unlink(part)
        raise MoveError("io", str(exc)) from exc


def _silent_unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def delete_source(src) -> bool:
    """مبدأ را پاک می‌کند؛ **فقط** بعد از اجازه‌ی صریحِ کاربر صدا بزن. فقط یک فایلِ ``.gguf`` معمولی (نه پوشه/لینک)."""
    path = Path(src)
    if path.suffix.lower() != ".gguf" or not path.is_file() or path.is_symlink():
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False
