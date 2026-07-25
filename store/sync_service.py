"""P2 STORE-AS-TRUTH Bước 3 (2026-07-25, nhánh feature/store-as-truth) — cầu
nối 2 CHIỀU giữa store (nguồn sự thật) và Sheet (VIEW thuần cho người xem/
thao tác). Pipeline (produce_from_sheet.py) KHÔNG BIẾT tới module này —
Nguyên tắc 3 ("Pipeline và Sheet KHÔNG BIẾT NHAU") — module này là adapter
DUY NHẤT được phép đọc/ghi CẢ HAI phía.

BỐN HÀM CHÍNH:
  render_context_to_sheet() / render_content_to_sheet() — store -> Sheet.
    DỰNG LẠI TOÀN BỘ tab (clear + ghi lại từ đầu), IDEMPOTENT — đây CHÍNH LÀ
    lệnh "phục hồi khi xoá nhầm" (xoá vài dòng Sheet, chạy lại hàm này, Sheet
    trở về đúng như trước — vì store append-only, KHÔNG hề mất dữ liệu).
  ingest_context_from_sheet() / ingest_content_from_sheet() — Sheet -> store.
    Đọc thao tác NGƯỜI vừa làm (Duyệt Context/Content/Public, Notes, Social
    Link, Posting Status) và topic MỚI (TopicKey có nhưng store chưa có raw —
    cầu nối tạm cho review_to_sheet.py, xem "CẦU NỐI TẠM" bên dưới), ghi
    version MỚI vào store.
  sync_all() — orchestrator: ingest TRƯỚC render (không mất thao tác người
    vừa bấm giữa 2 lượt gọi), rồi render lại từ store đã cập nhật.

NGUYÊN TẮC 3.3 — KHÔNG CỘT NÀO 2 CHIỀU (xem _CONTEXT_MACHINE_COLS/
_CONTEXT_USER_COLS/_CONTENT_MACHINE_COLS/_CONTENT_USER_COLS bên dưới cho danh
sách đầy đủ + lý do từng cột). NGOẠI LỆ DUY NHẤT đã biết: cột Execute (CONTEXT)
— máy ghi RUN/DONE/FAILED/NEEDS_HUMAN, NHƯNG người được phép tự đổi
NEEDS_HUMAN -> RUN để yêu cầu thử lại (đã tài liệu hoá ở agents/writer.py
Phase 4.9, "chờ người đổi Execute về RUN"). ingest_context_from_sheet() CHỈ
đọc ĐÚNG transition này (NEEDS_HUMAN -> RUN), KHÔNG đọc mọi giá trị Execute
như 1 cột người-sở-hữu bình thường — vẫn giữ đúng tinh thần "không 2 chiều
đầy đủ", chỉ mở 1 khe hẹp đã biết trước.

CẦU NỐI TẠM (móc nối chéo đã báo Lead ở Bước 1/Bước 2, CHƯA giải quyết dứt
điểm): review_to_sheet.py (crawl -> CONTEXT mới) nằm NGOÀI ranh giới file
được giao, vẫn ghi THẲNG vào Sheet, KHÔNG qua store. ingest_context_from_sheet()
coi "TopicKey có trên Sheet nhưng store chưa có raw" là CONTEXT MỚI hợp lệ,
tự nạp vào store (raw + gate_status) — bridge này giữ Nguyên tắc 1 ("Pipeline
CHỈ đọc/ghi STORE") đúng cho produce_from_sheet.py dù review_to_sheet.py chưa
migrate.
"""
from __future__ import annotations

from twmkt.sheets_board import (
    CONTENT_HEADER, CONTEXT_HEADER, GATE1_COL, GATE2_COL, GATE3_COL, OUTPUT_TYPE_COL,
    SheetsBoard, content_row, context_row, facts_to_json,
)

from . import document_store as ds
from . import pipeline_store as ps

_ALL_TYPES = ("article", "infographic", "video")

# --- Quyền sở hữu cột (Nguyên tắc 3.3) --------------------------------------
# MÁY-SỞ-HỮU (store->Sheet, render ghi đè KHÔNG hỏi) — dữ liệu NGUỒN từ raw/
# content_output/gate_status.execute/content_status.asset_*, KHÔNG phải chỗ
# người gõ tay.
_CONTEXT_MACHINE_COLS = ("Timestamp", "Hot%", "Score", "Group", "Topic", "Context",
                        "Hook", "Source", "Execute", "tickers", "TopicKey")
# NGƯỜI-SỞ-HỮU (Sheet->store, ingest đọc, render đọc THẲNG từ store để phản
# ánh lại — KHÔNG BAO GIỜ máy tự sinh nội dung các cột này). Output Type
# (Bước 4) — người chọn giới hạn Content Factory, xem OUTPUT_TYPE_VALUES.
_CONTEXT_USER_COLS = (GATE1_COL, "Notes", OUTPUT_TYPE_COL)

_CONTENT_MACHINE_COLS = ("Timestamp", "Context", "Type", "Status", "Output",
                         "Notes", "TopicKey", "Facts", "AssetPath")
_CONTENT_USER_COLS = (GATE2_COL, "Social Link", GATE3_COL, "Posting Status")


def _read_sheet_rows(board: SheetsBoard, tab_name: str) -> tuple[list[str], list[list[str]]]:
    try:
        rows = board._tab(tab_name).get_all_values()
    except Exception:  # pragma: no cover - tab chưa tồn tại
        return [], []
    if not rows:
        return [], []
    return rows[0], rows[1:]


def _col_index(header: list[str], name: str) -> int | None:
    low = [h.strip().lower() for h in header]
    key = name.strip().lower()
    return low.index(key) if key in low else None


def _cell(row: list[str], i: int | None) -> str:
    return row[i].strip() if i is not None and i < len(row) else ""


# =============================================================================
# store -> Sheet (render, idempotent, = lệnh phục hồi)
# =============================================================================

def render_context_to_sheet(board: SheetsBoard, *, db_path=None) -> int:
    """Dựng lại TOÀN BỘ tab CONTEXT từ store — bao gồm CẢ Duyệt Context/Notes,
    đọc THẲNG từ gate_status (KHÔNG đọc lại giá trị hiện có trên Sheet trước
    khi xoá — store, KHÔNG PHẢI Sheet, là nguồn sự thật cho 2 cột người-sở-
    hữu này). Đây CHÍNH LÀ điều kiện để lệnh phục hồi (Bước 5.4) đúng: ingest
    ĐÃ ghi thao tác người vào gate_status TRƯỚC khi Sheet bị xoá/render lại —
    nếu render còn dựa vào Sheet hiện tại làm "giữ nguyên", xoá Sheet TRƯỚC
    khi ingest kịp chạy sẽ làm mất thao tác đó (đã tự phát hiện qua
    test_sync_all_full_recovery_after_accidental_deletion khi viết hàm này —
    lỗi thật, không phải giả định)."""
    out_rows: list[list[str]] = []
    for topic_key in ds.list_topics(layer="raw", db_path=db_path):
        raw = ps.read_raw(topic_key, db_path=db_path) or {}
        gate = ps.read_gate_status(topic_key, db_path=db_path)
        out_rows.append(context_row(
            title=raw.get("context", ""), hook_line=raw.get("hook", ""),
            source_url=raw.get("source", ""),
            score=int(raw.get("score", 0) or 0), hot_pct=float(raw.get("hot_pct", 0.0) or 0.0),
            topic=raw.get("topic", ""), group=raw.get("group", ""),
            tickers=raw.get("tickers", []), status=gate.get("gate1", "PENDING"),
            execute=gate.get("execute", ""), topic_key=topic_key, notes=gate.get("notes", ""),
            output_type=gate.get("output_type") or [],
        ))

    ws = board._tab("CONTEXT")
    ws.clear()
    ws.update("A1", [CONTEXT_HEADER, *out_rows], value_input_option="USER_ENTERED")
    return len(out_rows)


def render_content_to_sheet(board: SheetsBoard, *, db_path=None) -> int:
    """Dựng lại TOÀN BỘ tab CONTENT từ store. Đọc TRƯỚC giá trị NGƯỜI-SỞ-HỮU
    hiện có — bao gồm CẢ Duyệt Content/Social Link/Duyệt Public/Posting
    Status, đọc THẲNG từ content_status (KHÔNG đọc lại Sheet hiện tại trước
    khi xoá — cùng lý do render_context_to_sheet(), xem docstring đó).
    content_row() hard-code Duyệt Public="PENDING" (INVARIANT — KHÔNG luồng
    máy nào được ghi Gate3, xem docstring content_row()) nên override 3 cột
    người-sở-hữu SAU khi gọi, bằng giá trị đọc từ content_status — vẫn KHÔNG
    máy TỰ SINH giá trị, chỉ phản ánh lại cái người đã ghi (qua ingest)."""
    i_h_social = CONTENT_HEADER.index("Social Link")
    i_h_g3 = CONTENT_HEADER.index(GATE3_COL)
    i_h_posting = CONTENT_HEADER.index("Posting Status")

    out_rows: list[list[str]] = []
    for topic_key in ds.list_topics(layer="content_output", db_path=db_path):
        raw = ps.read_raw(topic_key, db_path=db_path) or {}
        context_title = raw.get("context", "")
        for type_ in _ALL_TYPES:
            out = ps.read_content_output(topic_key, type_, db_path=db_path)
            if out is None:
                continue
            status_data = ps.read_content_status(topic_key, type_, db_path=db_path)
            row = content_row(
                context=context_title, type_=type_, status=out.get("status", ""),
                output=out.get("output", ""), notes=out.get("notes", ""),
                approve=status_data.get("gate2", "PENDING"), topic_key=topic_key,
                facts=out.get("facts", ""),
                asset_path=status_data.get("asset_url") or status_data.get("asset_local_path") or "",
            )
            row[i_h_social] = status_data.get("social_link", "")
            row[i_h_g3] = status_data.get("gate3", "PENDING")
            row[i_h_posting] = status_data.get("posting_status", "")
            out_rows.append(row)

    ws = board._tab("CONTENT")
    ws.clear()
    ws.update("A1", [CONTENT_HEADER, *out_rows], value_input_option="USER_ENTERED")
    return len(out_rows)


# =============================================================================
# Sheet -> store (ingest thao tác người + cầu nối topic mới từ review_to_sheet.py)
# =============================================================================

def ingest_context_from_sheet(board: SheetsBoard, *, db_path=None) -> int:
    """Đọc CONTEXT hiện tại, ghi version MỚI vào store cho: (1) topic MỚI
    (TopicKey có trên Sheet, store CHƯA có raw — CẦU NỐI TẠM, xem docstring
    module), (2) Duyệt Context/Notes đổi so với gate_status hiện có, (3)
    NGOẠI LỆ Execute: NEEDS_HUMAN -> RUN (người yêu cầu thử lại, xem Phase
    4.9). Trả số lần ghi (write_document calls)."""
    header, rows = _read_sheet_rows(board, "CONTEXT")
    if not header:
        return 0
    i_key = _col_index(header, "TopicKey")
    i_ctx = _col_index(header, "Context")
    i_hook = _col_index(header, "Hook")
    i_src = _col_index(header, "Source")
    i_tk = _col_index(header, "tickers")
    i_grp = _col_index(header, "Group")
    i_top = _col_index(header, "Topic")
    i_score = _col_index(header, "Score")
    i_hot = _col_index(header, "Hot%")
    i_g1 = _col_index(header, GATE1_COL)
    i_notes = _col_index(header, "Notes")
    i_ex = _col_index(header, "Execute")
    i_ot = _col_index(header, OUTPUT_TYPE_COL)

    writes = 0
    for row in rows:
        topic_key = _cell(row, i_key)
        if not topic_key:
            continue   # dòng chưa có TopicKey (vd chưa backfill) -- bỏ qua, KHÔNG đoán khoá
        sheet_gate1 = _cell(row, i_g1) or "PENDING"
        sheet_notes = _cell(row, i_notes)
        sheet_execute = _cell(row, i_ex).upper()
        sheet_output_type = [t.strip() for t in _cell(row, i_ot).split(",") if t.strip()]

        raw_src = _cell(row, i_src)
        source_url = raw_src.splitlines()[0] if raw_src else ""
        tickers = [t.strip() for t in _cell(row, i_tk).split(",") if t.strip()]

        if ps.read_raw(topic_key, db_path=db_path) is None:
            # Cầu nối tạm: topic MỚI từ review_to_sheet.py, chưa có trong store.
            try:
                score_val = int(float(_cell(row, i_score) or 0))
            except ValueError:
                score_val = 0
            try:
                hot_val = float(_cell(row, i_hot) or 0.0)
            except ValueError:
                hot_val = 0.0
            ps.write_raw(topic_key, {
                "context": _cell(row, i_ctx), "hook": _cell(row, i_hook),
                "source": source_url, "tickers": tickers,
                "group": _cell(row, i_grp), "topic": _cell(row, i_top),
                "score": score_val, "hot_pct": hot_val,
            }, db_path=db_path)
            writes += 1
            ps.write_gate_status(topic_key, gate1=sheet_gate1,
                                 execute=sheet_execute or None, notes=sheet_notes or None,
                                 output_type=sheet_output_type or None,
                                 db_path=db_path)
            writes += 1
            continue

        gate = ps.read_gate_status(topic_key, db_path=db_path)
        updates: dict = {}
        if sheet_gate1 != gate.get("gate1", "PENDING"):
            updates["gate1"] = sheet_gate1
        if sheet_notes != gate.get("notes", ""):
            updates["notes"] = sheet_notes
        if sheet_output_type != (gate.get("output_type") or []):
            updates["output_type"] = sheet_output_type
        # NGOẠI LỆ DUY NHẤT (xem docstring module): người đổi NEEDS_HUMAN -> RUN
        # để yêu cầu thử lại -- KHÔNG đọc mọi giá trị Execute khác.
        if gate.get("execute") == "NEEDS_HUMAN" and sheet_execute == "RUN":
            updates["execute"] = "RUN"
        if updates:
            ps.write_gate_status(topic_key, db_path=db_path, **updates)
            writes += 1
    return writes


def ingest_content_from_sheet(board: SheetsBoard, *, db_path=None) -> int:
    """Đọc CONTENT hiện tại, ghi version MỚI vào content_status cho các
    (TopicKey, Type) có Duyệt Content/Social Link/Duyệt Public/Posting Status
    đổi so với store. KHÔNG tạo content_output mới (đó là việc pipeline, xem
    Nguyên tắc 1) -- chỉ ghi khi (TopicKey, Type) ĐÃ có content_output."""
    header, rows = _read_sheet_rows(board, "CONTENT")
    if not header:
        return 0
    i_key = _col_index(header, "TopicKey")
    i_type = _col_index(header, "Type")
    i_g2 = _col_index(header, GATE2_COL)
    i_social = _col_index(header, "Social Link")
    i_g3 = _col_index(header, GATE3_COL)
    i_posting = _col_index(header, "Posting Status")

    writes = 0
    for row in rows:
        topic_key, type_ = _cell(row, i_key), _cell(row, i_type)
        if not topic_key or not type_:
            continue
        if ps.read_content_output(topic_key, type_, db_path=db_path) is None:
            continue   # content_output chưa tồn tại -- không có content_status để ingest vào
        sheet_gate2 = _cell(row, i_g2) or "PENDING"
        sheet_social = _cell(row, i_social)
        sheet_gate3 = _cell(row, i_g3) or "PENDING"
        sheet_posting = _cell(row, i_posting)

        status = ps.read_content_status(topic_key, type_, db_path=db_path)
        updates: dict = {}
        if sheet_gate2 != status.get("gate2", "PENDING"):
            updates["gate2"] = sheet_gate2
        if sheet_social != status.get("social_link", ""):
            updates["social_link"] = sheet_social
        if sheet_gate3 != status.get("gate3", "PENDING"):
            updates["gate3"] = sheet_gate3
        if sheet_posting != status.get("posting_status", ""):
            updates["posting_status"] = sheet_posting
        if updates:
            ps.write_content_status(topic_key, type_, db_path=db_path, **updates)
            writes += 1
    return writes


# =============================================================================
# Orchestrator
# =============================================================================

def sync_all(board: SheetsBoard, *, db_path=None) -> dict:
    """Ingest TRƯỚC (không mất thao tác người vừa bấm giữa 2 lượt), rồi render
    LẠI cả 2 tab từ store đã cập nhật. Đây là lệnh CHẠY DUY NHẤT cho vận hành
    bình thường lẫn "phục hồi khi xoá nhầm" (Bước 5.4)."""
    n_ingest_ctx = ingest_context_from_sheet(board, db_path=db_path)
    n_ingest_content = ingest_content_from_sheet(board, db_path=db_path)
    n_render_ctx = render_context_to_sheet(board, db_path=db_path)
    n_render_content = render_content_to_sheet(board, db_path=db_path)
    return {
        "ingested_context": n_ingest_ctx, "ingested_content": n_ingest_content,
        "rendered_context_rows": n_render_ctx, "rendered_content_rows": n_render_content,
    }
