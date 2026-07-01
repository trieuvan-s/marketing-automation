"""Shared data contracts for the Turtle Wealth marketing pipeline.

Mọi giai đoạn trao đổi dữ liệu qua các dataclass tất định ở đây. Không giai
đoạn nào được "nói chuyện tự do" với giai đoạn khác — chỉ qua các contract này.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


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


@dataclass
class RawDocument:
    source: str
    url: str
    title: str
    markdown: str
    source_type: SourceType = SourceType.NEWS
    fetched_at: datetime = field(default_factory=_now)

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
    drafts: list[ContentDraft] = field(default_factory=list)
    published: list[PublishResult] = field(default_factory=list)
    cost: dict = field(default_factory=dict)   # báo cáo token/chi phí
    log: list[str] = field(default_factory=list)

    def note(self, msg: str) -> None:
        self.log.append(f"[{self.stage.value}] {msg}")
