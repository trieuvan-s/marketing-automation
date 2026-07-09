"""Research/Brief (Phase 2, CLAUDE.md lộ trình v3) — đọc evidence thô (full-fetch,
$0, tất định) -> facts[] đã gắn NHÃN NGHĨA, dùng model alias 'brief' (rẻ, Haiku
qua factory.make_llm/step_model). Đây là bước MỚI, đứng GIỮA full-fetch evidence
và Production 3 agent (agents/production.py) — SỬA GỐC lý do InfographicSpecAgent
cũ chỉ trích được nhãn vô nghĩa "Số liệu N" (regex mù trên text thô, xem
_MAGNITUDE_RE ở production.py).

KHÔNG hợp nhất với ResearchBrief/Researcher (models.py, agents/researcher.py) —
đường Hook/Luồng B RAG giữ NGUYÊN, không đụng. Fact/facts[] (models.Fact) là
data contract RIÊNG, chỉ chảy vào ProductionBrief.facts.

KHÔNG dùng LLMRouter/Tier (đó là cơ chế đo chi phí cho đường Hook/Producer cũ) —
gọi thẳng LLMClient (factory.make_llm) qua complete(..., model=step_model(...)).
Bước 'brief' là bước PHỤ -> KHÔNG fail_loud (factory.is_fail_loud_step trả False
mặc định) -> lỗi/rỗng LÙI MƯỢT về facts=[] (KHÔNG crash; ProductionBrief.facts
rỗng vẫn hợp lệ, InfographicSpecAgent cũ vẫn chạy y nguyên bằng evidence thô).

CHỐNG BỊA (verify_fact_in_evidence): mỗi fact.value PHẢI xuất hiện NGUYÊN VĂN
trong ÍT NHẤT 1 câu của evidence+background -> không có thì LOẠI fact đó, nhất
quán với guardrail hiện có (agents/production.unsupported_numbers).

PHASE 4.8 MỤC C — SỐ CANONICAL ("AI hiểu ở Brief, CODE phán ở Guardrail"):
LLM trả THÊM 2 field/fact — "raw" (cụm nguyên văn value+unit, COPY Y NGUYÊN từ
văn bản, kể cả từ xấp xỉ nếu có, vd "gần 600 tỷ đồng") và "approx" (bool, có
từ xấp xỉ hay không). CODE (KHÔNG phải AI) tính `canonical_value` = số học
THẬT từ value+unit (agents/_numeric.parse_magnitude_token) — không tin AI làm
toán. RÀNG BUỘC CHỐNG TRÔI: "raw" PHẢI là substring THẬT (kiểm bằng `in`, không
chỉ verify_fact_in_evidence theo câu) của evidence+background -> thiếu/sai thì
LOẠI fact ngay, KHÔNG lọt xuống writer/guardrail.
"""
from __future__ import annotations

import re

from ._jsonparse import try_json_object
from ._numeric import has_approx_word, parse_magnitude_token
from ..models import FACT_KINDS, Fact
from .base import LLMClient

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?\n])\s+")

# "Infographic-worthy" = MỌI tuyên bố định lượng/mốc có tên đáng lên hình, KHÔNG
# chỉ %/tiền (Phase 2.5 — siết recall). Few-shot count BẮT BUỘC để chống thiên
# lệch: hỏi thử cho thấy Haiku mặc định chỉ bắt %/tiền, bỏ qua đếm số lượng nếu
# không có ví dụ minh hoạ rõ trong prompt.
_SYSTEM = (
    "Bạn là trợ lý trích MỌI tuyên bố định lượng hoặc mốc có tên ĐÁNG LÊN HÌNH "
    "(infographic-worthy) từ một đoạn văn — KHÔNG chỉ số tiền/phần trăm. 8 NHÓM "
    "cần bắt (kind):\n"
    "  - percent: tỷ lệ % (vd '8,18%').\n"
    "  - money: số tiền (vd '1.200 tỷ đồng', '300 tỷ USD').\n"
    "  - count: số đếm KHÔNG có đơn vị tiền/% (vd '8 cổ phiếu', '18 dự án', '3 ngân hàng').\n"
    "  - growth: mức tăng/giảm có so sánh (vd '+67,7%', 'gấp 2 lần', 'tăng 800%').\n"
    "  - date: mốc thời gian cụ thể (vd '23/6/2026', 'quý 2/2026', 'nửa cuối 2026').\n"
    "  - ranking: xếp hạng/so sánh cực cấp (vd 'cao nhất nhiều năm', 'lớn nhất nước').\n"
    "  - target: mục tiêu/ngưỡng thay đổi (vd '30% lên 40%', 'trần tín dụng 40%').\n"
    "  - other: định lượng khác không thuộc 7 nhóm trên.\n"
    "Với MỖI fact, gắn 1 NHÃN NGẮN GỌN mô tả CHÍNH XÁC nó LÀ GÌ (vd 'GDP 6 tháng "
    "đầu năm 2026', 'Số cổ phiếu SSI khuyến nghị', 'Ngày NHNN ra quyết định') — "
    "TUYỆT ĐỐI KHÔNG dùng nhãn chung chung kiểu 'Số liệu 1', 'Số liệu 2'.\n"
    "CHỈ trích số/mốc THẬT SỰ xuất hiện NGUYÊN VĂN trong văn bản — KHÔNG suy diễn, "
    "KHÔNG tính toán, KHÔNG làm tròn khác đi.\n"
    "Ví dụ (few-shot, kind=count — DỄ BỊ BỎ SÓT nếu chỉ nghĩ tới %/tiền): đoạn "
    "\"...SSI vẫn lựa chọn 8 cổ phiếu có triển vọng tích cực...\" PHẢI cho ra "
    '{"value": "8", "label": "Số cổ phiếu SSI khuyến nghị", "unit": null, "kind": "count"} '
    "— dù không có %/đơn vị tiền đi kèm.\n"
    "Với MỖI fact, THÊM 2 trường (Phase 4.8 Mục C, chống trôi số): \"raw\" = cụm "
    "NGUYÊN VĂN chứa value bạn COPY Y NGUYÊN từ văn bản (kể cả từ xấp xỉ nếu có, "
    "vd \"gần 600 tỷ đồng\") — PHẢI tìm được y hệt bằng tìm-chuỗi trong văn bản "
    "gốc, TUYỆT ĐỐI KHÔNG diễn giải/viết lại; \"approx\" = true nếu cụm đó có từ "
    "xấp xỉ (gần/khoảng/xấp xỉ/hơn/trên/dưới), false nếu là số chính xác.\n"
    'Trả về DUY NHẤT JSON: {"facts": [{"value": str, "label": str, "unit": str hoặc null, '
    '"kind": "percent|money|count|growth|date|ranking|target|other", '
    '"raw": str, "approx": bool}]}. '
    "KHÔNG markdown, KHÔNG lời dẫn."
)


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT_RE.split(text or "") if s.strip()]


def verify_fact_in_evidence(value: str, source_text: str) -> str | None:
    """Câu evidence ĐẦU TIÊN chứa NGUYÊN VĂN `value` — None nếu không có (chống
    bịa). Hàm THUẦN, test được không cần LLM.

    KHÔNG dùng substring `in` thô: value NGẮN (vd "8") sẽ khớp NHẦM vào bên
    trong 1 số khác không liên quan (vd "8" lọt trong "8,18%") -> gắn sai câu
    nguồn. Ép biên bất đối xứng có chủ đích:
      - TRƯỚC: không được là chữ số/`.`/`,` (chặn khớp vào GIỮA 1 số dài hơn,
        vd "18" trong "8,18%" — trước "18" là ",").
      - SAU: không được là chữ số, `%` (dính liền, vd "18" trong "8,18%" —
        sau "18" là "%"), hay `,`/`.` NỐI THÊM chữ số (phần thập phân/nghìn
        tiếp theo). `,`/`.` theo sau bởi KHÔNG-chữ-số (dấu câu bình thường,
        vd "8,18%, mức cao nhất" — dấu phẩy sau % rồi tới khoảng trắng) VẪN
        khớp bình thường — không thì chặn nhầm cả câu tiếng Việt tự nhiên.
    """
    value = (value or "").strip()
    if not value:
        return None
    pattern = re.compile(
        r"(?<![\d.,])" + re.escape(value) + r"(?!\d)(?!%)(?!,\d)(?!\.\d)")
    for sent in _split_sentences(source_text):
        if pattern.search(sent):
            return sent
    return None


def build_brief_prompt(evidence: str, background: str = "") -> str:
    text = f"{evidence}\n{background}".strip() if background else evidence.strip()
    return f"Văn bản:\n{text[:2500]}\n\nTrích facts[] đúng schema, đã dặn ở system."


def _verify_candidates(value: str, unit: str | None, source_text: str) -> str | None:
    """Thử verify theo THỨ TỰ cụ thể hoá dần: "value+unit" (dính liền, vd
    "8,18%"), "value unit" (cách nhau, vd "1.200 tỷ đồng"), rồi `value` trơ.
    LLM có lúc tách unit ra riêng ("value":"8,18","unit":"%") — verify value
    trơ ("8,18") sẽ bị chặn bởi luật biên (đứng ngay trước "%") dù đây là fact
    THẬT; thử ghép lại với unit trước mới đúng ý nghĩa số trong evidence."""
    candidates = []
    if unit:
        candidates += [f"{value}{unit}", f"{value} {unit}"]
    candidates.append(value)
    seen_c: set[str] = set()
    for cand in candidates:
        if cand in seen_c:
            continue
        seen_c.add(cand)
        sent = verify_fact_in_evidence(cand, source_text)
        if sent is not None:
            return sent
    return None


def facts_from_llm_output(raw: str, evidence: str, background: str = "") -> list[Fact]:
    """Parse output LLM -> facts[] đã LỌC CHỐNG BỊA (value phải verify được
    trong evidence+background). Hàm THUẦN — dùng chung bởi run_brief() và test
    (không cần LLM thật)."""
    data = try_json_object(raw) if raw else None
    if not data:
        return []
    source_text = f"{evidence}\n{background}"
    out: list[Fact] = []
    seen: set[str] = set()
    for item in (data.get("facts") or []):
        if not isinstance(item, dict):
            continue
        value = str(item.get("value", "")).strip()
        label = str(item.get("label", "")).strip()
        if not value or not label or value in seen:
            continue
        unit_raw = item.get("unit")
        unit = str(unit_raw).strip() or None if unit_raw else None
        sent = _verify_candidates(value, unit, source_text)
        if sent is None:
            continue   # không xuất hiện trong evidence/background -> nghi bịa, LOẠI

        # Mục C (Phase 4.8): "raw" PHẢI là substring THẬT của evidence+background
        # (kiểm `in`, chặt hơn verify_fact_in_evidence theo câu) -> chống AI tự
        # paraphrase/bịa cụm không có thật. Thiếu/sai -> LOẠI fact, KHÔNG lọt
        # xuống writer/guardrail (canonical_value không có ý nghĩa nếu raw giả).
        raw_phrase = str(item.get("raw", "")).strip()
        if not raw_phrase or raw_phrase not in source_text:
            continue

        kind_raw = str(item.get("kind", "")).strip().lower()
        kind = kind_raw if kind_raw in FACT_KINDS else "other"   # kind lạ -> "other", KHÔNG loại fact
        # canonical_value: CODE tính (KHÔNG tin AI làm toán) từ value+unit đã
        # verify ở trên — parse_magnitude_token thuần, tất định.
        canonical_value = parse_magnitude_token(f"{value}{unit or ''}")
        # approx: AI tự báo HOẶC code tự dò từ chính "raw" (an toàn kép, không
        # tin mù cờ AI điền, cùng triết lý với driver_count/residual_tension
        # ở structure_router.py).
        approx = bool(item.get("approx", False)) or has_approx_word(raw_phrase)
        out.append(Fact(value=value, label=label, unit=unit, source=sent, kind=kind,
                        raw=raw_phrase, canonical_value=canonical_value, approx=approx))
        seen.add(value)
    return out


def run_brief(llm: LLMClient, evidence: str, background: str = "", *,
              model: str | None = None, fail_loud: bool = False) -> list[Fact]:
    """Gọi LLM bước 'brief' -> facts[] đã verify. LÙI MƯỢT mặc định (fail_loud=
    False): LLM rỗng/lỗi/parse hỏng -> [] (KHÔNG crash). `model`/`fail_loud`
    truyền thẳng cho complete() (xem factory.step_model/is_fail_loud_step)."""
    raw = llm.complete(_SYSTEM, build_brief_prompt(evidence, background),
                       model=model, fail_loud=fail_loud)
    if not raw:
        return []
    return facts_from_llm_output(raw, evidence, background)
