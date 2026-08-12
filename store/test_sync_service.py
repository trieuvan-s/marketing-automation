"""Test store/sync_service.py -- dùng FAKE board/worksheet trong bộ nhớ (KHÔNG
chạm Google Sheet thật, KHÔNG cần credential/mạng). Fake worksheet chỉ implement
đúng 2 method sync_service.py thực sự gọi qua board._tab(...): get_all_values()/
clear()/update() -- đủ mô phỏng hành vi gspread cần cho test này. Tự thêm src/
vào sys.path (KHÔNG dựa side-effect import-order từ tests/test_pipeline.py) --
chạy standalone (python -m pytest store/test_sync_service.py) hay cùng bộ đều
được, cùng nếp tests/test_pipeline.py."""
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

import pytest

from store import document_store as ds
from store import pipeline_store as ps
from store import queue_store as qs
from store import sync_service as ss
from twmkt.sheets_board import (
    CONTENT_HEADER, CONTEXT_HEADER, GATE1_COL, GATE2_COL, GATE3_COL, OUTPUT_TYPE_COL,
)


class _FakeWorksheet:
    def __init__(self):
        self._grid: list[list[str]] = []

    def get_all_values(self) -> list[list[str]]:
        return [list(row) for row in self._grid]

    def clear(self) -> None:
        self._grid = []

    def update(self, range_str: str, values: list[list], value_input_option: str = "RAW") -> None:
        start_row = int(range_str[1:]) if len(range_str) > 1 else 1
        needed = start_row - 1 + len(values)
        while len(self._grid) < needed:
            self._grid.append([])
        for i, row in enumerate(values):
            self._grid[start_row - 1 + i] = [str(c) for c in row]

    def batch_clear(self, ranges: list[str]) -> None:
        """Fake `batch_clear` — chỉ cần cắt phần ĐUÔI (dòng thừa khi bảng co
        lại). Parse "A<start>:<col><end>" lấy start, xoá từ đó tới hết."""
        import re as _re
        for rng in ranges:
            m = _re.match(r"A(\d+):", rng)
            if m:
                self._grid = self._grid[: int(m.group(1)) - 1]

    def set_rows(self, rows: list[list[str]]) -> None:
        """Helper CHỈ dùng trong test -- mô phỏng trạng thái Sheet SẴN CÓ
        (bao gồm header) trước khi gọi hàm sync -- KHÔNG có trong gspread thật."""
        self._grid = [list(r) for r in rows]


class _FakeSyncBoard:
    def __init__(self):
        self._tabs = {"CONTEXT": _FakeWorksheet(), "CONTENT": _FakeWorksheet()}

    def _tab(self, name: str) -> _FakeWorksheet:
        return self._tabs[name]


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "test.db"
    ds.init_db(path)
    return path


@pytest.fixture()
def board():
    return _FakeSyncBoard()


def _header_index(header: list[str], name: str) -> int:
    return [h.strip().lower() for h in header].index(name.strip().lower())


# `_seed_full_state()` dùng 2 ngày tương đối "hôm qua"/"hôm nay" (KHÔNG
# hard-code "28/07/2026"/"29/07/2026") -- ngày cứng trôi ra ngoài cửa sổ
# `display_days` mặc định (7 ngày) một khi "hôm nay" của môi trường chạy test
# tiến xa hơn ngày viết test, khiến các test render dựa vào seed này ẩn mất
# dòng cần kiểm (đã xảy ra thật -- xem test_restore_keeps_every_user_owned_field).
from datetime import date as _date, timedelta as _timedelta   # noqa: E402
_SEED_YESTERDAY = (_date.today() - _timedelta(days=1)).strftime("%d/%m/%Y")
_SEED_TODAY = _date.today().strftime("%d/%m/%Y")


# =============================================================================
# render_context_to_sheet
# =============================================================================

def test_render_context_to_sheet_builds_rows_from_store(board, db_path):
    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "hook 1", "source": "https://cafef.vn/x.chn",
                          "tickers": ["FPT"], "group": "CoPhieu", "topic": "CoPhieu",
                          "score": 5, "hot_pct": 50.0}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="PENDING", execute="", db_path=db_path)

    written = ss.render_context_to_sheet(board, db_path=db_path)
    assert written == 1

    grid = board._tab("CONTEXT").get_all_values()
    assert grid[0] == CONTEXT_HEADER
    header = grid[0]
    row = grid[1]
    assert row[_header_index(header, "Context")] == "Bài 1"
    assert row[_header_index(header, "Source")] == "https://cafef.vn/x.chn"
    assert row[_header_index(header, "TopicKey")] == "tk-1"
    assert row[_header_index(header, GATE1_COL)] == "PENDING"
    # VIỆC Execute (2026-08-03, Lead) — ĐẢO LẠI quyết định 2026-07-28 (khi đó
    # ép "Waiting" cho Execute rỗng). Gate1=PENDING (chưa duyệt) + store
    # execute="" -> Sheet PHẢI hiện đúng "" (không tự đoán "Waiting").
    assert row[_header_index(header, "Execute")] == ""


def test_render_context_to_sheet_shows_waiting_once_approved_not_before(board, db_path):
    """VIỆC Execute (2026-08-03, Lead) — Gate1=APPROVE + store execute=
    "Waiting" -> Sheet hiện "Waiting" (khác ca PENDING/rỗng ở test trên).
    Phân biệt RÕ 2 trạng thái theo store, không hardcode 1 chiều."""
    ps.write_raw("tk-2", {"context": "Bài 2 đã duyệt"}, db_path=db_path)
    ps.write_gate_status("tk-2", gate1="APPROVE", execute="Waiting", db_path=db_path)

    ss.render_context_to_sheet(board, db_path=db_path)
    grid = board._tab("CONTEXT").get_all_values()
    header = grid[0]
    row = next(r for r in grid[1:] if r[_header_index(header, "TopicKey")] == "tk-2")
    assert row[_header_index(header, "Execute")] == "Waiting"


def test_render_context_to_sheet_reflects_gate1_and_notes_after_ingest(board, db_path):
    """render đọc THẲNG từ store (gate_status), KHÔNG đọc lại Sheet hiện có
    -- muốn 1 giá trị người vừa gõ trên Sheet "sống sót" qua render, PHẢI
    ingest TRƯỚC (đúng thứ tự sync_all() dùng: ingest rồi mới render)."""
    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "https://cafef.vn/x.chn",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="PENDING", execute="RUN", db_path=db_path)

    # Sheet đã có sẵn: người đã duyệt (APPROVE) + ghi chú -- store CHƯA biết.
    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["24/07/2026", "0.0", "0", "", "", "Bài 1", "h", "https://cafef.vn/x.chn",
         "APPROVE", "", "RUN", "", "ghi chú người", "tk-1"],
    ])

    ss.ingest_context_from_sheet(board, db_path=db_path)   # nạp thao tác người vào store
    ss.render_context_to_sheet(board, db_path=db_path)

    grid = board._tab("CONTEXT").get_all_values()
    header, row = grid[0], grid[1]
    assert row[_header_index(header, GATE1_COL)] == "APPROVE"
    assert row[_header_index(header, "Notes")] == "ghi chú người"


def test_render_context_to_sheet_without_prior_ingest_reflects_store_not_sheet(board, db_path):
    """Ngược lại: KHÔNG ingest trước -- render dùng ĐÚNG giá trị TRONG STORE
    (PENDING), bỏ qua APPROVE đang nằm trên Sheet chưa được nạp. Đây là hành
    vi ĐÚNG THIẾT KẾ (store là nguồn sự thật), không phải bug."""
    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="PENDING", db_path=db_path)
    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["24/07/2026", "0.0", "0", "", "", "Bài 1", "h", "u1", "APPROVE", "", "", "", "", "tk-1"],
    ])

    ss.render_context_to_sheet(board, db_path=db_path)   # KHÔNG gọi ingest trước

    grid = board._tab("CONTEXT").get_all_values()
    header, row = grid[0], grid[1]
    assert row[_header_index(header, GATE1_COL)] == "PENDING"


def test_render_context_to_sheet_is_idempotent_recovery(board, db_path):
    """LỆNH PHỤC HỒI (Bước 5.4): render 2 lần liên tiếp -> kết quả GIỐNG HỆT."""
    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="APPROVE", execute="DONE", db_path=db_path)

    ss.render_context_to_sheet(board, db_path=db_path)
    first = board._tab("CONTEXT").get_all_values()

    # Mô phỏng "xoá nhầm" -- người lỡ xoá sạch dòng dữ liệu trên Sheet.
    board._tab("CONTEXT").set_rows([CONTEXT_HEADER])
    ss.render_context_to_sheet(board, db_path=db_path)
    second = board._tab("CONTEXT").get_all_values()

    assert first == second   # phục hồi ĐÚNG NGUYÊN, không lệch 1 ô nào


def test_render_context_to_sheet_never_writes_to_notes_with_machine_content(board, db_path):
    """Notes là NGƯỜI-SỞ-HỮU -- render KHÔNG được tự sinh nội dung, chỉ giữ
    nguyên (mặc định rỗng nếu người chưa từng ghi)."""
    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="PENDING", execute="", db_path=db_path)
    ss.render_context_to_sheet(board, db_path=db_path)
    grid = board._tab("CONTEXT").get_all_values()
    header, row = grid[0], grid[1]
    assert row[_header_index(header, "Notes")] == ""


# =============================================================================
# render_content_to_sheet
# =============================================================================

def test_render_content_to_sheet_builds_rows_from_store(board, db_path):
    ps.write_raw("tk-1", {"context": "Bài 1"}, db_path=db_path)
    ps.write_content_output("tk-1", "article", {"status": "DONE", "output": "noi dung",
                                                "notes": "", "facts": "[]"}, db_path=db_path)

    written = ss.render_content_to_sheet(board, db_path=db_path)
    assert written == 1

    grid = board._tab("CONTENT").get_all_values()
    assert grid[0] == CONTENT_HEADER
    header, row = grid[0], grid[1]
    assert row[_header_index(header, "Context")] == "Bài 1"
    assert row[_header_index(header, "Type")] == "Article"   # VIỆC 3: Type ghi NHÃN hiển thị
    assert row[_header_index(header, "Status")] == "DONE"
    assert row[_header_index(header, GATE2_COL)] == "PENDING"
    assert row[_header_index(header, GATE3_COL)] == "PENDING"


def test_render_content_to_sheet_reflects_gate2_gate3_social_posting_after_ingest(board, db_path):
    ps.write_raw("tk-1", {"context": "Bài 1"}, db_path=db_path)
    ps.write_content_output("tk-1", "article", {"status": "DONE", "output": "x",
                                                "notes": "", "facts": "[]"}, db_path=db_path)

    board._tab("CONTENT").set_rows([
        CONTENT_HEADER,
        ["24/07/2026", "Bài 1", "article", "DONE", "x", "", "APPROVE", "tk-1", "[]", "", "",
         "https://facebook.com/post/1", "APPROVE", "Đã đăng"],
    ])

    ss.ingest_content_from_sheet(board, db_path=db_path)   # nạp thao tác người vào store trước
    ss.render_content_to_sheet(board, db_path=db_path)

    grid = board._tab("CONTENT").get_all_values()
    header, row = grid[0], grid[1]
    assert row[_header_index(header, GATE2_COL)] == "APPROVE"
    assert row[_header_index(header, "Social Link")] == "https://facebook.com/post/1"
    assert row[_header_index(header, GATE3_COL)] == "APPROVE"
    assert row[_header_index(header, "Posting Status")] == "Đã đăng"


def test_render_content_to_sheet_never_writes_gate3_away_from_pending_default(board, db_path):
    """INVARIANT thừa kế từ content_row(): KHÔNG luồng máy nào tự đặt Duyệt
    Public khác PENDING cho dòng CHƯA có quyết định người -- render giữ mặc
    định PENDING khi Sheet chưa từng có giá trị nào (topic MỚI)."""
    ps.write_raw("tk-1", {"context": "Bài 1"}, db_path=db_path)
    ps.write_content_output("tk-1", "infographic", {"status": "DONE", "output": "{}",
                                                     "notes": "", "facts": "[]"}, db_path=db_path)
    ss.render_content_to_sheet(board, db_path=db_path)
    grid = board._tab("CONTENT").get_all_values()
    header, row = grid[0], grid[1]
    assert row[_header_index(header, GATE3_COL)] == "PENDING"


def test_render_content_to_sheet_truncates_output_but_store_keeps_full(board, db_path):
    """VIỆC 1.3 (Lead 2026-07-27): store PHẢI giữ NGUYÊN VĂN (không phải nơi
    gây bug Bước 5.3 nữa — xem test_run_writes_full_body_to_store_over_1500_
    chars_not_truncated ở tests/test_pipeline.py), nhưng ô Sheet VẪN cắt ở
    ngưỡng _OUTPUT_PREVIEW (nâng lên 5000 — Việc 2, 2026-08-04) — Sheet chỉ để
    người liếc/sửa tay bài NGẮN hơn ngưỡng, KHÔNG nới giới hạn hiển thị cho
    bài DÀI hơn."""
    long_output = ("x" * 6000) + "MARKER_CUOI"
    ps.write_raw("tk-1", {"context": "Bài dài"}, db_path=db_path)
    ps.write_content_output("tk-1", "infographic",
                            {"status": "DONE", "output": long_output, "notes": "", "facts": "[]"},
                            db_path=db_path)

    # store giữ ĐẦY ĐỦ, không bị hàm render đụng vào (render chỉ ĐỌC).
    stored = ps.read_content_output("tk-1", "infographic", db_path=db_path)
    assert stored["output"] == long_output
    assert len(stored["output"]) == 6011

    ss.render_content_to_sheet(board, db_path=db_path)
    grid = board._tab("CONTENT").get_all_values()
    header, row = grid[0], grid[1]
    sheet_output = row[_header_index(header, "Output")]
    assert len(sheet_output) < len(long_output)   # Sheet VẪN cắt -- không nới giới hạn
    assert "MARKER_CUOI" not in sheet_output       # bản cắt Sheet KHÔNG có đoạn cuối
    assert sheet_output.startswith("x" * 5000)


def test_render_content_to_sheet_uses_asset_url_over_local_path(board, db_path):
    ps.write_raw("tk-1", {"context": "Bài 1"}, db_path=db_path)
    ps.write_content_output("tk-1", "infographic", {"status": "DONE", "output": "{}",
                                                     "notes": "", "facts": "[]"}, db_path=db_path)
    ps.write_content_status("tk-1", "infographic", asset_url="https://drive.google.com/x",
                            asset_local_path="/local/x.png", db_path=db_path)
    ss.render_content_to_sheet(board, db_path=db_path)
    grid = board._tab("CONTENT").get_all_values()
    header, row = grid[0], grid[1]
    # 2026-07-28: có asset_url -> ưu tiên URL (không dùng local path) VÀ bọc
    # HYPERLINK để người duyệt Gate 3 bấm được, thay vì text thô như trước.
    assert row[_header_index(header, "AssetPath")] == \
        '=HYPERLINK("https://drive.google.com/x", "Mở file")'


def test_render_content_to_sheet_timestamp_prefers_published_at(board, db_path):
    """VIỆC 3.1 (2026-08-04, Lead) — Timestamp CONTENT phải ưu tiên
    published_at (ngày ĐĂNG BÀI GỐC, cùng ý nghĩa Timestamp bên CONTEXT), lùi
    về `timestamp` (ngày xử lý) khi bản ghi CŨ chưa có published_at."""
    ps.write_raw("tk-1", {"context": "Bài 1"}, db_path=db_path)
    ps.write_content_output("tk-1", "article", {"status": "DONE", "output": "x", "notes": "",
                                                "facts": "[]", "timestamp": _SEED_TODAY,
                                                "published_at": _SEED_YESTERDAY}, db_path=db_path)
    ps.write_raw("tk-2", {"context": "Bài 2"}, db_path=db_path)
    ps.write_content_output("tk-2", "article", {"status": "DONE", "output": "x", "notes": "",
                                                "facts": "[]", "timestamp": _SEED_TODAY},
                            db_path=db_path)   # bản ghi CŨ, không có published_at

    ss.render_content_to_sheet(board, db_path=db_path)
    grid = board._tab("CONTENT").get_all_values()
    header = grid[0]
    i_ts, i_tk = _header_index(header, "Timestamp"), _header_index(header, "TopicKey")
    by_tk = {r[i_tk]: r[i_ts] for r in grid[1:]}
    assert by_tk["tk-1"] == _SEED_YESTERDAY   # có published_at -> dùng nó
    assert by_tk["tk-2"] == _SEED_TODAY       # thiếu published_at -> lùi về timestamp


def test_content_same_day_rows_keep_crawl_order_not_alphabetical(board, db_path):
    """VIỆC 3.2 (2026-08-04, Lead — cùng bug "dữ liệu trong cùng ngày bị xếp
    lẫn lộn" đã sửa cho CONTEXT ở Task #75) — topic_key CỐ Ý đặt ngược alphabet
    ("zzz" sinh content_output TRƯỚC "aaa") để phân biệt: nếu còn sort theo
    thứ tự list_topics() (ORDER BY topic_key) thì "aaa" lên trước — SAI. Đúng
    phải theo first_created_at() của content_output -> "zzz" trước."""
    from datetime import date
    day = date.today().strftime("%d/%m/%Y")
    ps.write_raw("zzz", {"context": "zzz"}, db_path=db_path)
    ps.write_content_output("zzz", "article", {"status": "DONE", "output": "x", "notes": "",
                                               "facts": "[]", "timestamp": day}, db_path=db_path)
    ps.write_raw("aaa", {"context": "aaa"}, db_path=db_path)
    ps.write_content_output("aaa", "article", {"status": "DONE", "output": "x", "notes": "",
                                               "facts": "[]", "timestamp": day}, db_path=db_path)

    ss.render_content_to_sheet(board, db_path=db_path)
    grid = board._tab("CONTENT").get_all_values()
    i_ctx = _header_index(grid[0], "Context")
    assert [r[i_ctx] for r in grid[1:]] == ["zzz", "aaa"], \
        "phải theo thứ tự content_output được TẠO (zzz trước), không theo alphabet topic_key"


def test_content_nguoi_thuc_hien_carried_forward_across_renders(board, db_path):
    """VIỆC 3.4 (2026-08-04, Lead — điều phối nhân sự) — cột "Người thực
    hiện" KHÔNG có store backing (Lead tự gõ tay qua Sheet UI). render_content_
    to_sheet() dựng lại TOÀN BỘ tab mỗi lượt (kể cả khi KHÔNG có gì đổi ở
    store) -- PHẢI đọc giá trị hiện có trên Sheet TRƯỚC khi ghi đè, nếu không
    sẽ xoá mất tên người Lead vừa gõ ở lượt render kế tiếp (vd do Gate 2 vừa
    đổi -- xem test_render_never_clears_whole_tab, cùng lo ngại mất dữ liệu
    trình bày người gõ tay)."""
    ps.write_raw("tk-1", {"context": "Bài 1"}, db_path=db_path)
    ps.write_content_output("tk-1", "article", {"status": "DONE", "output": "x", "notes": "",
                                                "facts": "[]"}, db_path=db_path)
    ss.render_content_to_sheet(board, db_path=db_path)

    ws = board._tab("CONTENT")
    grid = ws.get_all_values()
    i_nguoi = _header_index(grid[0], "Người thực hiện")
    row = list(grid[1])
    row[i_nguoi] = "Chị Lan"
    ws.update("A2", [row], value_input_option="RAW")

    # 1 thay đổi KHÔNG LIÊN QUAN ở store (Gate 2) -> render lại toàn bộ tab.
    ps.write_content_status("tk-1", "article", gate2="APPROVE", db_path=db_path)
    ss.render_content_to_sheet(board, db_path=db_path)

    grid_after = ws.get_all_values()
    assert grid_after[1][_header_index(grid_after[0], "Người thực hiện")] == "Chị Lan", \
        "render lại KHÔNG được xoá tên người Lead đã gõ tay (không có store backing)"


# =============================================================================
# ingest_context_from_sheet
# =============================================================================

def test_ingest_context_from_sheet_writes_gate1_and_notes_changes(board, db_path):
    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="PENDING", db_path=db_path)

    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["24/07/2026", "0.0", "0", "", "", "Bài 1", "h", "u1", "APPROVE", "", "", "", "note moi", "tk-1"],
    ])

    n = ss.ingest_context_from_sheet(board, db_path=db_path)
    assert n == 1
    gate = ps.read_gate_status("tk-1", db_path=db_path)
    assert gate["gate1"] == "APPROVE"
    assert gate["notes"] == "note moi"


def test_ingest_context_from_sheet_no_op_when_nothing_changed(board, db_path):
    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="APPROVE", execute="RUN", notes="giu nguyen", db_path=db_path)

    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["24/07/2026", "0.0", "0", "", "", "Bài 1", "h", "u1", "APPROVE", "", "RUN", "", "giu nguyen", "tk-1"],
    ])

    n = ss.ingest_context_from_sheet(board, db_path=db_path)
    assert n == 0
    history = ds.read_history("tk-1", "gate_status", "", db_path=db_path)
    assert len(history) == 1   # KHÔNG ghi version mới thừa


def test_ingest_context_from_sheet_bridges_new_topic_not_in_store(board, db_path):
    """CẦU NỐI TẠM: TopicKey có trên Sheet (review_to_sheet.py ghi) nhưng
    store CHƯA có raw -- ingest phải NẠP topic này vào store."""
    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["24/07/2026", "62.5", "8", "CoPhieu", "CoPhieu", "Bài mới từ crawl", "hook moi",
         "https://cafef.vn/moi.chn", "PENDING", "", "", "FPT, HPG", "", "tk-moi"],
    ])

    n = ss.ingest_context_from_sheet(board, db_path=db_path)
    assert n == 2   # 1 write_raw + 1 write_gate_status

    raw = ps.read_raw("tk-moi", db_path=db_path)
    assert raw["context"] == "Bài mới từ crawl"
    assert raw["source"] == "https://cafef.vn/moi.chn"
    assert raw["tickers"] == ["FPT", "HPG"]
    assert raw["score"] == 8
    assert raw["hot_pct"] == 62.5
    gate = ps.read_gate_status("tk-moi", db_path=db_path)
    assert gate["gate1"] == "PENDING"
    # VIỆC Execute (2026-08-03, Lead) — topic MỚI, gate1=PENDING (chưa duyệt)
    # -> Execute="" (KHÔNG "Waiting" — đó là ĐẢO LẠI quyết định 2026-07-28).
    assert gate["execute"] == ""


def test_ingest_context_from_sheet_skips_rows_without_topic_key(board, db_path):
    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["24/07/2026", "0.0", "0", "", "", "Bài chưa có khoá", "h", "u1", "PENDING", "", "", "", "", ""],
    ])
    n = ss.ingest_context_from_sheet(board, db_path=db_path)
    assert n == 0
    assert ds.list_topics(db_path=db_path) == []


def test_ingest_context_from_sheet_never_reads_execute_written_by_hand(board, db_path):
    """2026-07-28 — HỢP ĐỒNG ĐỔI: Execute là cờ MÁY-GHI, read-only với người.
    Trước đây có "khe hẹp" NEEDS_HUMAN->RUN cho người xin chạy lại; nay KHÔNG
    còn đọc giá trị Execute từ Sheet ở BẤT KỲ ca nào. Người gõ "RUN" vào ô
    (dù Protected Range đã chặn, chủ Sheet vẫn gõ được) -> BỎ QUA HOÀN TOÀN,
    trạng thái thật trong store giữ nguyên NEEDS_HUMAN."""
    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="APPROVE", execute="NEEDS_HUMAN", db_path=db_path)

    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["24/07/2026", "0.0", "0", "", "", "Bài 1", "h", "u1", "APPROVE", "", "RUN", "", "", "tk-1"],
    ])

    n = ss.ingest_context_from_sheet(board, db_path=db_path)
    assert n == 0
    assert ps.read_gate_status("tk-1", db_path=db_path)["execute"] == "NEEDS_HUMAN"
    assert qs.list_queue(db_path=db_path) == []   # không có job nào được tạo


def test_ingest_context_reapprove_is_the_retry_path_after_needs_human(board, db_path):
    """Đường CHẠY LẠI MỚI thay cho khe hẹp NEEDS_HUMAN->RUN đã bỏ: người bỏ
    APPROVE rồi APPROVE lại trên Gate 1 -> Execute reset về Waiting + job mới
    vào hàng đợi. Đây là lý do bỏ cột Execute 2 chiều mà KHÔNG mất tính năng."""
    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="PENDING", execute="NEEDS_HUMAN", db_path=db_path)

    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["24/07/2026", "0.0", "0", "", "", "Bài 1", "h", "u1", "APPROVE", "", "NEEDS_HUMAN", "", "", "tk-1"],
    ])

    ss.ingest_context_from_sheet(board, db_path=db_path)
    gate = ps.read_gate_status("tk-1", db_path=db_path)
    assert gate["gate1"] == "APPROVE"
    assert gate["execute"] == "Waiting"
    assert [j["topic_key"] for j in qs.list_queue(db_path=db_path)] == ["tk-1"]


def test_ingest_context_from_sheet_ignores_execute_run_when_not_needs_human(board, db_path):
    """Execute KHÔNG phải cột người-sở-hữu đầy đủ -- CHỈ đọc transition
    NEEDS_HUMAN->RUN. Execute=DONE mà Sheet lỡ ghi "RUN" (không có ý nghĩa
    thao tác người thật) -- KHÔNG được ingest, tránh phá idempotent Execute
    do pipeline quản lý."""
    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="APPROVE", execute="DONE", db_path=db_path)

    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["24/07/2026", "0.0", "0", "", "", "Bài 1", "h", "u1", "APPROVE", "", "RUN", "", "", "tk-1"],
    ])

    n = ss.ingest_context_from_sheet(board, db_path=db_path)
    assert n == 0
    assert ps.read_gate_status("tk-1", db_path=db_path)["execute"] == "DONE"


# =============================================================================
# ingest_content_from_sheet
# =============================================================================

def test_ingest_content_from_sheet_writes_gate2_gate3_social_posting_changes(board, db_path):
    ps.write_raw("tk-1", {"context": "Bài 1"}, db_path=db_path)
    ps.write_content_output("tk-1", "article", {"status": "DONE", "output": "x",
                                                "notes": "", "facts": "[]"}, db_path=db_path)
    ps.write_content_status("tk-1", "article", gate2="PENDING", db_path=db_path)

    board._tab("CONTENT").set_rows([
        CONTENT_HEADER,
        ["24/07/2026", "Bài 1", "article", "DONE", "x", "", "APPROVE", "tk-1", "[]", "", "",
         "https://fb.com/1", "APPROVE", "Đã đăng"],
    ])

    n = ss.ingest_content_from_sheet(board, db_path=db_path)
    assert n == 1
    status = ps.read_content_status("tk-1", "article", db_path=db_path)
    assert status["gate2"] == "APPROVE"
    assert status["social_link"] == "https://fb.com/1"
    assert status["gate3"] == "APPROVE"
    assert status["posting_status"] == "Đã đăng"


def test_ingest_content_from_sheet_matches_type_as_display_label(board, db_path):
    """SỬA LỖI THẬT NGHIÊM TRỌNG (2026-08-03, Lead báo qua ca Gate 2 duyệt
    xong không sinh AssetPath) — VIỆC 3 đổi content_row() ghi NHÃN hiển thị
    ("Video"/"Infographic"...) vào cột Type, nhưng ingest_content_from_sheet()
    vẫn đọc THẲNG ô đó làm content_type để tra store -> "Video" != "video" ->
    read_content_output() trả None -> CẢ DÒNG bị bỏ qua ÂM THẦM. Hậu quả thật:
    Gate 2 người vừa duyệt (APPROVE) KHÔNG BAO GIỜ được ghi vào store, rồi
    render_content_to_sheet() lượt sau lại vẽ đè Sheet về "PENDING" (từ store
    cũ) -- xoá mất thao tác người vừa bấm. Test này khoá ĐÚNG use-case
    "Type ghi nhãn hiển thị" (không phải khoá thô) vẫn phải ingest được."""
    ps.write_raw("tk-1", {"context": "Bài video"}, db_path=db_path)
    ps.write_content_output("tk-1", "video", {"status": "DONE", "output": "x",
                                              "notes": "", "facts": "[]"}, db_path=db_path)
    ps.write_content_status("tk-1", "video", gate2="PENDING", db_path=db_path)

    board._tab("CONTENT").set_rows([
        CONTENT_HEADER,
        # "Video" -- NHÃN hiển thị (VIỆC 3), KHÔNG phải "video" thô.
        ["24/07/2026", "Bài video", "Video", "DONE", "x", "", "APPROVE", "tk-1", "[]", "",
         "", "", "PENDING", ""],
    ])

    n = ss.ingest_content_from_sheet(board, db_path=db_path)
    assert n == 1, "Type ghi nhãn hiển thị PHẢI vẫn khớp được content_output, không bị bỏ qua"
    status = ps.read_content_status("tk-1", "video", db_path=db_path)
    assert status["gate2"] == "APPROVE"


def test_ingest_content_from_sheet_writes_back_edited_output(board, db_path):
    """VIỆC 2 (2026-08-04, Lead) — Output là cột HYBRID DUY NHẤT: người có thể
    sửa tay bài viết trên Sheet TRƯỚC khi duyệt Gate 2, sửa phải ghi NGƯỢC vào
    content_output (version MỚI, giữ nguyên mọi field khác — status/notes/
    facts — CHỈ đổi "output")."""
    ps.write_raw("tk-1", {"context": "Bài 1"}, db_path=db_path)
    ps.write_content_output("tk-1", "article", {"status": "DONE", "output": "bản gốc",
                                                "notes": "ghi chú cũ", "facts": "[]"}, db_path=db_path)
    ps.write_content_status("tk-1", "article", gate2="PENDING", db_path=db_path)

    board._tab("CONTENT").set_rows([
        CONTENT_HEADER,
        ["24/07/2026", "Bài 1", "article", "DONE", "bản đã sửa tay", "", "PENDING", "tk-1", "[]", "",
         "", "", "PENDING", ""],
    ])
    n = ss.ingest_content_from_sheet(board, db_path=db_path)
    assert n == 1
    out = ps.read_content_output("tk-1", "article", db_path=db_path)
    assert out["output"] == "bản đã sửa tay"
    assert out["status"] == "DONE" and out["notes"] == "ghi chú cũ", \
        "sửa Output KHÔNG được đụng field khác của content_output"


def test_ingest_content_from_sheet_no_writeback_when_output_unchanged(board, db_path):
    """Round-trip render->ingest KHÔNG người đụng vào KHÔNG được tự sinh
    version rác -- `_cell()` .strip() không được coi là 'đã sửa'."""
    ps.write_raw("tk-1", {"context": "Bài 1"}, db_path=db_path)
    ps.write_content_output("tk-1", "article", {"status": "DONE", "output": "bản gốc",
                                                "notes": "", "facts": "[]"}, db_path=db_path)
    ps.write_content_status("tk-1", "article", gate2="PENDING", db_path=db_path)

    ss.render_content_to_sheet(board, db_path=db_path)
    n = ss.ingest_content_from_sheet(board, db_path=db_path)
    assert n == 0
    history = ds.read_history("tk-1", "content_output", "article", db_path=db_path)
    assert len(history) == 1, "KHÔNG được ghi version content_output mới khi Output không đổi"


def test_ingest_content_from_sheet_skips_output_writeback_when_store_output_truncated(board, db_path):
    """Bài DÀI hơn _OUTPUT_PREVIEW: Sheet CHỈ hiện bản CẮT + hậu tố giải
    thích — so trực tiếp với bản store NGUYÊN VĂN sẽ luôn "khác nhau" giả.
    ingest phải CHỦ ĐỘNG bỏ qua write-back trong ca này (không ghi đè bài dài
    thành bản cụt)."""
    long_output = "x" * 6000
    ps.write_raw("tk-1", {"context": "Bài dài"}, db_path=db_path)
    ps.write_content_output("tk-1", "article", {"status": "DONE", "output": long_output,
                                                "notes": "", "facts": "[]"}, db_path=db_path)
    ps.write_content_status("tk-1", "article", gate2="PENDING", db_path=db_path)

    ss.render_content_to_sheet(board, db_path=db_path)
    n = ss.ingest_content_from_sheet(board, db_path=db_path)
    assert n == 0
    out = ps.read_content_output("tk-1", "article", db_path=db_path)
    assert out["output"] == long_output, "bản NGUYÊN VĂN trong store không được đụng tới"


def test_ingest_content_from_sheet_ignores_stale_truncated_cell_as_edit(board, db_path):
    """SỰ CỐ THẬT (2026-08-04, phát hiện ngay lượt sync_all() sản xuất đầu
    tiên sau khi nâng _OUTPUT_PREVIEW 1500->5000) — Sheet còn giữ NGUYÊN bản
    CẮT + hậu tố từ TRƯỚC khi deploy (ngưỡng cũ 1500, hoặc bất kỳ ngưỡng nào
    trước đó); ingest chạy TRƯỚC render (sync_all()) nên đọc phải ảnh cũ này.
    Nếu chỉ so độ dài (store hiện <= ngưỡng MỚI), ingest coi bản cắt CŨ là
    "người vừa sửa tay" và GHI ĐÈ content_output thật bằng bản cụt — ĐÃ XẢY RA
    THẬT, làm hỏng 17 bản ghi production, phải phục hồi tay từ version trước.
    Khoá lại: cell mang hậu tố _TRUNCATION_SUFFIX KHÔNG BAO GIỜ được coi là
    edit, bất kể so khớp độ dài ra sao."""
    real_output = "y" * 2000   # NGẮN hơn ngưỡng mới (5000) -- sẽ lọt qua nếu chỉ xét độ dài
    stale_sheet_cell = ("y" * 1500) + ss._TRUNCATION_SUFFIX   # ảnh CẮT sót từ lượt render TRƯỚC
    ps.write_raw("tk-1", {"context": "Bài 1"}, db_path=db_path)
    ps.write_content_output("tk-1", "article", {"status": "DONE", "output": real_output,
                                                "notes": "", "facts": "[]"}, db_path=db_path)
    ps.write_content_status("tk-1", "article", gate2="PENDING", db_path=db_path)

    board._tab("CONTENT").set_rows([
        CONTENT_HEADER,
        ["24/07/2026", "Bài 1", "article", "DONE", stale_sheet_cell, "", "PENDING", "tk-1", "[]", "",
         "", "", "PENDING", ""],
    ])
    n = ss.ingest_content_from_sheet(board, db_path=db_path)
    assert n == 0, "cell mang hậu tố cắt KHÔNG được coi là người sửa tay"
    out = ps.read_content_output("tk-1", "article", db_path=db_path)
    assert out["output"] == real_output, "content_output thật KHÔNG được ghi đè bằng ảnh cắt cũ"


def test_ingest_content_from_sheet_skips_when_content_output_missing(board, db_path):
    """CONTENT row tham chiếu (TopicKey, Type) CHƯA có content_output trong
    store -- KHÔNG được tự tạo content_status mồ côi."""
    board._tab("CONTENT").set_rows([
        CONTENT_HEADER,
        ["24/07/2026", "Bài lạ", "video", "DONE", "x", "", "APPROVE", "tk-la", "[]", "",
         "", "PENDING", ""],
    ])
    n = ss.ingest_content_from_sheet(board, db_path=db_path)
    assert n == 0
    assert ps.read_content_status("tk-la", "video", db_path=db_path) == {}


# =============================================================================
# sync_all
# =============================================================================

def test_sync_all_ingests_user_edit_then_renders_it_back(board, db_path):
    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="PENDING", db_path=db_path)
    ss.render_context_to_sheet(board, db_path=db_path)   # dựng Sheet lần đầu

    # Người bấm duyệt trên Sheet.
    grid = board._tab("CONTEXT").get_all_values()
    header = grid[0]
    grid[1][_header_index(header, GATE1_COL)] = "APPROVE"
    board._tab("CONTEXT").set_rows(grid)

    result = ss.sync_all(board, db_path=db_path)
    assert result["ingested_context"] == 1

    assert ps.read_gate_status("tk-1", db_path=db_path)["gate1"] == "APPROVE"
    grid_after = board._tab("CONTEXT").get_all_values()
    row_after = grid_after[1]
    assert row_after[_header_index(grid_after[0], GATE1_COL)] == "APPROVE"


def test_sync_all_full_recovery_after_accidental_deletion(board, db_path):
    """Bước 5.4 thu nhỏ: seed store + duyệt qua Sheet (đã ingest) -> xoá SẠCH
    Sheet -> sync_all() -> Sheet phục hồi ĐÚNG NGUYÊN trạng thái đã duyệt
    (KHÔNG mất Duyệt Context, vì đã ingest vào store TRƯỚC khi xoá)."""
    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": ["FPT"], "group": "CoPhieu", "topic": "CoPhieu"}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="PENDING", db_path=db_path)
    ss.sync_all(board, db_path=db_path)

    grid = board._tab("CONTEXT").get_all_values()
    header = grid[0]
    grid[1][_header_index(header, GATE1_COL)] = "APPROVE"
    board._tab("CONTEXT").set_rows(grid)
    ss.sync_all(board, db_path=db_path)   # ingest APPROVE vào store
    before_wipe = board._tab("CONTEXT").get_all_values()

    board._tab("CONTEXT").set_rows([CONTEXT_HEADER])   # xoá nhầm
    ss.sync_all(board, db_path=db_path)   # phục hồi
    after_recovery = board._tab("CONTEXT").get_all_values()

    assert after_recovery == before_wipe
    row = after_recovery[1]
    assert row[_header_index(header, GATE1_COL)] == "APPROVE"   # quyết định người KHÔNG mất


# =============================================================================
# Output Type (Bước 4)
# =============================================================================

def test_render_context_to_sheet_includes_output_type(board, db_path):
    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="APPROVE", output_type=["Infographic", "Video"], db_path=db_path)
    ss.render_context_to_sheet(board, db_path=db_path)
    grid = board._tab("CONTEXT").get_all_values()
    header, row = grid[0], grid[1]
    assert row[_header_index(header, OUTPUT_TYPE_COL)] == "Infographic, Video"


def test_write_rows_skips_unchanged_rows_touches_only_changed_ones(board, db_path):
    """Lead 02/08 ("Output Type bị khoá") — `_write_rows()` giờ SO KHỚP từng
    dòng với Sheet hiện tại, CHỈ gọi update() cho dòng THẬT SỰ đổi. Dòng không
    đổi giữa 2 lần render KHÔNG được đụng tới ô nào (tránh ghi đè ô "dropdown
    chip multi-select" Output Type Lead tự bật tay qua UI — mỗi lần ghi giá
    trị thô qua API vào ô chip, kể cả giá trị giống hệt, có thể làm rớt trạng
    thái UI chip đó, xem docstring _write_rows())."""
    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="APPROVE", output_type=["Article"], db_path=db_path)
    ps.write_raw("tk-2", {"context": "Bài 2", "hook": "h", "source": "u2",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-2", gate1="APPROVE", output_type=["Video"], db_path=db_path)

    ss.render_context_to_sheet(board, db_path=db_path)
    ws = board._tab("CONTEXT")
    baseline = ws.get_all_values()

    calls: list[str] = []
    orig_update = ws.update

    def _spy_update(range_str, values, value_input_option="RAW"):
        calls.append(range_str)
        return orig_update(range_str, values, value_input_option=value_input_option)

    ws.update = _spy_update

    # Chỉ đổi tk-2 (Execute) -- tk-1 giữ nguyên hệt.
    ps.write_gate_status("tk-2", execute="DONE", db_path=db_path)
    ss.render_context_to_sheet(board, db_path=db_path)

    header = baseline[0]
    i_key = _header_index(header, "TopicKey")
    row_of = {r[i_key]: i for i, r in enumerate(baseline[1:], start=2)}   # +2 = số dòng Sheet (1-based, có header)

    # KHÔNG lệnh update() nào chạm dòng tk-1 (không đổi).
    tk1_row_num = row_of["tk-1"]
    for rng in calls:
        start = int(rng[1:])
        assert start != tk1_row_num, f"dòng tk-1 (không đổi) bị đụng: {rng}"

    # Dòng tk-2 (CÓ đổi) phải được ghi lại.
    tk2_row_num = row_of["tk-2"]
    assert any(int(rng[1:]) == tk2_row_num for rng in calls), \
        f"dòng tk-2 (có đổi) PHẢI được ghi, calls={calls}"

    grid = ws.get_all_values()
    i_ex = _header_index(header, "Execute")
    new_row_of = {r[i_key]: r for r in grid[1:]}
    assert new_row_of["tk-2"][i_ex] == "DONE"


def test_render_context_to_sheet_output_type_shows_auto_when_never_set(board, db_path):
    """Sửa 2026-07-27 (Lead): ô Output Type rỗng gây khó hiểu cho người nhìn
    Sheet dù xử lý tương đương AUTO — context_row() giờ hiển thị CHỮ "AUTO"
    tường minh (KHÔNG đổi hành vi _allowed_output_types(), vẫn coi ["AUTO"]
    = không giới hạn thêm, xem test_run_output_type_default_empty_behaves_
    like_auto trong tests/test_pipeline.py)."""
    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="PENDING", db_path=db_path)
    ss.render_context_to_sheet(board, db_path=db_path)
    grid = board._tab("CONTEXT").get_all_values()
    header, row = grid[0], grid[1]
    assert row[_header_index(header, OUTPUT_TYPE_COL)] == "AUTO"


def test_ingest_context_from_sheet_writes_output_type_change(board, db_path):
    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="APPROVE", db_path=db_path)

    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["24/07/2026", "0.0", "0", "", "", "Bài 1", "h", "u1", "APPROVE", "Article", "", "", "", "tk-1"],
    ])

    n = ss.ingest_context_from_sheet(board, db_path=db_path)
    assert n == 1
    assert ps.read_gate_status("tk-1", db_path=db_path)["output_type"] == ["Article"]


def test_ingest_context_from_sheet_bridges_new_topic_with_output_type(board, db_path):
    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["24/07/2026", "0.0", "0", "", "", "Bài mới", "h", "u1", "PENDING", "Infographic, Video",
         "", "", "", "tk-moi"],
    ])
    ss.ingest_context_from_sheet(board, db_path=db_path)
    assert ps.read_gate_status("tk-moi", db_path=db_path)["output_type"] == ["Infographic", "Video"]


def test_sync_all_round_trip_preserves_output_type_selection(board, db_path):
    """Người chọn Output Type trên Sheet -> sync_all() -> ingest vào store ->
    render lại đúng NGUYÊN lựa chọn (0 mất khi xoá nhầm, giống Duyệt Context)."""
    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="PENDING", db_path=db_path)
    ss.sync_all(board, db_path=db_path)

    grid = board._tab("CONTEXT").get_all_values()
    header = grid[0]
    grid[1][_header_index(header, OUTPUT_TYPE_COL)] = "Article"
    board._tab("CONTEXT").set_rows(grid)
    ss.sync_all(board, db_path=db_path)

    grid_after = board._tab("CONTEXT").get_all_values()
    row_after = grid_after[1]
    assert row_after[_header_index(header, OUTPUT_TYPE_COL)] == "Article"
    assert ps.read_gate_status("tk-1", db_path=db_path)["output_type"] == ["Article"]


# =============================================================================
# Execute bootstrap (Gate1 vừa APPROVE -> tự đặt RUN, thay
# SheetsBoard.sync_approve_execute_flags() cũ)
# =============================================================================

def test_ingest_context_from_sheet_bootstraps_execute_run_for_existing_topic(board, db_path):
    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="PENDING", db_path=db_path)   # chưa duyệt, chưa Execute

    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["24/07/2026", "0.0", "0", "", "", "Bài 1", "h", "u1", "APPROVE", "", "", "", "", "tk-1"],
    ])

    n = ss.ingest_context_from_sheet(board, db_path=db_path)
    assert n == 1
    gate = ps.read_gate_status("tk-1", db_path=db_path)
    assert gate["gate1"] == "APPROVE"
    assert gate["execute"] == "Waiting"


def test_ingest_context_from_sheet_bridges_new_topic_already_approved_bootstraps_run(board, db_path):
    """review_to_sheet.py KHÔNG tự đặt Execute -- topic mới nạp vào store lần
    đầu mà Sheet đã Gate1=APPROVE (người duyệt rất nhanh) vẫn phải vào hàng
    đợi NGAY, không phải chờ 1 lượt ingest thứ 2 (ca này KHÔNG có "chuyển
    tiếp Gate 1" để bắt, nên là nhánh riêng trong ingest)."""
    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["24/07/2026", "50.0", "5", "", "", "Bài mới đã duyệt ngay", "h",
         "https://cafef.vn/x.chn", "APPROVE", "", "", "", "", "tk-moi-approved"],
    ])
    ss.ingest_context_from_sheet(board, db_path=db_path)
    gate = ps.read_gate_status("tk-moi-approved", db_path=db_path)
    assert gate["gate1"] == "APPROVE"
    assert gate["execute"] == "Waiting"
    assert [j["topic_key"] for j in qs.list_queue(db_path=db_path)] == ["tk-moi-approved"]


def test_ingest_context_from_sheet_does_not_bootstrap_when_gate1_still_pending(board, db_path):
    """VIỆC Execute (2026-08-03, Lead) — ĐẢO LẠI quyết định 2026-07-28 (khi đó
    ép "Waiting" cho MỌI dòng). Chưa duyệt -> Execute = "" (mới crawl, chưa có
    gì để chờ) — "Waiting" giờ nghĩa CHÍNH XÁC là "đã duyệt, đang xếp hàng",
    KHÔNG còn dùng cho "hệ thống đã thấy dòng này" nữa. TUYỆT ĐỐI không có
    job nào."""
    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["24/07/2026", "0.0", "0", "", "", "Bài chưa duyệt", "h", "u1", "PENDING", "", "", "", "", "tk-1"],
    ])
    ss.ingest_context_from_sheet(board, db_path=db_path)
    gate = ps.read_gate_status("tk-1", db_path=db_path)
    assert gate["execute"] == ""
    assert qs.list_queue(db_path=db_path) == []


# =============================================================================
# PHASE QUEUE (2026-07-27) -- ingest_context_from_sheet() phải enqueue() ĐÚNG
# LÚC Execute chuyển thành "RUN" (bootstrap Gate1 APPROVE, HOẶC NEEDS_HUMAN->
# RUN người yêu cầu thử lại) -- KHÔNG thay thế gate_status.execute (vẫn ghi y
# hệt, xem 3 test ở trên), CHỈ THÊM 1 job vào execution_queue.
# =============================================================================

def test_ingest_context_from_sheet_enqueues_job_when_bootstrapping_execute_run(board, db_path):
    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="PENDING", db_path=db_path)

    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["24/07/2026", "0.0", "0", "", "", "Bài 1", "h", "u1", "APPROVE", "", "", "", "", "tk-1"],
    ])
    ss.ingest_context_from_sheet(board, db_path=db_path)

    job = qs.find_pending("tk-1", job_type="produce", db_path=db_path)
    assert job is not None and job["status"] == "queued"


def test_ingest_context_from_sheet_enqueues_job_for_new_topic_already_approved(board, db_path):
    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["24/07/2026", "50.0", "5", "", "", "Bài mới đã duyệt ngay", "h",
         "https://cafef.vn/x.chn", "APPROVE", "", "", "", "", "tk-moi-approved"],
    ])
    ss.ingest_context_from_sheet(board, db_path=db_path)

    job = qs.find_pending("tk-moi-approved", job_type="produce", db_path=db_path)
    assert job is not None and job["status"] == "queued"


def test_ingest_context_from_sheet_enqueues_job_on_reapprove_retry(board, db_path):
    """Chạy lại sau NEEDS_HUMAN = Gate 1 chuyển PENDING -> APPROVE (thay khe
    hẹp NEEDS_HUMAN->RUN đã bỏ khi Execute thành read-only, 2026-07-28)."""
    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="PENDING", execute="NEEDS_HUMAN", db_path=db_path)

    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["24/07/2026", "0.0", "0", "", "", "Bài 1", "h", "u1", "APPROVE", "", "NEEDS_HUMAN", "", "", "tk-1"],
    ])
    ss.ingest_context_from_sheet(board, db_path=db_path)

    job = qs.find_pending("tk-1", job_type="produce", db_path=db_path)
    assert job is not None and job["status"] == "queued"


def test_ingest_context_from_sheet_does_not_enqueue_when_gate1_still_pending(board, db_path):
    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["24/07/2026", "0.0", "0", "", "", "Bài chưa duyệt", "h", "u1", "PENDING", "", "", "", "", "tk-1"],
    ])
    ss.ingest_context_from_sheet(board, db_path=db_path)
    assert qs.list_queue(db_path=db_path) == []


# =============================================================================
# TASK-031 — "Xử lý lại" (GATE1_REPROCESS): giá trị thứ 5 của Gate 1, ép chạy
# lại kể cả topic đã DONE (khác "APPROVE lại bình thường", không tự re-run
# nếu đã DONE — xem produce_from_sheet.existing_content_keys()).
# =============================================================================

def test_ingest_context_from_sheet_reprocess_normalizes_gate1_to_approve(board, db_path):
    """Sau ingest, store PHẢI thấy gate1="APPROVE" (KHÔNG lưu literal "Xử lý
    lại" -- state machine không có state riêng cho giá trị này, xem assumption
    #3 TASK-031: "gate1 quay về APPROVE y hệt lượt bình thường")."""
    from twmkt.sheets_board import GATE1_REPROCESS

    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="APPROVE", execute="DONE", output_type=["Article"], db_path=db_path)

    board._tab("CONTEXT").set_rows(_ctx_row(gate1=GATE1_REPROCESS, output_type="Article"))
    ss.ingest_context_from_sheet(board, db_path=db_path)

    gate = ps.read_gate_status("tk-1", db_path=db_path)
    assert gate["gate1"] == "APPROVE"
    assert gate["execute"] == "Waiting"


def test_ingest_context_from_sheet_reprocess_enqueues_job_with_force_payload(board, db_path):
    """Job MỚI vào hàng đợi PHẢI mang payload force=True -- queue_worker.py
    đọc lại field này để truyền `force` xuống produce_from_sheet.run(), khác
    hẳn job rerun bình thường (payload rỗng)."""
    import json as _json
    from twmkt.sheets_board import GATE1_REPROCESS

    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="APPROVE", execute="DONE", output_type=["Article"], db_path=db_path)

    board._tab("CONTEXT").set_rows(_ctx_row(gate1=GATE1_REPROCESS, output_type="Article"))
    ss.ingest_context_from_sheet(board, db_path=db_path)

    job = qs.find_pending("tk-1", job_type="produce", db_path=db_path)
    assert job is not None and job["status"] == "queued"
    assert _json.loads(job["payload_json"]) == {"force": True}


def test_ingest_context_from_sheet_reprocess_reruns_even_when_gate1_already_approve_same_output_type(board, db_path):
    """Khác rerun bình thường (chỉ enqueue khi gate1 CHUYỂN sang APPROVE hoặc
    Output Type đổi) -- "Xử lý lại" PHẢI enqueue dù gate1 đã ĐANG APPROVE VÀ
    Output Type GIỮ NGUYÊN (ca "lượt trước lỗi, thử lại y hệt" -- không đổi gì
    khác ngoài việc chọn "Xử lý lại")."""
    from twmkt.sheets_board import GATE1_REPROCESS

    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="APPROVE", execute="FAILED", output_type=["Article"], db_path=db_path)

    board._tab("CONTEXT").set_rows(_ctx_row(gate1=GATE1_REPROCESS, output_type="Article"))
    n = ss.ingest_context_from_sheet(board, db_path=db_path)

    assert n == 1   # vẫn ghi version mới (execute Waiting) dù gate1/output_type không đổi
    job = qs.find_pending("tk-1", job_type="produce", db_path=db_path)
    assert job is not None and job["status"] == "queued"


def test_ingest_context_from_sheet_reprocess_cancels_stale_pending_job_before_enqueue(board, db_path):
    """Job CŨ (nếu còn sót lại ở trạng thái 'queued', KHÔNG mang force=True) bị
    huỷ TRƯỚC KHI enqueue job MỚI -- nếu không, enqueue() dedup theo topic_key+
    job_type sẽ trả về job CŨ (không force), khiến produce_from_sheet.run()
    KHÔNG BAO GIỜ nhận được force=True cho topic này."""
    import json as _json
    from twmkt.sheets_board import GATE1_REPROCESS

    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="APPROVE", execute="Waiting", output_type=["Article"], db_path=db_path)
    old_job_id = qs.enqueue("tk-1", job_type="produce", request_id="req-cu-truoc-reprocess", db_path=db_path)

    board._tab("CONTEXT").set_rows(_ctx_row(gate1=GATE1_REPROCESS, output_type="Article"))
    ss.ingest_context_from_sheet(board, db_path=db_path)

    jobs = qs.list_queue(db_path=db_path)
    old = [j for j in jobs if j["id"] == old_job_id]
    new = [j for j in jobs if j["id"] != old_job_id]
    assert old and old[0]["status"] == "cancelled"
    assert new and new[0]["status"] == "queued"
    assert _json.loads(new[0]["payload_json"]) == {"force": True}


def test_ingest_context_from_sheet_normal_reapprove_never_carries_force_payload(board, db_path):
    """ĐỐI CHỨNG: APPROVE lại bình thường (Gate 1 rời APPROVE rồi APPROVE lại,
    KHÔNG qua "Xử lý lại") vẫn enqueue (hành vi cũ, không đổi) NHƯNG payload
    PHẢI rỗng -- KHÔNG lẫn cờ force=True, tránh mọi topic re-approve bình
    thường vô tình bị coi là "ép chạy lại"."""
    import json as _json

    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="PENDING", execute="DONE", output_type=["Article"], db_path=db_path)

    board._tab("CONTEXT").set_rows(_ctx_row(gate1="APPROVE", output_type="Article"))
    ss.ingest_context_from_sheet(board, db_path=db_path)

    job = qs.find_pending("tk-1", job_type="produce", db_path=db_path)
    assert job is not None and job["status"] == "queued"
    assert _json.loads(job["payload_json"]) == {}


def test_ingest_context_from_sheet_does_not_double_enqueue_across_two_ingest_runs(board, db_path):
    """Chạy ingest 2 LẦN liên tiếp trên CÙNG trạng thái Sheet (vd sync_all()
    gọi lặp, hay poll ngắn chạy xen giữa lúc worker CHƯA kịp claim job) -- lần
    2 KHÔNG được dồn thêm job trùng cho CÙNG topic_key. Idempotent vì 2 lớp:
    (a) enqueue chỉ chạy khi Gate 1 CHUYỂN TIẾP sang APPROVE — lần 2 store đã
    ghi APPROVE nên không còn chuyển tiếp nào (đây là lý do đọc chuyển-tiếp
    thay vì đọc trạng-thái: đọc trạng thái sẽ enqueue MỖI VÒNG POLL cho mọi
    dòng đã duyệt); (b) NẾU có re-trigger (Sheet đổi qua lại), enqueue() tự
    dedup — xem store/test_queue_store.py::
    test_enqueue_dedupes_when_already_queued_or_claimed."""
    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="PENDING", execute="NEEDS_HUMAN", db_path=db_path)

    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["24/07/2026", "0.0", "0", "", "", "Bài 1", "h", "u1", "APPROVE", "", "NEEDS_HUMAN", "", "", "tk-1"],
    ])
    ss.ingest_context_from_sheet(board, db_path=db_path)
    ss.ingest_context_from_sheet(board, db_path=db_path)

    assert len(qs.list_queue(db_path=db_path)) == 1


# =============================================================================
# GATE 2 -> hàng đợi (2026-07-28, yêu cầu Lead: "Scheduler phải kiểm tra được
# cả 3 trạng thái"). Gate 1 -> job "produce"; Gate 2 -> job "render_assets";
# Gate 3 CỐ Ý không sinh job (vẫn PENDING chờ hệ thống hoàn thiện).
# =============================================================================

def _content_rows_with_gate2(gate2: str, gate3: str = "PENDING"):
    return [
        CONTENT_HEADER,
        ["24/07/2026", "Bài 1", "infographic", "DONE", "{}", "", gate2, "tk-1", "[]", "",
         "", "", gate3, ""],
    ]


def test_ingest_content_enqueues_render_assets_job_on_gate2_approve(board, db_path):
    ps.write_raw("tk-1", {"context": "Bài 1"}, db_path=db_path)
    ps.write_content_output("tk-1", "infographic", {"status": "DONE", "output": "{}",
                                                    "notes": "", "facts": "[]"}, db_path=db_path)

    board._tab("CONTENT").set_rows(_content_rows_with_gate2("APPROVE"))
    ss.ingest_content_from_sheet(board, db_path=db_path)

    jobs = qs.list_queue(db_path=db_path)
    assert [(j["topic_key"], j["job_type"]) for j in jobs] == [("tk-1", "render_assets")]


def test_ingest_content_does_not_enqueue_when_gate2_still_pending(board, db_path):
    ps.write_raw("tk-1", {"context": "Bài 1"}, db_path=db_path)
    ps.write_content_output("tk-1", "infographic", {"status": "DONE", "output": "{}",
                                                    "notes": "", "facts": "[]"}, db_path=db_path)

    board._tab("CONTENT").set_rows(_content_rows_with_gate2("PENDING"))
    ss.ingest_content_from_sheet(board, db_path=db_path)
    assert qs.list_queue(db_path=db_path) == []


def test_ingest_content_does_not_double_enqueue_render_assets(board, db_path):
    """CÙNG lý do Gate 1: bắt CHUYỂN TIẾP, không phải trạng thái -- nếu không,
    mỗi vòng poll sẽ dồn thêm 1 job render (tốn tiền API ảnh thật)."""
    ps.write_raw("tk-1", {"context": "Bài 1"}, db_path=db_path)
    ps.write_content_output("tk-1", "infographic", {"status": "DONE", "output": "{}",
                                                    "notes": "", "facts": "[]"}, db_path=db_path)

    board._tab("CONTENT").set_rows(_content_rows_with_gate2("APPROVE"))
    ss.ingest_content_from_sheet(board, db_path=db_path)
    ss.ingest_content_from_sheet(board, db_path=db_path)
    ss.ingest_content_from_sheet(board, db_path=db_path)

    assert len(qs.list_queue(db_path=db_path)) == 1


def test_ingest_content_gate3_approve_never_enqueues_any_job(board, db_path):
    """Gate 3 vẫn là cổng NGƯỜI thuần (quyết định Lead: để PENDING chờ hệ
    thống hoàn thiện) -- người bấm APPROVE ở Gate 3 chỉ được GHI vào store,
    TUYỆT ĐỐI không kích hoạt tiến trình máy nào."""
    ps.write_raw("tk-1", {"context": "Bài 1"}, db_path=db_path)
    ps.write_content_output("tk-1", "infographic", {"status": "DONE", "output": "{}",
                                                    "notes": "", "facts": "[]"}, db_path=db_path)
    ps.write_content_status("tk-1", "infographic", gate2="APPROVE", db_path=db_path)

    board._tab("CONTENT").set_rows(_content_rows_with_gate2("APPROVE", gate3="APPROVE"))
    ss.ingest_content_from_sheet(board, db_path=db_path)

    assert ps.read_content_status("tk-1", "infographic", db_path=db_path)["gate3"] == "APPROVE"
    assert qs.list_queue(db_path=db_path) == []   # gate2 đã APPROVE từ trước -> không chuyển tiếp


# =============================================================================
# AssetPath — bug bắt được ở lượt e2e thật 2026-07-28: render_production_assets
# ghi THẲNG ô Sheet, rồi queue_worker gọi render_content_to_sheet() vài giây
# sau dựng lại tab từ store -> XOÁ SẠCH link vừa ghi. Ảnh render thành công
# nhưng Gate 3 không có gì để bấm. Nay asset_url ĐI QUA STORE.
# =============================================================================

def test_render_content_to_sheet_shows_asset_hyperlink_from_store(board, db_path):
    ps.write_raw("tk-1", {"context": "Bài 1"}, db_path=db_path)
    ps.write_content_output("tk-1", "infographic", {"status": "DONE", "output": "{}",
                                                    "notes": "", "facts": "[]"}, db_path=db_path)
    ps.write_content_status("tk-1", "infographic", gate2="APPROVE",
                            asset_url="http://127.0.0.1:8800/a/b_9x16.png",
                            asset_local_path="D:/x/b_9x16.png", db_path=db_path)

    ss.render_content_to_sheet(board, db_path=db_path)
    grid = board._tab("CONTENT").get_all_values()
    cell = grid[1][_header_index(grid[0], "AssetPath")]
    assert cell == '=HYPERLINK("http://127.0.0.1:8800/a/b_9x16.png", "Mở file")'


def test_render_content_to_sheet_survives_repeated_render_without_losing_asset(board, db_path):
    """ĐÚNG kịch bản đã gãy: render lại NHIỀU LẦN (worker làm sau mỗi job)
    KHÔNG được làm mất AssetPath."""
    ps.write_raw("tk-1", {"context": "Bài 1"}, db_path=db_path)
    ps.write_content_output("tk-1", "infographic", {"status": "DONE", "output": "{}",
                                                    "notes": "", "facts": "[]"}, db_path=db_path)
    ps.write_content_status("tk-1", "infographic", asset_url="http://h/x.png", db_path=db_path)

    ss.render_content_to_sheet(board, db_path=db_path)
    first = board._tab("CONTENT").get_all_values()
    ss.ingest_content_from_sheet(board, db_path=db_path)
    ss.render_content_to_sheet(board, db_path=db_path)
    assert board._tab("CONTENT").get_all_values() == first


def test_asset_cell_falls_back_to_local_path_then_empty():
    assert ss._asset_cell({"asset_local_path": "D:/x.png"}) == "D:/x.png"
    assert ss._asset_cell({}) == ""


def test_asset_cell_matches_render_script_formula():
    """2 lối ghi ô AssetPath (store->Sheet ở đây, và ghi thẳng ở
    scripts/render_production_assets.py cho đường chạy tay) PHẢI cho ra CÙNG
    chuỗi -- lệch nhau là ô nhấp nháy đổi giá trị mỗi lượt render."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_rpa", os.path.join(REPO_ROOT, "scripts", "render_production_assets.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_rpa"] = mod
    spec.loader.exec_module(mod)

    url = "http://127.0.0.1:8800/a/b.png"
    assert ss._asset_cell({"asset_url": url}) == mod.asset_hyperlink_formula(url)


# =============================================================================
# REQUEST ID + HUỶ YÊU CẦU (2026-07-28, quyết định Lead)
# =============================================================================

def _ctx_row(gate1="APPROVE", output_type="", key="tk-1", execute=""):
    return [CONTEXT_HEADER,
            ["28/07/2026", "0.0", "0", "", "", "Bài 1", "h", "u1", gate1,
             output_type, execute, "", "", key]]


def test_cancel_pending_when_gate1_leaves_approve(board, db_path):
    """Người RÚT duyệt -> job đang xếp hàng trở nên vô nghĩa (nó sẽ sinh nội
    dung cho yêu cầu vừa bị bỏ). Phải huỷ, không để chạy.

    VIỆC Execute (2026-08-03, Lead) — Execute về "" (không phải "Waiting")
    sau khi rút duyệt: "Waiting" giờ nghĩa CHÍNH XÁC "đã duyệt, đang xếp
    hàng" — rút duyệt thì không còn gì xếp hàng, "" (chưa duyệt) đúng hơn."""
    ps.write_raw("tk-1", {"context": "Bài 1"}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="APPROVE", execute="Waiting", db_path=db_path)
    qs.enqueue("tk-1", job_type="produce", db_path=db_path)

    board._tab("CONTEXT").set_rows(_ctx_row(gate1="PENDING"))
    ss.ingest_context_from_sheet(board, db_path=db_path)

    jobs = qs.list_queue(db_path=db_path)
    assert [j["status"] for j in jobs] == ["cancelled"]
    assert ps.read_gate_status("tk-1", db_path=db_path)["execute"] == ""


def test_change_output_type_cancels_old_request_and_creates_new(board, db_path):
    """Đổi Output Type = huỷ yêu cầu CŨ + tạo yêu cầu MỚI (request_id khác)."""
    ps.write_raw("tk-1", {"context": "Bài 1"}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="APPROVE", output_type=["Article"],
                         execute="DONE", db_path=db_path)
    qs.enqueue("tk-1", job_type="produce", request_id="req-cu", db_path=db_path)

    board._tab("CONTEXT").set_rows(_ctx_row(output_type="Infographic"))
    ss.ingest_context_from_sheet(board, db_path=db_path)

    jobs = qs.list_queue(db_path=db_path)
    old = [j for j in jobs if j["request_id"] == "req-cu"]
    new = [j for j in jobs if j["request_id"] != "req-cu"]
    assert old and old[0]["status"] == "cancelled"
    assert new and new[0]["status"] == "queued"
    assert ps.read_gate_status("tk-1", db_path=db_path)["execute"] == "Waiting"


def test_running_job_locks_out_user_changes(board, db_path):
    """Job 'claimed' -> BỎ QUA mọi thay đổi người vừa gõ. Nhận yêu cầu chồng
    lên việc đang làm dở chỉ đẻ trạng thái mâu thuẫn."""
    ps.write_raw("tk-1", {"context": "Bài 1"}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="APPROVE", output_type=["Article"],
                         execute="Running...", db_path=db_path)
    qs.enqueue("tk-1", job_type="produce", db_path=db_path)
    qs.claim_next("w1", db_path=db_path)          # -> claimed

    board._tab("CONTEXT").set_rows(_ctx_row(gate1="REJECT", output_type="Video"))
    ss.ingest_context_from_sheet(board, db_path=db_path)

    g = ps.read_gate_status("tk-1", db_path=db_path)
    assert g["gate1"] == "APPROVE"                 # KHÔNG nhận REJECT
    assert g["output_type"] == ["Article"]         # KHÔNG nhận Video
    assert [j["status"] for j in qs.list_queue(db_path=db_path)] == ["claimed"]


def test_cancel_render_job_when_gate2_leaves_approve(board, db_path):
    """Rút Gate 2 -> huỷ job render. Quan trọng hơn Gate 1 vì render TỐN TIỀN
    THẬT (ảnh gpt-image-2, hoặc cả lượt dựng video)."""
    ps.write_raw("tk-1", {"context": "Bài 1"}, db_path=db_path)
    ps.write_content_output("tk-1", "infographic", {"status": "DONE", "output": "{}",
                                                    "notes": "", "facts": "[]"}, db_path=db_path)
    ps.write_content_status("tk-1", "infographic", gate2="APPROVE", db_path=db_path)
    qs.enqueue("tk-1", job_type="render_assets", db_path=db_path)

    board._tab("CONTENT").set_rows([
        CONTENT_HEADER,
        ["28/07/2026", "Bài 1", "infographic", "DONE", "{}", "", "PENDING", "tk-1", "[]", "",
         "", "PENDING", ""],
    ])
    ss.ingest_content_from_sheet(board, db_path=db_path)
    assert [j["status"] for j in qs.list_queue(db_path=db_path)] == ["cancelled"]


def test_cancel_pending_never_touches_running_job(db_path):
    """Job 'claimed' KHÔNG bị huỷ (quyết định Lead): giết giữa chừng 1 lượt gọi
    LLM/render là nguồn bug khó truy — cứ để chạy hết, không đạt thì chạy lại."""
    qs.enqueue("tk-1", job_type="produce", db_path=db_path)
    qs.claim_next("w1", db_path=db_path)
    assert qs.cancel_pending("tk-1", db_path=db_path) == 0
    assert [j["status"] for j in qs.list_queue(db_path=db_path)] == ["claimed"]


def test_reconcile_recovers_lost_transition(board, db_path):
    """BUG THẬT 2026-07-29: store ghi gate1=APPROVE xong thì tiến trình CHẾT
    trước khi enqueue (worker crash vì DB thiếu cột). Chuyển tiếp đã bị TIÊU
    THỤ nên không lần ingest nào cứu được — topic nằm im ở Waiting mãi mãi."""
    ps.write_raw("tk-1", {"context": "Bài 1"}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="APPROVE", execute="Waiting",
                         output_type=["Video"], db_path=db_path)
    assert qs.list_queue(db_path=db_path) == []          # đúng trạng thái kẹt

    assert ss.reconcile_pending_requests(db_path=db_path) == 1
    jobs = qs.list_queue(db_path=db_path)
    assert [(j["topic_key"], j["status"]) for j in jobs] == [("tk-1", "queued")]


def test_reconcile_does_not_resurrect_finished_or_queued_work(board, db_path):
    """Không được dựng lại việc ĐÃ XONG hoặc ĐANG chờ — nếu không, mỗi vòng
    poll sẽ đẻ thêm job cho mọi topic đã duyệt."""
    ps.write_raw("done", {"context": "A"}, db_path=db_path)
    ps.write_gate_status("done", gate1="APPROVE", execute="DONE", db_path=db_path)
    ps.write_raw("pending-gate", {"context": "B"}, db_path=db_path)
    ps.write_gate_status("pending-gate", gate1="PENDING", execute="Waiting", db_path=db_path)
    ps.write_raw("co-job", {"context": "C"}, db_path=db_path)
    ps.write_gate_status("co-job", gate1="APPROVE", execute="Waiting", db_path=db_path)
    qs.enqueue("co-job", job_type="produce", db_path=db_path)

    assert ss.reconcile_pending_requests(db_path=db_path) == 0
    assert len(qs.list_queue(db_path=db_path)) == 1


def test_render_preserves_original_timestamp_not_today(board, db_path):
    """BUG THẬT (Lead báo 2026-07-29): render KHÔNG truyền `ts` -> context_row
    lấy now() -> MỖI LƯỢT RENDER ghi đè Timestamp thành hôm nay. Mọi dòng crawl
    hoá thành hôm nay, mất hẳn khả năng phân biệt tin theo ngày.

    Ngày dùng ở đây LUÔN tương đối với `date.today()` (KHÔNG hard-code
    "28/07/2026") -- ngày cứng trôi ra ngoài cửa sổ `display_days` mặc định (7
    ngày) khi "hôm nay" của môi trường chạy test tiến xa hơn ngày viết test,
    khiến dòng bị `_visible_rows()` ẩn đi và assert dưới sai kiểu IndexError,
    không phải sai logic Timestamp đang test."""
    from datetime import date, timedelta
    old_day = (date.today() - timedelta(days=1)).strftime("%d/%m/%Y")
    ps.write_raw("tk-1", {"context": "Bài cũ", "timestamp": old_day}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="PENDING", db_path=db_path)
    ps.write_content_output("tk-1", "article", {"status": "DONE", "output": "x",
                                                "notes": "", "facts": "[]",
                                                "timestamp": old_day}, db_path=db_path)

    ss.render_context_to_sheet(board, db_path=db_path)
    ss.render_content_to_sheet(board, db_path=db_path)

    ctx = board._tab("CONTEXT").get_all_values()
    assert ctx[1][_header_index(ctx[0], "Timestamp")] == old_day
    con = board._tab("CONTENT").get_all_values()
    assert con[1][_header_index(con[0], "Timestamp")] == old_day


def test_ingest_stores_sheet_timestamp_for_new_topic(board, db_path):
    """Timestamp gốc do review_to_sheet.py ghi lúc crawl phải đi VÀO store,
    ghi 1 lần rồi bất biến."""
    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["28/07/2026", "0.0", "0", "", "", "Bài mới", "h", "u1", "PENDING", "", "", "", "", "tk-new"],
    ])
    ss.ingest_context_from_sheet(board, db_path=db_path)
    assert ps.read_raw("tk-new", db_path=db_path)["timestamp"] == "28/07/2026"


# =============================================================================
# KHÔI PHỤC 100% (2026-07-29, yêu cầu Lead): "DB là nguồn dữ liệu đầy đủ tin
# cậy, có thể khôi phục 100% cho Sheet UI khi cần." Test kiểm nghiệm ĐÚNG kịch
# bản Lead nêu: xoá sạch bảng -> dựng lại -> phải GIỐNG HỆT từng ô.
# =============================================================================

def _seed_full_state(db_path):
    """Dựng 1 trạng thái ĐẦY ĐỦ mọi loại dữ liệu người + máy."""
    ps.write_raw("tk-a", {"context": "Bài A", "hook": "hook A", "source": "https://cafef.vn/a.chn",
                          "tickers": ["FPT", "ACB"], "group": "CoPhieu", "topic": "CoPhieu",
                          "score": 7, "hot_pct": 62.0, "timestamp": _SEED_YESTERDAY}, db_path=db_path)
    ps.write_gate_status("tk-a", gate1="APPROVE", execute="DONE", notes="ghi chú người",
                         output_type=["Article", "Infographic"], db_path=db_path)
    ps.write_content_output("tk-a", "article", {"status": "DONE", "output": "x" * 3000,
                                                "notes": "", "facts": "[]",
                                                "timestamp": _SEED_TODAY,
                                                "published_at": _SEED_YESTERDAY}, db_path=db_path)
    ps.write_content_status("tk-a", "article", gate2="APPROVE", gate3="APPROVE",
                            social_link="https://fb.com/p/1", posting_status="Đã đăng",
                            asset_url="https://drive.google.com/file/d/X/view", db_path=db_path)
    ps.write_content_output("tk-a", "infographic", {"status": "SKIPPED", "output": "",
                                                    "notes": "router từ chối", "facts": "[]",
                                                    "timestamp": _SEED_TODAY}, db_path=db_path)
    ps.write_content_status("tk-a", "infographic", gate2="PENDING", db_path=db_path)

    ps.write_raw("tk-b", {"context": "Bài B", "hook": "hook B", "source": "https://vietstock.vn/b",
                          "tickers": [], "group": "ChinhSach", "topic": "ChinhSach",
                          "score": 3, "hot_pct": 20.0, "timestamp": _SEED_TODAY}, db_path=db_path)
    ps.write_gate_status("tk-b", gate1="PENDING", execute="Waiting", db_path=db_path)


def test_full_restore_after_wiping_both_tabs(board, db_path):
    """KỊCH BẢN LEAD: xoá TOÀN BỘ dữ liệu 2 tab -> render lại từ store -> phải
    khớp TỪNG Ô với trước khi xoá. Đây là thước đo "DB đủ tin cậy": bất kỳ
    trường nào chỉ sống trên Sheet mà không vào store sẽ làm test này đỏ."""
    _seed_full_state(db_path)
    ss.render_context_to_sheet(board, db_path=db_path)
    ss.render_content_to_sheet(board, db_path=db_path)
    before_ctx = board._tab("CONTEXT").get_all_values()
    before_con = board._tab("CONTENT").get_all_values()

    # Người xoá sạch (giữ mỗi header) — mô phỏng sự cố thật.
    board._tab("CONTEXT").set_rows([CONTEXT_HEADER])
    board._tab("CONTENT").set_rows([CONTENT_HEADER])

    ss.render_context_to_sheet(board, db_path=db_path)
    ss.render_content_to_sheet(board, db_path=db_path)

    assert board._tab("CONTEXT").get_all_values() == before_ctx
    assert board._tab("CONTENT").get_all_values() == before_con


def test_restore_keeps_every_user_owned_field(board, db_path):
    """Soi TỪNG cột NGƯỜI-SỞ-HỮU sau khôi phục — đây là nhóm dễ mất nhất vì
    máy không tự sinh lại được: mất là mất vĩnh viễn."""
    _seed_full_state(db_path)
    board._tab("CONTEXT").set_rows([CONTEXT_HEADER])
    board._tab("CONTENT").set_rows([CONTENT_HEADER])
    ss.render_context_to_sheet(board, db_path=db_path)
    ss.render_content_to_sheet(board, db_path=db_path)

    ctx = board._tab("CONTEXT").get_all_values()
    row_a = next(r for r in ctx[1:] if r[_header_index(ctx[0], "TopicKey")] == "tk-a")
    assert row_a[_header_index(ctx[0], GATE1_COL)] == "APPROVE"
    assert row_a[_header_index(ctx[0], "Notes")] == "ghi chú người"
    assert row_a[_header_index(ctx[0], OUTPUT_TYPE_COL)] == "Article, Infographic"
    assert row_a[_header_index(ctx[0], "Timestamp")] == _SEED_YESTERDAY

    con = board._tab("CONTENT").get_all_values()
    art = next(r for r in con[1:] if r[_header_index(con[0], "Type")] == "Article")   # VIỆC 3: nhãn hiển thị
    assert art[_header_index(con[0], GATE2_COL)] == "APPROVE"
    assert art[_header_index(con[0], GATE3_COL)] == "APPROVE"
    assert art[_header_index(con[0], "Social Link")] == "https://fb.com/p/1"
    assert art[_header_index(con[0], "Posting Status")] == "Đã đăng"
    assert "drive.google.com" in art[_header_index(con[0], "AssetPath")]
    # VIỆC 3.1 (2026-08-04): Timestamp CONTENT giờ ưu tiên published_at (ngày
    # ĐĂNG BÀI GỐC, cùng ý nghĩa cột CONTEXT) — KHÁC "ngày xử lý" cũ.
    assert art[_header_index(con[0], "Timestamp")] == _SEED_YESTERDAY


def test_store_keeps_both_publish_and_produce_dates(db_path):
    """Hai mốc thời gian phải cùng tồn tại trong DB (quyết định Lead
    2026-07-29): trùng nhau khi crawl+xử lý cùng ngày, KHÁC khi người duyệt
    sản xuất vào ngày sau. Chỉ lưu 1 mốc là mất khả năng phân biệt."""
    _seed_full_state(db_path)
    rec = ps.read_content_output("tk-a", "article", db_path=db_path)
    assert rec["timestamp"] == _SEED_TODAY        # ngày xử lý
    assert rec["published_at"] == _SEED_YESTERDAY  # ngày đăng bài gốc
    assert rec["timestamp"] != rec["published_at"]


def test_restore_is_idempotent_across_repeated_renders(board, db_path):
    """Render nhiều lần liên tiếp KHÔNG được làm trôi giá trị nào (đây chính
    là bug Timestamp 2026-07-29: mỗi lượt render ghi đè ngày thành hôm nay)."""
    _seed_full_state(db_path)
    ss.render_context_to_sheet(board, db_path=db_path)
    first = board._tab("CONTEXT").get_all_values()
    for _ in range(3):
        ss.render_context_to_sheet(board, db_path=db_path)
    assert board._tab("CONTEXT").get_all_values() == first


# =============================================================================
# XOÁ CHỦ ĐỀ — Gate 1 = "DELETE" (2026-07-29, quyết định Lead)
# =============================================================================

def test_gate1_delete_removes_topic_from_db_and_sheet(board, db_path):
    """DELETE = xoá HẲN khỏi DB; dòng tự biến mất khỏi Sheet ở lượt render kế
    tiếp vì store không còn dữ liệu. KHÔNG hoàn tác được."""
    ps.write_raw("tk-xoa", {"context": "Bài bỏ", "timestamp": "29/07/2026"}, db_path=db_path)
    ps.write_gate_status("tk-xoa", gate1="APPROVE", execute="DONE", db_path=db_path)
    ps.write_content_output("tk-xoa", "article", {"status": "DONE", "output": "x",
                                                  "notes": "", "facts": "[]"}, db_path=db_path)
    ps.write_raw("tk-giu", {"context": "Bài giữ", "timestamp": "29/07/2026"}, db_path=db_path)
    ps.write_gate_status("tk-giu", gate1="PENDING", db_path=db_path)

    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["29/07/2026", "0", "0", "", "", "Bài bỏ", "h", "u", "DELETE", "", "", "", "", "tk-xoa"],
        ["29/07/2026", "0", "0", "", "", "Bài giữ", "h", "u", "PENDING", "", "", "", "", "tk-giu"],
    ])
    ss.ingest_context_from_sheet(board, db_path=db_path)

    assert ps.read_raw("tk-xoa", db_path=db_path) is None
    assert ps.read_content_output("tk-xoa", "article", db_path=db_path) is None
    assert ps.read_raw("tk-giu", db_path=db_path) is not None   # KHÔNG đụng chủ đề khác

    ss.render_context_to_sheet(board, db_path=db_path)
    grid = board._tab("CONTEXT").get_all_values()
    keys = [r[_header_index(grid[0], "TopicKey")] for r in grid[1:]]
    assert keys == ["tk-giu"]


def test_gate1_delete_cancels_pending_jobs(board, db_path):
    """Xoá chủ đề -> job chờ của nó phải bị huỷ, không được chạy tiếp."""
    ps.write_raw("tk-1", {"context": "A"}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="APPROVE", db_path=db_path)
    qs.enqueue("tk-1", job_type="produce", db_path=db_path)

    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["29/07/2026", "0", "0", "", "", "A", "h", "u", "DELETE", "", "", "", "", "tk-1"],
    ])
    ss.ingest_context_from_sheet(board, db_path=db_path)
    # delete_topic xoá luôn hàng đợi của topic -> không còn job nào sót lại.
    assert qs.list_queue(db_path=db_path) == []


def test_gate1_delete_on_new_topic_does_not_create_it(board, db_path):
    """Người gõ DELETE cho dòng crawl mới (chưa vào store) -> KHÔNG được nạp
    vào store rồi mới xoá; phải bỏ qua hẳn."""
    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["29/07/2026", "0", "0", "", "", "Bài mới", "h", "u", "DELETE", "", "", "", "", "tk-moi"],
    ])
    ss.ingest_context_from_sheet(board, db_path=db_path)
    assert ps.read_raw("tk-moi", db_path=db_path) is None


def test_delete_topic_requires_key_and_leaves_others(db_path):
    ps.write_raw("a", {"context": "A"}, db_path=db_path)
    ps.write_raw("b", {"context": "B"}, db_path=db_path)
    assert ds.delete_topic("a", db_path=db_path) >= 1
    assert ps.read_raw("a", db_path=db_path) is None
    assert ps.read_raw("b", db_path=db_path) is not None
    try:
        ds.delete_topic("  ", db_path=db_path)
    except ValueError:
        pass
    else:
        raise AssertionError("topic_key rỗng phải raise ValueError")


def test_delete_removes_sheet_row_immediately_bottom_up(board, db_path):
    """Realtime (2026-07-29): xoá dòng NGAY, và xoá TỪ DƯỚI LÊN — xoá dòng
    trên trước làm mọi chỉ số dưới nó dịch lên 1, các lần xoá sau nhắm sai
    dòng (lỗi kinh điển khi xoá theo chỉ số)."""
    deleted = []
    board.delete_row = lambda tab, row: deleted.append((tab, row))
    for k in ("tk-1", "tk-2", "tk-3"):
        ps.write_raw(k, {"context": k}, db_path=db_path)
        ps.write_gate_status(k, gate1="PENDING", db_path=db_path)

    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["29/07/2026", "0", "0", "", "", "1", "h", "u", "DELETE", "", "", "", "", "tk-1"],
        ["29/07/2026", "0", "0", "", "", "2", "h", "u", "PENDING", "", "", "", "", "tk-2"],
        ["29/07/2026", "0", "0", "", "", "3", "h", "u", "DELETE", "", "", "", "", "tk-3"],
    ])
    ss.ingest_context_from_sheet(board, db_path=db_path)

    assert deleted == [("CONTEXT", 4), ("CONTEXT", 2)]   # dưới lên, KHÔNG phải 2 rồi 4
    assert ps.read_raw("tk-2", db_path=db_path) is not None


def test_render_never_clears_whole_tab(board, db_path):
    """CỐT LÕI 2026-07-29: `clear()` xoá CẢ ĐỊNH DẠNG -> băng màu và thiết lập
    người dựng tay bay sau MỖI lượt render. Khoá lại: render KHÔNG được gọi
    clear() trên cả tab."""
    called = []
    ws = board._tab("CONTEXT")
    ws.clear = lambda: called.append("clear")
    ps.write_raw("tk-1", {"context": "A", "timestamp": "29/07/2026"}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="PENDING", db_path=db_path)

    ss.render_context_to_sheet(board, db_path=db_path)
    assert called == [], "render KHÔNG được clear() cả tab (mất định dạng)"


def test_context_rows_sorted_into_day_blocks_newest_at_bottom(board, db_path):
    """Quy ước Lead: khối NGÀY liền nhau, và ngày MỚI NHẤT nằm DƯỚI CÙNG —
    người vận hành cuộn xuống cuối là thấy việc hôm nay, dòng mới không đẩy
    dòng cũ trôi chỗ."""
    from datetime import date, timedelta
    d0 = date.today()
    d1 = d0 - timedelta(days=1)
    older, newer = d1.strftime("%d/%m/%Y"), d0.strftime("%d/%m/%Y")
    for k, day, hot in (("a", older, 10.0), ("b", newer, 5.0),
                        ("c", older, 90.0), ("d", newer, 99.0)):
        ps.write_raw(k, {"context": k, "timestamp": day, "hot_pct": hot}, db_path=db_path)
        ps.write_gate_status(k, gate1="PENDING", db_path=db_path)

    ss.render_context_to_sheet(board, db_path=db_path)
    grid = board._tab("CONTEXT").get_all_values()
    i_ts = _header_index(grid[0], "Timestamp")
    assert [r[i_ts] for r in grid[1:]] == [older, older, newer, newer]


def test_context_same_day_rows_keep_crawl_order_not_hot_pct_or_alphabetical(board, db_path):
    """SỬA LỖI THẬT (2026-08-03, Lead: "dữ liệu trong cùng ngày bị xếp lẫn
    lộn") -- BỎ tie-break theo Hot% (không phản ánh thứ tự crawl); topic_key
    ở đây CỐ Ý đặt ngược alphabet ("zzz" < "aaa" theo THỨ TỰ GHI) để phân biệt
    rõ 2 khả năng sai: nếu còn sort theo topic_key (list_topics() ORDER BY
    topic_key) thì "aaa" sẽ lên trước "zzz" dù "zzz" crawl trước -- sai. Đúng
    phải là first_created_at() (bản ghi ĐẦU TIÊN) -> "zzz" trước "aaa"."""
    from datetime import date
    day = date.today().strftime("%d/%m/%Y")
    ps.write_raw("zzz", {"context": "zzz", "timestamp": day, "hot_pct": 1.0}, db_path=db_path)
    ps.write_gate_status("zzz", gate1="PENDING", db_path=db_path)
    ps.write_raw("aaa", {"context": "aaa", "timestamp": day, "hot_pct": 99.0}, db_path=db_path)
    ps.write_gate_status("aaa", gate1="PENDING", db_path=db_path)

    ss.render_context_to_sheet(board, db_path=db_path)
    grid = board._tab("CONTEXT").get_all_values()
    i_ctx = _header_index(grid[0], "Context")
    assert [r[i_ctx] for r in grid[1:]] == ["zzz", "aaa"], \
        "phải theo thứ tự CRAWL (zzz trước), không theo Hot% (aaa cao hơn) hay alphabet"


def test_context_hides_rows_older_than_display_days(board, db_path):
    """Sheet là BẢNG LÀM VIỆC: chỉ hiện `sheets.display_days` ngày gần nhất.
    Dòng cũ VẪN nằm nguyên trong DB — không xoá gì, chỉ không hiển thị."""
    from datetime import date, timedelta
    from twmkt.config import Settings as _S
    today = date.today()
    for k, delta in (("moi", 0), ("cu", 30)):
        d = (today - timedelta(days=delta)).strftime("%d/%m/%Y")
        ps.write_raw(k, {"context": k, "timestamp": d}, db_path=db_path)
        ps.write_gate_status(k, gate1="PENDING", db_path=db_path)

    ss.render_context_to_sheet(board, db_path=db_path, settings=_S({"sheets": {"display_days": 7}}))
    grid = board._tab("CONTEXT").get_all_values()
    keys = [r[_header_index(grid[0], "TopicKey")] for r in grid[1:]]
    assert keys == ["moi"]
    assert ps.read_raw("cu", db_path=db_path) is not None      # DB giữ nguyên

    # display_days=0 -> hiện tất cả (đường thoát soi lịch sử)
    ss.render_context_to_sheet(board, db_path=db_path, settings=_S({"sheets": {"display_days": 0}}))
    grid = board._tab("CONTEXT").get_all_values()
    assert len(grid) - 1 == 2
