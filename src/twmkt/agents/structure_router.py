"""StructureRouterAgent (Phase 3, CLAUDE.md lộ trình v3) — "tim" của milestone
voice-lock động. Đọc ProductionBrief (facts[]+kind từ agents/brief.py, Phase 2)
+ classification/hotness (dict rời, tự do — group/topic/hot% từ CONTEXT) rồi
CHỌN ĐÚNG 1 khung diễn giải S1-S5 + 1 hook H1-H3 khớp HÌNH DẠNG THẬT của thông
tin, theo đúng menu ở docs/voice_examples.md §2/§2b (v3 — KHÔNG phải khung cố
định "phản đề" như v2). Phase 4 sẽ lắp output này vào agents/voice.py để nối
ĐÚNG 1 khung §2 + 1 hook §2b + 1 anchor §5 vào system prompt Writer.

Model alias 'router' = haiku (rẻ — phân loại/chọn khung không cần Sonnet). KHÔNG
dùng LLMRouter/Tier (đó là cơ chế đo chi phí đường Hook/Producer cũ) — gọi thẳng
LLMClient qua factory.make_llm/step_model.

Bước 'router' là bước PHỤ (KHÔNG nằm trong llm.fail_loud_steps mặc định) — lỗi/
JSON hỏng/không chắc -> FALLBACK AN TOÀN: structure=S1, hook=H3 (map mặc định
S1 -> anchor "Ví dụ D" ở voice_examples.md §0, Phase 4 sẽ resolve; router KHÔNG
tự phát field anchor — không có trong schema). KHÔNG BAO GIỜ crash pipeline.
Mỗi quyết định (kể cả fallback) đều IN RA LOG (rationale + signals) để audit
chất lượng định tuyến — không lùi mượt trong im lặng.

RÀNG BUỘC CỨNG (không tin tưởng mù LLM tự áp luật ở tầng prompt): structure=S5
mà signals.has_genuine_paradox=false -> coi là VI PHẠM luật "S5 cấm làm mặc
định" -> ép fallback (không chỉ nhắc trong prompt, mà CHẶN Ở CODE).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ._jsonparse import try_json_object
from .base import LLMClient
from .production import ProductionBrief

STRUCTURES = ("S1", "S2", "S3", "S4", "S5")
HOOKS = ("H1", "H2", "H3")

_SYSTEM = (
    "Bạn là Structure Router — đọc dữ kiện (thesis/facts) rồi CHỌN ĐÚNG 1 khung "
    "diễn giải khớp HÌNH DẠNG THẬT của thông tin (KHÔNG phải khung bạn thích nhất).\n\n"
    "5 KHUNG (chọn `structure`):\n"
    "  S1 · Tổng-phân-hợp: có 1 luận điểm trung tâm rõ + nhiều fact bổ trợ. Dùng khi "
    "has_central_thesis=true và có nhiều fact ủng hộ luận điểm đó.\n"
    "  S2 · Diễn dịch: dạy 1 nguyên tắc/cách đọc chung rồi áp vào ca cụ thể. Dùng khi "
    "chủ đề trừu tượng cần khung trước khi vào số.\n"
    "  S3 · Quy nạp: nhiều dữ kiện RỜI RẠC, để người đọc tự thấy pattern rồi mới kết "
    "luận xu hướng chung ở CUỐI bài (KHÔNG áp kết luận ngay đầu).\n"
    "  S4 · Song hành: nhiều driver ĐỘC LẬP cùng tác động (driver_count>=3), không cái "
    "nào phụ cái nào. Thường là 1 ĐOẠN trong bài lớn hơn (secondary_structure), hiếm "
    "khi là cả bài.\n"
    "  S5 · Phản đề: CHỈ dùng khi CÓ NGHỊCH LÝ THẬT cần hoá giải (has_genuine_paradox="
    "true) — vd 2 tín hiệu THẬT SỰ mâu thuẫn nhau, không phải chỉ 'nghe hơi lạ'. TUYỆT "
    "ĐỐI KHÔNG chọn S5 làm mặc định hay khi không chắc — dùng sai chỗ sẽ gượng.\n\n"
    "3 HOOK (chọn `hook`):\n"
    "  H1 · Ngã ba: nêu nghịch lý nén, thả 1 lựa chọn kép, kết bằng câu hỏi.\n"
    "  H2 · Chi tiết bị bỏ qua: giấu 1 chi tiết, nâng mức cược của nó.\n"
    "  H3 · Sự thật + câu hỏi trực diện: 1 câu sự thật có số/tên, rồi 1 câu hỏi.\n\n"
    "TRƯỚC KHI CHỌN, PHẢI đánh giá `signals` TRUNG THỰC (dùng để audit, KHÔNG phải điền "
    "cho có):\n"
    "  - has_genuine_paradox: có THẬT 2 tín hiệu mâu thuẫn nhau, hay chỉ có vẻ lạ?\n"
    "  - driver_count: đếm số driver/nguyên nhân ĐỘC LẬP đang tác động (không phải đếm "
    "số fact).\n"
    "  - has_central_thesis: có 1 luận điểm trung tâm rõ ràng gói được cả bài không?\n\n"
    "content_type: 'article' (bài phân tích), 'video' (kịch bản ngắn), hoặc "
    "'infographic-hint' (chỉ đáng làm infographic, không đủ chất liệu viết dài).\n"
    "secondary_structure: khung PHỤ nếu bài LAI (vd thân S1 nhưng 1 đoạn liệt kê theo "
    "S4) — null nếu thuần 1 khung.\n"
    "rationale: 1-2 câu VÌ SAO khung này khớp hình dạng dữ kiện (không phải khung khác).\n\n"
    'Trả về DUY NHẤT JSON: {"content_type": str, "structure": "S1|S2|S3|S4|S5", '
    '"hook": "H1|H2|H3", "secondary_structure": "S1|S2|S3|S4|S5 hoặc null", '
    '"rationale": str, "signals": {"has_genuine_paradox": bool, "driver_count": int, '
    '"has_central_thesis": bool}}. KHÔNG markdown, KHÔNG lời dẫn.'
)


@dataclass
class RouterDecision:
    """Output StructureRouter — Phase 4 dùng `structure`/`hook`/`secondary_structure`
    để lắp voice-lock động; `rationale`/`signals`/`fallback` chỉ để AUDIT (log),
    KHÔNG chảy vào system prompt Writer."""
    content_type: str                  # article|video|infographic-hint
    structure: str                      # S1-S5
    hook: str                           # H1-H3
    secondary_structure: str | None
    rationale: str
    signals: dict = field(default_factory=dict)   # has_genuine_paradox/driver_count/has_central_thesis
    fallback: bool = False              # True nếu đây là fallback an toàn (audit)


def _fallback(reason: str) -> RouterDecision:
    print(f"[CẢNH BÁO] StructureRouter fallback: {reason} -> dùng S1+H3 (trung tính, anchor D).")
    return RouterDecision(
        content_type="article", structure="S1", hook="H3", secondary_structure=None,
        rationale=f"Fallback an toàn: {reason}",
        signals={"has_genuine_paradox": False, "driver_count": 0, "has_central_thesis": True},
        fallback=True,
    )


def build_router_prompt(brief: ProductionBrief, classification: dict | None = None) -> str:
    """`classification` = dict RỜI, tự do (vd {"group":..., "hotness_pct":...} đọc
    từ CONTEXT/curation.enrich) — ProductionBrief KHÔNG có field classification/
    hotness riêng nên truyền tách, gộp vào prompt cho router THAM KHẢO thêm."""
    facts_lines = "\n".join(
        f"- [{f.kind}] {f.label}: {f.value}{f.unit or ''}" for f in brief.facts
    ) or "(chưa có fact trích sẵn — xem thẳng evidence bên dưới)"
    parts = [f"Tiêu đề: {brief.title}"]
    if brief.hook:
        parts.append(f"Hook gợi ý (Cổng 1): {brief.hook}")
    if brief.group:
        parts.append(f"Nhóm: {brief.group}")
    if brief.topic:
        parts.append(f"Chủ đề: {brief.topic}")
    if classification:
        parts.append(f"Phân loại/Hot bổ sung: {classification}")
    parts.append(f"Facts đã trích (Research/Brief):\n{facts_lines}")
    if brief.evidence:
        parts.append(f"Trích evidence gốc (tham khảo thêm sắc thái): {brief.evidence[:800]}")
    if brief.background:
        parts.append(f"Bối cảnh mở rộng: {brief.background[:500]}")
    return "\n".join(parts)


def route_from_llm_output(raw: str) -> RouterDecision:
    """Parse output LLM -> RouterDecision đã validate. Hàm THUẦN — dùng chung
    bởi run_route() và test (không cần LLM thật). JSON hỏng/thiếu field/structure
    hoặc hook không hợp lệ -> fallback (S1+H3). S5 mà thiếu has_genuine_paradox
    -> CŨNG fallback (ép luật, không tin mù LLM)."""
    data = try_json_object(raw) if raw else None
    if not data:
        return _fallback("LLM rỗng hoặc JSON không parse được")

    structure = str(data.get("structure", "")).strip().upper()
    hook = str(data.get("hook", "")).strip().upper()
    signals_raw = data.get("signals") if isinstance(data.get("signals"), dict) else {}
    signals = {
        "has_genuine_paradox": bool(signals_raw.get("has_genuine_paradox", False)),
        "driver_count": int(signals_raw.get("driver_count", 0) or 0),
        "has_central_thesis": bool(signals_raw.get("has_central_thesis", False)),
    }

    if structure == "S5" and not signals["has_genuine_paradox"]:
        return _fallback("router chọn S5 nhưng signals.has_genuine_paradox=false "
                         "(vi phạm luật 'S5 cấm làm mặc định')")
    if structure not in STRUCTURES or hook not in HOOKS:
        return _fallback(f"structure/hook không hợp lệ: structure={structure!r} hook={hook!r}")

    secondary = str(data.get("secondary_structure") or "").strip().upper() or None
    if secondary is not None and secondary not in STRUCTURES:
        secondary = None   # field PHỤ -> bỏ giá trị lạ, KHÔNG fallback cả quyết định

    return RouterDecision(
        content_type=str(data.get("content_type", "")).strip().lower() or "article",
        structure=structure, hook=hook, secondary_structure=secondary,
        rationale=str(data.get("rationale", "")).strip() or "(router không cho rationale)",
        signals=signals, fallback=False,
    )


def _log_decision(brief: ProductionBrief, decision: RouterDecision) -> None:
    print(f"[router] '{brief.title[:60]}' -> structure={decision.structure}"
         f"{'/' + decision.secondary_structure if decision.secondary_structure else ''} "
         f"hook={decision.hook} fallback={decision.fallback} | signals={decision.signals} "
         f"| rationale: {decision.rationale}")


def run_route(llm: LLMClient, brief: ProductionBrief, classification: dict | None = None, *,
              model: str | None = None, fail_loud: bool = False) -> RouterDecision:
    """Gọi LLM bước 'router' -> RouterDecision đã validate + LOG (audit). LÙI
    MƯỢT mặc định (fail_loud=False): lỗi/JSON hỏng -> fallback S1+H3, KHÔNG crash."""
    raw = llm.complete(_SYSTEM, build_router_prompt(brief, classification),
                       model=model, fail_loud=fail_loud)
    decision = route_from_llm_output(raw)
    _log_decision(brief, decision)
    return decision
