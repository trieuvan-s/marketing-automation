"""Giai đoạn SẢN XUẤT (cổng 2) — chạy SAU khi người duyệt đặt CONTEXT.Status=APPROVE.

Đây là nơi DUY NHẤT bật LLM ĐẮT (Sonnet, content_model): vì đã qua cổng duyệt 1
nên không đốt token cho chủ đề bị loại. Mỗi định dạng = 1 agent chuyên biệt, output
JSON theo SCHEMA cố định (xem docs/production_agents_design.md):
  • AnalysisWriterAgent  — bài phân tích (LLM). Schema: title/sapo/sections/disclaimer/sources.
  • VideoScriptAgent     — kịch bản video ~60s (LLM). Schema: title/duration_sec/scenes/cta/disclaimer.
  • InfographicSpecAgent — spec JSON (TẤT ĐỊNH, $0 — theo CLAUDE.md: infographic ở
    Tầng 0/free). Số liệu đọc THẲNG từ ProductionBrief.facts[] (Phase 4.10 — trước
    đó trích thô bằng regex trên evidence, không qua LLM nên không thể bịa).

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
thương hiệu (tên đọc từ config/brand.yaml, KHÔNG hard-code — xem _BRAND_NAME),
không tường thuật lại 1 bài báo, và xâu chuỗi thêm bối cảnh/tiền
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

PHASE 4.8 MỤC C — SỐ CANONICAL: số trong body KHÔNG khớp NGUYÊN VĂN evidence
(vd Writer viết "gần 600 tỷ" trong khi evidence chỉ có "585 tỷ đồng") KHÔNG còn
tự động bị flag — nếu `facts` (agents/brief.py) có 1 fact.canonical_value lệch
≤ dung sai (0% mặc định, nới ≤ guardrail.approx_tolerance_pct% CHỈ KHI số
trong body đi kèm từ xấp xỉ ngay trước nó) thì coi là HỢP LỆ. Đây vẫn là PHÉP
TÍNH SỐ HỌC TẤT ĐỊNH (agents/_numeric.py) — KHÔNG gọi LLM để phán. `facts`
rỗng/không truyền (đa số call site hiện tại CHƯA wire agents/brief.run_brief())
-> cơ chế này no-op hoàn toàn, lùi về hành vi CŨ (chỉ so khớp evidence trực
tiếp) — KHÔNG đổi hành vi các đường sản xuất hiện có.

Cơ chế PROMPTS (đổi văn phong không cần sửa code): xem agents/prompts.py +
sheets_board.SheetsBoard.read_prompt_versions. Gọi all_production_agents(llm,
prompt_overrides=...) để áp bản prompt đã kích hoạt trên tab PROMPTS.

PHASE 4.13 MỤC B — KỶ LUẬT SỐ Ở NGUỒN SINH (sửa CHẤT LƯỢNG, KHÔNG nới guardrail):
backtest Phase 4.12-B phát hiện writer/composer tự CHẾ số sai (vd cộng "89.000
tỷ" + "125.000 tỷ" thành "200.000 tỷ" không có thật trong evidence; rớt "000"
biến "357.000 tỷ đồng" thành "357 tỷ" — sai 1.000 lần) — cả 2 case đều bị
guardrail-canonical (Mục C, apply_guardrails/unsupported_numbers) CHẶN ĐÚNG,
nhưng gây NEEDS_HUMAN OAN (writer/composer THỪA SỨC viết đúng ngay từ đầu nếu
được nhắc kỷ luật). `_NUMBER_DISCIPLINE` (hằng số dùng CHUNG, tránh trôi giữa 2
agent) nối vào CUỐI `AnalysisWriterAgent.system` và `_INFOGRAPHIC_COMPOSER_SYSTEM`
— guardrail-canonical GIỮ NGUYÊN làm lưới chặn CUỐI (không nới lỏng), đây chỉ
là sửa NGUỒN để giảm tỷ lệ bị lưới chặn oan.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from ._jsonparse import try_json_object
from ._numeric import has_approx_word, parse_magnitude_token
from ..config import load_brand, load_settings
from ..guardrails import compliance
from ..models import ContentDraft, ContentFormat, Fact
from .base import Agent, LLMClient
from .voice import assemble_voice

_FALLBACK_DISCLAIMER = "Nội dung mang tính thông tin, không phải khuyến nghị đầu tư."


def _default_cta(brand: dict | None = None) -> str:
    """CTA mặc định — Content Factory Phase D (vá rò brand cũ): tên thương
    hiệu đọc từ config/brand.yaml (MỘT NGUỒN, qua config.load_brand()), TUYỆT
    ĐỐI KHÔNG hard-code TÊN BRAND NÀO (cũ hay mới) ở đây — đổi brand chỉ sửa
    brand.yaml, KHÔNG sửa prompt/code. Sự cố THẬT đã gặp: CTA mang brand CŨ
    (đã đổi tên từ lâu) vẫn rò ra sản phẩm video THẬT vì hằng số hard-code ở
    đây không theo kịp lúc chốt brand mới (Phase 1.2 chỉ vá renderer, CHƯA
    quét hết prompt) — xem test_no_old_brand_name_anywhere_in_product_code."""
    b = brand if brand is not None else load_brand()
    name = str(b.get("name") or "").strip()
    return f"Theo dõi {name} để cập nhật phân tích." if name else "Theo dõi để cập nhật phân tích."


def _default_disclaimer(brand: dict | None = None) -> str:
    """Disclaimer mặc định — đọc `footer.disclaimer` từ config/brand.yaml (MỘT
    NGUỒN, cùng brand kit dùng bởi render/infographic.py). _FALLBACK_DISCLAIMER
    CHỈ dùng khi CẢ brand.yaml lẫn key này đều thiếu (môi trường test/lỗi đọc
    file) — không hard-code brand nào, chỉ là câu miễn trừ trách nhiệm chung."""
    b = brand if brand is not None else load_brand()
    footer = b.get("footer") or {}
    return str(footer.get("disclaimer") or "").strip() or _FALLBACK_DISCLAIMER


# ACTIVE_TASK — Tích hợp CONTENT_WRITER_RULES: đọc prompts/content_writer_
# rules.md TẠI THỜI ĐIỂM GỌI (không cache import-time, CÙNG NẾP với agents/
# voice.assemble_voice đọc docs/voice_examples.md mỗi lần gọi) — sửa rule
# trong file .md KHÔNG cần sửa code. Trích ĐÚNG các mục §-số nguyên thuộc
# nhóm (a) PROMPT (Phase 1 phân loại: §2 nguyên tắc viết cốt lõi dùng chung +
# §3 Article + §4 Video + §5 Infographic) — GHÉP NGUYÊN VĂN, KHÔNG diễn giải
# lại/tóm tắt (file rules là NGUỒN CHUẨN). §1 (quyết định model)/§6-§9
# (checklist/reject-conditions/meta) KHÔNG nhúng ở đây — đó là input cho
# validator (guardrails/) và bước tự-review, không phải nội dung DẠY VĂN.
_CONTENT_WRITER_RULES_SECTION_RE = re.compile(r"(?m)^# (\d+)\. ")


def _load_content_writer_rules(*, sections: tuple[str, ...], settings=None) -> str:
    """Đọc + trích các mục `sections` (số §, vd ("2","3") cho Article) từ
    `prompts/content_writer_rules.md` (đường dẫn qua config, KHÔNG hard-code —
    `writer.content_rules_path`). File thiếu/đọc lỗi -> "" (LÙI MƯỢT, agent
    vẫn chạy bằng persona/schema gốc, KHÔNG crash) + 1 dòng cảnh báo console.
    Hàm THUẦN ngoại trừ đọc đĩa — test được bằng cách trỏ `settings` tới file
    tạm, không cần LLM thật."""
    settings = settings or load_settings()
    path = Path(settings.get("writer.content_rules_path", "prompts/content_writer_rules.md"))
    if not path.exists():
        print(f"[CẢNH BÁO] không thấy {path} -> bỏ qua CONTENT_WRITER_RULES (rỗng).")
        return ""
    text = path.read_text(encoding="utf-8")
    matches = list(_CONTENT_WRITER_RULES_SECTION_RE.finditer(text))
    blocks: list[str] = []
    for i, m in enumerate(matches):
        if m.group(1) not in sections:
            continue
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks.append(text[start:end].rstrip())
    return "\n\n".join(blocks)


_JSON_ONLY = "\n\nCHỈ trả JSON đúng schema, KHÔNG markdown, KHÔNG lời dẫn."

# PERSONA của AnalysisWriterAgent/VideoScriptAgent (system prompt, xem 2 class
# bên dưới) đọc tên brand 1 LẦN lúc import module — CÙNG NẾP với mọi `system`
# khác trong file này (hằng số string tĩnh, đối chiếu 1-1 với prompts/*.v1.md
# qua test_prompts_*_file_matches_code_default_no_drift, xem tests/test_
# pipeline.py) — KHÔNG đổi sang property/method động (sẽ vỡ đối chiếu chuỗi
# tĩnh đó). Đổi brand.yaml rồi restart tiến trình là đủ, khớp cách load_settings()
# cũng chỉ đọc 1 lần mỗi lượt chạy script.
_BRAND_NAME = str(load_brand().get("name") or "").strip() or "đội ngũ phân tích"

# Phase 4.13 Mục B — dùng CHUNG cho AnalysisWriterAgent + InfographicSpecAgent
# (composer), tránh trôi giữa 2 nơi. Xem docstring module đầu file.
_NUMBER_DISCIPLINE = (
    "\nKỶ LUẬT SỐ (BẮT BUỘC, Phase 4.13 — giảm NEEDS_HUMAN oan do tự chế số):\n"
    "- MỌI số bạn viết PHẢI Y NGUYÊN VĂN như trong facts[].raw (hoặc evidence "
    "nếu không có facts) — KHÔNG tự CỘNG/GỘP nhiều số RIÊNG LẺ thành 1 số MỚI "
    "(vd evidence có '89.000 tỷ đồng' và '125.000 tỷ đồng' ở 2 câu KHÁC NHAU -> "
    "CẤM tự cộng ra '214.000 tỷ đồng' hay bất kỳ số tổng nào KHÔNG có sẵn "
    "nguyên văn trong facts[]/evidence).\n"
    "- KHÔNG tự đổi/rớt ĐƠN VỊ hay BẬC SỐ (vd evidence viết '357.000 tỷ đồng' -> "
    "PHẢI giữ đúng '357.000 tỷ đồng' hoặc '357 nghìn tỷ đồng' — TUYỆT ĐỐI KHÔNG "
    "viết thành '357 tỷ' vì đã làm mất 3 chữ số 0, sai lệch 1.000 LẦN).\n"
    "- QUY ƯỚC SỐ TIẾNG VIỆT (đọc SAI 2 dấu này là nguồn lỗi lệch bậc số phổ "
    "biến nhất — LUÔN đếm lại số chữ số trước khi viết): dấu CHẤM (.) = phân "
    "cách HÀNG NGHÌN của PHẦN NGUYÊN (vd '357.000' = ba trăm năm mươi bảy "
    "NGHÌN); dấu PHẨY (,) = phân cách PHẦN THẬP PHÂN sau hàng đơn vị (vd "
    "'8,18%' = tám phẩy mười tám phần trăm, KHÔNG phải 818%).\n"
    "- Muốn dùng SỐ TỔNG (vd tổng nhiều khoản) -> CHỈ dùng nếu con số tổng đó "
    "ĐÃ có sẵn NGUYÊN VĂN trong facts[]/evidence (ai đó đã tính sẵn và công bố) "
    "— KHÔNG tự làm phép cộng/trừ/nhân/chia rồi trình bày như số THẬT của nguồn."
)

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
    facts: list[Fact] = field(default_factory=list)  # số liệu đã gắn nhãn (agents/brief.py, Phase 2)
    no_numeric_content: bool = False   # Phase 4.12: Brief xác nhận CHẮC CHẮN tin không có số (facts=[] hợp lệ, khác facts=[] do Brief hỏng — xem agents/brief.BriefResult)


def _tickers_line(brief: ProductionBrief) -> str:
    return ", ".join(brief.tickers) or "N/A"


def _soft_truncate(text: str, limit: int) -> str:
    """Cắt `text` về TỐI ĐA `limit` ký tự nhưng KHÔNG cắt GIỮA 1 từ (Phase
    4.11, item 6 — sửa lỗi cắt cụt giữa chữ ở các đường LÙI MƯỢT article/video,
    vd cũ 'brief.evidence[:200]' có thể đứt ngang 1 từ). Lùi về khoảng trắng
    GẦN NHẤT trước `limit`; không có khoảng trắng nào (1 từ dài hơn limit) ->
    cắt cứng như cũ (không còn lựa chọn nào tốt hơn). text ngắn hơn limit ->
    giữ NGUYÊN, không thêm "…". Hàm THUẦN — test được không cần Brief thật."""
    text = text or ""
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit)
    return text[:cut if cut > 0 else limit].rstrip() + "…"


def domain_of(url: str) -> str:
    """Tên miền để trích nguồn TẤT ĐỊNH (vd 'cafef.vn'). URL rỗng/hỏng -> ''."""
    try:
        return (urlparse(url).netloc or "").removeprefix("www.")
    except Exception:
        return ""


def _normalize_number(token: str) -> str:
    """Chuẩn hoá SO SÁNH 1 token số (Phase 4.6, sửa false-positive phát hiện
    khi validate): bỏ hết dấu '.'/',' trong token — token do _MAGNITUDE_RE bắt
    CHỈ chứa số + đơn vị (không có câu chữ khác lẫn vào) nên an toàn để bỏ dấu
    phân cách, bất kể kiểu viết: evidence gốc hay để dấu CHẤM thập phân kiểu
    quốc tế ("12.61%" — dữ liệu bảng/HOSE), trong khi Writer viết đúng chuẩn
    tiếng Việt bằng dấu PHẨY ("12,61%") — không chuẩn hoá thì 2 chuỗi này
    KHÁC NHAU dù CÙNG 1 con số, gây báo sai 'bịa số'."""
    return re.sub(r"[.,]", "", token.lower().strip())


_DEFAULT_APPROX_TOLERANCE = 0.05   # Mục C: nới ≤5% CHỈ KHI số TRONG BÀI đi kèm từ xấp xỉ
_APPROX_LOOKBACK = 12               # số ký tự nhìn NGƯỢC trước token để tìm từ xấp xỉ


def _matches_canonical_fact(tok: str, body: str, start: int, facts: list[Fact],
                            tolerance: float) -> bool:
    """Mục C (Phase 4.8; mở rộng Content Factory Phase 1 — range/delta): số
    TRONG BÀI (`tok`, tại vị trí `start`) HỢP LỆ nếu khớp BẤT KỲ trường
    canonical_* nào có mặt trên 1 fact: canonical_value (shape=scalar) lệch ≤
    `tolerance`; NẰM TRONG [canonical_low, canonical_high] (shape=range, biên
    nới thêm theo `tolerance` CHỈ khi có từ xấp xỉ — số NẰM SẴN trong range
    khớp dù không có từ xấp xỉ, đúng bản chất range, khớp media_factory/
    spec._fact_matches cho NHẤT QUÁN 2 lượt guardrail); khớp canonical_from
    HOẶC canonical_to (shape=delta). `tolerance` = 0 (khớp chính xác) CHỈ nới
    lên khi `tok` trong bài đi kèm từ xấp xỉ ngay trước nó — xem apply_
    guardrails/unsupported_numbers. shape=entity/entity_list KHÔNG có
    canonical_* số nào -> tự động bỏ qua ở đây (guardrail TÊN chưa có ở lượt
    1, xem media_factory/spec._check_plain_list_item_entity cho lượt 2). So
    khớp SỐ HỌC tất định (agents/_numeric.py) — guardrail luôn là CODE, KHÔNG
    bao giờ để AI phán 1 số là an toàn."""
    val = parse_magnitude_token(tok)
    if val is None:
        return False
    effective_tolerance = tolerance if has_approx_word(body[max(0, start - _APPROX_LOOKBACK):start]) else 0.0
    for f in facts:
        if f.canonical_value is not None and f.canonical_value != 0:
            if abs(val - f.canonical_value) / abs(f.canonical_value) <= effective_tolerance:
                return True
        if f.canonical_low is not None and f.canonical_high is not None:
            lo, hi = sorted((f.canonical_low, f.canonical_high))
            slack = (hi - lo) * effective_tolerance
            if lo - slack <= val <= hi + slack:
                return True
        if f.canonical_from is not None and f.canonical_from != 0:
            if abs(val - f.canonical_from) / abs(f.canonical_from) <= effective_tolerance:
                return True
        if f.canonical_to is not None and f.canonical_to != 0:
            if abs(val - f.canonical_to) / abs(f.canonical_to) <= effective_tolerance:
                return True
    return False


def unsupported_numbers(body: str, source_text: str, facts: list[Fact] | None = None, *,
                        approx_tolerance: float = _DEFAULT_APPROX_TOLERANCE) -> list[str]:
    """Số liệu tài chính (%, tỷ, triệu...) xuất hiện trong `body` nhưng KHÔNG có
    trong `source_text` (evidence + background gộp lại) VÀ không khớp canonical
    nào trong `facts` -> nghi bịa số. Hàm THUẦN, dùng bởi apply_guardrails().
    Thứ tự kiểm (dừng ở bước đầu tiên khớp):
      1. So khớp CHÍNH XÁC trong evidence.
      2. Sau khi chuẩn hoá dấu thập phân (_normalize_number, Phase 4.6 fix 1) —
         chấp nhận Writer đổi "12.61%" (evidence) thành "12,61%" (chuẩn tiếng
         Việt) mà KHÔNG coi là bịa số, miễn CHỮ SỐ giống hệt.
      3. Mục C (Phase 4.8): khớp SỐ HỌC với 1 fact.canonical_value trong dung
         sai (0% mặc định; ≤ approx_tolerance nếu số trong bài đi kèm từ xấp
         xỉ) — `facts` rỗng/None -> bước này no-op, hành vi y hệt trước Mục C."""
    low = source_text.lower()
    evidence_norm = {_normalize_number(m.group(0)) for m in _MAGNITUDE_RE.finditer(source_text)}
    facts = facts or []
    bad, seen = [], set()
    for m in _MAGNITUDE_RE.finditer(body):
        tok = m.group(0)
        key = tok.lower().strip()
        if key in low or key in seen:
            continue
        if _normalize_number(tok) in evidence_norm:
            continue   # khớp sau khi chuẩn hoá dấu thập phân -> KHÔNG nghi bịa
        if facts and _matches_canonical_fact(tok, body, m.start(), facts, approx_tolerance):
            continue   # khớp canonical (đúng số hoặc làm tròn hợp lý) -> KHÔNG nghi bịa
        seen.add(key)
        bad.append(tok)
    return bad


def apply_guardrails(draft: ContentDraft, evidence: str, background: str = "",
                     facts: list[Fact] | None = None, *,
                     approx_tolerance: float = _DEFAULT_APPROX_TOLERANCE) -> ContentDraft:
    """Chạy compliance.check (disclaimer/claim cấm) + chặn bịa số (evidence +
    background gộp lại — background = bối cảnh Claude Code research thêm khi
    viết; `facts` (agents/brief.py, tuỳ chọn) cho phép số làm tròn hợp lý khớp
    canonical, xem unsupported_numbers). Gắn draft.compliance_issues
    (Status=ERROR nếu vi phạm). Trả lại draft."""
    issues = compliance.check(draft)
    source_text = f"{evidence}\n{background}"
    if source_text.strip():   # infographic trích số THẲNG từ evidence -> luôn rỗng, bỏ qua vô ích
        issues += [f"Số liệu không thấy trong evidence/background: {t}" for t in
                   unsupported_numbers(draft.body, source_text, facts, approx_tolerance=approx_tolerance)]
    draft.compliance_issues = issues
    return draft


class AnalysisWriterAgent(Agent):
    role = "AnalysisWriter"
    prompt_name = "analysis"          # khớp tab PROMPTS.Name + prompts/analysis.<v>.md
    system = (
        f"PERSONA: Bạn là cây bút phân tích trưởng của {_BRAND_NAME} — giọng SẮC,\n"
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
        f'- "disclaimer": PHẢI dùng ĐÚNG NGUYÊN VĂN "{_default_disclaimer()}" (KHÔNG viết '
        "lại/diễn giải/thêm bớt chữ nào — đây là câu miễn trừ trách nhiệm CHUẨN, đã duyệt).\n"
        + _NUMBER_DISCIPLINE +
        '\nTrả về DUY NHẤT JSON: {"title": str, "sapo": str, '
        '"sections": [{"heading": str, "content": str}], '
        '"disclaimer": str, "sources": [str]}.'
    )

    def run(self, brief: ProductionBrief) -> ContentDraft:
        # decision=None -> fallback an toàn S1+H3+D (chưa chạy StructureRouter ở
        # đường LEGACY này — xem agents/writer.py cho đường MỚI có router thật).
        voice = assemble_voice(None)
        extra = f"\n\n---\n\nVOICE-LOCK (giọng văn bắt buộc):\n{voice}" if voice else ""
        rules = _load_content_writer_rules(sections=("2", "3"))
        if rules:
            extra += f"\n\n---\n\nCONTENT_WRITER_RULES (bắt buộc, nguồn chuẩn):\n{rules}"
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
        disclaimer = str(data.get("disclaimer") or _default_disclaimer()).strip()
        sources = [str(u).strip() for u in (data.get("sources") or []) if str(u).strip()]
        if sections:
            return title, sapo, sections, disclaimer, sources
    # LÙI MƯỢT: dựng schema tất định từ dữ kiện đã duyệt (không LLM/parse lỗi).
    # LUÔN giữ tiêu đề gốc trong Bối cảnh (dù có hook/evidence riêng) -> truy vết được.
    # _soft_truncate (Phase 4.11, item 6): cắt về giới hạn nhưng KHÔNG cắt GIỮA
    # 1 từ (lùi về khoảng trắng gần nhất) — trước đây cắt cứng [:N] có thể đứt
    # ngang chữ.
    title = brief.hook or brief.title
    sapo = _soft_truncate(brief.evidence, 200) or brief.title
    boi_canh = f"{brief.title}. {_soft_truncate(brief.evidence, 600)}" if brief.evidence else brief.title
    sections = [{"heading": "Bối cảnh", "content": boi_canh}]
    if brief.background:
        sections.append({"heading": "Bối cảnh mở rộng", "content": _soft_truncate(brief.background, 600)})
    sections.append({"heading": "Hàm ý với nhà đầu tư",
                     "content": f"Mã liên quan: {_tickers_line(brief)}."})
    return title, sapo, sections, _default_disclaimer(), ([brief.url] if brief.url else [])


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
    body += ["", _default_cta(), "", f"_{disclaimer}_"]
    return "\n".join(body)


# PHASE 4.10: hướng dẫn CHUYỂN THỂ VIDEO riêng (docs/voice_examples.md §4) —
# assemble_voice() (agents/voice.py) CHỈ lắp §1/§2/§2b/§2c/§3/§5 (phổ quát +
# theo router), KHÔNG có §4 (đặc thù theo FORMAT: bài dài/social/video/
# infographic) — nối THÊM ở đây, cục bộ cho VideoScriptAgent, KHÔNG sửa
# voice.py (giữ voice.py dùng CHUNG cho article, không lẫn hướng dẫn riêng
# format khác).
_VIDEO_TTS_GUIDANCE = (
    "\n\n---\n\nCHUYỂN THỂ VIDEO (§4 voice_examples.md): hook 5-8 giây đầu = câu "
    "Mở-nghịch-lý đọc lên được; giữ câu NGẮN để TTS mượt và phụ đề không tràn "
    "dòng; mỗi 'beat' một ý; kết mở bằng câu hỏi. Tránh câu lồng nhiều mệnh đề."
)


class VideoScriptAgent(Agent):
    role = "VideoScripter"
    prompt_name = "video"
    system = (
        f"PERSONA: Bạn viết kịch bản video ngắn (~45-60s) cho kênh {_BRAND_NAME} —\n"
        "giọng SẮC, có góc nhìn riêng, KHÔNG đọc lại tin như phát thanh viên. Xâu\n"
        "chuỗi sự kiện với bối cảnh/tiền lệ liên quan (nếu có 'Bối cảnh mở rộng')\n"
        "để người xem CHƯA theo dõi tin trước đó vẫn hiểu toàn cảnh — đây là điểm\n"
        "khác biệt (signature) so với clip tóm tắt tin thông thường.\n"
        "Bố cục: HOOK (0-3s, dùng hook đã có, dẫn bằng NHẬN ĐỊNH chứ không phải\n"
        "tóm tắt) -> 3 beat nội dung (mỗi beat 1 ý + số liệu từ evidence/bối cảnh,\n"
        "PHẢI có góc nhìn/so sánh, không chỉ thuật lại) -> CTA. Mỗi cảnh: lời thoại\n"
        "(voiceover) tự nhiên, chữ trên hình (on-screen text) ngắn, gợi ý hình ảnh.\n"
        f'Kết bằng disclaimer: PHẢI dùng ĐÚNG NGUYÊN VĂN "{_default_disclaimer()}" '
        "(KHÔNG viết lại/diễn giải/thêm bớt chữ nào — đây là câu miễn trừ trách nhiệm "
        "CHUẨN, đã duyệt). KHÔNG bịa số, KHÔNG hô hào mua.\n"
        'Trả về DUY NHẤT JSON: {"title": str, "duration_sec": int, '
        '"scenes": [{"t": str, "voiceover": str, "on_screen_text": str, "visual_hint": str}], '
        '"cta": str, "disclaimer": str}.'
    )

    def run(self, brief: ProductionBrief, decision=None) -> ContentDraft:
        """PHASE 4.10: `decision` = RouterDecision (agents/structure_router,
        đã ĐÓNG BĂNG qua agents/route_once — CÙNG quyết định article của chủ đề
        này dùng, xem scripts/produce_from_sheet.run) hoặc None (fallback
        S1+H3+D, giống AnalysisWriterAgent đường legacy). Voice-lock ĐỘNG +
        §4 chuyển-thể video nối vào system qua _ask(extra_system=...), CÙNG cơ
        chế AnalysisWriterAgent.run() (đường legacy) đã dùng — KHÔNG tự chế
        đường mới."""
        voice = assemble_voice(decision)
        extra = (f"\n\n---\n\nVOICE-LOCK (giọng văn bắt buộc):\n{voice}" if voice else "")
        extra += _VIDEO_TTS_GUIDANCE
        rules = _load_content_writer_rules(sections=("2", "4"))
        if rules:
            extra += f"\n\n---\n\nCONTENT_WRITER_RULES (bắt buộc, nguồn chuẩn):\n{rules}"
        data = try_json_object(self._ask(build_video_prompt(brief), extra_system=extra))
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
        cta = str(data.get("cta") or _default_cta()).strip()
        disclaimer = str(data.get("disclaimer") or _default_disclaimer()).strip()
        if scenes:
            return title, duration, scenes, cta, disclaimer
    # LÙI MƯỢT: kịch bản tất định 3-4 cảnh từ dữ kiện đã duyệt.
    title = brief.hook or brief.title
    scenes = [
        {"t": "0-3s", "voiceover": brief.hook or brief.title, "on_screen_text": brief.title, "visual_hint": ""},
        {"t": "3-30s", "voiceover": brief.title, "on_screen_text": "", "visual_hint": ""},
    ]
    if brief.background:
        scenes.append({"t": "30-45s", "voiceover": _soft_truncate(brief.background, 200),
                       "on_screen_text": "", "visual_hint": ""})
    scenes.append({"t": "45-55s", "voiceover": f"Hàm ý cho nhà đầu tư với {_tickers_line(brief)}.",
                   "on_screen_text": "", "visual_hint": ""})
    return title, 60, scenes, _default_cta(), _default_disclaimer()


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


# PHASE 4.10: kind ưu tiên "đáng lên hình nhất" khi chọn stat emphasis=true —
# ưu tiên số có SỨC NẶNG (tiền/%/tăng-giảm) hơn đếm/xếp hạng/ngày tháng, khớp
# trực giác "con số đập vào mắt trước" của 1 tấm infographic. Vẫn dùng ở Phase
# 4.11 để chọn 1 fact lên `hero` trong đường LÙI MƯỢT (composer LLM lỗi/rỗng).
_INFOGRAPHIC_EMPHASIS_KINDS = ("percent", "growth", "money")


def _pick_emphasis_index(facts: list[Fact]) -> int:
    """Fact ĐẦU TIÊN thuộc nhóm kind đáng lên hình nhất (percent/growth/money)
    -> emphasis=true; không có fact nào thuộc nhóm đó -> mặc định fact đầu
    tiên (giữ hành vi cũ i==0). Hàm THUẦN — test được không cần Brief thật."""
    for i, f in enumerate(facts):
        if f.kind in _INFOGRAPHIC_EMPHASIS_KINDS:
            return i
    return 0


# PHASE 4.11 — INFOGRAPHIC COMPOSER: Phase 4.10 đọc facts[] nhưng DUMP thẳng
# (value = nguyên câu evidence, label dài, takeaway cắt cụt 160 ký tự, subhead
# lặp headline khi hook rỗng). Đây là việc CÔ ĐỌNG — cần LLM (Loại B/haiku,
# KHÔNG còn $0 thuần T0 như trước), không phải chuỗi Python. Input = facts[] +
# RouterDecision (khung bài, để composer biết nên nhấn số nào); output = spec
# JSON 8 TRƯỜNG ổn định (title/subtitle/hero/market/highlights/related/
# priority/source) + 1 khối render_hint TÁCH RIÊNG (gợi ý style mềm, KHÔNG
# thuộc "8 trường data"). disclaimer KHÔNG còn nằm trong spec (thuộc RENDER,
# xem CLAUDE.md nguyên tắc tách data/trình bày) — render/infographic.py (Phase
# 5, chưa làm) sẽ tự gắn khi vẽ.
_INFOGRAPHIC_COMPOSER_SYSTEM = (
    "Bạn là Infographic Composer — nén facts[] (đã trích sẵn, có nhãn NGHĨA + "
    "số nguyên văn) + khung bài (StructureRouter) thành spec JSON 8 TRƯỜNG cho "
    "1 tấm infographic. Đây là việc CÔ ĐỌNG (viết lại NGẮN hơn), KHÔNG phải "
    "liệt kê nguyên văn facts.\n"
    "YÊU CẦU CÔ ĐỌNG:\n"
    "- value NÉN: bỏ chủ ngữ/động từ thừa trong câu, nhưng GIỮ NGUYÊN VĂN cả "
    "SỐ và ĐƠN VỊ như trong fact gốc (BẮT BUỘC, để còn đối chiếu được với dữ "
    "kiện gốc) — CHỈ được cắt bớt CHỮ THỪA (chủ ngữ/động từ), TUYỆT ĐỐI KHÔNG "
    "tự quy đổi bậc số/đơn vị (vd '357.000 tỷ đồng' PHẢI giữ nguyên '357.000 "
    "tỷ đồng', KHÔNG tự viết lại thành '357 tỷ' hay '357 nghìn tỷ' — mọi phép "
    "quy đổi bậc số đều có rủi ro rớt số, xem KỶ LUẬT SỐ bên dưới). Vd an toàn "
    "(chỉ cắt chữ, không đụng số): 'GDP 6 tháng đầu năm tăng 8,18%' -> "
    "'GDP +8,18%'.\n"
    "- hero: 2-3 mã/số NỔI NHẤT (đáng lên hình đầu tiên, ưu tiên %/tăng-giảm/tiền).\n"
    "- market: các số còn lại (cũng phải NÉN như hero).\n"
    "- highlights: 1-3 câu góc-nhìn NGẮN (KHÔNG phải 1 đoạn takeaway dài, "
    "KHÔNG cắt cụt giữa câu — mỗi câu phải TRỌN VẸN).\n"
    "- related: TÊN thực thể thật liên quan trực tiếp (địa danh/dự án/công ty/"
    "mã CK/chính sách) — LẤY TỪ facts[] có [entity]/[entity_list] (xem nhãn "
    "[shape:salience] đầu mỗi dòng fact), GHÉP tên NGUYÊN VĂN. TUYỆT ĐỐI KHÔNG "
    "tự bịa thêm tên nào KHÔNG có trong facts[] — dòng nào trong 'related' "
    "không khớp facts[] SẼ BỊ GUARDRAIL LẦN 2 CHẶN (xem media_factory/spec.py). "
    "CHỈ LẤY entity/entity_list có salience=\"subject\" — TUYỆT ĐỐI KHÔNG lấy "
    "salience=\"context\" (Content Factory Phase 2b — lỗi THẬT đã gặp: related "
    "bị lấp bởi tên hội thảo/hiệp hội/viện nghiên cứu thay vì tên cảng/dự án "
    "thật). facts[] không có entity/entity_list salience=subject nào -> để "
    "related rỗng [], KHÔNG lùi về mã CK/tên context khi không chắc chắn.\n"
    "- priority: {\"primary\": [...nhãn/tên quan trọng nhất...], \"secondary\": "
    "[...], \"minor\": [...]} — \"primary\" CHỈ được chứa nhãn (label) đã dùng "
    "ở hero/market VÀ/HOẶC tên thực thể salience=\"subject\" đã đưa vào "
    "related (KHÔNG bao giờ salience=\"context\") — \"secondary\"/\"minor\" có "
    "thể chứa nhãn context (hội thảo/hiệp hội...) nếu cần, dựa trên mức độ "
    "phục vụ luận điểm chính (khung bài đã cho). MỌI mục trong \"primary\" LẤY "
    "TỪ hero/market PHẢI LẶP LẠI NGUYÊN VĂN chuỗi label đã dùng ở đó — TUYỆT "
    "ĐỐI KHÔNG viết tắt/diễn giải lại (vd đã dùng label \"Khu công nghiệp\" ở "
    "market thì priority.primary PHẢI ghi lại đúng \"Khu công nghiệp\", KHÔNG "
    "được rút gọn thành \"KCN\") — guardrail lần 2 so khớp CHUỖI, viết tắt sẽ "
    "bị chặn NHẦM dù không phải bịa.\n"
    "- title KHÁC subtitle: title = tiêu đề GỌN; subtitle = 1 CÂU GÓC NHÌN "
    "(KHÔNG được lặp lại y hệt title).\n"
    "- render_hint (TÁCH RIÊNG khỏi 8 trường data, chỉ là gợi ý style MỀM): "
    "{\"theme\": \"dark|light\", \"palette\": tên bảng màu ngắn, \"ratio\": "
    "\"4:5|1:1|16:9\"} — tự chọn theo cảm giác nội dung bài.\n"
    "- TUYỆT ĐỐI KHÔNG bịa số ngoài facts[] được cung cấp — MỌI số trong spec "
    "PHẢI xuất phát từ 1 fact đã cho.\n"
    + _NUMBER_DISCIPLINE +
    '\nTrả về DUY NHẤT JSON: {"title": str, "subtitle": str, '
    '"hero": [{"label": str, "value": str}], "market": [{"label": str, "value": str}], '
    '"highlights": [str], "related": [str], '
    '"priority": {"primary": [str], "secondary": [str], "minor": [str]}, '
    '"source": str, "render_hint": {"theme": str, "palette": str, "ratio": str}}. '
    "KHÔNG markdown, KHÔNG lời dẫn."
)

_DEFAULT_RENDER_HINT = {"theme": "dark", "palette": "navy-gold", "ratio": "4:5"}


def _fact_display_value(f: Fact) -> str:
    """Số/tên hiển thị của 1 fact cho Composer đọc — Content Factory Phase 2:
    khác nhau THEO SHAPE (models.FACT_SHAPES), KHÔNG còn chỉ scalar. `raw`
    (nguyên văn evidence) ưu tiên cho scalar; range/delta ghép 2 đầu; entity_
    list liệt kê ĐỦ mọi thành viên (Composer PHẢI thấy hết để điền 'related'
    — thiếu 1 tên là mất nguyên liệu, xem _INFOGRAPHIC_COMPOSER_SYSTEM); entity
    là 1 tên đơn."""
    if f.shape == "range":
        return f"{f.value_low} - {f.value_high}{f.unit or ''}"
    if f.shape == "delta":
        return f"{f.from_value} → {f.to_value}"
    if f.shape == "entity_list":
        return ", ".join(f.entities)
    if f.shape == "entity":
        return f.value
    return f.raw or f"{f.value}{f.unit or ''}"   # shape == "scalar" (mặc định, dữ liệu cũ)


def _fact_tag(f: Fact) -> str:
    """Nhãn đầu dòng fact cho Composer đọc — [shape] (scalar/range/delta), hoặc
    [shape:salience] cho entity/entity_list (Content Factory Phase 2b — Composer
    PHẢI thấy salience ngay trên dòng để lọc related/priority.primary, không
    phải suy đoán)."""
    if f.shape in ("entity", "entity_list"):
        return f"{f.shape}:{f.salience or 'context'}"   # salience rỗng (dữ liệu cũ) -> hiển thị NHƯ context, AN TOÀN hơn
    return f.shape


def build_infographic_composer_prompt(brief: ProductionBrief, decision=None) -> str:
    """Prompt (user turn) cho Infographic Composer — facts[] (KHÔNG phải
    evidence thô) là NGUYÊN LIỆU chính, kèm khung bài (RouterDecision đã đóng
    băng, agents/route_once.py) để composer biết nhấn số nào theo đúng luận
    điểm article/video của CÙNG chủ đề đang dùng (nhất quán multi-content).
    Content Factory Phase 2: mỗi dòng gắn nhãn [shape] (KHÔNG phải [kind] như
    cũ) — Composer cần biết HÌNH DẠNG fact để biết cách dùng (vd entity_list
    -> nguồn cho 'related', KHÔNG phải 1 con số cho hero/market). Phase 2b:
    entity/entity_list thêm ":salience" ([entity_list:subject] vs
    [entity_list:context]) — Composer lọc related/priority.primary CHỈ theo
    subject, xem _INFOGRAPHIC_COMPOSER_SYSTEM."""
    facts_lines = "\n".join(
        f"- [{_fact_tag(f)}] {f.label}: {_fact_display_value(f)}" for f in brief.facts
    )
    structure = str(getattr(decision, "structure", None) or "S1").strip().upper()
    parts = [
        f"Tiêu đề: {brief.title}", f"Hook: {brief.hook}", f"Mã: {_tickers_line(brief)}",
        f"Khung bài đã chọn (StructureRouter): {structure}",
        f"Facts đã trích (agents/brief.py):\n{facts_lines}",
        _JSON_ONLY,
    ]
    return "\n".join(parts)


def _parse_stat_list(raw) -> list[dict]:
    """[{label,value}] từ JSON composer — bỏ item thiếu label/value (an toàn,
    không tin mù LLM trả đủ trường)."""
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()
        value = str(item.get("value", "")).strip()
        if label and value:
            out.append({"label": label, "value": value})
    return out


def _parse_priority(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {tier: [str(x).strip() for x in (raw.get(tier) or []) if str(x).strip()]
            for tier in ("primary", "secondary", "minor")}


def _parse_render_hint(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {k: str(raw.get(k) or v).strip() for k, v in _DEFAULT_RENDER_HINT.items()}


def _stat_from_fact(f: Fact) -> dict:
    return {"label": f.label, "value": _fact_display_value(f)}


def _entity_names_from_facts(facts: list[Fact]) -> list[str]:
    """Content Factory Phase 2 (+ 2b — salience) — mọi TÊN thật CHỦ THỂ
    (salience="subject", KHÔNG phải "context"/phông nền — hội thảo/hiệp hội/
    người phát biểu; xem models.Fact.salience) đã verify sẵn ở Brief (agents/
    brief.py, KHÔNG bịa) — nguồn DUY NHẤT cho 'related' ở đường lùi mượt (KHÔNG
    LLM, xem _empty_infographic_spec/_fallback_infographic_spec). CỐ Ý loại
    salience="" (dữ liệu CŨ trước Phase 2b, chưa phân loại) — KHÔNG đủ chắc
    chắn để lên hình 'related' cho luồng MỚI, dù verify_spec vẫn coi salience
    rỗng là khớp hợp lệ khi ĐỐI CHIẾU (tương thích ngược đọc, không tương
    thích ngược CHỌN). Giữ thứ tự xuất hiện, khử trùng."""
    seen: set[str] = set()
    out: list[str] = []
    for f in facts:
        if f.salience != "subject":
            continue
        names = f.entities if f.shape == "entity_list" else ([f.value] if f.shape == "entity" and f.value else [])
        for n in names:
            if n and n not in seen:
                seen.add(n)
                out.append(n)
    return out


def _empty_infographic_spec(brief: ProductionBrief) -> dict:
    """facts[] RỖNG (Brief lỗi/timeout) -> spec RỖNG CÓ CHỦ Ý — KHÔNG bịa (giữ
    nguyên triết lý Phase 4.10; caller (scripts/produce_from_sheet.run) đánh
    dấu NEEDS_HUMAN cho dòng này). facts[] rỗng -> _entity_names_from_facts
    cũng rỗng -> related lùi về brief.tickers (mã CK từ CONTEXT, KHÔNG phải
    bịa — vẫn là dữ liệu THẬT, chỉ là nguồn khác)."""
    return {
        "title": brief.hook or brief.title, "subtitle": "",
        "hero": [], "market": [], "highlights": [],
        "related": _entity_names_from_facts(brief.facts) or list(brief.tickers),
        "priority": {"primary": [], "secondary": [], "minor": []},
        "source": domain_of(brief.url), "render_hint": dict(_DEFAULT_RENDER_HINT),
    }


def _fallback_infographic_spec(brief: ProductionBrief) -> dict:
    """LÙI MƯỢT: composer LLM lỗi/JSON rỗng -> dựng spec TẤT ĐỊNH trực tiếp từ
    facts[] (KHÔNG nén được chữ vì không có LLM ở bước lùi mượt — value dài
    hơn bản composer thật, nhưng vẫn ĐÚNG số/KHÔNG bịa, và vẫn đủ 8 trường +
    title != subtitle). Fact ưu tiên (_pick_emphasis_index) lên `hero`; còn
    lại (tối đa 5 fact) vào `market`. `related` (Content Factory Phase 2) lấy
    từ MỌI fact entity/entity_list (không chỉ 5 fact đầu — related không giới
    hạn như hero/market), lùi về brief.tickers nếu Brief không trích được tên nào."""
    facts = brief.facts[:5]
    idx = _pick_emphasis_index(facts)
    hero = [_stat_from_fact(f) for i, f in enumerate(facts) if i == idx]
    market = [_stat_from_fact(f) for i, f in enumerate(facts) if i != idx]
    title = brief.hook or brief.title
    subtitle = facts[idx].label if facts and facts[idx].label != title else ""
    related = _entity_names_from_facts(brief.facts) or list(brief.tickers)
    return {
        "title": title, "subtitle": subtitle, "hero": hero, "market": market,
        "highlights": [f"{f.label}: {_fact_display_value(f)}" for f in facts[:2]],
        "related": related,
        "priority": {"primary": [s["label"] for s in hero],
                     "secondary": [s["label"] for s in market], "minor": []},
        "source": domain_of(brief.url), "render_hint": dict(_DEFAULT_RENDER_HINT),
    }


def infographic_spec_from_data(data: dict | None, brief: ProductionBrief) -> dict:
    """JSON composer -> spec 8 trường + render_hint đã validate. Hàm THUẦN —
    test được không cần LLM thật, dùng chung bởi InfographicSpecAgent.run()."""
    if data:
        hero = _parse_stat_list(data.get("hero"))
        market = _parse_stat_list(data.get("market"))
        if hero or market:
            title = str(data.get("title") or brief.hook or brief.title).strip()
            subtitle = str(data.get("subtitle") or "").strip()
            if not subtitle or subtitle == title:
                # RÀNG BUỘC CỨNG (không tin mù LLM): title != subtitle luôn —
                # composer lỡ lặp/để trống thì CODE tự chọn subtitle khác,
                # cùng triết lý "không tin field rời LLM" như driver_count.
                subtitle = brief.title if brief.title != title else ""
            highlights = [str(h).strip() for h in (data.get("highlights") or []) if str(h).strip()]
            related = [str(t).strip() for t in
                      (data.get("related") or _entity_names_from_facts(brief.facts) or brief.tickers)
                      if str(t).strip()]
            return {
                "title": title, "subtitle": subtitle, "hero": hero, "market": market,
                "highlights": highlights, "related": related,
                "priority": _parse_priority(data.get("priority")),
                "source": domain_of(brief.url),
                "render_hint": _parse_render_hint(data.get("render_hint")),
            }
    return _fallback_infographic_spec(brief)


class InfographicSpecAgent(Agent):
    """PHASE 4.11: KHÔNG còn TẤT ĐỊNH/$0 thuần — giờ là 1 bước LLM Loại B/rẻ
    (caller gán `self.model`/`self.llm` = alias 'composer'/haiku, xem
    scripts/produce_from_sheet.run) để CÔ ĐỌNG facts[]+RouterDecision thành
    spec 8 trường (xem _INFOGRAPHIC_COMPOSER_SYSTEM). Đổi từ Phase 4.10 (đọc
    thẳng facts[] nhưng DUMP nguyên văn — value cả câu, takeaway cắt cụt 160
    ký tự, subhead lặp headline khi hook rỗng).

    AN TOÀN SỐ: composer chỉ được CÔ ĐỌNG CHỮ, KHÔNG được đổi giá trị — guard
    chống bịa vẫn là facts[]-verify (agents/brief.py) TRƯỚC + guardrail-số-
    canonical (Mục C, agents/production.apply_guardrails/unsupported_numbers)
    CHẠY LẠI SAU trên `draft.body` (spec JSON đầy đủ) như đã wire từ Phase 4.9
    — KHÔNG cần code MỚI ở đây, chỉ cần composer dùng ĐÚNG từ đơn vị mà
    agents/_numeric.parse_magnitude_token nhận diện được (%, tỷ, tỷ đồng,
    nghìn tỷ, triệu, usd, đồng) để số nén vẫn map được về canonical.

    facts[] RỖNG -> _empty_infographic_spec (KHÔNG gọi LLM, KHÔNG bịa)."""
    role = "InfographicComposer"
    prompt_name = "infographic"
    system = _INFOGRAPHIC_COMPOSER_SYSTEM
    uses_llm = True

    def run(self, brief: ProductionBrief, decision=None) -> ContentDraft:
        if not brief.facts:
            spec = _empty_infographic_spec(brief)
        else:
            rules = _load_content_writer_rules(sections=("2", "5"))
            extra = (f"\n\n---\n\nCONTENT_WRITER_RULES (bắt buộc, nguồn chuẩn):\n{rules}"
                    if rules else "")
            data = try_json_object(self._ask(build_infographic_composer_prompt(brief, decision),
                                             extra_system=extra))
            spec = infographic_spec_from_data(data, brief)
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
