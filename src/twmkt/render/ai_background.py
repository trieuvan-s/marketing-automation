"""Lớp AI (mềm) của renderer Infographic Hybrid — sinh MỘT LẦN, cache, dùng
lại. TUYỆT ĐỐI KHÔNG sinh chữ/số/layout/bản đồ/icon (những thứ đó là lớp CODE
tất định, xem `infographic.py`) — module này CHỈ trả về 1 ảnh nền (PNG bytes)
làm không khí thị giác, hoặc `None` (kèm cảnh báo) khi không sinh được.

PHÂN TẦNG (nguyên tắc cốt lõi Hybrid — xem docs/VPS_MIGRATION_BACKLOG.md C8):
  Lớp AI (module này):   nền/minh hoạ, KHÔNG chữ/số.
  Lớp code (infographic.py): MỌI chữ, MỌI số, layout, bản đồ, icon.
Vi phạm phân tầng (để AI vẽ chữ/số/bản đồ) là BƯỚC LÙI về guardrail chống bịa
số — số nằm trong ảnh raster thì KHÔNG kiểm được nữa.

TẤT ĐỊNH qua CACHE (không phải qua chính API — DALL-E/gpt-image-1 vốn KHÔNG
tất định, mỗi lần gọi ra ảnh khác dù cùng prompt): `get_or_generate_background()`
tính `cache_key = sha256(topic + prompt + template_version)`, cache HIT ->
đọc lại PNG cũ, KHÔNG gọi API lần nào -> 2 lần render cùng input ra CÙNG
1 file ảnh (so được bằng hash). Cache MISS hoặc `regenerate=True` mới gọi API.

FALLBACK (B5, bắt buộc): thiếu OPENAI_API_KEY / lỗi mạng / hết quota /
timeout -> trả `(None, "cảnh báo rõ ràng")`, KHÔNG raise, KHÔNG crash. Caller
(`infographic.py`) tự quyết định render pure_html khi nhận `None`.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger("twmkt.render.ai_background")

# Model + kích thước ảnh (portrait, gần khớp tỉ lệ canvas 1080x1350 = 4:5) —
# CONFIG được, không hardcode cứng trong code gọi (đọc qua get_or_generate_
# background(settings=...)) — giá trị ở đây chỉ là mặc định lùi-mượt-cuối.
_DEFAULT_MODEL = "gpt-image-1"
_DEFAULT_SIZE = "1024x1536"
_DEFAULT_QUALITY = "low"          # kiểm soát chi phí — "low"/"medium"/"high" (gpt-image-1)
_API_URL = "https://api.openai.com/v1/images/generations"
_TIMEOUT_S = 60

# Ước tính chi phí/ảnh (USD) theo quality "low" của gpt-image-1 tại thời điểm
# viết — GHI RÕ LÀ ƯỚC TÍNH (xem manifest.json "cost_estimate_usd"), KHÔNG
# phải số chính xác từ hoá đơn OpenAI thật — đối chiếu lại dashboard billing
# OpenAI định kỳ, sửa hằng số này nếu lệch nhiều.
_ESTIMATED_COST_USD = 0.02


class AiBackgroundError(Exception):
    """Lỗi gọi API/parse response — CHỈ dùng NỘI BỘ module này, KHÔNG lộ ra
    ngoài get_or_generate_background() (hàm đó luôn trả (None, warning),
    không bao giờ raise ra caller — xem B5)."""


def _cache_key(topic: str, prompt: str, template_version: str) -> str:
    raw = f"{topic} {prompt} {template_version}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def build_background_prompt(topic: str, *, brand_colors: dict | None = None) -> str:
    """Prompt gửi OpenAI — CHỈ nhận CHỦ ĐỀ CHÍNH (topic, vd tiêu đề/hook bài),
    KHÔNG nhận facts[]/con số cụ thể (B2: "lấy CHỦ ĐỀ CHÍNH, không phải từng
    con số làm đầu vào") — tránh AI vẽ minh hoạ sai lệch số liệu thật (dù AI
    không VẼ số, việc đưa số vào prompt vẫn có thể khiến bố cục ảnh gợi ý sai
    quy mô/tỷ lệ một cách trực quan, gây hiểu lầm).

    Cấm chữ/số/watermark/nhãn/biểu đồ-có-trục — TUYỆT ĐỐI (B2, lý do kỹ thuật:
    guardrail không kiểm được số trong ảnh raster; tiếng Việt có dấu AI vẽ dễ
    sai chính tả). Tông màu khớp brand FVA Capital: nền tối, xanh dương/xanh
    ngọc/vàng cam (không giới hạn đúng 2 màu brand.yaml — dải màu rộng hơn để
    có biến thiên thị giác, vẫn trong tinh thần "nền tối, tài chính, cao cấp")."""
    colors = brand_colors or {}
    color_hint = colors.get("prompt_hint") or (
        "dark navy and deep blue background with subtle teal/cyan and warm "
        "amber/orange gradient accents"
    )
    return (
        f"Abstract, atmospheric background illustration evoking the theme: {topic.strip()}. "
        f"{color_hint}. Moody, premium financial/business aesthetic, soft gradients, "
        "subtle bokeh or particle texture, cinematic lighting, high-end editorial style. "
        "Absolutely no text, no numbers, no letters, no watermark, no logos, no labels, "
        "no charts, no graphs, no axis labels, no UI elements, no infographics, no icons. "
        "Pure abstract atmospheric visual only — no readable characters of any kind, "
        "no Vietnamese or English words anywhere in the image."
    )


def _manifest_paths(assets_dir: Path) -> tuple[Path, Path]:
    generated_dir = assets_dir / "generated"
    manifest_path = assets_dir / "manifest.json"
    return generated_dir, manifest_path


def _load_manifest(manifest_path: Path) -> dict:
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("assets/manifest.json lỗi parse -- coi như rỗng, sẽ ghi đè entry mới")
        return {}


def _save_manifest(manifest_path: Path, data: dict) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _call_openai_images_api(
    prompt: str, *, api_key: str, model: str, size: str, quality: str
) -> bytes:
    """Gọi OpenAI Images API thật -> trả PNG bytes. Raise `AiBackgroundError`
    cho MỌI lỗi (timeout/network/quota/HTTP lỗi/response thiếu ảnh) -- KHÔNG
    bao giờ để lộ traceback httpx thô ra ngoài module này."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "prompt": prompt, "size": size, "quality": quality, "n": 1}
    try:
        resp = httpx.post(_API_URL, headers=headers, json=payload, timeout=_TIMEOUT_S)
    except httpx.TimeoutException as e:
        raise AiBackgroundError(f"timeout sau {_TIMEOUT_S}s gọi OpenAI Images API") from e
    except httpx.HTTPError as e:
        raise AiBackgroundError(f"lỗi mạng gọi OpenAI Images API: {e}") from e

    if resp.status_code != 200:
        # KHÔNG log full response (có thể lẫn thông tin key/org trong header lỗi) --
        # chỉ log status + đoạn text ngắn.
        raise AiBackgroundError(
            f"OpenAI Images API trả lỗi HTTP {resp.status_code}: {resp.text[:200]}"
        )

    try:
        data = resp.json()
        item = data["data"][0]
    except Exception as e:
        raise AiBackgroundError(f"response OpenAI không đúng shape mong đợi: {e}") from e

    if "b64_json" in item and item["b64_json"]:
        import base64
        return base64.b64decode(item["b64_json"])

    if "url" in item and item["url"]:
        try:
            img_resp = httpx.get(item["url"], timeout=_TIMEOUT_S)
            img_resp.raise_for_status()
            return img_resp.content
        except httpx.HTTPError as e:
            raise AiBackgroundError(f"tải ảnh từ URL OpenAI trả về thất bại: {e}") from e

    raise AiBackgroundError("response OpenAI không có 'b64_json' lẫn 'url' -- không có ảnh để dùng")


def get_or_generate_background(
    topic: str,
    *,
    template_version: str = "v1",
    regenerate: bool = False,
    assets_dir: str | Path | None = None,
    settings=None,
) -> tuple[Path | None, str]:
    """Điểm vào DUY NHẤT của lớp AI. Trả `(đường_dẫn_PNG, cảnh_báo)`:
      - `render_mode == "pure_html"` (config, xem `infographic.py`) -> hàm
        này thậm chí KHÔNG được gọi bởi caller đúng thiết kế, nhưng nếu lỡ
        gọi vẫn trả `(None, "")` an toàn, KHÔNG gọi API.
      - Cache HIT -> `(path, "")`, KHÔNG gọi API (B3 bắt buộc).
      - Cache MISS, có key, API thành công -> `(path, "")`, đã ghi cache +
        manifest.
      - Thiếu key / API lỗi / timeout / quota -> `(None, "cảnh báo rõ")`,
        KHÔNG raise (B5) -- caller tự fallback render pure_html.

    `assets_dir=None` (mặc định) -> resolve qua `config.data_path()` (NGOÀI
    repo, dưới `storage.data_root`, key `infographic.ai_background.cache_dir`)
    -- dữ liệu SINH RA (kể cả cache ảnh AI) KHÔNG BAO GIỜ nằm trong repo, xem
    docs/VPS_MIGRATION_BACKLOG.md mục C6. Test/gọi cô lập truyền `assets_dir`
    tường minh (vd `tmp_path`) để GHI ĐÈ, không đụng data_root thật.
    """
    if assets_dir is None:
        from ..config import data_path

        cache_dir_name = (
            settings.get("infographic.ai_background.cache_dir", "assets")
            if settings is not None
            else "assets"
        )
        assets_dir = data_path(cache_dir_name, settings=settings)
    else:
        assets_dir = Path(assets_dir)
    generated_dir, manifest_path = _manifest_paths(assets_dir)

    brand_colors = {}
    model, size, quality = _DEFAULT_MODEL, _DEFAULT_SIZE, _DEFAULT_QUALITY
    if settings is not None:
        model = settings.get("infographic.ai_background.model", _DEFAULT_MODEL)
        size = settings.get("infographic.ai_background.size", _DEFAULT_SIZE)
        quality = settings.get("infographic.ai_background.quality", _DEFAULT_QUALITY)

    prompt = build_background_prompt(topic, brand_colors=brand_colors)
    key = _cache_key(topic, prompt, template_version)
    png_path = generated_dir / f"{key}.png"

    manifest = _load_manifest(manifest_path)

    if not regenerate and png_path.exists() and key in manifest:
        logger.info("cache HIT (%s) -- không gọi API", key)
        return png_path, ""

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        warning = (
            "CẢNH BÁO: thiếu OPENAI_API_KEY trong môi trường -- fallback pure_html "
            "(không sinh nền AI). Xem assets/README.md để cấu hình."
        )
        logger.warning(warning)
        return None, warning

    try:
        png_bytes = _call_openai_images_api(
            prompt, api_key=api_key, model=model, size=size, quality=quality
        )
    except AiBackgroundError as e:
        warning = f"CẢNH BÁO: sinh nền AI thất bại ({e}) -- fallback pure_html."
        logger.warning(warning)
        return None, warning

    generated_dir.mkdir(parents=True, exist_ok=True)
    png_path.write_bytes(png_bytes)

    manifest[key] = {
        "topic": topic,
        "prompt": prompt,
        "template_version": template_version,
        "model": model,
        "size": size,
        "quality": quality,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cost_estimate_usd": _ESTIMATED_COST_USD,
        "file": f"generated/{key}.png",
    }
    _save_manifest(manifest_path, manifest)
    logger.info("cache MISS (%s) -- đã gọi API, ghi cache mới", key)
    return png_path, ""
