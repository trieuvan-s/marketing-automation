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
CONTEXT_HEADER = ["Timestamp", "Hot%", "Score", "Group", "Topic", "Context", "Hook",
                  "Source", "Status", "Execute", "tickers", "Notes"]
# "engine" TẠM (haiku|sonnet|mock) — đối chiếu model NÀO thực sự chạy cho mỗi
# dòng log, xem factory.model_engine_label(). Rỗng nếu dòng log không gắn LLM.
LOG_HEADER = ["timestamp", "level", "message", "engine"]
README_HEADER = ["Turtle Wealth — Bảng duyệt nội dung (Sheets là UI, thay được)"]
# CONTENT — SẢN PHẨM sinh SAU cổng 1 (giai đoạn Production): 1 dòng/(bài × định
# dạng). Timestamp ĐẦU TIÊN. Status = PENDING|RUNNING|DONE|ERROR (tất định, kết
# quả sản xuất — dropdown do format_board đặt). "Approve(gate 2)" = CỔNG DUYỆT
# NỘI DUNG (PENDING|APPROVE|REJECT, dropdown) — THAY cho tab ContentReview cũ
# (đã xoá); người duyệt chọn ngay trên dòng sản phẩm, không cần tab riêng.
CONTENT_HEADER = ["Timestamp", "Context", "Type", "Status", "Output", "Notes", "Approve(gate 2)"]

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
_MIGRATE_DEFAULTS: dict[str, dict[str, str]] = {
    "CONTEXT": {"Execute": ""},
    "CONTENT": {"Approve(gate 2)": "PENDING"},
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
                execute: str = "", ts: str | None = None) -> list[str]:
    """Một hàng CONTEXT ĐÚNG thứ tự CONTEXT_HEADER (Timestamp đầu tiên).

    Status mặc định PENDING, Execute mặc định rỗng (tự chuyển RUN khi Status=
    APPROVE — xem SheetsBoard.sync_approve_execute_flags). score/hot_pct do
    curation.enrich tính; Group/Topic từ classify (nhóm marketing). Source gộp
    url bài chính + các báo khác đưa cùng tin (dedup chéo nguồn, xem review_to_sheet).
    Publisher/Field KHÔNG ghi ra sheet (chỉ dùng nội bộ cho cluster/tiebreak).
    """
    return [
        ts or _now_iso(),                                 # Timestamp
        f"{hot_pct:.1f}",                                   # Hot%
        str(score),                                          # Score
        group,                                                # Group
        topic,                                                 # Topic
        title,                                                  # Context
        hook_line,                                               # Hook
        _source_cell(source_url, other_sources),                  # Source (gộp báo khác)
        status,                                                    # Status
        execute,                                                    # Execute
        ", ".join(tickers or []),                                   # tickers
        "",                                                          # Notes
    ]


def content_row(*, context: str, type_: str, status: str, output: str,
                notes: str = "", approve: str = "PENDING", ts: str | None = None) -> list[str]:
    """1 hàng CONTENT ĐÚNG thứ tự CONTENT_HEADER (Timestamp|Context|Type|Status|
    Output|Notes|Approve(gate 2)). Status: DONE (sạch)|ERROR (lỗi/compliance) —
    kết quả sản xuất, tất định. Approve(gate 2): cổng NGƯỜI duyệt nội dung
    (PENDING mặc định, thay tab ContentReview cũ)."""
    return [ts or _now_iso(), context, type_, status, output, notes, approve]


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


def content_merge_ranges(header: list[str], rows: list[list[str]]) -> list[tuple[int, int]]:
    """`rows` PHẢI đã regroup (regroup_content_rows) trước — hàm này chỉ tìm dải,
    KHÔNG tự sắp lại. Trả list (start, end) 0-based/end-exclusive TÍNH THEO SHEET
    (offset +1 vì hàng 1 là header) — mỗi dải là 1 Context có ĐỦ CẢ 3 loại
    (_FULL_TYPES: article/video_script/infographic) nằm ở các hàng LIÊN TIẾP.
    Context thiếu loại hoặc hàng không liền kề (chưa regroup) -> KHÔNG merge."""
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
        if _FULL_TYPES <= types_seen:
            ranges.append((i + 1, j + 1))
        i = j
    return ranges


def approved_context_from_rows(rows: list[list[str]]) -> list[dict]:
    """Các dòng CONTEXT có Status=APPROVE -> list dict (ánh xạ theo TÊN cột):
    context (tiêu đề), hook, source (url chính), tickers, group, topic, execute
    (RUN/DONE/rỗng), row (số dòng 1-based TRÊN SHEET — dùng để ghi lại
    Execute=DONE sau khi sản xuất xong, xem SheetsBoard.mark_execute_done)."""
    if not rows:
        return []
    header = [c.strip().lower() for c in rows[0]]

    def idx(name: str) -> int | None:
        return header.index(name) if name in header else None

    i_ctx, i_hook, i_src = idx("context"), idx("hook"), idx("source")
    i_tk, i_grp, i_tp, i_st = idx("tickers"), idx("group"), idx("topic"), idx("status")
    i_ex = idx("execute")
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
                    "execute": cell(row, i_ex).upper(), "row": row_i})
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
        out.append(_set_validation(sid, 1, fmt_rows, c, _one_of_list(["RUN", "DONE"])))
    if t.name == "CONTENT" and "status" in low:  # -> dropdown (kết quả sản xuất, tất định)
        c = low.index("status")
        out.append(_set_validation(sid, 1, fmt_rows, c,
                                   _one_of_list(["PENDING", "RUNNING", "DONE", "ERROR"])))
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
        """(Context, Type) đã có trong CONTENT — bỏ qua sản phẩm đã sinh để KHỎI
        tốn Sonnet lại (dedup across-run)."""
        try:
            rows = self._tab("CONTENT").get_all_values()
        except Exception:  # pragma: no cover - tab chưa tồn tại
            return set()
        if not rows:
            return set()
        header = [c.strip().lower() for c in rows[0]]
        if "context" not in header or "type" not in header:
            return set()
        ic, it = header.index("context"), header.index("type")
        keys: set[tuple[str, str]] = set()
        for r in rows[1:]:
            if ic < len(r) and it < len(r) and r[ic].strip():
                keys.add((r[ic].strip(), r[it].strip()))
        return keys

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
        cột Timestamp+Context cho các chủ đề đã ĐỦ 3 loại article/video_script/
        infographic (content_merge_ranges). Idempotent: unmerge TOÀN vùng dữ
        liệu trước khi merge lại nên gọi nhiều lần không lỗi/không merge chồng.
        Trả số dải đã merge (0 -> không đổi gì, kể cả khi tab rỗng/thiếu cột)."""
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
                      tickers: list[str] | None = None) -> bool:
        """Ghi 1 dòng chờ duyệt (PENDING, Execute rỗng) vào tab CONTEXT.

        BỎ TRÙNG theo url (cột Source): nếu url đã có ở tab CONTEXT thì KHÔNG ghi
        lại — GIỮ NGUYÊN dòng cũ (Status/Execute/Hook/Notes...), idempotent
        across-run. Trả True nếu đã ghi, False nếu bỏ qua vì trùng. Ghi NHIỀU
        dòng 1 lượt -> dùng upsert_context_rows (rẻ hơn, 2 lệnh gọi thay vì N)."""
        ws = self._tab("CONTEXT")
        if url and url.strip() in self._context_urls(ws):
            return False
        ws.append_row(
            context_row(title=title, hook_line=hook_line, source_url=url, score=score,
                       hot_pct=hot_pct, topic=topic, group=group,
                       other_sources=other_sources, tickers=tickers),
            value_input_option="RAW",
        )
        return True

    def upsert_context_rows(self, rows: list[list[str]]) -> int:
        """UPSERT NHIỀU dòng vào CONTEXT theo url (cột Source), 1 lượt (2 lệnh
        gọi API): url ĐÃ CÓ -> BỎ QUA HOÀN TOÀN (giữ nguyên dòng cũ — Status/
        Execute/Hook/Notes... không đổi); url CHƯA CÓ -> append. KHÔNG xoá/ghi
        đè dòng đã có (khác replace_context cũ đã bỏ). `rows` phải ĐÚNG thứ tự
        CONTEXT_HEADER (dùng context_row). Trả số dòng MỚI đã ghi."""
        ws = self._tab("CONTEXT")
        existing_urls = self._context_urls(ws)
        i_src = [h.strip().lower() for h in CONTEXT_HEADER].index("source")

        def primary_url(row: list[str]) -> str:
            # ô Source có thể gộp "<url>\n(+N báo)\n<url2>..." -> url ĐẦU là chính.
            return row[i_src].splitlines()[0].strip() if i_src < len(row) else ""

        new_rows = [r for r in rows if primary_url(r) and primary_url(r) not in existing_urls]
        if new_rows:
            ws.append_rows(new_rows, value_input_option="USER_ENTERED")
        return len(new_rows)

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
        if not rows:
            return
        ws = self._tab("CONTEXT")
        header = [h.strip().lower() for h in ws.row_values(1)]
        if "execute" not in header:
            return
        col_letter = _col_a1(header.index("execute") + 1)
        ws.batch_update([{"range": f"{col_letter}{r}", "values": [["DONE"]]} for r in rows],
                        value_input_option="RAW")

    def _context_urls(self, ws) -> set[str]:
        """Tập url đã có ở tab CONTEXT (ánh xạ theo tên cột 'source'; ô Source
        có thể gộp "<url>\\n(+N báo)\\n..." -> chỉ tính url ĐẦU/chính)."""
        rows = ws.get_all_values()
        if not rows:
            return set()
        header = [c.strip().lower() for c in rows[0]]
        if "source" not in header:
            return set()
        i = header.index("source")
        return {r[i].splitlines()[0].strip() for r in rows[1:] if i < len(r) and r[i].strip()}

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
