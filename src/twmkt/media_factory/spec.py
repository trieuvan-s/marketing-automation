"""Production Factory — `ProductionSpec`: schema TRUNG LẬP NHÀ CUNG CẤP, CỦA
TA (KHÔNG dùng `TemplateScript` của vendor nào làm định dạng lõi — quyết định
kiến trúc #1, Phase 1.0). Đây là input DUY NHẤT cho renderer (`render/
infographic.py` — SVG, Phase 1.2) — adapter dịch `ProductionSpec` sang schema
từng vendor nếu cần (video, Phase 2), KHÔNG sửa lõi.

QUYẾT ĐỊNH #1 Phase 1.0 (đã CHỐT, KHÔNG persist ProductionSpec):
  `ProductionSpec` là đối tượng DẪN XUẤT (derived) — dựng LẠI mỗi lần cần
  render, từ (CONTENT.Output hiện tại + facts[] đọc từ cột JSON MỚI trên
  CONTENT, neo TopicKey). KHÔNG đóng băng/ghi xuống data_root (data_root
  KHÔNG đồng bộ giữa nhiều máy — đúng lỗi Fix (a) vừa sửa cho CONTEXT, không
  lặp lại cho Production Factory). Vì vậy `ProductionSpec` KHÔNG có hàm
  persist ở đây — nơi gọi (Phase 1.3, wiring vào produce_from_sheet.py) tự
  build lại mỗi lần cần, rẻ vì đây là phép biến đổi CODE TẤT ĐỊNH, không LLM.

GUARDRAIL CHẠY 2 LẦN (quyết định #1 Phase 1.0):
  (a) Ngay sau Composer, TRƯỚC Gate 2 — ĐÃ CÓ, xem agents/production.py:
      apply_guardrails()/unsupported_numbers() (chạy trên JSON thô Composer
      sinh ra, dùng facts[] còn trong RAM cùng tiến trình).
  (b) `verify_spec()` Ở ĐÂY — chạy TRƯỚC KHI RENDER (Phase 1.2), trên
      `ProductionSpec` dựng LẠI từ CONTENT.Output SAU KHI người có thể đã sửa
      tay ở Gate 2 (Người có thể gõ nhầm số) + facts[] đọc từ cột Sheet mới
      (KHÔNG phải facts[] cũ trong RAM — facts[] đã persist ra Sheet, xem
      docstring module-level ở nơi đọc cột đó, dự kiến sheets_board.py Phase
      1.3). Đây là LẦN MỚI, bắt buộc — chưa qua thì KHÔNG render/lên Gate 3
      (NEEDS_HUMAN, xem nơi gọi).

`verify_spec()` kiểm CẢ số dạng CHỮ SỐ (vd "585 tỷ" — media_factory.numbers.
parse_digit_token) LẪN số VIẾT BẰNG CHỮ (vd "năm trăm tám mươi lăm tỷ" —
media_factory.numbers.parse_vn_number_words) trong MỌI `slots` và `voice_text`
của MỌI scene — số không khớp `facts[].canonical_value` nào (trong dung sai
xấp xỉ nếu có từ "gần/khoảng/..." đứng ngay trước) -> `Violation`.

`build_spec_from_content()` — Phase 1.3, dựng `ProductionSpec` TỪ 8-trường
Composer JSON (`CONTENT.Output`, SAU khi người có thể đã sửa tay ở Gate 2) +
`facts` (đọc từ `CONTENT.Facts`, xem `sheets_board.facts_from_json`) theo quy
tắc ánh xạ TẤT ĐỊNH đã duyệt Phase 1.0: title+subtitle -> scene title (hook) |
hero -> scene stat (body) | market -> scene list (body) | highlights -> scene
quote (outro). Dùng ĐỂ VERIFY (guardrail lần 2) — renderer SVG hiện có
(`render/infographic.render_infographic_svg`) vẫn đọc THẲNG `output_data`
8-trường gốc, KHÔNG đọc `ProductionSpec`/scenes (tránh chuyển đổi khứ hồi
thừa: 8-field -> scenes -> verify -> [8-field lại] -> render).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..models import Fact
from .numbers import (
    find_word_number_phrases, has_approx_word, parse_digit_token,
    parse_vn_number_words, _DIGIT_MAGNITUDE_RE,
)

_APPROX_TOLERANCE = 0.05     # nới ≤5% CHỈ KHI số đi kèm từ xấp xỉ ngay trước — khớp
                              # _DEFAULT_APPROX_TOLERANCE ở agents/production.py cho nhất quán
_APPROX_LOOKBACK = 12        # số ký tự nhìn NGƯỢC trước số để tìm từ xấp xỉ, khớp _APPROX_LOOKBACK cũ


@dataclass
class ProductionScene:
    """1 "cảnh"/khối nội dung trong ProductionSpec. `role` = hook|body|outro
    (thứ tự kể chuyện). `visual_kind` = stat|list|comparison|quote|title —
    TRUNG LẬP, KHÔNG phải tên template (renderer tra `render.infographic.
    visual_kind_templates` để biết vẽ bằng gì, xem config/settings.yaml).
    `slots` = dữ liệu điền vào (hình dạng tuỳ visual_kind, vd stat:
    {"stats": [{"label","value"}, ...]}). `voice_text` CHỈ dùng cho video
    (Phase 2) — ảnh (Phase 1) luôn để rỗng, renderer bỏ qua field này."""
    role: str
    visual_kind: str
    slots: dict = field(default_factory=dict)
    voice_text: str = ""


@dataclass
class ProductionSpec:
    """Input DUY NHẤT cho renderer — xem docstring module. `facts` mang theo
    NGUYÊN VẸN kiểu `twmkt.models.Fact` (KHÔNG bịa schema số mới) — đây là
    "chân lý" để `verify_spec()` đối chiếu."""
    topic_key: str
    title: str
    source_url: str
    channel: str
    facts: list[Fact] = field(default_factory=list)
    scenes: list[ProductionScene] = field(default_factory=list)
    aspect: str = "4:5"
    variant: str = "infographic"


@dataclass
class Violation:
    """1 số KHÔNG khớp fact nào trong ProductionSpec.facts — verify_spec()
    trả list rỗng nếu spec SẠCH (không câu gọi nào cho biết "sạch" khác việc
    list rỗng, giống compliance.check())."""
    scene_index: int
    field: str      # tên slot (vd "stats[0].value") hoặc "voice_text"
    token: str       # cụm số/chữ bị flag (nguyên văn trong text, để audit)
    reason: str = "unmatched"   # để ngỏ mở rộng loại vi phạm khác sau này


def _fact_matches(value: float, facts: list[Fact], *, approx: bool) -> bool:
    tolerance = _APPROX_TOLERANCE if approx else 0.0
    for f in facts:
        if f.canonical_value is None:
            continue
        denom = abs(f.canonical_value) or 1e-9
        if abs(value - f.canonical_value) / denom <= tolerance:
            return True
    return False


def _check_text(text: str, facts: list[Fact], scene_index: int, field_name: str) -> list[Violation]:
    if not text:
        return []
    violations: list[Violation] = []
    seen: set[str] = set()

    for m in _DIGIT_MAGNITUDE_RE.finditer(text):
        tok = m.group(0)
        key = tok.lower().strip()
        if key in seen:
            continue
        val = parse_digit_token(tok)
        approx = has_approx_word(text[max(0, m.start() - _APPROX_LOOKBACK):m.start()])
        if val is None or not _fact_matches(val, facts, approx=approx):
            violations.append(Violation(scene_index, field_name, tok))
        seen.add(key)

    for phrase, start in find_word_number_phrases(text):
        key = phrase.lower().strip()
        if key in seen:
            continue
        val = parse_vn_number_words(phrase)
        approx = has_approx_word(text[max(0, start - _APPROX_LOOKBACK):start])
        if val is None or not _fact_matches(val, facts, approx=approx):
            violations.append(Violation(scene_index, field_name, phrase))
        seen.add(key)

    return violations


def _iter_slot_texts(slots: dict):
    """Duyệt MỌI chuỗi text trong `slots` (hình dạng lồng nhau tuỳ ý: str,
    list[str], list[dict], dict phẳng) -> (field_path, text). Hàm THUẦN, đệ
    quy nông (đủ cho các dạng slots thực tế: {"stats":[{"label","value"}]},
    {"title","subtitle"}, {"lines":[...]})."""
    for key, value in slots.items():
        if isinstance(value, str):
            yield key, value
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    for sub_key, sub_val in item.items():
                        if isinstance(sub_val, str):
                            yield f"{key}[{i}].{sub_key}", sub_val
                elif isinstance(item, str):
                    yield f"{key}[{i}]", item
        elif isinstance(value, dict):
            for sub_key, sub_val in value.items():
                if isinstance(sub_val, str):
                    yield f"{key}.{sub_key}", sub_val


def verify_spec(spec: ProductionSpec) -> list[Violation]:
    """Guardrail LẦN 2 (quyết định #1 Phase 1.0) — mọi số (dạng chữ số LẪN
    dạng chữ) trong `slots` và `voice_text` của MỌI scene phải khớp 1 mục
    trong `spec.facts` (số học, dung sai xấp xỉ nếu có từ xấp xỉ đứng ngay
    trước). Trả [] nếu spec SẠCH. Hàm THUẦN — không mạng, không LLM."""
    violations: list[Violation] = []
    for i, scene in enumerate(spec.scenes):
        for field_path, text in _iter_slot_texts(scene.slots):
            violations += _check_text(text, spec.facts, i, field_path)
        if scene.voice_text:
            violations += _check_text(scene.voice_text, spec.facts, i, "voice_text")
    return violations


def build_spec_from_content(output_data: dict, facts: list[Fact], *, topic_key: str,
                            title: str = "", source_url: str = "",
                            channel: str = "facebook_feed") -> ProductionSpec:
    """Dựng `ProductionSpec` (scenes[]) TỪ 8-trường Composer JSON (`CONTENT.
    Output`, SAU khi người có thể đã sửa tay ở Gate 2) + `facts` (`CONTENT.
    Facts`, Phase 1.3) — xem quy tắc ánh xạ ở docstring module. Dùng để
    `verify_spec()` (guardrail lần 2) TRƯỚC KHI RENDER — KHÔNG dùng để render
    trực tiếp (renderer SVG hiện có vẫn đọc `output_data` 8-trường gốc). Hàm
    THUẦN — không mạng, không LLM."""
    scenes = [
        ProductionScene(role="hook", visual_kind="title",
                        slots={"title": output_data.get("title", ""),
                               "subtitle": output_data.get("subtitle", "")}),
        ProductionScene(role="body", visual_kind="stat",
                        slots={"stats": output_data.get("hero") or []}),
        ProductionScene(role="body", visual_kind="list",
                        slots={"items": output_data.get("market") or []}),
        ProductionScene(role="outro", visual_kind="quote",
                        slots={"lines": output_data.get("highlights") or []}),
    ]
    aspect = (output_data.get("render_hint") or {}).get("ratio", "4:5")
    return ProductionSpec(
        topic_key=topic_key, title=title or output_data.get("title", ""),
        source_url=source_url, channel=channel, facts=facts,
        scenes=scenes, aspect=aspect, variant="infographic",
    )
