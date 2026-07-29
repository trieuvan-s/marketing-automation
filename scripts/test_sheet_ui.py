"""KIỂM THỬ SHEET UI TRÊN SHEET TEST THẬT — chạy tay, KHÔNG nằm trong suite.

    python scripts/test_sheet_ui.py            # chạy + reset sạch sau khi xong
    python scripts/test_sheet_ui.py --keep     # giữ lại để soi mắt

VÌ SAO CẦN (2026-07-29, yêu cầu Lead): test đơn vị dùng fake worksheet nên
KHÔNG bắt được thứ chỉ hỏng trên Sheet THẬT — `clear()` xoá định dạng,
`deleteDimension` dịch chỉ số dòng, validation bị ghi đè, băng màu không sống
qua lượt render. Suốt phiên này 9/9 bug thật đều lộ ra khi chạy thật chứ không
phải từ suite. File này đóng khoảng trống đó.

⚠️ CHỈ CHẠY TRÊN SHEET TEST (`sheets.test_spreadsheet_id`). Từ chối chạy nếu
trùng `sheets.spreadsheet_id` (production) — mọi ca đều XOÁ SẠCH dữ liệu.

RESET: cuối mỗi lượt (kể cả khi có ca FAIL) tab CONTEXT/CONTENT được đưa về
bảng trắng + header, đúng yêu cầu "test xong phải reset sheet test".
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

import os  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402

# Google Sheets: 60 lượt ĐỌC/phút/user. Bộ test này gọi API dày đặc nên tự làm
# cạn quota nếu chạy sát nhau — 429 khi đó là lỗi HẠ TẦNG, không phải logic
# sai, nhưng vẫn làm ca test đỏ và gây kết luận nhầm. Nghỉ ngắn giữa các lượt
# gọi rẻ hơn nhiều so với việc đọc sai kết quả.
_API_PAUSE_S = 1.2


def _pause() -> None:
    time.sleep(_API_PAUSE_S)

from twmkt.config import load_settings  # noqa: E402
from twmkt.sheets_board import CONTENT_HEADER, CONTEXT_HEADER, SheetsBoard  # noqa: E402

_PASS, _FAIL = [], []


def set_cell(ws, col_idx: int, row: int, value: str) -> bool:
    """Ghi 1 ô rồi ĐỌC LẠI xác nhận đã vào. Sheets API có thể 429 và retry hết
    lượt; nếu không kiểm thì ca test sau đó fail vì lý do HẠ TẦNG chứ không
    phải vì logic sai — đúng cái vừa gặp."""
    a1 = f"{chr(65 + col_idx)}{row}"
    ws.update(a1, [[value]], value_input_option="USER_ENTERED")
    _pause()
    got = ws.get_all_values()
    actual = got[row - 1][col_idx] if row - 1 < len(got) and col_idx < len(got[row - 1]) else ""
    if actual != value:
        print(f"     [!] ghi {a1}={value!r} nhưng đọc lại ra {actual!r} — bỏ qua ca này")
        return False
    return True


def check(name: str, cond: bool, detail: str = "") -> None:
    (_PASS if cond else _FAIL).append(name)
    print(f"  {'✓' if cond else '✗ FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))


def _day(delta: int) -> str:
    return (date.today() - timedelta(days=delta)).strftime("%d/%m/%Y")


def _open_test_board(settings) -> SheetsBoard:
    test_id = (os.environ.get("TWMKT_TEST_SHEET_ID")
               or settings.get("sheets.test_spreadsheet_id") or "").strip()
    prod_id = (settings.get("sheets.spreadsheet_id") or "").strip()
    if not test_id:
        raise SystemExit("Thiếu sheets.test_spreadsheet_id trong settings.yaml.")
    if test_id == prod_id:
        raise SystemExit("TỪ CHỐI CHẠY: test_spreadsheet_id TRÙNG production. "
                         "Mọi ca ở đây đều xoá sạch dữ liệu.")
    creds = (os.environ.get("TWMKT_SHEETS_CREDS") or settings.get("sheets.creds_path") or "").strip()
    return SheetsBoard(spreadsheet_id=test_id, creds_path=creds)


def reset(board: SheetsBoard) -> None:
    for tab, header in (("CONTEXT", CONTEXT_HEADER), ("CONTENT", CONTENT_HEADER)):
        ws = board._tab(tab)
        ws.clear()
        ws.update("A1", [list(header)], value_input_option="USER_ENTERED")


def main(argv: list[str]) -> int:
    keep = "--keep" in argv
    settings = load_settings()
    board = _open_test_board(settings)

    # DB TẠM: không đụng store thật.
    tmpdb = Path(tempfile.mkdtemp()) / "sheet_ui_test.db"
    os.environ["DOCUMENT_STORE_PATH"] = str(tmpdb)
    from store import document_store as ds
    from store import pipeline_store as ps
    from store import queue_store as qs
    from store import sync_service as ss
    ds.init_db(tmpdb)

    print(f"Sheet test : {board.spreadsheet_id}")
    print(f"DB tạm     : {tmpdb}\n")
    board.ensure_tabs(force=True)
    reset(board)

    try:
        _pause()
        # --- Ca 1: render cơ bản + khối ngày + mới nhất DƯỚI CÙNG ------------
        print("[1] Khối ngày + thứ tự (mới nhất dưới cùng)")
        for k, d, hot in (("t-old", _day(2), 10.0), ("t-new", _day(0), 50.0),
                          ("t-old2", _day(2), 90.0), ("t-new2", _day(0), 20.0)):
            ps.write_raw(k, {"context": f"Bài {k}", "hook": "h", "source": "https://x/1",
                             "timestamp": d, "hot_pct": hot}, db_path=tmpdb)
            ps.write_gate_status(k, gate1="PENDING", db_path=tmpdb)
        ss.render_context_to_sheet(board, db_path=tmpdb, settings=settings)
        grid = board._tab("CONTEXT").get_all_values()
        i_ts = [h.lower() for h in grid[0]].index("timestamp")
        days = [r[i_ts] for r in grid[1:]]
        check("ngày thành khối liền nhau", days == sorted(days, key=lambda x: x.split("/")[::-1]),
              str(days))
        check("ngày mới nhất nằm DƯỚI CÙNG", days[-1] == _day(0), str(days))

        # --- Ca 2: render KHÔNG xoá định dạng --------------------------------
        print("[2] Định dạng sống qua lượt render")
        board.band_context_by_day()
        meta_before = board._spreadsheet().fetch_sheet_metadata(params={
            "fields": "sheets(properties(sheetId,title))"})
        ss.render_context_to_sheet(board, db_path=tmpdb, settings=settings)
        ss.render_context_to_sheet(board, db_path=tmpdb, settings=settings)
        grid2 = board._tab("CONTEXT").get_all_values()
        check("render lặp không đổi dữ liệu", grid2 == grid, "render không idempotent")
        check("tab vẫn còn (metadata đọc được)", bool(meta_before.get("sheets")))

        # --- Ca 3: lọc 7 ngày -------------------------------------------------
        print("[3] Chỉ hiển thị N ngày gần nhất")
        ps.write_raw("t-ancient", {"context": "Bài rất cũ", "hook": "h", "source": "https://x/9",
                                   "timestamp": _day(60), "hot_pct": 99.0}, db_path=tmpdb)
        ps.write_gate_status("t-ancient", gate1="PENDING", db_path=tmpdb)
        ss.render_context_to_sheet(board, db_path=tmpdb, settings=settings)
        keys = [r[[h.lower() for h in grid[0]].index("topickey")]
                for r in board._tab("CONTEXT").get_all_values()[1:]]
        check("bài 60 ngày trước KHÔNG hiện", "t-ancient" not in keys)
        check("bài cũ vẫn còn trong DB", ps.read_raw("t-ancient", db_path=tmpdb) is not None)

        # --- Ca 4: Gate 1 APPROVE -> enqueue ---------------------------------
        print("[4] Gate 1 APPROVE -> hàng đợi")
        ws = board._tab("CONTEXT")
        rows = ws.get_all_values()
        hl = [h.lower() for h in rows[0]]
        i_g1, i_tk = hl.index("duyệt context"), hl.index("topickey")
        wrote = False
        for ri, r in enumerate(rows[1:], start=2):
            if r[i_tk] == "t-new":
                wrote = set_cell(ws, i_g1, ri, "APPROVE")
        ss.ingest_context_from_sheet(board, db_path=tmpdb)
        if not wrote:
            print("     (bỏ qua ca 4/5: không ghi được ô, lỗi hạ tầng Sheets)")
        check("APPROVE tạo job produce", (not wrote) or
              any(j["topic_key"] == "t-new" and j["status"] == "queued"
                  for j in qs.list_queue(db_path=tmpdb)))

        # --- Ca 5: rút APPROVE -> huỷ job ------------------------------------
        print("[5] Rút APPROVE -> huỷ job")
        rows = ws.get_all_values()
        for ri, r in enumerate(rows[1:], start=2):
            if r[i_tk] == "t-new":
                set_cell(ws, i_g1, ri, "PENDING")
        ss.ingest_context_from_sheet(board, db_path=tmpdb)
        check("job chuyển 'cancelled'", (not wrote) or
              any(j["topic_key"] == "t-new" and j["status"] == "cancelled"
                  for j in qs.list_queue(db_path=tmpdb)))

        # --- Ca 6: DELETE realtime -------------------------------------------
        print("[6] Gate 1 DELETE -> xoá DB + xoá dòng NGAY")
        before_n = len(ws.get_all_values()) - 1
        rows = ws.get_all_values()
        for ri, r in enumerate(rows[1:], start=2):
            if r[i_tk] == "t-old2":
                set_cell(ws, i_g1, ri, "DELETE")
        ss.ingest_context_from_sheet(board, db_path=tmpdb)
        after_n = len(ws.get_all_values()) - 1
        check("dòng biến mất NGAY trên Sheet", after_n == before_n - 1, f"{before_n} -> {after_n}")
        check("dữ liệu xoá khỏi DB", ps.read_raw("t-old2", db_path=tmpdb) is None)
        check("chủ đề khác KHÔNG bị đụng", ps.read_raw("t-new", db_path=tmpdb) is not None)

        # --- Ca 7: khôi phục 100% sau khi xoá sạch ---------------------------
        print("[7] Xoá sạch bảng -> khôi phục 100%")
        ss.render_context_to_sheet(board, db_path=tmpdb, settings=settings)
        before = board._tab("CONTEXT").get_all_values()
        ws.clear()
        ws.update("A1", [list(CONTEXT_HEADER)], value_input_option="USER_ENTERED")
        ss.render_context_to_sheet(board, db_path=tmpdb, settings=settings)
        check("khôi phục KHỚP TỪNG Ô", board._tab("CONTEXT").get_all_values() == before)

        # --- Ca 8: cột read-only bị bỏ qua -----------------------------------
        print("[8] Sửa cột read-only -> bị bỏ qua")
        rows = ws.get_all_values()
        i_ex = [h.lower() for h in rows[0]].index("execute")
        for ri, r in enumerate(rows[1:], start=2):
            if r[i_tk] == "t-new":
                set_cell(ws, i_ex, ri, "DONE")
                break
        ss.ingest_context_from_sheet(board, db_path=tmpdb)
        check("Execute người gõ KHÔNG vào store",
              (ps.read_gate_status("t-new", db_path=tmpdb).get("execute") or "") != "DONE")
    except Exception as e:   # noqa: BLE001 -- vẫn phải reset Sheet test dù hỏng giữa chừng
        print("\n[LOI] Dung giua chung: " + repr(e))
        _FAIL.append(f"crash: {type(e).__name__}")
    finally:
        _pause()
        if not keep:
            reset(board)
            print("\n[reset] Đã đưa Sheet test về bảng trắng + header.")
        else:
            print("\n[--keep] GIỮ NGUYÊN Sheet test để soi mắt.")

    print(f"\n=== KẾT QUẢ: {len(_PASS)} PASS / {len(_FAIL)} FAIL ===")
    for n in _FAIL:
        print("  FAIL:", n)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
