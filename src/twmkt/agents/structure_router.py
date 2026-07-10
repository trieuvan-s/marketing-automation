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

RÀNG BUỘC CỨNG #2 (Phase 3.5, "phục hồi Hybrid S4"): signals.driver_count KHÔNG
còn là field LLM tự gõ số — LLM chỉ liệt kê TÊN từng driver độc lập vào
signals.drivers[]; driver_count = len(drivers) TÍNH BẰNG CODE (route_from_llm_
output bỏ qua bất kỳ field "driver_count" rời nào LLM có thể lỡ trả về). Nhất
quán bắt buộc: rationale nhắc bao nhiêu driver thì drivers[] phải liệt kê đúng
bấy nhiêu — liệt kê TÊN THẬT (thay vì tự báo số) khiến LLM khó lệch giữa lời
văn và số đếm hơn. driver_count (đã tính) >= 3 VÀ structure chính KHÔNG PHẢI S4
-> ÉP secondary_structure=S4 (Hybrid: khung chính + 1 đoạn song hành nhiều
driver), bất kể LLM tự điền secondary_structure gì — CHẶN Ở CODE, không chỉ tin
prompt, cùng triết lý với ràng buộc S5 ở trên.

PHASE 3.6 (ổn định + thước đo nghịch lý-thật):
  - temperature=0.0 truyền cho bước 'router' (xem run_route) — AnthropicLLM hỗ
    trợ đầy đủ; ClaudeCodeLLM (`claude -p`, backend đang dùng qua llm.mode=
    claude_code) KHÔNG expose tham số sampling nào (đã kiểm `claude -p --help`)
    -> tham số này là NO-OP cho backend đó (cảnh báo 1 lần, xem agents/base.py).
    Vì không ép được tất định bằng tham số, ĐỘ ỔN ĐỊNH dựa vào thước đo dưới đây.
  - RÀNG BUỘC CỨNG #3: signals.has_genuine_paradox=true BẮT BUỘC kèm
    signals.residual_tension khác null (1 câu căng thẳng/câu hỏi mở CÒN LẠI sau
    khi đã giải thích — không phải mô tả lại vẻ ngoài mâu thuẫn). Claim
    has_genuine_paradox=true mà KHÔNG kèm residual_tension -> coi là claim
    KHÔNG hợp lệ, CODE tự ép về false (route_from_llm_output), sau đó ràng buộc
    S5 ở trên áp dụng như thường (S5 + has_genuine_paradox đã-ép-false ->
    fallback). Hook dạng H1/§2b (nêu "mâu thuẫn… hay là…") KHÔNG tự động nghĩa
    là nghịch lý thật ở tầng `structure` — đó là kỹ thuật viết câu mở, còn
    has_genuine_paradox soi CẤU TRÚC lập luận (sau khi giải thích, căng thẳng
    có TAN hết thành 1 luận điểm sạch hay còn sót lại thật).

PHASE 4.8-B2 (báo cáo 4.8 phát hiện: probe Ví dụ A — ca S5 đã biết chắc — router
trả has_genuine_paradox=true KÈM residual_tension hợp lệ, nhưng LẠI chọn
structure=S1 với rationale "logic khép sạch" — TỰ MÂU THUẪN ngay trong 1 output.
Trước Phase 4.8-B2, code chỉ ép CHIỀU 1 (S5 mà paradox=false -> fallback S1),
KHÔNG có luật ép CHIỀU NGƯỢC LẠI (paradox=true -> phải là S5) -> lai trạng thái
lọt qua được):
  - RÀNG BUỘC CỨNG #4: has_genuine_paradox "EFFECTIVE" (đã chuẩn hoá ở RÀNG BUỘC
    #3 — paradox=true VÀ residual_tension khác null/rỗng) == True -> ÉP
    structure=S5, GHI ĐÈ bất kể LLM tự chọn structure gì (kể cả khi LLM tự nói
    "khép sạch" ở rationale) — CHẶN Ở CODE, không tin field rời tự mâu thuẫn của
    LLM, cùng triết lý với ràng buộc driver_count>=3 ép secondary=S4. Giờ CẢ 2
    CHIỀU của "S5 <=> has_genuine_paradox" đều bị ép ở CODE:
      chiều 1 (Phase 3): S5 mà paradox=false -> fallback (KHÔNG cho S5 giả).
      chiều 2 (4.8-B2):  paradox=true (effective) -> BẮT BUỘC S5 (KHÔNG cho lai).

PHASE 4.13 MỤC A — CONTENT-FIT ROUTER (đóng gap (a) — trước phase này MỌI chủ đề
APPROVE đều bị ép sinh ĐỦ 3 tuyến article+video+infographic, kể cả khi 1 tuyến
không hợp bản chất tin, gây SKIPPED/ERROR "oan" phát hiện ở backtest Phase 4.12/
4.12-B). RouterDecision giờ trả THÊM (ĐÓNG BĂNG CÙNG quyết định qua route-once,
agents/route_once.py — không route lại riêng cho từng tuyến):
  - output_channels: {"article": bool, "infographic": bool, "video": bool} —
    AI PHÁN theo hình dạng THẬT của tin (KHÔNG đếm số cứng ở CODE, luật chỉ nằm
    trong PROMPT — xem _SYSTEM): infographic hợp khi có dữ liệu định lượng trình
    bày được bằng hình; video hợp khi có narrative kể được (kém hợp tin bảng-số
    thuần); article mặc định true trừ khi tin quá vụn/không đủ chất liệu.
  - channel_rationale: {"article": str, "infographic": str, "video": str} — 1
    câu/tuyến để AUDIT (vì sao hợp/không hợp), KHÔNG chảy vào system prompt Writer.
  Parse LỎNG (route_from_llm_output): thiếu/hỏng field hay type sai -> MẶC ĐỊNH
  CẢ 3 TRUE (an toàn — KHÔNG tự ý cắt tuyến khi không chắc, khác hẳn nguyên tắc
  "S5 cấm mặc định" ở trên vì hướng rủi ro ngược nhau: sinh thừa 1 tuyến không
  hợp chỉ tốn thêm ít lượt LLM rẻ + có thể SKIPPED tay sau, còn CẮT NHẦM 1 tuyến
  hợp làm mất nội dung đáng ra có được — an toàn nghiêng về sinh thừa).
  Owner override thủ công: agents/route_once.RouterDecisionStore.set_channel()
  (scripts/reroute.py --channel/--set) — GIỐNG triết lý reroute (Mục A cũ), sửa
  TRỰC TIẾP quyết định đã đóng băng, KHÔNG gọi lại LLM.
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
    "  S4 · Song hành: nhiều driver ĐỘC LẬP cùng tác động (từ 3 tên trở lên trong "
    "signals.drivers), không cái nào phụ cái nào. Thường là 1 ĐOẠN trong bài lớn hơn "
    "(secondary_structure), hiếm khi là cả bài.\n"
    "  S5 · Phản đề: CHỈ dùng khi CÓ NGHỊCH LÝ THẬT cần hoá giải (has_genuine_paradox="
    "true) — vd 2 tín hiệu THẬT SỰ mâu thuẫn nhau, không phải chỉ 'nghe hơi lạ'. TUYỆT "
    "ĐỐI KHÔNG chọn S5 làm mặc định hay khi không chắc — dùng sai chỗ sẽ gượng.\n"
    "  THƯỚC ĐO nghịch lý-thật (bắt buộc tự kiểm trước khi chọn S5): tưởng tượng bạn ĐÃ "
    "giải thích xong logic đằng sau (vd 'công ty A chọn 8 khoản đầu tư vì mỗi cái có động "
    "lực riêng, không phụ thuộc vĩ mô'). Sau khi giải thích, còn CĂNG THẲNG/CÂU HỎI MỞ nào "
    "người đọc phải ngồi với không, hay logic đã KHÉP LẠI sạch sẽ thành 1 luận điểm gọn "
    "(không còn gì lấn cấn)? Nếu KHÉP LẠI sạch -> has_genuine_paradox=false -> dùng S1, "
    "KHÔNG phải S5 (kể cả khi câu mở/hook nghe như nghịch lý — xem lưu ý HOOK bên dưới).\n"
    "  LƯU Ý: hook dạng H1/§2b (kiểu 'mâu thuẫn… hay là…') là KỸ THUẬT VIẾT CÂU MỞ, KHÔNG "
    "tự động đồng nghĩa nghịch lý THẬT ở tầng structure — soi CẤU TRÚC lập luận, không soi "
    "câu chữ hook.\n"
    "  BẮT BUỘC NHẤT QUÁN 2 CHIỀU (structure=S5 <=> has_genuine_paradox=true, CẤM trạng "
    "thái lai — CODE sẽ ép lại nếu bạn lỡ lai, nhưng PHẢI cố trả đúng ngay từ đầu):\n"
    "    · Còn CĂNG THẲNG DƯ thật sau khi giải thích -> structure PHẢI là S5 VÀ "
    "has_genuine_paradox=true VÀ residual_tension = đúng 1 câu căng thẳng đó (khác null).\n"
    "    · Logic KHÉP LẠI sạch thành 1 luận điểm gọn -> structure PHẢI KHÁC S5 (thường S1) "
    "VÀ has_genuine_paradox=false VÀ residual_tension=null.\n"
    "    · TUYỆT ĐỐI KHÔNG được: has_genuine_paradox=true nhưng lại chọn structure khác S5 "
    "(vd 'S1 vì logic khép sạch' TRONG KHI vẫn báo paradox=true) — đây là tự mâu thuẫn "
    "ngay trong 1 output, không chấp nhận được dù rationale nghe hợp lý.\n\n"
    "3 HOOK (chọn `hook`):\n"
    "  H1 · Ngã ba: nêu nghịch lý nén, thả 1 lựa chọn kép, kết bằng câu hỏi.\n"
    "  H2 · Chi tiết bị bỏ qua: giấu 1 chi tiết, nâng mức cược của nó.\n"
    "  H3 · Sự thật + câu hỏi trực diện: 1 câu sự thật có số/tên, rồi 1 câu hỏi.\n\n"
    "TRƯỚC KHI CHỌN, PHẢI đánh giá `signals` TRUNG THỰC (dùng để audit, KHÔNG phải điền "
    "cho có):\n"
    "  - has_genuine_paradox: có THẬT 2 tín hiệu mâu thuẫn nhau (áp thước đo ở mục S5 "
    "trên), hay chỉ có vẻ lạ?\n"
    "  - residual_tension: BẮT BUỘC nếu has_genuine_paradox=true — viết ĐÚNG 1 câu mô tả "
    "căng thẳng/câu hỏi mở CÒN SÓT LẠI sau khi đã giải thích (không phải mô tả lại vẻ "
    "ngoài mâu thuẫn) — đây là bằng chứng bạn THẬT SỰ thấy còn vướng, không phải điền cho "
    "có. has_genuine_paradox=false -> để null.\n"
    "  - drivers: LIỆT KÊ TÊN từng driver/nguyên nhân ĐỘC LẬP đang tác động (KHÔNG phải "
    "đếm số fact, KHÔNG tự gõ 1 con số — liệt kê tên thật, vd [\"Hòa Phát\", \"Masan\", "
    "\"MB\", \"HDBank\"]). Số lượng driver sẽ được TÍNH TỪ danh sách này — PHẢI khớp "
    "đúng số driver bạn nhắc trong rationale, không nhiều hơn/ít hơn.\n"
    "  - has_central_thesis: có 1 luận điểm trung tâm rõ ràng gói được cả bài không?\n\n"
    "content_type: 'article' (bài phân tích), 'video' (kịch bản ngắn), hoặc "
    "'infographic-hint' (chỉ đáng làm infographic, không đủ chất liệu viết dài).\n"
    "secondary_structure: khung PHỤ nếu bài LAI (vd thân S1 nhưng 1 đoạn liệt kê theo "
    "S4) — null nếu thuần 1 khung. LƯU Ý: nếu drivers[] có từ 3 tên trở lên, hệ thống "
    "sẽ TỰ ÉP secondary_structure=S4 (không cần bạn tự điền, nhưng vẫn nên điền đúng "
    "cho nhất quán).\n"
    "rationale: 1-2 câu VÌ SAO khung này khớp hình dạng dữ kiện (không phải khung khác).\n\n"
    "output_channels (Phase 4.13 — CHỌN TUYẾN, KHÔNG ép sinh đủ 3 loại cho mọi tin): "
    "PHÁN theo HÌNH DẠNG THẬT của tin, KHÔNG đếm số cứng:\n"
    "  - infographic: true CHỈ khi có dữ liệu ĐỊNH LƯỢNG trình bày được bằng hình "
    "(số/%/mốc/xếp hạng đủ để dựng 1 tấm hình có nghĩa) — tin thuần bình luận/nhận "
    "định không số cụ thể thì false.\n"
    "  - video: true khi có NARRATIVE kể được (diễn biến, nhân vật, mâu thuẫn, hệ quả) "
    "— false nếu tin CHỈ LÀ bảng số/danh sách thuần, không có gì để 'kể'.\n"
    "  - article: MẶC ĐỊNH true — chỉ false khi tin quá VỤN (1-2 câu, không đủ chất "
    "liệu viết thành bài phân tích).\n"
    "channel_rationale: 1 câu/tuyến giải thích NGẮN vì sao hợp/không hợp (dùng để audit).\n\n"
    'Trả về DUY NHẤT JSON: {"content_type": str, "structure": "S1|S2|S3|S4|S5", '
    '"hook": "H1|H2|H3", "secondary_structure": "S1|S2|S3|S4|S5 hoặc null", '
    '"rationale": str, "signals": {"has_genuine_paradox": bool, '
    '"residual_tension": "str hoặc null", "drivers": [str, ...], '
    '"has_central_thesis": bool}, '
    '"output_channels": {"article": bool, "infographic": bool, "video": bool}, '
    '"channel_rationale": {"article": str, "infographic": str, "video": str}}. '
    "KHÔNG markdown, KHÔNG lời dẫn."
)

_CHANNELS = ("article", "infographic", "video")


def _default_channels() -> dict:
    return {c: True for c in _CHANNELS}


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
    signals: dict = field(default_factory=dict)   # has_genuine_paradox/residual_tension/drivers/driver_count/has_central_thesis
    fallback: bool = False              # True nếu đây là fallback an toàn (audit)
    # Phase 4.13 Mục A — content-fit router: tuyến nào ĐƯỢC sinh + lý do audit.
    # Mặc định CẢ 3 True (an toàn, xem docstring module) — KHÔNG suy diễn false.
    output_channels: dict = field(default_factory=_default_channels)
    channel_rationale: dict = field(default_factory=dict)


def _fallback(reason: str) -> RouterDecision:
    print(f"[CẢNH BÁO] StructureRouter fallback: {reason} -> dùng S1+H3 (trung tính, anchor D).")
    return RouterDecision(
        content_type="article", structure="S1", hook="H3", secondary_structure=None,
        rationale=f"Fallback an toàn: {reason}",
        signals={"has_genuine_paradox": False, "residual_tension": None, "drivers": [],
                "driver_count": 0, "has_central_thesis": True},
        fallback=True,
        # Fallback KHÔNG được tự ý cắt tuyến (router hỏng không phải lý do hợp lệ
        # để suy ra "tin này không hợp infographic/video") -> giữ CẢ 3 True.
        output_channels=_default_channels(),
        channel_rationale={c: "Fallback an toàn — giữ nguyên tuyến (không tự cắt khi router lỗi)"
                           for c in _CHANNELS},
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
    drivers_raw = signals_raw.get("drivers")
    # drivers[]: LLM liệt kê TÊN, driver_count TÍNH BẰNG CODE từ len(drivers) — bất
    # kỳ field "driver_count" rời nào LLM lỡ trả về đều BỊ BỎ QUA (không tin mù).
    drivers = ([str(d).strip() for d in drivers_raw if str(d).strip()]
              if isinstance(drivers_raw, list) else [])

    residual_tension_raw = signals_raw.get("residual_tension")
    residual_tension = str(residual_tension_raw).strip() or None if residual_tension_raw else None
    # Phase 3.6: has_genuine_paradox=true BẮT BUỘC kèm residual_tension khác null —
    # claim paradox mà không "chứng minh" được câu căng thẳng dư -> ÉP false (không
    # tin mù claim của LLM). Guard S5 bên dưới dùng ĐÚNG giá trị đã-ép này.
    has_genuine_paradox = bool(signals_raw.get("has_genuine_paradox", False)) and residual_tension is not None

    signals = {
        "has_genuine_paradox": has_genuine_paradox,
        "residual_tension": residual_tension if has_genuine_paradox else None,
        "drivers": drivers,
        "driver_count": len(drivers),
        "has_central_thesis": bool(signals_raw.get("has_central_thesis", False)),
    }

    # RÀNG BUỘC CỨNG #4 (Phase 4.8-B2, chiều NGƯỢC LẠI trước đây còn thiếu):
    # has_genuine_paradox EFFECTIVE=True -> ÉP structure=S5, GHI ĐÈ bất kể LLM
    # tự chọn structure gì -- chặn ca "tự mâu thuẫn" (paradox=true + residual_
    # tension hợp lệ nhưng LLM lại chọn S1 "logic khép sạch") phát hiện qua
    # probe Ví dụ A ở báo cáo Phase 4.8. Đặt TRƯỚC guard "S5 mà paradox=false"
    # bên dưới -- sau khi ép, guard đó không bao giờ còn kích hoạt cho case này.
    if signals["has_genuine_paradox"]:
        structure = "S5"

    if structure == "S5" and not signals["has_genuine_paradox"]:
        return _fallback("router chọn S5 nhưng signals.has_genuine_paradox=false "
                         "(vi phạm luật 'S5 cấm làm mặc định')")
    if structure not in STRUCTURES or hook not in HOOKS:
        return _fallback(f"structure/hook không hợp lệ: structure={structure!r} hook={hook!r}")

    secondary = str(data.get("secondary_structure") or "").strip().upper() or None
    if secondary is not None and secondary not in STRUCTURES:
        secondary = None   # field PHỤ -> bỏ giá trị lạ, KHÔNG fallback cả quyết định

    # Luật S4 (phục hồi, Phase 3.5): >=3 driver ĐỘC LẬP (đã tính, không tin LLM tự
    # điền) VÀ structure chính KHÔNG PHẢI S4 -> ÉP secondary_structure=S4, bất kể
    # LLM tự điền gì (kể cả None) — CHẶN Ở CODE, cùng triết lý với ràng buộc S5.
    if signals["driver_count"] >= 3 and structure != "S4":
        secondary = "S4"

    output_channels, channel_rationale = _parse_channels(data)

    return RouterDecision(
        content_type=str(data.get("content_type", "")).strip().lower() or "article",
        structure=structure, hook=hook, secondary_structure=secondary,
        rationale=str(data.get("rationale", "")).strip() or "(router không cho rationale)",
        signals=signals, fallback=False,
        output_channels=output_channels, channel_rationale=channel_rationale,
    )


def _parse_channels(data: dict) -> tuple[dict, dict]:
    """output_channels/channel_rationale (Phase 4.13) — parse LỎNG: field thiếu/
    sai kiểu/thiếu khoá -> MẶC ĐỊNH True cho khoá đó (an toàn, xem docstring
    module: KHÔNG tự ý cắt tuyến khi không chắc). Hàm THUẦN, tách riêng để
    route_from_llm_output không phình to."""
    channels_raw = data.get("output_channels")
    channels_raw = channels_raw if isinstance(channels_raw, dict) else {}
    channels = {c: bool(channels_raw[c]) if c in channels_raw else True for c in _CHANNELS}

    rationale_raw = data.get("channel_rationale")
    rationale_raw = rationale_raw if isinstance(rationale_raw, dict) else {}
    rationale = {c: str(rationale_raw.get(c, "")).strip() for c in _CHANNELS}

    return channels, rationale


def _log_decision(brief: ProductionBrief, decision: RouterDecision) -> None:
    print(f"[router] '{brief.title[:60]}' -> structure={decision.structure}"
         f"{'/' + decision.secondary_structure if decision.secondary_structure else ''} "
         f"hook={decision.hook} fallback={decision.fallback} | signals={decision.signals} "
         f"| rationale: {decision.rationale}")
    # Phase 4.13 Mục A — "Gate hiển thị": in output_channels/channel_rationale ra
    # log audit (KHÔNG thêm cột Sheet, cùng triết lý route_once.py — file JSON +
    # log, không đổi schema Sheet).
    print(f"[router-channels] '{brief.title[:60]}' -> {decision.output_channels} "
         f"| rationale: {decision.channel_rationale}")


def run_route(llm: LLMClient, brief: ProductionBrief, classification: dict | None = None, *,
              model: str | None = None, fail_loud: bool = False) -> RouterDecision:
    """Gọi LLM bước 'router' -> RouterDecision đã validate + LOG (audit). LÙI
    MƯỢT mặc định (fail_loud=False): lỗi/JSON hỏng -> fallback S1+H3, KHÔNG crash.
    temperature=0.0 (Phase 3.6, ổn định) — backend hỗ trợ (AnthropicLLM) sẽ dùng
    đúng 0.0; backend không hỗ trợ (ClaudeCodeLLM/`claude -p`) bỏ qua tham số này
    (no-op, xem agents/base.py), độ ổn định lúc đó dựa vào thước đo residual_tension."""
    raw = llm.complete(_SYSTEM, build_router_prompt(brief, classification),
                       model=model, fail_loud=fail_loud, temperature=0.0)
    decision = route_from_llm_output(raw)
    _log_decision(brief, decision)
    return decision
