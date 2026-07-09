"""Lắp ráp thành phần từ settings — điểm hội tụ của nguyên tắc config-first.

Mọi lựa chọn adapter (LLM mock/anthropic, cổng console/auto/sheets, embedder,
collector, nguồn crawl) được quyết ở đây dựa trên config/settings.yaml, LÕI
(orchestrator + agents) không cần biết. Thêm nhà cung cấp = thêm nhánh ở đây.

Không gọi mạng / không gọi LLM khi chỉ *dựng* pipeline: các client đắt tiền
(AnthropicLLM, Crawl4aiCollector, SheetsApprovalGate) đều import/kết nối lazy.
"""
from __future__ import annotations

from dataclasses import dataclass

from .agents.base import AnthropicLLM, ClaudeCodeLLM, LLMClient, MockLLM
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


def _hook_model(settings: Settings) -> str:
    """Model cho Hook: llm.hook_model nếu khai, ngược lại theo llm.content_model
    (Sonnet). Hook ngắn nên tầng cao vẫn rẻ mà chất lượng cao."""
    return (settings.get("llm.hook_model")
            or settings.get("llm.content_model", "claude-sonnet-4-6"))


def _budget(settings: Settings) -> float | None:
    b = settings.get("llm.budget_usd")
    return float(b) if b else None


def build_research_llm(settings: Settings, *, offline: bool = False) -> LLMRouter:
    """LLM cho RESEARCHER — tầng RẺ (llm.triage_model = Haiku), bọc LLMRouter đo
    token/chi phí (tier CHEAP để định giá). offline/mock -> MockLLM ($0)."""
    base: LLMClient = MockLLM() if offline else _build_llm(
        settings, model_key="llm.triage_model", default_model="claude-haiku-4-5-20251001")
    return LLMRouter(base, default_tier=Tier.CHEAP, budget_usd=_budget(settings))


def build_hook_llm(settings: Settings, *, offline: bool = False) -> LLMRouter:
    """LLM cho HOOK — tầng content_model/Sonnet (hoặc llm.hook_model riêng), bọc
    LLMRouter (tier SMART để định giá Sonnet). offline/mock -> MockLLM ($0).
    Hook chạy SAU crawl, đầu ra ngắn -> Sonnet rẻ mà chất lượng cao."""
    base: LLMClient = MockLLM() if offline else _build_llm(
        settings, model_key="llm.hook_model", default_model=_hook_model(settings))
    return LLMRouter(base, default_tier=Tier.SMART, budget_usd=_budget(settings))


@dataclass
class LLMStatus:
    """Trạng thái LLM đã QUYẾT cho lần chạy này — in ra console để KHÔNG lùi mượt
    trong im lặng (người vận hành luôn biết đang chạy anthropic thật hay mock)."""
    use_llm: bool
    provider: str
    reason: str = ""                 # lý do fallback (rỗng nếu use_llm=True)
    hook_model: str = ""
    researcher_model: str = ""
    content_model: str = ""

    @property
    def banner(self) -> str:
        if self.use_llm:
            return (f"LLM active: anthropic (hook={self.hook_model}, "
                    f"researcher={self.researcher_model})")
        return f"LLM active: MOCK ($0 fallback) — lý do: {self.reason}"


def llm_status(settings: Settings) -> LLMStatus:
    """QUYẾT 1 LẦN xem lần chạy này dùng anthropic thật hay mock, kèm banner IN RÕ.
    Gọi hàm này ở đầu mỗi script rồi `print(status.banner)` — không được lùi mượt
    trong im lặng. provider != anthropic hoặc thiếu SDK/ANTHROPIC_API_KEY -> mock."""
    provider = (settings.get("llm.provider", "mock") or "mock").lower()
    researcher_model = settings.get("llm.triage_model", "claude-haiku-4-5-20251001")
    content_model = settings.get("llm.content_model", "claude-sonnet-4-6")
    hook_model = _hook_model(settings)
    if provider != "anthropic":
        return LLMStatus(False, provider, reason=f"llm.provider={provider!r} (không phải anthropic)",
                         hook_model=hook_model, researcher_model=researcher_model,
                         content_model=content_model)
    ok, why = AnthropicLLM.is_available()
    return LLMStatus(ok, provider, reason=why, hook_model=hook_model,
                     researcher_model=researcher_model, content_model=content_model)


def model_engine_label(model: str, *, use_llm: bool) -> str:
    """Nhãn NGẮN cho cột Engine ở tab LOG (haiku|sonnet|opus|mock) — đối chiếu
    nhanh model nào thực sự chạy mà không cần mở cả tên model đầy đủ."""
    if not use_llm:
        return "mock"
    low = (model or "").lower()
    for tag in ("haiku", "sonnet", "opus"):
        if tag in low:
            return tag
    return low or "mock"


_MODEL_ALIASES = {
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-8",
}


def build_content_llm(settings: Settings, *, offline: bool = False,
                      model: str | None = None) -> LLMRouter:
    """LLM cho PRODUCERS (giai đoạn sản xuất SAU cổng 1) — tầng ĐẮT content_model
    (Sonnet mặc định), bọc LLMRouter (tier SMART định giá + áp budget). offline/
    mock -> $0. `model` = 'sonnet'|'opus' (hoặc tên model đầy đủ) ghi đè
    llm.content_model — Opus chất lượng cao hơn nhưng đắt hơn, dùng khi cần."""
    if offline:
        return LLMRouter(MockLLM(), default_tier=Tier.SMART, budget_usd=_budget(settings))
    model_name = _MODEL_ALIASES.get((model or "").lower(), model) or None
    base: LLMClient = _build_llm(
        settings, model_key="llm.content_model", default_model=model_name or "claude-sonnet-4-6")
    if model_name and isinstance(base, AnthropicLLM):
        base.model = model_name   # ghi đè settings.yaml khi --model chỉ định rõ
    return LLMRouter(base, default_tier=Tier.SMART, budget_usd=_budget(settings))


# --- LLM adapter mới (Research/Brief -> StructureRouter -> Writer, xem CLAUDE.md
# lộ trình v3) — SONG SONG với build_*_llm/LLMRouter/Tier ở trên, KHÔNG thay thế,
# KHÔNG đụng LLMRouter (đó vẫn là cơ chế đo chi phí cho đường Hook/Producer cũ).
# Chọn backend theo llm.mode; model theo TỪNG BƯỚC (llm.step_models.<step>) truyền
# qua complete(..., model=...) mỗi lần gọi, KHÔNG cố định ở constructor.
def make_llm(settings: Settings) -> LLMClient:
    """claude_code (CLI `claude -p`, gói Pro/Max hiện có, KHÔNG cần API key riêng)
    | api (AnthropicLLM, cần ANTHROPIC_API_KEY) | mock ($0). KHÔNG BAO GIỜ crash
    khi thiếu key/SDK/binary — các backend tự lùi mượt (trả "") ở complete(),
    KHÔNG kiểm tra tại đây. In banner "LLM backend: <mode>" mỗi lần gọi (không
    lùi mượt trong im lặng)."""
    mode = (settings.get("llm.mode", "mock") or "mock").lower()
    print(f"LLM backend: {mode}")
    if mode == "mock":
        return MockLLM()
    if mode == "claude_code":
        timeout_s = float(settings.get("llm.claude_code.timeout_s", 120))
        return ClaudeCodeLLM(timeout_s=timeout_s)
    if mode == "api":
        return AnthropicLLM(model=settings.get("llm.content_model", "claude-sonnet-4-6"),
                            max_tokens=int(settings.get("llm.max_tokens", 1500)))
    raise ValueError(f"llm.mode không hỗ trợ: {mode} (claude_code|api|mock)")


def step_model(settings: Settings, step: str) -> str | None:
    """ALIAS model (haiku|sonnet|opus) cho 1 BƯỚC (brief|router|writer) theo
    llm.step_models.<step> — truyền vào complete(..., model=...); mỗi backend tự
    map alias -> id/cờ thật (xem agents/base.py). Thiếu key -> None (backend tự
    dùng model mặc định của nó, KHÔNG lỗi)."""
    return settings.get(f"llm.step_models.{step}") or None


def is_fail_loud_step(settings: Settings, step: str) -> bool:
    """True nếu `step` nằm trong llm.fail_loud_steps (mặc định ["writer"]) —
    truyền vào complete(..., fail_loud=...). Bước fail-loud: lỗi/timeout raise
    LLMCallError thay vì lùi mượt trả "" (không được âm thầm sinh nội dung rỗng)."""
    return step in (settings.get("llm.fail_loud_steps", ["writer"]) or [])


def build_writer_llm(settings: Settings) -> LLMClient:
    """LLM client RIÊNG cho bước 'writer' (Phase 4.5, agents/writer.run_writer_
    with_retry) — CÙNG mode với make_llm() nhưng timeout đọc từ `writer.timeout_s`
    (KHÔNG dùng chung llm.claude_code.timeout_s với brief/router) vì Writer là
    bước QUAN TRỌNG (fail_loud mặc định), có thể cần chờ lâu hơn/ngắn hơn 2 bước
    kia tuỳ ngân sách vận hành."""
    mode = (settings.get("llm.mode", "mock") or "mock").lower()
    if mode == "claude_code":
        timeout_s = float(settings.get("writer.timeout_s", 120))
        print(f"LLM backend (writer): {mode} (timeout_s={timeout_s:.0f})")
        return ClaudeCodeLLM(timeout_s=timeout_s)
    return make_llm(settings)


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
def build_collector(settings: Settings, *, offline: bool = True,
                    source: Source | None = None) -> Collector:
    """offline=True -> MockCollector ($0, không mạng).

    Có `source` (không offline) -> DISPATCH theo Source.fetch_type: 'rss' =
    RssCollector (tầng 1 phát hiện), 'html' = HttpFirstCollector (full ngay) —
    KHÔNG còn mặc định html cho mọi nguồn. Không `source` -> chọn engine chung
    theo crawl.engine ('http'|'crawl4ai') cho toàn pipeline (run_pipeline.py)."""
    if offline:
        return MockCollector()
    if source is not None:
        return build_collector_for_source(source, settings)
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
        return FileDocumentStore(
            settings.get("storage.documents_dir", "storage/documents"),
            retention_days=int(settings.get("storage.retention_days", 10)),
            tz=settings.get("storage.timezone", "Asia/Ho_Chi_Minh"),
        )
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
        llm=build_research_llm(settings, offline=offline),   # Researcher = Haiku (rẻ)
        hook_llm=build_hook_llm(settings, offline=offline),   # Hook = Sonnet (content_model)
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
