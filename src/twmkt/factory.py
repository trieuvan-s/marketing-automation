"""Lắp ráp thành phần từ settings — điểm hội tụ của nguyên tắc config-first.

Mọi lựa chọn adapter (LLM mock/anthropic, cổng console/auto/sheets, embedder,
collector, nguồn crawl) được quyết ở đây dựa trên config/settings.yaml, LÕI
(orchestrator + agents) không cần biết. Thêm nhà cung cấp = thêm nhánh ở đây.

Không gọi mạng / không gọi LLM khi chỉ *dựng* pipeline: các client đắt tiền
(AnthropicLLM, Crawl4aiCollector, SheetsApprovalGate) đều import/kết nối lazy.
"""
from __future__ import annotations

from .agents.base import AnthropicLLM, LLMClient, MockLLM
from .agents.router import LLMRouter, Tier
from .approval import sheets_gate
from .approval.gate import ApprovalGate, AutoApproveGate, ConsoleApprovalGate
from .collectors.base import Collector
from .collectors.crawl4ai_collector import Crawl4aiCollector
from .collectors.http_collector import HttpFirstCollector
from .collectors.mock import MockCollector
from .collectors.rss_collector import RssCollector
from .config import Settings, load_settings
from .curation.config import CurationConfig
from .curation.store import DocumentStore, InMemoryStore
from .curation.file_store import FileDocumentStore
from .knowledge.rag import Retriever
from .models import Source, SourceType
from .orchestrator import MarketingPipeline, PipelineConfig
from .publishers.base import ConsolePublisher, Publisher


# --- LLM: chọn theo llm.provider -------------------------------------------
def build_llm(settings: Settings) -> LLMClient:
    return _build_llm(settings, model_key="llm.content_model",
                      default_model="claude-sonnet-4-6")


def build_hook_llm(settings: Settings) -> LLMClient:
    """LLM cho HookAgent — dùng tầng rẻ (llm.triage_model)."""
    return _build_llm(settings, model_key="llm.triage_model",
                      default_model="claude-haiku-4-5-20251001")


def _build_llm(settings: Settings, *, model_key: str, default_model: str) -> LLMClient:
    provider = (settings.get("llm.provider", "mock") or "mock").lower()
    if provider == "mock":
        return MockLLM()
    if provider == "anthropic":
        return AnthropicLLM(
            model=settings.get(model_key, default_model),
            max_tokens=int(settings.get("llm.max_tokens", 1500)),
        )
    raise ValueError(f"llm.provider không hỗ trợ: {provider} (mock|anthropic)")


def build_research_llm(settings: Settings, *, offline: bool = False) -> LLMRouter:
    """LLM cho Researcher + Hook, BỌC LLMRouter để đo token + ước tính chi phí.

    - offline=True hoặc provider=mock -> MockLLM ($0 token, không mạng/không khóa).
    - provider=anthropic -> tầng RẺ (triage_model = Haiku) để nếm chất lượng + đo
      token trước khi bật tầng đắt. Không gọi mạng khi *dựng* (SDK/khóa lazy).
    Router dùng tier CHEAP để định giá và áp `llm.budget_usd` (hạn mức mềm)."""
    base: LLMClient = MockLLM() if offline else build_hook_llm(settings)
    budget = settings.get("llm.budget_usd")
    return LLMRouter(
        base,
        default_tier=Tier.CHEAP,
        budget_usd=float(budget) if budget else None,
    )


# --- Cổng duyệt: console | auto | sheets -----------------------------------
def build_gate(settings: Settings, *, gate: str) -> ApprovalGate:
    """gate = 'research' | 'content'. Đọc gates.<gate>.type."""
    kind = (settings.get(f"gates.{gate}.type", "console") or "console").lower()
    if kind == "console":
        return ConsoleApprovalGate()
    if kind == "auto":
        return AutoApproveGate()
    if kind == "sheets":
        return sheets_gate.from_settings(settings, gate=gate)
    raise ValueError(f"gates.{gate}.type không hỗ trợ: {kind} (console|auto|sheets)")


# --- Nguồn crawl từ settings.sources (enabled) ------------------------------
def build_sources(settings: Settings) -> list[Source]:
    """Dựng list[Source] từ settings.sources (mục `enabled: true`). Đọc thêm
    fetch_type/field/interval_minutes/priority (mô hình 3 lớp thu thập) — khớp
    các trường sheets_board.sources_from_rows đọc từ SOURCES sheet. Kết quả sắp
    theo priority GIẢM DẦN (ưu tiên cao xử lý trước)."""
    out: list[Source] = []
    for s in settings.enabled_sources():
        try:
            st = SourceType(s.get("type", "news"))
        except ValueError:
            st = SourceType.OTHER
        fetch_type = (s.get("fetch_type") or "html").lower()
        if fetch_type not in ("rss", "html"):
            fetch_type = "html"
        out.append(Source(
            name=s.get("name") or s.get("key", ""),
            url=s.get("url", ""),
            source_type=st,
            fetch_type=fetch_type,
            field_hint=s.get("field", "") or "",
            interval_minutes=int(s.get("interval_minutes", 0) or 0),
            priority=int(s.get("priority", 0) or 0),
        ))
    out.sort(key=lambda src: src.priority, reverse=True)
    return out


# --- Collector: mock (offline) | http (mặc định) | crawl4ai (fallback JS) ---
def build_collector(settings: Settings, *, offline: bool = True) -> Collector:
    """offline=True -> MockCollector ($0, không mạng). Ngược lại chọn engine thật
    theo crawl.engine: 'http' = HttpFirstCollector (httpx+bs4, $0 token);
    'crawl4ai' = Crawl4aiCollector (fallback cho nguồn cần JS)."""
    if offline:
        return MockCollector()
    engine = (settings.get("crawl.engine", "http") or "http").lower()
    if engine == "http":
        return HttpFirstCollector.from_settings(settings)
    if engine == "crawl4ai":
        return Crawl4aiCollector.from_settings(settings)
    raise ValueError(f"crawl.engine không hỗ trợ: {engine} (http|crawl4ai)")


def build_collector_for_source(source: Source, settings: Settings, *,
                               html_collector: HttpFirstCollector | None = None,
                               rss_collector: RssCollector | None = None) -> Collector:
    """Chọn collector THEO TỪNG NGUỒN (mô hình 3 lớp thu thập): Source.fetch_type
    'rss' -> RssCollector (tầng 1: phát hiện nhẹ); 'html' -> HttpFirstCollector
    (full ngay). Khác `build_collector` (MỘT collector chung cho cả pipeline,
    dùng bởi run_pipeline.py) — hàm này phục vụ review_to_sheet.py, nơi SOURCES
    trộn cả nguồn rss lẫn html trong CÙNG 1 lượt chạy.

    Truyền `html_collector`/`rss_collector` đã dựng sẵn để TÁI DÙNG 1 instance
    cho nhiều nguồn (tránh dựng lại mỗi nguồn); không truyền -> tự dựng theo
    settings (vẫn không gọi mạng lúc dựng)."""
    if source.fetch_type == "rss":
        return rss_collector or RssCollector.from_settings(settings)
    return html_collector or HttpFirstCollector.from_settings(settings)


def build_retriever(settings: Settings) -> Retriever:
    return Retriever.from_settings(settings)


def build_store(settings: Settings) -> DocumentStore:
    """storage.type = file -> FileDocumentStore (persist); mặc định memory."""
    kind = (settings.get("storage.type", "memory") or "memory").lower()
    if kind == "memory":
        return InMemoryStore()
    if kind == "file":
        return FileDocumentStore(settings.get("storage.documents_dir", "storage/documents"))
    raise ValueError(f"storage.type không hỗ trợ: {kind} (file|memory)")


def build_publishers(settings: Settings) -> list[Publisher]:
    # Hiện chỉ có ConsolePublisher; thêm nền tảng = thêm adapter + nhánh ở đây.
    pubs: list[Publisher] = []
    for p in settings.get("publishers", []) or []:
        if p.get("enabled") and p.get("key") == "console":
            pubs.append(ConsolePublisher())
    return pubs or [ConsolePublisher()]


def build_pipeline(settings: Settings, *,
                   collector: Collector | None = None,
                   offline: bool = True) -> MarketingPipeline:
    """Dựng pipeline hoàn chỉnh từ settings. Mặc định offline (MockCollector)."""
    return MarketingPipeline(
        collector or build_collector(settings, offline=offline),
        llm=build_llm(settings),
        hook_llm=build_hook_llm(settings),
        store=build_store(settings),
        retriever=build_retriever(settings),
        research_gate=build_gate(settings, gate="research"),
        content_gate=build_gate(settings, gate="content"),
        publishers=build_publishers(settings),
        config=PipelineConfig(
            collect_limit=int(settings.get("crawl.limit_per_source", 10)),
            curation=CurationConfig.from_settings(settings),
            hook_enabled=bool(settings.get("producers.hook", True)),
        ),
    )


def load_and_build(path=None, *, offline: bool = True) -> MarketingPipeline:
    """Tiện ích: nạp settings từ file rồi dựng pipeline."""
    return build_pipeline(load_settings(path), offline=offline)
