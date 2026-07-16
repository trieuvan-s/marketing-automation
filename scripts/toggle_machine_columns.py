"""Sheet UI cleanup Phase 4 — ẩn/hiện cột MÁY-SỞ-HỮU (TopicKey ở CONTEXT+
CONTENT, Facts ở CONTENT) — người vận hành không nên sửa tay các cột này (xem
sheets_board._MACHINE_OWNED_COLS). CHỈ đổi hiển thị (hideColumn), KHÔNG chuyển
tab/xoá dữ liệu — API vẫn đọc/ghi đủ mọi cột dù ẩn hay hiện.

Sheet UI cleanup Phase 6b: AssetPath ĐÃ RÚT khỏi nhóm này (giờ HIỂN THỊ, khoá
bằng Protected Range riêng — xem scripts/protect_asset_path.py).

Mặc định (không cờ): ẨN cột máy-sở-hữu.
`--show-machine-cols`: HIỆN lại (soi khi cần debug/audit).

Chạy:
    python scripts/toggle_machine_columns.py                    # ẩn (mặc định)
    python scripts/toggle_machine_columns.py --show-machine-cols  # hiện lại
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

import os  # noqa: E402

from twmkt.config import load_settings  # noqa: E402
from twmkt.sheets_board import SheetsBoard  # noqa: E402


def _open_board(settings) -> SheetsBoard:
    sheet_id = (os.environ.get("TWMKT_SHEET_ID") or settings.get("sheets.spreadsheet_id") or "").strip()
    creds = (os.environ.get("TWMKT_SHEETS_CREDS") or settings.get("sheets.creds_path") or "").strip()
    if not sheet_id or not creds:
        raise SystemExit("Thiếu sheets.spreadsheet_id/creds_path (settings.yaml hoặc ENV).")
    return SheetsBoard(spreadsheet_id=sheet_id, creds_path=creds)


def main(*, show: bool = False) -> int:
    settings = load_settings()
    board = _open_board(settings)
    n = board.set_machine_columns_hidden(hidden=not show)
    verb = "Hiện lại" if show else "Đã ẩn"
    print(f"{verb} {n} cột máy-sở-hữu (TopicKey/Facts).")
    return n


def _parse_args(argv: list[str]):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--show-machine-cols", action="store_true",
                    help="Hiện lại cột máy-sở-hữu thay vì ẩn (mặc định là ẩn).")
    return ap.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    main(show=args.show_machine_cols)
