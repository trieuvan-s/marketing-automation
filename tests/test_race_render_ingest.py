"""REGRESSION TEST cho bug CHƯA VÁ — race giữa render_context_to_sheet() và
ingest_context_from_sheet() (store/sync_service.py), phát hiện qua TASK-028
(handoffs/TASK-028-agent-b.md, Triệu chứng 3: "Gate 1 tự reset PENDING có độ
trễ ⚠️ MẤT THAO TÁC NGƯỜI"). TASK-029 dựng phép tái lập XÁC ĐỊNH cho bug này —
trước đó chỉ có bằng chứng GIÁN TIẾP (thứ tự job enqueue + gate_status version
trên document_store.db thật, KHÔNG có log ở mức lệnh Sheets API).

CƠ CHẾ (đã xác nhận qua đọc code, không phải suy đoán):
  render_context_to_sheet() (sync_service.py) đọc STORE (KHÔNG đọc lại Sheet
  hiện có) rồi ghi đè MỌI cột, kể cả 2 cột NGƯỜI-SỞ-HỮU (Duyệt Context/Notes).
  Nếu 1 lượt render bị kích bởi 1 JOB KHÁC (không liên quan tới topic đang
  xét — xem queue_worker.py:170-172, MỌI job xong đều trigger _sync_sheet()
  render CẢ CONTEXT) đọc store TẠI THỜI ĐIỂM store CHƯA kịp ghi nhận APPROVE
  của người (vì lượt ingest bắt APPROVE đó chạy SAU điểm đọc kia), lượt render
  đó ghi giá trị CŨ (PENDING) đè lên ô Sheet — kể cả khi ô đó VỪA được ingest
  cập nhật thành APPROVE. Lượt ingest KẾ TIẾP đọc lại ô đã bị đè, thấy khác
  với store (store lúc đó ĐÃ có APPROVE) -> kết luận SAI "người rút duyệt" ->
  gọi cancel_pending() huỷ job + reset gate1 về "".

CÁCH TÁI LẬP (KHÔNG mock logic nghiệp vụ — ingest_context_from_sheet(),
render_context_to_sheet(), queue_store.cancel_pending() đều là hàm PRODUCTION
THẬT, gọi nguyên vẹn, không patch). Chỉ có 2 điểm được "đạo diễn", cả hai đều
mô phỏng hành vi CÓ THẬT của 2 tiến trình chạy song song, không phải giả lập
hành vi nghiệp vụ:
  (a) "người bấm APPROVE trên Sheet" — sửa trực tiếp ô trên fake board (CÙNG
      kỹ thuật `test_sync_all_ingests_user_edit_then_renders_it_back` trong
      store/test_sync_service.py đã dùng, không phải kỹ thuật mới).
  (b) "lượt render bị 1 job KHÁC kích, đọc store TRƯỚC khi ingest ghi APPROVE"
      — mô phỏng bằng cách snapshot FILE sqlite CŨ (trước khi ingest ghi) rồi
      cho lượt render đó đọc từ snapshot đó thay vì DB hiện tại. Đây CHÍNH XÁC
      là điều 1 tiến trình worker THỨ HAI (đã mở connection đọc TRƯỚC khi
      worker THỨ NHẤT commit) sẽ thấy — sqlite3.connect() mở connection MỚI
      mỗi lời gọi (xem document_store.py::_connect()), nên trỏ `db_path` sang
      bản snapshot tương đương "connection mở sớm hơn" một cách trung thực,
      không đụng vào bất kỳ hàm nghiệp vụ nào.

KỲ VỌNG: test này ĐỎ trên code hiện tại — chứng minh bug CÓ THẬT bằng dữ liệu
tái lập được, không chỉ suy luận gián tiếp. Khi 1 trong 3 phương án vá (xem
handoffs/TASK-028-agent-b.md, mục "Triệu chứng 3 — Đề xuất") được chủ dự án
CHỌN và áp dụng, test này PHẢI CHUYỂN XANH — đó là tiêu chí khách quan để biết
bản vá đã bịt đúng lỗ hổng, không phải "trông có vẻ đã sửa"."""
from __future__ import annotations

import os
import shutil
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from store import document_store as ds  # noqa: E402
from store import pipeline_store as ps  # noqa: E402
from store import queue_store as qs  # noqa: E402
from store import sync_service as ss  # noqa: E402
from twmkt.sheets_board import CONTEXT_HEADER, GATE1_COL  # noqa: E402


class _OrderedFakeWorksheet:
    """Giống `_FakeSyncWorksheet` ở store/test_sync_service.py, CỘNG THÊM ghi
    lại THỨ TỰ mọi lệnh đọc/ghi vào `log` dùng chung của board (yêu cầu hợp
    đồng TASK-029: "SheetsBoard giả ghi lại THỨ TỰ mọi lệnh đọc/ghi")."""

    def __init__(self, tab_name: str, log: list[tuple[str, str]]):
        self._tab_name = tab_name
        self._log = log
        self._grid: list[list[str]] = []

    def get_all_values(self) -> list[list[str]]:
        self._log.append(("get_all_values", self._tab_name))
        return [list(row) for row in self._grid]

    def clear(self) -> None:
        self._log.append(("clear", self._tab_name))
        self._grid = []

    def update(self, range_str: str, values: list[list], value_input_option: str = "RAW") -> None:
        self._log.append(("update", self._tab_name))
        start_row = int(range_str[1:]) if len(range_str) > 1 else 1
        needed = start_row - 1 + len(values)
        while len(self._grid) < needed:
            self._grid.append([])
        for i, row in enumerate(values):
            self._grid[start_row - 1 + i] = [str(c) for c in row]

    def batch_clear(self, ranges: list[str]) -> None:
        self._log.append(("batch_clear", self._tab_name))
        import re as _re
        for rng in ranges:
            m = _re.match(r"A(\d+):", rng)
            if m:
                self._grid = self._grid[: int(m.group(1)) - 1]

    def set_rows(self, rows: list[list[str]]) -> None:
        """Helper CHỈ dùng trong test -- mô phỏng (1) trạng thái Sheet có sẵn
        TRƯỚC lượt sync, HOẶC (2) người bấm sửa trực tiếp 1 ô qua Sheet UI.
        KHÔNG log vào `_log` -- đây không phải 1 lệnh Sheets API mà code
        production gọi, chỉ là đạo cụ dựng bối cảnh của test."""
        self._grid = [list(r) for r in rows]


class _OrderedFakeBoard:
    """Double SheetsBoard trong bộ nhớ — chỉ implement `_tab()`, đúng bề mặt
    sync_service.py thực sự dùng. `calls` là NHẬT KÝ THỨ TỰ dùng chung mọi
    tab, đọc được sau khi test chạy xong để xác nhận trình tự thật."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self._tabs = {
            "CONTEXT": _OrderedFakeWorksheet("CONTEXT", self.calls),
            "CONTENT": _OrderedFakeWorksheet("CONTENT", self.calls),
        }

    def _tab(self, name: str) -> _OrderedFakeWorksheet:
        return self._tabs[name]


def _header_index(header: list[str], name: str) -> int:
    return [h.strip().lower() for h in header].index(name.strip().lower())


def test_regression_stale_render_snapshot_overwrites_approve_before_next_ingest(tmp_path):
    """Xem docstring module cho bối cảnh đầy đủ + cách tái lập. Test này ĐỎ
    trên code hiện tại (chứng minh bug CÓ THẬT); phương án vá được chọn phải
    làm test này XANH."""
    topic_key = "tk-race-2026-08-08"
    db_path = tmp_path / "store.db"
    ds.init_db(db_path)

    # --- 0. Trạng thái ban đầu: topic đã crawl, CHƯA duyệt. ------------------
    ps.write_raw(topic_key, {
        "context": "Bài test race render/ingest", "hook": "hook",
        "source": "https://vietnambiz.vn/race-test.htm", "tickers": [], "group": "", "topic": "",
    }, db_path=db_path)
    ps.write_gate_status(topic_key, gate1="PENDING", execute="", db_path=db_path)

    board = _OrderedFakeBoard()
    # rebuild=False (TASK-032) -- CẢ HAI lệnh render trong test này mô phỏng
    # `queue_worker.py::_sync_sheet()` (lượt sync TỰ ĐỘNG sau mỗi job, nơi có
    # race thật) chứ KHÔNG phải lối gọi trực tiếp/thủ công -- default MỚI của
    # render_context_to_sheet() (rebuild=True, bỏ qua CAS) đúng cho lối gọi
    # kia (xem store/test_sync_service.py::test_render_context_to_sheet_
    # without_prior_ingest_reflects_store_not_sheet + docstring hàm), KHÔNG
    # đúng ở đây -- không đổi giá trị assert nào, chỉ khai báo tường minh ý
    # định lượt gọi, đúng tinh thần "không ngầm định" của cả bản vá này.
    ss.render_context_to_sheet(board, db_path=db_path, rebuild=False)   # dựng Sheet lần đầu (Gate1=PENDING)

    grid0 = board._tab("CONTEXT").get_all_values()
    header = grid0[0]
    i_g1 = _header_index(header, GATE1_COL)
    row0 = next(r for r in grid0[1:] if r[_header_index(header, "TopicKey")] == topic_key)
    assert row0[i_g1] == "PENDING"

    # --- 1. ẢNH CHỤP STORE CŨ (trước khi ingest ghi APPROVE) -- mô phỏng
    # connection của 1 tiến trình render KHÁC đã mở SỚM HƠN, TRƯỚC khi worker
    # xử lý APPROVE của người kịp commit. -------------------------------------
    stale_snapshot_path = tmp_path / "store_snapshot_before_approve.db"
    shutil.copyfile(db_path, stale_snapshot_path)

    # --- 2. "Người bấm Duyệt Context trên Sheet" -- sửa trực tiếp ô Gate1. ---
    grid = board._tab("CONTEXT").get_all_values()
    for r in grid[1:]:
        if r[_header_index(header, "TopicKey")] == topic_key:
            r[i_g1] = "APPROVE"
    board._tab("CONTEXT").set_rows(grid)

    # --- 3. "Ingest bắt APPROVE -> job enqueue" -- HÀM PRODUCTION THẬT. ------
    n_ingest_1 = ss.ingest_context_from_sheet(board, db_path=db_path)
    assert n_ingest_1 >= 1
    assert ps.read_gate_status(topic_key, db_path=db_path)["gate1"] == "APPROVE"
    job_before = qs.find_pending(topic_key, job_type="produce", db_path=db_path)
    assert job_before is not None and job_before["status"] == "queued", (
        "job phải nằm ở 'queued' (chưa claim) -- đúng khớp job #95-97 thật ngày "
        "2026-08-08 (claimed_at=None cả 3 job bị cancel)"
    )

    # --- 4. "Render chen vào với ảnh chụp store CŨ" -- HÀM PRODUCTION THẬT,
    # chỉ khác db_path trỏ snapshot (mô phỏng đọc SỚM HƠN của 1 job KHÁC).
    # rebuild=False (TASK-032, xem ghi chú ở lệnh render đầu tiên phía trên). --
    ss.render_context_to_sheet(board, db_path=stale_snapshot_path, rebuild=False)

    grid_after_stale_render = board._tab("CONTEXT").get_all_values()
    row_after_stale = next(
        r for r in grid_after_stale_render[1:]
        if r[_header_index(header, "TopicKey")] == topic_key
    )
    # SỬA (TASK-030, xem handoffs/TASK-030-agent-b.md) -- bản TASK-029 kỳ vọng
    # "PENDING" ở đây (chứng minh code CHƯA VÁ ghi đè vô điều kiện). Sau khi vá
    # bằng CAS theo timestamp (store/sync_service.py::_cas_user_value()), ĐÂY
    # CHÍNH LÀ ĐIỂM bản vá chặn đứng bug: ảnh chụp store CŨ (chỉ thấy version
    # PENDING, CHƯA từng thấy version APPROVE) không chứng minh được nó MỚI
    # HƠN giá trị "APPROVE" đang có trên Sheet -> giữ nguyên, KHÔNG ghi đè.
    # Assertion đổi hướng 180 độ: giờ xác nhận NGAY TẠI ĐÂY ô Sheet PHẢI CÒN
    # "APPROVE" (không đợi tới bước ingest kế tiếp mới phát hiện gián tiếp).
    assert row_after_stale[i_g1] == "APPROVE", (
        "BUG THẬT nếu fail (CAS không hoạt động): lượt render dùng ảnh chụp "
        "store CŨ (chỉ thấy PENDING, chưa từng thấy APPROVE) đã ghi đè ô Sheet "
        "-- đúng lỗ hổng TASK-028 Triệu chứng 3, bản vá TASK-030 phải chặn "
        "được ngay ở bước này."
    )

    # --- 5. "Ingest kế tiếp đọc ô đã bị đè" -- HÀM PRODUCTION THẬT, db_path
    # THẬT (đã có APPROVE từ bước 3). ------------------------------------------
    ss.ingest_context_from_sheet(board, db_path=db_path)

    # --- KIỂM: đây là 2 hệ quả BUG THẬT đã xác nhận trên document_store.db
    # sản xuất ngày 2026-08-08 (handoffs/TASK-028-agent-b.md, Triệu chứng 3).
    # Assertion mô tả hành vi ĐÚNG (KHÔNG được mất APPROVE, KHÔNG được huỷ job
    # oan) -- giờ đây là hệ quả TẤT YẾU của bước 4 đã đứng vững ở trên (Sheet
    # chưa từng bị đè về PENDING nên ingest này không có gì để "phát hiện rút
    # duyệt" nữa); giữ 2 assertion này làm lưới an toàn KIỂM TRA ĐẦU CUỐI, độc
    # lập với chi tiết cài đặt của _cas_user_value().
    final_gate1 = ps.read_gate_status(topic_key, db_path=db_path)["gate1"]
    assert final_gate1 == "APPROVE", (
        f"BUG THẬT (regression, chưa vá đúng): race giữa render (ảnh chụp store CŨ) và "
        f"ingest kế tiếp đã xoá mất APPROVE người vừa duyệt -- gate1 hiện = "
        f"{final_gate1!r}, đúng cơ chế TASK-028 Triệu chứng 3 (ngày 2026-08-08, "
        f"3/4 job APPROVE bị mất theo đúng cách này)."
    )

    job_after = [j for j in qs.list_queue(db_path=db_path) if j["topic_key"] == topic_key]
    cancelled = [j for j in job_after if j["status"] == "cancelled"]
    assert not cancelled, (
        f"BUG THẬT (regression, chưa vá đúng): job bị cancel_pending() huỷ OAN vì "
        f"race trên, lý do lưu trong DB: {[j.get('error') for j in cancelled]!r} "
        f"(khớp nguyên văn 'Gate 1 rút khỏi APPROVE' đã thấy trên job #95-97 "
        f"thật -- xem handoffs/TASK-028-agent-b.md)."
    )

    # --- Nhật ký thứ tự lệnh đọc/ghi (yêu cầu hợp đồng TASK-029) -- SỬA
    # (TASK-030, xem handoff): bản TASK-029 đếm lượt "update" trên CONTEXT, kỳ
    # vọng >=2 (render đầu + render chen ngang). Sau khi vá bằng CAS, render
    # chen ngang ở kịch bản NÀY tạo ra 1 dòng giống HỆT dòng Sheet hiện có (CAS
    # đã giữ nguyên APPROVE thay vì ghi PENDING đè lên) -- _write_rows() (có từ
    # trước, VIỆC 2026-08-02) CHỦ ĐỘNG bỏ qua update() cho dòng không đổi, nên
    # đếm "update" không còn phản ánh đúng "2 lượt render đã xảy ra" nữa (số
    # lượng >=2 có thể tình cờ đạt được chỉ từ 1 lượt render, vì mỗi lượt vốn
    # đã tách header/data thành 2 lệnh update riêng -- không còn là bằng chứng
    # có ý nghĩa cho "render chen ngang có xảy ra"). Đổi sang đếm
    # "get_all_values" -- CAS (`_cas_user_value`) BẮT BUỘC đọc lại Sheet hiện
    # tại trước khi quyết định ghi, nên mỗi lượt render giờ đọc CONTEXT >=2 lần
    # (1 lần cho CAS so khớp, 1 lần _write_rows() dùng để diff) -- đây MỚI là
    # bằng chứng trực tiếp "2 lượt render đã thật sự chạy", không suy diễn.
    read_calls = [c for c in board.calls if c == ("get_all_values", "CONTEXT")]
    assert len(read_calls) >= 4, (
        f"kỳ vọng >=4 lượt đọc CONTEXT (2 lượt render x >=2 lượt đọc/lượt -- CAS "
        f"so khớp + _write_rows() diff), log thật={board.calls}"
    )
