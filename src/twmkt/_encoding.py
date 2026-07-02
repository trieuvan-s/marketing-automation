"""Tiện ích nhỏ: đảm bảo stdout/stderr in được UTF-8 (tiếng Việt).

Windows mặc định dùng cp1252 cho console → in ký tự "ĐĂNG", "NHẬT KÝ"… sẽ
raise UnicodeEncodeError. Gọi `ensure_utf8_stdio()` ở các entry point offline
(demo, test runner) để chạy được trên mọi console mà không cần đặt PYTHONUTF8.
"""
from __future__ import annotations

import sys


def ensure_utf8_stdio() -> None:
    """Chuyển stdout/stderr sang UTF-8 nếu có thể (Python 3.7+, no-op nếu đã UTF-8)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # Stream không hỗ trợ reconfigure (đã bị redirect/bọc) → bỏ qua.
            pass
