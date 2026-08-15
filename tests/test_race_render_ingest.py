"""REGRESSION TEST cho race giữa render_context_to_sheet() và
ingest_context_from_sheet() (store/sync_service.py), gốc từ TASK-028
(handoffs/TASK-028-agent-b.md, Triệu chứng 3: "Gate 1 tự reset PENDING có độ
trễ ⚠️ MẤT THAO TÁC NGƯỜI") -- TÁI HIỆN lại ngày 15/08 y hệt ở Gate 2 tab
CONTENT (hợp đồng TASK-035, xem store/test_sync_service.py::test_regression_
2026_08_15_gate2_approve_survives_automatic_render_and_enqueues_render_assets
cho bản CONTENT).

BẢN CŨ (TASK-029/030/032, xem lịch sử git) tái lập bằng cách trỏ render vào 1
SNAPSHOT sqlite CŨ để mô phỏng "ảnh chụp store cũ hơn giá trị Sheet hiện có",
rồi khoá ngữ nghĩa CAS theo timestamp (`_cas_user_value()`) bảo vệ ca đó. TASK-
035 XOÁ HẲN CAS: `render_context_to_sheet()` giờ CHỈ ghi dải cột MÁY-SỞ-HỮU
cho dòng ĐÃ TỒN TẠI trên Sheet, KHÔNG BAO GIỜ đụng Duyệt Context/Notes/Output
Type -- không còn "ảnh chụp cũ/mới" nào để phân biệt nữa, nên phép tái lập ở
đây ĐƠN GIẢN HOÁ tương ứng: không cần snapshot DB tách biệt, chỉ cần chứng
minh 1 lượt render TỰ ĐỘNG xen giữa "người bấm APPROVE" và "ingest kịp bắt"
không hề đụng ô đó."""
from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from store import document_store as ds  # noqa: E402
from store import pipeline_store as ps  # noqa: E402
from store import queue_store as qs  # noqa: E402
from store import sync_service as ss  # noqa: E402
from twmkt.sheets_board import GATE1_COL  # noqa: E402


class _FakeWorksheet:
    """Cùng khuôn `_FakeWorksheet` ở store/test_sync_service.py (mỗi file test
    tự copy 1 bản nhỏ, cùng nếp sẵn có trong repo) -- support đủ update/
    batch_clear/batch_update/append_rows cho đường ghi mới (TASK-035)."""

    def __init__(self):
        self._grid: list[list[str]] = []

    def get_all_values(self) -> list[list[str]]:
        return [list(row) for row in self._grid]

    def update(self, range_str: str, values: list[list], value_input_option: str = "RAW") -> None:
        start_row = int(range_str[1:]) if len(range_str) > 1 else 1
        needed = start_row - 1 + len(values)
        while len(self._grid) < needed:
            self._grid.append([])
        for i, row in enumerate(values):
            self._grid[start_row - 1 + i] = [str(c) for c in row]

    def batch_clear(self, ranges: list[str]) -> None:
        import re as _re
        for rng in ranges:
            m = _re.match(r"A(\d+):", rng)
            if m:
                self._grid = self._grid[: int(m.group(1)) - 1]

    def batch_update(self, data: list[dict], value_input_option: str = "RAW") -> None:
        import re as _re

        def _col_idx(letters: str) -> int:
            n = 0
            for ch in letters:
                n = n * 26 + (ord(ch) - 64)
            return n - 1

        for entry in data:
            m = _re.match(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", entry["range"])
            col0, row0 = _col_idx(m.group(1)), int(m.group(2)) - 1
            values = entry["values"]
            needed = row0 + len(values)
            while len(self._grid) < needed:
                self._grid.append([])
            for i, vals in enumerate(values):
                r = self._grid[row0 + i]
                needed_len = col0 + len(vals)
                if len(r) < needed_len:
                    r.extend([""] * (needed_len - len(r)))
                for j, v in enumerate(vals):
                    r[col0 + j] = str(v)

    def append_rows(self, rows: list[list], value_input_option: str = "RAW") -> None:
        for row in rows:
            self._grid.append([str(c) for c in row])

    def set_rows(self, rows: list[list[str]]) -> None:
        self._grid = [list(r) for r in rows]


class _FakeBoard:
    def __init__(self):
        self._tabs = {"CONTEXT": _FakeWorksheet(), "CONTENT": _FakeWorksheet()}

    def _tab(self, name: str) -> _FakeWorksheet:
        return self._tabs[name]


def _header_index(header: list[str], name: str) -> int:
    return [h.strip().lower() for h in header].index(name.strip().lower())


def test_gate1_approve_survives_automatic_render_interleaved_before_ingest(tmp_path):
    """Hình dạng CONTEXT của sự cố 15/08 (bản CONTENT xem store/test_sync_
    service.py). Trình tự tái lập ĐÚNG race thật:
      1. Topic đã crawl (PENDING), dòng CONTEXT đã tồn tại trên Sheet.
      2. "Người bấm Duyệt Context = APPROVE trên Sheet" -- sửa Ô trực tiếp,
         CHƯA ingest (mô phỏng độ trễ giữa click và lượt ingest kế tiếp).
      3. "1 lượt render tự động chen vào" -- job KHÁC (không liên quan) vừa xử
         lý xong, worker gọi render_context_to_sheet() (xem queue_worker.py::
         _sync_sheet(), luôn render CẢ CONTEXT dù job vừa xong không phải của
         topic này) -- TRƯỚC khi ingest kịp bắt APPROVE.
      4. Ô Duyệt Context PHẢI CÒN "APPROVE" NGAY SAU BƯỚC 3 (TASK-035: không
         còn "chậm vài giây rồi ingest cứu lại" như CAS cũ -- máy đơn giản
         KHÔNG BAO GIỜ đụng cột này của dòng đã tồn tại).
      5. Ingest kế tiếp phải bắt được APPROVE + enqueue job, KHÔNG coi nhầm
         thành "rút duyệt" (đúng 2 hệ quả bug thật đã xác nhận trên
         document_store.db sản xuất 2026-08-08, xem handoffs/TASK-028-agent-b.md)."""
    topic_key = "tk-race-2026-08-15"
    db_path = tmp_path / "store.db"
    ds.init_db(db_path)

    ps.write_raw(topic_key, {
        "context": "Bài test race render/ingest", "hook": "hook",
        "source": "https://vietnambiz.vn/race-test.htm", "tickers": [], "group": "", "topic": "",
    }, db_path=db_path)
    ps.write_gate_status(topic_key, gate1="PENDING", execute="", db_path=db_path)

    board = _FakeBoard()
    ss.render_context_to_sheet(board, db_path=db_path)   # dựng dòng CONTEXT lần đầu (PENDING)

    grid0 = board._tab("CONTEXT").get_all_values()
    header = grid0[0]
    i_g1 = _header_index(header, GATE1_COL)
    row0 = next(r for r in grid0[1:] if r[_header_index(header, "TopicKey")] == topic_key)
    assert row0[i_g1] == "PENDING"

    # --- "Người bấm Duyệt Context trên Sheet" -- CHƯA ingest. ---------------
    grid = board._tab("CONTEXT").get_all_values()
    for r in grid[1:]:
        if r[_header_index(header, "TopicKey")] == topic_key:
            r[i_g1] = "APPROVE"
    board._tab("CONTEXT").set_rows(grid)

    # --- "1 lượt render tự động chen vào" TRƯỚC ingest -- HÀM PRODUCTION THẬT. ---
    ss.render_context_to_sheet(board, db_path=db_path)

    grid_after_render = board._tab("CONTEXT").get_all_values()
    row_after = next(
        r for r in grid_after_render[1:] if r[_header_index(header, "TopicKey")] == topic_key)
    assert row_after[i_g1] == "APPROVE", (
        "BUG THẬT nếu fail: lượt render tự động (chưa được ingest đi trước) đã "
        "ghi đè Duyệt Context về giá trị store cũ (PENDING) -- đúng hình dạng "
        "sự cố 15/08 (khi đó xảy ra ở Gate 2 CONTENT), TASK-035 phải chặn được "
        "NGAY tại đây (không đợi ingest kế tiếp mới 'cứu lại')."
    )

    # --- Ingest kế tiếp phải bắt được APPROVE + enqueue, không huỷ oan. -----
    ss.ingest_context_from_sheet(board, db_path=db_path)

    final_gate1 = ps.read_gate_status(topic_key, db_path=db_path)["gate1"]
    assert final_gate1 == "APPROVE", (
        f"BUG THẬT (regression): gate1 hiện = {final_gate1!r}, đúng cơ chế "
        f"TASK-028 Triệu chứng 3 (3/4 job APPROVE bị mất theo đúng cách này "
        f"ngày 2026-08-08)."
    )
    jobs = [j for j in qs.list_queue(db_path=db_path) if j["topic_key"] == topic_key]
    cancelled = [j for j in jobs if j["status"] == "cancelled"]
    assert not cancelled, (
        f"BUG THẬT (regression): job bị cancel_pending() huỷ OAN vì tưởng "
        f"'rút duyệt', lý do lưu trong DB: {[j.get('error') for j in cancelled]!r}."
    )
    queued = [j for j in jobs if j["status"] == "queued"]
    assert len(queued) == 1 and queued[0]["topic_key"] == topic_key, (
        f"job produce PHẢI được enqueue đúng 1 lần cho topic vừa APPROVE: {jobs!r}"
    )
