"""Lắp ráp thành phần từ settings — điểm hội tụ của nguyên tắc config-first.

Mọi lựa chọn adapter (LLM mock/anthropic, cổng console/auto/sheets, embedder,
collector, nguồn crawl) được quyết ở đây dựa trên config/settings.yaml, LÕI
(orchestrator + agents) không cần biết. Thêm nhà cung cấp = thêm nhánh ở đây.

Không gọi mạng / không gọi LLM khi chỉ *dựng* pipeline: các client đắt tiền
(AnthropicLLM, Crawl4aiCollector, SheetsApprovalGate) đều import/kết nối lazy.
"""
from __future__ import annotations

from .agents.base import AnthropicLLM, LLMClient, MockLLM
from .approval import sheets_gate
from .approval.gate import ApprovalGate, AutoApproveGate, ConsoleApprovalGate
from .collectors.base import Collector
from .collectors.crawl4ai_collector import Crawl4aiCollector
from .collectors.mock import MockCollector
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
    out: list[Source] = []
    for s in settings.enabled_sources():
        try:
            st = SourceType(s.get("type", "news"))
        except ValueError:
            st = SourceType.OTHER
        out.append(Source(name=s.get("name") or s.get("key", ""),
                          url=s.get("url", ""), source_type=st))
    return out


# --- Collector: mock (offline) hoặc crawl4ai (production) -------------------
def build_collector(settings: Settings, *, offline: bool = True) -> Collector:
    if offline:
        return MockCollector()
    return Crawl4aiCollector.from_settings(settings)


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
