"""Production Factory — `ProductionSpec`: schema TRUNG LẬP NHÀ CUNG CẤP, CỦA
TA (KHÔNG dùng `TemplateScript`/`script.json` của vendor nào làm định dạng lõi
— quyết định kiến trúc #1, Phase 1.0). Đây là input DUY NHẤT cho renderer
(ảnh: `render/infographic.py` — SVG; video: adapter AIGEN — task SAU) — adapter
dịch `ProductionSpec` sang schema từng vendor nếu cần, KHÔNG sửa lõi.

QUYẾT ĐỊNH #1 Phase 1.0 (đã CHỐT, KHÔNG persist ProductionSpec):
  `ProductionSpec` là đối tượng DẪN XUẤT (derived) — dựng LẠI mỗi lần cần
  render, từ (CONTENT.Output hiện tại + facts[] đọc từ cột JSON MỚI trên
  CONTENT, neo TopicKey). KHÔNG đóng băng/ghi xuống data_root. `ProductionSpec`
  KHÔNG có hàm persist ở đây — nơi gọi tự build lại mỗi lần cần, rẻ vì đây là
  phép biến đổi CODE TẤT ĐỊNH, không LLM.

HAI TRỤC TÁCH BẠCH (rà soát ProductionSpec, chốt sau khi đối chiếu CATALOG.md
AIGEN thật — xem `../aigen-fva-capital/aigen/templates/CATALOG.md`):
  `ProductionBlock.block_kind` — trục KHỐI ĐỒNG THỜI, cho INFOGRAPHIC (ảnh
    tĩnh, nhiều block hiển thị CÙNG LÚC trên 1 canvas). Tập đóng 13 giá trị =
    NGUYÊN VĂN từ vựng `content_writer_rules.md` §5.4 (metric_cards/
    comparison_grid/timeline/map/flow/ranking/sector_matrix/before_after/
    progress_bar/donut/bar_chart/insight_cards/entity_map). ĐÃ ĐỐI CHIẾU thật
    với CATALOG.md AIGEN: **0/13 có template AIGEN tương ứng** — AIGEN là
    pipeline VIDEO-ONLY (README: "A Vietnamese article in. A 9:16 short out."),
    toàn bộ 15 template ở đó là scene-video (renderer "hyperframes"), KHÔNG có
    template ảnh tĩnh nào. Vì vậy `block_kind` KHÔNG map sang AIGEN — hợp đồng
    này dành cho renderer SVG NỘI BỘ (`render/infographic.py`), độc lập AIGEN.
  `ProductionScene.visual_kind` — trục THỜI GIAN, cho VIDEO (nhiều scene nối
    tiếp theo timeline). Tập đóng 9 giá trị (mở rộng từ 5, đối chiếu 15
    template AIGEN thật): title | stat | statement | list | comparison | quote
    | ticker | news | avatar | outro. `avatar` có trong tập nhưng
    **DEFERRED — chờ HeyGen, CHƯA kích hoạt** (template frame-avatar-presenter
    cần clip talking-head thật, chưa có nguồn). Bảng ánh xạ visual_kind ->
    templateId AIGEN (nhiều template/1 giá trị, adapter chọn) ghi ở
    `docs/HANDOFF.md` khi đóng task — KHÔNG đặt templateId trong spec (vendor-
    neutral tuyệt đối, quyết định #2).
  `ProductionSpec` mang CẢ HAI list (`blocks`, `scenes`) nhưng CHỈ MỘT được
  điền tuỳ `variant` ("infographic" -> blocks, "scenes"=[]; "video" -> scenes,
  "blocks"=[]) — KHÔNG trộn 2 trục trong 1 lần dựng.

CON TRỎ `fact_ref` (mỗi block/scene, Phase 2 — rà soát ProductionSpec):
  `list[int]` = index vào `spec.facts` mà block/scene đó RENDER RA — tính TẤT
  ĐỊNH lúc `build_spec_from_content()` (tái dùng logic khớp số/tên đã có, xem
  `_fact_ref_for_texts`). Con trỏ MỘT CHIỀU, KHÔNG nhân bản giá trị — `slots`
  vẫn là chuỗi đã render (KHÔNG đổi cấu trúc thành {value, fact_index}, quyết
  định rà soát ProductionSpec điểm B). Ai đọc: guardrail-2 (thu hẹp phạm vi so
  khớp thay vì quét toàn `facts[]`), renderer/adapter tương lai (tra
  `entity_type`/`shape` của fact để chọn cách vẽ item). fact_ref chỉ hợp lệ
  TRONG 1 lần dựng (index vào list `facts` của CHÍNH spec đó) — nhất quán với
  "dẫn xuất, không persist".

GUARDRAIL CHẠY 2 LẦN (quyết định #1 Phase 1.0):
  (a) Ngay sau Composer, TRƯỚC Gate 2 — ĐÃ CÓ, xem agents/production.py:
      apply_guardrails()/unsupported_numbers().
  (b) `verify_spec()` Ở ĐÂY — chạy TRƯỚC KHI RENDER, trên `ProductionSpec`
      dựng LẠI từ CONTENT.Output SAU KHI người có thể đã sửa tay ở Gate 2 +
      facts[] đọc từ cột Sheet. Trượt -> KHÔNG render (NEEDS_HUMAN).
  `verify_spec()` kiểm CẢ số dạng CHỮ SỐ LẪN VIẾT BẰNG CHỮ trong MỌI `slots`
  của MỌI block/scene VÀ `voice_text` của MỌI scene — số không khớp
  `facts[].canonical_*` nào (dung sai xấp xỉ nếu có từ "gần/khoảng/..." đứng
  ngay trước) -> `Violation`. Alias-theo-kênh (cấm ticker/viết-tắt trong
  `voice_text`) là validator CỨNG còn NỢ — Phase 3 riêng của task này, CHƯA
  làm ở Phase 2.

`build_spec_from_content()` — dựng `ProductionSpec` TỪ 8-trường Composer JSON
(`CONTENT.Output`, SAU khi người có thể đã sửa tay ở Gate 2) + `facts` theo
quy tắc ánh xạ TẤT ĐỊNH: title+subtitle -> block hook (block_kind="", KHÔNG
phải chart component) | hero -> block body (metric_cards, theo ví dụ §5.4) |
market -> block body (comparison_grid, theo ví dụ §5.4) | highlights -> block
outro (insight_cards, theo ví dụ §5.4) | related -> block body (entity_map —
suy luận, §5.4 không có ví dụ) | priority.primary -> block body (ranking — suy
luận, tên "priority" khớp ngữ nghĩa "xếp hạng ưu tiên"). CHỈ build blocks[]
(nhánh video/scenes[] chưa có nguồn dữ liệu — VideoScriptAgent chưa nối vào
đây, ngoài scope). Dùng ĐỂ VERIFY (guardrail lần 2) — renderer SVG hiện có vẫn
đọc THẲNG `output_data` 8-trường gốc, KHÔNG đọc `ProductionSpec`/blocks (tránh
chuyển đổi khứ hồi thừa).
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

# Tập đóng block_kind (infographic, trục KHỐI ĐỒNG THỜI) — NGUYÊN VĂN
# content_writer_rules.md §5.4, ĐÃ đối chiếu CATALOG.md AIGEN: 0/13 có
# template AIGEN — hợp đồng này dành cho renderer SVG nội bộ, không phải AIGEN.
BLOCK_KINDS = frozenset({
    "metric_cards", "comparison_grid", "timeline", "map", "flow", "ranking",
    "sector_matrix", "before_after", "progress_bar", "donut", "bar_chart",
    "insight_cards", "entity_map",
})

# Tập đóng visual_kind (video, trục THỜI GIAN) — mở rộng 5->9 sau khi đối
# chiếu 15 template AIGEN thật (xem docstring module).
VISUAL_KINDS = frozenset({
    "title", "stat", "statement", "list", "comparison", "quote",
    "ticker", "news", "avatar", "outro",
})

# "avatar" (frame-avatar-presenter) nằm TRONG VISUAL_KINDS nhưng CHƯA kích
# hoạt — cần clip talking-head thật (chờ HeyGen), build_spec_from_content
# hiện tại không có nguồn scene video nên KHÔNG sinh giá trị nào từ tập này.
DEFERRED_VISUAL_KINDS = frozenset({"avatar"})


@dataclass
class ProductionBlock:
    """1 khối trong ẢNH infographic (nhiều block hiển thị ĐỒNG THỜI trên 1
    canvas — trục KHỐI, xem docstring module). `role` = hook|body|outro (vị
    trí bố cục). `block_kind` = 1 trong `BLOCK_KINDS`, hoặc "" cho block THUẦN
    CHỮ không phải chart component (vd tiêu đề). `slots` = dữ liệu điền vào
    (chuỗi đã render, hình dạng tuỳ block). `fact_ref` = index vào
    `ProductionSpec.facts` mà block này render ra (xem docstring module)."""
    role: str
    block_kind: str
    slots: dict = field(default_factory=dict)
    fact_ref: list[int] = field(default_factory=list)


@dataclass
class ProductionScene:
    """1 cảnh trong VIDEO (nhiều scene nối tiếp theo TIMELINE — trục thời
    gian, xem docstring module). `role` = hook|body|outro (vị trí trong
    timeline). `visual_kind` = 1 trong `VISUAL_KINDS` (TRUNG LẬP, KHÔNG phải
    tên template — AigenAdapter, task sau, chọn 1 trong nhiều template AIGEN
    cùng visual_kind, xem HANDOFF.md). `slots` = on-screen text nếu có.
    `voice_text` = lời thoại — guardrail-2 Phase 3 (chưa làm ở đây) sẽ cấm
    ticker/viết-tắt tại đây (alias ĐƯỢC phép ở `slots`, CẤM ở `voice_text`).
    `fact_ref` = index vào `ProductionSpec.facts`."""
    role: str
    visual_kind: str
    slots: dict = field(default_factory=dict)
    voice_text: str = ""
    fact_ref: list[int] = field(default_factory=list)


@dataclass
class ProductionSpec:
    """Input DUY NHẤT cho renderer — xem docstring module. `facts` mang theo
    NGUYÊN VẸN kiểu `twmkt.models.Fact` (KHÔNG bịa schema số mới) — đây là
    "chân lý" để `verify_spec()` đối chiếu. CHỈ MỘT trong `blocks`/`scenes`
    được điền tuỳ `variant` — không trộn 2 trục (xem docstring module)."""
    topic_key: str
    title: str
    source_url: str
    channel: str
    facts: list[Fact] = field(default_factory=list)
    blocks: list[ProductionBlock] = field(default_factory=list)
    scenes: list[ProductionScene] = field(default_factory=list)
    aspect: str = "4:5"
    variant: str = "infographic"


@dataclass
class Violation:
    """1 số/tên KHÔNG khớp fact nào trong ProductionSpec.facts — verify_spec()
    trả list rỗng nếu spec SẠCH. `scene_index` = vị trí trong list ĐÃ quét
    (`spec.blocks` cho infographic, `spec.scenes` cho video — 1 spec chỉ có 1
    trong 2 list khác rỗng nên không mơ hồ, xem docstring module)."""
    scene_index: int
    field: str      # tên slot (vd "stats[0].value") hoặc "voice_text"
    token: str       # cụm số/chữ bị flag (nguyên văn trong text, để audit)
    reason: str = "unmatched"   # để ngỏ mở rộng loại vi phạm khác sau này


def _fact_index_matching(value: float, facts: list[Fact], *, approx: bool) -> int | None:
    """Content Factory Phase 1 — index fact ĐẦU TIÊN khớp `value` theo BẤT KỲ
    trường canonical_* nào có mặt (scalar/range/delta), hoặc None nếu không
    fact nào khớp. Nguyên hàm khớp của `_fact_matches` (Phase 2 tách ra để
    `_fact_ref_for_texts` tái dùng — cần biết fact NÀO khớp, không chỉ có/
    không)."""
    tolerance = _APPROX_TOLERANCE if approx else 0.0
    for i, f in enumerate(facts):
        if f.canonical_value is not None:
            denom = abs(f.canonical_value) or 1e-9
            if abs(value - f.canonical_value) / denom <= tolerance:
                return i
        if f.canonical_low is not None and f.canonical_high is not None:
            lo, hi = sorted((f.canonical_low, f.canonical_high))
            slack = (hi - lo) * tolerance
            if lo - slack <= value <= hi + slack:
                return i
        if f.canonical_from is not None:
            denom = abs(f.canonical_from) or 1e-9
            if abs(value - f.canonical_from) / denom <= tolerance:
                return i
        if f.canonical_to is not None:
            denom = abs(f.canonical_to) or 1e-9
            if abs(value - f.canonical_to) / denom <= tolerance:
                return i
    return None


def _fact_matches(value: float, facts: list[Fact], *, approx: bool) -> bool:
    """Content Factory Phase 1 — số TRONG BÀI khớp fact NÀO ĐÓ (xem
    _fact_index_matching cho quy tắc khớp từng shape). shape=entity/
    entity_list KHÔNG có canonical_* số nào -> tự động bỏ qua ở đây, xem
    _check_plain_list_item_entity cho tên."""
    return _fact_index_matching(value, facts, approx=approx) is not None


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
    """Content Factory Phase 2b — mọi LABEL đã dùng ở hero/market (mọi block,
    field_path dạng "key[i].label") — nguồn khớp HỢP LỆ THỨ 2 cho slot
    "priority_primary" (BÊN CẠNH _known_entity_names, xem _check_plain_list_
    item_entity) vì Composer được phép nhét CẢ nhãn hero/market LẪN tên thực
    thể subject vào priority.primary (KHÔNG chỉ tên). Quét `spec.blocks`
    (infographic — "priority_primary" là khái niệm infographic-only, video
    không có slot này). Hàm THUẦN."""
    labels: set[str] = set()
    for block in spec.blocks:
        for field_path, text in _iter_slot_texts(block.slots):
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


def _fact_ref_for_texts(texts: list[str], facts: list[Fact]) -> list[int]:
    """Rà soát ProductionSpec, Phase 2 — tính TẤT ĐỊNH index vào `facts` mà 1
    tập text (toàn bộ text trong `slots` của 1 block/scene) THAM CHIẾU tới.
    Tái dùng CHÍNH logic khớp guardrail (_fact_index_matching cho số,
    entity/entity_list.value/.entities cho tên) — con trỏ MỘT CHIỀU, không
    nhân bản giá trị (xem docstring module). CỐ Ý khớp tên KHÔNG lọc theo
    salience (khác _known_entity_names) — đây là con trỏ THAM KHẢO "text này
    ứng với fact nào", không phải guardrail đúng/sai (guardrail đúng/sai vẫn ở
    verify_spec/_check_plain_list_item_entity); 1 fact salience=context xuất
    hiện HỢP LỆ trong prose (vd "highlights") vẫn cần fact_ref trỏ đúng."""
    refs: list[int] = []
    for text in texts:
        if not text:
            continue
        for m in _DIGIT_MAGNITUDE_RE.finditer(text):
            val = parse_digit_token(m.group(0))
            if val is None:
                continue
            idx = _fact_index_matching(val, facts, approx=False)
            if idx is not None and idx not in refs:
                refs.append(idx)
        for phrase, _ in find_word_number_phrases(text):
            val = parse_vn_number_words(phrase)
            if val is None:
                continue
            idx = _fact_index_matching(val, facts, approx=False)
            if idx is not None and idx not in refs:
                refs.append(idx)
        low = text.strip().lower()
        for fi, f in enumerate(facts):
            if fi in refs:
                continue
            if f.shape == "entity" and f.value.strip() and f.value.strip().lower() in low:
                refs.append(fi)
            elif f.shape == "entity_list":
                if any(e.strip() and e.strip().lower() in low for e in f.entities):
                    refs.append(fi)
    return refs


def verify_spec(spec: ProductionSpec) -> list[Violation]:
    """Guardrail LẦN 2 (quyết định #1 Phase 1.0; mở rộng Content Factory Phase
    1 + 2b) — mọi SỐ (dạng chữ số LẪN dạng chữ, mọi shape scalar/range/delta)
    trong `slots` của MỌI block/scene VÀ `voice_text` của MỌI scene phải khớp
    1 mục trong `spec.facts` (số học, dung sai xấp xỉ nếu có từ xấp xỉ đứng
    ngay trước, xem _fact_matches); MỌI TÊN thực thể trong 1 phần tử list
    THUẦN CHUỖI (field dạng "key[i]", vd slots={"related": [...]}) phải khớp 1
    fact shape=entity/entity_list salience="subject" nào đó (xem
    _check_plain_list_item_entity). Riêng slot "priority_primary" CŨNG được
    khớp với nhãn hero/market (xem _known_stat_labels). Quét CẢ `spec.blocks`
    (infographic) LẪN `spec.scenes` (video) — 1 spec thường chỉ có 1 trong 2
    khác rỗng (xem docstring module), quét cả hai vô hại nếu rỗng. Trả [] nếu
    spec SẠCH. Alias-theo-kênh (ticker cấm trong voice_text) CHƯA làm ở đây —
    Phase 3 riêng. Hàm THUẦN — không mạng, không LLM."""
    violations: list[Violation] = []
    stat_labels = _known_stat_labels(spec)
    for i, block in enumerate(spec.blocks):
        for field_path, text in _iter_slot_texts(block.slots):
            violations += _check_text(text, spec.facts, i, field_path)
            extra = stat_labels if field_path.startswith("priority_primary[") else None
            violations += _check_plain_list_item_entity(text, spec.facts, i, field_path, extra)
    for i, scene in enumerate(spec.scenes):
        for field_path, text in _iter_slot_texts(scene.slots):
            violations += _check_text(text, spec.facts, i, field_path)
            violations += _check_plain_list_item_entity(text, spec.facts, i, field_path)
        if scene.voice_text:
            violations += _check_text(scene.voice_text, spec.facts, i, "voice_text")
    return violations


def build_spec_from_content(output_data: dict, facts: list[Fact], *, topic_key: str,
                            title: str = "", source_url: str = "",
                            channel: str = "facebook_feed") -> ProductionSpec:
    """Dựng `ProductionSpec` (blocks[], nhánh infographic) TỪ 8-trường Composer
    JSON (`CONTENT.Output`, SAU khi người có thể đã sửa tay ở Gate 2) + `facts`
    (`CONTENT.Facts`) theo quy tắc ánh xạ TẤT ĐỊNH — xem docstring module cho
    lý do chọn từng block_kind. `fact_ref` mỗi block tính qua
    `_fact_ref_for_texts`. `scenes` luôn rỗng (nhánh video chưa có nguồn dữ
    liệu — VideoScriptAgent chưa nối vào đây, ngoài scope task này). Dùng ĐỂ
    VERIFY (guardrail lần 2) TRƯỚC KHI RENDER — KHÔNG dùng để render trực tiếp
    (renderer SVG hiện có vẫn đọc `output_data` 8-trường gốc). Hàm THUẦN —
    không mạng, không LLM."""
    block_defs = [
        ("hook", "", {"title": output_data.get("title", ""),
                      "subtitle": output_data.get("subtitle", "")}),
        ("body", "metric_cards", {"stats": output_data.get("hero") or []}),
        ("body", "comparison_grid", {"items": output_data.get("market") or []}),
        ("outro", "insight_cards", {"lines": output_data.get("highlights") or []}),
        # Content Factory Phase 2 — KÍCH HOẠT guardrail tên (spec._check_plain_
        # list_item_entity): "related" route vào slot key "related" — TRÙNG
        # tên với _ENTITY_LIST_SLOT_KEYS, để mỗi phần tử được đối chiếu với
        # facts[] shape=entity/entity_list. block_kind="entity_map" — suy luận
        # (§5.4 không có ví dụ cho "related"): danh sách tên thực thể gắn với
        # chủ đề khớp ngữ nghĩa "entity_map" hơn "ranking" (không có thứ tự).
        ("body", "entity_map", {"related": output_data.get("related") or []}),
        # Content Factory Phase 2b — cùng lý do trên, cho "priority.primary".
        # block_kind="ranking" — suy luận: tên "priority" (ưu tiên) khớp ngữ
        # nghĩa "ranking" (danh sách có thứ tự quan trọng) hơn "entity_map".
        ("body", "ranking", {"priority_primary": (output_data.get("priority") or {}).get("primary") or []}),
    ]
    blocks = [
        ProductionBlock(
            role=role, block_kind=block_kind, slots=slots,
            fact_ref=_fact_ref_for_texts([text for _, text in _iter_slot_texts(slots)], facts),
        )
        for role, block_kind, slots in block_defs
    ]
    aspect = (output_data.get("render_hint") or {}).get("ratio", "4:5")
    return ProductionSpec(
        topic_key=topic_key, title=title or output_data.get("title", ""),
        source_url=source_url, channel=channel, facts=facts,
        blocks=blocks, scenes=[], aspect=aspect, variant="infographic",
    )
