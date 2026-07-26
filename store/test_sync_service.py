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
    assert row[_header_index(header, "Type")] == "article"
    assert row[_header_index(header, "Status")] == "DONE"
    assert row[_header_index(header, GATE2_COL)] == "PENDING"
    assert row[_header_index(header, GATE3_COL)] == "PENDING"


def test_render_content_to_sheet_reflects_gate2_gate3_social_posting_after_ingest(board, db_path):
    ps.write_raw("tk-1", {"context": "Bài 1"}, db_path=db_path)
    ps.write_content_output("tk-1", "article", {"status": "DONE", "output": "x",
                                                "notes": "", "facts": "[]"}, db_path=db_path)

    board._tab("CONTENT").set_rows([
        CONTENT_HEADER,
        ["24/07/2026", "Bài 1", "article", "DONE", "x", "", "APPROVE", "tk-1", "[]", "",
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


def test_render_content_to_sheet_uses_asset_url_over_local_path(board, db_path):
    ps.write_raw("tk-1", {"context": "Bài 1"}, db_path=db_path)
    ps.write_content_output("tk-1", "infographic", {"status": "DONE", "output": "{}",
                                                     "notes": "", "facts": "[]"}, db_path=db_path)
    ps.write_content_status("tk-1", "infographic", asset_url="https://drive.google.com/x",
                            asset_local_path="/local/x.png", db_path=db_path)
    ss.render_content_to_sheet(board, db_path=db_path)
    grid = board._tab("CONTENT").get_all_values()
    header, row = grid[0], grid[1]
    assert row[_header_index(header, "AssetPath")] == "https://drive.google.com/x"


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


def test_ingest_context_from_sheet_skips_rows_without_topic_key(board, db_path):
    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["24/07/2026", "0.0", "0", "", "", "Bài chưa có khoá", "h", "u1", "PENDING", "", "", "", "", ""],
    ])
    n = ss.ingest_context_from_sheet(board, db_path=db_path)
    assert n == 0
    assert ds.list_topics(db_path=db_path) == []


def test_ingest_context_from_sheet_execute_needs_human_to_run_exception(board, db_path):
    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="APPROVE", execute="NEEDS_HUMAN", db_path=db_path)

    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["24/07/2026", "0.0", "0", "", "", "Bài 1", "h", "u1", "APPROVE", "", "RUN", "", "", "tk-1"],
    ])

    n = ss.ingest_context_from_sheet(board, db_path=db_path)
    assert n == 1
    assert ps.read_gate_status("tk-1", db_path=db_path)["execute"] == "RUN"


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
        ["24/07/2026", "Bài 1", "article", "DONE", "x", "", "APPROVE", "tk-1", "[]", "",
         "https://fb.com/1", "APPROVE", "Đã đăng"],
    ])

    n = ss.ingest_content_from_sheet(board, db_path=db_path)
    assert n == 1
    status = ps.read_content_status("tk-1", "article", db_path=db_path)
    assert status["gate2"] == "APPROVE"
    assert status["social_link"] == "https://fb.com/1"
    assert status["gate3"] == "APPROVE"
    assert status["posting_status"] == "Đã đăng"


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


def test_render_context_to_sheet_output_type_empty_when_never_set(board, db_path):
    ps.write_raw("tk-1", {"context": "Bài 1", "hook": "h", "source": "u1",
                          "tickers": [], "group": "", "topic": ""}, db_path=db_path)
    ps.write_gate_status("tk-1", gate1="PENDING", db_path=db_path)
    ss.render_context_to_sheet(board, db_path=db_path)
    grid = board._tab("CONTEXT").get_all_values()
    header, row = grid[0], grid[1]
    assert row[_header_index(header, OUTPUT_TYPE_COL)] == ""   # rỗng = AUTO


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
    assert gate["execute"] == "RUN"


def test_ingest_context_from_sheet_bridges_new_topic_already_approved_bootstraps_run(board, db_path):
    """review_to_sheet.py KHÔNG tự đặt Execute -- topic mới nạp vào store lần
    đầu mà Sheet đã Gate1=APPROVE (người duyệt rất nhanh) vẫn phải bootstrap
    Execute=RUN NGAY, không phải chờ 1 lượt ingest thứ 2."""
    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["24/07/2026", "50.0", "5", "", "", "Bài mới đã duyệt ngay", "h",
         "https://cafef.vn/x.chn", "APPROVE", "", "", "", "", "tk-moi-approved"],
    ])
    ss.ingest_context_from_sheet(board, db_path=db_path)
    gate = ps.read_gate_status("tk-moi-approved", db_path=db_path)
    assert gate["gate1"] == "APPROVE"
    assert gate["execute"] == "RUN"


def test_ingest_context_from_sheet_does_not_bootstrap_when_gate1_still_pending(board, db_path):
    board._tab("CONTEXT").set_rows([
        CONTEXT_HEADER,
        ["24/07/2026", "0.0", "0", "", "", "Bài chưa duyệt", "h", "u1", "PENDING", "", "", "", "", "tk-1"],
    ])
    ss.ingest_context_from_sheet(board, db_path=db_path)
    gate = ps.read_gate_status("tk-1", db_path=db_path)
    assert "execute" not in gate   # KHÔNG bootstrap khi chưa duyệt
