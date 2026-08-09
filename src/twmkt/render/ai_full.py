"""Infographic mode "ai_full" — AI (gpt-image-2) sinh TOÀN BỘ ảnh (chữ/số/
layout/minh hoạ), lớp CODE tất định chỉ ĐÓNG DẤU brand LÊN TRÊN sau cùng
(logo/nguồn/disclaimer) — NGƯỢC hẳn kiến trúc Hybrid cũ (AI ở lớp DƯỚI, HTML
đè lên che mất — lý do Hybrid "không thấy gì", xem QUYẾT ĐỊNH LEAD 2026-07-21).

CĂN CỨ QUYẾT ĐỊNH ĐẢO HƯỚNG: spike so sánh ảnh AI 100% (gpt-image-2) với
renderer HTML/SVG thuần (2 vòng cải tiến template) cho thấy AI vượt xa —
xem báo cáo trong hội thoại 2026-07-21. Quyết định cũ "chất lượng phụ thuộc
template, không phải AI" ĐÃ BỊ BÁC BỎ.

KẾT LUẬN BƯỚC 1 (A/B/C test cùng ngày, xem báo cáo): prompt = JSON THÔ, KHÔNG
qua lớp LLM diễn giải lại, cho kết quả giàu thông tin + chính xác NHẤT (đúng
cách user tự làm đẹp nhất trên ChatGPT app: dán JSON, không nói gì thêm).
KHÔNG bọc thêm lớp diễn giải nào — chỉ thêm ĐÚNG các chỉ dẫn AN TOÀN bắt buộc
(cấm vẽ bản đồ/logo, photorealistic) vì (a) tự nó VẪN vẽ bản đồ Việt Nam sai/
thiếu đảo khi thấy field `related` — bằng chứng ảnh thật.

ĐẢO HƯỚNG P0 (2026-07-23, PHẦN B, quyết định Lead — xem STOP-REPORT phiên
feature/infographic-frame): prompt KHÔNG còn nói bất kỳ hình thức "chừa dải
trống"/"safe zone" nào (kể cả từ đồng nghĩa) — LÝ DO CĂN CỐT: model sinh ảnh
coi MỌI DANH TỪ trong prompt là VẬT THỂ CẦN VẼ. Nói "chừa một dải trống ở
đỉnh" → nó vẽ MỘT DẢI (bằng chứng ảnh thật: dải kem ở mép trên bản v4).
Đây là TÍNH CHẤT của model, KHÔNG PHẢI bug — không sửa được bằng cách diễn
đạt khéo hơn, CHỈ sửa được bằng cách bỏ HẲN loại chỉ dẫn này (xem
`_check_prompt_banned_words`, `build_ai_full_prompt` v5). Vị trí pixel của
logo/nguồn/disclaimer giờ do brand_stamp.py lo TUYỆT ĐỐI bằng kiến trúc
(khung cứng đáy, matting — xem brand_stamp.py module docstring), KHÔNG còn
phụ thuộc AI "chừa chỗ đúng".

⚠️ BẢN ĐỒ VIỆT NAM: KHÔNG asset chuẩn nào tồn tại trong repo/content-rules/
aigen-pipeline/data_root tại thời điểm viết (2026-07-21, đã tìm kỹ, xem báo
cáo DỪNG KHI #1) — module này do đó LUÔN cấm AI vẽ bản đồ/sơ đồ địa lý VN
TUYỆT ĐỐI (không có nhánh "chừa chỗ dán bản đồ thật" vì chưa có gì để dán).
Khi Lead cấp asset chuẩn, bổ sung `_MAP_ASSET_PATH` + logic dán riêng.

Theme-rules (Bước 2): copy nguyên văn từ content-rules/ (sibling, KHÔNG theo
git) vào `prompts/themes/Infographic_Theme_{Dark,Light}.md` (đổi tên bỏ tiền
tố "FVA_" — Phase A dọn `prompts/`, 2026-07-3x, KHÔNG đổi nội dung) — MỘT
NGUỒN, không sửa nội dung khi đọc. `information_score`/layout selector implement lại
Ở CODE (tất định) theo đúng công thức trong theme file, KHÔNG để LLM tự đoán
layout — cùng triết lý "AI hiểu ở Brief, CODE phán ở Guardrail" xuyên suốt dự
án này.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from PIL import Image

from .brand_stamp import (
    load_theme_palette,
    resolve_theme_name,
    select_ai_size as _select_ai_size,
    select_full_canvas_ai_size as _select_full_canvas_ai_size,
)

logger = logging.getLogger("twmkt.render.ai_full")

_DEFAULT_MODEL = "gpt-image-2"
_DEFAULT_QUALITY = "medium"
_API_URL = "https://api.openai.com/v1/images/generations"
_TIMEOUT_S = 120
_PROMPT_VERSION = "v13"  # v13: TASK-013/017/019 real subject + layout + logo fixes.

# Bước 4.3 — sinh ĐÚNG size cho từng tỷ lệ (KHÔNG crop sau bởi API — nhờ
# brand_stamp.matting() fit-inside/contain, xem SỬA LỖI ĐẶC TẢ 2026-07-24 --
# brand_stamp.py module docstring). API gpt-image-2 chấp nhận size TUỲ Ý miễn
# chia hết cho 16 (xác nhận thật 2026-07-21 VÀ tái xác nhận 2026-07-24, xem
# `brand_stamp.select_ai_size` docstring) -- KHÔNG phải enum cố định như
# gpt-image-1.
#
# 2026-07-24 (SỬA LỖI ĐẶC TẢ) -- bảng cũ ở đây (1024x1280 cho 4:5, 864x1536
# cho 9:16...) đúng tỷ lệ HIỂN THỊ cuối (4:5, 9:16) nhưng SAI mục tiêu thật:
# ảnh AI cần khớp ratio_inner = FINAL_W/(FINAL_H-BAND_H) (tỷ lệ vùng TRONG
# sau khi trừ band đáy), KHÔNG phải tỷ lệ khung CUỐI -- lệch này (vd 4:5:
# 0.8 cũ vs ~0.865 thật) là 1 phần nguyên nhân matting phải cắt nhiều, góp
# phần vào bug tiêu đề cụt đỉnh + chip cụt đáy (xem HANDOFF phiên trước).
# Bảng dưới đây CHỈ là THAM KHẢO mặc định (settings=None, dùng cho test/hiển
# thị nhanh) -- get_or_generate_raw_image() gọi select_ai_size() TƯƠI mỗi lần
# generate thật, tôn trọng settings override (final_size/bottom_band_min_px).
RATIO_SIZES: dict[str, tuple[int, int]] = {
    ratio: _select_ai_size(ratio)[0] for ratio in ("1:1", "4:5", "9:16")
}
FULL_CANVAS_RATIO_SIZES: dict[str, tuple[int, int]] = {
    ratio: _select_full_canvas_ai_size(ratio)[0] for ratio in RATIO_SIZES
}

# 2026-07-23 (Phần B1, yêu cầu Lead) -- CẤM CỨNG mọi từ/cụm liên quan "chừa
# trống"/safe-zone trong prompt gửi API, kể cả vô tình gõ lại khi sửa prompt
# sau này (model sinh ảnh coi danh từ = vật thể cần vẽ, xem module docstring
# + `_check_prompt_banned_words`). Kiểm tra CHẠY TRƯỚC khi gửi API.
_BANNED_PROMPT_WORDS = [
    "safe zone", "safe-zone", "reserve", "leave blank", "blank band",
    "empty space", "clear space", "margin", "padding",
    "chừa trống", "chừa chỗ", "để trống",
]

_THEME_FILES = {
    "dark": "Infographic_Theme_Dark.md",
    "light": "Infographic_Theme_Light.md",
}

# Trích ĐÚNG design token màu từ 2 theme file (tránh nhúng nguyên 300 dòng
# markdown vào mỗi prompt -- tốn token, API tính phí theo prompt length).
_THEME_COLORS = {
    "dark": {
        "background": "#061521",
        "background_secondary": "#0C2232",
        "text_primary": "#F3EBDD",
        "text_secondary": "#C8D0D4",
        "gold": "#C9A14A",
    },
    "light": {
        "background": "#F6F0E5",
        "background_secondary": "#ECE8E0",
        "text_primary": "#1F1F1F",
        "text_secondary": "#60676B",
        "gold": "#C9A14A",
    },
}


class AiFullError(Exception):
    """Lỗi gọi API/parse response -- CHỈ dùng NỘI BỘ, KHÔNG lộ ra ngoài
    get_or_generate_raw_image() (luôn trả (None, warning), không raise)."""


def compute_information_score(spec: dict) -> int:
    """Công thức NGUYÊN VĂN theo Theme-rules §6 (Dark) -- comparison_group_count/
    timeline_point_count = 0 vì schema Infographic JSON hiện tại (Phase 4.11:
    title/subtitle/hero/market/highlights/related/priority/source) chưa có 2
    trường đó. Tất định, không LLM đoán."""
    hero_count = len(spec.get("hero") or [])
    metric_count = len(spec.get("main") or spec.get("market") or [])
    highlight_count = len(spec.get("highlights") or [])
    return hero_count * 2 + metric_count + highlight_count


def select_layout(score: int, *, theme: str = "dark") -> str:
    """Legacy selector giữ tương thích cho caller/test cũ.

    Renderer production không còn gọi selector này: Dark/Light chỉ cung cấp
    màu, không quyết định bố cục.

    Layout selector THEO ĐÚNG bảng ngưỡng Theme-rules §7. Khi tài liệu ghi
    "X hoặc Y" (ngưỡng chồng lấn 2 lựa chọn hợp lệ) -- CHỌN 1 CỐ ĐỊNH để tất
    định (Dark: D3 thay vì "D2 hoặc D3" vì D3 khớp infographic nhiều chỉ số
    hơn D2 vốn dành cho ảnh+chuyện ngang vai; Light: L3 thay vì "L2 hoặc L3"
    cùng lý do). comparison/timeline luôn 0 ở schema hiện tại nên 2 nhánh đầu
    không bao giờ kích hoạt -- giữ trong code cho đúng thứ tự ưu tiên tài liệu
    gốc, phòng khi schema thêm 2 trường đó sau này."""
    if theme == "light":
        if score <= 6:
            return "L1"
        if score <= 13:
            return "L3"
        if score <= 22:
            return "L3"
        return "SPLIT_TO_SERIES_OR_REPORT"
    if score <= 6:
        return "D1"
    if score <= 12:
        return "D3"
    if score <= 20:
        return "D4"
    return "SPLIT_TO_CAROUSEL"


def select_content_layout(score: int) -> str:
    """Layout trung lập theme, thích ứng một hoặc nhiều cụm dữ liệu."""
    if score <= 6:
        return "EDITORIAL_HERO"
    if score <= 12:
        return "FLEX_DATA_RAIL"
    if score <= 20:
        return "FLEX_MODULAR_GRID"
    return "SPLIT_TO_SERIES"


def _check_prompt_banned_words(prompt: str) -> None:
    """Phần B1 (2026-07-23, yêu cầu Lead) -- chặn CỨNG mọi từ/cụm liên quan
    "chừa trống"/safe-zone lọt vào prompt gửi API (kể cả vô tình gõ lại khi
    sửa prompt sau này) -- KHÔNG dựa vào tự giác diễn đạt. raise ValueError
    NGAY nếu phát hiện, KHÔNG gọi API. Chạy TRƯỚC MỌI lượt gọi
    `_call_openai_images_api` (xem `get_or_generate_raw_image`)."""
    lower = prompt.lower()
    hit = [w for w in _BANNED_PROMPT_WORDS if w.lower() in lower]
    if hit:
        raise ValueError(
            f"Prompt chứa từ CẤM (Phần B1 -- model sinh ảnh coi danh từ là vật thể cần vẽ, "
            f"'chừa trống' -> nó vẽ MỘT DẢI, xem module docstring): {hit}"
        )


def _content_unit_kinds(spec: dict) -> list[str]:
    units = spec.get("content_units")
    if not isinstance(units, list):
        return []
    kinds: list[str] = []
    for unit in units:
        if not isinstance(unit, dict):
            continue
        value = (
            unit.get("type")
            or unit.get("kind")
            or unit.get("unit_type")
            or unit.get("content_type")
        )
        if value:
            kinds.append(str(value).strip().casefold())
    return kinds


def _qualitative_visual_direction(spec: dict) -> str:
    """Renderer direction only; không đổi schema hoặc diễn giải lại facts."""
    kinds = _content_unit_kinds(spec)
    if not kinds:
        return ""
    process = sum(
        kind in {"process", "timeline", "procedure", "workflow", "sequence"}
        for kind in kinds
    )
    relation = sum(
        kind in {"relation", "relationship", "state_change", "before_after"}
        for kind in kinds
    )
    if process > len(kinds) / 2:
        return (
            "Nội dung chủ yếu là process/timeline: trình bày các bước theo đúng "
            "trình tự có trong content_units. Ảnh chụp vẫn là neo thị giác; sơ "
            "đồ bước chỉ là lớp thông tin, không biến thành cartoon/vector."
        )
    if relation > len(kinds) / 2:
        return (
            "Nội dung chủ yếu là relation/state_change: trình bày quan hệ giữa "
            "các bên hoặc trạng thái trước–sau đúng như content_units. Ảnh chụp "
            "vẫn là neo thị giác; sơ đồ chỉ là lớp thông tin."
        )
    return ""


def _photo_subject_direction(spec: dict) -> str:
    """ADR-002 (2026-08-07, chủ dự án) + TASK-013 Phần A: ra lệnh dùng CHỦ THỂ
    THẬT lấy từ spec (tên doanh nghiệp/tổ chức/sự kiện trong title/subtitle/
    hero) thay cho bảng 10 category cứng khớp-keyword từng dùng ở đây.

    Root cause đã xác minh (xem ADR-002 + TASK-013 contract): bảng cũ khớp
    keyword ngành ("thị trường", "cổ phiếu"...) vào MỘT category chung
    ("a real securities trading workstation... generic price chart") bất kể
    bài viết thật sự nói về gì -- bài "FPT bắt tay OpenAI, khai phá THỊ
    TRƯỜNG 240 tỷ USD" (hợp tác công nghệ) bị ép ra ảnh bàn giao dịch chứng
    khoán chỉ vì trùng từ "thị trường". Đây KHÔNG phải chỗ để CODE tự đoán
    ngành nghề bằng keyword nữa -- hàm chỉ trích xuất TẤT ĐỊNH các đoạn text
    định danh chủ thể rồi giao cho model đọc JSON để tự nhận diện, cấm quy
    về category chung chung do trùng từ khoá ngành."""
    subject_fragments: list[str] = []
    for key in ("title", "subtitle"):
        value = spec.get(key)
        if value:
            subject_fragments.append(str(value).strip())
    for item in spec.get("hero") or []:
        if isinstance(item, dict):
            label = item.get("label")
            if label:
                subject_fragments.append(str(label).strip())
        elif item:
            subject_fragments.append(str(item).strip())
    subject_text = " | ".join(fragment for fragment in subject_fragments if fragment)
    if not subject_text:
        subject_text = "chủ thể chính nêu trong dữ liệu JSON bên dưới"

    return (
        "PHOTO SUBJECT ANCHOR: xác định CHỦ THỂ THẬT (tên doanh nghiệp, tổ "
        f'chức, sản phẩm hoặc sự kiện) được nêu trong: "{subject_text}". '
        "Dựng bối cảnh ảnh chụp thật thể hiện ĐÚNG chủ thể đó -- đúng ngành "
        "nghề, sản phẩm, trụ sở hoặc hoạt động thật của chủ thể -- được phép "
        "hiển thị logo, biển hiệu hoặc thương hiệu thật của đúng chủ thể đó "
        "nếu tự nhiên xuất hiện trong khung hình (ADR-002, chủ dự án 2026-"
        "08-07). TUYỆT ĐỐI KHÔNG quy về một category chung chung chỉ vì "
        "trùng từ khoá ngành -- ví dụ: không tự động vẽ bàn giao dịch chứng "
        "khoán hay biểu đồ giá chỉ vì tiêu đề có chữ 'thị trường' hoặc 'cổ "
        "phiếu' nếu bài không thực sự nói về giao dịch chứng khoán. Ảnh phải "
        "giải thích được chủ thể ngay từ cái nhìn đầu tiên, không chỉ gợi "
        "không khí 'kinh doanh' chung chung."
    )


def _spec_for_image_prompt(spec: dict) -> tuple[dict, list[str]]:
    """Omit intentionally empty optional blocks before calling the image model.

    An absent block must not be named in the prompt: image models can treat even
    a negative mention as an object to draw.  Only the two optional presentation
    blocks covered by the Composer contract are omitted; all factual fields are
    preserved verbatim.
    """
    prompt_spec = dict(spec)
    omitted: list[str] = []
    for key in ("subtitle", "related"):
        value = prompt_spec.get(key)
        is_empty = (
            value is None
            or isinstance(value, (list, tuple, dict, set)) and not value
            or isinstance(value, str) and not value.strip()
        )
        if key in prompt_spec and is_empty:
            prompt_spec.pop(key)
            omitted.append(key)
    return prompt_spec, omitted


def build_ai_full_prompt(
    spec: dict,
    *,
    theme: str | None = None,
    ratio: str = "4:5",
    postflight_instruction: str = "",
) -> str:
    """BƯỚC 1 kết luận: JSON THÔ thắng -- KHÔNG bọc qua LLM diễn giải lại nội
    dung. Prompt = JSON spec (serialize thẳng, giữ NGUYÊN mọi field) + ĐÚNG
    các chỉ dẫn AN TOÀN bắt buộc. KHÔNG thêm mô tả bố cục/diễn giải nội dung
    nào khác ngoài rào an toàn.

    v5 (Phần B, 2026-07-23, ĐẢO HƯỚNG P0): `spec` truyền vào đây PHẢI ĐÃ qua
    `apply_density_cap()` (Phần C, gọi ở `get_or_generate_raw_image`) --
    hàm này KHÔNG tự cắt/đếm mục, chỉ mô tả bố cục DƯƠNG TÍNH + negative
    prompt, KHÔNG còn nói bất kỳ hình thức "chừa chỗ" nào (xem
    `_check_prompt_banned_words`, module docstring)."""
    theme, theme_id, colors = load_theme_palette(
        theme,
        content_type=spec.get("content_type"),
    )
    score = compute_information_score(spec)
    layout_id = select_content_layout(score)

    prompt_spec, _omitted_empty_blocks = _spec_for_image_prompt(spec)
    spec_json_str = json.dumps(prompt_spec, ensure_ascii=False, indent=2)
    if theme == "bright":
        visual_direction = """
Bright Editorial: nền trắng sáng đến ivory rất nhạt, có ánh xanh trời nhẹ.
Tiêu đề navy trang trọng, số quan trọng màu gold ấm, nội dung charcoal; phân
vùng bằng đường navy/gold mảnh và khoảng trắng. Dùng ngôn ngữ ảnh chụp
photojournalistic tự nhiên làm neo thị giác chính, hòa vào header hoặc một
phân khu lớn bằng chuyển sắc trắng. Thiết kế nghiêm túc, cao cấp, không
vintage, không dashboard UI.
""".strip()
    else:
        visual_direction = (
            "Full-canvas editorial design using the configured theme colors; "
            "clear hierarchy, natural photography and restrained dividers."
        )
    photo_subject_direction = _photo_subject_direction(spec)
    photo_subject_block = f"\n8. {photo_subject_direction}"
    qualitative_direction = _qualitative_visual_direction(spec)
    qualitative_block = (
        f"\n9. {qualitative_direction}" if qualitative_direction else ""
    )
    retry_block = (
        "\n9. HẬU KIỂM LẦN TRƯỚC ĐÃ FAIL: "
        + postflight_instruction.strip()
        if postflight_instruction.strip()
        else ""
    )

    safety_block = f"""
YÊU CẦU BẮT BUỘC (không thoả hiệp):
1. Dùng TOÀN BỘ canvas tỷ lệ {ratio} một cách tự nhiên. Không đặt infographic
   vào poster/card/màn hình/khung con nhỏ hơn ảnh. Các phân khu hợp thành một
   thiết kế liền mạch phủ toàn kích thước đầu ra. Full-bleed full-canvas:
   no border around the entire canvas, no letterbox, no cream or beige band.
2. {visual_direction}
3. BỐ CỤC CỨNG (yêu cầu trực tiếp của chủ dự án): khối tiêu đề/chữ chính đặt
   bên TRÁI canvas, hình minh hoạ chủ thể (mục 8) chiếm phần bên PHẢI. Góc
   trên-phải LUÔN giữ thị giác nhẹ, không đặt chữ, số hay chi tiết cốt lõi
   tại đó -- đây là nơi DUY NHẤT lớp deterministic dán logo brand sau cùng.
   Mép dưới dùng nền ít chi tiết; không đặt dữ kiện cốt lõi ở dòng cuối vì
   lớp deterministic đặt nguồn và disclaimer tại đó. Đây không phải dải
   trống hay khung riêng: nền và hình ảnh vẫn tiếp tục tự nhiên đến đủ bốn
   mép canvas.
4. KHÔNG tự vẽ watermark, chữ "FVA Capital", nguồn, tác giả, ngày đăng hoặc
   disclaimer của trang này -- các thành phần đó do lớp deterministic dán
   riêng ở góc trên-phải và dải đáy (mục 3). Field "source" chỉ cung cấp bối
   cảnh, không được biến thành chữ trên ảnh. Logo, biển hiệu hoặc thương hiệu
   THẬT của đúng doanh nghiệp hay sự kiện được nêu tên trong JSON ĐƯỢC PHÉP
   xuất hiện tự nhiên trong khung hình (ADR-002, chủ dự án 2026-08-07) --
   KHÔNG đặt vào góc trên-phải để tránh chồng lấn logo FVA.
5. KHÔNG vẽ bản đồ, biên giới hoặc hình lãnh thổ. ƯU TIÊN HÌNH ẢNH THẬT:
   dùng ngôn ngữ ảnh chụp báo chí/doanh nghiệp tự nhiên làm minh hoạ chính,
   với ánh sáng, vật liệu, tỷ lệ, phối cảnh và môi trường giống ảnh máy ảnh.
   Ít nhất một vùng ảnh quang thực đủ lớn để làm neo thị giác; không biến ảnh
   chụp thành thumbnail nhỏ giữa các icon. Đây phải là AI photorealistic mô
   tả bối cảnh liên quan trực tiếp đến chủ thể được nêu tên (mục 8) -- ĐƯỢC
   PHÉP hiển thị logo doanh nghiệp, biển hiệu có thương hiệu hoặc công trình
   nhận diện cụ thể của ĐÚNG chủ thể đó (ADR-002, chủ dự án 2026-08-07).
   KHÔNG dựng thành ảnh tài liệu/bằng chứng giả: không chú thích như ảnh
   chụp đúng thời điểm/địa điểm sự kiện, không bịa số liệu, văn bản hay biểu
   đồ trông như tài liệu chính thức. Không dựng gương mặt người thật. Không
   cartoon, vector, flat illustration, clip-art, icon-led composition hay
   3D-render.
6. Chỉ dùng ĐÚNG số liệu có trong JSON. KHÔNG tự cộng tổng, tính trung bình,
   tỷ lệ, chênh lệch, xếp hạng hoặc sinh thêm bất kỳ con số nào. Nếu một phân
   khu không có fact hỗ trợ thì bỏ phân khu, không điền số trang trí.
7. Giữ nguyên dấu tiếng Việt và cách viết số, kể cả dấu phẩy thập phân.
   Chỉ vẽ các khối có key trong JSON; không suy ra hoặc bổ sung khối nội dung
   không có key trong JSON.
{photo_subject_block}{qualitative_block}{retry_block}

Theme màu: {theme_id}. Nền {colors["background.primary"]}, vùng phụ
{colors["background.secondary"]}, chữ chính {colors["text.primary"]}, chữ phụ
{colors["text.secondary"]}, Gold {colors["accent.gold"]}. Theme chỉ cấp màu;
bố cục thích ứng với số chủ thể thực tế. Mức thông tin: {score}; layout tham
chiếu: {layout_id}.

Dữ liệu Infographic (JSON, giữ nguyên mọi trường):
{spec_json_str}
""".strip()
    return safety_block


# =====================================================================
# Phần C (2026-07-23, quyết định Lead) -- GIỚI HẠN TRÊN mật độ nội dung.
# ĐẶT Ở ĐÂY (pre-flight của renderer), KHÔNG ở Contract Validator: giới hạn
# mật độ là SỨC CHỨA LAYOUT, phụ thuộc TỶ LỆ KHUNG (4:5 chứa nhiều hơn 9:16)
# -- Contract Validator kiểm HỢP ĐỒNG NỘI DUNG, không biết gì về tỷ lệ ảnh.
# Nhét ràng buộc layout vào đó = dựng phụ thuộc ngược từ tầng render lên tầng
# content. NGUYÊN NHÂN: rules v2.1 §7.3 chỉ có vế chống THIẾU, không có vế
# chống THỪA -- nguồn giàu (nhiều dòng LNTT/nhiều doanh nghiệp) khiến Composer
# nhồi hết, HOÀN TOÀN ĐÚNG LUẬT hiện có. KHÔNG sửa rules v2.1 (sẽ gò Composer
# lại đúng cái vừa cởi được) -- cắt ở ĐÂY, sau khi Composer đã sinh xong.
# =====================================================================

_DEFAULT_DENSITY_CAPS: dict[str, dict[str, int]] = {
    "4:5":  {"market": 12, "highlights": 3, "related": 12},
    "9:16": {"market": 8,  "highlights": 3, "related": 8},
    "1:1":  {"market": 8,  "highlights": 3, "related": 8},
}


def _resolve_density_caps(ratio: str, settings=None) -> dict[str, int]:
    if settings is not None:
        cfg = settings.get(f"infographic.ai_full.density_caps.{ratio}")
        if isinstance(cfg, dict):
            return {"main": int(cfg.get("main", cfg.get("market", 999))), "highlights": int(cfg.get("highlights", 999)),
                    "related": int(cfg.get("related", 999))}
    legacy = _DEFAULT_DENSITY_CAPS.get(ratio, _DEFAULT_DENSITY_CAPS["4:5"])
    return {
        "main": legacy["market"],
        "highlights": legacy["highlights"],
        "related": legacy["related"],
    }


def _item_label(item) -> str:
    return item.get("label", "") if isinstance(item, dict) else str(item)


def _priority_rank(label: str, priority: dict) -> int:
    """0 = primary (giữ TRƯỚC TIÊN), 1 = secondary, 2 = minor HOẶC CHƯA PHÂN
    LOẠI (coi ngang minor -- an toàn, KHÔNG đoán quan trọng hơn mục đã được
    Composer xếp minor tường minh)."""
    if label in (priority.get("primary") or []):
        return 0
    if label in (priority.get("secondary") or []):
        return 1
    return 2


def apply_density_cap(spec: dict, *, ratio: str, settings=None) -> tuple[dict, list[dict]]:
    """C1-C3: cắt CÓ CHỦ ĐÍCH các block "main"/"highlights"/"related" vượt
    giới hạn mật độ theo tỷ lệ (config infographic.ai_full.density_caps) --
    chấp nhận alias legacy `market` để render dữ liệu cũ,
    GIỮ priority.primary + secondary TRƯỚC, cắt minor/chưa phân loại TRƯỚC
    (ổn định: trong cùng hạng ưu tiên, giữ đúng thứ tự xuất hiện gốc, KHÔNG
    xáo trộn). KHÔNG cắt/tràn im lặng -- trả kèm `truncated` (C3-C4):
    [{block, kept, dropped, reason, dropped_labels}] rỗng nếu không cắt gì.
    KHÔNG sửa `hero`/`title`/`subtitle`/`priority`/`source` -- CHỈ 3 block
    liệt kê trên bị giới hạn (đúng phạm vi C1)."""
    caps = _resolve_density_caps(ratio, settings)
    priority = spec.get("priority") or {}
    capped = dict(spec)
    truncated: list[dict] = []

    for logical_block in ("main", "highlights", "related"):
        # v3.4 chốt tên `main`; `market` là contract legacy vẫn phải đọc được.
        block = (
            "main"
            if logical_block == "main" and "main" in spec
            else "market"
            if logical_block == "main"
            else logical_block
        )
        cap = caps.get(logical_block)
        items = spec.get(block) or []
        if not cap or len(items) <= cap:
            continue
        ranked = sorted(range(len(items)), key=lambda i: _priority_rank(_item_label(items[i]), priority))
        keep_idx = sorted(ranked[:cap])
        dropped_idx = [i for i in range(len(items)) if i not in set(keep_idx)]
        capped[block] = [items[i] for i in keep_idx]
        entry = {
            "block": block, "kept": len(keep_idx), "dropped": len(dropped_idx),
            "reason": f"vượt giới hạn mật độ {cap} cho tỷ lệ {ratio}",
            "dropped_labels": [_item_label(items[i]) for i in dropped_idx],
        }
        truncated.append(entry)

    # Density cap must remove every alternate path by which the image model
    # could still see a dropped item. `priority` is prompt metadata, so keeping
    # a dropped label there silently defeats the cap.
    dropped_labels = {
        label
        for entry in truncated
        for label in entry["dropped_labels"]
    }
    if dropped_labels and isinstance(priority, dict):
        retained_labels = {
            _item_label(item)
            for block in ("hero", "main", "market", "highlights", "related")
            for item in (capped.get(block) or [])
        }
        removed_refs = dropped_labels - retained_labels
        capped_priority = {}
        for key, values in priority.items():
            if isinstance(values, list):
                capped_priority[key] = [
                    value for value in values if value not in removed_refs
                ]
            else:
                capped_priority[key] = values
        capped["priority"] = capped_priority
        for entry in truncated:
            entry["removed_priority_refs"] = [
                label
                for label in entry["dropped_labels"]
                if label in removed_refs
            ]

    return capped, truncated


def _manifest_paths(assets_dir: Path) -> tuple[Path, Path]:
    return assets_dir / "generated", assets_dir / "manifest.json"


def _load_manifest(manifest_path: Path) -> dict:
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("assets/manifest.json (ai_full) lỗi parse -- coi như rỗng")
        return {}


def _save_manifest(manifest_path: Path, data: dict) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _cache_key(
    spec: dict,
    theme: str,
    ratio: str,
    postflight_instruction: str = "",
) -> str:
    raw = (
        json.dumps(spec, ensure_ascii=False, sort_keys=True)
        + "|"
        + theme
        + "|"
        + ratio
        + "|"
        + _PROMPT_VERSION
        + "|"
        + postflight_instruction
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _call_openai_images_api(prompt: str, *, api_key: str, model: str, size: str, quality: str) -> tuple[bytes, dict | None]:
    """Trả (png_bytes, usage) -- `usage` = dict token thật OpenAI trả về
    (input_tokens/output_tokens/total_tokens, xem response thật đã xác nhận
    2026-07-21: KHÔNG có field cost/USD trực tiếp, chỉ có token). Ghi token
    THẬT vào manifest thay vì tự đoán USD (chưa có bảng giá gpt-image-2 xác
    nhận) -- xem `record_actual_cost()` khi Lead có bảng giá đối chiếu."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "prompt": prompt, "size": size, "quality": quality, "n": 1}
    try:
        resp = httpx.post(_API_URL, headers=headers, json=payload, timeout=_TIMEOUT_S)
    except httpx.TimeoutException as e:
        raise AiFullError(f"timeout sau {_TIMEOUT_S}s gọi OpenAI Images API") from e
    except httpx.HTTPError as e:
        raise AiFullError(f"lỗi mạng gọi OpenAI Images API: {e}") from e

    if resp.status_code != 200:
        raise AiFullError(f"OpenAI Images API trả lỗi HTTP {resp.status_code}: {resp.text[:200]}")

    try:
        data = resp.json()
        item = data["data"][0]
    except Exception as e:
        raise AiFullError(f"response OpenAI không đúng shape mong đợi: {e}") from e
    usage = data.get("usage") if isinstance(data, dict) else None

    if "b64_json" in item and item["b64_json"]:
        import base64
        return base64.b64decode(item["b64_json"]), usage
    if "url" in item and item["url"]:
        try:
            img_resp = httpx.get(item["url"], timeout=_TIMEOUT_S)
            img_resp.raise_for_status()
            return img_resp.content, usage
        except httpx.HTTPError as e:
            raise AiFullError(f"tải ảnh từ URL OpenAI trả về thất bại: {e}") from e
    raise AiFullError("response OpenAI không có 'b64_json' lẫn 'url' -- không có ảnh để dùng")


def get_or_generate_raw_image(
    spec: dict,
    *,
    theme: str | None = None,
    ratio: str = "4:5",
    regenerate: bool = False,
    assets_dir: str | Path | None = None,
    settings=None,
    postflight_instruction: str = "",
) -> tuple[Path | None, str]:
    """Điểm vào DUY NHẤT gọi API thật -- cache-first (B3 CÙNG NẾP ai_background.py).
    Trả (đường_dẫn_PNG_THÔ_chưa_đóng_dấu_brand, cảnh_báo). Cache key theo
    hash(spec + theme + ratio + prompt_version) -- ĐỔI 1 field spec (kể cả
    thứ tự key khác nhau không ảnh hưởng, dùng sort_keys) -> hash khác -> cache
    MISS, gọi API lại. KHÔNG raise ra ngoài cho lỗi mạng/thiếu key -- (None,
    cảnh báo). NGOẠI LỆ (2026-07-23, Phần B1): raise ValueError NGAY nếu
    prompt lọt từ cấm (`_check_prompt_banned_words`) -- đây là lỗi LẬP TRÌNH
    thật (bug ở `build_ai_full_prompt`), KHÔNG phải lỗi vận hành bình
    thường, KHÔNG được nuốt thành warning."""
    if ratio not in RATIO_SIZES:
        return None, f"CẢNH BÁO: tỷ lệ '{ratio}' không hỗ trợ (chỉ {list(RATIO_SIZES)})."
    theme = resolve_theme_name(theme, content_type=spec.get("content_type"))

    if assets_dir is None:
        from ..config import data_path
        cache_dir_name = (
            settings.get("infographic.ai_full.cache_dir", "assets_ai_full")
            if settings is not None
            else "assets_ai_full"
        )
        assets_dir = data_path(cache_dir_name, settings=settings)
    else:
        assets_dir = Path(assets_dir)

    generated_dir, manifest_path = _manifest_paths(assets_dir)
    model, quality = _DEFAULT_MODEL, _DEFAULT_QUALITY
    if settings is not None:
        model = settings.get("infographic.ai_full.model", _DEFAULT_MODEL)
        quality = settings.get("infographic.ai_full.quality", _DEFAULT_QUALITY)

    key = _cache_key(spec, theme, ratio, postflight_instruction)
    png_path = generated_dir / f"{key}.png"
    manifest = _load_manifest(manifest_path)

    if not regenerate and png_path.exists() and key in manifest:
        logger.info("cache HIT (%s) -- không gọi API", key)
        return png_path, ""

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        warning = (
            "CẢNH BÁO: thiếu OPENAI_API_KEY trong môi trường -- không sinh được "
            "ảnh ai_full. Xem docs/VPS_MIGRATION_BACKLOG.md mục C6."
        )
        logger.warning(warning)
        return None, warning

    prompt = build_ai_full_prompt(
        spec,
        theme=theme,
        ratio=ratio,
        postflight_instruction=postflight_instruction,
    )
    _check_prompt_banned_words(prompt)   # Phần B1 -- raise NGAY nếu lọt từ cấm, KHÔNG gọi API
    # v7 full-canvas: gọi API ở đúng tỷ lệ xuất bản và kích thước lớn hơn
    # final_size; lớp overlay chỉ downscale, không matting/crop.
    (w, h), _size_reason = _select_full_canvas_ai_size(ratio, settings=settings)
    size_str = f"{w}x{h}"

    try:
        png_bytes, usage = _call_openai_images_api(prompt, api_key=api_key, model=model, size=size_str, quality=quality)
    except AiFullError as e:
        warning = f"CẢNH BÁO: sinh ảnh ai_full thất bại ({e})."
        logger.warning(warning)
        return None, warning

    generated_dir.mkdir(parents=True, exist_ok=True)
    png_path.write_bytes(png_bytes)

    manifest[key] = {
        "topic": spec.get("title", ""),
        "theme": theme,
        "ratio": ratio,
        "size": size_str,
        "prompt": prompt,
        "prompt_version": _PROMPT_VERSION,
        "model": model,
        "quality": quality,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "usage": usage,   # token THẬT từ OpenAI (input/output/total_tokens) -- xem docstring _call_openai_images_api
        "cost_usd": None,  # CHƯA có bảng giá gpt-image-2 xác nhận -- đối chiếu dashboard OpenAI rồi gọi record_actual_cost()
        "file": f"generated/{key}.png",
    }
    _save_manifest(manifest_path, manifest)
    logger.info("cache MISS (%s) -- đã gọi API, ghi cache mới", key)
    return png_path, ""


def record_actual_cost(*, cache_key: str, cost_usd: float, assets_dir: str | Path, settings=None) -> None:
    """Ghi CHI PHÍ THẬT (đối chiếu dashboard OpenAI, KHÔNG phải ước tính) vào
    entry manifest đã có -- gọi SAU khi biết số thật, tách khỏi lúc sinh ảnh
    (response OpenAI Images API không trả cost trực tiếp)."""
    assets_dir = Path(assets_dir)
    _, manifest_path = _manifest_paths(assets_dir)
    manifest = _load_manifest(manifest_path)
    if cache_key in manifest:
        manifest[cache_key]["cost_usd"] = cost_usd
        _save_manifest(manifest_path, manifest)


def render_ai_full(
    spec: dict,
    *,
    theme: str | None = None,
    ratios: tuple[str, ...] = ("1:1", "4:5", "9:16"),
    regenerate: bool = False,
    assets_dir: str | Path | None = None,
    settings=None,
) -> tuple[dict[str, tuple[bytes | None, str]], dict[str, dict]]:
    """Điểm vào NÊN DÙNG cho mode "ai_full": cắt mật độ riêng từng tỷ lệ ->
    sinh full-canvas cache-first -> overlay brand/metadata tất định trực tiếp.
    Mỗi tỷ lệ gọi API riêng ở đúng size; không matting, crop hoặc khung con.

    2026-07-23 (ĐẢO HƯỚNG P0) -- BREAKING: trả (results, logs) 2 dict, KHÔNG
    còn 1 dict như bản cũ:
      results: {ratio: (png_bytes_đã_đóng_dấu | None, warning)} -- `warning`
        rỗng nếu thành công, khác rỗng nếu fallback (thiếu key/lỗi API) --
        CHỈ ratio đó thất bại, các ratio khác vẫn xử lý bình thường.
      logs: {ratio: log_dict} -- CHỈ có mặt cho ratio THÀNH CÔNG -- log_dict
        từ `stamp_brand` (A2 Bước 6) + thêm field `truncated` (Phần C, danh
        sách block đã cắt nếu có, rỗng nếu không cắt gì) -- ai_full.py KHÔNG
        tự ghi file, CALLER (vd render_production_assets.py) ghi JSON cạnh
        ảnh để Lead kiểm không cần mở ảnh."""
    from .brand_stamp import overlay_brand_full_canvas, precheck_logo_corner
    from .postflight import content_has_explicit_ranking, detect_ordinal_markers
    from ..config import load_brand

    theme, theme_id, _palette = load_theme_palette(
        theme,
        content_type=spec.get("content_type"),
    )
    layout_id = select_content_layout(compute_information_score(spec))
    brand = load_brand()
    # 2026-07-24 (quyết định Lead, SỬA VIỆC 2 -- "một nguồn sự thật"): BỎ HẲN
    # override render.infographic.disclaimer (settings.yaml) từng thêm 2026-
    # 07-22 -- 2 nguồn (brand.yaml + settings.yaml) đã LỆCH NHAU về câu chữ
    # (khác nhau đúng 1 dấu chấm cuối), rủi ro thật của việc có 2 chỗ giữ
    # cùng 1 chuỗi pháp lý. disclaimer giờ CHỈ đọc từ config/brand.yaml (đổi
    # disclaimer sau này CHỈ sửa brand.yaml, không đụng code) -- xem
    # config/brand.yaml::footer.disclaimer, config.load_brand().
    disclaimer = brand.get("footer", {}).get("disclaimer", "") if isinstance(brand.get("footer"), dict) else ""
    source = spec.get("source", "")

    results: dict[str, tuple[bytes | None, str]] = {}
    logs: dict[str, dict] = {}
    for ratio in ratios:
        # Phần C -- cắt mật độ TRƯỚC KHI sinh ảnh, RIÊNG cho từng tỷ lệ (sức
        # chứa layout khác nhau theo tỷ lệ, xem _DEFAULT_DENSITY_CAPS).
        capped_spec, truncated = apply_density_cap(spec, ratio=ratio, settings=settings)
        for t in truncated:
            msg = (f"[CẢNH BÁO] density cap tỷ lệ {ratio}: cắt khối '{t['block']}' -- "
                  f"giữ {t['kept']}, bỏ {t['dropped']} ({t['reason']}): {t['dropped_labels']}")
            print(msg, file=sys.stderr)   # C4 -- TUYỆT ĐỐI không cắt im lặng
            logger.warning(msg)

        png_path, warning = get_or_generate_raw_image(
            capped_spec, theme=theme, ratio=ratio, regenerate=regenerate, assets_dir=assets_dir, settings=settings
        )
        if png_path is None:
            results[ratio] = (None, warning or f"CẢNH BÁO: không sinh được ảnh ai_full tỷ lệ {ratio}.")
            continue
        raw_bytes = Path(png_path).read_bytes()
        ranking_allowed = content_has_explicit_ranking(capped_spec)
        ranking_scan = detect_ordinal_markers(Image.open(png_path).convert("RGB"))
        ranking_attempts = 1
        if ranking_scan["detected"] and not ranking_allowed:
            retry_instruction = (
                "Ảnh trước đã tự thêm marker 1/2/3 như bảng xếp hạng. Tuyệt đối "
                "không đánh số thứ tự, không dùng số trong vòng tròn và không "
                "gắn ordinal marker cho bất kỳ item nào; facts không có thứ hạng."
            )
            retry_path, retry_warning = get_or_generate_raw_image(
                capped_spec,
                theme=theme,
                ratio=ratio,
                regenerate=True,
                assets_dir=assets_dir,
                settings=settings,
                postflight_instruction=retry_instruction,
            )
            ranking_attempts = 2
            if retry_path is None:
                results[ratio] = (
                    None,
                    retry_warning
                    or "NEEDS_HUMAN: hậu kiểm ranking yêu cầu retry nhưng không sinh được ảnh.",
                )
                logs[ratio] = {
                    "postflight_status": "NEEDS_HUMAN",
                    "ranking_allowed": False,
                    "ranking_attempts": ranking_attempts,
                    "ranking_scan_attempt_1": ranking_scan,
                    "ranking_scan_attempt_2": None,
                }
                continue
            png_path = retry_path
            raw_bytes = Path(png_path).read_bytes()
            retry_scan = detect_ordinal_markers(
                Image.open(png_path).convert("RGB")
            )
            if retry_scan["detected"]:
                results[ratio] = (
                    None,
                    "NEEDS_HUMAN: ảnh vẫn tự thêm thứ tự/ranking sau 2 lần render; "
                    "không xuất ảnh.",
                )
                logs[ratio] = {
                    "postflight_status": "NEEDS_HUMAN",
                    "ranking_allowed": False,
                    "ranking_attempts": ranking_attempts,
                    "ranking_scan_attempt_1": ranking_scan,
                    "ranking_scan_attempt_2": retry_scan,
                }
                continue
            ranking_scan_attempt_1 = ranking_scan
            ranking_scan = retry_scan
        else:
            ranking_scan_attempt_1 = ranking_scan

        # TASK-013 Phần C (2026-08-07, ADR-002) -- pre-check góc logo TRƯỚC
        # khi đóng dấu, dùng ĐÚNG khuôn retry ranking ở trên
        # (detect_ordinal_markers -> get_or_generate_raw_image với
        # postflight_instruction). Root cause đã xác minh: brand_stamp.py cũ
        # dán logo đè lên chữ khi CẢ 2 góc bận thay vì sinh lại ảnh (ảnh BSR
        # 05/08, logo đè thẳng lên chữ "BSR" -- xem TASK-013 contract). Tối
        # đa 1 lần sinh lại/ảnh; hết lượt vẫn bận -> NEEDS_HUMAN, KHÔNG dán
        # bừa (brand_stamp.overlay_brand_full_canvas() tự bỏ qua logo trong
        # trường hợp đó, nhưng ta chặn TỪ ĐÂY để không xuất ảnh thiếu logo
        # ra ngoài mà không ai biết).
        logo_precheck = precheck_logo_corner(raw_bytes, ratio=ratio, theme=theme, settings=settings)
        logo_attempts = 1
        if logo_precheck["all_occupied"]:
            logo_retry_instruction = (
                "Ảnh trước đặt chữ hoặc chi tiết chính chạm cả góc trên-phải "
                "và góc trên-trái, không còn chỗ trống cho logo. Bố cục PHẢI "
                "đặt khối tiêu đề/chữ bên TRÁI, hình minh hoạ chủ thể bên "
                "PHẢI, và giữ góc trên-phải HOÀN TOÀN không chữ/số/chi tiết "
                "chính để lớp deterministic dán logo."
            )
            retry_path, retry_warning = get_or_generate_raw_image(
                capped_spec,
                theme=theme,
                ratio=ratio,
                regenerate=True,
                assets_dir=assets_dir,
                settings=settings,
                postflight_instruction=logo_retry_instruction,
            )
            logo_attempts = 2
            if retry_path is None:
                results[ratio] = (
                    None,
                    retry_warning
                    or "NEEDS_HUMAN: hậu kiểm góc logo yêu cầu retry nhưng không sinh được ảnh.",
                )
                logs[ratio] = {
                    "postflight_status": "NEEDS_HUMAN",
                    "logo_attempts": logo_attempts,
                    "logo_precheck_attempt_1": logo_precheck,
                    "logo_precheck_attempt_2": None,
                }
                continue
            png_path = retry_path
            raw_bytes = Path(png_path).read_bytes()
            logo_precheck_retry = precheck_logo_corner(raw_bytes, ratio=ratio, settings=settings)
            if logo_precheck_retry["all_occupied"]:
                results[ratio] = (
                    None,
                    "NEEDS_HUMAN: ảnh vẫn không có góc trống cho logo sau 2 lần "
                    "render; không xuất ảnh.",
                )
                logs[ratio] = {
                    "postflight_status": "NEEDS_HUMAN",
                    "logo_attempts": logo_attempts,
                    "logo_precheck_attempt_1": logo_precheck,
                    "logo_precheck_attempt_2": logo_precheck_retry,
                }
                continue
            logo_precheck = logo_precheck_retry
        try:
            stamped, stamp_log = overlay_brand_full_canvas(
                raw_bytes,
                ratio=ratio,
                theme=theme,
                source=source,
                disclaimer=disclaimer,
                settings=settings,
            )
        except ValueError as exc:
            msg = str(exc)
            if "METADATA_GUARDRAIL_FAIL" in msg:
                results[ratio] = (None, msg)
                logs[ratio] = {
                    "postflight_status": "FAIL",
                    "metadata_guardrail": "FAIL",
                    "ranking_allowed": ranking_allowed,
                    "ranking_attempts": ranking_attempts,
                    "ranking_scan_attempt_1": ranking_scan_attempt_1,
                    "ranking_scan_final": ranking_scan,
                    "logo_attempts": logo_attempts,
                    "logo_precheck_final": logo_precheck,
                }
                continue
            if "LOGO_GUARDRAIL_FAIL" in msg:
                # TASK-017 (2026-08-07) -- phòng thủ thêm lớp: precheck ở
                # trên đã lọc trước khi tới đây nên nhánh này HIẾM khi chạy,
                # nhưng nếu 2 lượt quét (precheck vs overlay_brand_full_
                # canvas) lệch nhau vì lý do bất kỳ, KHÔNG được để lọt ảnh
                # thiếu logo ra ngoài -- coi như hết lượt retry, NEEDS_HUMAN.
                results[ratio] = (None, "NEEDS_HUMAN: " + msg)
                logs[ratio] = {
                    "postflight_status": "NEEDS_HUMAN",
                    "ranking_allowed": ranking_allowed,
                    "ranking_attempts": ranking_attempts,
                    "ranking_scan_attempt_1": ranking_scan_attempt_1,
                    "ranking_scan_final": ranking_scan,
                    "logo_attempts": logo_attempts,
                    "logo_precheck_final": logo_precheck,
                }
                continue
            raise
        stamp_log["truncated"] = truncated   # C4 -- cảnh báo cắt mật độ CẠNH ảnh, KHÔNG lên Sheet
        stamp_log["theme"] = theme
        stamp_log["theme_id"] = theme_id
        stamp_log["layout_id"] = layout_id
        stamp_log["postflight_status"] = "PASS"
        stamp_log["ranking_allowed"] = ranking_allowed
        stamp_log["ranking_attempts"] = ranking_attempts
        stamp_log["ranking_scan_attempt_1"] = ranking_scan_attempt_1
        stamp_log["ranking_scan_final"] = ranking_scan
        stamp_log["logo_attempts"] = logo_attempts
        stamp_log["logo_precheck_final"] = logo_precheck
        _, omitted_empty_blocks = _spec_for_image_prompt(capped_spec)
        stamp_log["prompt_omitted_empty_blocks"] = omitted_empty_blocks
        results[ratio] = (stamped, "")
        logs[ratio] = stamp_log
    return results, logs
