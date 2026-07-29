"""TopicKey (Phase 5/Lớp 5 — "Ghi CONTENT neo theo KHOÁ chủ đề") — danh tính BỀN
của 1 chủ đề, KHÔNG phụ thuộc vị trí dòng trên Sheet (khác `(Context text, Type)`
hiện dùng ở `sheets_board.existing_content_keys()`, vốn trôi khi Sheet merge/
sort/insert/delete — xem CHỐT PHASE 0 bên dưới).

CHỐT PHASE 0 (đã duyệt): TopicKey = sha256(URL đã CHUẨN HOÁ), KHÔNG tái dùng
`curation.file_store._content_key()` (khoá đó hash NỘI DUNG title+markdown —
domain KHÁC, dùng để dedup document trong corpus, KHÔNG phải danh tính "chủ đề"
mà CONTEXT/CONTENT đang thao tác). URL-based ổn định hơn qua thời gian: nếu
publisher sửa bài (đổi vài chữ) sau khi đã APPROVE, content-hash sẽ đổi và phá
liên kết đã có, còn URL thường giữ nguyên. Cùng PHONG CÁCH hash (sha256, cắt
gọn) với `_content_key`/`RawDocument.content_hash` để nhất quán, nhưng là hàm
RIÊNG (input domain khác — không gọi lại được nguyên hàm cũ). HAI HỆ KHOÁ (corpus
content-hash vs Sheet canonical-URL) TÁCH BẠCH có chủ đích — KHÔNG có join giữa
2 hệ (xác nhận Phase 1R.0): cả 2 chỉ tính song song từ CÙNG 1 CleanDocument tại
1 điểm (review_to_sheet.py), không tra cứu chéo.

Phát hiện quan trọng (Phase 0, LỊCH SỬ — đã sửa ở Sheet UI cleanup Phase 1):
`SheetsBoard.regroup_and_merge_content()` (đã XOÁ, thay bằng `regroup_and_
band_content()`) từng dùng Sheets API `mergeCells` (MERGE_COLUMNS) cho cột
Context — API này XOÁ THẬT giá trị mọi ô bị merge trừ ô đầu tiên (không chỉ ẩn
hiển thị). Hệ quả: sau 1 lần merge, `existing_content_keys()` (so khớp theo
Context text) không còn thấy được các dòng video/infographic đã merge
-> mất idempotency, chính là cơ chế "content mồ côi". TopicKey PHẢI là cột
RIÊNG, không bao giờ bị mergeCells đụng tới — dữ liệu ghi MỚI từ Phase 1 không
còn dùng mergeCells nữa nên không còn phát sinh ca này, nhưng TopicKey vẫn là
neo danh tính đáng tin nhất cho dữ liệu CŨ còn sót lại.

PHASE 1R — SỬA ĐỊNH NGHĨA KHOÁ (canonical-URL, không còn bỏ-hết-query):
Phase 1 gốc `normalize_url()` bỏ TOÀN BỘ query-string — rủi ro va chạm thật cho
site dùng `?id=123` làm định danh bài (2 bài khác nhau cùng path, khác id, sẽ
RA CÙNG khoá — sai). Sửa: CHỈ bỏ tham số TRACKING theo denylist (config
`sheets.topic_key.tracking_params`), GIỮ mọi query khác + sort để ổn định thứ
tự. `compute_topic_key()` giờ trả `None` (KHÔNG còn title-hash fallback) khi
URL rỗng/không hợp lệ — caller (Phase 1R.2) tự gán surrogate `uuid4` MỘT LẦN
cho các dòng không có URL, KHÔNG suy diễn khoá từ tiêu đề (rủi ro va chạm cao
hơn UUID ngẫu nhiên, và 2 tin trùng tiêu đề vẫn là 2 tin khác nhau).

Resolve canonical/redirect (rel="canonical", URL cuối sau redirect) đặt ở TẦNG
COLLECTOR (`collectors/http_collector.py::HttpFirstCollector`, xem
`extract_canonical_url()` + `_fetch_and_extract()`) — KHÔNG phải ở đây.
`compute_topic_key()` VẪN LÀ HÀM THUẦN, không gọi mạng, không tự resolve gì —
chỉ nhận URL ĐÃ resolve sẵn từ caller.

PHASE 1R.2 — WRITE-ONCE + SURROGATE (thay dứt điểm khoá rỗng ""):
`assign_topic_key(existing_key, url=...)` là hàm caller PHẢI dùng thay vì gọi
thẳng `compute_topic_key()` khi xử lý 1 dòng CÓ THỂ đã có khoá từ trước:
  - `existing_key` khác rỗng -> TRẢ NGUYÊN, KHÔNG tính lại — đây là điểm neo
    BỀN thật sự (khác `compute_topic_key()`, hàm THUẦN luôn tính mới). Dù URL
    đổi/`normalize_url()` đổi hành vi ở version sau, khoá ĐÃ GHI XUỐNG SHEET
    KHÔNG BAO GIỜ trôi.
  - `existing_key` rỗng -> tính từ `url` (compute_topic_key); `url` rỗng/
    không hợp lệ -> gán SURROGATE `uuid4` ngẫu nhiên (tiền tố "sur-") — KHÔNG
    BAO GIỜ còn để lại khoá rỗng "" nữa (khác Phase 1 gốc, "" là trạng thái
    hợp lệ tạm thời chờ backfill). 2 dòng không-URL luôn ra 2 surrogate KHÁC
    NHAU (uuid4 ngẫu nhiên, không suy từ nội dung nên không va chạm).
  - Caller PHẢI GHI kết quả trả về XUỐNG Ô NGAY (persist) — lần gọi SAU
    truyền lại giá trị đã ghi thì write-once mới có hiệu lực thật (xem
    scripts/produce_from_sheet.py, SheetsBoard.set_topic_key_values()).

NGOẠI LỆ CÓ CHỦ Ý — RE-KEY MỘT LẦN (Phase 1R.2, xem sheets_board.
backfill_context_topic_keys(..., force=True)): vì khoá Phase 1 gốc tính bởi
`normalize_url()` phiên bản CŨ (bỏ HẾT query-string) có thể ĐÃ va chạm sai
(2 bài khác `?id=` ra cùng khoá), CHẠY ĐÚNG 1 LẦN 1 migration ghi ĐÈ mọi khoá
URL-based bằng `compute_topic_key()` MỚI (canonical, giữ query định danh) —
bypass write-once CÓ CHỦ ĐÍCH, chỉ dùng khi migrate. SAU migration này, mọi
đường gọi PHẢI quay lại `assign_topic_key()` (write-once mặc định) — xem
docs/CHANGELOG.md.
"""
from __future__ import annotations

import hashlib
import uuid
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse, urlunparse

_DEFAULT_KEY_LEN = 16   # cùng độ dài với curation.file_store._content_key (đủ ngắn để
                        # đọc trên Sheet, va chạm không đáng kể ở quy mô vài trăm nghìn
                        # chủ đề) — config-first qua sheets.topic_key.key_length, xem
                        # _key_length_from_settings(). CẢNH BÁO: đổi giá trị này SAU khi
                        # đã có khoá tính rồi sẽ làm MỌI khoá cũ KHÔNG khớp khoá mới tính
                        # (khác độ dài cắt) -> chỉ đổi khi CHƯA có dữ liệu, hoặc chấp nhận
                        # backfill lại toàn bộ.

# Tham số query CHẮC CHẮN là tracking (không định danh nội dung bài) -> BỎ khi
# chuẩn hoá. KHÔNG bỏ tham số khác (vd `?id=`, `?p=`) — nhiều site dùng query
# làm định danh THẬT, bỏ hết sẽ gây va chạm khoá giữa 2 bài khác nhau.
_DEFAULT_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "ref", "cmpid", "igshid", "mc_cid", "mc_eid",
})
_DEFAULT_PORTS = {"http": "80", "https": "443"}


def _key_length_from_settings() -> int:
    """Đọc sheets.topic_key.key_length nếu có settings.yaml — LÙI MƯỢT về
    _DEFAULT_KEY_LEN khi chưa cấu hình/lỗi (KHÔNG crash — hàm này chỉ ảnh hưởng
    default, caller vẫn truyền `key_length` thẳng để test/ghi đè). Import hoãn
    (..config) để keys.py không phụ thuộc vòng lúc import module curation."""
    try:
        from ..config import load_settings
        return int(load_settings().get("sheets.topic_key.key_length", _DEFAULT_KEY_LEN))
    except Exception:
        return _DEFAULT_KEY_LEN


def _tracking_params_from_settings() -> frozenset[str]:
    """Đọc sheets.topic_key.tracking_params nếu có settings.yaml (list chuỗi) —
    LÙI MƯỢT về _DEFAULT_TRACKING_PARAMS khi chưa cấu hình/lỗi/rỗng."""
    try:
        from ..config import load_settings
        raw = load_settings().get("sheets.topic_key.tracking_params")
        if raw:
            cleaned = frozenset(str(p).strip().lower() for p in raw if str(p).strip())
            if cleaned:
                return cleaned
    except Exception:
        pass
    return _DEFAULT_TRACKING_PARAMS


def _normalize_path(path: str) -> str:
    """Chuẩn hoá percent-encoding (decode rồi encode lại nhất quán) + bỏ dấu
    `/` cuối (trừ path rỗng/chỉ có `/`)."""
    decoded = unquote(path or "")
    encoded = quote(decoded, safe="/-._~")
    return encoded.rstrip("/") or ""


def _normalize_netloc(netloc: str) -> str:
    """Hạ thường, bỏ userinfo (hiếm), bỏ tiền tố `www.`, bỏ cổng MẶC ĐỊNH
    (80/443 — không phân biệt bởi cổng đó vốn ngầm định theo scheme). Cổng
    KHÁC 80/443 (hiếm, custom) được GIỮ (vẫn định danh site khác nhau thật)."""
    netloc = netloc.lower()
    if "@" in netloc:
        netloc = netloc.rsplit("@", 1)[1]
    host, sep, port = netloc.partition(":")
    if sep and port in _DEFAULT_PORTS.values():
        netloc = host
    return netloc.removeprefix("www.")


def normalize_url(url: str, *, tracking_params: frozenset[str] | None = None) -> str:
    """Chuẩn hoá URL CANONICAL — 2 biến thể CÙNG BÀI (khác tracking-param, khác
    hoa/thường host, có/không `www.`/dấu `/` cuối/scheme http-vs-https/percent-
    encoding) cho RA CÙNG khoá, nhưng GIỮ query ĐỊNH DANH THẬT (vd `?id=123`) để
    KHÔNG va chạm giữa 2 bài khác nhau:
      - Ép scheme "https" (http/https cùng site coi là 1 bài).
      - Hạ thường host, bỏ `www.`, bỏ cổng mặc định 80/443.
      - Chuẩn hoá percent-encoding + bỏ `/` cuối path.
      - Bỏ fragment (`#...`).
      - Query: CHỈ bỏ tham số trong `tracking_params` (mặc định đọc
        sheets.topic_key.tracking_params, xem _tracking_params_from_settings) —
        GIỮ mọi tham số khác, SẮP XẾP lại để `?b=2&a=1` == `?a=1&b=2`.
    URL rỗng/thiếu scheme hoặc host (không hợp lệ/tương đối) -> "" (không đủ
    dữ kiện, xem compute_topic_key). Hàm THUẦN — không mạng, không theo dõi
    redirect thật (redirect/canonical đã resolve ở tầng collector TRƯỚC khi
    gọi hàm này, xem module docstring)."""
    url = (url or "").strip()
    if not url:
        return ""
    p = urlparse(url)
    if not p.scheme or not p.netloc:
        return ""   # tương đối/không hợp lệ -> không đủ dữ kiện làm danh tính
    tp = tracking_params if tracking_params is not None else _tracking_params_from_settings()
    query_pairs = sorted(
        (k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() not in tp
    )
    return urlunparse((
        "https", _normalize_netloc(p.netloc), _normalize_path(p.path),
        "", urlencode(query_pairs), "",
    ))


def compute_topic_key(url: str, *, title: str | None = None,
                      key_length: int | None = None) -> str | None:
    """TopicKey ổn định cho 1 chủ đề — sha256(URL chuẩn hoá canonical), cắt còn
    `key_length` ký tự hex (mặc định đọc sheets.topic_key.key_length, lùi về
    16 — xem _key_length_from_settings). `url` rỗng/không hợp lệ (sau
    normalize_url) -> trả `None` (Phase 1R: KHÔNG còn lùi về title-hash — 2 tin
    trùng tiêu đề vẫn là 2 tin KHÁC NHAU, hash theo title tạo rủi ro va chạm
    thật). Caller PHẢI tự xử lý `None` — gán surrogate `uuid4` MỘT LẦN rồi ghi
    lại (write-once, xem Phase 1R.2), KHÔNG gọi lại hàm này để "thử lại ra
    khoá". `title` CHỈ để log/debug (KHÔNG dùng để tính hash)."""
    norm = normalize_url(url)
    if not norm:
        return None
    length = key_length if key_length is not None else _key_length_from_settings()
    return hashlib.sha256(f"url:{norm}".encode("utf-8")).hexdigest()[:length]


def assign_topic_key(existing_key: str, *, url: str = "",
                     key_length: int | None = None) -> str:
    """WRITE-ONCE (Phase 1R.2) — hàm caller nên dùng cho MỌI dòng có thể đã có
    khoá từ trước (thay vì gọi thẳng compute_topic_key). `existing_key` khác
    rỗng -> TRẢ NGUYÊN NGAY, KHÔNG chạm normalize_url/compute_topic_key —
    khoá đã ghi xuống Sheet là NEO BỀN, không tính lại dù `url` truyền vào là
    gì (kể cả khi trang đã đổi URL/canonical sau lần ghi đầu). `existing_key`
    rỗng -> tính từ `url` (compute_topic_key); không đủ dữ kiện (url rỗng/
    không hợp lệ) -> gán SURROGATE `uuid4` ngẫu nhiên (tiền tố "sur-") — KHÔNG
    BAO GIỜ trả về "" nữa. Caller PHẢI ghi kết quả xuống Sheet ngay (xem
    SheetsBoard.set_topic_key_values) để lần gọi SAU đọc lại đúng existing_key
    và write-once thật sự có hiệu lực."""
    existing = (existing_key or "").strip()
    if existing:
        return existing
    key = compute_topic_key(url, key_length=key_length)
    if key:
        return key
    length = key_length if key_length is not None else _key_length_from_settings()
    return f"sur-{uuid.uuid4().hex[:max(length, 8)]}"
