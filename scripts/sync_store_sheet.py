"""CLI mỏng gọi store/sync_service.py::sync_all() trên Sheet THẬT (production
spreadsheet, settings.yaml: sheets.spreadsheet_id) -- ingest thao tác người
TRƯỚC, render lại CẢ 2 tab (CONTEXT/CONTENT) từ store SAU. Đây CHÍNH LÀ lệnh
"phục hồi khi xoá nhầm" (Bước 5.4) lẫn đồng bộ vận hành bình thường -- store
append-only nên chạy lại KHÔNG mất dữ liệu, idempotent.

Chạy:
    python scripts/sync_store_sheet.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

from twmkt.config import load_settings  # noqa: E402
from twmkt.sheets_board import SheetsBoard  # noqa: E402

from store.sync_service import sync_all  # noqa: E402


def _open_board(settings) -> SheetsBoard:
    sheet_id = (os.environ.get("TWMKT_SHEET_ID") or settings.get("sheets.spreadsheet_id") or "").strip()
    creds = (os.environ.get("TWMKT_SHEETS_CREDS") or settings.get("sheets.creds_path") or "").strip()
    if not sheet_id or not creds:
        raise SystemExit("Thiếu sheets.spreadsheet_id/creds_path (settings.yaml hoặc ENV).")
    return SheetsBoard(spreadsheet_id=sheet_id, creds_path=creds)


def main() -> dict:
    settings = load_settings()
    board = _open_board(settings)
    result = sync_all(board)
    print(f"[sync_all] ingest: CONTEXT={result['ingested_context']} lần ghi, "
         f"CONTENT={result['ingested_content']} lần ghi | "
         f"render: CONTEXT={result['rendered_context_rows']} dòng, "
         f"CONTENT={result['rendered_content_rows']} dòng")
    return result


if __name__ == "__main__":
    main()
