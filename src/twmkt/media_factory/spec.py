"""Production Factory — `ProductionSpec`: schema TRUNG LẬP NHÀ CUNG CẤP, CỦA
TA (KHÔNG dùng `TemplateScript`/`script.json` của vendor nào làm định dạng lõi
— quyết định kiến trúc #1, Phase 1.0). Input DUY NHẤT cho pipeline VIDEO
(adapter AIGEN dịch `ProductionSpec` sang schema vendor nếu cần, KHÔNG sửa lõi).

ĐẢO HƯỚNG INFOGRAPHIC (2026-07-21, QUYẾT ĐỊNH LEAD — xem
docs/VPS_MIGRATION_BACKLOG.md): trục `ProductionBlock`/`block_kind` (13 giá
trị, guardrail-2 nhánh ẢNH cũ) ĐÃ XOÁ KHỎI CODE cùng lượt chuyển renderer
Infographic sang AI-only (`render/ai_full.py`, model gpt-image-2) — spike xác
nhận `block_kind` CHƯA TỪNG map sang AIGEN (0/13 có template tương ứng, xem
lịch sử git nếu cần đối chiếu lại lý do gốc) và renderer SVG dùng nó
(`render/infographic.py::render_infographic_svg`) giờ CHỈ còn phục vụ
`render_mode="hybrid"` (giữ chạy được, không phát triển thêm) — không còn là
đường sản xuất chính nên guardrail-2 riêng cho nó (`build_spec_from_content()`,
nhánh `spec.blocks` của `verify_spec()`) không còn cần thiết. `ProductionSpec`
từ đây CHỈ còn phục vụ trục VIDEO (`scenes`).

QUYẾT ĐỊNH #1 Phase 1.0 (đã CHỐT, KHÔNG persist ProductionSpec):
  `ProductionSpec` là đối tượng DẪN XUẤT (derived) — dựng LẠI mỗi lần cần
  render, từ (CONTENT.Output hiện tại + facts[] đọc từ cột JSON MỚI trên
  CONTENT, neo TopicKey). KHÔNG đóng băng/ghi xuống data_root. `ProductionSpec`
  KHÔNG có hàm persist ở đây — nơi gọi tự build lại mỗi lần cần, rẻ vì đây là
  phép biến đổi CODE TẤT ĐỊNH, không LLM.

`ProductionScene.visual_kind` — trục THỜI GIAN, cho VIDEO (nhiều scene nối
tiếp theo timeline). Tập đóng 10 giá trị (mở rộng từ 5, đối chiếu 15 template
AIGEN thật): title | stat | statement | list | comparison | quote | ticker |
news | avatar | outro. `avatar` có trong tập nhưng **DEFERRED — chờ HeyGen,
CHƯA kích hoạt** (template frame-avatar-presenter cần clip talking-head thật,
chưa có nguồn). Bảng ánh xạ visual_kind -> templateId AIGEN (nhiều template/1
giá trị, adapter chọn) ghi ở `docs/HANDOFF.md` khi đóng task — KHÔNG đặt
templateId trong spec (vendor-neutral tuyệt đối, quyết định #2).

CON TRỎ `fact_ref` (mỗi scene, Phase 2 — rà soát ProductionSpec):
  `list[int]` = index vào `spec.facts` mà scene đó RENDER RA — tính TẤT ĐỊNH
  (tái dùng logic khớp số/tên đã có, xem `_fact_ref_for_texts`). Con trỏ MỘT
  CHIỀU, KHÔNG nhân bản giá trị — `slots` vẫn là chuỗi đã render. Ai đọc:
  guardrail-2 (thu hẹp phạm vi so khớp thay vì quét toàn `facts[]`),
  renderer/adapter tương lai (tra `entity_type`/`shape` của fact để chọn cách
  vẽ item). fact_ref chỉ hợp lệ TRONG 1 lần dựng (index vào list `facts` của
  CHÍNH spec đó) — nhất quán với "dẫn xuất, không persist".

GUARDRAIL CHẠY 2 LẦN (quyết định #1 Phase 1.0):
  (a) Ngay sau Composer, TRƯỚC Gate 2 — ĐÃ CÓ, xem agents/production.py:
      apply_guardrails()/unsupported_numbers().
  (b) `verify_spec()` Ở ĐÂY — chạy TRƯỚC KHI RENDER, trên `ProductionSpec`
      dựng LẠI từ CONTENT.Output SAU KHI người có thể đã sửa tay ở Gate 2 +
      facts[] đọc từ cột Sheet. Trượt -> KHÔNG render (NEEDS_HUMAN).
  `verify_spec()` kiểm CẢ số dạng CHỮ SỐ LẪN VIẾT BẰNG CHỮ trong MỌI `slots`
  của MỌI scene VÀ `voice_text` của MỌI scene — số không khớp
  `facts[].canonical_*` nào (dung sai xấp xỉ nếu có từ "gần/khoảng/..." đứng
  ngay trước) -> `Violation`. Alias-theo-kênh (cấm ticker/viết-tắt trong
  `voice_text`) là validator CỨNG còn NỢ — Phase 3 riêng của task này, CHƯA
  làm ở Phase 2.
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

# Tập đóng visual_kind (video, trục THỜI GIAN) — mở rộng 5->9 sau khi đối
# chiếu 15 template AIGEN thật (xem docstring module).
VISUAL_KINDS = frozenset({
    "title", "stat", "statement", "list", "comparison", "quote",
    "ticker", "news", "avatar", "outro",
})

# "avatar" (frame-avatar-presenter) nằm TRONG VISUAL_KINDS nhưng CHƯA kích
# hoạt — cần clip talking-head thật (chờ HeyGen), chưa có nguồn nào sinh giá
# trị này (VideoScriptAgent chưa nối ProductionSpec.scenes[]).
DEFERRED_VISUAL_KINDS = frozenset({"avatar"})


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
    """Input DUY NHẤT cho pipeline video — xem docstring module. `facts` mang
    theo NGUYÊN VẸN kiểu `twmkt.models.Fact` (KHÔNG bịa schema số mới) — đây
    là "chân lý" để `verify_spec()` đối chiếu."""
    topic_key: str
    title: str
    source_url: str
    channel: str
    facts: list[Fact] = field(default_factory=list)
    scenes: list[ProductionScene] = field(default_factory=list)
    aspect: str = "4:5"
    variant: str = "video"


@dataclass
class Violation:
    """1 số/tên KHÔNG khớp fact nào trong ProductionSpec.facts — verify_spec()
    trả list rỗng nếu spec SẠCH. `scene_index` = vị trí trong `spec.scenes`
    ĐÃ quét."""
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
    1) — mọi SỐ (dạng chữ số LẪN dạng chữ, mọi shape scalar/range/delta) trong
    `slots` của MỌI scene VÀ `voice_text` của MỌI scene phải khớp 1 mục trong
    `spec.facts` (số học, dung sai xấp xỉ nếu có từ xấp xỉ đứng ngay trước, xem
    _fact_matches); MỌI TÊN thực thể trong 1 phần tử list THUẦN CHUỖI (field
    dạng "key[i]", vd slots={"related": [...]}) phải khớp 1 fact shape=entity/
    entity_list salience="subject" nào đó (xem _check_plain_list_item_entity).
    Trả [] nếu spec SẠCH. Alias-theo-kênh (ticker cấm trong voice_text) CHƯA
    làm ở đây — Phase 3 riêng. Hàm THUẦN — không mạng, không LLM."""
    violations: list[Violation] = []
    for i, scene in enumerate(spec.scenes):
        for field_path, text in _iter_slot_texts(scene.slots):
            violations += _check_text(text, spec.facts, i, field_path)
            violations += _check_plain_list_item_entity(text, spec.facts, i, field_path)
        if scene.voice_text:
            violations += _check_text(scene.voice_text, spec.facts, i, "voice_text")
    return violations
