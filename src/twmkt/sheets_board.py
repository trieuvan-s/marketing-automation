"""SheetsBoard — Google Sheet làm "bảng điều khiển" cho vòng duyệt của con người.

Một Sheet = control-plane khép kín (Sheets chỉ là UI, thay được):
  • SOURCES  — người dùng khai/nguồn crawl (cột Enable để bật/tắt).  [đầu vào]
  • CONTEXT  — pipeline ghi title + hook (1 dòng/bài) để user DUYỆT.  [đầu ra chính]
  • LOG      — nhật ký chạy (INFO/WARN/ERROR).
  • ResearchReview / ContentReview — 2 cổng duyệt (tương thích sheets_gate).
  • README   — hướng dẫn ngắn.

Nguyên tắc adapter: mọi thứ chạm gspread nằm ở lớp SheetsBoard (import hoãn để
môi trường offline/test KHÔNG cần thư viện/khoá). Logic thuần (dựng Source từ
hàng, dựng hàng CONTEXT, chấm điểm) tách thành hàm module — test được, không mạng.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .models import Source, SourceType

# --- HỢP ĐỒNG CỘT từng tab (đổi ở đây = đổi header, giữ 1 nguồn sự thật) ------
SOURCES_HEADER = ["Enable", "key", "name", "url", "type"]
CONTEXT_HEADER = ["timestamp", "title", "hook", "url", "score", "tickers", "Decision", "Notes"]
LOG_HEADER = ["timestamp", "level", "message"]
REVIEW_HEADER = ["timestamp", "gate", "label", "payload", "Decision", "Notes"]
README_HEADER = ["Turtle Wealth — Bảng duyệt nội dung (Sheets là UI, thay được)"]

# 6 tab dựng lần đầu (tên : header). Thứ tự = thứ tự tab hiển thị.
TABS: dict[str, list[str]] = {
    "README": README_HEADER,
    "SOURCES": SOURCES_HEADER,
    "CONTEXT": CONTEXT_HEADER,
    "LOG": LOG_HEADER,
    "ResearchReview": REVIEW_HEADER,
    "ContentReview": REVIEW_HEADER,
}

_README_ROWS = [
    ["1) Khai nguồn ở tab SOURCES (đặt Enable = TRUE để bật)."],
    ["2) Chạy scripts/review_to_sheet.py — bot crawl thật, ghi title + hook vào CONTEXT."],
    ["3) Duyệt ở cột Decision của CONTEXT: APPROVE / REJECT / REVISE (mặc định PENDING)."],
    ["Cột CONTEXT: " + " | ".join(CONTEXT_HEADER)],
]

# Giá trị coi là "bật" ở cột Enable (không phân biệt hoa/thường).
_TRUTHY = {"TRUE", "YES", "Y", "1", "X", "✓", "ĐÚNG", "BẬT"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _source_type(value: str) -> SourceType:
    try:
        return SourceType((value or "news").strip().lower())
    except ValueError:
        return SourceType.OTHER


# =====================================================================
# Hàm THUẦN (không mạng) — test trực tiếp bằng dữ liệu hàng giả.
# =====================================================================
def sources_from_rows(rows: list[list[str]]) -> list[Source]:
    """Dựng list[Source] từ các hàng tab SOURCES; CHỈ giữ hàng Enable bật.

    Ánh xạ cột theo TÊN header (bền với việc đổi thứ tự cột). Thiếu cột Enable ->
    coi như bật tất cả. Hàng không có url -> bỏ.
    """
    if not rows:
        return []
    header = [c.strip().lower() for c in rows[0]]

    def col(name: str) -> int | None:
        return header.index(name) if name in header else None

    i_en, i_name, i_url, i_type = col("enable"), col("name"), col("url"), col("type")
    if i_url is None:
        return []

    def cell(row: list[str], i: int | None) -> str:
        return row[i].strip() if i is not None and i < len(row) else ""

    out: list[Source] = []
    for row in rows[1:]:
        if i_en is not None and cell(row, i_en).upper() not in _TRUTHY:
            continue
        url = cell(row, i_url)
        if not url:
            continue
        out.append(Source(
            name=cell(row, i_name) or url,
            url=url,
            source_type=_source_type(cell(row, i_type)),
        ))
    return out


def context_row(title: str, hook_line: str, url: str, score: int,
                tickers: list[str] | None = None, *, ts: str | None = None) -> list[str]:
    """Một hàng CONTEXT ĐÚNG thứ tự CONTEXT_HEADER; Decision mặc định PENDING."""
    return [
        ts or _now_iso(),
        title,
        hook_line,
        url,
        str(score),
        ", ".join(tickers or []),
        "PENDING",
        "",
    ]


def score_item(tickers: list[str] | None, macro_hits: int) -> int:
    """Điểm ưu tiên duyệt (tất định, $0): mỗi mã +2, mỗi từ khóa vĩ mô +1."""
    return 2 * len(set(tickers or [])) + int(macro_hits)


# =====================================================================
# UI / định dạng bảng — dựng request batchUpdate THUẦN (test không mạng).
# Toàn bộ chỉ đổi ĐỊNH DẠNG, KHÔNG đổi dữ liệu. Idempotent: banding &
# conditional format được XÓA cái cũ trước khi thêm lại (dựa metadata).
# =====================================================================
# Bảng màu (tông xanh Turtle Wealth), lưu hex -> chuyển sang {red,green,blue} 0..1.
_C_HEADER_BG = "#0F5132"   # xanh đậm header
_C_HEADER_FG = "#FFFFFF"
_C_BAND = "#F3F3F3"        # xám nhạt hàng xen kẽ
_C_BORDER = "#D9D9D9"      # xám khung
_C_APPROVE = "#D9EAD3"     # xanh lá nhạt
_C_PENDING = "#FFF2CC"     # vàng nhạt
_C_REJECT = "#F4CCCC"      # đỏ nhạt
_C_SCORE_MIN = "#FFFFFF"
_C_SCORE_MID = "#B6D7A8"
_C_SCORE_MAX = "#38761D"

# Tab có cột đầu là mốc thời gian -> freeze cột đầu cho tiện cuộn ngang.
_FREEZE_FIRST_COL = {"CONTEXT", "LOG", "ResearchReview", "ContentReview"}

# Bề rộng cột (px) theo TÊN header (chữ thường). Cột dài rộng, score/Decision hẹp.
_COL_WIDTH = {
    "timestamp": 155, "title": 360, "hook": 320, "url": 260, "score": 70,
    "tickers": 120, "decision": 110, "notes": 220, "level": 80, "message": 440,
    "gate": 110, "label": 170, "payload": 380, "enable": 80, "key": 120,
    "name": 210, "type": 90, "status": 110, "context": 380, "output": 380,
    "prompt": 380, "template": 380,
}
_COL_WIDTH_DEFAULT = 140
# Cột nội dung dài -> wrap text.
_WRAP_COLS = {"title", "hook", "notes", "message", "payload", "context",
              "output", "prompt", "template", "label"}


def _rgb(hex_str: str) -> dict:
    h = hex_str.lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255,
            "blue": int(h[4:6], 16) / 255}


@dataclass
class TabMeta:
    """Ảnh chụp 1 tab để dựng request (lấy từ metadata + đếm hàng dữ liệu)."""
    name: str
    header: list[str]
    sheet_id: int
    n_rows: int                 # số hàng CÓ dữ liệu (gồm header)
    grid_rows: int = 1000       # rowCount cấp phát (giới hạn range)
    banding_ids: list[int] = field(default_factory=list)
    cond_format_count: int = 0

    @property
    def n_cols(self) -> int:
        return len(self.header)

    @property
    def fmt_rows(self) -> int:
        """Vùng định dạng có đệm để hàng mới thêm vào vẫn đẹp; cắt theo grid."""
        return min(max(self.n_rows + 100, 200), self.grid_rows)


def _grid_range(sid: int, r0: int, r1: int, c0: int, c1: int) -> dict:
    return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
            "startColumnIndex": c0, "endColumnIndex": c1}


def _set_validation(sid: int, r0: int, r1: int, c: int, rule: dict) -> dict:
    return {"setDataValidation": {"range": _grid_range(sid, r0, r1, c, c + 1),
                                  "rule": rule}}


def _one_of_list(values: list[str]) -> dict:
    return {
        "condition": {"type": "ONE_OF_LIST",
                      "values": [{"userEnteredValue": v} for v in values]},
        "showCustomUi": True, "strict": False,   # không phủ nhận giá trị cũ (vd REVISE)
    }


def _text_eq_rule(sid: int, col: int, r0: int, r1: int, text: str, bg: str) -> dict:
    return {"addConditionalFormatRule": {"index": 0, "rule": {
        "ranges": [_grid_range(sid, r0, r1, col, col + 1)],
        "booleanRule": {
            "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": text}]},
            "format": {"backgroundColor": _rgb(bg)},
        }}}}


def _score_scale_rule(sid: int, col: int, r0: int, r1: int) -> dict:
    return {"addConditionalFormatRule": {"index": 0, "rule": {
        "ranges": [_grid_range(sid, r0, r1, col, col + 1)],
        "gradientRule": {
            "minpoint": {"color": _rgb(_C_SCORE_MIN), "type": "MIN"},
            "midpoint": {"color": _rgb(_C_SCORE_MID), "type": "PERCENTILE", "value": "50"},
            "maxpoint": {"color": _rgb(_C_SCORE_MAX), "type": "MAX"},
        }}}}


def build_format_requests(tabs: list[TabMeta]) -> list[dict]:
    """Dựng list request cho spreadsheets().batchUpdate. Hàm THUẦN -> test được."""
    reqs: list[dict] = []
    for t in tabs:
        reqs.extend(_tab_requests(t))
    return reqs


def _tab_requests(t: TabMeta) -> list[dict]:
    sid, ncols = t.sheet_id, t.n_cols
    low = [h.strip().lower() for h in t.header]
    n_rows, fmt_rows = max(t.n_rows, 1), t.fmt_rows
    is_readme = t.name == "README"
    out: list[dict] = []

    # 1) Freeze hàng tiêu đề (+ cột đầu nếu hợp).
    frozen_cols = 1 if t.name in _FREEZE_FIRST_COL else 0
    out.append({"updateSheetProperties": {
        "properties": {"sheetId": sid, "gridProperties": {
            "frozenRowCount": 1, "frozenColumnCount": frozen_cols}},
        "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}})

    # 2) Hàng header cao hơn.
    out.append({"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
        "properties": {"pixelSize": 34}, "fields": "pixelSize"}})

    # 3) Header: đậm, chữ trắng, nền xanh đậm, canh giữa, wrap.
    out.append({"repeatCell": {
        "range": _grid_range(sid, 0, 1, 0, ncols),
        "cell": {"userEnteredFormat": {
            "backgroundColor": _rgb(_C_HEADER_BG),
            "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
            "wrapStrategy": "WRAP",
            "textFormat": {"bold": True, "foregroundColor": _rgb(_C_HEADER_FG)}}},
        "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,"
                  "verticalAlignment,wrapStrategy,textFormat)"}})

    # 4) Kẻ khung quanh + giữa các ô, vùng dữ liệu (header + hàng có dữ liệu).
    border = {"style": "SOLID", "color": _rgb(_C_BORDER)}
    out.append({"updateBorders": {
        "range": _grid_range(sid, 0, n_rows, 0, ncols),
        "top": border, "bottom": border, "left": border, "right": border,
        "innerHorizontal": border, "innerVertical": border}})

    # 5) Banding: xóa cái cũ (idempotent) rồi thêm mới cho hàng dữ liệu.
    for bid in t.banding_ids:
        out.append({"deleteBanding": {"bandedRangeId": bid}})
    if fmt_rows > 1:
        out.append({"addBanding": {"bandedRange": {
            "range": _grid_range(sid, 1, fmt_rows, 0, ncols),
            "rowProperties": {"firstBandColor": _rgb("#FFFFFF"),
                              "secondBandColor": _rgb(_C_BAND)}}}})

    # 6) Bề rộng cột + wrap cột dài.
    for i, colname in enumerate(low):
        width = 720 if is_readme else _COL_WIDTH.get(colname, _COL_WIDTH_DEFAULT)
        out.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS",
                      "startIndex": i, "endIndex": i + 1},
            "properties": {"pixelSize": width}, "fields": "pixelSize"}})
        if is_readme or colname in _WRAP_COLS:
            out.append({"repeatCell": {
                "range": _grid_range(sid, 0, fmt_rows, i, i + 1),
                "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
                "fields": "userEnteredFormat.wrapStrategy"}})

    # 7) Data validation.
    if "enable" in low:  # SOURCES.Enable / PROMPTS.Enable -> checkbox
        c = low.index("enable")
        out.append(_set_validation(sid, 1, fmt_rows, c,
                                   {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}))
    if t.name == "CONTEXT" and "decision" in low:  # -> dropdown
        c = low.index("decision")
        out.append(_set_validation(sid, 1, fmt_rows, c,
                                   _one_of_list(["PENDING", "APPROVE", "REJECT"])))
    if t.name == "CONTENT" and "status" in low:  # -> dropdown (khi có tab CONTENT)
        c = low.index("status")
        out.append(_set_validation(sid, 1, fmt_rows, c,
                                   _one_of_list(["PENDING", "RUNNING", "DONE", "ERROR"])))

    # 8) Conditional formatting cho CONTEXT (xóa rule cũ trước -> idempotent).
    if t.name == "CONTEXT":
        for i in range(t.cond_format_count - 1, -1, -1):
            out.append({"deleteConditionalFormatRule": {"sheetId": sid, "index": i}})
        if "decision" in low:
            c = low.index("decision")
            out.append(_text_eq_rule(sid, c, 1, fmt_rows, "APPROVE", _C_APPROVE))
            out.append(_text_eq_rule(sid, c, 1, fmt_rows, "PENDING", _C_PENDING))
            out.append(_text_eq_rule(sid, c, 1, fmt_rows, "REJECT", _C_REJECT))
        if "score" in low:
            c = low.index("score")
            out.append(_score_scale_rule(sid, c, 1, fmt_rows))

    return out


# =====================================================================
# Adapter Google Sheets (gspread) — import hoãn.
# =====================================================================
class SheetsBoard:
    def __init__(self, *, spreadsheet_id: str, creds_path: str):
        if not spreadsheet_id or not creds_path:
            raise ValueError(
                "Thiếu spreadsheet_id/creds_path — đặt TWMKT_SHEET_ID và "
                "TWMKT_SHEETS_CREDS (xem docs/google_sheets_setup.md)."
            )
        self.spreadsheet_id = spreadsheet_id
        self.creds_path = creds_path
        self._sh = None
        self._ws: dict[str, object] = {}

    # --- kết nối (lazy) --------------------------------------------
    def _spreadsheet(self):
        if self._sh is not None:
            return self._sh
        try:
            import gspread
            from google.oauth2.service_account import Credentials
        except ImportError as e:  # pragma: no cover - phụ thuộc tùy chọn
            raise RuntimeError("Cần: pip install gspread google-auth") from e
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(self.creds_path, scopes=scopes)
        self._sh = gspread.authorize(creds).open_by_key(self.spreadsheet_id)
        return self._sh

    def ensure_tabs(self) -> list[str]:
        """Tạo đủ 6 tab + hàng header nếu chưa có. Trả về tên các tab vừa tạo."""
        import gspread

        sh = self._spreadsheet()
        existing = {w.title for w in sh.worksheets()}
        created: list[str] = []
        for name, header in TABS.items():
            if name in existing:
                ws = sh.worksheet(name)
            else:
                ws = sh.add_worksheet(title=name, rows=1000, cols=max(len(header), 8))
                created.append(name)
            if ws.row_values(1) != header:
                ws.update("A1", [header])
            if name == "README" and len(ws.get_all_values()) <= 1:
                ws.append_rows(_README_ROWS, value_input_option="RAW")
            self._ws[name] = ws
        # gspread tạo sẵn "Sheet1" khi tạo spreadsheet — dọn cho gọn (nếu có).
        if "Sheet1" in existing and len(sh.worksheets()) > len(TABS):
            try:
                sh.del_worksheet(sh.worksheet("Sheet1"))
            except gspread.GSpreadException:  # pragma: no cover
                pass
        # UI: định dạng bảng (idempotent, chỉ đổi format). Lỗi cosmetic KHÔNG
        # được chặn luồng dữ liệu -> bắt và cảnh báo.
        try:
            self.format_board()
        except Exception as e:  # pragma: no cover - cosmetic, không ảnh hưởng dữ liệu
            print(f"[CẢNH BÁO] format_board lỗi (bỏ qua): {e}")
        return created

    def format_board(self) -> int:
        """Áp toàn bộ định dạng cho 6 tab qua 1 lần batchUpdate. Idempotent, KHÔNG
        đổi dữ liệu. Trả về số request đã gửi (0 nếu không có tab nào)."""
        sh = self._spreadsheet()
        meta = sh.fetch_sheet_metadata(params={
            "fields": "sheets(properties(sheetId,title,gridProperties(rowCount)),"
                      "bandedRanges(bandedRangeId),conditionalFormats)"
        })
        by_title = {s["properties"]["title"]: s for s in meta.get("sheets", [])}

        tabs: list[TabMeta] = []
        for name, header in TABS.items():
            s = by_title.get(name)
            if not s:
                continue
            props = s["properties"]
            grid_rows = props.get("gridProperties", {}).get("rowCount", 1000)
            try:
                n_rows = len(self._tab(name).get_all_values()) or 1
            except Exception:  # pragma: no cover - tab đọc lỗi -> chỉ format header
                n_rows = 1
            banding_ids = [b["bandedRangeId"] for b in s.get("bandedRanges", [])
                           if b.get("bandedRangeId") is not None]
            cond_count = len(s.get("conditionalFormats", []))
            tabs.append(TabMeta(name=name, header=header, sheet_id=props["sheetId"],
                                n_rows=n_rows, grid_rows=grid_rows,
                                banding_ids=banding_ids, cond_format_count=cond_count))

        requests = build_format_requests(tabs)
        if requests:
            sh.batch_update({"requests": requests})
        return len(requests)

    def _tab(self, name: str):
        if name not in self._ws:
            self._ws[name] = self._spreadsheet().worksheet(name)
        return self._ws[name]

    # --- API dùng bởi review_to_sheet.py ---------------------------
    def read_sources(self) -> list[Source]:
        """Đọc tab SOURCES -> list[Source] (chỉ hàng Enable bật). Rỗng nếu chưa khai."""
        try:
            rows = self._tab("SOURCES").get_all_values()
        except Exception:  # pragma: no cover - tab chưa tồn tại
            return []
        return sources_from_rows(rows)

    def write_context(self, *, title: str, hook_line: str, url: str, score: int,
                      tickers: list[str] | None = None) -> bool:
        """Ghi 1 dòng chờ duyệt (PENDING) vào tab CONTEXT.

        BỎ TRÙNG theo url: nếu url đã có ở tab CONTEXT thì KHÔNG ghi lại (idempotent
        across-run). Trả về True nếu đã ghi, False nếu bỏ qua vì trùng.
        """
        ws = self._tab("CONTEXT")
        if url and url.strip() in self._context_urls(ws):
            return False
        ws.append_row(
            context_row(title, hook_line, url, score, tickers),
            value_input_option="RAW",
        )
        return True

    def _context_urls(self, ws) -> set[str]:
        """Tập url đã có ở tab CONTEXT (ánh xạ theo tên cột 'url')."""
        rows = ws.get_all_values()
        if not rows:
            return set()
        header = [c.strip().lower() for c in rows[0]]
        if "url" not in header:
            return set()
        i = header.index("url")
        return {r[i].strip() for r in rows[1:] if i < len(r) and r[i].strip()}

    def log(self, level: str, message: str) -> None:
        """Ghi 1 dòng nhật ký vào tab LOG."""
        self._tab("LOG").append_row(
            [_now_iso(), level.upper(), message], value_input_option="RAW"
        )
