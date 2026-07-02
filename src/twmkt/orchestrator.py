"""Bộ điều phối pipeline — máy trạng thái tất định với 2 cổng người duyệt.

Bản thuần stdlib của thứ LangGraph sẽ làm ở production. Thứ tự gọi _stage_* = các
cạnh graph; 2 cổng duyệt = node 'User Approval' (interrupt).

Chiến lược token: mọi việc tới hết _stage_curate + index RAG là TẦNG 0 (free).
LLM chỉ chạm vào ở _stage_research (gửi chunk liên quan) và _stage_produce — mà
_stage_produce nằm SAU cổng 1, nên không đốt token cho chủ đề bị loại.
"""
from __future__ import annotations

from dataclasses import dataclass

from .agents import HookAgent, ResearcherAgent, all_producers
from .agents.base import LLMClient, MockLLM
from .approval.gate import ApprovalGate, AutoApproveGate
from .collectors.base import Collector
from .curation import normalize
from .curation.config import CurationConfig
from .curation.store import DocumentStore, InMemoryStore
from .guardrails import compliance
from .knowledge.rag import Retriever
from .models import Decision, PipelineState, Source, Stage
from .publishers.base import ConsolePublisher, Publisher


@dataclass
class PipelineConfig:
    """Các tham số điều chỉnh của pipeline (config-first).

    Mặc định = hành vi cũ để demo/test không truyền gì vẫn chạy như trước. Khi
    dựng từ settings (xem twmkt.factory.build_pipeline), các giá trị đọc từ
    config/settings.yaml. `curation=None` -> chuẩn hóa không lọc bài (tương thích
    ngược); khi có CurationConfig -> lọc theo whitelist + từ khóa vĩ mô.
    """

    collect_limit: int = 10
    curation: CurationConfig | None = None
    hook_enabled: bool = True       # bật/tắt bước Hook (producers.hook)


class MarketingPipeline:
    def __init__(
        self,
        collector: Collector,
        *,
        llm: LLMClient | None = None,
        hook_llm: LLMClient | None = None,
        store: DocumentStore | None = None,
        retriever: Retriever | None = None,
        research_gate: ApprovalGate | None = None,
        content_gate: ApprovalGate | None = None,
        publishers: list[Publisher] | None = None,
        config: PipelineConfig | None = None,
    ):
        self.collector = collector
        self.llm = llm or MockLLM()
        # HookAgent dùng tầng LLM rẻ (triage); mặc định dùng chung self.llm.
        self.hook_llm = hook_llm or self.llm
        self.store = store or InMemoryStore()
        self.retriever = retriever or Retriever()
        self.research_gate = research_gate or AutoApproveGate()
        self.content_gate = content_gate or AutoApproveGate()
        self.publishers = publishers or [ConsolePublisher()]
        self.config = config or PipelineConfig()

    def run(self, topic: str, sources: list[Source]) -> PipelineState:
        st = PipelineState(topic=topic)
        self._stage_collect(st, sources)
        self._stage_curate(st)          # + index vào Knowledge Layer (free)
        self._stage_research(st)        # LLM (chỉ chunk liên quan)
        self._stage_hook(st)            # góc marketing (LLM rẻ + fallback tất định)
        if not self._gate_research(st):
            return st
        self._stage_produce(st)         # LLM đắt — chỉ chạy sau khi được duyệt
        if not self._gate_content(st):
            return st
        self._stage_publish(st)
        return st

    # --- nodes -----------------------------------------------------------
    def _stage_collect(self, st: PipelineState, sources: list[Source]) -> None:
        st.stage = Stage.COLLECTED
        for s in sources:
            st.raw_docs.extend(self.collector.collect(s, limit=self.config.collect_limit))
        st.note(f"thu thập {len(st.raw_docs)} tài liệu thô")

    def _stage_curate(self, st: PipelineState) -> None:
        st.stage = Stage.CURATED
        st.clean_docs = normalize(st.raw_docs, self.config.curation)
        self.store.upsert(st.clean_docs)
        n_chunks = self.retriever.index(st.clean_docs)
        st.note(
            f"còn {len(st.clean_docs)} sau dedup "
            f"({len(st.raw_docs) - len(st.clean_docs)} trùng), "
            f"index {n_chunks} chunk vào RAG"
        )

    def _stage_research(self, st: PipelineState) -> None:
        st.stage = Stage.RESEARCHED
        agent = ResearcherAgent(self.llm)
        st.brief = agent.run(st.topic, self.retriever)
        st.note(f"brief: {len(st.brief.tickers)} mã, "
                f"{len(st.brief.evidence)} trích đoạn")

    def _stage_hook(self, st: PipelineState) -> None:
        if not self.config.hook_enabled:
            st.note("bỏ qua bước Hook (tắt trong config: producers.hook=false)")
            return
        st.hook = HookAgent(self.hook_llm).run(st.brief)
        st.note(f"hook: {st.hook.angle}")

    def _gate_research(self, st: PipelineState) -> bool:
        payload = f"{st.brief.thesis}\nMã: {st.brief.tickers}"
        if st.hook is not None:
            payload += (
                f"\n\n-- Góc marketing --\nAngle: {st.hook.angle}\n"
                f"Headlines: {st.hook.headlines}"
            )
        if self.research_gate.review("Nghiên cứu", payload) is Decision.APPROVE:
            st.stage = Stage.APPROVED_RESEARCH
            st.note("cổng 1: DUYỆT")
            return True
        st.stage = Stage.REJECTED
        st.note("cổng 1: TỪ CHỐI -> dừng (không tốn token sinh nội dung)")
        return False

    def _stage_produce(self, st: PipelineState) -> None:
        st.stage = Stage.PRODUCED
        for producer in all_producers(self.llm):
            draft = compliance.apply(producer.run(st.brief, st.hook))
            st.drafts.append(draft)
        flagged = sum(1 for d in st.drafts if not d.is_clean)
        st.note(f"tạo {len(st.drafts)} bản nháp, {flagged} dính cảnh báo tuân thủ")

    def _gate_content(self, st: PipelineState) -> bool:
        clean = [d for d in st.drafts if d.is_clean]
        if not clean:
            st.stage = Stage.REJECTED
            st.note("cổng 2: mọi bản nháp dính lỗi tuân thủ -> dừng")
            return False
        approved_any = False
        for d in clean:
            if self.content_gate.review(f"Nội dung [{d.fmt.value}]", d.body) is Decision.APPROVE:
                d.approved = True
                approved_any = True
        if approved_any:
            st.stage = Stage.APPROVED_CONTENT
            st.note(f"cổng 2: duyệt {sum(d.approved for d in st.drafts)} bản")
            return True
        st.stage = Stage.REJECTED
        st.note("cổng 2: không bản nào được duyệt -> dừng")
        return False

    def _stage_publish(self, st: PipelineState) -> None:
        st.stage = Stage.PUBLISHED
        for d in st.drafts:
            if not d.approved:
                continue
            for pub in self.publishers:
                st.published.append(pub.publish(d))
        st.note(f"đăng {len(st.published)} lượt")
