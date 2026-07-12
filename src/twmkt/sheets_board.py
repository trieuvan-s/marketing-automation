"""SheetsBoard — Google Sheet làm "bảng điều khiển" cho vòng duyệt của con người.

Một Sheet = control-plane khép kín (Sheets chỉ là UI, thay được):
  • SOURCES  — nguồn crawl, mô hình 3 lớp thu thập: Enable|Publisher|FeedURL|
    Type(rss/html)|Field|Interval|Priority. Type chọn collector (rss=phát hiện
    nhẹ, html=full ngay); Field là gợi ý taxonomy cho cả nguồn.  [đầu vào]
  • SETTINGS — cấu hình "sống" (Key/Value), vd PriorityGroups — đọc LIVE mỗi lần
    chạy để team đổi theo pha thị trường mà KHÔNG cần sửa code/deploy lại.
  • TAXONOMY — Field|Topic|Keywords do user định nghĩa (bảng tra cứu tay, tuỳ chọn).
  • CONTEXT  — pipeline ghi title + hook + Score/Hot%/Group/Topic (1 dòng/bài, ĐÃ
    gộp sự kiện chéo nguồn — giữ báo Priority cao) để user DUYỆT.  [đầu ra chính]
  • LOG      — nhật ký chạy (INFO/WARN/ERROR).
  • ResearchReview / ContentReview — 2 cổng duyệt (tương thích sheets_gate).
  • README   — hướng dẫn ngắn.

Nguyên tắc adapter: mọi thứ chạm gspread nằm ở lớp SheetsBoard (import hoãn để
môi trường offline/test KHÔNG cần thư viện/khoá). Logic thuần (dựng Source từ
hàng, dựng hàng CONTEXT, đọc SETTINGS/TAXONOMY) tách thành hàm module — test
được, không mạng.

RETRY QUOTA (429): mọi Spreadsheet/Worksheet trả về từ _spreadsheet()/_tab()
đều được bọc bởi _RetryingProxy — MỌI method gọi qua đó (append_row, update,
get_all_values, batch_update, v.v.) tự động retry khi Google Sheets API trả
429 (quota), không cần sửa từng điểm gọi riêng lẻ. Xem call_with_retry().
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .models import Source, SourceType

# =====================================================================
# Retry quota 429 — bọc MỌI lệnh gọi gspread (không riêng ApprovalGate).
# =====================================================================
_RETRY_MAX_ATTEMPTS = 5
_RETRY_BACKOFF_BASE_S = 2.0   # lần 1->2s, 2->4s, 3->8s, 4->16s (+ jitter)


def _is_quota_429(exc: Exception) -> bool:
    """True nếu lỗi là quota Google Sheets API (HTTP 429 / RESOURCE_EXHAUSTED)."""
    code = getattr(exc, "code", None)
    if code == 429:
        return True
    resp = getattr(exc, "response", None)
    if resp is not None and getattr(resp, "status_code", None) == 429:
        return True
    error = getattr(exc, "error", None) or {}
    return str(error.get("status", "")) == "RESOURCE_EXHAUSTED"


def _retry_after_s(exc: Exception) -> float | None:
    """Đọc header Retry-After (giây) từ response lỗi; None nếu không có/không hợp lệ."""
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None) if resp is not None else None
    if not headers:
        return None
    val = headers.get("Retry-After")
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _backoff_delay_s(attempt: int, retry_after: float | None) -> float:
    """Retry-After (nếu có) ưu tiên; không có -> backoff mũ 2,4,8,16s + jitter
    (thêm tới 25% ngẫu nhiên, tránh nhiều tiến trình cùng thử lại đúng 1 mốc)."""
    if retry_after is not None and retry_after > 0:
        return retry_after
    base = _RETRY_BACKOFF_BASE_S * (2 ** (attempt - 1))
    return base + random.uniform(0, base * 0.25)


def call_with_retry(func, *args, max_attempts: int = _RETRY_MAX_ATTEMPTS,
                    sleep=time.sleep, **kwargs):
    """Gọi func(*args, **kwargs); lỗi quota 429 (gspread APIError) -> chờ theo
    Retry-After hoặc backoff mũ + jitter, tối đa `max_attempts` lần rồi mới
    RAISE lỗi thật. Lỗi KHÁC 429 -> raise ngay (không nuốt/không retry).
    `sleep` cho phép tiêm hàm giả lập trong test (không chờ thật, $0 thời gian)."""
    import gspread

    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func(*args, **kwargs)
        except gspread.exceptions.APIError as e:
            if not _is_quota_429(e):
                raise
            last_exc = e
            if attempt == max_attempts:
                break
            delay = _backoff_delay_s(attempt, _retry_after_s(e))
            print(f"[CẢNH BÁO] Google Sheets quota (429) — chờ {delay:.1f}s rồi thử lại "
                  f"(lần {attempt}/{max_attempts})...")
            sleep(delay)
    raise last_exc


class _RetryingProxy:
    """Bọc 1 object gspread (Spreadsheet/Worksheet) — MỌI method gọi qua đây tự
    động retry khi gặp lỗi quota 429 (call_with_retry). Trong suốt với code gọi
    (ws.append_row(...) y hệt, không cần sửa từng điểm gọi) — đáp ứng "retry cho
    MỌI lệnh gọi gspread" mà không phải sửa từng dòng gọi API riêng lẻ."""

    def __init__(self, target, *, max_attempts: int = _RETRY_MAX_ATTEMPTS, sleep=time.sleep):
        object.__setattr__(self, "_rp_target", target)
        object.__setattr__(self, "_rp_max_attempts", max_attempts)
        object.__setattr__(self, "_rp_sleep", sleep)   # tiêm được trong test -> $0 thời gian

    def __getattr__(self, name):
        attr = getattr(object.__getattribute__(self, "_rp_target"), name)
        if not callable(attr):
            return attr
        max_attempts = object.__getattribute__(self, "_rp_max_attempts")
        sleep = object.__getattribute__(self, "_rp_sleep")

        def _wrapped(*args, **kwargs):
            return call_with_retry(attr, *args, max_attempts=max_attempts, sleep=sleep, **kwargs)
        return _wrapped


@dataclass
class TaxonomyRow:
    """1 hàng tab TAXONOMY (Field|Topic|Keywords). Giữ ở đây (không phụ thuộc
    enrich) vì chỉ là hợp đồng cột của Sheet — team có thể dùng để tra cứu tay."""
    field: str
    topic: str = ""
    keywords: list[str] = field(default_factory=list)

# --- HỢP ĐỒNG CỘT từng tab (đổi ở đây = đổi header, giữ 1 nguồn sự thật) ------
# Mô hình 3 lớp thu thập: Type=rss -> RssCollector (phát hiện nhẹ, tầng 1);
# Type=html -> HttpFirstCollector (full ngay). Field = gợi ý taxonomy cho CẢ
# nguồn (kết hợp với <category> RSS + từ khóa TAXONOMY ở classify_field_topic).
SOURCES_HEADER = ["Enable", "Publisher", "FeedURL", "Type", "Field", "Interval", "Priority"]
SETTINGS_HEADER = ["Key", "Value", "Notes"]
TAXONOMY_HEADER = ["Field", "Topic", "Keywords"]
# PROMPTS — BẢNG KÍCH HOẠT phiên bản prompt (KHÔNG chứa nội dung prompt): agent
# đọc dòng Enable=TRUE của Name mình -> nạp prompts/<Name>.<Version>.md (repo,
# version-controlled). Thiếu dòng/file -> agent dùng default nội bộ trong code.
PROMPTS_HEADER = ["Name", "Version", "Enable"]
# CONTEXT — Timestamp ĐẦU TIÊN (dễ nhìn khi lướt dọc). KHÔNG còn cột Use (trùng
# chức năng Status, đã xoá). Source = url bài đại diện (dùng để UPSERT theo url
# — url đã có thì BỎ QUA, giữ nguyên dòng cũ; xem SheetsBoard.upsert_context);
# "(+N báo)" các báo khác đưa cùng tin xuống dòng cùng ô Source. Execute NGAY
# SAU Status = cờ thực thi sản xuất: rỗng (mới) -> RUN (tự đặt khi Status=APPROVE,
# xem sync_approve_execute_flags) -> DONE (đã sinh xong CONTENT, idempotent —
# produce_from_sheet bỏ qua dòng đã DONE). tickers/Notes giữ cuối để audit.
# PHASE 4.9 — cầu nối writer retry: Execute còn nhận 2 giá trị nữa, map từ
# agents.writer.WriterOutcome của bài ARTICLE (xem scripts/produce_from_sheet.run):
#   FAILED       lỗi TẠM THỜI (hạ tầng gọi LLM) — produce_from_sheet TỰ ĐỘNG coi
#                như RUN ở lượt sau (tái chạy được, KHÔNG cần người reset tay).
#   NEEDS_HUMAN  guardrail reject VĨNH VIỄN — produce_from_sheet BỎ QUA dòng này
#                ở các lượt sau cho tới khi người CHỦ ĐỘNG đổi Execute về RUN
#                (móc cho nút MANUAL của Phase 5, chưa có UI riêng ở phase này).
# LỚP 5 (Phase 1) — TopicKey CUỐI CÙNG (append, giống cách Execute/Approve(gate 2)
# đã thêm ở các phase trước): danh tính BỀN của chủ đề (sha256 URL chuẩn hoá,
# xem curation.keys.compute_topic_key) — KHÔNG đổi khi Sheet insert/delete/sort/
# merge (khác Context text, vốn có thể bị Sheets API mergeCells XOÁ THẬT ở phía
# CONTENT — xem curation/keys.py docstring). Đặt CUỐI (không chen giữa) để
# KHÔNG lệch số cột của MỌI code/test hiện có đang truy cập theo VỊ TRÍ (vd
# `row[3]` = Status ở CONTENT) — bài học từ chính lần soát Phase 1 này. CONTENT
# tra cứu chủ đề qua cột này TỪ PHASE 2 trở đi (Phase 1 chỉ thêm cột + backfill).
CONTEXT_HEADER = ["Timestamp", "Hot%", "Score", "Group", "Topic", "Context", "Hook",
                  "Source", "Status", "Execute", "tickers", "Notes", "TopicKey"]
# "engine" TẠM (haiku|sonnet|mock) — đối chiếu model NÀO thực sự chạy cho mỗi
# dòng log, xem factory.model_engine_label(). Rỗng nếu dòng log không gắn LLM.
LOG_HEADER = ["timestamp", "level", "message", "engine"]
README_HEADER = ["Turtle Wealth — Bảng duyệt nội dung (Sheets là UI, thay được)"]
# CONTENT — SẢN PHẨM sinh SAU cổng 1 (giai đoạn Production): 1 dòng/(bài × định
# dạng). Timestamp ĐẦU TIÊN. Status = PENDING|RUNNING|DONE|ERROR (tất định, kết
# quả sản xuất — dropdown do format_board đặt). "Approve(gate 2)" = CỔNG DUYỆT
# NỘI DUNG (PENDING|APPROVE|REJECT, dropdown) — THAY cho tab ContentReview cũ
# (đã xoá); người duyệt chọn ngay trên dòng sản phẩm, không cần tab riêng.
# LỚP 5 (Phase 1) — TopicKey CUỐI CÙNG (append, KHÔNG chen giữa — xem lý do ở
# comment CONTEXT_HEADER phía trên: giữ nguyên vị trí cột hiện có, tránh lệch
# mọi code/test truy cập theo index, vd `row[3]` = Status). BẮT BUỘC KHÔNG được
# liệt vào SheetsBoard._CONTENT_MERGE_COLS (chỉ "timestamp"/"context" bị
# merge-xoá) — đây là cột SỐNG SÓT qua merge, neo lại danh tính chủ đề cho dòng
# con dù Context/Timestamp của nó đã bị mergeCells xoá rỗng.
CONTENT_HEADER = ["Timestamp", "Context", "Type", "Status", "Output", "Notes",
                  "Approve(gate 2)", "TopicKey"]

# 8 tab dựng lần đầu (tên : header). Thứ tự = thứ tự tab hiển thị. ResearchReview/
# ContentReview đã GỘP vào CONTEXT.Status / CONTENT."Approve(gate 2)" -> xoá khỏi
# danh sách (ensure_tabs tự dọn tab cũ còn sót trên Sheet, xem _LEGACY_TABS).
TABS: dict[str, list[str]] = {
    "README": README_HEADER,
    "SOURCES": SOURCES_HEADER,
    "SETTINGS": SETTINGS_HEADER,
    "TAXONOMY": TAXONOMY_HEADER,
    "PROMPTS": PROMPTS_HEADER,
    "CONTEXT": CONTEXT_HEADER,
    "CONTENT": CONTENT_HEADER,
    "LOG": LOG_HEADER,
}

# Tab KHÔNG còn dùng (chức năng đã gộp) — ensure_tabs() TỰ XOÁ nếu còn sót trên
# Sheet (cùng cơ chế dọn "Sheet1" đã có sẵn). Chỉ xoá ĐÚNG tên này, không đụng
# tab lạ khác của người dùng.
_LEGACY_TABS = {"Sheet1", "ResearchReview", "ContentReview"}

# Giá trị mặc định cho cột MỚI khi migrate_rows() gặp header cũ chưa có cột đó
# (vd Execute mới thêm vào CONTEXT). Tab không liệt kê ở đây -> cột mới rỗng "".
# TopicKey (Phase 1) -> "" khi migrate (dòng CŨ chưa có khoá) — CHỦ Ý: backfill
# tính khoá THẬT là bước RIÊNG (backfill_context_topic_keys/backfill_content_
# topic_keys), migrate_rows() chỉ lo dịch chuyển SCHEMA, không tính khoá.
_MIGRATE_DEFAULTS: dict[str, dict[str, str]] = {
    "CONTEXT": {"Execute": "", "TopicKey": ""},
    "CONTENT": {"Approve(gate 2)": "PENDING", "TopicKey": ""},
}

_README_ROWS = [
    ["1) Khai nguồn ở tab SOURCES: Enable=TRUE, Type=rss (feed) hoặc html (trang mục)."],
    ["2) Chỉnh nhóm ưu tiên ở tab SETTINGS (Key=PriorityGroups) — đọc LIVE mỗi lần chạy."],
    ["3) Chỉnh Field/Topic/từ khóa phân loại ở tab TAXONOMY (đọc LIVE mỗi lần chạy)."],
    ["4) Chạy scripts/review_to_sheet.py — bot phát hiện (RSS)/crawl (HTML) thật, "
     "gộp bài trùng giữa các nguồn, UPSERT vào CONTEXT theo url (bài đã có GIỮ NGUYÊN)."],
    ["5) Duyệt ở cột Status của CONTEXT: APPROVE / REJECT (mặc định PENDING). "
     "APPROVE -> tự đặt Execute=RUN (chờ sản xuất)."],
    ["6) scripts/produce_from_sheet.py --draft/--ingest chạy lịch 30'/lần (power_on.py): "
     "CHỈ xử lý dòng Status=APPROVE và Execute=RUN, xong đặt Execute=DONE (idempotent), "
     "ghi tab CONTENT."],
    ["7) Duyệt nội dung (cổng 2) ở cột \"Approve(gate 2)\" của tab CONTENT: APPROVE / REJECT."],
    ["8) Đổi văn phong agent sản xuất: sửa prompts/<Name>.<Version>.md rồi trỏ Version ở tab PROMPTS."],
    ["Cột SOURCES: " + " | ".join(SOURCES_HEADER)],
    ["Cột CONTEXT: " + " | ".join(CONTEXT_HEADER)],
    ["Cột CONTENT: " + " | ".join(CONTENT_HEADER)],
    ["Cột PROMPTS: " + " | ".join(PROMPTS_HEADER)],
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

# Seed PROMPTS: bật sẵn v1 cho 3 agent sản xuất (khớp prompts/<name>.v1.md —
# nội dung giống hệt default nội bộ trong code nên bật/tắt KHÔNG đổi hành vi
# ngay từ đầu; đổi Version ở đây để trỏ sang bản khác mà KHÔNG cần sửa code).
_PROMPTS_SEED_ROWS = [
    ["analysis", "v1", "TRUE"],
    ["video", "v1", "TRUE"],
    ["infographic", "v1", "TRUE"],
]

# Giá trị coi là "bật" ở cột Enable/Use (không phân biệt hoa/thường).
_TRUTHY = {"TRUE", "YES", "Y", "1", "X", "✓", "ĐÚNG", "BẬT"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _now_ddmmyyyy() -> str:
    """Ngày hiện tại dạng DD/MM/YYYY (KHÔNG giờ:phút:giây) — dùng cho cột
    Timestamp CONTEXT/CONTENT (yêu cầu hiển thị gọn). Múi giờ Asia/Ho_Chi_Minh,
    khớp storage.timezone (storage/output/<ngày> dùng CÙNG múi giờ này ở
    produce_from_sheet._today()) — tránh lệch ngày so với UTC gần nửa đêm.
    LOG.timestamp KHÔNG đổi, vẫn dùng _now_iso() đầy đủ giờ để audit."""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    except Exception:  # pragma: no cover - thiếu tzdata (hiếm) -> lùi UTC
        now = datetime.now(timezone.utc)
    return now.strftime("%d/%m/%Y")


def _col_a1(n: int) -> str:
    """Số cột (1-based) -> chữ cái A1 (1->A, 15->O). Tránh phụ thuộc gspread ở lõi."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def migrate_rows(old_header: list[str], new_header: list[str], rows: list[list[str]],
                 *, defaults: dict[str, str] | None = None) -> list[list[str]]:
    """Map DỮ LIỆU (không phải header) từ `old_header` -> `new_header` THEO TÊN
    cột (không phân biệt hoa/thường), KHÔNG mất/lệch dữ liệu khi cột bị đổi thứ
    tự/thêm/bớt. Cột MẤT trong new_header (vd "Use" bị xoá) -> bỏ giá trị đó.
    Cột MỚI (vd "Execute") -> lấy từ `defaults` (theo TÊN cột new_header, không
    phân biệt hoa/thường), thiếu -> "". Hàm THUẦN — test được, dùng khi
    ensure_tabs() phát hiện header đổi (thay cho ws.clear() từng xoá sạch dữ liệu).
    """
    defaults = defaults or {}
    defaults_low = {k.strip().lower(): v for k, v in defaults.items()}
    old_low = [h.strip().lower() for h in old_header]
    out: list[list[str]] = []
    for row in rows:
        new_row: list[str] = []
        for col in new_header:
            col_low = col.strip().lower()
            if col_low in old_low:
                i = old_low.index(col_low)
                new_row.append(row[i] if i < len(row) else "")
            else:
                new_row.append(defaults_low.get(col_low, ""))
        out.append(new_row)
    return out


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


def _source_cell(source_url: str, other_sources: list[str] | None) -> str:
    """Ô Source: url bài chính; nếu có báo khác đưa cùng tin -> thêm '(+N báo)' và
    các url đó XUỐNG DÒNG cùng ô (bỏ cột Sources riêng)."""
    others = [u for u in (other_sources or []) if u and u != source_url]
    if not others:
        return source_url
    return f"{source_url}\n(+{len(others)} báo)\n" + "\n".join(others)


def context_row(*, title: str, hook_line: str, source_url: str, score: int, hot_pct: float,
                topic: str = "", group: str = "", other_sources: list[str] | None = None,
                tickers: list[str] | None = None, status: str = "PENDING",
                execute: str = "", topic_key: str = "", ts: str | None = None) -> list[str]:
    """Một hàng CONTEXT ĐÚNG thứ tự CONTEXT_HEADER (Timestamp đầu tiên).

    Status mặc định PENDING, Execute mặc định rỗng (tự chuyển RUN khi Status=
    APPROVE — xem SheetsBoard.sync_approve_execute_flags). score/hot_pct do
    curation.enrich tính; Group/Topic từ classify (nhóm marketing). Source gộp
    url bài chính + các báo khác đưa cùng tin (dedup chéo nguồn, xem review_to_sheet).
    Publisher/Field KHÔNG ghi ra sheet (chỉ dùng nội bộ cho cluster/tiebreak).
    `topic_key` (Lớp 5 Phase 1) — CALLER tự tính (curation.keys.compute_topic_key)
    rồi truyền vào, hàm này KHÔNG tự tính (giữ context_row() thuần/không phụ
    thuộc curation, giống triết lý các tham số khác ở đây); rỗng nếu caller
    chưa wire (vd đường --draft cũ) — backfill xử lý sau. Đặt CUỐI danh sách
    (khớp CONTEXT_HEADER append, KHÔNG lệch vị trí các cột hiện có).
    """
    return [
        ts or _now_ddmmyyyy(),                            # Timestamp (DD/MM/YYYY, không giờ)
        f"{hot_pct:.1f}",                                   # Hot%
        str(score),                                          # Score
        group,                                                # Group
        topic,                                                 # Topic
        title,                                                  # Context
        hook_line,                                               # Hook
        _source_cell(source_url, other_sources),                  # Source (gộp báo khác)
        status,                                                     # Status
        execute,                                                     # Execute
        ", ".join(tickers or []),                                    # tickers
        "",                                                           # Notes
        topic_key,                                                     # TopicKey (Lớp 5, cuối)
    ]


def content_row(*, context: str, type_: str, status: str, output: str,
                notes: str = "", approve: str = "PENDING", topic_key: str = "",
                ts: str | None = None) -> list[str]:
    """1 hàng CONTENT ĐÚNG thứ tự CONTENT_HEADER (Timestamp|Context|Type|Status|
    Output|Notes|Approve(gate 2)|TopicKey). Status: DONE (sạch)|ERROR (lỗi/
    compliance) — kết quả sản xuất, tất định. Approve(gate 2): cổng NGƯỜI duyệt
    nội dung (PENDING mặc định, thay tab ContentReview cũ). `topic_key` (Lớp 5
    Phase 1) — caller tự tính (curation.keys.compute_topic_key) + truyền vào,
    giống context_row(); rỗng nếu chưa wire. Đặt CUỐI (khớp CONTENT_HEADER append)."""
    return [ts or _now_ddmmyyyy(), context, type_, status, output, notes, approve, topic_key]


_FULL_TYPES = frozenset({"article", "video_script", "infographic"})


def group_content_rows(header: list[str], rows: list[list[str]]) -> dict[str, list[list[str]]]:
    """Nhóm các hàng CONTENT (KHÔNG gồm header) theo Context, GIỮ nguyên thứ tự
    xuất hiện bên trong mỗi nhóm. Hàng Context rỗng bị bỏ qua. Hàm THUẦN — dùng
    bởi regroup_content_rows/content_merge_ranges (test được, không mạng)."""
    low = [h.strip().lower() for h in header]
    if "context" not in low:
        return {}
    ic = low.index("context")
    groups: dict[str, list[list[str]]] = {}
    for r in rows:
        ctx = r[ic].strip() if ic < len(r) else ""
        if not ctx:
            continue
        groups.setdefault(ctx, []).append(r)
    return groups


def regroup_content_rows(header: list[str], rows: list[list[str]]) -> list[list[str]]:
    """Sắp lại `rows` (KHÔNG gồm header) sao cho các hàng CÙNG Context LUÔN liền
    kề nhau — điều kiện bắt buộc để merge dọc (Sheets chỉ merge được 1 dải liên
    tục). Thứ tự xuất hiện ĐẦU TIÊN giữa các Context và thứ tự BÊN TRONG mỗi
    Context được giữ nguyên (ổn định) — chỉ đổi VỊ TRÍ nhóm, không đổi dữ liệu.
    Hàng Context rỗng giữ nguyên thứ tự tương đối, đẩy xuống cuối. Hàm THUẦN."""
    low = [h.strip().lower() for h in header]
    if "context" not in low:
        return list(rows)
    ic = low.index("context")
    groups = group_content_rows(header, rows)
    empty = [r for r in rows if not (r[ic].strip() if ic < len(r) else "")]
    out: list[list[str]] = []
    seen_ctx: set[str] = set()
    for r in rows:
        ctx = r[ic].strip() if ic < len(r) else ""
        if not ctx or ctx in seen_ctx:
            continue
        seen_ctx.add(ctx)
        out.extend(groups[ctx])
    out.extend(empty)
    return out


_MIN_MERGE_TYPES = 2   # ngưỡng merge: Context có >= N loại KHÁC NHAU (article/video_script/
                        # infographic) liền kề là merge — KHÔNG còn bắt buộc đủ cả 3 (_FULL_TYPES
                        # vẫn giữ làm tập THAM KHẢO 3 loại hợp lệ, không dùng để so đủ/thiếu nữa).


def content_merge_ranges(header: list[str], rows: list[list[str]]) -> list[tuple[int, int]]:
    """`rows` PHẢI đã regroup (regroup_content_rows) trước — hàm này chỉ tìm dải,
    KHÔNG tự sắp lại. Trả list (start, end) 0-based/end-exclusive TÍNH THEO SHEET
    (offset +1 vì hàng 1 là header) — mỗi dải là 1 Context có TỪ _MIN_MERGE_TYPES
    (mặc định 2) loại KHÁC NHAU trở lên (đếm loại PHÂN BIỆT, không đếm số hàng)
    nằm ở các hàng LIÊN TIẾP. Context chỉ 1 loại hoặc hàng không liền kề (chưa
    regroup) -> KHÔNG merge."""
    low = [h.strip().lower() for h in header]
    if "context" not in low or "type" not in low:
        return []
    ic, it = low.index("context"), low.index("type")
    ranges: list[tuple[int, int]] = []
    n = len(rows)
    i = 0
    while i < n:
        ctx = rows[i][ic].strip() if ic < len(rows[i]) else ""
        if not ctx:
            i += 1
            continue
        j = i
        types_seen: set[str] = set()
        while j < n and (rows[j][ic].strip() if ic < len(rows[j]) else "") == ctx:
            types_seen.add(rows[j][it].strip().lower() if it < len(rows[j]) else "")
            j += 1
        if len(types_seen) >= _MIN_MERGE_TYPES:
            ranges.append((i + 1, j + 1))
        i = j
    return ranges


# =====================================================================
# LỚP 5 Phase 1/1R.2 — Backfill/Re-key TopicKey (curation/keys.py). Hàm THUẦN.
# Mặc định (force=False): WRITE-ONCE — dòng ĐÃ có TopicKey GIỮ NGUYÊN, không
# tính lại (an toàn chạy nhiều lần, dùng cho steady-state). force=True: NGOẠI
# LỆ RE-KEY MỘT LẦN (Phase 1R.2, xem curation/keys.py docstring) — ghi ĐÈ khoá
# URL-based bằng compute_topic_key() MỚI (sửa khoá SAI tính bởi normalize_url
# Phase 1 gốc, bỏ hết query); surrogate (dòng không-URL) KHÔNG bị đụng (không
# liên quan bug đó) trừ khi đang rỗng thật. Idempotent CẢ 2 chế độ: force=True
# chạy 2 lần vẫn ra CÙNG kết quả vì compute_topic_key là hàm thuần/tất định.
# Xem SheetsBoard.backfill_topic_keys() cho bản chạy live (đọc/ghi Sheet thật).
# =====================================================================
def backfill_context_topic_keys(header: list[str], rows: list[list[str]],
                                *, force: bool = False) -> list[list[str]]:
    """`force=False` (mặc định, WRITE-ONCE): điền TopicKey RỖNG cho các dòng
    CONTEXT — tính/gán qua `curation.keys.assign_topic_key()` (URL hợp lệ ->
    compute_topic_key; không có URL -> surrogate uuid4, KHÔNG BAO GIỜ để lại
    ""). Dòng ĐÃ có TopicKey GIỮ NGUYÊN TUYỆT ĐỐI.
    `force=True` (NGOẠI LỆ re-key một lần, Phase 1R.2): dòng CÓ url hợp lệ ->
    TÍNH LẠI + GHI ĐÈ bằng compute_topic_key() MỚI bất kể đã có khoá gì (bypass
    write-once có chủ đích — sửa khoá SAI từ normalize_url Phase 1 gốc). Dòng
    KHÔNG có url -> XỬ LÝ NHƯ force=False (giữ nguyên nếu có, chỉ gán surrogate
    khi đang rỗng — surrogate không liên quan bug cần sửa).
    Trả `rows` MỚI (không sửa in-place); thiếu cột Source/TopicKey -> trả
    nguyên `rows` (no-op an toàn)."""
    from .curation.keys import assign_topic_key, compute_topic_key   # lazy: tránh vòng import

    low = [h.strip().lower() for h in header]
    if "source" not in low or "topickey" not in low:
        return list(rows)
    i_src, i_key = low.index("source"), low.index("topickey")

    out: list[list[str]] = []
    for row in rows:
        row = list(row)
        while len(row) <= max(i_src, i_key):
            row.append("")
        primary_url = row[i_src].splitlines()[0].strip() if row[i_src] else ""
        existing = row[i_key].strip()
        if force and primary_url:
            new_key = compute_topic_key(primary_url)
            row[i_key] = new_key if new_key else assign_topic_key(existing, url=primary_url)
        elif not existing:
            row[i_key] = assign_topic_key(existing, url=primary_url)
        # else: existing khác rỗng và (không force HOẶC force nhưng không có
        # url) -> GIỮ NGUYÊN (write-once).
        out.append(row)
    return out


def backfill_content_topic_keys(
    context_header: list[str], context_rows: list[list[str]],
    content_header: list[str], content_rows: list[list[str]],
    *, force: bool = False,
) -> tuple[list[list[str]], list[str]]:
    """`force=False` (mặc định, WRITE-ONCE): điền TopicKey RỖNG cho các dòng
    CONTENT — tra chủ đề qua Context text rồi map sang TopicKey ĐÃ CÓ ở CONTEXT
    (`context_rows` nên là kết quả SAU backfill_context_topic_keys, để có khoá
    tra). CARRY-FORWARD cho dòng Context bị BLANK (Sheets API mergeCells XOÁ
    giá trị mọi ô trừ ô đầu dải merge — xem curation/keys.py docstring): dùng
    Context KHÔNG-RỖNG gần nhất PHÍA TRÊN làm chủ đề hiệu lực. Dòng ĐÃ có
    TopicKey GIỮ NGUYÊN (idempotent).
    `force=True` (NGOẠI LỆ re-key một lần, Phase 1R.2): GHI ĐÈ TopicKey của
    MỌI dòng CONTENT theo ánh xạ title->key MỚI NHẤT từ CONTEXT (context_rows
    nên là kết quả SAU rekey CONTEXT với force=True) — đồng bộ lại CONTENT
    khớp CONTEXT vừa re-key.
    Trả (rows MỚI, list Context KHÔNG tra được khoá — vd đã bị xoá khỏi
    CONTEXT, hoặc CONTEXT dòng đó cũng chưa có TopicKey — để caller log cảnh
    báo, KHÔNG tự bịa khoá)."""
    clow = [h.strip().lower() for h in context_header]
    low = [h.strip().lower() for h in content_header]
    if "context" not in clow or "topickey" not in clow or "context" not in low or "topickey" not in low:
        return list(content_rows), []
    ic_ctx, ic_key = clow.index("context"), clow.index("topickey")
    title_to_key: dict[str, str] = {}
    for r in context_rows:
        title = r[ic_ctx].strip() if ic_ctx < len(r) else ""
        key = r[ic_key].strip() if ic_key < len(r) else ""
        if title and key:
            title_to_key[title] = key

    ic, ik = low.index("context"), low.index("topickey")
    out: list[list[str]] = []
    warnings: list[str] = []
    last_context = ""
    for row in content_rows:
        row = list(row)
        while len(row) <= max(ic, ik):
            row.append("")
        ctx = row[ic].strip()
        if ctx:
            last_context = ctx
        effective_ctx = ctx or last_context   # carry-forward qua merge-blank
        if force or not row[ik].strip():
            key = title_to_key.get(effective_ctx, "")
            if key:
                row[ik] = key
            elif effective_ctx and not row[ik].strip():
                warnings.append(effective_ctx)
        out.append(row)
    return out, warnings


# =====================================================================
# Fix (a) Phase 2 — dọn dòng CONTEXT trùng TopicKey CŨ (dữ liệu TRƯỚC khi Fix
# (a) Phase 1 chặn trùng mới ở upsert_context_rows). Dùng bởi scripts/
# dedupe_context.py. Hàm THUẦN, test được không cần Sheet thật.
# =====================================================================
def find_duplicate_context_groups(header: list[str], rows: list[list[str]]) -> dict[str, list[int]]:
    """{TopicKey: [số dòng Sheet 1-based, ...]} CHỈ cho TopicKey xuất hiện Ở
    ÍT NHẤT 2 dòng. `rows` KHÔNG gồm header (rows[0] = dòng Sheet 2). TopicKey
    rỗng bị bỏ qua (không tính là "trùng nhau", giống upsert_context_rows)."""
    low = [h.strip().lower() for h in header]
    if "topickey" not in low:
        return {}
    i_tk = low.index("topickey")
    groups: dict[str, list[int]] = {}
    for offset, r in enumerate(rows):
        tk = r[i_tk].strip() if i_tk < len(r) else ""
        if not tk:
            continue
        groups.setdefault(tk, []).append(offset + 2)
    return {k: v for k, v in groups.items() if len(v) > 1}


def _keep_rank(status: str, execute: str) -> int:
    """Điểm ưu tiên GIỮ (cao hơn = ưu tiên giữ hơn): Execute=DONE (3) >
    Status=APPROVE hoặc Execute=RUN (2) > còn lại/PENDING (1)."""
    execute = (execute or "").strip().upper()
    status = (status or "").strip().upper()
    if execute == "DONE":
        return 3
    if status == "APPROVE" or execute == "RUN":
        return 2
    return 1


def choose_keep_row(candidates: list[dict]) -> int:
    """`candidates` = [{"row": int, "status": str, "execute": str,
    "has_content": bool}, ...] CÙNG 1 TopicKey. Trả số dòng (1-based) nên GIỮ
    theo quy tắc ưu tiên đã duyệt: rank(Execute=DONE > Status=APPROVE/Execute=
    RUN > PENDING) giảm dần -> hoà thì có CONTENT con thắng -> hoà nữa thì
    dòng nhỏ nhất (số dòng thấp nhất, xuất hiện sớm nhất)."""
    best = max(candidates, key=lambda c: (_keep_rank(c["status"], c["execute"]),
                                          bool(c["has_content"]), -c["row"]))
    return best["row"]


def extract_cell_url(cell: dict) -> str | None:
    """URL THẬT gắn với 1 ô (CellData từ spreadsheets.get/fetch_sheet_metadata
    với includeGridData=True), KHÔNG dựa formattedValue/get_all_values() —
    Sheets có thể hiển thị TIÊU ĐỀ trong khi cell vẫn link tới URL thật
    ("title-chip", quan sát THẬT trên board production: Source hiển thị tiêu
    đề bài, nhưng hyperlink ẩn bên dưới là URL crawl gốc).
    Ưu tiên `cell["hyperlink"]` (link áp cho CẢ ô — trường hợp phổ biến).
    Fallback `cell["textFormatRuns"][i]["format"]["link"]["uri"]` (link áp cho
    1 PHẦN chuỗi — quan sát THẬT trên board: 1 dòng có link nằm ở textFormatRuns
    thay vì cell["hyperlink"], có thể do cách link được chèn khác nhau).
    None nếu không tìm thấy URL nào (ô là text thuần, không link)."""
    hl = cell.get("hyperlink")
    if hl:
        return hl
    for run in cell.get("textFormatRuns") or []:
        uri = ((run.get("format") or {}).get("link") or {}).get("uri")
        if uri:
            return uri
    return None


def is_title_chip(cell: dict, formatted_value: str) -> bool:
    """True nếu ô CÓ url thật (extract_cell_url) NHƯNG KHÁC formattedValue —
    dấu hiệu cột Source "nói dối" nếu đọc bằng get_all_values() (hiện chữ tiêu
    đề, không phải URL). False nếu ô không có url (text thuần) HOẶC url TRÙNG
    formattedValue (chip nhưng hiển thị đúng URL, không gây hiểu lầm)."""
    url = extract_cell_url(cell)
    return bool(url) and url.strip() != (formatted_value or "").strip()


# =====================================================================
# LỚP 5 Phase 2 — Upsert CONTENT theo khoá. INVARIANT (chốt của Lead): match-
# or-insert TRA THEO CỘT TopicKey ĐÃ LƯU. TUYỆT ĐỐI không tra theo Source sống,
# không theo chỉ số dòng. TopicKey KHÔNG nằm trong _CONTENT_MERGE_COLS nên
# SỐNG SÓT mergeCells (khác Context/Timestamp bị API xoá thật) — đây là lý do
# chuyển dedup từ (Context, Type) sang (TopicKey, Type) đóng dứt điểm bug
# "content mồ côi" (xem curation/keys.py docstring cho gốc rễ đầy đủ).
# =====================================================================
def content_topic_keys(header: list[str], rows: list[list[str]]) -> tuple[set[tuple[str, str]], list[str]]:
    """(TopicKey, Type) đã có trong CONTENT — đọc TRỰC TIẾP cột TopicKey, KHÔNG
    suy/tái tạo từ Context (bị mergeCells xoá thật, không đáng tin). Dòng CÓ
    Type nhưng TopicKey RỖNG (dữ liệu cũ chưa backfill/rekey — xem
    backfill_content_topic_keys) KHÔNG được đưa vào set khoá (không thể định
    danh theo khoá) — Context của các dòng đó (carry-forward qua merge-blank,
    cùng kỹ thuật backfill_content_topic_keys) trả riêng ở phần tử thứ 2 để
    caller CẢNH BÁO/NEEDS_HUMAN. TUYỆT ĐỐI KHÔNG dùng Context này để auto-map
    khoá — chỉ để báo người vận hành chạy backfill_topic_keys.py.
    Hàm THUẦN — SheetsBoard.existing_content_keys()/existing_content_missing_
    keys() là 2 wrapper live gọi hàm này."""
    low = [h.strip().lower() for h in header]
    if "type" not in low or "topickey" not in low:
        return set(), []
    it, ik = low.index("type"), low.index("topickey")
    ic = low.index("context") if "context" in low else None
    keys: set[tuple[str, str]] = set()
    missing: list[str] = []
    last_context = ""
    for r in rows:
        type_ = r[it].strip() if it < len(r) else ""
        if not type_:
            continue
        ctx = r[ic].strip() if ic is not None and ic < len(r) else ""
        if ctx:
            last_context = ctx
        key = r[ik].strip() if ik < len(r) else ""
        if key:
            keys.add((key, type_))
        else:
            effective_ctx = ctx or last_context
            if effective_ctx:
                missing.append(effective_ctx)
    return keys, missing


def approved_context_from_rows(rows: list[list[str]]) -> list[dict]:
    """Các dòng CONTEXT có Status=APPROVE -> list dict (ánh xạ theo TÊN cột):
    context (tiêu đề), hook, source (url chính), tickers, group, topic, execute
    (RUN/DONE/rỗng), row (số dòng 1-based TRÊN SHEET — dùng để ghi lại
    Execute=DONE sau khi sản xuất xong, xem SheetsBoard.mark_execute_done),
    topic_key (Lớp 5 Phase 1 — cột TopicKey đã backfill/ghi sẵn; rỗng nếu dòng
    chưa có, vd trước khi chạy backfill — caller tự quyết định lùi mượt)."""
    if not rows:
        return []
    header = [c.strip().lower() for c in rows[0]]

    def idx(name: str) -> int | None:
        return header.index(name) if name in header else None

    i_ctx, i_hook, i_src = idx("context"), idx("hook"), idx("source")
    i_tk, i_grp, i_tp, i_st = idx("tickers"), idx("group"), idx("topic"), idx("status")
    i_ex, i_key = idx("execute"), idx("topickey")
    if i_ctx is None or i_st is None:
        return []

    def cell(row: list[str], i: int | None) -> str:
        return row[i].strip() if i is not None and i < len(row) else ""

    out: list[dict] = []
    for row_i, row in enumerate(rows[1:], start=2):   # dòng 1 = header trên Sheet
        if cell(row, i_st).upper() != "APPROVE":
            continue
        ctx = cell(row, i_ctx)
        if not ctx:
            continue
        raw_src = cell(row, i_src)
        src = raw_src.splitlines()[0] if raw_src else ""   # ô Source gộp -> lấy url chính
        tickers = [t.strip() for t in cell(row, i_tk).split(",") if t.strip()]
        out.append({"context": ctx, "hook": cell(row, i_hook), "source": src,
                    "tickers": tickers, "group": cell(row, i_grp), "topic": cell(row, i_tp),
                    "execute": cell(row, i_ex).upper(), "row": row_i,
                    "topic_key": cell(row, i_key)})
    return out


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


def prompt_versions_from_rows(rows: list[list[str]]) -> dict[str, str]:
    """Dựng dict Name->Version từ hàng tab PROMPTS; CHỈ giữ hàng Enable bật.
    Dùng bởi agents.prompts.resolve_prompts để nạp prompts/<Name>.<Version>.md."""
    if not rows:
        return {}
    header = [c.strip().lower() for c in rows[0]]
    if "name" not in header or "version" not in header:
        return {}
    i_name, i_ver = header.index("name"), header.index("version")
    i_en = header.index("enable") if "enable" in header else None

    def cell(row: list[str], i: int) -> str:
        return row[i].strip() if i < len(row) else ""

    out: dict[str, str] = {}
    for row in rows[1:]:
        if i_en is not None and cell(row, i_en).upper() not in _TRUTHY:
            continue
        name = cell(row, i_name)
        if name:
            out[name] = cell(row, i_ver)
    return out


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
_C_RUN = "#CFE2F3"         # xanh dương nhạt — Execute=RUN (đang chờ sản xuất)
_C_SCORE_MIN = "#FFFFFF"
_C_SCORE_MID = "#B6D7A8"
_C_SCORE_MAX = "#38761D"

# Freeze cột đầu cho tiện cuộn ngang (CONTEXT/CONTENT: cột đầu = Timestamp, dễ
# thấy khi cuộn sang các cột nội dung dài hơn).
_FREEZE_FIRST_COL = {"CONTEXT", "CONTENT", "LOG"}

# Bề rộng cột (px) theo TÊN header (chữ thường). Cột dài rộng, score/status hẹp.
_COL_WIDTH = {
    "timestamp": 155, "title": 360, "hook": 320, "url": 260, "score": 70,
    "tickers": 150, "decision": 110, "notes": 220, "level": 80, "message": 440,
    "gate": 110, "label": 170, "payload": 380, "enable": 80, "key": 120,
    "name": 210, "type": 90, "status": 110, "context": 380, "output": 380,
    "prompt": 380, "template": 380,
    "hot%": 80, "group": 140, "source": 260, "value": 260,
    "publisher": 170, "field": 110, "topic": 130, "sources": 260, "feedurl": 260,
    "interval": 80, "priority": 80, "keywords": 380, "execute": 90,
    "approve(gate 2)": 130,
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
    if t.name == "CONTEXT" and "status" in low:  # -> dropdown quy trình duyệt (cổng 1)
        c = low.index("status")
        out.append(_set_validation(sid, 1, fmt_rows, c,
                                   _one_of_list(["PENDING", "APPROVE", "REJECT"])))
    if t.name == "CONTEXT" and "execute" in low:  # -> dropdown cờ thực thi sản xuất
        c = low.index("execute")
        out.append(_set_validation(sid, 1, fmt_rows, c,
                                   _one_of_list(["RUN", "DONE", "FAILED", "NEEDS_HUMAN"])))
    if t.name == "CONTENT" and "status" in low:  # -> dropdown (kết quả sản xuất, tất định)
        c = low.index("status")
        out.append(_set_validation(sid, 1, fmt_rows, c,
                                   _one_of_list(["PENDING", "RUNNING", "DONE", "ERROR", "SKIPPED"])))
    if t.name == "CONTENT" and "approve(gate 2)" in low:  # -> dropdown quy trình duyệt (cổng 2)
        c = low.index("approve(gate 2)")
        out.append(_set_validation(sid, 1, fmt_rows, c,
                                   _one_of_list(["PENDING", "APPROVE", "REJECT"])))

    # 8) Conditional formatting cho CONTEXT/CONTENT (xóa rule cũ trước -> idempotent).
    if t.name in ("CONTEXT", "CONTENT"):
        for i in range(t.cond_format_count - 1, -1, -1):
            out.append({"deleteConditionalFormatRule": {"sheetId": sid, "index": i}})
    if t.name == "CONTEXT":
        if "status" in low:
            c = low.index("status")
            out.append(_text_eq_rule(sid, c, 1, fmt_rows, "APPROVE", _C_APPROVE))
            out.append(_text_eq_rule(sid, c, 1, fmt_rows, "PENDING", _C_PENDING))
            out.append(_text_eq_rule(sid, c, 1, fmt_rows, "REJECT", _C_REJECT))
        if "execute" in low:
            c = low.index("execute")
            out.append(_text_eq_rule(sid, c, 1, fmt_rows, "RUN", _C_RUN))
            out.append(_text_eq_rule(sid, c, 1, fmt_rows, "DONE", _C_APPROVE))
            out.append(_text_eq_rule(sid, c, 1, fmt_rows, "FAILED", _C_PENDING))       # vàng — tái chạy được
            out.append(_text_eq_rule(sid, c, 1, fmt_rows, "NEEDS_HUMAN", _C_REJECT))   # đỏ — chờ người
        if "score" in low:
            c = low.index("score")
            out.append(_score_scale_rule(sid, c, 1, fmt_rows))
        if "hot%" in low:  # thang màu độ hot, cùng kiểu gradient với score
            c = low.index("hot%")
            out.append(_score_scale_rule(sid, c, 1, fmt_rows))
    if t.name == "CONTENT" and "approve(gate 2)" in low:
        c = low.index("approve(gate 2)")
        out.append(_text_eq_rule(sid, c, 1, fmt_rows, "APPROVE", _C_APPROVE))
        out.append(_text_eq_rule(sid, c, 1, fmt_rows, "PENDING", _C_PENDING))
        out.append(_text_eq_rule(sid, c, 1, fmt_rows, "REJECT", _C_REJECT))

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
        sh = gspread.authorize(creds).open_by_key(self.spreadsheet_id)
        self._sh = _RetryingProxy(sh)   # mọi method (worksheets/batch_update/...) tự retry 429
        return self._sh

    def ensure_tabs(self, *, force: bool = False) -> list[str]:
        """Đảm bảo đủ 8 tab + header ĐÚNG + định dạng (format_board).

        GIẢM LƯỢT GỌI SHEETS API: mặc định (force=False) chỉ chạy phần tạo/seed/
        format NẶNG khi phát hiện tab thiếu hoặc header SAI — dò bằng
        `_headers_need_setup()` (2 lệnh gọi rẻ: worksheets() + values_batch_get,
        so với >20 lệnh của luồng setup đầy đủ). Dùng `force=True` (cờ --setup
        ở CLI) để LUÔN chạy setup đầy đủ (vd sau khi đổi schema cột thủ công).
        Trả về tên các tab vừa TẠO MỚI (rỗng nếu bỏ qua vì đã đúng header).
        """
        if not force and not self._headers_need_setup():
            return []
        return self._full_ensure_tabs()

    def _headers_need_setup(self) -> bool:
        """Kiểm tra RẺ (2 lệnh gọi): có tab nào THIẾU, hoặc header hàng 1 của tab
        nào SAI so với TABS. Lỗi mạng/API bất kỳ -> coi như CẦN setup (an toàn)."""
        try:
            sh = self._spreadsheet()
            existing = {w.title for w in sh.worksheets()}
            if any(name not in existing for name in TABS):
                return True
            ranges = [f"'{name}'!A1:{_col_a1(len(header))}1" for name, header in TABS.items()]
            resp = sh.values_batch_get(ranges)
        except Exception:  # pragma: no cover - lỗi mạng/API -> an toàn, cần setup
            return True
        value_ranges = resp.get("valueRanges", [])
        for (name, header), vr in zip(TABS.items(), value_ranges):
            values = vr.get("values") or [[]]
            row = values[0] if values else []
            if row != header:
                return True
        return False

    def _full_ensure_tabs(self) -> list[str]:
        """Tạo đủ 8 tab + hàng header nếu chưa có, seed dữ liệu mẫu, rồi format_board.
        Luồng NẶNG — chỉ gọi qua ensure_tabs() khi thật cần (xem đó)."""
        import gspread

        sh = self._spreadsheet()
        existing = {w.title for w in sh.worksheets()}
        created: list[str] = []
        for name, header in TABS.items():
            if name in existing:
                ws = _RetryingProxy(sh.worksheet(name))
            else:
                ws = _RetryingProxy(sh.add_worksheet(title=name, rows=1000, cols=max(len(header), 8)))
                created.append(name)
            all_values = ws.get_all_values()
            cur = all_values[0] if all_values else []
            if cur != header:
                # MIGRATE: header đổi -> map DỮ LIỆU cũ sang cột MỚI theo TÊN cột
                # (migrate_rows, KHÔNG mất/lệch dữ liệu — thay cho ws.clear() cũ
                # từng xoá sạch dòng đã duyệt). Cột mới (vd Execute) lấy default
                # ở _MIGRATE_DEFAULTS; cột bị xoá (vd Use) rớt tự nhiên.
                old_rows = all_values[1:] if cur else []
                new_rows = migrate_rows(cur, header, old_rows,
                                        defaults=_MIGRATE_DEFAULTS.get(name, {}))
                ws.update("A1", [header, *new_rows], value_input_option="USER_ENTERED")
            if name == "README" and len(ws.get_all_values()) <= 1:
                ws.append_rows(_README_ROWS, value_input_option="RAW")
            if name == "SETTINGS" and len(ws.get_all_values()) <= 1:
                ws.append_rows(_SETTINGS_SEED_ROWS, value_input_option="RAW")
            if name == "TAXONOMY" and len(ws.get_all_values()) <= 1:
                ws.append_rows(_TAXONOMY_SEED_ROWS, value_input_option="RAW")
            if name == "PROMPTS" and len(ws.get_all_values()) <= 1:
                ws.append_rows(_PROMPTS_SEED_ROWS, value_input_option="USER_ENTERED")
            self._ws[name] = ws
        # Dọn tab CŨ không còn dùng: "Sheet1" (gspread tự tạo lúc dựng spreadsheet)
        # + ResearchReview/ContentReview (chức năng đã gộp vào CONTEXT.Status/
        # CONTENT."Approve(gate 2)"). CHỈ xoá ĐÚNG tên trong _LEGACY_TABS, không
        # đụng tab lạ khác của người dùng.
        for legacy in _LEGACY_TABS:
            if legacy in existing:
                try:
                    sh.del_worksheet(sh.worksheet(legacy))
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
        requests = self._drop_stale_delete_banding(sh, requests)
        if requests:
            sh.batch_update({"requests": requests})
        return len(requests)

    def _drop_stale_delete_banding(self, sh, requests: list[dict]) -> list[dict]:
        """GET lại danh sách bandedRangeId CÒN TỒN TẠI ngay TRƯỚC khi gửi
        batchUpdate, chỉ giữ deleteBanding cho ID còn tồn tại — tránh lỗi 400
        "no banding with id X" khi ID đã bị xoá bởi 1 lượt chạy KHÁC giữa lúc
        format_board() đọc metadata (đầu hàm) và lúc gửi batchUpdate (đóng khe
        hở race, vd 2 lịch power_on.py chạy song song). No-op nếu không có
        deleteBanding nào trong `requests` (đỡ tốn 1 lượt gọi khi không cần)."""
        if not any("deleteBanding" in r for r in requests):
            return requests
        try:
            fresh = sh.fetch_sheet_metadata(
                params={"fields": "sheets(bandedRanges(bandedRangeId))"})
        except Exception:  # pragma: no cover - lỗi mạng -> giữ nguyên, để batch_update tự báo
            return requests
        live_ids = {
            b["bandedRangeId"]
            for s in fresh.get("sheets", [])
            for b in s.get("bandedRanges", [])
            if b.get("bandedRangeId") is not None
        }
        return [
            r for r in requests
            if "deleteBanding" not in r or r["deleteBanding"]["bandedRangeId"] in live_ids
        ]

    def _tab(self, name: str):
        if name not in self._ws:
            self._ws[name] = _RetryingProxy(self._spreadsheet().worksheet(name))
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

    def read_approved_context(self) -> list[dict]:
        """Đọc CONTEXT -> các dòng Status=APPROVE (đầu vào giai đoạn Production)."""
        try:
            rows = self._tab("CONTEXT").get_all_values()
        except Exception:  # pragma: no cover - tab chưa tồn tại
            return []
        return approved_context_from_rows(rows)

    def existing_content_keys(self) -> set[tuple[str, str]]:
        """(TopicKey, Type) đã có trong CONTENT (Lớp 5 Phase 2) — đọc TRỰC TIẾP
        cột TopicKey, bỏ qua sản phẩm đã sinh để KHỎI tốn Sonnet lại (dedup
        across-run). Xem content_topic_keys() cho lý do đóng dứt điểm "content
        mồ côi" (KHÔNG suy từ Context, sống sót mergeCells)."""
        try:
            rows = self._tab("CONTENT").get_all_values()
        except Exception:  # pragma: no cover - tab chưa tồn tại
            return set()
        if not rows:
            return set()
        keys, _missing = content_topic_keys(rows[0], rows[1:])
        return keys

    def existing_content_missing_keys(self) -> list[str]:
        """Context (carry-forward qua merge-blank) của các dòng CONTENT CÓ Type
        nhưng TopicKey RỖNG (dữ liệu cũ chưa backfill/rekey, Lớp 5 Phase 2) —
        dùng để CẢNH BÁO/NEEDS_HUMAN. TUYỆT ĐỐI KHÔNG dùng để auto-map khoá."""
        try:
            rows = self._tab("CONTENT").get_all_values()
        except Exception:  # pragma: no cover - tab chưa tồn tại
            return []
        if not rows:
            return []
        _keys, missing = content_topic_keys(rows[0], rows[1:])
        return missing

    def append_content_rows(self, rows: list[list[str]]) -> int:
        """Ghi thêm (append) các dòng sản phẩm vào tab CONTENT. Trả số dòng đã ghi."""
        if not rows:
            return 0
        self._tab("CONTENT").append_rows(rows, value_input_option="RAW")
        return len(rows)

    _CONTENT_MERGE_COLS = ("timestamp", "context")

    def regroup_and_merge_content(self) -> int:
        """Sắp lại tab CONTENT để các hàng CÙNG chủ đề (Context) liền kề nhau
        (regroup_content_rows — CHỈ đổi vị trí, không đổi dữ liệu), rồi merge dọc
        cột Timestamp+Context cho các chủ đề có TỪ 2 LOẠI khác nhau trở lên
        (article/video_script/infographic — content_merge_ranges, ngưỡng
        _MIN_MERGE_TYPES). Idempotent: unmerge TOÀN vùng dữ liệu trước khi merge
        lại nên gọi nhiều lần không lỗi/không merge chồng. Trả số dải đã merge
        (0 -> không đổi gì, kể cả khi tab rỗng/thiếu cột)."""
        ws = self._tab("CONTENT")
        values = ws.get_all_values()
        if len(values) < 2:
            return 0
        header, rows = values[0], values[1:]
        low = [h.strip().lower() for h in header]

        new_rows = regroup_content_rows(header, rows)
        if new_rows != rows:
            ws.update("A2", new_rows, value_input_option="RAW")
        ranges = content_merge_ranges(header, new_rows)

        sid = ws.id
        ncols = len(header)
        n_rows = len(new_rows) + 1   # +1 header
        reqs: list[dict] = [{"unmergeCells": {"range": _grid_range(sid, 1, n_rows, 0, ncols)}}]
        for col_name in self._CONTENT_MERGE_COLS:
            if col_name not in low or not ranges:
                continue
            c = low.index(col_name)
            for r0, r1 in ranges:
                reqs.append({"mergeCells": {"range": _grid_range(sid, r0, r1, c, c + 1),
                                            "mergeType": "MERGE_COLUMNS"}})
                reqs.append({"repeatCell": {
                    "range": _grid_range(sid, r0, r1, c, c + 1),
                    "cell": {"userEnteredFormat": {"verticalAlignment": "MIDDLE"}},
                    "fields": "userEnteredFormat.verticalAlignment",
                }})
        self._spreadsheet().batch_update({"requests": reqs})
        return len(ranges)

    def backfill_topic_keys(self, *, force: bool = False) -> dict:
        """LỚP 5 Phase 1/1R.2 — điền TopicKey rỗng cho CONTEXT rồi CONTENT
        (THEO THỨ TỰ NÀY — CONTENT cần tra title->key đã có ở CONTEXT).
        `force=False` (mặc định, WRITE-ONCE): chỉ điền dòng RỖNG, GIỮ NGUYÊN
        dòng đã có khoá — an toàn chạy nhiều lần/theo lịch.
        `force=True` (NGOẠI LỆ RE-KEY MỘT LẦN, Phase 1R.2 — xem docs/
        CHANGELOG.md): GHI ĐÈ mọi khoá URL-based bằng compute_topic_key() MỚI
        (canonical, giữ query định danh) — sửa khoá SAI tính bởi normalize_url
        Phase 1 gốc (bỏ hết query, có thể đã va chạm). Surrogate (dòng không
        URL) KHÔNG bị đụng. CHỈ dùng ĐÚNG 1 LẦN khi migrate — sau đó luôn gọi
        force=False (mặc định) để write-once có hiệu lực. Idempotent CẢ 2 chế
        độ (chạy lại không đổi thêm — chỉ ghi lại range khi THẬT SỰ có dòng
        thay đổi, tránh gọi Sheets API vô ích). Trả {"context": số dòng CONTEXT
        vừa đổi, "content": số dòng CONTENT vừa đổi, "warnings": [Context text
        không tra được khoá]}."""
        ctx_ws = self._tab("CONTEXT")
        ctx_values = ctx_ws.get_all_values()
        if len(ctx_values) < 2:
            return {"context": 0, "content": 0, "warnings": []}
        ctx_header, ctx_rows = ctx_values[0], ctx_values[1:]
        new_ctx_rows = backfill_context_topic_keys(ctx_header, ctx_rows, force=force)
        n_ctx = sum(1 for old, new in zip(ctx_rows, new_ctx_rows) if old != new)
        if n_ctx:
            ctx_ws.update("A2", new_ctx_rows, value_input_option="RAW")

        content_ws = self._tab("CONTENT")
        content_values = content_ws.get_all_values()
        n_content = 0
        warnings: list[str] = []
        if len(content_values) >= 2:
            content_header, content_rows = content_values[0], content_values[1:]
            new_content_rows, warnings = backfill_content_topic_keys(
                ctx_header, new_ctx_rows, content_header, content_rows, force=force)
            n_content = sum(1 for old, new in zip(content_rows, new_content_rows) if old != new)
            if n_content:
                content_ws.update("A2", new_content_rows, value_input_option="RAW")
        return {"context": n_ctx, "content": n_content, "warnings": warnings}

    def set_topic_key_values(self, key_by_row: dict[int, str]) -> None:
        """LỚP 5 Phase 1R.2 — ghi TopicKey cho NHIỀU dòng CONTEXT (số dòng
        1-based) — dùng khi produce_from_sheet.py PHÁT HIỆN dòng CONTEXT CHƯA
        có TopicKey (backfill/rekey chưa chạy tới, hoặc dòng --draft cũ) và
        `curation.keys.assign_topic_key()` vừa gán khoá MỚI (URL-based hoặc
        surrogate) — PHẢI ghi lại NGAY để lần sau write-once có hiệu lực (đọc
        lại đúng khoá cũ, KHÔNG tính lại/KHÔNG đổi surrogate). Cùng khuôn mẫu
        với set_execute_values(). No-op nếu `key_by_row` rỗng hoặc thiếu cột
        TopicKey."""
        if not key_by_row:
            return
        ws = self._tab("CONTEXT")
        header = [h.strip().lower() for h in ws.row_values(1)]
        if "topickey" not in header:
            return
        col_letter = _col_a1(header.index("topickey") + 1)
        ws.batch_update([{"range": f"{col_letter}{r}", "values": [[v]]}
                         for r, v in key_by_row.items()], value_input_option="RAW")

    # --- Fix (a) Phase 2: dọn dòng CONTEXT trùng TopicKey cũ ------------
    def fetch_context_source_cells(self, rows: list[int]) -> dict[int, dict]:
        """{số dòng 1-based: CellData thô (formattedValue/hyperlink/
        textFormatRuns)} cho cột Source của các dòng CONTEXT chỉ định — gọi
        spreadsheets.get (KHÔNG phải get_all_values, vốn chỉ trả formattedValue,
        thiếu hyperlink) để dedupe_context.py xác minh "title-chip" trước khi
        xoá (xem sheets_board.extract_cell_url/is_title_chip). Rỗng -> {}."""
        if not rows:
            return {}
        header = [h.strip().lower() for h in self._tab("CONTEXT").row_values(1)]
        if "source" not in header:
            return {}
        col = _col_a1(header.index("source") + 1)
        r0, r1 = min(rows), max(rows)
        params = {
            "ranges": [f"CONTEXT!{col}{r0}:{col}{r1}"],
            "fields": "sheets.data.rowData.values(formattedValue,hyperlink,textFormatRuns)",
            "includeGridData": True,
        }
        meta = self._spreadsheet().fetch_sheet_metadata(params=params)
        data = meta.get("sheets", [{}])[0].get("data", [{}])[0].get("rowData", [])
        out: dict[int, dict] = {}
        for i, row_data in enumerate(data):
            row_n = r0 + i
            if row_n not in rows:
                continue
            values = row_data.get("values") or [{}]
            out[row_n] = values[0] if values else {}
        return out

    def backup_tab(self, name: str, *, suffix: str) -> str:
        """Sao chép TOÀN BỘ tab `name` (dữ liệu + định dạng) sang tab MỚI
        "<name>_backup_<suffix>" TRƯỚC khi làm thao tác phá huỷ (Fix (a) Phase
        2b). Idempotent: xoá bản backup TRÙNG TÊN nếu đã có (chạy --apply 2
        lần cùng ngày không lỗi/không chồng — GHI ĐÈ backup cũ trong ngày bằng
        bản mới nhất trước khi xoá thật). Trả tên tab backup vừa tạo."""
        import gspread

        sh = self._spreadsheet()
        src = self._tab(name)
        new_title = f"{name}_backup_{suffix}"
        try:
            old = sh.worksheet(new_title)
            sh.del_worksheet(old)
        except gspread.exceptions.WorksheetNotFound:
            pass
        new_ws = sh.duplicate_sheet(source_sheet_id=src.id, new_sheet_name=new_title)
        return new_ws.title

    def delete_context_rows(self, rows: list[int]) -> None:
        """Xoá NHIỀU dòng CONTEXT (số dòng Sheet 1-based) 1 lượt batch_update.
        Sắp XOÁ TỪ DƯỚI LÊN (số dòng giảm dần) trong CÙNG 1 batch — deleteDimension
        áp dụng TUẦN TỰ theo thứ tự request; xoá dòng nhỏ trước sẽ làm lệch số
        dòng lớn hơn chưa xoá, xoá từ dưới lên tránh mất đồng bộ index."""
        if not rows:
            return
        ws = self._tab("CONTEXT")
        sid = ws.id
        reqs = [
            {"deleteDimension": {"range": {"sheetId": sid, "dimension": "ROWS",
                                           "startIndex": r - 1, "endIndex": r}}}
            for r in sorted(set(rows), reverse=True)
        ]
        self._spreadsheet().batch_update({"requests": reqs})

    def set_context_cell(self, row: int, col_name: str, value: str) -> None:
        """Ghi 1 giá trị vào 1 ô CONTEXT (số dòng 1-based, tên cột KHÔNG phân
        biệt hoa/thường) — dùng để "chép" URL thật (extract_cell_url) vào ô
        Source của dòng GIỮ khi nó đang là title-chip (Fix (a) Phase 2b).
        No-op nếu thiếu cột."""
        ws = self._tab("CONTEXT")
        header = [h.strip().lower() for h in ws.row_values(1)]
        low = col_name.strip().lower()
        if low not in header:
            return
        col_letter = _col_a1(header.index(low) + 1)
        ws.update(f"{col_letter}{row}", [[value]], value_input_option="USER_ENTERED")

    def read_prompt_versions(self) -> dict[str, str]:
        """Đọc LIVE tab PROMPTS (Name|Version|Enable) -> {name: version} (chỉ hàng
        Enable bật). Rỗng/thiếu tab -> {} (agent dùng default nội bộ)."""
        try:
            rows = self._tab("PROMPTS").get_all_values()
        except Exception:  # pragma: no cover - tab chưa tồn tại
            return {}
        return prompt_versions_from_rows(rows)

    def read_taxonomy(self, *, default: list[TaxonomyRow] | None = None) -> list[TaxonomyRow]:
        """Đọc LIVE tab TAXONOMY (Field|Topic|Keywords) — gọi lại MỖI LẦN chạy để
        team đổi phân loại không cần sửa code/deploy lại. Rỗng/thiếu tab -> `default`."""
        try:
            rows = self._tab("TAXONOMY").get_all_values()
        except Exception:  # pragma: no cover - tab chưa tồn tại
            return list(default or [])
        return taxonomy_from_rows(rows) or list(default or [])

    def write_context(self, *, title: str, hook_line: str, url: str, score: int,
                      hot_pct: float = 0.0, topic: str = "", group: str = "",
                      other_sources: list[str] | None = None,
                      tickers: list[str] | None = None, topic_key: str = "") -> bool:
        """Ghi 1 dòng chờ duyệt (PENDING, Execute rỗng) vào tab CONTEXT.

        BỎ TRÙNG theo url (cột Source): nếu url đã có ở tab CONTEXT thì KHÔNG ghi
        lại — GIỮ NGUYÊN dòng cũ (Status/Execute/Hook/Notes...), idempotent
        across-run. Trả True nếu đã ghi, False nếu bỏ qua vì trùng. Ghi NHIỀU
        dòng 1 lượt -> dùng upsert_context_rows (rẻ hơn, 2 lệnh gọi thay vì N).
        `topic_key` (Lớp 5 Phase 1) — caller tự tính, rỗng nếu chưa wire."""
        ws = self._tab("CONTEXT")
        if url and url.strip() in self._context_urls(ws):
            return False
        ws.append_row(
            context_row(title=title, hook_line=hook_line, source_url=url, score=score,
                       hot_pct=hot_pct, topic=topic, group=group,
                       other_sources=other_sources, tickers=tickers, topic_key=topic_key),
            value_input_option="RAW",
        )
        return True

    def upsert_context_rows(self, rows: list[list[str]]) -> list[list[str]]:
        """UPSERT NHIỀU dòng vào CONTEXT theo TopicKey (Fix (a) — membership đọc
        cột TopicKey TRÊN SHEET, KHÔNG phải Source-URL literal-match cũ và
        KHÔNG phải corpus cục bộ), 1 lượt (2 lệnh gọi API):
          - TopicKey ĐÃ CÓ trên Sheet -> BỎ QUA HOÀN TOÀN, KHÔNG ghi cột nào
            (giữ nguyên TOÀN BỘ dòng cũ — Status/Execute/Hook/Notes/Hot%/Score...
            — chính sách đã chốt, xem PR "Fix (a)").
          - TopicKey CHƯA CÓ -> append.
        Lý do đổi từ Source-URL literal-match: 2 lượt crawl (vd 2 máy khác nhau,
        hoặc dữ liệu cũ trước khi convention "Source=URL" chuẩn hoá) có thể ghi
        Source-text KHÁC NHAU cho CÙNG 1 chủ đề (khác domain mirror, hoặc dòng
        cũ Source=tiêu đề thay vì URL) — literal-match BỎ SÓT, tạo dòng trùng dù
        TopicKey (hash URL canonical) giống hệt. `rows` phải ĐÚNG thứ tự
        CONTEXT_HEADER (dùng context_row, PHẢI có topic_key khác rỗng — xem
        curation.keys.assign_topic_key; topic_key rỗng KHÔNG BAO GIỜ coi là
        trùng dòng khác, kể cả dòng khác cũng rỗng -> luôn append, an toàn
        nghiêng về không mất dữ liệu). KHÔNG xoá/ghi đè dòng đã có (khác
        replace_context cũ đã bỏ). Trả CHÍNH CÁC DÒNG MỚI đã ghi (KHÔNG chỉ đếm
        số lượng — Phase 4.6: review_to_sheet.py cần Context/Source của từng
        dòng mới để bắn notify kèm link bài viết); `len(...)` thay cho số đếm
        cũ nếu chỉ cần đếm."""
        ws = self._tab("CONTEXT")
        existing_keys = self._context_topic_keys(ws)
        i_tk = [h.strip().lower() for h in CONTEXT_HEADER].index("topickey")

        def topic_key_of(row: list[str]) -> str:
            return row[i_tk].strip() if i_tk < len(row) else ""

        new_rows = [r for r in rows if not topic_key_of(r) or topic_key_of(r) not in existing_keys]
        if new_rows:
            ws.append_rows(new_rows, value_input_option="USER_ENTERED")
        return new_rows

    def sync_approve_execute_flags(self) -> int:
        """MỌI dòng CONTEXT có Status=APPROVE và Execute RỖNG -> tự đặt Execute=
        RUN (chuẩn bị cho produce_from_sheet.py xử lý). Dòng đã RUN/DONE giữ
        nguyên (idempotent, không đụng lại). Trả số dòng vừa đổi."""
        ws = self._tab("CONTEXT")
        rows = ws.get_all_values()
        if not rows:
            return 0
        header = [h.strip().lower() for h in rows[0]]
        if "status" not in header or "execute" not in header:
            return 0
        i_st, i_ex = header.index("status"), header.index("execute")

        to_set: list[int] = []   # số dòng 1-based (2..N) cần đặt RUN
        for row_i, r in enumerate(rows[1:], start=2):
            st = r[i_st].strip().upper() if i_st < len(r) else ""
            ex = r[i_ex].strip().upper() if i_ex < len(r) else ""
            if st == "APPROVE" and not ex:
                to_set.append(row_i)
        if not to_set:
            return 0
        col_letter = _col_a1(i_ex + 1)
        ws.batch_update([{"range": f"{col_letter}{r}", "values": [["RUN"]]} for r in to_set],
                        value_input_option="RAW")
        return len(to_set)

    def mark_execute_done(self, rows: list[int]) -> None:
        """Đặt Execute=DONE cho các dòng CONTEXT (số dòng 1-based trên Sheet, xem
        approved_context_from_rows()["row"]) VỪA sản xuất XONG (đủ nội dung, đã
        ghi CONTENT) — idempotent: lần chạy sau approved_context_from_rows lọc
        theo execute=='RUN' sẽ tự bỏ qua dòng đã DONE. No-op nếu `rows` rỗng."""
        self.set_execute_values({r: "DONE" for r in rows})

    def set_execute_values(self, status_by_row: dict[int, str]) -> None:
        """Ghi Execute cho NHIỀU dòng CONTEXT (số dòng 1-based), MỖI DÒNG 1 giá
        trị RIÊNG (Phase 4.9 — map WriterOutcome của bài ARTICLE vào Execute:
        DONE/FAILED/NEEDS_HUMAN có thể khác nhau giữa các dòng CÙNG 1 lượt chạy,
        khác mark_execute_done() chỉ ghi "DONE" đồng loạt — nay dùng chung hàm
        này bên dưới). No-op nếu `status_by_row` rỗng hoặc thiếu cột Execute."""
        if not status_by_row:
            return
        ws = self._tab("CONTEXT")
        header = [h.strip().lower() for h in ws.row_values(1)]
        if "execute" not in header:
            return
        col_letter = _col_a1(header.index("execute") + 1)
        ws.batch_update([{"range": f"{col_letter}{r}", "values": [[v]]}
                         for r, v in status_by_row.items()], value_input_option="RAW")

    def _context_urls(self, ws) -> set[str]:
        """Tập url đã có ở tab CONTEXT (ánh xạ theo tên cột 'source'; ô Source
        có thể gộp "<url>\\n(+N báo)\\n..." -> chỉ tính url ĐẦU/chính). Dùng bởi
        write_context() (đơn dòng) — upsert_context_rows() dùng
        _context_topic_keys() (Fix (a), xem docstring ở đó)."""
        rows = ws.get_all_values()
        if not rows:
            return set()
        header = [c.strip().lower() for c in rows[0]]
        if "source" not in header:
            return set()
        i = header.index("source")
        return {r[i].splitlines()[0].strip() for r in rows[1:] if i < len(r) and r[i].strip()}

    def _context_topic_keys(self, ws) -> set[str]:
        """Tập TopicKey đã có ở tab CONTEXT — membership đọc TRỰC TIẾP TỪ SHEET
        (Fix (a)), KHÔNG phải corpus cục bộ (file_store — corpus chỉ giữ vai
        trò evidence, xem curation/keys.py). Khoá rỗng KHÔNG được tính (không
        coi 2 dòng cùng thiếu khoá là "trùng nhau")."""
        rows = ws.get_all_values()
        if not rows:
            return set()
        header = [c.strip().lower() for c in rows[0]]
        if "topickey" not in header:
            return set()
        i = header.index("topickey")
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

    def log(self, level: str, message: str, *, engine: str = "") -> None:
        """Ghi 1 dòng nhật ký vào tab LOG. `engine` (tạm, vd haiku/sonnet/mock) để
        đối chiếu model nào thực sự chạy — rỗng nếu dòng log không gắn LLM."""
        self._tab("LOG").append_row(
            [_now_iso(), level.upper(), message, engine], value_input_option="RAW"
        )
