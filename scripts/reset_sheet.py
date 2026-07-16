"""Sheet UI cleanup Phase 2 — công cụ RESET SẠCH tái sử dụng cho tương lai (vd
crawl lại từ đầu, đổi giai đoạn dữ liệu). KHÔNG chạy tự động ở bất kỳ pipeline
nào — CHỈ chạy tay khi người vận hành chủ động cần reset.

Xoá TOÀN BỘ dòng dữ liệu (CONTEXT + CONTENT) + un-merge MỌI vùng còn sót (dọn
tàn dư mergeCells cũ, TRƯỚC Sheet UI cleanup Phase 1) — GIỮ NGUYÊN mọi tab,
mọi cột, header, định dạng cột (dropdown/conditional format của format_board()
KHÔNG bị đụng, vì đây là values-clear, không phải resize/xoá dòng). KHÔNG đụng
SOURCES/SETTINGS/TAXONOMY/PROMPTS/README (tab CẤU HÌNH, người vận hành tự
quản — xem SheetsBoard._RESET_DATA_TABS).

BẮT BUỘC `--dry-run` HOẶC `--confirm` — không cờ nào -> báo lỗi, không đoán ý
định. `--dry-run` chỉ ĐỌC (fetch_sheet_metadata + get_all_values), KHÔNG ghi
gì. `--confirm` chạy THẬT — KHÔNG THỂ HOÀN TÁC, không backup tự động (Phase 2
này KHÔNG xây cơ chế backup — xem Phase 5, sheet vận hành riêng cho archive).

Chạy:
    python scripts/reset_sheet.py --dry-run      # xem trước, AN TOÀN, không đụng gì
    python scripts/reset_sheet.py --confirm       # chạy THẬT, KHÔNG THỂ HOÀN TÁC
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


def main(*, dry_run: bool, confirm: bool) -> dict[str, dict[str, int]]:
    if dry_run == confirm:   # cả 2 cùng True HOẶC cùng False đều sai — bắt buộc CHỌN ĐÚNG 1
        raise SystemExit("Phải chỉ rõ ĐÚNG 1 trong hai: --dry-run (xem trước, an toàn) "
                         "hoặc --confirm (chạy THẬT, không thể hoàn tác).")
    settings = load_settings()
    board = _open_board(settings)

    if dry_run:
        plan = board.reset_plan()
        print("== DRY-RUN — CHƯA đụng gì, chỉ đọc ==")
        for tab, info in plan.items():
            print(f"[{tab}] sẽ xoá {info['rows']} dòng dữ liệu | un-merge {info['merge_ranges']} vùng")
        print("\nSchema (tab/cột/header/định dạng cột) sẽ GIỮ NGUYÊN.")
        print("Chạy lại với --confirm để thực thi THẬT (KHÔNG THỂ HOÀN TÁC).")
        return plan

    print("[CẢNH BÁO] --confirm: XOÁ THẬT dòng dữ liệu CONTEXT + CONTENT + un-merge mọi vùng "
         "— KHÔNG THỂ HOÀN TÁC, không có backup tự động.")
    result = board.reset_all()
    print("== ĐÃ RESET ==")
    for tab, info in result.items():
        print(f"[{tab}] đã xoá {info['rows']} dòng dữ liệu | đã un-merge {info['merge_ranges']} vùng")
    print("\nSchema (tab/cột/header/định dạng cột) GIỮ NGUYÊN.")
    return result


def _parse_args(argv: list[str]):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="Chỉ in ra sẽ xoá/un-merge bao nhiêu — KHÔNG đụng gì.")
    ap.add_argument("--confirm", action="store_true",
                    help="Chạy THẬT — KHÔNG THỂ HOÀN TÁC.")
    return ap.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    main(dry_run=args.dry_run, confirm=args.confirm)
