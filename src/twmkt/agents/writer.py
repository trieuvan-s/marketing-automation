"""Writer (Phase 4, CLAUDE.md lộ trình v3) — bước CUỐI của Brief -> StructureRouter
-> Writer. Gọi THẲNG LLMClient (factory.make_llm, model=llm.step_models.writer=
"sonnet") — KHÔNG qua đường --draft/--ingest thủ công (Claude Code tự viết JSON
trong 1 phiên chat riêng, xem scripts/produce_from_sheet.py --draft — đường đó
vẫn còn TỒN TẠI cho tương thích ngược/power_on.py, nhưng KHÔNG còn là đường sống
chính; Writer ở đây là đường MỚI, tự gọi model thật trong 1 lượt).

System prompt = persona/schema JSON (dùng CHUNG AnalysisWriterAgent.system —
KHÔNG lặp lại) + voice-lock ĐỘNG (agents/voice.assemble_voice theo quyết định
StructureRouterAgent — đúng khung §2 (+khung phụ nếu lai) + đúng 1 hook §2b +
đúng 1 anchor §5, xem agents/structure_router.py).

Bước 'writer' là bước QUAN TRỌNG (llm.fail_loud_steps mặc định = ["writer"],
xem factory.is_fail_loud_step) — fail_loud=True MẶC ĐỊNH ở đây: lỗi/timeout/
is_error RAISE LLMCallError (agents/base.py) thay vì âm thầm sinh nội dung rỗng
rồi ghi CONTENT như thật.

Guardrail compliance.py (agents/production.apply_guardrails) chạy Y NGUYÊN SAU
Writer — KHÔNG gọi bên trong run_writer() (giữ đúng ranh giới "Writer sinh chữ,
guardrail kiểm chữ"), nhưng run_writer_with_retry() BÊN DƯỚI (Phase 4.5) CÓ gọi
guardrail nội bộ vì cần biết reject để phân biệt lỗi TẠM THỜI/VĨNH VIỄN (xem
docstring run_writer_with_retry). Hai cổng duyệt (CONTEXT Status/CONTENT
Approve gate 2) KHÔNG đổi.

PHASE 4.5 — WRITER RETRY (gắn lên fail_loud ở trên, xem config/settings.yaml
khối `writer`):
  - Lỗi TẠM THỜI (LLMCallError từ llm.complete() — timeout/rate-limit/exit≠0/
    JSON hỏng, xem agents/base.py) -> thử lại tối đa writer.max_retries lần,
    chờ writer.retry_backoff_s giữa các lần, log ERROR mỗi lần thất bại. Hết
    lượt -> outcome=FAILED (KHÔNG trả "" coi như nội dung thật — caller PHẢI
    thấy rõ đây là lỗi, không phải bài rỗng hợp lệ).
  - Lỗi VĨNH VIỄN (LLM ĐÃ trả lời thành công nhưng guardrail reject — claim
    cấm/thiếu disclaimer/bịa số) -> KHÔNG retry (thử lại không giúp gì, vấn đề
    ở NỘI DUNG chứ không phải hạ tầng gọi LLM) -> outcome=NEEDS_HUMAN ngay.
  - Idempotent qua `state`+`key` (tuỳ chọn, dict đơn giản — KHÔNG ép Sheets ở
    đây, nơi gọi tự quyết định lưu state ở đâu — vd cột Execute trên CONTEXT
    khi wire vào Sheets sau): state[key]=="DONE" -> SKIP hoàn toàn, không tốn
    lượt gọi. FAILED/NEEDS_HUMAN KHÔNG bị skip -> tự động "tái chạy được" ở
    lần gọi produce SAU mà không cần cờ CLI riêng (chỉ DONE mới coi là xong).
  - `notify(event, info)` (tuỳ chọn) gọi tại 3 điểm: "retry"/"failed"/
    "needs_human" — chỗ nối Telegram/kênh cảnh báo khác sau này.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from ._jsonparse import try_json_object
from .base import LLMCallError, LLMClient
from .production import (
    AnalysisWriterAgent, ProductionBrief, analysis_fields_from_data,
    apply_guardrails, build_analysis_prompt, render_analysis,
)
from .voice import assemble_voice
from ..config import Settings, load_settings
from ..models import ContentDraft, ContentFormat

_PERSONA = AnalysisWriterAgent.system   # persona + QUY TẮC BẮT BUỘC + schema JSON — dùng CHUNG, không lặp


def build_writer_system(decision=None) -> str:
    """Persona/schema (CHUNG) + voice-lock ĐỘNG (theo `decision`, xem
    agents/voice.assemble_voice — decision=None -> fallback an toàn S1+H3+D).
    Hàm THUẦN (không mạng) — tách riêng để test được không cần LLM thật."""
    voice = assemble_voice(decision)
    if not voice:
        return _PERSONA
    return f"{_PERSONA}\n\n---\n\nVOICE-LOCK (giọng văn bắt buộc):\n{voice}"


def run_writer(llm: LLMClient, brief: ProductionBrief, decision=None, *,
               model: str | None = None, fail_loud: bool = True) -> ContentDraft:
    """Gọi LLM bước 'writer' -> ContentDraft (CHƯA qua guardrail — caller tự gọi
    apply_guardrails() sau, xem docstring module). `decision` = RouterDecision
    (agents/structure_router.RouterDecision) hoặc None (fallback S1+H3+D).
    `fail_loud=True` MẶC ĐỊNH (khác các bước phụ brief/router) — lỗi RAISE
    LLMCallError, KHÔNG lùi mượt trả nội dung rỗng."""
    system = build_writer_system(decision)
    raw = llm.complete(system, build_analysis_prompt(brief), model=model, fail_loud=fail_loud)
    data = try_json_object(raw)
    title, sapo, sections, disclaimer, sources = analysis_fields_from_data(data, brief)
    body = render_analysis(title, sapo, sections, disclaimer, sources, brief)
    return ContentDraft(fmt=ContentFormat.ARTICLE, title=title, body=body, brief_topic=brief.topic)


class WriterOutcome(str, Enum):
    DONE = "DONE"                 # LLM trả lời, qua guardrail sạch
    FAILED = "FAILED"             # hết lượt retry vì lỗi TẠM THỜI (hạ tầng gọi LLM)
    NEEDS_HUMAN = "NEEDS_HUMAN"   # LLM trả lời nhưng guardrail reject — lỗi VĨNH VIỄN


@dataclass
class WriterResult:
    """Kết quả run_writer_with_retry() — `draft` chỉ có giá trị khi outcome
    DONE hoặc NEEDS_HUMAN (LLM ĐÃ trả lời); None khi FAILED (chưa từng có nội
    dung hợp lệ để trả — KHÔNG được coi None/"" là bài rỗng hợp lệ)."""
    outcome: WriterOutcome
    draft: ContentDraft | None = None
    attempts: int = 0
    reason: str = ""


def run_writer_with_retry(
    llm: LLMClient, brief: ProductionBrief, decision=None, *,
    settings: Settings | None = None, model: str | None = None,
    state: dict[str, str] | None = None, key: str | None = None,
    notify: Callable[[str, dict], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> WriterResult:
    """Bọc run_writer() bằng retry (Phase 4.5) — xem docstring module. `state`+
    `key` tuỳ chọn cho idempotent (bỏ qua nếu đã DONE); `notify` tuỳ chọn, gọi
    tại retry/failed/needs_human; `sleep` tiêm được cho test ($0 thời gian,
    giống pattern call_with_retry ở sheets_board.py)."""
    settings = settings or load_settings()
    notify = notify or (lambda event, info: None)

    if state is not None and key is not None and state.get(key) == WriterOutcome.DONE.value:
        return WriterResult(outcome=WriterOutcome.DONE, attempts=0, reason="đã DONE trước đó (skip, idempotent)")

    max_retries = int(settings.get("writer.max_retries", 1))
    backoff_s = float(settings.get("writer.retry_backoff_s", 3))
    max_attempts = max_retries + 1

    last_reason = ""
    for attempt in range(1, max_attempts + 1):
        try:
            draft = run_writer(llm, brief, decision, model=model, fail_loud=True)
        except LLMCallError as e:
            last_reason = str(e)
            print(f"[ERROR] writer attempt {attempt}/{max_attempts} failed: {last_reason}")
            notify("retry", {"attempt": attempt, "max_attempts": max_attempts, "reason": last_reason})
            if attempt < max_attempts:
                sleep(backoff_s)
            continue

        # LLM trả lời thành công -> guardrail. Reject = lỗi VĨNH VIỄN, KHÔNG retry.
        # facts=brief.facts (Phase 4.8 Mục C) -> chấp nhận số làm tròn hợp lý
        # khớp canonical; brief.facts=[] (chưa chạy agents/brief.run_brief())
        # -> no-op, hành vi y hệt trước Mục C.
        approx_tol = float(settings.get("guardrail.approx_tolerance_pct", 5)) / 100
        draft = apply_guardrails(draft, brief.evidence, brief.background,
                                 brief.facts, approx_tolerance=approx_tol)
        if not draft.is_clean:
            reason = "; ".join(draft.compliance_issues)
            print(f"[ERROR] writer NEEDS_HUMAN (guardrail reject, KHÔNG retry): {reason}")
            notify("needs_human", {"reason": reason, "attempt": attempt})
            if state is not None and key is not None:
                state[key] = WriterOutcome.NEEDS_HUMAN.value
            return WriterResult(outcome=WriterOutcome.NEEDS_HUMAN, draft=draft,
                                attempts=attempt, reason=reason)

        if state is not None and key is not None:
            state[key] = WriterOutcome.DONE.value
        return WriterResult(outcome=WriterOutcome.DONE, draft=draft, attempts=attempt)

    # Hết retry vì lỗi TẠM THỜI -> FAILED loud, KHÔNG trả nội dung rỗng coi như thật.
    print(f"[ERROR] writer FAILED sau {max_attempts} lượt (lỗi tạm thời, tái chạy được lần sau): {last_reason}")
    notify("failed", {"attempts": max_attempts, "reason": last_reason})
    if state is not None and key is not None:
        state[key] = WriterOutcome.FAILED.value
    return WriterResult(outcome=WriterOutcome.FAILED, attempts=max_attempts, reason=last_reason)
