"""Sheet UI cleanup Phase 6b — khoá CỨNG cột AssetPath (CONTENT) bằng
Protected Range: CHỈ Service Account (client_email trong creds) + Owner Sheet
được ghi, người khác chỉ xem (xem sheets_board.SheetsBoard.
protect_asset_path_column()). Khác với TopicKey/Facts (chỉ ẨN qua
toggle_machine_columns.py) — AssetPath giờ HIỂN THỊ (Phase 6) nên cần khoá
RIÊNG thay vì ẩn.

Idempotent: chạy lại nhiều lần không tạo trùng protection.

Chạy:
    python scripts/protect_asset_path.py
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


def main() -> dict:
    settings = load_settings()
    board = _open_board(settings)
    result = board.protect_asset_path_column()
    if not result:
        print("Tab CONTENT thiếu cột AssetPath -> bỏ qua.")
    elif result.get("already_protected"):
        print(f"AssetPath đã được khoá từ trước (protectedRangeId="
             f"{result['protectedRangeId']}) -> không tạo trùng.")
    else:
        print("Đã tạo Protected Range mới cho cột AssetPath (CONTENT) — "
             "chỉ Service Account + Owner Sheet được ghi.")
    return result


if __name__ == "__main__":
    main()
