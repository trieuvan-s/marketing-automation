"""Sheet UI cleanup Phase 6c — local static file server phục vụ thư mục
output asset, để link AssetPath trên Sheet (HYPERLINK http://127.0.0.1:PORT/
...) BẤM MỞ ĐƯỢC. Thay cho `file://` — Google Sheets chạy qua HTTPS, trình
duyệt CHẶN điều hướng từ trang HTTPS tới `file://` cục bộ (xác nhận THẬT qua
test Phase 6b: HYPERLINK(file://...) không kích hoạt link nào trên Sheet
sống) — `http://` là scheme web-an-toàn nên hoạt động bình thường.

CHỈ bind 127.0.0.1 — KHÔNG BAO GIỜ 0.0.0.0 (không expose file cục bộ ra
mạng, chỉ phục vụ trình duyệt trên CHÍNH máy đã render, đúng giới hạn "chỉ mở
được trên máy render" đã ghi ở docs/HANDOFF.md)."""
from __future__ import annotations

import functools
import http.server
from pathlib import Path
from urllib.parse import quote

DEFAULT_PORT = 8899
DEFAULT_HOST = "127.0.0.1"


def asset_url(path: Path, *, root: Path, host: str = DEFAULT_HOST,
              port: int = DEFAULT_PORT) -> str:
    """URL `http://host:port/...` tới 1 file NẰM TRONG `root` (thư mục server
    phục vụ) — `path` PHẢI nằm trong `root`, raise ValueError nếu không (xem
    Path.relative_to). Mỗi phần đường dẫn được `quote()` riêng (không quote
    dấu "/") để an toàn với ký tự Unicode/khoảng trắng trong tên file."""
    rel = path.resolve().relative_to(root.resolve())
    segments = "/".join(quote(part) for part in rel.parts)
    return f"http://{host}:{port}/{segments}"


def build_server(root: Path, *, host: str = DEFAULT_HOST,
                 port: int = DEFAULT_PORT) -> http.server.ThreadingHTTPServer:
    """Dựng (chưa serve_forever()) 1 ThreadingHTTPServer phục vụ TĨNH thư mục
    `root` — `port=0` để hệ điều hành tự chọn cổng trống (dùng trong test,
    tra `server.server_address[1]` sau khi dựng)."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    return http.server.ThreadingHTTPServer((host, port), handler)
