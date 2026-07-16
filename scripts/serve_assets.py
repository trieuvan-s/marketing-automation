"""Sheet UI cleanup Phase 6c — chạy local static file server (CHỈ 127.0.0.1,
KHÔNG expose ra mạng) phục vụ thư mục output asset, để link AssetPath trên
Sheet (HYPERLINK http://127.0.0.1:PORT/...) bấm mở được — thay cho `file://`
(bị trình duyệt chặn khi mở từ trang HTTPS như Google Sheets, xác nhận THẬT
Phase 6b).

Chạy nền khi cần mở link (Ctrl+C để dừng):
    python scripts/serve_assets.py                # cổng mặc định (settings.yaml hoặc 8899)
    python scripts/serve_assets.py --port 9000
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

from twmkt.asset_server import DEFAULT_PORT, build_server  # noqa: E402
from twmkt.config import data_path, load_settings  # noqa: E402


def main(*, port: int | None = None) -> None:
    settings = load_settings()
    root = data_path(settings.get("storage.output_dir", "output"), settings=settings)
    port = port if port is not None else int(settings.get("storage.asset_server_port", DEFAULT_PORT))
    server = build_server(root, port=port)
    print(f"Đang phục vụ {root} tại http://127.0.0.1:{port}/ (Ctrl+C để dừng)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã dừng server.")
    finally:
        server.server_close()


def _parse_args(argv: list[str]):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=None,
                    help="Cổng phục vụ (mặc định: storage.asset_server_port trong settings.yaml, hoặc 8899).")
    return ap.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    main(port=args.port)
