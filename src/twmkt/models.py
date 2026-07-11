"""Shared data contracts for the Turtle Wealth marketing pipeline.

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
    VIDEO_SCRIPT = "video_script"
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


@dataclass
class Fact:
    """1 số liệu/tuyên bố định lượng đã trích + gắn NHÃN NGHĨA từ evidence thô —
    sinh bởi bước Research/Brief (agents/brief.py, model alias 'brief' = Haiku,
    xem factory.make_llm/step_model). THAY THẾ nhãn vô nghĩa "Số liệu N" của
    InfographicSpecAgent cũ (regex mù trên text thô).

    KHÔNG hợp nhất với ResearchBrief (đường Hook/Luồng B RAG giữ nguyên, không
    đụng) — Fact/facts[] CHỈ dùng cho ProductionBrief (agents/production.py).

    Ràng buộc chống bịa: mỗi Fact PHẢI verify được — `value` xuất hiện NGUYÊN
    VĂN trong `source` (1 câu evidence thật). Fact nào không verify được bị loại
    ngay ở agents/brief.facts_from_llm_output(), KHÔNG bao giờ tồn tại instance
    Fact "bịa".

    PHASE 4.8 MỤC C — SỐ CANONICAL: nguyên tắc "AI hiểu ở Brief, CODE phán ở
    Guardrail" — sự giòn với NGÔN NGỮ số ("gần 600 tỷ"/"585 tỉ"/"585 tỷ đồng"
    cùng 1 số thật) được xử ở khâu TRÍCH (agents/brief.py, AI nhận diện biến
    thể cách viết); guardrail (agents/production.unsupported_numbers) chỉ làm
    PHÉP TÍNH SỐ HỌC TẤT ĐỊNH trên `canonical_value` — KHÔNG BAO GIỜ để AI làm
    quan toà phán 1 số là an toàn.
    """
    value: str            # "8,18", "8", "1.200" — nguyên văn số trong evidence (KHÔNG kèm unit)
    label: str             # "GDP 6T/2026", "LNTT MB" — nhãn CÓ NGHĨA, không phải "Số liệu N"
    unit: str | None = None    # "%", "tỷ đồng"... None nếu value không đi kèm đơn vị (vd đếm)
    source: str = ""       # câu evidence gốc chứa value (audit/verify)
    kind: str = "other"    # xem FACT_KINDS — percent|money|count|growth|date|ranking|target|other
    raw: str = ""                          # cụm NGUYÊN VĂN (value+unit, kể cả từ xấp xỉ nếu có) —
                                            # PHẢI là substring THẬT của evidence+background, xem
                                            # agents/brief.facts_from_llm_output (không thì LOẠI fact)
    canonical_value: float | None = None   # số máy đọc được, CODE tính từ value+unit (agents/
                                            # _numeric.parse_magnitude_token) — vd "585 tỷ" -> 585e9
    approx: bool = False                   # true nếu raw có từ xấp xỉ (gần/khoảng/xấp xỉ/hơn/
                                            # trên/dưới) — agents/_numeric.has_approx_word


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
