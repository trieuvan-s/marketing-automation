"""Research/Brief (Phase 2, CLAUDE.md lộ trình v3) — đọc evidence thô (full-fetch,
$0, tất định) -> content_units[] đã gắn NHÃN NGHĨA, dùng model alias 'brief'
(rẻ, Haiku qua factory.make_llm/step_model). Đây là bước MỚI, đứng GIỮA
full-fetch evidence và Production 3 agent (agents/production.py) — SỬA GỐC lý
do InfographicSpecAgent cũ chỉ trích được nhãn vô nghĩa "Số liệu N" (regex mù
trên text thô, xem _MAGNITUDE_RE ở production.py).

KHÔNG hợp nhất với ResearchBrief/Researcher (models.py, agents/researcher.py) —
đường Hook/Luồng B RAG giữ NGUYÊN, không đụng. ContentUnit/content_units[]
(models.ContentUnit) là data contract RIÊNG, chỉ chảy vào ProductionBrief.
content_units.

KHÔNG dùng LLMRouter/Tier (đó là cơ chế đo chi phí cho đường Hook/Producer cũ) —
gọi thẳng LLMClient (factory.make_llm) qua complete(..., model=step_model(...)).
Bước 'brief' là bước PHỤ -> KHÔNG fail_loud (factory.is_fail_loud_step trả False
mặc định) -> lỗi/rỗng LÙI MƯỢT về content_units=[] (KHÔNG crash; ProductionBrief.
content_units rỗng vẫn hợp lệ, InfographicSpecAgent cũ vẫn chạy y nguyên bằng
evidence thô).

CHỐNG BỊA (verify_fact_in_evidence): mỗi content_unit SỐ PHẢI verify được TRONG
EVIDENCE THẬT — không có câu nguồn xác nhận thì LOẠI đơn vị đó (KHÔNG BAO GIỜ
tin field "source"/câu trích do chính LLM tự báo — CODE luôn tự tìm lại câu
nguồn bằng tìm-chuỗi biên-an-toàn, nhất quán "AI hiểu ở Brief, CODE phán ở
Guardrail"). Đơn vị ĐỊNH TÍNH (type != "numeric", Phase C bước 3) verify khác
cơ chế — xem _parse_qualitative_unit/_verify_source_substring bên dưới.

CONTENT FACTORY PHASE 2 (chặn gốc (a) — "prompt Brief bảo tóm tắt thay vì vét
cạn"): thay `_SYSTEM` cũ (chỉ 1 shape "scalar", ~8 kind, KHÔNG khoảng/biến
thiên/danh sách thực thể) bằng prompt VÉT CẠN 5 shape SỐ (models.FACT_SHAPES —
scalar|range|delta|entity_list|entity, Content Factory Phase 1) + (Phase C
bước 3) các TYPE ĐỊNH TÍNH (models.CONTENT_UNIT_TYPES). Mục tiêu 8-15 đơn vị/
bài THẬT (không phải 2) — bài nghèo dữ liệu thì ít hơn nhưng LLM phải tự báo
`scan_note` xác nhận đã quét hết, KHÔNG được dừng sớm ngầm.

QUY TẮC VERIFY THEO SHAPE SỐ (CODE, KHÔNG tin AI phán) — xem content_units_
from_llm_output:
  scalar      : value(+unit) PHẢI tìm được câu evidence chứa nó (như cũ).
  range       : value_low VÀ value_high PHẢI CÙNG xuất hiện trong 1 câu (chống
                ghép 2 số KHÔNG liên quan tình cờ cùng có mặt đâu đó thành 1
                range bịa) — xem _find_shared_sentence.
  delta       : from_value VÀ to_value PHẢI CÙNG xuất hiện trong 1 câu (cùng lý
                do trên). canonical_from/to = None nếu không phải số (vd đổi
                trạng thái "diện kiểm soát" -> "diện cảnh báo", không phải lỗi).
                Phase C bước 3 (R3): 2 số LIÊN QUAN nhưng ở 2 CÂU KHÁC NHAU
                KHÔNG được ép chung 1 delta — prompt dặn LLM tách 2 scalar
                riêng thay vì paraphrase lại để ép vừa 1 câu (_find_shared_
                sentence GIỮ NGUYÊN KHÔNG NỚI).
  entity_list : MỖI phần tử `entities[]` PHẢI verify riêng (tìm được câu chứa
                nó) — phần tử KHÔNG verify được bị LOẠI KHỎI DANH SÁCH (không
                loại cả đơn vị, trừ khi danh sách rỗng sau lọc). source = câu
                của phần tử ĐẦU TIÊN còn sống sót.
  entity      : value PHẢI tìm được câu evidence chứa nó (như scalar).
`entity_type` (shape=entity) validate theo `guardrail.entity_types` (config,
KHÔNG hard-code — xem run_brief(settings=...)) — giá trị lạ -> "other" (KHÔNG
loại đơn vị, chỉ hạ cấp phân loại hiển thị).

QUY TẮC VERIFY CONTENT_UNIT ĐỊNH TÍNH (type != "numeric", Phase C bước 3) —
xem _parse_qualitative_unit: `source` PHẢI là SUBSTRING của văn bản nguồn SAU
CHUẨN HOÁ KHOẢNG TRẮNG (không phải tìm-câu như shape số — đơn vị định tính
không có "value" số để neo biên an toàn, chuẩn hoá khoảng trắng là sàn chống
bịa RẺ + TẤT ĐỊNH tương đương). Không khớp -> LOẠI, KHÔNG loại cả lượt gọi.
`subject`/`claim` BẮT BUỘC khác rỗng (thiếu 1 trong 2 -> LOẠI, đây là sàn
chống boilerplate — trang rỗng không có gì để LLM điền `claim` có ý nghĩa).
`evidence` (CONTENT_UNIT_EVIDENCE_LEVELS: direct_quote|paraphrase|derived|
inferred) do LLM tự gán theo quy tắc trong _system_prompt, KHÔNG code verify
lại (khác `source`, vốn có thể verify tất định bằng substring — "claim diễn
đạt lại đúng mức nào so với source" là phán đoán ngữ nghĩa, không tất định
hoá được rẻ tương đương).

PHASE 4.8 MỤC C — SỐ CANONICAL ("AI hiểu ở Brief, CODE phán ở Guardrail"):
LLM trả THÊM field "raw" (cụm nguyên văn value+unit, COPY Y NGUYÊN từ văn bản,
kể cả từ xấp xỉ nếu có, vd "gần 600 tỷ đồng" — CHỈ áp cho shape=scalar, xem
docstring _SYSTEM) và "approx" (bool, có từ xấp xỉ hay không, áp cho scalar/
range/delta). CODE (KHÔNG phải AI) tính canonical_value/canonical_low/
canonical_high/canonical_from/canonical_to = số học THẬT từ value+unit
(agents/_numeric.parse_magnitude_token) — không tin AI làm toán.

PHASE 4.12 — PHÂN BIỆT content_units=[] RỖNG-HỢP-LỆ vs RỖNG-DO-HỎNG: trước
phase này, facts=[] (tên cũ) chỉ có 1 nghĩa (Brief lỗi/timeout/parse hỏng) ->
caller (scripts/produce_from_sheet.run) coi MỌI facts rỗng là NEEDS_HUMAN, kể
cả khi tin THẬT SỰ không có tuyên bố định lượng nào (vd bình luận/phân tích
xu hướng thuần định tính) — OAN cho những tin này. `no_numeric_content` (cờ
LLM tự xác nhận, GIỮ NGUYÊN cơ chế) là bước đầu xử vấn đề này; Phase C thay
bằng `brief_status` 3 giá trị làm nguồn suy luận CHÍNH — xem BriefResult.

PHASE C (content_unit contract, quyết định Lead 2026-07-3x — reports/LEAD_
DECISION_INPUT_STRICTNESS.md §4.1/§5/§6-P0, file đã xoá sau khi đọc xong) +
ĐỔI TÊN DỨT ĐIỂM (quyết định Lead 31/07, content_units complete) — KHÔNG còn
tên cũ `Fact`/`facts`/`.facts` property nào trong code Python (dữ liệu hiện
tại là dữ liệu TEST, được phép đổi schema dứt điểm, không cần tương thích
ngược). `brief_status` (OK|NO_USABLE_CONTENT|FAILED, xem BriefResult
docstring) THAY `no_numeric_content` làm nguồn SUY LUẬN CHÍNH cho caller —
đóng đúng gap Phase 4.12 để lọt: no_numeric_content=False vốn dùng CHUNG cho
CẢ "Brief hỏng thật" LẪN "đọc được nhưng nguồn boilerplate/rỗng tuếch" (2
tình huống khác hẳn nhau, gộp làm 1 khiến nguồn boilerplate rơi vào NEEDS_
HUMAN thay vì SKIPPED — xác nhận THẬT qua test hồi quy Phase B). `no_numeric_
content` GIỮ NGUYÊN cơ chế cũ (LLM tự xác nhận, code không suy diễn) — chỉ
KHÔNG CÒN là field DUY NHẤT caller đọc để quyết định.

Bước 3 (content_unit ĐỊNH TÍNH) xây parser thật cho type != "numeric" (xem
_parse_qualitative_unit) — `has_numeric_units`/`has_qualitative_units` giờ có
dữ liệu định tính thật để phản ánh (không còn luôn False như trước bước 3).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from ._jsonparse import try_json_object
from ._numeric import has_approx_word, parse_magnitude_token
from ..models import (
    CONTENT_UNIT_EVIDENCE_LEVELS, CONTENT_UNIT_TYPES, FACT_KINDS, FACT_SHAPES, ContentUnit,
)
from .base import LLMClient


@dataclass
class BriefResult:
    """Output run_brief()/content_units_from_llm_output() — content_units[] +
    `brief_status` (Phase C — thay `no_numeric_content` làm nguồn SUY LUẬN
    chính, xem dưới) + cờ phụ trợ. Xem docstring module.

    PHASE C (content_unit contract) — `brief_status` là 3 GIÁ TRỊ tường minh
    (KHÔNG còn suy nhị phân facts=[] + no_numeric_content như Phase 4.12):
      "OK"               — content_units khác rỗng, HOẶC no_numeric_content=
                           True (LLM XÁC NHẬN CHẮC CHẮN tin thuần định tính,
                           cơ chế Phase 4.12 giữ nguyên) -> có chất liệu, cho
                           Router định tuyến.
      "NO_USABLE_CONTENT" — JSON parse ĐƯỢC (không phải lỗi hạ tầng) nhưng
                           content_units RỖNG VÀ LLM KHÔNG tự tin khẳng định
                           "chắc chắn không có số" (no_numeric_content vẫn
                           False mặc định) -- ĐÂY LÀ CHỮ KÝ của nguồn
                           boilerplate/trang điều hướng/"đang cập nhật": LLM
                           không đọc hiểu được nội dung gì để KHẲNG ĐỊNH bất
                           cứ điều gì, kể cả "không có số" -- xác nhận qua
                           test_regression_row11_... (tests/test_pipeline.py,
                           Phase B) trước khi có field này, ca này bị lẫn vào
                           "NEEDS_HUMAN" (content_units[] rỗng do hỏng) một
                           cách SAI, dẫn tới Article vẫn được viết (bịa từ
                           trang rỗng).
      "FAILED"            — LLM rỗng/lỗi/timeout HOẶC JSON không parse được
                           (lỗi hạ tầng THẬT) -- GIÁ TRỊ MẶC ĐỊNH của dataclass
                           này (an toàn: mọi đường LÙI MƯỢT không set tường
                           minh sẽ tự rơi vào FAILED, không bao giờ ngộ nhận
                           OK/NO_USABLE_CONTENT từ 1 lỗi hạ tầng).
    `content_units=[]` KHÔNG CÒN được dùng riêng để suy trạng thái Brief
    (nguyên tắc Phase C) — dùng `brief_status` tường minh."""
    content_units: list[ContentUnit] = field(default_factory=list)
    no_numeric_content: bool = False
    scan_note: str = ""   # Content Factory Phase 2 — LLM tự báo lý do đơn vị < 8
                          # (bài nghèo dữ liệu thật) HOẶC "" nếu không cần giải trình
    brief_status: str = "FAILED"   # xem docstring lớp — mặc định AN TOÀN, mọi
                                    # chỗ tạo BriefResult() TRẦN (đường lùi mượt
                                    # do lỗi hạ tầng) tự nhận FAILED, KHÔNG cần
                                    # set tường minh ở từng nơi.

    @property
    def has_numeric_units(self) -> bool:
        """Phase C — 2 cờ has_numeric_units/has_qualitative_units ĐỘC LẬP,
        tính từ `type` của TỪNG content_unit (KHÔNG suy đoán từ có/không có
        field rời như no_numeric_content cũ) — 1 bài có thể vừa có số vừa có
        dữ kiện định tính, 2 cờ không loại trừ nhau."""
        return any(u.type == "numeric" for u in self.content_units)

    @property
    def has_qualitative_units(self) -> bool:
        return any(u.type != "numeric" for u in self.content_units)

    @property
    def has_anchored_units(self) -> bool:
        """Bước 4.1 (Router) — sàn thay cho "đếm số" cũ: article=true khi
        brief_status=OK VÀ có ≥1 content_unit NEO ĐƯỢC vào nguồn, đó là:
          - MỌI content_unit type="numeric" (5 shape số) — LUÔN được tính,
            vì cơ chế verify RIÊNG của chúng (value/raw PHẢI là substring
            chính xác của evidence, xem _parse_scalar/_parse_range/...) đã
            NGHIÊM NGẶT HƠN mức "direct_quote" định tính — không cần field
            `evidence` (vốn chỉ áp cho content_unit định tính).
          - content_unit ĐỊNH TÍNH (type != "numeric") CHỈ tính khi evidence
            ∈ {"direct_quote", "paraphrase"} — "derived"/"inferred" KHÔNG
            tính vào ngưỡng này (chúng là DIỄN GIẢI, không phải bằng chứng
            neo nguồn trực tiếp — có thể vẫn đúng, nhưng không đủ CHẮC CHẮN
            để một mình quyết định "bài này có chất liệu viết Article").
        1 content_unit derived/inferred DUY NHẤT (không kèm gì khác) KHÔNG
        đủ để ép article=true — đây CHÍNH LÀ sàn "không đặt article=false vì
        thiếu số" NHƯNG cũng không lỏng tới mức chấp nhận suy diễn đơn thuần
        làm chất liệu."""
        for u in self.content_units:
            if u.type == "numeric":
                return True
            if u.evidence in ("direct_quote", "paraphrase"):
                return True
        return False

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?\n])\s+")

_DEFAULT_ENTITY_TYPES = ("ticker", "company", "policy", "place", "person", "project", "other")
_DEFAULT_ENTITY_SALIENCE = ("subject", "context")
_MIN_CONTENT_UNIT_TARGET = 8   # Content Factory Phase 2 — nghiệm thu: "Mục tiêu 8-15 content unit/bài"


def _system_prompt(entity_types: list[str] | None = None,
                   entity_salience: list[str] | None = None) -> str:
    """Content Factory Phase 2 (+ 2b — salience) + Phase C bước 3 (content
    unit định tính) — system prompt VÉT CẠN, 6 shape (models.FACT_SHAPES: 5
    shape SỐ + "qualitative" cho 9 type định tính, models.CONTENT_UNIT_TYPES).
    `entity_types`/`entity_salience` đọc từ config (guardrail.entity_types/
    entity_salience, KHÔNG hard-code — xem run_brief(settings=...)), chỉ liệt
    kê minh hoạ cho LLM biết phân loại nào có sẵn, KHÔNG phải enum cứng
    (validate THẬT ở CODE, content_units_from_llm_output).

    Bước 3 (Lead 31/07, "content unit" thay "fact" trong ngôn ngữ prompt) —
    KHÔNG chỉ đổi CHỮ suông: chữ "fact" tự nó lái mô hình về phía số liệu
    (dùng "fact" trong tiếng Anh/Việt thường gợi ý "dữ kiện có thể kiểm
    chứng bằng số"), khiến mô hình coi nội dung định tính (thay đổi chính
    sách không kèm số, phát biểu chính thức, bước quy trình...) là hạng hai/
    bỏ qua dù prompt CŨ đã liệt kê entity/entity_list. Đổi hẳn từ vựng
    "content unit" (trung lập hơn, không thiên về số) + liệt kê tường minh
    10 type là chất liệu HỢP LỆ NGANG NHAU (không chỉ numeric)."""
    types_line = "|".join(entity_types or _DEFAULT_ENTITY_TYPES)
    salience_line = "|".join(entity_salience or _DEFAULT_ENTITY_SALIENCE)
    return (
        "Bạn là trợ lý TRÍCH XUẤT (KHÔNG PHẢI viết/tóm tắt/diễn giải) MỌI "
        "CONTENT UNIT (đơn vị nội dung đáng lên hình/đáng viết) từ 1 đoạn văn "
        "tài chính/kinh tế tiếng Việt. Đây là bước VÉT CẠN — nhiệm vụ của bạn "
        "là ĐỌC KỸ TỪNG CÂU và không bỏ sót bất kỳ con số/khoảng/biến thiên/"
        "thực thể có tên/sự kiện/thay đổi chính sách/phát biểu/bước quy "
        "trình/quan hệ giữa các bên/trạng thái trước-sau/mốc thời gian/trích "
        "dẫn/suy luận có căn cứ nào, KHÔNG phải chọn lọc vài ý 'quan trọng "
        "nhất' rồi tóm gọn.\n"
        "\n"
        "QUAN TRỌNG — 'content unit' KHÔNG ĐỒNG NGHĨA với 'số liệu'. Bài "
        "KHÔNG có con số vẫn có thể VÉT ĐƯỢC nhiều content unit hợp lệ. Ví dụ "
        "TƯỜNG MINH (đây là content unit HỢP LỆ, KHÔNG phải hạng hai so với "
        "số liệu):\n"
        "  • 'Ngân hàng Nhà nước bỏ trần lãi suất huy động kỳ hạn dưới 6 "
        "tháng' — 1 THAY ĐỔI CHÍNH SÁCH không kèm số nào, VẪN là 1 content "
        "unit hợp lệ (type=policy_change).\n"
        "  • 'Bộ trưởng Tài chính khẳng định sẽ không nới lỏng kỷ luật ngân "
        "sách' — 1 PHÁT BIỂU CHÍNH THỨC, VẪN là 1 content unit hợp lệ (type="
        "statement).\n"
        "  • 'Doanh nghiệp phải nộp hồ sơ, chờ thẩm định, rồi mới được cấp "
        "phép' — 1 BƯỚC QUY TRÌNH, VẪN là 1 content unit hợp lệ (type="
        "process).\n"
        "\n"
        "CÓ 10 LOẠI content unit (`type`, xem models.CONTENT_UNIT_TYPES) — "
        "PHẢI phân loại đúng, đừng ép mọi thứ về numeric:\n"
        "  numeric        — có con số/khoảng/biến thiên/thực thể-có-tên đi "
        "kèm số đếm (xem 5 HÌNH DẠNG SỐ bên dưới, `shape` khác \"qualitative\").\n"
        "  event          — 1 sự việc đã xảy ra/sắp xảy ra (vd 'công ty khởi "
        "công nhà máy mới').\n"
        "  policy_change   — 1 thay đổi chính sách/quy định (có hoặc KHÔNG "
        "kèm số).\n"
        "  statement       — 1 phát biểu/tuyên bố chính thức của 1 chủ thể "
        "có tên.\n"
        "  process         — 1 bước/chuỗi bước trong 1 quy trình.\n"
        "  relation        — 1 quan hệ giữa 2+ chủ thể (vd 'A là nhà cung "
        "cấp chính của B').\n"
        "  state_change    — 1 chuyển trạng thái KHÔNG PHẢI số (vd 'từ diện "
        "kiểm soát sang diện cảnh báo' — nếu có kèm số thì đây là numeric/"
        "shape=delta, xem dưới).\n"
        "  timeline        — 1 mốc/chuỗi mốc thời gian gắn với 1 sự kiện.\n"
        "  quote           — 1 câu trích dẫn trực tiếp đáng chú ý.\n"
        "  inference       — 1 cách hiểu/suy luận CÓ CĂN CỨ RÕ RÀNG trong bài "
        "(không phải bịa thêm ý ngoài bài).\n"
        "\n"
        "MỖI content unit type != numeric PHẢI có 4 TRƯỜNG: `subject` (chủ "
        "thể của claim, vd tên công ty/cơ quan/chính sách), `claim` (nội "
        "dung dữ kiện dạng 1 câu), `source` (CÂU NGUYÊN VĂN trong bài chứa "
        "dữ kiện này — COPY Y NGUYÊN, KHÔNG diễn giải lại câu nguồn, dù "
        "`claim` có thể diễn giải), `evidence` (mức độ chắc chắn — PHẢI chọn "
        "ĐÚNG 1 trong 4, đừng mặc định direct_quote):\n"
        "  direct_quote — `claim` trùng gần như NGUYÊN VĂN `source` (không "
        "diễn giải, chỉ rút gọn câu chữ thừa).\n"
        "  paraphrase   — `claim` diễn đạt LẠI ý của `source` bằng lời khác, "
        "KHÔNG thêm thông tin nào ngoài source.\n"
        "  derived      — `claim` là kết quả TÍNH RA từ `source` (vd cộng/"
        "trừ/so sánh 2 phần trong CÙNG câu nguồn).\n"
        "  inferred     — `claim` là CÁCH HIỂU của bạn, `source` KHÔNG nói "
        "thẳng ra điều đó (bạn suy luận từ ngữ cảnh) — dùng THẬN TRỌNG, chỉ "
        "khi suy luận có căn cứ rõ, không phải đoán mò.\n"
        "\n"
        "CÓ 5 HÌNH DẠNG dữ kiện SỐ (`shape`, dùng khi type=numeric) — PHẢI "
        "phân loại đúng, đừng ép mọi thứ về scalar:\n"
        "  1) scalar — 1 con số ĐƠN, kèm đơn vị + nhãn. 8 NHÓM (`kind`): "
        "percent (%), money (tiền), count (đếm, KHÔNG %/tiền — vd '8 cổ "
        "phiếu', '4 cảng biển'), growth (tăng/giảm có so sánh), date (mốc "
        "thời gian, vd '10/7', 'quý 2/2026'), ranking (xếp hạng/so sánh cực "
        "cấp, vd 'cao nhất 15 năm'), target (mục tiêu/ngưỡng), other.\n"
        "  2) range — 1 KHOẢNG 2 đầu (value_low, value_high CÙNG unit), vd "
        "'70 - 80% vốn FDI', '225 - 226 tỷ USD', '1.396 – 1.656 triệu tấn'. "
        "KHÔNG được rút gọn range thành 1 con số đơn (vd KHÔNG lấy trung bình "
        "hay chỉ lấy 1 đầu) — giữ NGUYÊN cả 2 đầu.\n"
        "  3) delta — 1 BIẾN THIÊN từ→đến (from_value, to_value — CÓ THỂ LÀ "
        "SỐ 'giảm từ 36 xuống 23 cảng', HOẶC CHUYỂN TRẠNG THÁI không phải số "
        "'từ diện kiểm soát sang diện cảnh báo', 'từ 16,3 tỷ đồng còn 176 "
        "triệu đồng'). Nhận diện qua cụm 'từ X xuống/còn/lên Y', 'so với mức "
        "X ... nay Y', 'X ... giảm/tăng ... thành Y'. QUAN TRỌNG (Phase C, "
        "R3): range/delta CHỈ hợp lệ khi cả 2 đầu số CÙNG NẰM TRONG 1 CÂU — "
        "nếu 2 số/mốc liên quan (vd 2 đợt trong 1 lịch thanh toán nhiều đợt) "
        "nằm ở 2 CÂU KHÁC NHAU, TUYỆT ĐỐI KHÔNG cố ghép/diễn giải lại thành 1 "
        "câu để ép vừa khung range/delta — hãy trích MỖI đầu số thành 1 fact "
        "scalar RIÊNG (dùng chung `label` mô tả rõ đây là 1 phần của cùng 1 "
        "chuỗi/lịch, vd label='Đợt 1 lịch thanh toán X', 'Đợt 2 lịch thanh "
        "toán X') — fact bị ghép sai câu sẽ bị CODE LOẠI BỎ HOÀN TOÀN (không "
        "phải cảnh báo), mất luôn dữ liệu thật, còn 2 fact scalar riêng vẫn "
        "giữ được đủ thông tin.\n"
        "  4) entity_list — 1 TẬP HỢP tên (`entities`, ≥2 phần tử) được LIỆT "
        "KÊ CÙNG NHAU trong bài, vd 'Hàn Quốc, Nhật Bản, Singapore, Trung "
        "Quốc, Mỹ và châu Âu', '4 cảng: Cần Giờ, Liên Chiểu, Nam Đồ Sơn, Vân "
        "Phong'. QUAN TRỌNG: nếu bài nêu 1 SỐ ĐẾM có tên kèm theo (vd '4 cảng "
        "biển đặc biệt' RỒI liệt kê tên 4 cảng đó), PHẢI trích CẢ 2 — 1 fact "
        "scalar (kind=count, value='4') VÀ 1 fact entity_list (tên 4 cảng) — "
        "TUYỆT ĐỐI KHÔNG chỉ trích số đếm rồi bỏ qua tên, đó là NGUYÊN LIỆU "
        "bắt buộc cho infographic (trường 'related'/'priority'). NHƯNG BÀI "
        "THẬT SỰ KHÔNG NÊU TÊN CỤ THỂ nào (chỉ nói '4 cảng' mà không kể tên) "
        "-> KHÔNG được TỰ BỊA tên cảng để lấp — chỉ trích fact scalar (kind="
        "count), entity_list CHỈ tồn tại khi tên THẬT SỰ xuất hiện trong văn bản.\n"
        "  5) entity — 1 thực thể ĐƠN có tên, KHÔNG hàm ý tập hợp (mã CK, "
        "công ty, chính sách/nghị quyết, địa danh, dự án, người có chức danh "
        "gắn với 1 số liệu/nhận định cụ thể). Gắn `entity_type` (gợi ý: "
        f"{types_line} — chọn gần đúng nhất, không chắc thì 'other').\n"
        "\n"
        "shape=entity/entity_list BẮT BUỘC THÊM `salience` (" + salience_line + ") "
        "— PHÂN BIỆT CHỦ THỂ với PHÔNG NỀN, đây là lỗi THẬT đã gặp (Content "
        "Factory Phase 2b — vét cạn tốt nhưng không phân biệt khiến related bị "
        "lấp bởi tên hội thảo/hiệp hội thay vì tên cảng/dự án thật):\n"
        "  - \"subject\" = thứ bài báo NÓI VỀ, chủ thể chính của tin (cảng, mã "
        "CK, công ty, dự án LÀ trọng tâm — vd nếu bài về JOS thua lỗ thì "
        "'JOS' là subject; nếu bài về 4 cảng biển được quy hoạch thì TÊN 4 "
        "cảng đó là subject).\n"
        "  - \"context\" = NGUỒN PHÁT NGÔN/bối cảnh sự kiện, KHÔNG phải chủ đề "
        "chính (hội thảo/diễn đàn tổ chức sự kiện, cơ quan/hiệp hội/viện "
        "nghiên cứu đồng tổ chức, người phát biểu/chuyên gia được trích dẫn, "
        "công ty CŨ/lịch sử chỉ nhắc để so sánh — KHÔNG phải chủ thể tin đang "
        "nói tới). Vd bài về hội thảo KCN do Hiệp hội Bất động sản tổ chức, "
        "TS Nguyễn Văn Khôi phát biểu -> 'Hiệp hội Bất động sản Việt Nam' và "
        "'Nguyễn Văn Khôi' là context (họ là NGUỒN nói, không phải điều bài "
        "đang báo cáo).\n"
        "  Không chắc chắn -> chọn \"context\" (AN TOÀN hơn — context không "
        "lên hình related/priority, subject sai mới đáng ngại).\n"
        "\n"
        "SIẾT LẠI (Phase 3.1b — lỗi thật đo được qua benchmark lặp lại: tên sự "
        "kiện/diễn đàn bị gán nhầm \"subject\" 4/10 lượt dù chỉ là bối cảnh): "
        "TRƯỚC KHI gán salience=\"subject\" cho 1 entity/entity_list, PHẢI tự "
        "hỏi — thực thể này có phải điều bài báo ĐANG NÓI VỀ (chủ đề chính), "
        "hay chỉ là BỐI CẢNH xuất hiện quanh chủ đề đó? Các dấu hiệu CONTEXT "
        "sau đây, DÙ XUẤT HIỆN NHIỀU LẦN, vẫn GIỮ salience=\"context\":\n"
        "  • Tên sự kiện/hội thảo/diễn đàn ĐƯỢC TỔ CHỨC (vd 'Diễn đàn Phát "
        "triển Khu Công nghiệp Việt Nam - ... Summit 2026') — bản thân sự "
        "kiện không phải chủ đề tin, dù được nhắc đi nhắc lại làm bối cảnh.\n"
        "  • Địa điểm tổ chức sự kiện/hội thảo (vd 'tại Hải Phòng').\n"
        "  • Người phát biểu/quan chức được dẫn lời.\n"
        "  • Đơn vị/hiệp hội/viện tổ chức hoặc bảo trợ sự kiện.\n"
        "  • Nguồn trích dẫn số liệu (cơ quan thống kê, công ty chứng khoán...).\n"
        "TẦN SUẤT XUẤT HIỆN KHÔNG PHẢI tín hiệu của \"subject\". Một địa danh "
        "hay tên sự kiện được nhắc nhiều lần vì đó là NƠI/DỊP diễn ra tin vẫn "
        "là \"context\", KHÔNG phải \"subject\" — TRỪ KHI bài báo nói VỀ CHÍNH "
        "địa danh/sự kiện đó (vd quy hoạch CHO địa danh đó, dự án ĐẶT TẠI địa "
        "danh đó với vai trò là đối tượng chính đang được bàn tới). Không "
        "chắc chắn -> \"context\" (thà bỏ sót còn hơn gán nhầm — related/"
        "priority.primary chỉ nên chứa thực thể chắc chắn là chủ thể).\n"
        "\n"
        "MỖI content unit SỐ (type=numeric) PHẢI có `label` NGẮN GỌN mô tả "
        "CHÍNH XÁC nó LÀ GÌ (vd 'GDP 6 tháng đầu năm 2026', 'Số cổ phiếu SSI "
        "khuyến nghị', '4 cảng biển đặc biệt được quy hoạch') — TUYỆT ĐỐI "
        "KHÔNG dùng nhãn chung chung kiểu 'Số liệu 1', 'Thông tin thêm'.\n"
        "CHỈ trích số/khoảng/biến thiên/tên/sự kiện/phát biểu THẬT SỰ xuất "
        "hiện NGUYÊN VĂN trong văn bản — KHÔNG suy diễn ngoài căn cứ, KHÔNG "
        "tính toán bịa, KHÔNG rút gọn/diễn giải lại câu NGUỒN (field `source`,"
        " diễn giải chỉ được phép ở `claim`). Đây là bước TRÍCH XUẤT, không "
        "phải bước VIẾT.\n"
        "shape=scalar/range/delta: thêm \"approx\" = true nếu cụm đi kèm từ "
        "xấp xỉ (gần/khoảng/xấp xỉ/hơn/trên/dưới), false nếu số chính xác. "
        "shape=scalar THÊM \"raw\" = cụm NGUYÊN VĂN chứa value bạn COPY Y "
        "NGUYÊN từ văn bản (kể cả từ xấp xỉ nếu có) — PHẢI tìm được y hệt "
        "bằng tìm-chuỗi trong văn bản gốc.\n"
        "\n"
        f"MỤC TIÊU: {_MIN_CONTENT_UNIT_TARGET}-15 content unit/bài (SỐ và "
        "ĐỊNH TÍNH CỘNG LẠI) — bài THẬT SỰ có nhiều dữ kiện mà bạn chỉ trích "
        "2-3 unit là bạn đang TÓM TẮT SAI NHIỆM VỤ. Bài KHÔNG có số vẫn có "
        "thể đạt mục tiêu này bằng content unit ĐỊNH TÍNH (policy_change/"
        "event/statement/process/...). Nếu đọc hết bài mà bài THẬT SỰ nghèo "
        "dữ liệu (ít hơn "
        f"{_MIN_CONTENT_UNIT_TARGET} unit CẢ SỐ LẪN ĐỊNH TÍNH) thì được phép "
        "ít hơn, NHƯNG BẮT BUỘC ghi \"scan_note\": giải thích ngắn bạn đã đọc "
        "hết và bài chỉ có từng đó (vd \"Bài chỉ có 3 content unit (2 định "
        "lượng, 1 định tính), đã quét hết toàn văn.\") — KHÔNG được dừng sớm "
        "ngầm không giải thích.\n"
        "\n"
        "Sau khi đọc KỸ toàn bộ văn bản: nếu bạn XÁC NHẬN CHẮC CHẮN không có "
        "bất kỳ con số/khoảng/biến thiên/thực thể có tên nào (CHỈ nói về việc "
        "KHÔNG CÓ SỐ, KHÔNG PHẢI không có nội dung — bài thuần định tính vẫn "
        "phải trích content unit định tính bình thường) -> đặt \"no_numeric_"
        "content\": true. CHỈ đặt true khi THẬT SỰ chắc chắn đã đọc hết và "
        "không sót — còn nghi ngờ/không chắc thì để false (mặc định, KHÔNG "
        "suy diễn 'chắc là không có').\n"
        'Trả về DUY NHẤT JSON: {"content_units": [\n'
        '  {"shape": "scalar", "value": str, "label": str, "unit": str hoặc null, '
        '"kind": "percent|money|count|growth|date|ranking|target|other", '
        '"raw": str, "approx": bool} |\n'
        '  {"shape": "range", "value_low": str, "value_high": str, "label": str, '
        '"unit": str hoặc null, "kind": str, "approx": bool} |\n'
        '  {"shape": "delta", "from_value": str, "to_value": str, "label": str, '
        '"unit": str hoặc null, "kind": str, "approx": bool} |\n'
        '  {"shape": "entity_list", "entities": [str], "label": str, "salience": str} |\n'
        '  {"shape": "entity", "value": str, "label": str, "entity_type": str, "salience": str} |\n'
        '  {"shape": "qualitative", "type": "event|policy_change|statement|process|relation|'
        'state_change|timeline|quote|inference", "subject": str, "claim": str, "source": str, '
        '"evidence": "direct_quote|paraphrase|derived|inferred"}\n'
        '], "no_numeric_content": bool, "scan_note": str}. '
        "KHÔNG markdown, KHÔNG lời dẫn."
    )


# Tương thích ngược: giữ tên `_SYSTEM` (module-level, dùng entity_types mặc
# định) cho code/test CŨ còn import trực tiếp — run_brief() thật SỰ DÙNG
# _system_prompt(entity_types) động theo config (xem run_brief bên dưới).
_SYSTEM = _system_prompt()


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT_RE.split(text or "") if s.strip()]


def _normalize_text(text: str) -> str:
    """Chuẩn hoá Unicode NFC — BUG THẬT phát hiện qua round-trip trên bài cảng
    biển (Content Factory Phase 2b): 1 số trang nguồn (vd cafef.vn qua
    collector hiện có) trả markdown với dấu tiếng Việt ở dạng TỔ HỢP (NFD —
    "ó" = "o" + dấu sắc rời, 2 code point) thay vì DỰNG SẴN (NFC — "ó" = 1 code
    point), trong khi LLM luôn trả NFC. So khớp chuỗi thô (`in`/regex) giữa 2
    dạng NHÌN GIỐNG HỆT nhưng byte KHÁC NHAU sẽ luôn thất bại — im lặng loại
    hàng loạt fact/thành viên entity_list ĐÚNG SỰ THẬT (tái hiện được: 15/15
    tên tỉnh trong 1 fact chỉ còn sống sót "Gia Lai" — tên duy nhất không dấu
    tổ hợp). Chuẩn hoá CẢ 2 vế (value cần tìm VÀ text nguồn) về NFC trước khi
    so khớp — an toàn/idempotent với text ĐÃ là NFC (5/6 nguồn khác trong
    golden set không bị ảnh hưởng)."""
    return unicodedata.normalize("NFC", text or "")


def _boundary_match(value: str, text: str) -> bool:
    """True nếu `value` xuất hiện trong `text` với biên AN TOÀN (không khớp
    giữa 1 số dài hơn) — lõi dùng chung bởi verify_fact_in_evidence (quét
    nhiều câu) VÀ _find_shared_sentence (Phase 2 — quét range/delta phải CÙNG
    câu). Tách riêng để 2 nơi dùng CHUNG 1 luật biên, không lặp regex.
    Chuẩn hoá NFC cả 2 vế trước khi so khớp — xem _normalize_text."""
    value = _normalize_text(value).strip()
    if not value:
        return False
    pattern = re.compile(
        r"(?<![\d.,])" + re.escape(value) + r"(?!\d)(?!%)(?!,\d)(?!\.\d)")
    return bool(pattern.search(_normalize_text(text)))


def verify_fact_in_evidence(value: str, source_text: str) -> str | None:
    """Câu evidence ĐẦU TIÊN chứa NGUYÊN VĂN `value` — None nếu không có (chống
    bịa). Hàm THUẦN, test được không cần LLM.

    KHÔNG dùng substring `in` thô: value NGẮN (vd "8") sẽ khớp NHẦM vào bên
    trong 1 số khác không liên quan (vd "8" lọt trong "8,18%") -> gắn sai câu
    nguồn. Ép biên bất đối xứng có chủ đích — xem _boundary_match.
    """
    for sent in _split_sentences(source_text):
        if _boundary_match(value, sent):
            return sent
    return None


def _find_shared_sentence(candidates_a: list[str], candidates_b: list[str],
                          source_text: str) -> str | None:
    """Content Factory Phase 2 — câu evidence chứa ÍT NHẤT 1 candidate của MỖI
    bên (range: value_low & value_high; delta: from_value & to_value) TRONG
    CÙNG 1 CÂU — chống ghép 2 số/cụm KHÔNG liên quan tình cờ cùng xuất hiện
    đâu đó trong bài thành 1 range/delta bịa. Hàm THUẦN."""
    for sent in _split_sentences(source_text):
        if any(_boundary_match(a, sent) for a in candidates_a) and \
           any(_boundary_match(b, sent) for b in candidates_b):
            return sent
    return None


def build_brief_prompt(evidence: str, background: str = "") -> str:
    text = f"{evidence}\n{background}".strip() if background else evidence.strip()
    return f"Văn bản:\n{text[:2500]}\n\nTrích content_units[] đúng schema, đã dặn ở system."


def _value_unit_candidates(value: str, unit: str | None) -> list[str]:
    """Thử THEO THỨ TỰ cụ thể hoá dần: "value+unit" (dính liền, vd "8,18%"),
    "value unit" (cách nhau, vd "1.200 tỷ đồng"), rồi `value` trơ. LLM có lúc
    tách unit ra riêng ("value":"8,18","unit":"%") — verify value trơ ("8,18")
    sẽ bị chặn bởi luật biên (đứng ngay trước "%") dù đây là fact THẬT; thử
    ghép lại với unit trước mới đúng ý nghĩa số trong evidence."""
    candidates = []
    if unit:
        candidates += [f"{value}{unit}", f"{value} {unit}"]
    candidates.append(value)
    seen, out = set(), []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _verify_candidates(value: str, unit: str | None, source_text: str) -> str | None:
    for cand in _value_unit_candidates(value, unit):
        sent = verify_fact_in_evidence(cand, source_text)
        if sent is not None:
            return sent
    return None


def _canonical(value: str, unit: str | None) -> float | None:
    return parse_magnitude_token(f"{value}{unit or ''}")


def _parse_scalar(item: dict, source_text: str, kind: str) -> ContentUnit | None:
    value = str(item.get("value", "")).strip()
    label = str(item.get("label", "")).strip()
    if not value or not label:
        return None
    unit_raw = item.get("unit")
    unit = str(unit_raw).strip() or None if unit_raw else None
    sent = _verify_candidates(value, unit, source_text)
    if sent is None:
        return None   # không xuất hiện trong evidence/background -> nghi bịa, LOẠI

    # Mục C (Phase 4.8): "raw" PHẢI là substring THẬT của evidence+background
    # (kiểm `in`, chặt hơn verify_fact_in_evidence theo câu) -> chống AI tự
    # paraphrase/bịa cụm không có thật. Thiếu/sai -> LOẠI đơn vị. Chuẩn hoá NFC
    # (xem _normalize_text) — source_text gọi vào đây ĐÃ chuẩn hoá sẵn
    # (content_units_from_llm_output), nhưng raw_phrase (chuỗi mới từ item)
    # cần tự chuẩn hoá riêng trước khi so `in`.
    raw_phrase = _normalize_text(str(item.get("raw", "")).strip())
    if not raw_phrase or raw_phrase not in source_text:
        return None

    approx = bool(item.get("approx", False)) or has_approx_word(raw_phrase)
    return ContentUnit(value=value, label=label, unit=unit, source=sent, kind=kind,
                       shape="scalar", raw=raw_phrase, canonical_value=_canonical(value, unit),
                       approx=approx)


def _parse_range(item: dict, source_text: str, kind: str) -> ContentUnit | None:
    value_low = str(item.get("value_low", "")).strip()
    value_high = str(item.get("value_high", "")).strip()
    label = str(item.get("label", "")).strip()
    if not value_low or not value_high or not label:
        return None
    unit_raw = item.get("unit")
    unit = str(unit_raw).strip() or None if unit_raw else None
    sent = _find_shared_sentence(_value_unit_candidates(value_low, unit),
                                 _value_unit_candidates(value_high, unit), source_text)
    if sent is None:
        return None   # 2 đầu range không CÙNG xuất hiện 1 câu -> nghi ghép bịa, LOẠI
    approx = bool(item.get("approx", False))
    return ContentUnit(value="", label=label, unit=unit, source=sent, kind=kind, shape="range",
                       value_low=value_low, value_high=value_high,
                       canonical_low=_canonical(value_low, unit), canonical_high=_canonical(value_high, unit),
                       approx=approx)


def _parse_delta(item: dict, source_text: str, kind: str) -> ContentUnit | None:
    from_value = str(item.get("from_value", "")).strip()
    to_value = str(item.get("to_value", "")).strip()
    label = str(item.get("label", "")).strip()
    if not from_value or not to_value or not label:
        return None
    unit_raw = item.get("unit")
    unit = str(unit_raw).strip() or None if unit_raw else None
    sent = _find_shared_sentence(_value_unit_candidates(from_value, unit),
                                 _value_unit_candidates(to_value, unit), source_text)
    if sent is None:
        return None   # from/to không CÙNG xuất hiện 1 câu -> nghi ghép bịa, LOẠI
    approx = bool(item.get("approx", False))
    return ContentUnit(value="", label=label, unit=unit, source=sent, kind=kind, shape="delta",
                       from_value=from_value, to_value=to_value,
                       canonical_from=_canonical(from_value, unit), canonical_to=_canonical(to_value, unit),
                       approx=approx)


def _parse_salience(item: dict, entity_salience: list[str]) -> str:
    """Content Factory Phase 2b — validate `salience` theo config (KHÔNG hard-
    code). FAIL-CLOSED: thiếu/lạ -> "context" (AN TOÀN — context KHÔNG lên
    hình related/priority.primary, subject sai mới đáng ngại hơn, xem agents/
    production._entity_names_from_content_units)."""
    salience = str(item.get("salience", "")).strip().lower()
    if salience not in {s.lower() for s in entity_salience}:
        return "context"
    return salience


def _parse_entity_list(item: dict, source_text: str, entity_salience: list[str]) -> ContentUnit | None:
    label = str(item.get("label", "")).strip()
    raw_entities = item.get("entities")
    if not label or not isinstance(raw_entities, list):
        return None
    survivors: list[str] = []
    source = ""
    for e in raw_entities:
        name = str(e).strip()
        if not name:
            continue
        sent = verify_fact_in_evidence(name, source_text)
        if sent is None:
            continue   # tên KHÔNG verify được -> LOẠI KHỎI DANH SÁCH (không loại cả đơn vị)
        survivors.append(name)
        if not source:
            source = sent   # câu của phần tử ĐẦU TIÊN còn sống sót
    if not survivors:
        return None   # rỗng sau lọc -> không còn gì để trình bày, LOẠI cả đơn vị
    salience = _parse_salience(item, entity_salience)
    return ContentUnit(value="", label=label, source=source, shape="entity_list",
                       entities=survivors, salience=salience)


def _parse_entity(item: dict, source_text: str, entity_types: list[str],
                  entity_salience: list[str]) -> ContentUnit | None:
    value = str(item.get("value", "")).strip()
    label = str(item.get("label", "")).strip()
    if not value or not label:
        return None
    sent = verify_fact_in_evidence(value, source_text)
    if sent is None:
        return None
    entity_type = str(item.get("entity_type", "")).strip().lower()
    if entity_type not in {t.lower() for t in entity_types}:
        entity_type = "other"   # loại lạ ngoài config -> hạ cấp, KHÔNG loại đơn vị
    salience = _parse_salience(item, entity_salience)
    return ContentUnit(value=value, label=label, source=sent, shape="entity",
                       entity_type=entity_type, salience=salience)


_WS_RE = re.compile(r"\s+")


def _normalize_whitespace(text: str) -> str:
    """Chuẩn hoá khoảng trắng (xuống dòng/tab/nhiều dấu cách liên tiếp -> 1
    dấu cách, strip 2 đầu, sau NFC — xem _normalize_text) — sàn chống bịa RẺ+
    TẤT ĐỊNH cho content_unit ĐỊNH TÍNH (Phase C bước 3.2): không có value số
    để neo biên an toàn như _boundary_match, nên dùng substring THẲNG sau khi
    chuẩn hoá khoảng trắng (đủ chặt: LLM không thể bịa 1 câu KHÔNG có trong
    bài mà vẫn khớp substring được, chỉ cho phép sai khác về xuống dòng/dấu
    cách thừa — thứ full-fetch/markdown hay chèn thêm)."""
    return _WS_RE.sub(" ", _normalize_text(text)).strip()


def _verify_qualitative_source(source: str, source_text_ws_normalized: str) -> bool:
    normalized = _normalize_whitespace(source)
    return bool(normalized) and normalized in source_text_ws_normalized


def _parse_qualitative_unit(item: dict, source_text_ws_normalized: str) -> ContentUnit | None:
    """Phase C bước 3 — parser cho content_unit ĐỊNH TÍNH (type != "numeric").
    `subject`/`claim`/`source` BẮT BUỘC khác rỗng (thiếu 1 trong 3 -> LOẠI —
    đây là SÀN CHỐNG BOILERPLATE: trang rỗng/điều hướng không có gì để LLM
    điền `claim` có ý nghĩa lẫn `source` verify được). `source` PHẢI là
    substring của văn bản nguồn SAU CHUẨN HOÁ KHOẢNG TRẮNG (_verify_
    qualitative_source, bước 3.2) — không khớp -> nghi bịa, LOẠI, KHÔNG loại
    cả lượt gọi. `evidence` (mức độ chắc chắn, bước 3.3) do LLM tự gán theo
    quy tắc trong _system_prompt — CODE KHÔNG verify lại ngữ nghĩa (khác
    `source`, verify được tất định bằng substring); thiếu/lạ -> hạ cấp về
    "inferred" (mức THẬN TRỌNG NHẤT trong 4 mức, KHÔNG tự tin gán direct_
    quote/paraphrase khi LLM không tự khai rõ)."""
    type_raw = str(item.get("type", "")).strip().lower()
    content_type = type_raw if type_raw in CONTENT_UNIT_TYPES and type_raw != "numeric" else ""
    if not content_type:
        return None   # type rỗng/lạ/"numeric" (sai chỗ — numeric phải qua 5 shape số) -> LOẠI
    subject = str(item.get("subject", "")).strip()
    claim = str(item.get("claim", "")).strip()
    source = str(item.get("source", "")).strip()
    if not subject or not claim or not source:
        return None   # thiếu 1 trong 3 field bắt buộc -> LOẠI (sàn chống boilerplate)
    if not _verify_qualitative_source(source, source_text_ws_normalized):
        return None   # source không verify được trong văn bản -> nghi bịa, LOẠI
    evidence_raw = str(item.get("evidence", "")).strip().lower()
    evidence = evidence_raw if evidence_raw in CONTENT_UNIT_EVIDENCE_LEVELS else "inferred"
    return ContentUnit(value="", label=subject, source=source, shape="qualitative",
                       type=content_type, subject=subject, claim=claim, evidence=evidence)


_SHAPE_PARSERS = {
    "scalar": _parse_scalar,
    "range": _parse_range,
    "delta": _parse_delta,
}


def content_units_from_llm_output(raw: str, evidence: str, background: str = "",
                                  entity_types: list[str] | None = None,
                                  entity_salience: list[str] | None = None) -> BriefResult:
    """Parse output LLM -> BriefResult (content_units[] đã LỌC CHỐNG BỊA theo
    shape, xem docstring module + cờ no_numeric_content, Phase 4.12). Hàm
    THUẦN — dùng chung bởi run_brief() và test (không cần LLM thật). JSON
    không parse được -> BriefResult() rỗng-DO-HỎNG (no_numeric_content=False
    mặc định, KHÔNG BAO GIỜ True ở đường lùi mượt này). `entity_types`/
    `entity_salience` — xem run_brief."""
    data = try_json_object(raw) if raw else None
    if not data:
        return BriefResult()   # brief_status mặc định "FAILED" (lỗi hạ tầng THẬT)
    # Chuẩn hoá NFC 1 LẦN Ở ĐÂY (xem _normalize_text) — mọi hàm _parse_* +
    # raw_phrase check bên dưới đọc source_text ĐÃ chuẩn hoá, tránh lặp lại
    # normalize() rải rác nhiều nơi.
    source_text = _normalize_text(f"{evidence}\n{background}")
    source_text_ws = _normalize_whitespace(source_text)   # Phase C bước 3.2 — cho _parse_qualitative_unit
    entity_types = entity_types or list(_DEFAULT_ENTITY_TYPES)
    entity_salience = entity_salience or list(_DEFAULT_ENTITY_SALIENCE)
    out: list[ContentUnit] = []
    seen: set[str] = set()   # chống trùng theo (shape, khoá định danh) — xem key bên dưới
    n_qualitative_raw = 0     # Phase C bước 3.2 — đếm để log tỷ lệ source không khớp
    n_qualitative_verified = 0

    for item in (data.get("content_units") or []):
        if not isinstance(item, dict):
            continue
        shape_raw = str(item.get("shape", "")).strip().lower()
        shape = shape_raw if shape_raw in FACT_SHAPES else "scalar"   # thiếu/lạ -> lùi về scalar (dữ liệu cũ)
        kind_raw = str(item.get("kind", "")).strip().lower()
        kind = kind_raw if kind_raw in FACT_KINDS else "other"

        if shape in _SHAPE_PARSERS:
            unit = _SHAPE_PARSERS[shape](item, source_text, kind)
            key = f"{shape}:{unit.value or unit.value_low or unit.from_value}" if unit else None
        elif shape == "entity_list":
            unit = _parse_entity_list(item, source_text, entity_salience)
            key = f"entity_list:{tuple(unit.entities)}" if unit else None
        elif shape == "qualitative":
            n_qualitative_raw += 1
            unit = _parse_qualitative_unit(item, source_text_ws)
            if unit is not None:
                n_qualitative_verified += 1
            key = f"qualitative:{unit.subject}:{unit.claim}" if unit else None
        else:   # shape == "entity"
            unit = _parse_entity(item, source_text, entity_types, entity_salience)
            key = f"entity:{unit.value}" if unit else None

        if unit is None or key in seen:
            continue
        seen.add(key)
        out.append(unit)

    if n_qualitative_raw:
        # Bước 3.2 — "ghi tỷ lệ không khớp vào log": biến sàn chống bịa content
        # unit định tính thành ĐO ĐƯỢC (không chỉ tin lời mô hình đã lọc sạch).
        mismatch_rate = 1.0 - (n_qualitative_verified / n_qualitative_raw)
        print(f"[content_units_from_llm_output] qualitative: {n_qualitative_verified}/"
             f"{n_qualitative_raw} verify được (source khớp văn bản nguồn) — "
             f"tỷ lệ KHÔNG khớp: {mismatch_rate:.0%}")

    # Phase 4.12: no_numeric_content=True CHỈ đứng vững khi content_units
    # SỐ THẬT SỰ rỗng (content_units khác rỗng mà LLM lỡ báo true -> mâu
    # thuẫn logic, ép False — không tin mù field rời của LLM, cùng triết lý
    # driver_count/has_genuine_paradox).
    no_numeric_content = bool(data.get("no_numeric_content", False)) and not out
    scan_note = str(data.get("scan_note", "")).strip()
    # Phase C — brief_status: JSON parse ĐƯỢC tới đây rồi (không phải FAILED).
    # out khác rỗng HOẶC LLM tự tin xác nhận no_numeric_content -> OK (có chất
    # liệu). Cả 2 đều rỗng/False -> NO_USABLE_CONTENT (chữ ký boilerplate/
    # trang rỗng — xem docstring BriefResult).
    brief_status = "OK" if (out or no_numeric_content) else "NO_USABLE_CONTENT"
    return BriefResult(content_units=out, no_numeric_content=no_numeric_content,
                       scan_note=scan_note, brief_status=brief_status)


def run_brief(llm: LLMClient, evidence: str, background: str = "", *,
             model: str | None = None, fail_loud: bool = False, settings=None) -> BriefResult:
    """Gọi LLM bước 'brief' -> BriefResult (content_units[] đã verify +
    no_numeric_content, Phase 4.12; VÉT CẠN 5 shape SỐ + shape "qualitative"
    cho 9 type định tính (Phase C bước 3); salience chủ thể/phông nền, Phase
    2b). LÙI MƯỢT mặc định (fail_loud=False): LLM rỗng/lỗi/parse hỏng ->
    BriefResult() rỗng-DO-HỎNG (KHÔNG crash, no_numeric_content luôn False ở
    đường này). `model`/`fail_loud` truyền thẳng cho complete() (xem factory.
    step_model/is_fail_loud_step). `settings` (tuỳ chọn) — đọc `guardrail.
    entity_types`/`guardrail.entity_salience` cho system prompt + validate
    shape=entity/entity_list (KHÔNG hard-code); thiếu -> dùng _DEFAULT_ENTITY_
    TYPES/_DEFAULT_ENTITY_SALIENCE, KHÔNG crash (giữ hàm gọi được không cần
    Settings ở test thuần)."""
    entity_types = None
    entity_salience = None
    if settings is not None:
        entity_types = settings.get("guardrail.entity_types") or None
        entity_salience = settings.get("guardrail.entity_salience") or None
    system = _system_prompt(entity_types, entity_salience)
    raw = llm.complete(system, build_brief_prompt(evidence, background),
                       model=model, fail_loud=fail_loud)
    if not raw:
        return BriefResult()   # brief_status mặc định "FAILED" (LLM rỗng/lỗi/timeout)
    return content_units_from_llm_output(raw, evidence, background,
                                         entity_types=entity_types, entity_salience=entity_salience)
