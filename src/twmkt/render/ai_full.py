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
(cấm vẽ bản đồ/logo, photorealistic, chừa dải trống) vì (a) tự nó VẪN vẽ bản
đồ Việt Nam sai/thiếu đảo khi thấy field `related` — bằng chứng ảnh thật.

⚠️ BẢN ĐỒ VIỆT NAM: KHÔNG asset chuẩn nào tồn tại trong repo/content-rules/
aigen-pipeline/data_root tại thời điểm viết (2026-07-21, đã tìm kỹ, xem báo
cáo DỪNG KHI #1) — module này do đó LUÔN cấm AI vẽ bản đồ/sơ đồ địa lý VN
TUYỆT ĐỐI (không có nhánh "chừa chỗ dán bản đồ thật" vì chưa có gì để dán).
Khi Lead cấp asset chuẩn, bổ sung `_MAP_ASSET_PATH` + logic dán riêng.

Theme-rules (Bước 2): copy nguyên văn từ content-rules/ (sibling, KHÔNG theo
git) vào `prompts/themes/FVA_Infographic_Theme_{Dark,Light}.md` — MỘT NGUỒN,
không sửa nội dung khi đọc. `information_score`/layout selector implement lại
Ở CODE (tất định) theo đúng công thức trong theme file, KHÔNG để LLM tự đoán
layout — cùng triết lý "AI hiểu ở Brief, CODE phán ở Guardrail" xuyên suốt dự
án này.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger("twmkt.render.ai_full")

_DEFAULT_MODEL = "gpt-image-2"
_DEFAULT_QUALITY = "medium"
_API_URL = "https://api.openai.com/v1/images/generations"
_TIMEOUT_S = 120
_PROMPT_VERSION = "v3"  # v3 (2026-07-22): cấm khoảng trống lớn giữa dải đỉnh và tiêu đề, bắt buộc lấp đều bố cục -- lỗi THẬT: AI để trống ~15-20% chiều cao giữa logo/dải đỉnh và headline, dồn nội dung xuống đáy, gây chồng lấn dải đáy. v2 (2026-07-21): cấm AI vẽ "Nguồn:"/source text -- v1 để lọt AI tự vẽ trùng dòng nguồn với brand_stamp.py, xem báo cáo

# Bước 4.3 — sinh ĐÚNG size cho từng tỷ lệ (KHÔNG crop sau). API gpt-image-2
# chấp nhận size TUỲ Ý miễn chia hết cho 16 (xác nhận thật 2026-07-21, xem lỗi
# "Width and height must both be divisible by 16" khi thử size không hợp lệ)
# -- KHÔNG phải enum cố định như gpt-image-1. 3 size dưới đây là tỷ lệ CHÍNH
# XÁC (864/1536 = 9/16 = 0.5625 y hệt), không xấp xỉ.
RATIO_SIZES = {
    "1:1": (1024, 1024),
    "4:5": (1024, 1280),
    "9:16": (864, 1536),
}

# Bước 4.1 — dải trống bắt buộc AI KHÔNG được đặt nội dung vào, để lớp code
# đóng dấu brand lên trên không đè lên minh hoạ/chữ do AI vẽ.
_TOP_SAFE_PCT = 0.10
_BOTTOM_SAFE_PCT = 0.08

_THEME_FILES = {
    "dark": "FVA_Infographic_Theme_Dark.md",
    "light": "FVA_Infographic_Theme_Light.md",
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
    metric_count = len(spec.get("market") or [])
    highlight_count = len(spec.get("highlights") or [])
    return hero_count * 2 + metric_count + highlight_count


def select_layout(score: int, *, theme: str = "dark") -> str:
    """Layout selector THEO ĐÚNG bảng ngưỡng Theme-rules §7. Khi tài liệu ghi
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


def _theme_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "prompts" / "themes"


def build_ai_full_prompt(spec: dict, *, theme: str = "dark", ratio: str = "4:5") -> str:
    """BƯỚC 1 kết luận: JSON THÔ thắng -- KHÔNG bọc qua LLM diễn giải lại nội
    dung. Prompt = JSON spec (serialize thẳng, giữ NGUYÊN mọi field) + ĐÚNG
    các chỉ dẫn AN TOÀN bắt buộc (Bước 3/4, không phải "thêm chỉ dẫn bố cục" --
    đó là điều (a) đã thắng (b) khi so sánh). KHÔNG thêm mô tả bố cục/diễn giải
    nội dung nào khác ngoài rào an toàn."""
    theme = theme if theme in _THEME_COLORS else "dark"
    colors = _THEME_COLORS[theme]
    score = compute_information_score(spec)
    layout_id = select_layout(score, theme=theme)

    spec_json_str = json.dumps(spec, ensure_ascii=False, indent=2)

    safety_block = f"""
YÊU CẦU BẮT BUỘC (không thoả hiệp):
1. KHÔNG vẽ bản đồ Việt Nam, sơ đồ địa lý, đường biên giới, hay bất kỳ hình
   dạng lãnh thổ/quốc gia nào -- kể cả khi dữ liệu trên nhắc tên tỉnh/thành/
   địa danh. Nếu cần thể hiện địa danh, chỉ dùng TÊN CHỮ, không vẽ hình bản đồ.
2. KHÔNG tự vẽ logo, biểu tượng thương hiệu, chữ "FVA Capital"/"FVA CAPITAL",
   dòng "Nguồn:"/"Source:" hay bất kỳ dạng ghi chú nguồn/miễn trừ trách nhiệm
   nào (kể cả field "source" trong JSON dưới đây) -- các phần này do lớp khác
   đóng dấu sau, KHÔNG phải việc của bước sinh ảnh này. Chỉ dùng field
   "source" để BIẾT bối cảnh, KHÔNG vẽ nó thành chữ trên ảnh.
3. Mọi hình minh hoạ (tàu, cảng, máy bay, nhà máy...) PHẢI là photorealistic
   professional photography -- ảnh chụp thật hoặc quang thực chuyên nghiệp.
   TUYỆT ĐỐI KHÔNG phong cách illustration, cartoon, vector art, hay 3D-render.
4. CHỪA DẢI TRỐNG hoàn toàn, không đặt bất kỳ nội dung/chữ/hình nào vào đó:
   - Đỉnh ảnh: {int(_TOP_SAFE_PCT * 100)}% chiều cao tính từ mép trên.
   - Đáy ảnh: {int(_BOTTOM_SAFE_PCT * 100)}% chiều cao tính từ mép dưới.
   NGAY SAU dải trống đỉnh ({int(_TOP_SAFE_PCT * 100)}%), tiêu đề (title)
   PHẢI bắt đầu GẦN NHƯ NGAY LẬP TỨC -- TUYỆT ĐỐI KHÔNG chừa thêm khoảng
   trống trang trí nào giữa dải đỉnh và tiêu đề. Đây là lỗi THẬT đã xảy ra:
   AI để trống thêm ~15-20% chiều cao ảnh giữa logo/dải đỉnh và tiêu đề, đẩy
   dồn toàn bộ nội dung còn lại xuống sát đáy, gây chồng lấn với dải đáy.
5. BỐ CỤC PHẢI LẤP ĐẦY ĐỀU khoảng không gian giữa 2 dải trống (đỉnh/đáy) --
   phân bổ tiêu đề, thẻ số liệu, điểm nổi bật, hình minh hoạ trải ĐỀU từ
   ngay dưới dải đỉnh tới ngay trên dải đáy, KHÔNG dồn cụm nội dung về một
   phía rồi để trống mảng lớn ở phía còn lại. KHÔNG có khoảng trắng/khoảng
   tối trang trí nào rộng hơn khoảng cách bình thường giữa 2 khối nội dung
   liền kề.
6. Giữ NGUYÊN VĂN, chính xác tuyệt đối mọi số liệu và dấu tiếng Việt trong
   JSON dưới đây -- không dịch, không làm tròn, không bịa thêm số.

Theme: FVA Capital VN -- {"Dark Editorial" if theme == "dark" else "Light Research"}.
Nền {colors["background"]}, chữ chính {colors["text_primary"]}, chữ phụ
{colors["text_secondary"]}, Gold {colors["gold"]} CHỈ nhấn priority.primary
(tối đa 1-2 mục), không phủ rộng. Tỷ lệ ảnh: {ratio}.
Mức độ thông tin: {score} điểm -- bố cục tham chiếu: {layout_id}.

Dữ liệu Infographic (JSON, giữ nguyên mọi trường):
{spec_json_str}
""".strip()
    return safety_block


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


def _cache_key(spec: dict, theme: str, ratio: str) -> str:
    raw = json.dumps(spec, ensure_ascii=False, sort_keys=True) + "|" + theme + "|" + ratio + "|" + _PROMPT_VERSION
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
    theme: str = "dark",
    ratio: str = "4:5",
    regenerate: bool = False,
    assets_dir: str | Path | None = None,
    settings=None,
) -> tuple[Path | None, str]:
    """Điểm vào DUY NHẤT gọi API thật -- cache-first (B3 CÙNG NẾP ai_background.py).
    Trả (đường_dẫn_PNG_THÔ_chưa_đóng_dấu_brand, cảnh_báo). Cache key theo
    hash(spec + theme + ratio + prompt_version) -- ĐỔI 1 field spec (kể cả
    thứ tự key khác nhau không ảnh hưởng, dùng sort_keys) -> hash khác -> cache
    MISS, gọi API lại. KHÔNG raise ra ngoài -- lỗi/thiếu key -> (None, cảnh báo)."""
    if ratio not in RATIO_SIZES:
        return None, f"CẢNH BÁO: tỷ lệ '{ratio}' không hỗ trợ (chỉ {list(RATIO_SIZES)})."

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

    key = _cache_key(spec, theme, ratio)
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

    prompt = build_ai_full_prompt(spec, theme=theme, ratio=ratio)
    w, h = RATIO_SIZES[ratio]
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
    theme: str = "dark",
    ratios: tuple[str, ...] = ("1:1", "4:5", "9:16"),
    regenerate: bool = False,
    assets_dir: str | Path | None = None,
    settings=None,
) -> dict[str, tuple[bytes | None, str]]:
    """Điểm vào NÊN DÙNG cho mode "ai_full" -- sinh (cache-first) + đóng dấu
    brand cho MỖI tỷ lệ trong `ratios`, KHÔNG crop chéo tỷ lệ (Bước 4.3: mỗi
    tỷ lệ gọi API RIÊNG, đúng size, xem RATIO_SIZES). Trả dict
    {ratio: (png_bytes_đã_đóng_dấu | None, warning)} -- `warning` rỗng nếu
    thành công, khác rỗng nếu fallback (thiếu key/lỗi API) -- CHỈ ratio đó
    thất bại, các ratio khác trong cùng lệnh gọi vẫn xử lý bình thường (không
    dừng cả loạt vì 1 tỷ lệ lỗi)."""
    from .brand_stamp import stamp_brand
    from ..config import load_brand

    brand = load_brand()
    wordmark = brand.get("wordmark", "FVA CAPITAL")
    brand_disclaimer = brand.get("footer", {}).get("disclaimer", "") if isinstance(brand.get("footer"), dict) else ""
    # CÙNG NẾP render/infographic.py::brand_kit_from_settings() -- ghi đè
    # RIÊNG cho infographic (không đụng brand.yaml dùng chung article/video)
    # qua render.infographic.disclaimer. Yêu cầu Lead 2026-07-22: đổi văn bản
    # disclaimer CHỈ cho infographic, KHÔNG đổi brand.yaml toàn cục.
    disclaimer = settings.get("render.infographic.disclaimer", brand_disclaimer) if settings is not None else brand_disclaimer
    source = spec.get("source", "")

    results: dict[str, tuple[bytes | None, str]] = {}
    for ratio in ratios:
        png_path, warning = get_or_generate_raw_image(
            spec, theme=theme, ratio=ratio, regenerate=regenerate, assets_dir=assets_dir, settings=settings
        )
        if png_path is None:
            results[ratio] = (None, warning or f"CẢNH BÁO: không sinh được ảnh ai_full tỷ lệ {ratio}.")
            continue
        raw_bytes = Path(png_path).read_bytes()
        stamped = stamp_brand(raw_bytes, theme=theme, wordmark=wordmark, source=source, disclaimer=disclaimer)
        results[ratio] = (stamped, "")
    return results
