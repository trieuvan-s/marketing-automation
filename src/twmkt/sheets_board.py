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
        return created

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
                      tickers: list[str] | None = None) -> None:
        """Ghi 1 dòng chờ duyệt (PENDING) vào tab CONTEXT."""
        self._tab("CONTEXT").append_row(
            context_row(title, hook_line, url, score, tickers),
            value_input_option="RAW",
        )

    def log(self, level: str, message: str) -> None:
        """Ghi 1 dòng nhật ký vào tab LOG."""
        self._tab("LOG").append_row(
            [_now_iso(), level.upper(), message], value_input_option="RAW"
        )
