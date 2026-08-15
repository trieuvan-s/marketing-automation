"""NẠP LẠI SHEET TỪ STORE — lệnh vận hành chính khi Sheet hiển thị sai/lệch.

    python scripts/sync_store_sheet.py                # đồng bộ 2 chiều (mặc định)
    python scripts/sync_store_sheet.py --from-store   # CHỈ 1 chiều: store -> Sheet

HAI CHẾ ĐỘ, CHỌN ĐÚNG CÁI (TASK-035 -- đọc kỹ, ý nghĩa 2 chế độ đã đổi so với
trước: KHÔNG còn CAS đoán ghi đè, ranh giới giờ RÕ theo TÊN HÀM):

  (mặc định) 2 CHIỀU — ingest thao tác người TRƯỚC, rồi `render_*_to_sheet()`
    (`store/sync_service.py`) CHỈ ghi lại dải cột MÁY-SỞ-HỮU cho dòng đã tồn
    tại (KHÔNG BAO GIỜ đụng Duyệt Context/Content/Public, Notes, Output Type,
    Social Link, Posting Status, "Người thực hiện"); dòng CHƯA có trên Sheet
    (topic mới, hoặc dòng vừa bị xoá tay lẻ tẻ) được thêm mới đầy đủ. Dùng cho
    vận hành THƯỜNG NGÀY. KHÔNG tự sắp lại/ẩn dòng cũ theo display_days.

  --from-store — 1 CHIỀU, BỎ QUA ingest, `restore_*_from_store()` dựng lại
    TOÀN BỘ tab ĐÚNG y như store (kể cả cột người, sắp lại thứ tự, áp
    display_days). Dùng khi SHEET ĐANG SAI (ô bị sửa tay nhầm mà KHÔNG phải
    thao tác hợp lệ, dòng thừa do bug cũ, định dạng loạn, cần sắp lại thứ tự/
    ẩn dòng cũ) và bạn muốn store thắng TUYỆT ĐỐI, kể cả với dòng ĐÃ TỒN TẠI.
    ⚠️ VỨT BỎ mọi thay đổi trên Sheet chưa kịp ingest (vd vừa bấm APPROVE 5
    giây trước) — ĐIỂM KHÁC BIỆT DUY NHẤT nhưng quan trọng giữa 2 chế độ.
    Không chắc thì dùng mặc định.

Cả hai đều idempotent: chạy lại nhiều lần cho cùng kết quả.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))
# SỬA LỖI THẬT (2026-08-04, xem run_scheduler.py cùng lý do) -- ép cwd =
# REPO_ROOT NGAY ĐẦU để chạy đúng bất kể ai/gì khởi động tiến trình.
os.chdir(REPO_ROOT)

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

from twmkt.config import load_settings  # noqa: E402
from twmkt.sheets_board import SheetsBoard  # noqa: E402

from store.sync_service import (  # noqa: E402
    restore_content_from_store, restore_context_from_store, sync_all,
)


def _open_board(settings) -> SheetsBoard:
    sheet_id = (os.environ.get("TWMKT_SHEET_ID") or settings.get("sheets.spreadsheet_id") or "").strip()
    creds = (os.environ.get("TWMKT_SHEETS_CREDS") or settings.get("sheets.creds_path") or "").strip()
    if not sheet_id or not creds:
        raise SystemExit("Thiếu sheets.spreadsheet_id/creds_path (settings.yaml hoặc ENV).")
    return SheetsBoard(spreadsheet_id=sheet_id, creds_path=creds)


def main(argv: list[str] | None = None) -> dict:
    argv = sys.argv[1:] if argv is None else argv
    from_store_only = "--from-store" in argv

    settings = load_settings()
    board = _open_board(settings)

    if from_store_only:
        print("[reload] CHỈ 1 CHIỀU store -> Sheet (bỏ qua ingest — mọi thay đổi "
              "trên Sheet chưa ingest sẽ bị ghi đè).")
        # TASK-035 -- ĐÂY CHÍNH LÀ lệnh phục hồi Bước 5.4 "Sheet đang sai,
        # muốn store thắng tuyệt đối": restore_*_from_store() là NƠI DUY NHẤT
        # còn ghi cả cột người-sở-hữu (dựng lại toàn bộ tab, sắp lại thứ tự,
        # áp display_days) -- render_*_to_sheet() (dùng ở nhánh mặc định bên
        # dưới) không còn làm việc này nữa, xem docstring store/sync_service.py.
        n_ctx = restore_context_from_store(board)
        n_content = restore_content_from_store(board)
        board.set_machine_columns_hidden(hidden=True)   # giữ cột máy-ghi luôn ẩn sau khi dựng lại
        print(f"[reload] Đã dựng lại: CONTEXT={n_ctx} dòng, CONTENT={n_content} dòng.")
        return {"ingested_context": 0, "ingested_content": 0,
                "rendered_context_rows": n_ctx, "rendered_content_rows": n_content}

    result = sync_all(board)
    board.set_machine_columns_hidden(hidden=True)
    print(f"[sync_all] ingest: CONTEXT={result['ingested_context']} lần ghi, "
         f"CONTENT={result['ingested_content']} lần ghi | "
         f"render: CONTEXT={result['rendered_context_rows']} dòng, "
         f"CONTENT={result['rendered_content_rows']} dòng")
    return result


if __name__ == "__main__":
    main()
