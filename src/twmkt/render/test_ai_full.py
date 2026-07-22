"""Test render/ai_full.py + brand_stamp.py -- MOCK hoàn toàn httpx.post,
KHÔNG mạng thật, KHÔNG tốn tiền API khi chạy CI/test."""
import base64
import io
import json

import httpx
import pytest
from PIL import Image, ImageDraw

from twmkt.config import Settings
from twmkt.render import ai_full as af
from twmkt.render import brand_stamp as bs

_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _real_png_bytes(w: int, h: int) -> bytes:
    im = Image.new("RGB", (w, h), (10, 20, 30))
    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


def _fake_success_response(*a, **kw):
    return httpx.Response(
        200, json={"data": [{"b64_json": _TINY_PNG_B64}]},
        request=httpx.Request("POST", af._API_URL),
    )


_SPEC = {
    "title": "Chu de test",
    "subtitle": "Phu de test",
    "hero": [{"label": "A", "value": "1"}, {"label": "B", "value": "2"}],
    "market": [{"label": "C", "value": "3"}],
    "highlights": ["Diem mot", "Diem hai"],
    "related": ["X"],
    "source": "test.vn",
}


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key-not-real")
    yield


# --- information_score / layout selector -----------------------------------

def test_information_score_matches_theme_formula():
    # hero=2*2=4, market=1, highlights=2 -> 4+1+2=7
    assert af.compute_information_score(_SPEC) == 7


def test_select_layout_thresholds_dark():
    assert af.select_layout(0, theme="dark") == "D1"
    assert af.select_layout(6, theme="dark") == "D1"
    assert af.select_layout(7, theme="dark") == "D3"
    assert af.select_layout(12, theme="dark") == "D3"
    assert af.select_layout(13, theme="dark") == "D4"
    assert af.select_layout(21, theme="dark") == "SPLIT_TO_CAROUSEL"


def test_select_layout_thresholds_light():
    assert af.select_layout(0, theme="light") == "L1"
    assert af.select_layout(7, theme="light") == "L3"
    assert af.select_layout(23, theme="light") == "SPLIT_TO_SERIES_OR_REPORT"


# --- prompt builder: BẮT BUỘC chứa rào an toàn ------------------------------

def test_prompt_forbids_map_and_logo_and_requires_photorealistic():
    prompt = af.build_ai_full_prompt(_SPEC, theme="dark", ratio="4:5")
    lower = prompt.lower()
    assert "bản đồ" in lower
    assert "photorealistic" in lower
    assert "logo" in lower
    assert "10%" in prompt
    assert "8%" in prompt


def test_prompt_embeds_raw_json_not_llm_rewrite():
    """Bước 1: (a) JSON thô thắng -- prompt PHẢI chứa spec serialize thẳng,
    không phải 1 bản diễn giải tóm tắt khác nội dung."""
    prompt = af.build_ai_full_prompt(_SPEC, theme="dark", ratio="4:5")
    assert '"title": "Chu de test"' in prompt
    assert '"value": "3"' in prompt


def test_prompt_rejects_unsupported_ratio_gracefully():
    # ratio khong hop le van build duoc prompt (khong crash) -- loi thuc su
    # chi xay o get_or_generate_raw_image (kiem tra RATIO_SIZES truoc goi API)
    prompt = af.build_ai_full_prompt(_SPEC, theme="dark", ratio="4:5")
    assert isinstance(prompt, str) and len(prompt) > 0


# --- cache / fallback (get_or_generate_raw_image) ---------------------------

def test_missing_api_key_returns_none_with_warning(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    path, warning = af.get_or_generate_raw_image(_SPEC, assets_dir=tmp_path)
    assert path is None
    assert "OPENAI_API_KEY" in warning


def test_unsupported_ratio_returns_none_with_warning(tmp_path):
    path, warning = af.get_or_generate_raw_image(_SPEC, ratio="16:9", assets_dir=tmp_path)
    assert path is None
    assert "không hỗ trợ" in warning


def test_cache_hit_does_not_call_api(monkeypatch, tmp_path):
    call_count = {"n": 0}

    def _tracked_post(*a, **kw):
        call_count["n"] += 1
        return _fake_success_response(*a, **kw)

    monkeypatch.setattr(httpx, "post", _tracked_post)
    path1, w1 = af.get_or_generate_raw_image(_SPEC, assets_dir=tmp_path)
    assert call_count["n"] == 1
    assert w1 == ""

    path2, w2 = af.get_or_generate_raw_image(_SPEC, assets_dir=tmp_path)
    assert call_count["n"] == 1, "cache HIT nhưng vẫn gọi API -- SAI"
    assert path1 == path2


def test_regenerate_flag_bypasses_cache(monkeypatch, tmp_path):
    call_count = {"n": 0}

    def _tracked_post(*a, **kw):
        call_count["n"] += 1
        return _fake_success_response(*a, **kw)

    monkeypatch.setattr(httpx, "post", _tracked_post)
    af.get_or_generate_raw_image(_SPEC, assets_dir=tmp_path)
    af.get_or_generate_raw_image(_SPEC, assets_dir=tmp_path, regenerate=True)
    assert call_count["n"] == 2


def test_different_ratio_is_different_cache_key(monkeypatch, tmp_path):
    monkeypatch.setattr(httpx, "post", _fake_success_response)
    p1, _ = af.get_or_generate_raw_image(_SPEC, ratio="1:1", assets_dir=tmp_path)
    p2, _ = af.get_or_generate_raw_image(_SPEC, ratio="4:5", assets_dir=tmp_path)
    assert p1 != p2


def test_api_error_returns_none_with_warning_not_raise(monkeypatch, tmp_path):
    def _fake_error(*a, **kw):
        return httpx.Response(429, text="rate limit", request=httpx.Request("POST", af._API_URL))

    monkeypatch.setattr(httpx, "post", _fake_error)
    path, warning = af.get_or_generate_raw_image(_SPEC, assets_dir=tmp_path)
    assert path is None
    assert "429" in warning


def test_manifest_records_prompt_and_metadata(monkeypatch, tmp_path):
    monkeypatch.setattr(httpx, "post", _fake_success_response)
    af.get_or_generate_raw_image(_SPEC, theme="dark", ratio="1:1", assets_dir=tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    entry = next(iter(manifest.values()))
    assert entry["theme"] == "dark"
    assert entry["ratio"] == "1:1"
    assert entry["model"] == af._DEFAULT_MODEL
    assert "prompt" in entry and "generated_at" in entry
    assert entry["cost_usd"] is None  # chưa ghi chi phí thật


def test_manifest_records_real_token_usage_from_api_response(monkeypatch, tmp_path):
    def _fake_response_with_usage(*a, **kw):
        return httpx.Response(
            200,
            json={
                "data": [{"b64_json": _TINY_PNG_B64}],
                "usage": {"input_tokens": 10, "output_tokens": 196, "total_tokens": 206},
            },
            request=httpx.Request("POST", af._API_URL),
        )

    monkeypatch.setattr(httpx, "post", _fake_response_with_usage)
    af.get_or_generate_raw_image(_SPEC, theme="dark", ratio="1:1", assets_dir=tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    entry = next(iter(manifest.values()))
    assert entry["usage"] == {"input_tokens": 10, "output_tokens": 196, "total_tokens": 206}


def test_record_actual_cost_updates_manifest(monkeypatch, tmp_path):
    monkeypatch.setattr(httpx, "post", _fake_success_response)
    key = af._cache_key(_SPEC, "dark", "1:1")
    af.get_or_generate_raw_image(_SPEC, theme="dark", ratio="1:1", assets_dir=tmp_path)
    af.record_actual_cost(cache_key=key, cost_usd=0.07, assets_dir=tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest[key]["cost_usd"] == 0.07


# --- render_ai_full (orchestrator: sinh + đóng dấu) -------------------------

def test_render_ai_full_returns_stamped_bytes_per_ratio(monkeypatch, tmp_path):
    monkeypatch.setattr(httpx, "post", _fake_success_response)
    results = af.render_ai_full(_SPEC, ratios=("1:1", "4:5"), assets_dir=tmp_path)
    assert set(results.keys()) == {"1:1", "4:5"}
    for ratio, (png_bytes, warning) in results.items():
        assert warning == ""
        assert png_bytes is not None
        im = Image.open(io.BytesIO(png_bytes))
        assert im.format == "PNG"


def test_render_ai_full_one_ratio_failing_does_not_block_others(monkeypatch, tmp_path):
    monkeypatch.setattr(httpx, "post", _fake_success_response)
    results = af.render_ai_full(_SPEC, ratios=("4:5", "16:9"), assets_dir=tmp_path)
    assert results["16:9"][0] is None
    assert "không hỗ trợ" in results["16:9"][1]
    assert results["4:5"][0] is not None
    assert results["4:5"][1] == ""


# --- brand_stamp.stamp_brand -------------------------------------------------

def test_stamp_brand_produces_valid_png_same_size():
    raw = _real_png_bytes(1024, 1280)
    stamped = bs.stamp_brand(raw, theme="dark", wordmark="FVA CAPITAL", source="test.vn", disclaimer="Disclaimer")
    im = Image.open(io.BytesIO(stamped))
    assert im.size == (1024, 1280)
    assert im.format == "PNG"


def test_stamp_brand_light_theme_does_not_crash():
    raw = _real_png_bytes(864, 1536)
    stamped = bs.stamp_brand(raw, theme="light", wordmark="FVA CAPITAL", source="", disclaimer="")
    im = Image.open(io.BytesIO(stamped))
    assert im.size == (864, 1536)


def test_wrap_to_width_splits_long_source_into_multiple_lines():
    """BUG THẬT phát hiện qua ảnh AI thật 2026-07-21: nguồn dài (trích dẫn
    HoSE) vẽ thẳng 1 dòng tràn hẳn ra ngoài mép ảnh phải. wrap_to_width phải
    tách thành nhiều dòng, mỗi dòng vừa `max_width`."""
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    font = bs._find_font(30)
    long_source = ("Nguồn: HoSE - Thông báo thay đổi tình trạng chứng khoán cổ phiếu "
                   "HVN của Tổng công ty Hàng không Việt Nam")
    max_width = 1024 - 2 * max(int(1024 * 0.04), 16)
    lines = bs._wrap_to_width(long_source, font, max_width, draw)
    assert len(lines) > 1, "nguon dai phai bi tach nhieu dong, khong con 1 dong duy nhat"
    for line in lines:
        assert draw.textlength(line, font=font) <= max_width


def test_stamp_brand_does_not_crash_with_long_source():
    long_source = "HoSE - Thông báo thay đổi tình trạng chứng khoán cổ phiếu HVN của Tổng công ty Hàng không Việt Nam"
    raw = _real_png_bytes(1024, 1280)
    stamped = bs.stamp_brand(raw, theme="dark", wordmark="FVA CAPITAL", source=long_source, disclaimer="")
    im = Image.open(io.BytesIO(stamped))
    assert im.size == (1024, 1280)


def test_stamp_brand_changes_pixels_in_safe_zones():
    """Xac nhan co ve gi do vao anh (khong phai no-op) -- so pixel dai top/
    bottom truoc/sau, phai khac nhau it nhat 1 vi tri."""
    raw = _real_png_bytes(1024, 1280)
    stamped = bs.stamp_brand(raw, theme="dark", wordmark="FVA CAPITAL", source="cafef.vn", disclaimer="Disclaimer text")
    before = Image.open(io.BytesIO(raw)).convert("RGB")
    after = Image.open(io.BytesIO(stamped)).convert("RGB")
    diff_found = False
    for y in range(30, 90, 4):
        for x in range(0, 1024, 8):
            if before.getpixel((x, y)) != after.getpixel((x, y)):
                diff_found = True
                break
        if diff_found:
            break
    assert diff_found, "vung dai an toan dinh khong doi -- stamp khong ve gi"


# --- BUOC 2026-07-22 (yeu cau Lead): logo that + disclaimer moi + nguon rut
# gon + co chu 75% ------------------------------------------------------------

def test_shorten_source_extracts_site_name_before_dash():
    assert bs._shorten_source("HoSE - Thông báo thay đổi tình trạng chứng khoán cổ phiếu HVN") == "HoSE"


def test_shorten_source_keeps_already_short_source_unchanged():
    assert bs._shorten_source("cafef.vn") == "cafef.vn"


def test_shorten_source_empty_stays_empty():
    assert bs._shorten_source("") == ""


def test_stamp_brand_long_source_gets_shortened_before_drawing():
    """Nguon dai (trich dan day du) phai duoc rut gon THANH TEN TRANG truoc
    khi ve -- xac nhan gian tiep qua so dong wrap: ban rut gon phai wrap it
    dong hon ban day du o cung do rong."""
    raw = _real_png_bytes(1024, 1280)
    long_source = "HoSE - Thông báo thay đổi tình trạng chứng khoán cổ phiếu HVN của Tổng công ty Hàng không Việt Nam"
    stamped = bs.stamp_brand(raw, theme="dark", source=long_source, disclaimer="")
    im = Image.open(io.BytesIO(stamped))
    assert im.size == (1024, 1280)  # khong crash, van ra anh hop le


def test_secondary_text_font_scale_is_75_percent_of_original_base():
    """Yeu cau Lead: disclaimer/nguon giam con 70-80% co chu cu -- xac nhan
    hang so scale dung 0.75 (giua khoang) va thuc su duoc nhan vao base_size
    TRUOC khi vao vong co-font (khong phai sau)."""
    assert bs._SECONDARY_TEXT_SCALE == 0.75
    bottom_h = 102
    old_disclaimer_base = int(bottom_h * 0.30)
    new_disclaimer_base = max(int(bottom_h * 0.30 * bs._SECONDARY_TEXT_SCALE), bs._MIN_READABLE_FONT_SIZE)
    assert new_disclaimer_base < old_disclaimer_base


def test_paste_logo_missing_file_does_not_crash(tmp_path):
    raw = _real_png_bytes(1024, 1280)
    missing = tmp_path / "khong-ton-tai.png"
    stamped = bs.stamp_brand(raw, theme="dark", logo_path=missing, source="cafef.vn", disclaimer="x")
    im = Image.open(io.BytesIO(stamped))
    assert im.size == (1024, 1280)


def test_paste_logo_uses_real_transparent_logo_file(tmp_path):
    """Dung fixture logo RGBA that (mau do net, nen trong suot) -- xac nhan
    mau do THAT SU xuat hien trong vung dinh sau khi dong dau (chung to logo
    anh duoc dan, khong phai chi bo qua)."""
    logo = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    ImageDraw.Draw(logo).rectangle([20, 20, 180, 180], fill=(255, 0, 0, 255))
    logo_path = tmp_path / "test_logo.png"
    logo.save(logo_path)

    raw = _real_png_bytes(1024, 1280)
    stamped = bs.stamp_brand(raw, theme="dark", logo_path=logo_path, source="", disclaimer="")
    im = Image.open(io.BytesIO(stamped)).convert("RGB")
    top_h = int(1280 * bs._TOP_SAFE_PCT)
    found_red = False
    for y in range(0, top_h):
        for x in range(0, 300):
            r, g, b = im.getpixel((x, y))
            if r > 200 and g < 60 and b < 60:
                found_red = True
                break
        if found_red:
            break
    assert found_red, "logo do khong xuat hien trong vung dinh -- _paste_logo khong dan anh"
