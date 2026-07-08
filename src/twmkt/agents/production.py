"""Giai đoạn SẢN XUẤT (cổng 2) — chạy SAU khi người duyệt đặt CONTEXT.Status=APPROVE.

Đây là nơi DUY NHẤT bật LLM ĐẮT (Sonnet, content_model): vì đã qua cổng duyệt 1
nên không đốt token cho chủ đề bị loại. Mỗi định dạng = 1 agent chuyên biệt, output
JSON theo SCHEMA cố định (xem docs/production_agents_design.md):
  • AnalysisWriterAgent  — bài phân tích (LLM). Schema: title/sapo/sections/disclaimer/sources.
  • VideoScriptAgent     — kịch bản video ~60s (LLM). Schema: title/duration_sec/scenes/cta/disclaimer.
  • InfographicSpecAgent — spec JSON (TẤT ĐỊNH, $0 — theo CLAUDE.md: infographic ở
    Tầng 0/free). Số liệu trích THẲNG từ evidence, không qua LLM nên không thể bịa.

HAI CÁCH điền JSON cho Analysis/Video (cùng schema, cùng guardrail, khác "ai viết"):
  1. AnthropicLLM API (llm.provider=anthropic, cần ANTHROPIC_API_KEY riêng) — để
     dành cho khi cần automation 100% không người trông (xem factory.build_content_llm).
  2. Claude Code (phiên chat đang chạy, dùng gói Pro/Max/Team sẵn có, KHÔNG cần
     API key riêng) — build_analysis_prompt/build_video_prompt tách sẵn để Claude
     Code đọc rồi tự viết JSON, qua scripts/produce_from_sheet.py --draft/--ingest.
     Vì hệ thống đã có 2 cổng duyệt người-trong-vòng-lặp, bước sinh nội dung KHÔNG
     cần chạy tự động hoàn toàn ở giai đoạn hiện tại — dùng cách 2 là mặc định.

LÙI MƯỢT: LLM trả rỗng/không parse được JSON -> dựng schema TẤT ĐỊNH từ dữ kiện
đã duyệt (KHÔNG crash, vẫn ra sản phẩm nháp đúng cấu trúc).

SIGNATURE + BỐI CẢNH MỞ RỘNG: bài viết PHẢI có góc nhìn/nhận định riêng của
Turtle Wealth (không tường thuật lại 1 bài báo) và xâu chuỗi thêm bối cảnh/tiền
lệ liên quan đã research (brief.background) để người CHƯA đọc tin trước đó vẫn
hiểu toàn cảnh. `evidence` = thân bài gốc (full-fetch, $0, tất định); `background`
= tóm tắt nghiên cứu bổ sung — do Claude Code tự tìm (WebSearch) khi viết qua
--draft/--ingest, hoặc để trống nếu gọi thẳng AnthropicLLM (chưa có web search).

GUARDRAIL (chạy SAU khi sinh, TRƯỚC khi ghi CONTENT, xem apply_guardrails()):
  - compliance.check (đã có): disclaimer bắt buộc + chặn claim cấm.
  - MỚI: mọi con số tài chính (%, tỷ, triệu, usd, đồng...) xuất hiện trong body
    PHẢI có trong `evidence` HOẶC `background` — chống bịa số. Vi phạm -> ERROR.
  - Trích nguồn báo: gắn "Nguồn: <domain>" TẤT ĐỊNH khi render (không phụ thuộc
    LLM có nhớ ghi hay không).

Cơ chế PROMPTS (đổi văn phong không cần sửa code): xem agents/prompts.py +
sheets_board.SheetsBoard.read_prompt_versions. Gọi all_production_agents(llm,
prompt_overrides=...) để áp bản prompt đã kích hoạt trên tab PROMPTS.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from ._jsonparse import try_json_object
from ..guardrails import compliance
from ..models import ContentDraft, ContentFormat
from .base import Agent, LLMClient
from .voice import load_voice_lock

_DISCLAIMER = (
    "Nội dung chỉ mang tính thông tin, không phải khuyến nghị đầu tư. "
    "Nhà đầu tư tự chịu trách nhiệm với quyết định của mình."
)
_CTA = "Theo dõi Turtle Wealth để cập nhật phân tích."
_JSON_ONLY = "\n\nCHỈ trả JSON đúng schema, KHÔNG markdown, KHÔNG lời dẫn."

# Dữ kiện gây chú ý dạng số (dùng cho cả anti-hallucination guardrail lẫn trích
# stat cho infographic): số tiền/%/kỷ lục.
_MAGNITUDE_RE = re.compile(
    r"\d[\d.,]*\s*(?:%|tỷ đồng|nghìn tỷ|tỷ|triệu|usd|đồng)", re.IGNORECASE)


@dataclass
class ProductionBrief:
    """Đầu vào sản xuất — dựng từ 1 dòng CONTEXT đã APPROVE (+ full-fetch bài)."""
    title: str                                   # CONTEXT.Context (tiêu đề bài)
    hook: str = ""                               # CONTEXT.Hook (tiêu đề gợi ý)
    tickers: list[str] = field(default_factory=list)
    group: str = ""                              # CONTEXT.Group
    topic: str = ""                              # CONTEXT.Topic
    url: str = ""                                # CONTEXT.Source (bài chính)
    evidence: str = ""                           # thân bài (full-fetch) để LLM bám + chống bịa số
    background: str = ""                         # bối cảnh/tiền lệ research THÊM (Claude Code tự tìm)


def _tickers_line(brief: ProductionBrief) -> str:
    return ", ".join(brief.tickers) or "N/A"


def domain_of(url: str) -> str:
    """Tên miền để trích nguồn TẤT ĐỊNH (vd 'cafef.vn'). URL rỗng/hỏng -> ''."""
    try:
        return (urlparse(url).netloc or "").removeprefix("www.")
    except Exception:
        return ""


def unsupported_numbers(body: str, source_text: str) -> list[str]:
    """Số liệu tài chính (%, tỷ, triệu...) xuất hiện trong `body` nhưng KHÔNG có
    trong `source_text` (evidence + background gộp lại) -> nghi bịa số. Hàm
    THUẦN, dùng bởi apply_guardrails()."""
    low = source_text.lower()
    bad, seen = [], set()
    for m in _MAGNITUDE_RE.finditer(body):
        tok = m.group(0)
        key = tok.lower().strip()
        if key in low or key in seen:
            continue
        seen.add(key)
        bad.append(tok)
    return bad


def apply_guardrails(draft: ContentDraft, evidence: str, background: str = "") -> ContentDraft:
    """Chạy compliance.check (disclaimer/claim cấm) + chặn bịa số (evidence +
    background gộp lại — background = bối cảnh Claude Code research thêm khi
    viết). Gắn draft.compliance_issues (Status=ERROR nếu vi phạm). Trả lại draft."""
    issues = compliance.check(draft)
    source_text = f"{evidence}\n{background}"
    if source_text.strip():   # infographic trích số THẲNG từ evidence -> luôn rỗng, bỏ qua vô ích
        issues += [f"Số liệu không thấy trong evidence/background: {t}" for t in
                   unsupported_numbers(draft.body, source_text)]
    draft.compliance_issues = issues
    return draft


class AnalysisWriterAgent(Agent):
    role = "AnalysisWriter"
    prompt_name = "analysis"          # khớp tab PROMPTS.Name + prompts/analysis.<v>.md
    system = (
        "PERSONA: Bạn là cây bút phân tích trưởng của Turtle Wealth — giọng SẮC,\n"
        "có QUAN ĐIỂM riêng (trung lập về khuyến nghị mua/bán, nhưng KHÔNG lấp\n"
        "lửng khi gọi tên vấn đề). Bạn KHÔNG tường thuật lại 1 bài báo — bạn TỔNG\n"
        "HỢP, xâu chuỗi sự kiện hiện tại với bối cảnh/tiền lệ liên quan để người\n"
        "CHƯA đọc tin trước đó vẫn hiểu toàn cảnh. Đây là điểm khác biệt (signature)\n"
        "so với mặt bằng tin tức thông thường.\n"
        "QUY TẮC BẮT BUỘC:\n"
        "- Mở bài bằng NHẬN ĐỊNH sắc nhất của bạn về ý nghĩa sự kiện — KHÔNG mở\n"
        "  bằng cách tóm tắt tin như báo chí.\n"
        "- Nếu có mục 'Bối cảnh mở rộng (research)' trong dữ kiện: PHẢI dùng để\n"
        "  dựng 1 phần riêng trong bài, xâu chuỗi tiền lệ/diễn biến trước đó —\n"
        "  không chỉ dựa vào 1 bài báo gốc.\n"
        "- MỖI phần phải có NHẬN ĐỊNH của người viết (ý nghĩa/rủi ro/so sánh),\n"
        "  không chỉ liệt kê dữ kiện.\n"
        "- BÁM SỐ LIỆU trong evidence/bối cảnh được cung cấp — KHÔNG bịa số.\n"
        "- KHÔNG khuyến nghị mua/bán.\n"
        'Trả về DUY NHẤT JSON: {"title": str, "sapo": str, '
        '"sections": [{"heading": str, "content": str}], '
        '"disclaimer": str, "sources": [str]}.'
    )

    def run(self, brief: ProductionBrief) -> ContentDraft:
        voice = load_voice_lock("analysis")
        extra = f"\n\n---\n\nVOICE-LOCK (giọng văn bắt buộc):\n{voice}" if voice else ""
        data = try_json_object(self._ask(build_analysis_prompt(brief), extra_system=extra))
        title, sapo, sections, disclaimer, sources = analysis_fields_from_data(data, brief)
        body = render_analysis(title, sapo, sections, disclaimer, sources, brief)
        return ContentDraft(fmt=ContentFormat.ARTICLE, title=title, body=body,
                            brief_topic=brief.topic)


def _background_block(brief: ProductionBrief) -> str:
    return f"\nBối cảnh mở rộng (research): {brief.background[:1500]}" if brief.background else ""


def build_analysis_prompt(brief: ProductionBrief) -> str:
    """Prompt (user turn) cho AnalysisWriterAgent — tách riêng để CÓ THỂ dùng mà
    KHÔNG gọi AnthropicLLM: xem scripts/produce_from_sheet.py --draft (nhờ Claude
    Code viết trực tiếp thay vì gọi API riêng — xem docs/production_agents_design.md)."""
    return (
        f"Tiêu đề: {brief.title}\nGóc marketing: {brief.hook}\n"
        f"Mã: {_tickers_line(brief)}\nNguồn: {brief.url}\n"
        f"Dữ kiện (evidence): {brief.evidence[:1500]}" + _background_block(brief) + _JSON_ONLY
    )


def analysis_fields_from_data(data: dict | None, brief: ProductionBrief):
    if data:
        title = str(data.get("title") or brief.hook or brief.title).strip()
        sapo = str(data.get("sapo", "")).strip()
        sections = [
            {"heading": str(s.get("heading", "")).strip(), "content": str(s.get("content", "")).strip()}
            for s in (data.get("sections") or []) if isinstance(s, dict)
        ]
        disclaimer = str(data.get("disclaimer") or _DISCLAIMER).strip()
        sources = [str(u).strip() for u in (data.get("sources") or []) if str(u).strip()]
        if sections:
            return title, sapo, sections, disclaimer, sources
    # LÙI MƯỢT: dựng schema tất định từ dữ kiện đã duyệt (không LLM/parse lỗi).
    # LUÔN giữ tiêu đề gốc trong Bối cảnh (dù có hook/evidence riêng) -> truy vết được.
    title = brief.hook or brief.title
    sapo = brief.evidence[:200] or brief.title
    boi_canh = f"{brief.title}. {brief.evidence[:600]}" if brief.evidence else brief.title
    sections = [{"heading": "Bối cảnh", "content": boi_canh}]
    if brief.background:
        sections.append({"heading": "Bối cảnh mở rộng", "content": brief.background[:600]})
    sections.append({"heading": "Hàm ý với nhà đầu tư",
                     "content": f"Mã liên quan: {_tickers_line(brief)}."})
    return title, sapo, sections, _DISCLAIMER, ([brief.url] if brief.url else [])


def render_analysis(title, sapo, sections, disclaimer, sources, brief: ProductionBrief) -> str:
    body = [f"# {title}", "", sapo, ""]
    for s in sections:
        if s["heading"] or s["content"]:
            body += [f"## {s['heading']}", s["content"], ""]
    body.append(f"Mã liên quan: {_tickers_line(brief)}")
    dom = domain_of(brief.url)
    if dom:
        body.append(f"Nguồn: {dom}")            # TẤT ĐỊNH — không phụ thuộc LLM có nhớ ghi
    for u in sources:
        if u and u != brief.url:
            body.append(f"Xem thêm: {u}")
    body += ["", _CTA, "", f"_{disclaimer}_"]
    return "\n".join(body)


class VideoScriptAgent(Agent):
    role = "VideoScripter"
    prompt_name = "video"
    system = (
        "PERSONA: Bạn viết kịch bản video ngắn (~45-60s) cho kênh Turtle Wealth —\n"
        "giọng SẮC, có góc nhìn riêng, KHÔNG đọc lại tin như phát thanh viên. Xâu\n"
        "chuỗi sự kiện với bối cảnh/tiền lệ liên quan (nếu có 'Bối cảnh mở rộng')\n"
        "để người xem CHƯA theo dõi tin trước đó vẫn hiểu toàn cảnh — đây là điểm\n"
        "khác biệt (signature) so với clip tóm tắt tin thông thường.\n"
        "Bố cục: HOOK (0-3s, dùng hook đã có, dẫn bằng NHẬN ĐỊNH chứ không phải\n"
        "tóm tắt) -> 3 beat nội dung (mỗi beat 1 ý + số liệu từ evidence/bối cảnh,\n"
        "PHẢI có góc nhìn/so sánh, không chỉ thuật lại) -> CTA. Mỗi cảnh: lời thoại\n"
        "(voiceover) tự nhiên, chữ trên hình (on-screen text) ngắn, gợi ý hình ảnh.\n"
        "Kết bằng disclaimer 1 dòng. KHÔNG bịa số, KHÔNG hô hào mua.\n"
        'Trả về DUY NHẤT JSON: {"title": str, "duration_sec": int, '
        '"scenes": [{"t": str, "voiceover": str, "on_screen_text": str, "visual_hint": str}], '
        '"cta": str, "disclaimer": str}.'
    )

    def run(self, brief: ProductionBrief) -> ContentDraft:
        data = try_json_object(self._ask(build_video_prompt(brief)))
        title, duration, scenes, cta, disclaimer = video_fields_from_data(data, brief)
        body = render_video(title, duration, scenes, cta, disclaimer, brief)
        return ContentDraft(fmt=ContentFormat.VIDEO_SCRIPT, title=title, body=body,
                            brief_topic=brief.topic)


def build_video_prompt(brief: ProductionBrief) -> str:
    """Prompt (user turn) cho VideoScriptAgent — tách riêng, cùng lý do với
    build_analysis_prompt (dùng cho luồng --draft/--ingest không gọi API)."""
    return (
        f"Tiêu đề: {brief.title}\nGóc/hook: {brief.hook}\n"
        f"Mã: {_tickers_line(brief)}\nDữ kiện (evidence): {brief.evidence[:1000]}"
        + _background_block(brief) + _JSON_ONLY
    )


def video_fields_from_data(data: dict | None, brief: ProductionBrief):
    if data:
        title = str(data.get("title") or brief.hook or brief.title).strip()
        duration = int(data.get("duration_sec") or 60)
        scenes = [
            {"t": str(sc.get("t", "")).strip(), "voiceover": str(sc.get("voiceover", "")).strip(),
             "on_screen_text": str(sc.get("on_screen_text", "")).strip(),
             "visual_hint": str(sc.get("visual_hint", "")).strip()}
            for sc in (data.get("scenes") or []) if isinstance(sc, dict)
        ]
        cta = str(data.get("cta") or _CTA).strip()
        disclaimer = str(data.get("disclaimer") or _DISCLAIMER).strip()
        if scenes:
            return title, duration, scenes, cta, disclaimer
    # LÙI MƯỢT: kịch bản tất định 3-4 cảnh từ dữ kiện đã duyệt.
    title = brief.hook or brief.title
    scenes = [
        {"t": "0-3s", "voiceover": brief.hook or brief.title, "on_screen_text": brief.title, "visual_hint": ""},
        {"t": "3-30s", "voiceover": brief.title, "on_screen_text": "", "visual_hint": ""},
    ]
    if brief.background:
        scenes.append({"t": "30-45s", "voiceover": brief.background[:200],
                       "on_screen_text": "", "visual_hint": ""})
    scenes.append({"t": "45-55s", "voiceover": f"Hàm ý cho nhà đầu tư với {_tickers_line(brief)}.",
                   "on_screen_text": "", "visual_hint": ""})
    return title, 60, scenes, _CTA, _DISCLAIMER


def render_video(title, duration, scenes, cta, disclaimer, brief: ProductionBrief) -> str:
    body = [f"HOOK: {title}", f"(~{duration}s)", ""]
    for sc in scenes:
        body.append(f"[{sc['t']}] {sc['voiceover']}")
        if sc["on_screen_text"]:
            body.append(f"  On-screen: {sc['on_screen_text']}")
        if sc["visual_hint"]:
            body.append(f"  Hình ảnh: {sc['visual_hint']}")
    dom = domain_of(brief.url)
    body += ["", f"[CTA] {cta}"]
    if dom:
        body.append(f"Nguồn: {dom}")
    body += ["", disclaimer]
    return "\n".join(body)


class InfographicSpecAgent(Agent):
    """TẤT ĐỊNH, $0 (theo CLAUDE.md: infographic ở Tầng 0/free) — số liệu trích
    THẲNG từ evidence bằng regex, KHÔNG qua LLM nên không thể bịa."""
    role = "InfographicDesigner"
    prompt_name = "infographic"
    system = "Tạo spec infographic dạng JSON — TẤT ĐỊNH, $0."
    uses_llm = False

    def run(self, brief: ProductionBrief) -> ContentDraft:
        stats_vals = _MAGNITUDE_RE.findall(f"{brief.evidence} {brief.background}")[:5]
        stats = [{"label": f"Số liệu {i + 1}", "value": v.strip(), "emphasis": i == 0}
                 for i, v in enumerate(stats_vals)]
        spec = {
            "headline": brief.hook or brief.title,
            "subhead": brief.topic or brief.group,
            "tickers": brief.tickers,
            "stats": stats,
            "takeaway": (brief.evidence[:160] or brief.title),
            "footer": {"disclaimer": _DISCLAIMER, "source": domain_of(brief.url)},
        }
        return ContentDraft(fmt=ContentFormat.INFOGRAPHIC,
                            title=f"[Infographic] {brief.title}",
                            body=json.dumps(spec, ensure_ascii=False, indent=2),
                            brief_topic=brief.topic)


_PRODUCTION_AGENT_CLASSES = (AnalysisWriterAgent, VideoScriptAgent, InfographicSpecAgent)


def all_production_agents(llm: LLMClient | None = None,
                          prompt_overrides: dict[str, str] | None = None) -> list[Agent]:
    """3 agent sản xuất: 2 dùng LLM (Sonnet) + 1 tất định. `prompt_overrides` =
    {prompt_name: system_text} đã resolve từ tab PROMPTS (agents.prompts.resolve_prompts)
    — override đúng agent theo `agent.prompt_name`, không đổi ai không có bản mới."""
    agents = [cls(llm) for cls in _PRODUCTION_AGENT_CLASSES]
    if prompt_overrides:
        for a in agents:
            text = prompt_overrides.get(getattr(a, "prompt_name", ""))
            if text:
                a.system = text
    return agents
