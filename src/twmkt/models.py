"""Shared data contracts for the marketing automation pipeline (brand identity
lives in config/brand.yaml, MỘT NGUỒN — KHÔNG hard-code brand ở docstring này).

Mọi giai đoạn trao đổi dữ liệu qua các dataclass tất định ở đây. Không giai
đoạn nào được "nói chuyện tự do" với giai đoạn khác — chỉ qua các contract này.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # tránh vòng import (agents import models)
    from .agents.hook import MarketingHook


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SourceType(str, Enum):
    NEWS = "news"            # CafeF, Vietstock, NDH...
    DISCLOSURE = "disclosure"  # Công bố thông tin HOSE/HNX
    IR = "ir"               # Trang quan hệ NĐT của doanh nghiệp
    OTHER = "other"


class ContentFormat(str, Enum):
    ARTICLE = "article"
    INFOGRAPHIC = "infographic"   # sinh ra SPEC (JSON), không phải ảnh
    # SỬA 2026-07-19/20 (BUG 2, phát hiện độc lập qua store/backfill_from_sheet.py
    # --dry-run TRÊN Sheet thật, xác nhận lại qua C7): giá trị CŨ "video_script"
    # KHÔNG khớp dữ liệu Type thật trên CONTENT (Sheet ghi "video", xác nhận qua
    # đọc trực tiếp 9 dòng CONTENT production) -- Sheet là nguồn sự thật ở giai
    # đoạn backfill, sửa ENUM theo Sheet, KHÔNG sửa Sheet. Tên member giữ
    # `VIDEO_SCRIPT` (định danh Python), chỉ .value đổi.
    VIDEO_SCRIPT = "video"
    NEWSLETTER = "newsletter"


class Stage(str, Enum):
    COLLECTED = "collected"
    CURATED = "curated"
    RESEARCHED = "researched"
    APPROVED_RESEARCH = "approved_research"
    PRODUCED = "produced"
    APPROVED_CONTENT = "approved_content"
    PUBLISHED = "published"
    REJECTED = "rejected"


class Decision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    REVISE = "revise"


@dataclass
class Source:
    name: str
    url: str
    source_type: SourceType = SourceType.NEWS
    # --- Mô hình thu thập 3 lớp (SOURCES sheet: Enable|Publisher|FeedURL|Type|
    # Field|Interval|Priority) — mặc định giữ hành vi cũ (html) cho code hiện có. ---
    fetch_type: str = "html"        # "rss" (tầng 1: phát hiện nhẹ) | "html" (full ngay)
    field_hint: str = ""            # gợi ý Field (taxonomy) do user khai ở SOURCES.Field
    interval_minutes: int = 0       # 0 = dùng lịch mặc định (schedule.*); >0 = ghi đè riêng nguồn
    priority: int = 0               # số lớn hơn = ưu tiên xử lý trước (SOURCES.Priority)


@dataclass
class RawDocument:
    source: str
    url: str
    title: str
    markdown: str
    source_type: SourceType = SourceType.NEWS
    fetched_at: datetime = field(default_factory=_now)
    category_hint: str = ""   # gợi ý Field từ <category> RSS (rss_collector) — rỗng nếu nguồn html
    # LỚP 5 Phase 1R (bổ sung Phương án 1) — `url` LUÔN là URL THẬT đã fetch
    # (sau redirect, KHÔNG BAO GIỜ bị ghi đè bởi canonical — giữ nguyên nguồn
    # gốc để audit/tái fetch). `canonical_url` = <link rel="canonical"> đã
    # KIỂM ĐỊNH (cùng host, không trỏ root/prefix — xem collectors/
    # http_collector.extract_canonical_url), "" nếu không có/không qua kiểm
    # định. Nơi cần danh tính bài (vd TopicKey) tự chọn `canonical_url or url`.
    canonical_url: str = ""

    @property
    def content_hash(self) -> str:
        """Hash nội dung để dedup (bỏ qua khoảng trắng thừa)."""
        norm = " ".join(self.markdown.split()).lower()
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()


@dataclass
class CleanDocument:
    source: str
    url: str
    title: str
    markdown: str
    tickers: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    source_type: SourceType = SourceType.NEWS
    fetched_at: datetime = field(default_factory=_now)
    category_hint: str = ""   # kế thừa từ RawDocument.category_hint (xem curation/normalize.py)
    canonical_url: str = ""   # kế thừa từ RawDocument.canonical_url (xem RawDocument docstring)


@dataclass
class ResearchBrief:
    """Sản phẩm của Researcher: luận điểm + bằng chứng trích từ RAG.

    `evidence` là các đoạn (chunk) liên quan truy hồi từ Knowledge Layer trên
    dữ liệu crawl. `thesis`/`key_points` do LLM diễn giải NHƯNG phải bám vào
    evidence. (Về sau có thể thay bằng brief từ service Research độc lập.)
    """
    topic: str
    tickers: list[str]
    thesis: str
    key_points: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)   # chunk truy hồi từ RAG
    sources: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=_now)


# "Infographic-worthy" = MỌI tuyên bố định lượng hoặc mốc có tên đáng lên hình,
# KHÔNG chỉ %/tiền (xem agents/brief.py _SYSTEM). Phase 5 dùng `kind` để chọn
# template hiển thị (percent -> vòng tròn %, ranking -> huy hiệu, date -> mốc
# thời gian trên trục...). "other" = không khớp nhóm nào ở trên (LÙI MƯỢT, vẫn
# giữ fact — không loại chỉ vì kind lạ).
FACT_KINDS = ("percent", "money", "count", "growth", "date", "ranking", "target", "other")

# Content Factory Phase 1 (chặn gốc (b) — "Fact schema không chứa nổi khoảng/
# biến thiên/danh sách thực thể"). CẤU TRÚC dữ liệu 1 Fact — KHÁC `kind` ở trên
# (đó là DANH MỤC ngữ nghĩa percent/money/...; `shape` là HÌNH DẠNG dữ liệu).
# ĐẶT TÊN "shape" thay vì tái dùng chữ "kind" từ yêu cầu gốc — CỐ Ý: `Fact.kind`
# đã mang nghĩa khác (percent|money|...) từ trước, dùng khắp Brief prompt/
# guardrail/280+ test hiện có — tái dùng "kind" cho nghĩa MỚI sẽ đụng độ, đổi
# nghĩa field cũ âm thầm. `shape` mặc định "scalar" -> dữ liệu Fact cũ (không
# field này trong JSON) tự hiểu là scalar, tương thích ngược 100% — xem
# facts_from_json (sheets_board.py) và test_fact_scalar_shape_backward_compat.
FACT_SHAPES = ("scalar", "range", "delta", "entity_list", "entity")


@dataclass
class Fact:
    """1 dữ kiện đã trích + gắn NHÃN NGHĨA từ evidence thô — sinh bởi bước
    Research/Brief (agents/brief.py, model alias 'brief' = Haiku, xem factory.
    make_llm/step_model). THAY THẾ nhãn vô nghĩa "Số liệu N" của
    InfographicSpecAgent cũ (regex mù trên text thô).

    KHÔNG hợp nhất với ResearchBrief (đường Hook/Luồng B RAG giữ nguyên, không
    đụng) — Fact/facts[] CHỈ dùng cho ProductionBrief (agents/production.py).

    Content Factory Phase 1 — 1 DATACLASS PHẲNG cho CẢ 5 `shape` (KHÔNG phải
    Union kiểu-riêng-từng-shape/isinstance dispatch) — CỐ Ý: giữ nguyên phong
    cách flat-dataclass + `dataclasses.asdict()`/`Fact(**item)` round-trip JSON
    (facts_to_json/facts_from_json, sheets_board.py) đã dùng khắp codebase,
    tránh 1 đợt refactor lớn/rủi ro chỉ để đổi hình dạng union. Field nào không
    áp dụng cho `shape` hiện tại thì để rỗng/None — xem "field theo shape" dưới.

    Ràng buộc chống bịa (MỌI shape): mỗi Fact PHẢI verify được — value chính
    (value/value_low+value_high/from_value+to_value/entities[]/value tuỳ shape)
    xuất hiện NGUYÊN VĂN trong `source`. Fact nào không verify được bị loại
    ngay ở agents/brief.facts_from_llm_output(), KHÔNG bao giờ tồn tại instance
    Fact "bịa".

    PHASE 4.8 MỤC C — SỐ CANONICAL: nguyên tắc "AI hiểu ở Brief, CODE phán ở
    Guardrail" — sự giòn với NGÔN NGỮ số ("gần 600 tỷ"/"585 tỉ"/"585 tỷ đồng"
    cùng 1 số thật) được xử ở khâu TRÍCH (agents/brief.py, AI nhận diện biến
    thể cách viết); guardrail (agents/production.unsupported_numbers,
    media_factory/spec.verify_spec) chỉ làm PHÉP TÍNH SỐ HỌC TẤT ĐỊNH trên các
    trường canonical_* — KHÔNG BAO GIỜ để AI làm quan toà phán 1 số là an toàn.
    Cùng nguyên tắc áp cho `shape="entity"/"entity_list"` — TÊN xuất hiện ở
    Composer/Writer PHẢI khớp `value`/1 phần tử `entities[]` nào đó, tên lạ =
    BỊA (nguy hiểm ngang bịa số, xem media_factory/spec.py).
    """
    value: str             # scalar: "8,18"/"8"/"1.200" (nguyên văn số, KHÔNG kèm unit).
                            # entity: TÊN thực thể đơn ("SHS", "Nghị quyết 57", "Rottanak Keo").
                            # range/delta/entity_list: RỖNG — dùng field riêng bên dưới.
    label: str              # "GDP 6T/2026", "LNTT MB" — nhãn CÓ NGHĨA, không phải "Số liệu N"
    unit: str | None = None    # "%", "tỷ đồng"... None nếu value không đi kèm đơn vị (vd đếm)
    source: str = ""       # CÂU NGUYÊN VĂN trong bài chứa dữ kiện (audit/verify) — ĐÂY LÀ
                            # "source_sentence" bắt buộc theo Content Factory Phase 1, KHÔNG
                            # thêm field trùng tên — mọi shape đều BẮT BUỘC field này khác rỗng
                            # (enforce ở agents/brief.facts_from_llm_output, không phải ở đây).
    kind: str = "other"    # DANH MỤC ngữ nghĩa — xem FACT_KINDS (percent|money|count|growth|
                            # date|ranking|target|other). KHÔNG đổi nghĩa Phase 1 — xem "shape"
                            # bên dưới cho HÌNH DẠNG dữ liệu (scalar|range|delta|entity_list|entity).
    shape: str = "scalar"   # Content Factory Phase 1 — xem FACT_SHAPES + docstring module.
    raw: str = ""                          # cụm NGUYÊN VĂN (value+unit, kể cả từ xấp xỉ nếu có) —
                                            # PHẢI là substring THẬT của evidence+background, xem
                                            # agents/brief.facts_from_llm_output (không thì LOẠI fact)
    canonical_value: float | None = None   # scalar: số máy đọc được, CODE tính từ value+unit
                                            # (agents/_numeric.parse_magnitude_token) — vd "585 tỷ" -> 585e9
    approx: bool = False                   # true nếu raw có từ xấp xỉ (gần/khoảng/xấp xỉ/hơn/
                                            # trên/dưới) — agents/_numeric.has_approx_word

    # --- field CHỈ dùng khi shape="range" (vd "1.396 – 1.656 triệu tấn") ---
    value_low: str = ""
    value_high: str = ""
    canonical_low: float | None = None
    canonical_high: float | None = None

    # --- field CHỈ dùng khi shape="delta" (vd "giảm từ 36 xuống 23 cảng",
    # hoặc chuyển trạng thái KHÔNG PHẢI số — "từ diện kiểm soát sang cảnh báo") ---
    from_value: str = ""
    to_value: str = ""
    canonical_from: float | None = None    # None nếu from_value không phải số (vd tên trạng thái)
    canonical_to: float | None = None      # None nếu to_value không phải số

    # --- field CHỈ dùng khi shape="entity_list" (TẬP HỢP có tính TRỌN VẸN —
    # vd "4 cảng: Thanh Hóa, Đà Nẵng, Khánh Hòa, Cần Thơ"; guardrail: thành
    # viên phải nằm trong tập, thêm thành viên lạ = BỊA, xem media_factory/spec.py) ---
    entities: list[str] = field(default_factory=list)

    # --- field CHỈ dùng khi shape="entity" (1 thực thể ĐƠN có tên, KHÔNG hàm ý
    # tập hợp — vd mã CK/công ty/chính sách/địa danh/dự án/người đơn lẻ) ---
    entity_type: str = ""  # ticker | company | policy | place | person | project | other —
                            # nguồn giá trị hợp lệ từ config (KHÔNG hard-code, xem Phase 2/
                            # config/settings.yaml), quyết định Composer/renderer hiển thị ra
                            # sao (mã CK -> badge, chính sách -> nhãn, địa danh -> điểm trên
                            # bản đồ...).

    # --- field CHỈ dùng khi shape="entity"/"entity_list" (Content Factory
    # Phase 2b — "vét cạn nhưng không phân biệt chủ thể với phông nền": bài
    # cảng biển thật cho thấy related/priority.primary bị lấp đầy bởi TÊN HỘI
    # THẢO/HIỆP HỘI/VIỆN NGHIÊN CỨU (phông nền — nguồn phát ngôn/bối cảnh sự
    # kiện) thay vì tên CẢNG/DỰ ÁN THẬT (chủ thể tin) — guardrail lần 2 KHÔNG
    # sai (không tên nào bịa), nhưng Composer không có cách phân biệt "thứ bài
    # nói VỀ" khỏi "nơi/ai nói ra nó") ---
    salience: str = ""     # "subject" (chủ thể — cảng/mã CK/công ty/dự án LÀ trọng tâm
                            # bài) | "context" (phông nền — hội thảo/cơ quan/người phát
                            # biểu/hiệp hội/viện nghiên cứu). Giá trị hợp lệ từ config
                            # (guardrail.entity_salience, KHÔNG hard-code, xem agents/
                            # brief.py). "" (rỗng) = dữ liệu CŨ trước Phase 2b, KHÔNG có
                            # salience — media_factory/spec.py coi TƯƠNG ĐƯƠNG "subject"
                            # khi ĐỐI CHIẾU tên hợp lệ (tương thích ngược, không bịa flag
                            # cho dữ liệu cũ), nhưng KHÔNG được Composer/fallback CHỌN
                            # vào related/priority.primary cho luồng MỚI (chỉ "subject"
                            # tường minh mới được chọn — xem agents/production.
                            # _entity_names_from_facts).


@dataclass
class ContentDraft:
    fmt: ContentFormat
    title: str
    body: str                      # bài viết / kịch bản; với infographic là JSON spec
    brief_topic: str = ""
    compliance_issues: list[str] = field(default_factory=list)
    approved: bool = False
    created_at: datetime = field(default_factory=_now)

    @property
    def is_clean(self) -> bool:
        return len(self.compliance_issues) == 0


@dataclass
class PublishResult:
    platform: str
    fmt: ContentFormat
    ok: bool
    ref: str = ""        # post id / url / lý do lỗi
    at: datetime = field(default_factory=_now)


@dataclass
class PipelineState:
    """Trạng thái chảy qua toàn bộ graph. LangGraph sẽ map 1-1 với cái này."""
    topic: str
    stage: Stage = Stage.COLLECTED
    raw_docs: list[RawDocument] = field(default_factory=list)
    clean_docs: list[CleanDocument] = field(default_factory=list)
    brief: ResearchBrief | None = None
    hook: "MarketingHook | None" = None       # góc marketing (sau research, trước cổng 1)
    drafts: list[ContentDraft] = field(default_factory=list)
    published: list[PublishResult] = field(default_factory=list)
    cost: dict = field(default_factory=dict)   # báo cáo token/chi phí
    log: list[str] = field(default_factory=list)

    def note(self, msg: str) -> None:
        self.log.append(f"[{self.stage.value}] {msg}")
