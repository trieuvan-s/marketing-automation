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
sách đầy đủ + lý do từng cột). 2 KHE HẸP đã biết trước cho cột Execute
(CONTEXT — máy ghi RUN/DONE/FAILED/NEEDS_HUMAN), ingest_context_from_sheet()
CHỈ đọc ĐÚNG 2 transition này, KHÔNG đọc mọi giá trị Execute như 1 cột
người-sở-hữu bình thường:
  1. rỗng -> RUN khi Gate1 vừa APPROVE (thay SheetsBoard.sync_approve_
     execute_flags() cũ — bootstrap lần đầu, KHÔNG phải người gõ tay "RUN").
  2. NEEDS_HUMAN -> RUN (người tự đổi để yêu cầu thử lại, đã tài liệu hoá ở
     agents/writer.py Phase 4.9, "chờ người đổi Execute về RUN").

CẦU NỐI TẠM (móc nối chéo đã báo Lead ở Bước 1/Bước 2, CHƯA giải quyết dứt
điểm): review_to_sheet.py (crawl -> CONTEXT mới) nằm NGOÀI ranh giới file
được giao, vẫn ghi THẲNG vào Sheet, KHÔNG qua store. ingest_context_from_sheet()
coi "TopicKey có trên Sheet nhưng store chưa có raw" là CONTEXT MỚI hợp lệ,
tự nạp vào store (raw + gate_status) — bridge này giữ Nguyên tắc 1 ("Pipeline
CHỈ đọc/ghi STORE") đúng cho produce_from_sheet.py dù review_to_sheet.py chưa
migrate.
"""
from __future__ import annotations

from twmkt.sheets_board import (  # noqa: F401
    _col_a1, _display_notes_business, raw_content_type,
    CONTENT_HEADER, CONTEXT_HEADER, EXECUTE_WAITING, GATE1_COL, GATE2_COL, GATE3_COL,
    OUTPUT_TYPE_COL, SheetsBoard, content_row, context_row, facts_to_json,
)

from . import document_store as ds
from . import pipeline_store as ps
from . import queue_store as qs

_ALL_TYPES = ("article", "long_article", "infographic", "video")

# Nhãn AssetPath khi Gate 2 đã duyệt mà asset chưa có (xem _asset_cell()).
ASSET_PROCESSING_LABEL = "Processing..."

# store/content_output.output giữ NGUYÊN VĂN (Lead xác nhận 2026-07-27) --
# TRUNCATE CHỈ còn ở đây, điểm đẩy sang Sheet cho người LIẾC nhanh. Bất kỳ
# code nào cần parse lại nội dung (vd render_production_assets.py) PHẢI đọc
# thẳng ps.read_content_output() từ store, KHÔNG BAO GIỜ đọc lại ô Sheet này.
#
# VIỆC 2 (2026-08-04, Lead: "tăng kích thước cell lên tối đa 5k ký tự... user
# xem và sửa tay nội dung nếu cần trước khi phê duyệt Gate 2") -- nâng 1500 ->
# 5000 để cột Output đủ chứa TRỌN bài (không cắt) cho phần lớn bài viết, đồng
# thời cho phép người sửa tay trực tiếp trên Sheet (xem
# ingest_content_from_sheet() -- Output giờ là cột HYBRID, xem ghi chú ở
# _CONTENT_MACHINE_COLS/_CONTENT_USER_COLS bên dưới).
_OUTPUT_PREVIEW = 5000


def _band_day(board, method: str, tab: str) -> None:
    """Gọi hàm tô khối ngày ĐÃ CÓ SẴN trong sheets_board (band_context_by_day /
    regroup_and_band_content).

    ⚠️ 2026-07-29: hai hàm này TỒN TẠI TỪ 2026-07-23 và `review_to_sheet.py`
    vẫn gọi sau mỗi lượt crawl — nhưng `render_*_to_sheet()` trước đây gọi
    `ws.clear()`, XOÁ SẠCH băng màu chúng vừa tô, mỗi vòng worker. Logic không
    hề mất; nó bị ghi đè liên tục. Nay render không clear nữa VÀ tự tô lại ở
    đây, nên khối ngày sống qua mọi lượt cập nhật.
    KHÔNG viết hàm tô mới — dùng đúng hàm đã có, tránh 2 định nghĩa lệch nhau."""
    fn = getattr(board, method, None)
    if fn is None:
        return          # fake board trong test
    try:
        fn()
    except Exception as e:   # noqa: BLE001 -- lớp trình bày, không chặn dữ liệu
        print(f"[sync] Tô khối ngày {tab} thất bại (bỏ qua, dữ liệu vẫn đúng): {e!r}")


def _visible_rows(rows: list[list[str]], i_ts: int, *, settings=None) -> list[list[str]]:
    """Giữ lại dòng trong `sheets.display_days` ngày gần nhất (mặc định 7).

    Quy ước Lead: Sheet là BẢNG LÀM VIỆC, không phải kho — dữ liệu từ ngày thứ
    8 trở về trước CHỈ nằm trong DB, không hiển thị. Không xoá gì khỏi DB:
    đổi `display_days` rồi render lại là dòng cũ hiện lại ngay.
    `display_days: 0` -> hiện tất cả (đường thoát khi cần soi lịch sử)."""
    if settings is None:
        # Tự nạp config khi caller không truyền — để MỌI lối gọi hiện có
        # (worker, sync_store_sheet, script tay) đều tôn trọng display_days mà
        # không phải sửa từng chỗ. Thiếu config -> mặc định 7, không nổ.
        try:
            from twmkt.config import load_settings
            settings = load_settings()
        except Exception:   # noqa: BLE001
            settings = None
    days = 7
    if settings is not None:
        try:
            days = int(settings.get("sheets.display_days", 7))
        except (TypeError, ValueError):
            days = 7
    if days <= 0:
        return rows
    from datetime import date, timedelta
    cutoff = date.today() - timedelta(days=days - 1)
    ck = (cutoff.year, cutoff.month, cutoff.day)
    out = []
    for r in rows:
        k = _day_key(r[i_ts] if i_ts < len(r) else "")
        if k == (0, 0, 0) or k >= ck:   # ngày hỏng -> GIỮ, không âm thầm giấu
            out.append(r)
    return out


def _day_key(ts: str) -> tuple[int, int, int]:
    """"DD/MM/YYYY" -> (yyyy, mm, dd) để SẮP XẾP. Chuỗi lạ -> (0,0,0) (xuống
    cuối) chứ KHÔNG raise: 1 ô ngày hỏng không đáng làm hỏng cả lượt render."""
    parts = (ts or "").strip().split("/")
    if len(parts) != 3:
        return (0, 0, 0)
    try:
        d, m, y = (int(x) for x in parts)
        return (y, m, d)
    except ValueError:
        return (0, 0, 0)


def _write_rows(board: SheetsBoard, tab: str, header: list[str], rows: list[list[str]]) -> None:
    """Ghi GIÁ TRỊ vào tab — KHÔNG `clear()` cả bảng.

    ⚠️ THAY ĐỔI CỐT LÕI 2026-07-29 (Lead: "thiết lập của user bị ghi đè",
    "block dữ liệu theo ngày chưa có"). Bản cũ gọi `ws.clear()` rồi ghi lại tất
    cả — mà `clear()` XOÁ CẢ ĐỊNH DẠNG: băng màu, viền, mọi thiết lập hiển thị
    người dựng tay đều bay sau MỖI lượt render (worker render sau mỗi job).
    Không có cách nào "tô lại cho kịp" — cứ tô xong lại bị xoá ở lượt sau.

    ⚠️ THAY ĐỔI TIẾP 2026-08-02 (Lead — sự cố "Output Type bị khoá"): bản
    2026-07-29 vẫn `ws.update("A2", TOÀN BỘ rows, ...)` MỖI LẦN render (chạy
    SAU MỌI job worker xử lý xong — rất thường xuyên), dù tuyệt đại đa số dòng
    KHÔNG đổi gì. `Output Type` là ô "dropdown chip multi-select" Lead tự bật
    TAY qua UI Sheets (API v4 không tạo/đọc được kiểu ô này, xem sheets_board.
    OUTPUT_TYPE_COL) — ghi giá trị thô qua API vào ô đang ở dạng chip đó,
    ngay cả khi giá trị GIỐNG HỆT, là thao tác Google không cam kết giữ
    nguyên trạng thái UI chip. Giờ SO KHỚP từng dòng với Sheet HIỆN TẠI
    (đã có sẵn trong `current`, không tốn thêm lượt đọc) — dòng giống hệt
    KHÔNG đụng tới (không gọi update() lên range của nó), CHỈ ghi dòng
    thật sự đổi. Các dòng đổi LIÊN TIẾP được gộp thành 1 khối/1 lệnh update
    (tránh nổ N lệnh API rời rạc khi nhiều dòng cùng đổi, vd lần render đầu
    hoặc sắp lại thứ tự theo ngày).

    `values.update` KHÔNG đụng tới format, nên chỉ ghi giá trị là định dạng
    sống nguyên. Dòng THỪA (bảng co lại) được `batch_clear` RIÊNG phần đuôi —
    hẹp nhất có thể, không chạm vùng còn dữ liệu."""
    ws = board._tab(tab)
    ncols = len(header)
    current = ws.get_all_values()
    # Header: chỉ ghi khi THIẾU/SAI. Ghi đè vô cớ mỗi lượt là tự xoá định dạng
    # hàng tiêu đề — đúng thứ vừa sửa ở dưới.
    if not current or [c.strip() for c in current[0]] != list(header):
        ws.update("A1", [list(header)], value_input_option="USER_ENTERED")
    current_rows = current[1:] if len(current) > 1 else []

    diff_idx = []
    for i, new_row in enumerate(rows):
        old_row = current_rows[i] if i < len(current_rows) else []
        padded_old = list(old_row) + [""] * max(0, ncols - len(old_row))
        if padded_old[:ncols] != list(new_row):
            diff_idx.append(i)

    block_start = None
    for j, i in enumerate(diff_idx):
        if block_start is None:
            block_start = i
        is_last = j == len(diff_idx) - 1
        next_is_contiguous = (not is_last) and (diff_idx[j + 1] == i + 1)
        if not next_is_contiguous:
            block = rows[block_start:i + 1]
            ws.update(f"A{block_start + 2}", block, value_input_option="USER_ENTERED")
            block_start = None

    old_n = max(len(current) - 1, 0)
    if old_n > len(rows):
        last_col = _col_a1(ncols)
        ws.batch_clear([f"A{len(rows) + 2}:{last_col}{old_n + 1}"])


def _asset_cell(status_data: dict) -> str:
    """Ô AssetPath trên Sheet từ content_status. `asset_url` -> công thức
    HYPERLINK bấm được; không có URL thì lùi về đường file cục bộ (không bọc
    — không bấm được, nhưng vẫn cho người biết ảnh nằm đâu); không có gì ->
    rỗng.

    Công thức viết TẠI ĐÂY thay vì import từ
    `scripts/render_production_assets.py::asset_hyperlink_formula()`: store/ là
    tầng dưới, KHÔNG được phụ thuộc vào scripts/ (script là tầng vận hành, gọi
    xuống store chứ không ngược lại). Một dòng f-string, và có test khoá 2 lối
    ghi ra CÙNG chuỗi -- xem test_asset_cell_matches_render_script_formula."""
    url = (status_data.get("asset_url") or "").strip()
    if url:
        return f'=HYPERLINK("{url}", "Mở file")'
    local = (status_data.get("asset_local_path") or "").strip()
    if local:
        return local
    # CHƯA có asset nhưng NGƯỜI ĐÃ DUYỆT Gate 2 -> hệ thống đang xử lý
    # (2026-07-28, yêu cầu Lead). Ô trống trong quãng này khiến người duyệt
    # tưởng hệ thống không nhận — render ảnh mất hàng chục giây tới vài phút.
    # CÙNG TINH THẦN cờ Execute="Running..." bên tab CONTEXT: phản hồi thị giác
    # cho quãng chờ dài. Suy ra TỪ gate2, KHÔNG thêm field mới vào store —
    # trạng thái phái sinh thì tính lúc hiển thị, không lưu (lưu là tự tạo thêm
    # 1 thứ có thể lệch với sự thật).
    if (status_data.get("gate2") or "").strip().upper() == "APPROVE":
        return ASSET_PROCESSING_LABEL
    return ""


# VIỆC 4 (2026-08-03, Lead) — Output Type=AUTO nghĩa là NGƯỜI ỦY QUYỀN cho
# Composer tự định tuyến; khi cả 3 tuyến đều KHÔNG sinh ra gì (0 DONE), hiển
# thị riêng từng dòng ERROR/SKIPPED là NHIỄU (người không hề yêu cầu tuyến cụ
# thể nào để cần giải thích riêng từng tuyến). Nhãn TỰ NHIÊN dùng trong câu gộp
# — thứ tự CỐ ĐỊNH (Bài viết trước, khớp ví dụ Nafoods Lead đưa).
_AUTO_MERGE_CHANNEL_LABEL_VI = (("article", "Bài viết"), ("infographic", "Ảnh"), ("video", "Video"))


def _is_auto_output_type(output_type: list[str] | None) -> bool:
    """AUTO = output_type rỗng HOẶC có "AUTO" — CÙNG ngữ nghĩa với scripts/
    produce_from_sheet._allowed_output_types() (KHÔNG import chéo qua scripts/,
    store/ không phụ thuộc tầng vận hành — xem docstring module)."""
    return not output_type or "AUTO" in output_type


def _auto_merge_notes(type_outs: list[tuple[str, dict]]) -> str:
    """VIỆC 4.2/4.3 — GỘP Ở TẦNG HIỂN THỊ (hàm này chỉ dựng 1 CÂU cho Sheet,
    KHÔNG đụng store — store vẫn giữ đủ bản ghi từng loại kèm mã lý do gốc,
    xem render_content_to_sheet()). Mỗi nguyên nhân dịch qua _display_notes_
    business() (VIỆC 5, câu nghiệp vụ, không thuật ngữ kỹ thuật) TRƯỚC khi gộp."""
    parts = []
    for type_, out in type_outs:
        label = dict(_AUTO_MERGE_CHANNEL_LABEL_VI).get(type_)
        if label is None:
            continue
        msg = _display_notes_business(out.get("notes", "")).rstrip(". ") or "không rõ nguyên nhân"
        parts.append(f"{label}: {msg}")
    body = ". ".join(parts)
    return f"Không tạo được nội dung nào. {body}." if body else "Không tạo được nội dung nào."


# SỰ CỐ THẬT (2026-08-04, phát hiện ngay lượt sync_all() đầu tiên sau khi
# nâng _OUTPUT_PREVIEW 1500->5000) — hậu tố này PHẢI là hằng số dùng chung
# giữa _preview_output() (ghi) và ingest_content_from_sheet() (đọc, kiểm
# tra). Trước đó ingest chỉ so `sheet_output != store_output.strip()` để
# quyết "người vừa sửa tay" — lượt sync ĐẦU TIÊN sau khi đổi ngưỡng, Sheet
# còn giữ NGUYÊN bản CẮT Ở NGƯỠNG CŨ (1500) từ trước khi deploy, ingest chạy
# TRƯỚC render (xem sync_all()) nên đọc phải bản cắt cũ đó, so với store đủ
# 2000-5000 ký tự -> luôn "khác nhau" giả -> ghi ĐÈ content_output THẬT bằng
# bản CẮT + hậu tố này (đã xảy ra thật: 17 bản ghi production bị ghi đè
# thành 1550 ký tự, phải phục hồi tay từ version trước). Sửa: sheet_output
# TRÙNG hậu tố này (đuôi) -> chắc chắn là ảnh còn sót của 1 lượt render CẮT
# nào đó (dù ngưỡng cũ hay mới) -- KHÔNG BAO GIỜ coi là người sửa tay, bất kể
# so khớp độ dài thế nào.
_TRUNCATION_SUFFIX = "\n…(bản đầy đủ nằm trong Store, xem content_output)"


def _preview_output(output: str) -> str:
    if len(output) <= _OUTPUT_PREVIEW:
        return output
    return output[:_OUTPUT_PREVIEW] + _TRUNCATION_SUFFIX

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

_CONTENT_MACHINE_COLS = ("Timestamp", "Context", "Type", "Status",
                         "Notes", "TopicKey", "Facts", "AssetPath")
_CONTENT_USER_COLS = (GATE2_COL, "Social Link", GATE3_COL, "Posting Status")
# "Output" -- NGOẠI LỆ CỐ Ý duy nhất khỏi "KHÔNG CỘT NÀO 2 CHIỀU" (Việc 2,
# 2026-08-04, Lead): máy ghi TRƯỚC lúc sản xuất xong, nhưng người có thể sửa
# tay TRÊN SHEET trước khi duyệt Gate 2 -- sửa PHẢI ghi ngược vào
# content_output (xem ingest_content_from_sheet()). CHỈ áp dụng khi bản lưu
# store <= _OUTPUT_PREVIEW ký tự (không bị _preview_output() cắt) -- so khớp
# 1 bản Sheet đã cắt với bản store nguyên văn dài hơn sẽ luôn "khác nhau" giả,
# nên ingest CHỦ ĐỘNG bỏ qua write-back khi phát hiện đã cắt (không đoán, không
# ghi đè nhầm bài dài thành bản cụt).


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


# --- CAS theo timestamp cho cột NGƯỜI-SỞ-HỮU của CONTEXT (TASK-030) ---------
# BUG THẬT đã tái lập (TASK-029, tests/test_race_render_ingest.py): render
# đọc 1 ẢNH CHỤP store (vd store TẠM CŨ do 1 job KHÁC kích, đọc TRƯỚC khi
# 1 lượt ingest khác kịp ghi APPROVE) rồi ghi đè VÔ ĐIỀU KIỆN 3 cột người-sở-
# hữu (Duyệt Context/Notes/Output Type) — nuốt mất APPROVE người vừa bấm nếu
# ảnh chụp đó cũ hơn. `gate_status` đã append-only + có `created_at` mỗi
# version SẴN (document_store.py) -- không cần đổi schema để vá.
_GATE1_CELL = lambda payload: payload.get("gate1", "PENDING")   # noqa: E731
_NOTES_CELL = lambda payload: payload.get("notes", "")   # noqa: E731
_OUTPUT_TYPE_CELL = lambda payload: ", ".join(payload.get("output_type") or ["AUTO"])   # noqa: E731


def _cas_user_value(history: list[tuple[int, dict, str]], field_cell, sheet_current: str | None, store_latest: str) -> str:
    """CAS THEO TIMESTAMP cho 1 cột NGƯỜI-SỞ-HỮU. `history` = `ds.read_history()`
    của gate_status (version tăng dần, MỖI version có sẵn `created_at`).
    `sheet_current=None` -- dòng CHƯA có trên Sheet (topic mới/dòng vừa mất)
    -> ghi tự do, không có gì để bảo vệ. Giống `store_latest` -> không xung
    đột. KHÁC NHAU -> CHỈ ghi đè khi CHỨNG MINH ĐƯỢC: giá trị hiện có trên
    Sheet KHỚP đúng 1 version CŨ HƠN (created_at bé hơn) version mới nhất
    trong lịch sử -- bằng chứng store đã tiến xa hơn giá trị Sheet đang hiện
    (vd Sheet bị reset/xoá nhầm, đây CHÍNH LÀ đường phục hồi Bước 5.4). KHÔNG
    khớp version nào (giá trị Sheet chưa từng xuất hiện trong lịch sử ẢNH
    CHỤP đang đọc -- đúng kịch bản race TASK-029: ảnh chụp cũ chưa hề thấy
    version APPROVE mà 1 tiến trình khác vừa ghi) -> KHÔNG chứng minh được
    nguồn gốc -> GIỮ NGUYÊN ô Sheet (thiên lệch an toàn, xem docstring module:
    ô chậm vài giây là phiền, thao tác người bị nuốt là mất dữ liệu)."""
    if not history or sheet_current is None or sheet_current == store_latest:
        return store_latest
    latest_created_at = history[-1][2]
    for _version, payload, created_at in reversed(history[:-1]):
        if created_at <= latest_created_at and field_cell(payload) == sheet_current:
            return store_latest
    return sheet_current


# =============================================================================
# store -> Sheet (render, idempotent, = lệnh phục hồi)
# =============================================================================

def render_context_to_sheet(board: SheetsBoard, *, db_path=None, settings=None, rebuild: bool = True) -> int:
    """Dựng lại TOÀN BỘ tab CONTEXT từ store — bao gồm CẢ Duyệt Context/Notes/
    Output Type, đọc THẲNG từ gate_status. 3 cột NGƯỜI-SỞ-HỮU này KHÔNG còn
    ghi đè vô điều kiện MẶC ĐỊNH (TASK-030, vá race render/ingest) -- khi
    `rebuild=False` đi qua CAS theo timestamp (`_cas_user_value()`, xem
    docstring): so giá trị store với giá trị HIỆN CÓ trên Sheet trước khi ghi,
    chỉ ghi đè khi chứng minh được store mới hơn.

    TASK-032 -- `rebuild` (mặc định True) LÀ TÍN HIỆU TƯỜNG MINH bắt buộc phải
    có, không suy luận được từ dữ liệu ô. Lý do: TASK-030 để lộ 1 mâu thuẫn
    ngữ nghĩa thật -- khi gate_status của 1 topic CHỈ CÓ ĐÚNG 1 version (chưa
    từng qua ingest thật, vd topic nạp thẳng bằng script/test), Sheet hiện giá
    trị KHÁC store rơi vào ĐÚNG 1 nhánh "không version nào chứng minh được" của
    `_cas_user_value()` -- và XÉT THUẦN TỪ (history, sheet_current,
    store_latest), nhánh đó Y HỆT kịch bản race thật (TASK-029, xem
    tests/test_race_render_ingest.py::test_regression_stale_render_snapshot_
    overwrites_approve_before_next_ingest) mà CAS phải BẢO VỆ (giữ nguyên Sheet).
    2 kịch bản chỉ khác nhau ở Ý ĐỊNH của lượt gọi -- không có cách phân biệt
    bằng dữ liệu, y hệt bằng chứng đã thấy ở test_render_context_to_sheet_
    without_prior_ingest_reflects_store_not_sheet (store/test_sync_service.py)
    kỳ vọng store thắng cho ĐÚNG kịch bản dữ liệu đó. Do đó:

      rebuild=True (MẶC ĐỊNH, hành vi CŨ trước TASK-030) -- BỎ QUA CAS hoàn
        toàn cho 3 cột người-sở-hữu, store LUÔN thắng. Đây là lựa chọn AN TOÀN
        cho lối gọi TRỰC TIẾP/thủ công KHÔNG chủ động ingest trước (test, lệnh
        `scripts/sync_store_sheet.py --from-store`, script vá tay) -- đúng
        đường phục hồi Bước 5.4 ("Sheet đang sai, muốn store thắng tuyệt đối").
      rebuild=False -- CAS áp dụng (`_cas_user_value()`), bảo vệ thao tác
        người khỏi bị 1 ảnh chụp store CŨ ghi đè (TASK-029). CHỈ 2 nơi cần
        truyền rebuild=False, cả 2 đều là lượt sync TỰ ĐỘNG lặp lại (có race
        thật giữa nhiều tiến trình): `scripts/queue_worker.py::_sync_sheet()`
        và `sync_all()` bên dưới.

    Đường phục hồi Bước 5.4 khi Sheet bị XOÁ (không phải "giá trị sai") không
    phụ thuộc `rebuild` -- `sheet_row is None` luôn để store thắng vô điều kiện
    (xem nhánh `sheet_current is None` trong `_cas_user_value()`), kể cả khi
    `rebuild=False` (xem test_sync_all_full_recovery_after_accidental_deletion)."""
    existing_header, existing_rows = _read_sheet_rows(board, "CONTEXT")
    i_sheet_key = _col_index(existing_header, "TopicKey")
    i_sheet_g1 = _col_index(existing_header, GATE1_COL)
    i_sheet_notes = _col_index(existing_header, "Notes")
    i_sheet_ot = _col_index(existing_header, OUTPUT_TYPE_COL)
    sheet_by_key: dict[str, list[str]] = {}
    if i_sheet_key is not None:
        for r in existing_rows:
            tk = _cell(r, i_sheet_key)
            if tk:
                sheet_by_key[tk] = r

    i_out_g1 = CONTEXT_HEADER.index(GATE1_COL)
    i_out_notes = CONTEXT_HEADER.index("Notes")
    i_out_ot = CONTEXT_HEADER.index(OUTPUT_TYPE_COL)

    keyed_rows: list[tuple[str, list[str]]] = []
    for topic_key in ds.list_topics(layer="raw", db_path=db_path):
        raw = ps.read_raw(topic_key, db_path=db_path) or {}
        gate = ps.read_gate_status(topic_key, db_path=db_path)
        row = context_row(
            title=raw.get("context", ""), hook_line=raw.get("hook", ""),
            source_url=raw.get("source", ""),
            score=int(raw.get("score", 0) or 0), hot_pct=float(raw.get("hot_pct", 0.0) or 0.0),
            topic=raw.get("topic", ""), group=raw.get("group", ""),
            tickers=raw.get("tickers", []), status=gate.get("gate1", "PENDING"),
            # VIỆC Execute (2026-08-03, Lead) — ĐẢO LẠI quyết định 2026-07-28
            # (khi đó ép "Waiting" cho MỌI Execute rỗng để tránh trông như "hệ
            # thống chưa thấy dòng này"). Lead giờ muốn phân biệt RÕ 2 trạng
            # thái: "" = mới crawl, CHƯA qua Gate 1 (chưa có gì để chờ) khác
            # "Waiting" = ĐÃ duyệt, đang xếp hàng. Hiển thị ĐÚNG giá trị store
            # (ingest_context_from_sheet() đã tự set "Waiting" đúng lúc Gate 1
            # chuyển APPROVE — xem đó), không tự đoán/ép ở đây nữa. Execute là
            # cột HỆ THỐNG sở hữu hoàn toàn (worker ghi) -- KHÔNG qua CAS.
            execute=gate.get("execute", ""),
            topic_key=topic_key, notes=gate.get("notes", ""),
            output_type=gate.get("output_type") or [],
            # BUG THẬT (Lead báo 2026-07-29): KHÔNG truyền `ts` thì context_row
            # lấy _now_ddmmyyyy() -> MỖI LƯỢT RENDER ghi đè Timestamp thành
            # HÔM NAY. Mọi dòng crawl 28/07 hoá thành 29/07, không còn phân
            # biệt được tin ngày nào — đúng thứ Lead cần để lọc/nhóm theo ngày.
            # `raw["timestamp"]` ghi MỘT LẦN lúc ingest đầu, không đổi về sau.
            ts=raw.get("timestamp") or None,
        )

        # rebuild=True (mặc định) -- BỎ QUA CAS, giữ nguyên giá trị store vừa
        # tính ở row[...] (đã đúng "store thắng"). Chỉ khi rebuild=False (lượt
        # sync tự động, có race thật) mới đọc lịch sử + so khớp CAS.
        if not rebuild:
            sheet_row = sheet_by_key.get(topic_key)
            gate_history = ds.read_history(topic_key, "gate_status", "", db_path=db_path)
            row[i_out_g1] = _cas_user_value(
                gate_history, _GATE1_CELL,
                _cell(sheet_row, i_sheet_g1) if sheet_row is not None else None, row[i_out_g1])
            row[i_out_notes] = _cas_user_value(
                gate_history, _NOTES_CELL,
                _cell(sheet_row, i_sheet_notes) if sheet_row is not None else None, row[i_out_notes])
            row[i_out_ot] = _cas_user_value(
                gate_history, _OUTPUT_TYPE_CELL,
                _cell(sheet_row, i_sheet_ot) if sheet_row is not None else None, row[i_out_ot])

        keyed_rows.append((topic_key, row))

    i_ts = CONTEXT_HEADER.index("Timestamp")
    visible = {id(r) for r in _visible_rows([r for _, r in keyed_rows], i_ts, settings=settings)}
    keyed_visible = [(tk, r) for tk, r in keyed_rows if id(r) in visible]
    # VIỆC sắp xếp (2026-08-03, Lead) — BỎ tie-break theo Hot% (dữ liệu mới
    # crawl cùng ngày bị xếp lẫn lộn vì Hot% không phản ánh THỨ TỰ VÀO HỆ
    # THỐNG). Thay bằng first_created_at() (thời điểm bản ghi "raw" ĐẦU TIÊN
    # của topic — xem docstring document_store.first_created_at) làm khoá phụ:
    # NGÀY TĂNG DẦN, trong cùng ngày THEO ĐÚNG THỨ TỰ CRAWL -> tin mới nhất
    # luôn nằm dưới cùng, không còn xáo trộn theo alphabet của topic_key (thứ
    # tự list_topics() trả về, vốn KHÔNG có ý nghĩa thời gian).
    keyed_visible.sort(key=lambda tr: (
        _day_key(tr[1][i_ts]),
        ds.first_created_at(tr[0], "raw", "", db_path=db_path) or "",
    ))
    out_rows = [r for _, r in keyed_visible]

    _write_rows(board, "CONTEXT", CONTEXT_HEADER, out_rows)
    _band_day(board, "band_context_by_day", "CONTEXT")
    return len(out_rows)


def render_content_to_sheet(board: SheetsBoard, *, db_path=None, settings=None) -> int:
    """Dựng lại TOÀN BỘ tab CONTENT từ store. Đọc TRƯỚC giá trị NGƯỜI-SỞ-HỮU
    hiện có — bao gồm CẢ Duyệt Content/Social Link/Duyệt Public/Posting
    Status, đọc THẲNG từ content_status (KHÔNG đọc lại Sheet hiện tại trước
    khi xoá — cùng lý do render_context_to_sheet(), xem docstring đó).
    content_row() hard-code Duyệt Public="PENDING" (INVARIANT — KHÔNG luồng
    máy nào được ghi Gate3, xem docstring content_row()) nên override 3 cột
    người-sở-hữu SAU khi gọi, bằng giá trị đọc từ content_status — vẫn KHÔNG
    máy TỰ SINH giá trị, chỉ phản ánh lại cái người đã ghi (qua ingest).

    Cột Output ghi lên Sheet đi qua `_preview_output()` (cắt ở _OUTPUT_PREVIEW
    ký tự, hiện 5000 — Việc 2, 2026-08-04). Bài NGẮN hơn ngưỡng hiện NGUYÊN
    VĂN (không cắt) — người có thể sửa tay ô này, `ingest_content_from_sheet()`
    đọc lại và ghi ngược vào content_output (xem ghi chú _CONTENT_USER_COLS).

    VIỆC 3 (2026-08-04, Lead):
    (a) Timestamp hiển thị đổi sang `published_at` (ngày ĐĂNG BÀI GỐC, cùng ý
        nghĩa cột Timestamp bên tab CONTEXT), lùi về `timestamp` (ngày XỬ LÝ)
        khi bản ghi cũ chưa có published_at.
    (b) Thứ tự dòng: NGÀY tăng dần, trong cùng ngày theo `first_created_at()`
        của chính bản ghi content_output đó (KHÔNG theo alphabet topic_key) —
        cùng cách CONTEXT đã sửa (Task #75).
    (c) "Người thực hiện" — đọc giá trị HIỆN CÓ trên Sheet (không có store
        backing, người tự gõ tay) TRƯỚC khi dựng lại, khoá theo (TopicKey,
        Type hiển thị) vì thứ tự dòng đổi mỗi lượt sort, rồi carry-forward
        sang dòng mới — máy KHÔNG được tự xoá giá trị người gõ."""
    i_h_type = CONTENT_HEADER.index("Type")
    i_h_social = CONTENT_HEADER.index("Social Link")
    i_h_g3 = CONTENT_HEADER.index(GATE3_COL)
    i_h_posting = CONTENT_HEADER.index("Posting Status")
    i_h_nguoi = CONTENT_HEADER.index("Người thực hiện")

    existing_header, existing_rows = _read_sheet_rows(board, "CONTENT")
    nguoi_thuc_hien_by_key: dict[tuple[str, str], str] = {}
    if existing_header:
        j_tk = _col_index(existing_header, "TopicKey")
        j_type = _col_index(existing_header, "Type")
        j_nguoi = _col_index(existing_header, "Người thực hiện")
        if j_tk is not None and j_type is not None and j_nguoi is not None:
            for r in existing_rows:
                tk = _cell(r, j_tk)
                if tk:
                    nguoi_thuc_hien_by_key[(tk, _cell(r, j_type))] = _cell(r, j_nguoi)

    # (topic_key, content_type dùng để tra first_created_at(), row) — content_type
    # riêng vì AUTO gộp vẫn cần khoá theo tuyến ĐẦU TIÊN thử (type_outs[0]) để
    # sắp xếp có ý nghĩa (topic_key một mình không đủ phân biệt các dòng khác
    # type cùng topic_key).
    keyed_rows: list[tuple[str, str, list[str]]] = []
    for topic_key in ds.list_topics(layer="content_output", db_path=db_path):
        raw = ps.read_raw(topic_key, db_path=db_path) or {}
        context_title = raw.get("context", "")
        gate = ps.read_gate_status(topic_key, db_path=db_path)
        is_auto = _is_auto_output_type(gate.get("output_type"))

        type_outs: list[tuple[str, dict]] = []
        for type_ in _ALL_TYPES:
            out = ps.read_content_output(topic_key, type_, db_path=db_path)
            if out is not None:
                type_outs.append((type_, out))

        # VIỆC 4.1 — CHỈ áp gộp khi AUTO. Output Type tường minh (Article/
        # Long-Article/Infographic/Video) GIỮ NGUYÊN hành vi cũ: mỗi loại 1
        # dòng, kể cả ERROR (người CHỌN loại đó, hỏng thì phải thấy Status=
        # ERROR đúng loại đã chọn — che thành AUTO là giấu việc hệ thống không
        # làm được điều người yêu cầu).
        has_done = any(out.get("status") == "DONE" for _, out in type_outs)
        if is_auto and not has_done and type_outs:
            # VIỆC 4.2 — định tuyến AUTO thất bại HOÀN TOÀN (0 DONE trong mọi
            # tuyến đã thử) -> ĐÚNG 1 dòng Type=AUTO/Status=ERROR/Notes gộp đủ
            # nguyên nhân từng loại (VIỆC 4.3: GỘP Ở TẦNG HIỂN THỊ, store vẫn
            # giữ nguyên `type_outs` từng bản ghi — không đụng gì ở đây).
            merged_notes = _auto_merge_notes(type_outs)
            first_type, first_out = type_outs[0]
            row = content_row(
                context=context_title, type_="AUTO", status="ERROR",
                output="", notes=merged_notes, approve="PENDING", topic_key=topic_key,
                facts="", ts=first_out.get("published_at") or first_out.get("timestamp") or None,
                asset_path="",
            )
            row[i_h_nguoi] = nguoi_thuc_hien_by_key.get((topic_key, row[i_h_type]), "")
            keyed_rows.append((topic_key, first_type, row))
            continue

        for type_, out in type_outs:
            if is_auto and has_done and out.get("status") == "ERROR":
                # VIỆC 4.2 — AUTO định tuyến THÀNH CÔNG (≥1 tuyến DONE): BỎ
                # dòng của loại LỖI (Status=ERROR) — SKIPPED (Router chủ động
                # từ chối, đã có Notes giải thích riêng, KHÔNG PHẢI lỗi) vẫn
                # hiện bình thường, không đụng.
                continue
            status_data = ps.read_content_status(topic_key, type_, db_path=db_path)
            row = content_row(
                context=context_title, type_=type_, status=out.get("status", ""),
                output=_preview_output(out.get("output", "")), notes=out.get("notes", ""),
                approve=status_data.get("gate2", "PENDING"), topic_key=topic_key,
                facts=out.get("facts", ""),
                # VIỆC 3.1 (2026-08-04) — Timestamp CONTENT giờ ưu tiên ngày
                # ĐĂNG BÀI GỐC (published_at, cùng ý nghĩa cột CONTEXT), lùi về
                # ngày XỬ LÝ (timestamp) cho bản ghi cũ chưa có published_at.
                ts=out.get("published_at") or out.get("timestamp") or None,
                # Store giữ URL THUẦN (asset_url) — bọc thành công thức
                # HYPERLINK ở ĐÚNG biên đẩy sang Sheet, cùng nếp
                # `_preview_output()`: định dạng cho người xem là việc của lớp
                # hiển thị, không phải của kho dữ liệu. Trùng khớp cái
                # render_production_assets.py ghi thẳng ô Sheet cho đường chạy
                # tay, nên 2 lối cho ra CÙNG 1 giá trị.
                asset_path=_asset_cell(status_data),
            )
            row[i_h_social] = status_data.get("social_link", "")
            row[i_h_g3] = status_data.get("gate3", "PENDING")
            row[i_h_posting] = status_data.get("posting_status", "")
            row[i_h_nguoi] = nguoi_thuc_hien_by_key.get((topic_key, row[i_h_type]), "")
            keyed_rows.append((topic_key, type_, row))

    i_ts_c = CONTENT_HEADER.index("Timestamp")
    visible = {id(r) for r in _visible_rows([r for _, _, r in keyed_rows], i_ts_c, settings=settings)}
    keyed_visible = [(tk, ct, r) for tk, ct, r in keyed_rows if id(r) in visible]
    # VIỆC 3.2/3.3 — cùng cách CONTEXT (Task #75): NGÀY tăng dần, trong cùng
    # ngày theo first_created_at() của CHÍNH bản ghi content_output (không
    # theo alphabet topic_key) -> "mới nhất luôn dưới cùng" đúng nghĩa CRAWL/
    # XỬ LÝ, không lẫn lộn trong 1 ngày.
    keyed_visible.sort(key=lambda tr: (
        _day_key(tr[2][i_ts_c]),
        ds.first_created_at(tr[0], "content_output", tr[1], db_path=db_path) or "",
    ))
    out_rows = [r for _, _, r in keyed_visible]
    _write_rows(board, "CONTENT", CONTENT_HEADER, out_rows)

    # BĂNG MÀU theo TopicKey + viền theo NGÀY (Lead báo thiếu 2026-07-29).
    # `clear()` xoá cả nền/viền nên PHẢI tô lại sau MỖI lần dựng tab, không thì
    # tab CONTENT trắng trơn, nhìn không ra đâu là nhóm của cùng 1 chủ đề.
    # Đặt trong try: đây là lớp TRÌNH BÀY — hỏng nó không đáng làm hỏng cả lượt
    # sync (dữ liệu đã ghi xong ở trên rồi). Fake board trong test không có
    # method này -> bỏ qua êm, không cần fake thêm.
    _band_day(board, "regroup_and_band_content", "CONTENT")
    return len(out_rows)


# =============================================================================
# Sheet -> store (ingest thao tác người + cầu nối topic mới từ review_to_sheet.py)
# =============================================================================

def ingest_context_from_sheet(board: SheetsBoard, *, db_path=None) -> int:
    """Đọc CONTEXT hiện tại, ghi version MỚI vào store cho: (1) topic MỚI
    (TopicKey có trên Sheet, store CHƯA có raw — CẦU NỐI TẠM, xem docstring
    module), (2) Duyệt Context/Notes đổi so với gate_status hiện có, (3)
    NGOẠI LỆ Execute: NEEDS_HUMAN -> RUN (người yêu cầu thử lại, xem Phase
    4.9). Trả số lần ghi (write_document calls).

    PHASE QUEUE (2026-07-27): MỌI lần Execute chuyển thành "RUN" ở đây (bootstrap
    Gate1 vừa APPROVE, HOẶC NEEDS_HUMAN->RUN người yêu cầu thử lại) ĐỀU gọi
    thêm `queue_store.enqueue()` — đây là điểm enqueue TỰ ĐỘNG duy nhất (đối
    xứng với enqueue THỦ CÔNG qua `api/main.py::webhook_execute()`).
    `gate_status.execute="RUN"` VẪN được ghi y hệt trước (Sheet hiển thị không
    đổi, `run_draft()` vẫn lọc execute=="RUN" như cũ) — hàng đợi là 1 khái
    niệm KHÁC (đã dispatch xử lý chưa), KHÔNG thay thế cờ Execute."""
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
    i_ts = _col_index(header, "Timestamp")

    writes = 0
    deleted_rows: list[int] = []
    for row_i, row in enumerate(rows, start=2):   # +2: hàng 1 là header
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
        # 2026-07-28 — Execute KHÔNG CÒN ĐƯỢC ĐỌC TỪ SHEET.
        # Trước đây cột này 2 chiều qua 2 "khe hẹp" (rỗng->RUN khi vừa APPROVE;
        # NEEDS_HUMAN->RUN khi người xin chạy lại). Nay Execute là cờ TRẠNG
        # THÁI MÁY-GHI, read-only với người (dropdown đã gỡ + Protected Range,
        # xem sheets_board.EXECUTE_VALUES) -> đọc ngược từ Sheet là VÔ NGHĨA và
        # nguy hiểm: giá trị người lỡ gõ sẽ ghi đè trạng thái thật trong store.
        # Cột này giờ THUẦN MỘT CHIỀU store->Sheet.
        #
        # Hệ quả: cổng điều khiển DUY NHẤT còn lại là Gate 1. Enqueue xảy ra
        # khi Gate 1 CHUYỂN sang APPROVE (xem `_should_enqueue` bên dưới) —
        # cũng chính là đường CHẠY LẠI sau NEEDS_HUMAN: bỏ APPROVE rồi APPROVE
        # lại, Execute reset về Waiting và job mới vào hàng đợi.

        # XOÁ CHỦ ĐỀ (2026-07-29, quyết định Lead) — xử lý TRƯỚC mọi nhánh
        # khác: người đã ra lệnh bỏ hẳn thì không cần ingest/enqueue gì nữa.
        # Job chờ bị huỷ; job ĐANG CHẠY vẫn chạy nốt (cùng lý do
        # cancel_pending: giết giữa chừng là nguồn bug), nhưng kết quả của nó
        # sẽ ghi vào một topic_key không còn ai đọc — vô hại.
        # Dòng biến mất khỏi Sheet ở lượt render kế tiếp vì store hết dữ liệu.
        if sheet_gate1.upper() == "DELETE":
            qs.cancel_pending(topic_key, db_path=db_path, reason="người xoá chủ đề (Gate 1=DELETE)")
            n = ds.delete_topic(topic_key, db_path=db_path)
            # XOÁ DÒNG NGAY trên Sheet (2026-07-29, yêu cầu Lead: "thực thi
            # realtime"). Không chờ lượt render kế tiếp — người bấm xong phải
            # thấy dòng biến mất luôn, nếu không sẽ tưởng lệnh không ăn.
            # `row_i` là chỉ số dòng THẬT của vòng lặp này; ta xoá NGAY nên
            # không có cửa sổ để bảng bị sắp lại giữa chừng (đúng bài học
            # row-index đã gây lỗi trước đây).
            deleted_rows.append(row_i)
            print(f"[sync] ĐÃ XOÁ chủ đề {topic_key[:8]} khỏi DB ({n} document) "
                  f"và khỏi Sheet. KHÔNG hoàn tác được.")
            writes += 1
            continue

        if ps.read_raw(topic_key, db_path=db_path) is None:
            # Cầu nối tạm: topic MỚI từ review_to_sheet.py, chưa có trong store.
            # (Ca DELETE đã `continue` ở trên nên không lọt xuống đây — không
            # nạp vào store thứ người vừa bảo xoá.)
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
                # Giữ NGUYÊN Timestamp review_to_sheet.py đã ghi lúc crawl —
                # đây là "ngày tin vào hệ thống", ghi 1 lần rồi bất biến.
                "timestamp": _cell(row, i_ts),
            }, db_path=db_path)
            writes += 1
            # VIỆC Execute (2026-08-03, Lead) — topic MỚI CHƯA duyệt (gate1=
            # PENDING/REJECT, đa số trường hợp) hiện Execute="" (mới crawl,
            # chưa có gì để chờ); CHỈ topic đã APPROVE SẴN lúc ingest đầu tiên
            # (người duyệt nhanh trước khi lượt ingest kịp chạy) mới vào thẳng
            # "Waiting" — TRƯỚC ĐÂY ép "Waiting" cho MỌI topic mới bất kể gate1,
            # khiến dòng CHƯA duyệt trông như đã xếp hàng.
            ps.write_gate_status(topic_key, gate1=sheet_gate1,
                                 execute=(EXECUTE_WAITING if sheet_gate1 == "APPROVE" else ""),
                                 notes=sheet_notes or None,
                                 output_type=sheet_output_type or None,
                                 db_path=db_path)
            writes += 1
            # Topic MỚI mà đã APPROVE sẵn (vd người duyệt trước lượt ingest
            # đầu tiên) -> vào hàng đợi ngay, không phải chờ 1 lượt đổi Gate 1.
            if sheet_gate1 == "APPROVE":
                qs.enqueue(topic_key, job_type="produce", db_path=db_path)
            continue

        gate = ps.read_gate_status(topic_key, db_path=db_path)

        # KHOÁ KHI ĐANG CHẠY (2026-07-28, quyết định Lead): topic có job
        # 'claimed' -> BỎ QUA mọi thay đổi người vừa gõ (Gate 1, Output Type,
        # Notes). Job đang chạy cứ chạy hết; nhận thêm yêu cầu chồng lên việc
        # đang làm dở chỉ đẻ ra trạng thái mâu thuẫn (vừa Running... vừa
        # Waiting, kết quả của yêu cầu CŨ ghi đè lên yêu cầu MỚI). Người muốn
        # đổi thì đợi xong rồi đổi — lượt render kế tiếp trả ô về giá trị thật
        # nên không mất gì ngoài vài giây.
        if qs.has_running(topic_key, db_path=db_path):
            continue

        updates: dict = {}
        prev_gate1 = gate.get("gate1", "PENDING")
        if sheet_gate1 != prev_gate1:
            updates["gate1"] = sheet_gate1
        if sheet_notes != gate.get("notes", ""):
            updates["notes"] = sheet_notes
        if sheet_output_type != (gate.get("output_type") or []):
            updates["output_type"] = sheet_output_type

        # ENQUEUE = Gate 1 CHUYỂN sang APPROVE (chuyển tiếp, không phải "đang
        # ở trạng thái APPROVE") — nếu đọc theo trạng thái, mỗi vòng poll sẽ
        # enqueue lại 1 job cho MỌI dòng đã duyệt. Cũng là đường CHẠY LẠI duy
        # nhất sau NEEDS_HUMAN/DONE: bỏ APPROVE rồi APPROVE lại.
        # Execute reset về Waiting CÙNG LÚC để người thấy ngay "đã nhận, đang
        # xếp hàng" thay vì còn treo trạng thái của lượt chạy trước.
        # BUG THẬT (Lead báo 2026-07-28): đổi Output Type trên dòng ĐANG
        # APPROVE thì KHÔNG có chuyển tiếp Gate 1 nào -> không enqueue, Execute
        # đứng nguyên ở DONE/NEEDS_HUMAN, hệ thống im lặng không chạy lại. Mà
        # đổi Output Type CHÍNH LÀ một yêu cầu sản xuất mới ("giờ tôi muốn
        # infographic thay vì article") — phải coi nó là tín hiệu chạy lại
        # ngang hàng với việc bấm APPROVE.
        output_type_changed = "output_type" in updates
        rerun = sheet_gate1 == "APPROVE" and (prev_gate1 != "APPROVE" or output_type_changed)

        # HUỶ YÊU CẦU (2026-07-28): người RÚT lại (APPROVE -> PENDING/REJECT)
        # hoặc ĐỔI Output Type. Cả hai đều làm job đang xếp hàng trở nên vô
        # nghĩa — nó sẽ sinh nội dung theo yêu cầu người vừa bỏ. Huỷ job
        # 'queued'; job 'claimed' cứ chạy hết (xem queue_store.cancel_pending).
        left_approve = prev_gate1 == "APPROVE" and sheet_gate1 != "APPROVE"
        if left_approve or output_type_changed:
            n = qs.cancel_pending(
                topic_key, job_type="produce", db_path=db_path,
                reason=("Gate 1 rút khỏi APPROVE" if left_approve else "Output Type đổi"))
            if n:
                print(f"[sync] Huỷ {n} job chờ của {topic_key[:8]} "
                      f"({'rút duyệt' if left_approve else 'đổi Output Type'}).")
            if left_approve:
                # VIỆC Execute (2026-08-03, Lead) — rút duyệt đưa cờ về "" (mới
                # crawl/chưa duyệt), KHÔNG phải "Waiting" (TRƯỚC ĐÂY dùng
                # Waiting — nhưng "Waiting" giờ nghĩa CHÍNH XÁC là "đã duyệt,
                # đang xếp hàng"; rút duyệt thì không còn gì xếp hàng cả, GIỮ
                # NGUYÊN DONE/NEEDS_HUMAN cũ mới đúng là sai — trạng thái đó
                # nói về lượt chạy của yêu cầu đã bị rút, nên vẫn phải xoá).
                updates["execute"] = ""

        if rerun:
            updates["execute"] = EXECUTE_WAITING
        elif not gate.get("execute") and sheet_gate1 == "APPROVE":
            # Dòng CŨ (trước bản vá VIỆC Execute 2026-08-03) Gate 1 ĐÃ APPROVE
            # nhưng Execute còn rỗng (chưa kịp backfill) -> điền Waiting.
            # Gate 1 CHƯA APPROVE thì Execute rỗng là ĐÚNG mặc định mới, không
            # phải lỗi cần "sửa". KHÔNG enqueue: không có chuyển tiếp nào cả.
            updates["execute"] = EXECUTE_WAITING

        # THỨ TỰ QUAN TRỌNG (bug thật 2026-07-29): enqueue TRƯỚC, ghi
        # gate_status SAU. Bản cũ ghi trước rồi enqueue — nếu enqueue lỗi hoặc
        # tiến trình chết ở giữa (đã xảy ra: worker crash vì thiếu cột
        # request_id), store đã ghi APPROVE nên lần ingest sau KHÔNG còn thấy
        # "chuyển tiếp" nào để bắt -> topic KẸT VĨNH VIỄN ở Waiting, không job.
        # Đảo thứ tự thì ca xấu nhất là có job mà store chưa kịp ghi — lần
        # ingest sau bắt lại transition, `enqueue()` tự dedup nên không nhân đôi.
        if rerun:
            qs.enqueue(topic_key, job_type="produce",
                       request_id=qs.new_request_id(), db_path=db_path)
        if updates:
            ps.write_gate_status(topic_key, db_path=db_path, **updates)
            writes += 1

    # Xoá TỪ DƯỚI LÊN: xoá dòng trên trước sẽ làm mọi chỉ số dưới nó dịch lên
    # 1, các lần xoá sau nhắm sai dòng — lỗi kinh điển khi xoá theo chỉ số.
    for r in sorted(deleted_rows, reverse=True):
        try:
            board.delete_row("CONTEXT", r)
        except AttributeError:
            pass          # fake board trong test không có method này
        except Exception as e:   # noqa: BLE001
            print(f"[sync] Không xoá được dòng {r} trên Sheet ({e!r}) — "
                  f"dữ liệu đã xoá khỏi DB, dòng sẽ biến mất ở lượt render sau.")
    return writes


def reconcile_pending_requests(*, db_path=None) -> int:
    """LƯỚI AN TOÀN: enqueue lại topic ĐÃ DUYỆT mà không có job nào.

    Bắt ca "chuyển tiếp bị mất": store ghi gate1=APPROVE xong thì tiến trình
    chết trước khi enqueue (gặp thật 2026-07-29 — worker crash vì DB thiếu cột).
    Sau đó KHÔNG lần ingest nào cứu được, vì cơ chế enqueue dựa trên CHUYỂN
    TIẾP mà chuyển tiếp đó đã bị tiêu thụ. Topic nằm im ở Waiting mãi mãi.

    Điều kiện enqueue lại — phải đủ CẢ BA, nếu không sẽ dựng lại việc đã xong:
      gate1=APPROVE  +  execute ở trạng thái CHỜ  +  KHÔNG có job queued/claimed.
    Chạy xong thì execute thành DONE/FAILED/NEEDS_HUMAN nên không lặp lại.

    CHỈ đọc/ghi store, KHÔNG gọi Sheets API -> gọi mỗi vòng poll vẫn rẻ."""
    waiting = {"Waiting", "", "RUN"}
    n = 0
    for topic_key in ds.list_topics(layer="gate_status", db_path=db_path):
        gate = ps.read_gate_status(topic_key, db_path=db_path)
        if gate.get("gate1") != "APPROVE":
            continue
        if (gate.get("execute") or "") not in waiting:
            continue
        if qs.find_pending(topic_key, job_type="produce", db_path=db_path):
            continue
        qs.enqueue(topic_key, job_type="produce",
                   request_id=qs.new_request_id(), db_path=db_path)
        print(f"[sync] Khôi phục yêu cầu bị mất cho {topic_key[:8]} "
              f"(đã duyệt nhưng không có job nào).")
        n += 1
    return n


def ingest_content_from_sheet(board: SheetsBoard, *, db_path=None) -> int:
    """Đọc CONTENT hiện tại, ghi version MỚI vào content_status cho các
    (TopicKey, Type) có Duyệt Content/Social Link/Duyệt Public/Posting Status
    đổi so với store. KHÔNG tạo content_output mới (đó là việc pipeline, xem
    Nguyên tắc 1) -- chỉ ghi khi (TopicKey, Type) ĐÃ có content_output.

    VIỆC 2 (2026-08-04) — cột Output là NGOẠI LỆ HYBRID (xem ghi chú cạnh
    _CONTENT_USER_COLS): nếu người sửa tay ô Output trên Sheet khác bản lưu
    content_output.output, ghi version MỚI vào content_output (giữ nguyên mọi
    field khác — status/notes/facts/timestamp/published_at — CHỈ đổi
    "output"). Bỏ qua write-back khi bản lưu > _OUTPUT_PREVIEW ký tự (Sheet
    đang hiện bản CẮT, so sánh sẽ luôn sai) HOẶC khi cell còn mang hậu tố cắt
    _TRUNCATION_SUFFIX (ảnh sót từ 1 lượt render CẮT trước đó — SỰ CỐ THẬT đã
    xảy ra: nâng ngưỡng cắt 1500->5000 rồi sync ngay, ingest chạy TRƯỚC render
    nên đọc phải bản cắt CŨ, ghi đè 17 content_output thật thành bản 1550 ký
    tự — đã phục hồi tay từ version trước, xem _TRUNCATION_SUFFIX)."""
    header, rows = _read_sheet_rows(board, "CONTENT")
    if not header:
        return 0
    i_key = _col_index(header, "TopicKey")
    i_type = _col_index(header, "Type")
    i_output = _col_index(header, "Output")
    i_g2 = _col_index(header, GATE2_COL)
    i_social = _col_index(header, "Social Link")
    i_g3 = _col_index(header, GATE3_COL)
    i_posting = _col_index(header, "Posting Status")

    writes = 0
    for row in rows:
        topic_key, type_display = _cell(row, i_key), _cell(row, i_type)
        if not topic_key or not type_display:
            continue
        # SỬA LỖI THẬT (2026-08-03) — cột Type trên Sheet giờ ghi NHÃN hiển thị
        # (VIỆC 3, vd "Infographic"), KHÔNG còn là content_type thô ("infographic")
        # — phải dịch ngược trước khi tra store, xem docstring raw_content_type().
        type_ = raw_content_type(type_display)
        current_out = ps.read_content_output(topic_key, type_, db_path=db_path)
        if current_out is None:
            continue   # content_output chưa tồn tại -- không có content_status để ingest vào

        store_output = current_out.get("output", "")
        sheet_output = _cell(row, i_output)
        # SỰ CỐ THẬT (2026-08-04, xem docstring _TRUNCATION_SUFFIX) — cell còn
        # mang hậu tố cắt (của NGƯỠNG NÀO cũng vậy, cũ hay mới) -> chắc chắn là
        # ảnh sót của 1 lượt render CẮT, TUYỆT ĐỐI không coi là người sửa tay,
        # bất kể so khớp độ dài với ngưỡng HIỆN TẠI ra sao.
        if len(store_output) <= _OUTPUT_PREVIEW and not sheet_output.endswith(_TRUNCATION_SUFFIX.strip()):
            # `_cell()` LUÔN .strip() (quy ước chung của hàm, mọi cột khác ở
            # đây cũng vậy) -- so với `store_output.strip()`, KHÔNG phải bản
            # thô, để 1 vòng render->ingest KHÔNG người đụng vào không tự sinh
            # "khác nhau" giả chỉ vì khoảng trắng đầu/cuối, rồi ghi version rác
            # mỗi lượt sync.
            if sheet_output != store_output.strip():
                ps.write_content_output(topic_key, type_,
                                        {**current_out, "output": sheet_output}, db_path=db_path)
                writes += 1

        sheet_gate2 = _cell(row, i_g2) or "PENDING"
        sheet_social = _cell(row, i_social)
        sheet_gate3 = _cell(row, i_g3) or "PENDING"
        sheet_posting = _cell(row, i_posting)

        status = ps.read_content_status(topic_key, type_, db_path=db_path)
        prev_gate2 = status.get("gate2", "PENDING")
        updates: dict = {}
        if sheet_gate2 != prev_gate2:
            updates["gate2"] = sheet_gate2
        if sheet_social != status.get("social_link", ""):
            updates["social_link"] = sheet_social
        if sheet_gate3 != status.get("gate3", "PENDING"):
            updates["gate3"] = sheet_gate3
        if sheet_posting != status.get("posting_status", ""):
            updates["posting_status"] = sheet_posting

        # GATE 2 -> hàng đợi (2026-07-28, yêu cầu Lead "Scheduler phải kiểm tra
        # được cả 3 trạng thái"). CÙNG CƠ CHẾ Gate 1: bắt CHUYỂN TIẾP sang
        # APPROVE, không phải trạng thái (đọc trạng thái = enqueue lại mỗi vòng
        # poll). Job `render_assets` -> queue_worker gọi
        # render_production_assets.run() (tự idempotent: bỏ qua dòng đã có
        # AssetPath), mở đường tới Gate 3.
        #
        # GATE 3 CỐ Ý KHÔNG có nhánh nào ở đây: theo quyết định Lead nó VẪN
        # mặc định PENDING chờ hệ thống hoàn thiện — ingest chỉ ĐỌC (dòng trên)
        # để store phản ánh đúng cái người bấm, KHÔNG máy nào ghi Gate 3
        # (INVARIANT cũ, xem docstring content_row()).
        if sheet_gate2 == "APPROVE" and prev_gate2 != "APPROVE":
            qs.enqueue(topic_key, job_type="render_assets",
                       request_id=qs.new_request_id(), db_path=db_path)
        elif prev_gate2 == "APPROVE" and sheet_gate2 != "APPROVE":
            # Rút duyệt Gate 2 -> huỷ job render đang chờ. Quan trọng hơn Gate 1
            # vì render TỐN TIỀN THẬT (ảnh gpt-image-2, hoặc cả lượt dựng video).
            n = qs.cancel_pending(topic_key, job_type="render_assets", db_path=db_path,
                                  reason="Gate 2 rút khỏi APPROVE")
            if n:
                print(f"[sync] Huỷ {n} job render của {topic_key[:8]} (rút duyệt Gate 2).")
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
    bình thường lẫn "phục hồi khi xoá nhầm" (Bước 5.4).

    `rebuild=False` (TASK-032) -- đây LÀ lượt sync tự động (ingest xong render
    ngay), đúng kịch bản có race thật giữa nhiều tiến trình (TASK-029) nên
    PHẢI qua CAS, không được bỏ qua như default của render_context_to_sheet()
    (xem docstring hàm đó). Đường phục hồi Bước 5.4 khi Sheet bị XOÁ vẫn đúng
    dưới CAS -- sheet_row=None luôn để store thắng, không phụ thuộc rebuild."""
    n_ingest_ctx = ingest_context_from_sheet(board, db_path=db_path)
    n_ingest_content = ingest_content_from_sheet(board, db_path=db_path)
    n_render_ctx = render_context_to_sheet(board, db_path=db_path, rebuild=False)
    n_render_content = render_content_to_sheet(board, db_path=db_path)
    return {
        "ingested_context": n_ingest_ctx, "ingested_content": n_ingest_content,
        "rendered_context_rows": n_render_ctx, "rendered_content_rows": n_render_content,
    }
