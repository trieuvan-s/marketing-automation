"""SheetsBoard — Google Sheet làm "bảng điều khiển" cho vòng duyệt của con người.

Một Sheet = control-plane khép kín (Sheets chỉ là UI, thay được):
  • SOURCES  — nguồn crawl, mô hình 3 lớp thu thập: Enable|Publisher|FeedURL|
    Type(rss/html)|Field|Interval|Priority. Type chọn collector (rss=phát hiện
    nhẹ, html=full ngay); Field là gợi ý taxonomy cho cả nguồn.  [đầu vào]
  • SETTINGS — cấu hình "sống" (Key/Value), vd PriorityGroups — đọc LIVE mỗi lần
    chạy để team đổi theo pha thị trường mà KHÔNG cần sửa code/deploy lại.
  • TAXONOMY — Field|Topic|Keywords do user định nghĩa (curation.enrich.classify_field_topic
    đọc bảng này để gắn Field/Topic cho từng bài).
  • CONTEXT  — pipeline ghi title + hook + điểm/nhóm/Field/Topic/độ hot (1 dòng/
    bài, ĐÃ gộp near-duplicate chéo nguồn) để user DUYỆT.  [đầu ra chính]
  • LOG      — nhật ký chạy (INFO/WARN/ERROR).
  • ResearchReview / ContentReview — 2 cổng duyệt (tương thích sheets_gate).
  • README   — hướng dẫn ngắn.

Nguyên tắc adapter: mọi thứ chạm gspread nằm ở lớp SheetsBoard (import hoãn để
môi trường offline/test KHÔNG cần thư viện/khoá). Logic thuần (dựng Source từ
hàng, dựng hàng CONTEXT, đọc SETTINGS/TAXONOMY) tách thành hàm module — test
được, không mạng.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .curation.enrich import TaxonomyRow
from .models import Source, SourceType

# --- HỢP ĐỒNG CỘT từng tab (đổi ở đây = đổi header, giữ 1 nguồn sự thật) ------
# Mô hình 3 lớp thu thập: Type=rss -> RssCollector (phát hiện nhẹ, tầng 1);
# Type=html -> HttpFirstCollector (full ngay). Field = gợi ý taxonomy cho CẢ
# nguồn (kết hợp với <category> RSS + từ khóa TAXONOMY ở classify_field_topic).
SOURCES_HEADER = ["Enable", "Publisher", "FeedURL", "Type", "Field", "Interval", "Priority"]
SETTINGS_HEADER = ["Key", "Value", "Notes"]
TAXONOMY_HEADER = ["Field", "Topic", "Keywords"]
# Use = checkbox người duyệt tự tick (chọn dùng cho sản xuất nội dung), ĐỘC LẬP
# với Status (PENDING/APPROVE/REJECT — quy trình duyệt). Publisher/Field/Topic
# đặt trước Group (bổ sung phân loại chi tiết hơn). Source = url bài đại diện
# (dùng để bỏ trùng across-run theo url); Sources = url các báo KHÁC đưa cùng
# tin (gộp bởi dedup chéo nguồn near-duplicate). timestamp/tickers/Notes giữ ở
# cuối để audit/truy vết.
CONTEXT_HEADER = ["Use", "Score", "Hot%", "Publisher", "Field", "Topic", "Group", "Context",
                  "Hook", "Source", "Sources", "Status", "timestamp", "tickers", "Notes"]
LOG_HEADER = ["timestamp", "level", "message"]
REVIEW_HEADER = ["timestamp", "gate", "label", "payload", "Decision", "Notes"]
README_HEADER = ["Turtle Wealth — Bảng duyệt nội dung (Sheets là UI, thay được)"]

# 8 tab dựng lần đầu (tên : header). Thứ tự = thứ tự tab hiển thị.
TABS: dict[str, list[str]] = {
    "README": README_HEADER,
    "SOURCES": SOURCES_HEADER,
    "SETTINGS": SETTINGS_HEADER,
    "TAXONOMY": TAXONOMY_HEADER,
    "CONTEXT": CONTEXT_HEADER,
    "LOG": LOG_HEADER,
    "ResearchReview": REVIEW_HEADER,
    "ContentReview": REVIEW_HEADER,
}

_README_ROWS = [
    ["1) Khai nguồn ở tab SOURCES: Enable=TRUE, Type=rss (feed) hoặc html (trang mục)."],
    ["2) Chỉnh nhóm ưu tiên ở tab SETTINGS (Key=PriorityGroups) — đọc LIVE mỗi lần chạy."],
    ["3) Chỉnh Field/Topic/từ khóa phân loại ở tab TAXONOMY (đọc LIVE mỗi lần chạy)."],
    ["4) Chạy scripts/review_to_sheet.py — bot phát hiện (RSS)/crawl (HTML) thật, "
     "gộp bài trùng giữa các nguồn, ghi vào CONTEXT (sắp theo Hot% giảm dần)."],
    ["5) Duyệt ở cột Status của CONTEXT: APPROVE / REJECT (mặc định PENDING); tick Use để chọn dùng."],
    ["Cột SOURCES: " + " | ".join(SOURCES_HEADER)],
    ["Cột CONTEXT: " + " | ".join(CONTEXT_HEADER)],
]

_SETTINGS_SEED_ROWS = [
    ["PriorityGroups", "ChinhSach, ViMoVN",
     "Nhóm ưu tiên hiện hành (đọc LIVE mỗi lần chạy) — sửa trực tiếp ở đây, không cần đổi code."],
]

# Seed TAXONOMY khớp curation.enrich.DEFAULT_TAXONOMY (dự phòng khi tab trống).
_TAXONOMY_SEED_ROWS = [
    ["ChinhSach", "TienTe", "lãi suất điều hành, room tín dụng, ngân hàng nhà nước, nhnn, sbv"],
    ["ChinhSach", "PhapLy", "nghị định, nghị quyết, thông tư, luật, quốc hội"],
    ["ViMo", "TrongNuoc", "gdp, lạm phát, cpi, tăng trưởng, xuất khẩu, nhập khẩu, fdi"],
    ["ViMo", "TheGioi", "fed, ecb, phố wall, dow jones, trung quốc, giá dầu"],
    ["DoanhNghiep", "KetQuaKinhDoanh", "lợi nhuận, doanh thu, cổ tức"],
    ["DoanhNghiep", "BatDongSan", "bất động sản, dự án, quy hoạch"],
]

# Giá trị coi là "bật" ở cột Enable/Use (không phân biệt hoa/thường).
_TRUTHY = {"TRUE", "YES", "Y", "1", "X", "✓", "ĐÚNG", "BẬT"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _col_a1(n: int) -> str:
    """Số cột (1-based) -> chữ cái A1 (1->A, 15->O). Tránh phụ thuộc gspread ở lõi."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


# =====================================================================
# Hàm THUẦN (không mạng) — test trực tiếp bằng dữ liệu hàng giả.
# =====================================================================
def engine_for(url: str, type_cell: str) -> str:
    """Quyết engine thu thập cho 1 nguồn (-> Source.fetch_type).

    - Type khai rõ 'rss'/'html' -> dùng luôn (người khai thắng).
    - Không khai -> SUY TỪ URL: đuôi '.rss' hoặc có '/rss' -> rss; còn lại html.
    """
    t = (type_cell or "").strip().lower()
    if t in ("rss", "html"):
        return t
    u = (url or "").strip().lower()
    if u.endswith(".rss") or "/rss" in u:
        return "rss"
    return "html"


def sources_from_rows(rows: list[list[str]]) -> list[Source]:
    """Dựng list[Source] từ hàng tab SOURCES; CHỈ giữ hàng Enable bật.

    HARDENING (đồng bộ schema cũ/mới + né lỗi crawl):
      - Ánh xạ cột KHOAN DUNG theo tên (chấp nhận cả cũ lẫn mới):
        Publisher|Name, FeedURL|URL, Type. Bền với việc đổi thứ tự/đổi tên cột.
      - fetch_type suy bằng engine_for(url, Type) (rss/html) -> collector đúng.
      - BỎ QUA dòng URL không bắt đầu http(s):// (in cảnh báo) -> tránh crawl vào
        giá trị rác (vd dữ liệu lệch cột schema cũ) gây UnsupportedProtocol.
    Thiếu cột Enable -> coi như bật tất cả. Kết quả SẮP theo Priority GIẢM DẦN.
    """
    if not rows:
        return []
    header = [c.strip().lower() for c in rows[0]]

    def col(*names: str) -> int | None:
        for n in names:
            if n in header:
                return header.index(n)
        return None

    i_en = col("enable"); i_pub = col("publisher", "name")
    i_url = col("feedurl", "url"); i_type = col("type"); i_field = col("field")
    i_int = col("interval"); i_pri = col("priority")
    if i_url is None:
        return []

    def cell(row: list[str], i: int | None) -> str:
        return row[i].strip() if i is not None and i < len(row) else ""

    def as_int(s: str) -> int:
        try:
            return int(s)
        except ValueError:
            return 0

    out: list[Source] = []
    for row in rows[1:]:
        if i_en is not None and cell(row, i_en).upper() not in _TRUTHY:
            continue
        url = cell(row, i_url)
        if not url:
            continue
        if not url.lower().startswith(("http://", "https://")):
            print(f"[CẢNH BÁO] SOURCES bỏ dòng URL thiếu scheme http(s):// -> {url!r} "
                  "(sửa/đồng bộ tab SOURCES bằng --sync-sources).")
            continue
        out.append(Source(
            name=cell(row, i_pub) or url,
            url=url,
            source_type=SourceType.NEWS,
            fetch_type=engine_for(url, cell(row, i_type)),
            field_hint=cell(row, i_field),
            interval_minutes=as_int(cell(row, i_int)),
            priority=as_int(cell(row, i_pri)),
        ))
    out.sort(key=lambda s: s.priority, reverse=True)
    return out


def taxonomy_from_rows(rows: list[list[str]]) -> list[TaxonomyRow]:
    """Dựng list[TaxonomyRow] từ hàng tab TAXONOMY (Field|Topic|Keywords, mỗi
    Keywords cách nhau dấu phẩy). Hàng thiếu Field -> bỏ."""
    if not rows:
        return []
    header = [c.strip().lower() for c in rows[0]]
    if "field" not in header:
        return []
    i_field = header.index("field")
    i_topic = header.index("topic") if "topic" in header else None
    i_kw = header.index("keywords") if "keywords" in header else None

    def cell(row: list[str], i: int | None) -> str:
        return row[i].strip() if i is not None and i < len(row) else ""

    out: list[TaxonomyRow] = []
    for row in rows[1:]:
        f = cell(row, i_field)
        if not f:
            continue
        kws = [k.strip().lower() for k in cell(row, i_kw).split(",") if k.strip()]
        out.append(TaxonomyRow(field=f, topic=cell(row, i_topic), keywords=kws))
    return out


def context_row(*, title: str, hook_line: str, source_url: str, score: int, hot_pct: float,
                publisher: str = "", field: str = "", topic: str = "", group: str = "",
                other_sources: list[str] | None = None, tickers: list[str] | None = None,
                ts: str | None = None) -> list[str]:
    """Một hàng CONTEXT ĐÚNG thứ tự CONTEXT_HEADER.

    Use mặc định FALSE (người duyệt tự tick), Status mặc định PENDING. Điểm
    (score) và độ hot (hot_pct) do curation/enrich.py tính (marketing_score,
    hotness_pct); field/topic từ classify_field_topic — hàm này CHỈ xếp giá
    trị đúng cột, không tự chấm điểm/phân loại. `other_sources` = url các báo
    KHÁC đưa cùng tin (dedup chéo nguồn near-duplicate, xem review_to_sheet.py).
    """
    return [
        "FALSE",                        # Use
        str(score),                      # Score
        f"{hot_pct:.1f}",                # Hot%
        publisher,                        # Publisher
        field,                             # Field
        topic,                              # Topic
        group,                               # Group
        title,                                # Context
        hook_line,                             # Hook
        source_url,                             # Source (url bài đại diện)
        ", ".join(other_sources or []),          # Sources (url báo khác đưa cùng tin)
        "PENDING",                                # Status
        ts or _now_iso(),                          # timestamp
        ", ".join(tickers or []),                   # tickers
        "",                                           # Notes
    ]


def settings_from_rows(rows: list[list[str]]) -> dict[str, str]:
    """Dựng dict Key->Value từ hàng tab SETTINGS. Ánh xạ theo TÊN header."""
    if not rows:
        return {}
    header = [c.strip().lower() for c in rows[0]]
    if "key" not in header or "value" not in header:
        return {}
    ik, iv = header.index("key"), header.index("value")
    out: dict[str, str] = {}
    for row in rows[1:]:
        if ik < len(row) and row[ik].strip():
            out[row[ik].strip()] = row[iv].strip() if iv < len(row) and row[iv] else ""
    return out


def priority_groups_from_rows(rows: list[list[str]], *,
                              default: list[str] | None = None) -> list[str]:
    """Đọc Key=PriorityGroups (giá trị dạng 'A, B, C') từ hàng tab SETTINGS.
    Thiếu khóa/tab rỗng -> `default`."""
    raw = settings_from_rows(rows).get("PriorityGroups", "")
    groups = [g.strip() for g in raw.split(",") if g.strip()]
    return groups or list(default or [])


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

# Freeze cột đầu cho tiện cuộn ngang (CONTEXT: cột đầu = Use, dễ tick/thấy khi
# cuộn sang các cột nội dung dài hơn).
_FREEZE_FIRST_COL = {"CONTEXT", "LOG", "ResearchReview", "ContentReview"}

# Bề rộng cột (px) theo TÊN header (chữ thường). Cột dài rộng, score/status hẹp.
_COL_WIDTH = {
    "timestamp": 155, "title": 360, "hook": 320, "url": 260, "score": 70,
    "tickers": 150, "decision": 110, "notes": 220, "level": 80, "message": 440,
    "gate": 110, "label": 170, "payload": 380, "enable": 80, "key": 120,
    "name": 210, "type": 90, "status": 110, "context": 380, "output": 380,
    "prompt": 380, "template": 380,
    "use": 60, "hot%": 80, "group": 140, "source": 260, "value": 260,
    "publisher": 170, "field": 110, "topic": 130, "sources": 260, "feedurl": 260,
    "interval": 80, "priority": 80, "keywords": 380,
}
_COL_WIDTH_DEFAULT = 140
# Cột nội dung dài -> wrap text.
_WRAP_COLS = {"title", "hook", "notes", "message", "payload", "context",
              "output", "prompt", "template", "label", "keywords", "sources"}


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
    if "use" in low:  # CONTEXT.Use -> checkbox (người duyệt tự tick, độc lập Status)
        c = low.index("use")
        out.append(_set_validation(sid, 1, fmt_rows, c,
                                   {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}))
    if t.name == "CONTEXT" and "status" in low:  # -> dropdown quy trình duyệt
        c = low.index("status")
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
        if "status" in low:
            c = low.index("status")
            out.append(_text_eq_rule(sid, c, 1, fmt_rows, "APPROVE", _C_APPROVE))
            out.append(_text_eq_rule(sid, c, 1, fmt_rows, "PENDING", _C_PENDING))
            out.append(_text_eq_rule(sid, c, 1, fmt_rows, "REJECT", _C_REJECT))
        if "score" in low:
            c = low.index("score")
            out.append(_score_scale_rule(sid, c, 1, fmt_rows))
        if "hot%" in low:  # thang màu độ hot, cùng kiểu gradient với score
            c = low.index("hot%")
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
        """Tạo đủ 8 tab + hàng header nếu chưa có. Trả về tên các tab vừa tạo."""
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
            if name == "SETTINGS" and len(ws.get_all_values()) <= 1:
                ws.append_rows(_SETTINGS_SEED_ROWS, value_input_option="RAW")
            if name == "TAXONOMY" and len(ws.get_all_values()) <= 1:
                ws.append_rows(_TAXONOMY_SEED_ROWS, value_input_option="RAW")
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

    def sync_sources_from_settings(self, settings) -> int:
        """Ghi ĐÈ tab SOURCES bằng nguồn enabled trong settings.yaml theo ĐÚNG
        schema mới (Enable|Publisher|FeedURL|Type|Field|Interval|Priority), XOÁ
        sạch dòng cũ/URL rỗng. Đồng bộ SHEET với config sau khi verify collectors.
        Trả về số nguồn đã ghi. KHÔNG đụng các tab khác."""
        from .factory import build_sources  # lazy: tránh phụ thuộc vòng lúc import

        sources = build_sources(settings)
        rows: list[list[str]] = [SOURCES_HEADER]
        for s in sources:
            rows.append([
                "TRUE", s.name, s.url, s.fetch_type, s.field_hint,
                str(s.interval_minutes or ""), str(s.priority or ""),
            ])
        ws = self._tab("SOURCES")
        ws.clear()                                   # xoá dòng cũ (schema cũ/URL rỗng)
        ws.update("A1", rows, value_input_option="USER_ENTERED")  # TRUE -> checkbox
        return len(sources)

    def read_taxonomy(self, *, default: list[TaxonomyRow] | None = None) -> list[TaxonomyRow]:
        """Đọc LIVE tab TAXONOMY (Field|Topic|Keywords) — gọi lại MỖI LẦN chạy để
        team đổi phân loại không cần sửa code/deploy lại. Rỗng/thiếu tab -> `default`."""
        try:
            rows = self._tab("TAXONOMY").get_all_values()
        except Exception:  # pragma: no cover - tab chưa tồn tại
            return list(default or [])
        return taxonomy_from_rows(rows) or list(default or [])

    def write_context(self, *, title: str, hook_line: str, url: str, score: int,
                      hot_pct: float = 0.0, publisher: str = "", field: str = "",
                      topic: str = "", group: str = "", other_sources: list[str] | None = None,
                      tickers: list[str] | None = None) -> bool:
        """Ghi 1 dòng chờ duyệt (PENDING, Use=FALSE) vào tab CONTEXT.

        BỎ TRÙNG theo url (cột Source): nếu url đã có ở tab CONTEXT thì KHÔNG
        ghi lại (idempotent across-run). Trả về True nếu đã ghi, False nếu bỏ
        qua vì trùng. Near-duplicate theo TIÊU ĐỀ (nhiều nguồn cùng đưa 1 tin,
        gộp vào cột Sources) không kiểm ở đây — gọi curation.enrich.is_near_duplicate
        với context_titles() TRƯỚC khi gọi hàm này (tránh gọi mạng thừa khi đã
        biết sẽ bỏ qua).
        """
        ws = self._tab("CONTEXT")
        if url and url.strip() in self._context_urls(ws):
            return False
        ws.append_row(
            context_row(title=title, hook_line=hook_line, source_url=url, score=score,
                       hot_pct=hot_pct, publisher=publisher, field=field, topic=topic,
                       group=group, other_sources=other_sources, tickers=tickers),
            value_input_option="RAW",
        )
        return True

    def replace_context(self, rows: list[list[str]]) -> int:
        """UPSERT tab CONTEXT: XÓA vùng dữ liệu (giữ header hàng 1) rồi ghi lại
        `rows`. Mỗi lần chạy CONTEXT phản ánh ĐÚNG kết quả lần đó — hết cảnh trộn
        dòng cũ (thiếu Publisher/Field/Topic) với dòng mới do append. `rows` phải
        ĐÚNG thứ tự CONTEXT_HEADER (dùng context_row). Trả số dòng đã ghi."""
        ws = self._tab("CONTEXT")
        n_existing = len(ws.get_all_values())
        if n_existing > 1:                     # có dữ liệu cũ dưới header -> xóa
            end = f"{_col_a1(len(CONTEXT_HEADER))}{n_existing}"
            ws.batch_clear([f"A2:{end}"])
        if rows:
            ws.update("A2", rows, value_input_option="USER_ENTERED")
        return len(rows)

    def _context_urls(self, ws) -> set[str]:
        """Tập url đã có ở tab CONTEXT (ánh xạ theo tên cột 'source')."""
        rows = ws.get_all_values()
        if not rows:
            return set()
        header = [c.strip().lower() for c in rows[0]]
        if "source" not in header:
            return set()
        i = header.index("source")
        return {r[i].strip() for r in rows[1:] if i < len(r) and r[i].strip()}

    def context_titles(self) -> list[str]:
        """Danh sách tiêu đề (cột Context) đã có trong CONTEXT — dùng để lọc
        near-duplicate (curation.enrich.is_near_duplicate) TRƯỚC khi write_context."""
        try:
            rows = self._tab("CONTEXT").get_all_values()
        except Exception:  # pragma: no cover - tab chưa tồn tại
            return []
        if not rows:
            return []
        header = [c.strip().lower() for c in rows[0]]
        if "context" not in header:
            return []
        i = header.index("context")
        return [r[i].strip() for r in rows[1:] if i < len(r) and r[i].strip()]

    def read_priority_groups(self, *, default: list[str] | None = None) -> list[str]:
        """Đọc LIVE tab SETTINGS (Key=PriorityGroups) — gọi lại MỖI LẦN chạy để
        team đổi theo pha thị trường không cần sửa code/deploy lại. Thiếu
        tab/khóa -> `default`."""
        try:
            rows = self._tab("SETTINGS").get_all_values()
        except Exception:  # pragma: no cover - tab chưa tồn tại
            return list(default or [])
        return priority_groups_from_rows(rows, default=default)

    def sort_context_by_hot(self) -> None:
        """Sắp lại toàn bộ hàng dữ liệu CONTEXT theo Hot% GIẢM DẦN. No-op nếu
        tab chưa có cột Hot% hoặc chưa có dữ liệu."""
        import gspread

        ws = self._tab("CONTEXT")
        header = ws.row_values(1)
        low = [h.strip().lower() for h in header]
        if "hot%" not in low:
            return
        n_rows = len(ws.get_all_values())
        if n_rows <= 2:   # 0-1 hàng dữ liệu, không cần sắp
            return
        col = low.index("hot%") + 1   # gspread sort dùng chỉ số cột 1-based
        end_a1 = gspread.utils.rowcol_to_a1(n_rows, len(header))
        ws.sort((col, "des"), range=f"A2:{end_a1}")

    def log(self, level: str, message: str) -> None:
        """Ghi 1 dòng nhật ký vào tab LOG."""
        self._tab("LOG").append_row(
            [_now_iso(), level.upper(), message], value_input_option="RAW"
        )
