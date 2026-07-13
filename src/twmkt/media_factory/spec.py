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

import re
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
    """Content Factory Phase 1 — số TRONG BÀI khớp fact NẾU khớp BẤT KỲ trường
    canonical_* nào có mặt trên fact đó (KHÔNG còn chỉ scalar): canonical_value
    (shape=scalar) trong dung sai; NẰM TRONG [canonical_low, canonical_high]
    (shape=range, biên nới thêm `span * tolerance` CHỈ khi có từ xấp xỉ — số
    NẰM SẴN trong range luôn khớp dù không có từ xấp xỉ, đó là bản chất của
    range); khớp canonical_from HOẶC canonical_to (shape=delta — number trước/
    sau đều hợp lệ). shape=entity/entity_list KHÔNG có canonical_* số nào ->
    tự động bỏ qua ở đây, xem _check_plain_list_item_entity cho tên."""
    tolerance = _APPROX_TOLERANCE if approx else 0.0
    for f in facts:
        if f.canonical_value is not None:
            denom = abs(f.canonical_value) or 1e-9
            if abs(value - f.canonical_value) / denom <= tolerance:
                return True
        if f.canonical_low is not None and f.canonical_high is not None:
            lo, hi = sorted((f.canonical_low, f.canonical_high))
            slack = (hi - lo) * tolerance
            if lo - slack <= value <= hi + slack:
                return True
        if f.canonical_from is not None:
            denom = abs(f.canonical_from) or 1e-9
            if abs(value - f.canonical_from) / denom <= tolerance:
                return True
        if f.canonical_to is not None:
            denom = abs(f.canonical_to) or 1e-9
            if abs(value - f.canonical_to) / denom <= tolerance:
                return True
    return False


def _known_entity_names(facts: list[Fact]) -> list[str]:
    """Mọi TÊN đã biết VÀ ĐỦ ĐIỀU KIỆN lên hình (shape=entity: `value`;
    shape=entity_list: từng phần tử `entities[]`) — chuẩn hoá thường/trim để
    so khớp không phân biệt hoa/thường ở _check_plain_list_item_entity.

    Content Factory Phase 2b — CHỈ salience="subject" (chủ thể tin) HOẶC ""
    (dữ liệu CŨ trước Phase 2b, chưa phân loại — tương thích ngược ĐỌC, không
    coi là vi phạm mới) mới được coi "đã biết" ở đây. salience="context"
    (phông nền — hội thảo/hiệp hội/người phát biểu) bị LOẠI KHỎI danh sách này
    NGAY CẢ KHI tên đó THẬT/verify được trong facts[] — đây chính là guardrail
    "related/priority.primary CHỈ subject" (lỗi THẬT đã gặp: bài cảng biển
    related bị lấp bởi tên hội thảo/hiệp hội thay vì tên cảng/dự án thật).
    Composer nhét 1 tên context THẬT vào related vẫn bị flag ở ĐÂY — không chỉ
    dựa vào lời dặn trong prompt."""
    names: list[str] = []
    for f in facts:
        if f.salience == "context":
            continue
        if f.shape == "entity" and f.value.strip():
            names.append(f.value.strip().lower())
        elif f.shape == "entity_list":
            names.extend(e.strip().lower() for e in f.entities if e.strip())
    return names


_PLAIN_LIST_ITEM_RE = re.compile(r"^(\w+)\[\d+\]$")

# CHỈ những slot key này mới coi 1 phần tử CHUỖI THUẦN là TÊN thực thể cần đối
# chiếu — "lines"/"highlights" (và các key khác ngoài danh sách) là PROSE (câu
# hoàn chỉnh, vd "Doanh nghiệp đầu tiên báo lỗ trong ngành." — 0 chữ số nhưng
# KHÔNG phải tên riêng), quét nhầm sẽ flag oan MỌI câu không có số (đã tái hiện
# thật bằng test — xem test_check_plain_list_item_entity_ignores_prose_slot_keys).
# "priority_primary" (Content Factory Phase 2b) khác 3 key kia — hỗn hợp NHÃN
# hero/market (vd "GDP") LẪN tên thực thể subject (vd "Hải Phòng"), xem
# _known_stat_labels + verify_spec.
_ENTITY_LIST_SLOT_KEYS = frozenset({"names", "entities", "related", "priority_primary"})


def _known_stat_labels(spec: "ProductionSpec") -> set[str]:
    """Content Factory Phase 2b — mọi LABEL đã dùng ở hero/market (mọi scene,
    field_path dạng "key[i].label") — nguồn khớp HỢP LỆ THỨ 2 cho slot
    "priority_primary" (BÊN CẠNH _known_entity_names, xem _check_plain_list_
    item_entity) vì Composer được phép nhét CẢ nhãn hero/market LẪN tên thực
    thể subject vào priority.primary (KHÔNG chỉ tên). Hàm THUẦN."""
    labels: set[str] = set()
    for scene in spec.scenes:
        for field_path, text in _iter_slot_texts(scene.slots):
            if field_path.endswith(".label") and text:
                labels.add(text.strip().lower())
    return labels


def _check_plain_list_item_entity(text: str, facts: list[Fact], scene_index: int,
                                  field_name: str, extra_known: set[str] | None = None) -> list[Violation]:
    """Guardrail TÊN thực thể (Content Factory Phase 1, shape=entity/entity_list
    — "tên lạ = BỊA", nguy hiểm ngang bịa số). CHỈ áp cho `field_name` dạng
    "key[i]" VỚI key thuộc _ENTITY_LIST_SLOT_KEYS (1 phần tử CHUỖI THUẦN trong
    list ĐÍCH THỊ là danh sách tên, vd slots={"related": [...]})  — CỐ Ý KHÔNG
    quét MỌI list THUẦN CHUỖI (vd "highlights"/"lines" là PROSE, không phải tên
    riêng — quét nhầm gây false-positive nặng, xem docstring _ENTITY_LIST_
    SLOT_KEYS) và KHÔNG quét prose tự do (title/subtitle) vì không có cách đáng
    tin cậy phân biệt "tên riêng" với chữ thường trong tiếng Việt bằng regex
    thuần. text CÓ số -> bỏ qua ở đây (đã qua _check_text ở trên). `extra_known`
    (Phase 2b, dùng cho "priority_primary") — tập text HỢP LỆ BỔ SUNG ngoài tên
    thực thể (vd nhãn hero/market, xem _known_stat_labels) — khớp EITHER bên.
    FAIL-CLOSED giống _fact_matches: facts rỗng hoặc không có entity/entity_list
    nào -> KHÔNG có gì để khớp -> LUÔN flag (nhất quán triết lý "rỗng = nghi
    ngờ tối đa" của guardrail số, xem test_verify_spec_empty_facts_flags_
    everything_with_numbers)."""
    if not text or any(c.isdigit() for c in text):
        return []
    m = _PLAIN_LIST_ITEM_RE.match(field_name)
    if not m or m.group(1) not in _ENTITY_LIST_SLOT_KEYS:
        return []
    low = text.strip().lower()
    candidates = list(_known_entity_names(facts)) + list(extra_known or ())
    for name in candidates:
        if name and (name in low or low in name):
            return []
    return [Violation(scene_index, field_name, text, reason="unmatched_entity")]


def _check_text(text: str, facts: list[Fact], scene_index: int, field_name: str) -> list[Violation]:
    """Guardrail SỐ (Content Factory Phase 1 — nay khớp scalar/range/delta, xem
    _fact_matches) trên 1 chuỗi text — dạng CHỮ SỐ (_DIGIT_MAGNITUDE_RE) LẪN
    VIẾT BẰNG CHỮ (find_word_number_phrases). Guardrail TÊN (entity/entity_list)
    tách riêng ở _check_plain_list_item_entity — gọi Ở NƠI KHÁC (verify_spec),
    KHÔNG ở đây, vì chỉ áp cho field_name dạng "key[i]", không áp mọi text."""
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
    """Guardrail LẦN 2 (quyết định #1 Phase 1.0; mở rộng Content Factory Phase
    1 + 2b) — mọi SỐ (dạng chữ số LẪN dạng chữ, mọi shape scalar/range/delta)
    trong `slots` và `voice_text` của MỌI scene phải khớp 1 mục trong
    `spec.facts` (số học, dung sai xấp xỉ nếu có từ xấp xỉ đứng ngay trước, xem
    _fact_matches); MỌI TÊN thực thể trong 1 phần tử list THUẦN CHUỖI (field
    dạng "key[i]", vd slots={"related": [...]}) phải khớp 1 fact shape=entity/
    entity_list salience="subject" nào đó (xem _check_plain_list_item_entity —
    CỐ Ý không quét prose tự do, xem docstring hàm đó). Riêng slot
    "priority_primary" CŨNG được khớp với nhãn hero/market (xem _known_stat_
    labels) vì Composer được phép trộn nhãn + tên subject ở đó. Trả [] nếu
    spec SẠCH. Hàm THUẦN — không mạng, không LLM."""
    violations: list[Violation] = []
    stat_labels = _known_stat_labels(spec)
    for i, scene in enumerate(spec.scenes):
        for field_path, text in _iter_slot_texts(scene.slots):
            violations += _check_text(text, spec.facts, i, field_path)
            extra = stat_labels if field_path.startswith("priority_primary[") else None
            violations += _check_plain_list_item_entity(text, spec.facts, i, field_path, extra)
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
        # Content Factory Phase 2 — KÍCH HOẠT guardrail tên (media_factory/
        # spec._check_plain_list_item_entity): "related" (Output 8-field, đã
        # có sẵn nhưng TRƯỚC ĐÂY bị bỏ qua khỏi scenes -> guardrail lần 2 KHÔNG
        # BAO GIỜ quét được) giờ route vào slot key "related" — TRÙNG tên với
        # _ENTITY_LIST_SLOT_KEYS ở spec.py, để mỗi phần tử được đối chiếu với
        # facts[] shape=entity/entity_list — Composer bịa 1 tên KHÔNG có trong
        # facts[] sẽ bị verify_spec() bắt (Violation reason="unmatched_entity").
        ProductionScene(role="body", visual_kind="list",
                        slots={"related": output_data.get("related") or []}),
        # Content Factory Phase 2b — cùng lý do trên, cho "priority.primary"
        # (KHÔNG chỉ "related"): route vào slot key "priority_primary" ->
        # verify_spec() khớp với TÊN subject (_known_entity_names) HOẶC nhãn
        # hero/market (_known_stat_labels, Composer được phép trộn cả 2 ở đây).
        ProductionScene(role="body", visual_kind="list",
                        slots={"priority_primary": (output_data.get("priority") or {}).get("primary") or []}),
    ]
    aspect = (output_data.get("render_hint") or {}).get("ratio", "4:5")
    return ProductionSpec(
        topic_key=topic_key, title=title or output_data.get("title", ""),
        source_url=source_url, channel=channel, facts=facts,
        scenes=scenes, aspect=aspect, variant="infographic",
    )
