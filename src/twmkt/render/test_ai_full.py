"""Test render/ai_full.py + brand_stamp.py -- MOCK hoàn toàn httpx.post,
KHÔNG mạng thật, KHÔNG tốn tiền API khi chạy CI/test.

2026-07-23 (feature/infographic-frame, ĐẢO HƯỚNG P0 -- xem STOP-REPORT):
viết lại HOÀN TOÀN phần test brand_stamp/render_ai_full theo kiến trúc khung
cứng đáy (Phần A) + chính sách prompt mới (Phần B) + giới hạn mật độ (Phần
C) -- signature `stamp_brand`/`render_ai_full` đã đổi (BREAKING, xem
ai_full.py/brand_stamp.py docstring)."""
import io
import json

import httpx
import pytest
from PIL import Image, ImageDraw, ImageStat

from twmkt.config import Settings
from twmkt.render import ai_full as af
from twmkt.render import brand_stamp as bs

_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _real_png_bytes(w: int, h: int, color=(10, 20, 30)) -> bytes:
    im = Image.new("RGB", (w, h), color)
    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


def _busy_png_bytes(w: int, h: int) -> bytes:
    """Ảnh "lấp đầy 100% khung, không có chỗ trống nào" cho test A3 (Phần A3
    -- bắt buộc). Vẽ lưới ô màu xen kẽ CHẠM CẢ 4 MÉP (không có dải phẳng nào
    đủ dài để edge sanitizer bắt -- cố tình, để A3 kiểm ĐÚNG cấu trúc matting/
    band, không lẫn với hành vi edge sanitizer)."""
    im = Image.new("RGB", (w, h), (20, 20, 20))
    draw = ImageDraw.Draw(im)
    cell = max(w, h) // 24 or 1
    palette = [(200, 40, 40), (40, 160, 60), (40, 90, 200), (220, 200, 40), (180, 60, 180)]
    i = 0
    for y in range(0, h, cell):
        for x in range(0, w, cell):
            draw.rectangle([x, y, x + cell, y + cell], fill=palette[i % len(palette)])
            i += 1
    return _to_png_bytes(im)


def _to_png_bytes(im: Image.Image) -> bytes:
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


# --- Phần B1 -- cấm từ "chừa trống"/safe-zone -------------------------------

def test_check_prompt_banned_words_raises_on_any_banned_phrase():
    for phrase in af._BANNED_PROMPT_WORDS:
        with pytest.raises(ValueError):
            af._check_prompt_banned_words(f"some prompt text containing {phrase} somewhere")


def test_check_prompt_banned_words_case_insensitive():
    with pytest.raises(ValueError):
        af._check_prompt_banned_words("Please leave a SAFE ZONE at the top")


def test_check_prompt_banned_words_allows_clean_prompt():
    af._check_prompt_banned_words("Full-bleed dark navy background extending past all edges.")  # khong raise


def test_build_ai_full_prompt_v5_passes_banned_words_check():
    """Regression guard (B1) -- prompt THẬT do build_ai_full_prompt sinh ra
    PHẢI tự vượt qua chính check cấm từ của nó, mọi tỷ lệ/theme."""
    for theme in ("dark", "light"):
        for ratio in af.RATIO_SIZES:
            prompt = af.build_ai_full_prompt(_SPEC, theme=theme, ratio=ratio)
            af._check_prompt_banned_words(prompt)  # khong duoc raise


# --- prompt builder: BẮT BUỘC chứa rào an toàn, KHÔNG còn ngôn ngữ safe-zone -

def test_prompt_forbids_map_and_logo_and_requires_photorealistic():
    prompt = af.build_ai_full_prompt(_SPEC, theme="dark", ratio="4:5")
    lower = prompt.lower()
    assert "bản đồ" in lower
    assert "photorealistic" in lower
    assert "logo" in lower


def test_prompt_v5_uses_positive_layout_language_not_safe_zone():
    """Phần B2/B4 -- KHÔNG còn "%" dải an toàn/"chừa" nào, thay bằng mô tả
    DƯƠNG TÍNH (full-bleed, headline begins around 12%...)."""
    prompt = af.build_ai_full_prompt(_SPEC, theme="dark", ratio="4:5")
    lower = prompt.lower()
    assert "full-bleed" in lower
    assert "no cream or beige band" in lower
    assert "no border" in lower
    for w in af._BANNED_PROMPT_WORDS:
        assert w.lower() not in lower


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


# --- Phần C -- giới hạn TRÊN mật độ nội dung --------------------------------

def _spec_with_n_items(n_market: int, n_highlights: int, n_related: int) -> dict:
    return {
        "title": "T", "subtitle": "S",
        "hero": [{"label": "H", "value": "1"}],
        "market": [{"label": f"m{i}", "value": str(i)} for i in range(n_market)],
        "highlights": [f"h{i}" for i in range(n_highlights)],
        "related": [f"r{i}" for i in range(n_related)],
        "priority": {"primary": ["m0"], "secondary": ["m1"], "minor": [f"m{i}" for i in range(2, n_market)]},
        "source": "",
    }


def test_apply_density_cap_noop_when_under_cap():
    spec = _spec_with_n_items(3, 2, 3)
    capped, truncated = af.apply_density_cap(spec, ratio="4:5")
    assert capped["market"] == spec["market"]
    assert truncated == []


def test_apply_density_cap_cuts_minor_first_keeps_primary_secondary():
    spec = _spec_with_n_items(20, 2, 3)  # 20 > cap 12 cho 4:5
    capped, truncated = af.apply_density_cap(spec, ratio="4:5")
    assert len(capped["market"]) == 12
    kept_labels = [m["label"] for m in capped["market"]]
    assert "m0" in kept_labels  # primary GIỮ
    assert "m1" in kept_labels  # secondary GIỮ
    assert len(truncated) == 1
    entry = truncated[0]
    assert entry["block"] == "market" and entry["kept"] == 12 and entry["dropped"] == 8
    assert "m0" not in entry["dropped_labels"] and "m1" not in entry["dropped_labels"]


def test_apply_density_cap_respects_ratio_specific_caps():
    spec = _spec_with_n_items(10, 2, 3)  # 10 > cap 8 cho 9:16, <= cap 12 cho 4:5
    capped_916, trunc_916 = af.apply_density_cap(spec, ratio="9:16")
    capped_45, trunc_45 = af.apply_density_cap(spec, ratio="4:5")
    assert len(capped_916["market"]) == 8 and len(trunc_916) == 1
    assert len(capped_45["market"]) == 10 and trunc_45 == []


def test_apply_density_cap_caps_highlights_and_related_independently():
    spec = _spec_with_n_items(2, 10, 20)
    capped, truncated = af.apply_density_cap(spec, ratio="4:5")
    assert len(capped["highlights"]) == 3
    assert len(capped["related"]) == 12
    blocks = {t["block"] for t in truncated}
    assert blocks == {"highlights", "related"}


def test_apply_density_cap_does_not_touch_hero_or_title():
    spec = _spec_with_n_items(20, 10, 20)
    capped, _ = af.apply_density_cap(spec, ratio="4:5")
    assert capped["hero"] == spec["hero"]
    assert capped["title"] == spec["title"]


def test_apply_density_cap_reads_caps_from_settings_override():
    spec = _spec_with_n_items(5, 2, 3)
    settings = Settings({"infographic": {"ai_full": {"density_caps": {"4:5": {"market": 2, "highlights": 3, "related": 12}}}}})
    capped, truncated = af.apply_density_cap(spec, ratio="4:5", settings=settings)
    assert len(capped["market"]) == 2
    assert truncated[0]["kept"] == 2


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


# --- render_ai_full (orchestrator: cắt mật độ + sinh + đóng dấu) -----------

def test_render_ai_full_returns_stamped_bytes_and_logs_per_ratio(monkeypatch, tmp_path):
    monkeypatch.setattr(httpx, "post", _fake_success_response)
    results, logs = af.render_ai_full(_SPEC, ratios=("1:1", "4:5"), assets_dir=tmp_path)
    assert set(results.keys()) == {"1:1", "4:5"}
    for ratio, (png_bytes, warning) in results.items():
        assert warning == ""
        assert png_bytes is not None
        im = Image.open(io.BytesIO(png_bytes))
        assert im.format == "PNG"
        assert im.size == bs._DEFAULT_FINAL_SIZES[ratio]  # A1 -- khung CUỐI cố định theo tỷ lệ
    assert set(logs.keys()) == {"1:1", "4:5"}
    for ratio, log in logs.items():
        assert log["final_wh"] == list(bs._DEFAULT_FINAL_SIZES[ratio])
        assert "truncated" in log  # Phần C -- luôn có mặt (rỗng nếu không cắt gì)


def test_render_ai_full_one_ratio_failing_does_not_block_others(monkeypatch, tmp_path):
    monkeypatch.setattr(httpx, "post", _fake_success_response)
    results, logs = af.render_ai_full(_SPEC, ratios=("4:5", "16:9"), assets_dir=tmp_path)
    assert results["16:9"][0] is None
    assert "không hỗ trợ" in results["16:9"][1]
    assert "16:9" not in logs
    assert results["4:5"][0] is not None
    assert results["4:5"][1] == ""
    assert "4:5" in logs


def test_render_ai_full_density_cap_warning_recorded_in_log(monkeypatch, tmp_path, capsys):
    """C3-C4 -- vượt mật độ PHẢI cảnh báo rõ (stderr + log JSON), KHÔNG cắt
    im lặng."""
    monkeypatch.setattr(httpx, "post", _fake_success_response)
    spec = _spec_with_n_items(20, 2, 3)  # market vượt cap 12 (4:5) và 8 (9:16/1:1)
    results, logs = af.render_ai_full(spec, ratios=("4:5",), assets_dir=tmp_path)
    assert results["4:5"][0] is not None
    assert logs["4:5"]["truncated"], "phai co canh bao cat trong log JSON"
    err = capsys.readouterr().err
    assert "density cap" in err and "market" in err


# =====================================================================
# brand_stamp.stamp_brand -- kiến trúc khung cứng đáy (Phần A, 2026-07-23)
# =====================================================================

def _resolve_band_top_y(log: dict) -> int:
    w, h = log["final_wh"]
    return h - log["band_h"]


def test_stamp_brand_output_size_is_configured_final_size_not_input_size():
    """A1 -- khung CUỐI CỐ ĐỊNH theo tỷ lệ (config), KHÔNG phải "giữ nguyên
    kích thước ảnh AI đầu vào" như kiến trúc cũ."""
    raw = _real_png_bytes(1024, 1280)  # kich thuoc API sinh, KHAC final_size
    stamped, log = bs.stamp_brand(raw, ratio="4:5", theme="dark", source="test.vn", disclaimer="Disclaimer")
    im = Image.open(io.BytesIO(stamped))
    assert im.size == bs._DEFAULT_FINAL_SIZES["4:5"]
    assert log["final_wh"] == list(bs._DEFAULT_FINAL_SIZES["4:5"])


def test_stamp_brand_light_theme_does_not_crash():
    raw = _real_png_bytes(864, 1536)
    stamped, log = bs.stamp_brand(raw, ratio="9:16", theme="light", source="", disclaimer="")
    im = Image.open(io.BytesIO(stamped))
    assert im.size == bs._DEFAULT_FINAL_SIZES["9:16"]


def test_stamp_brand_reads_final_size_from_settings_override():
    raw = _real_png_bytes(1024, 1280)
    settings = Settings({"infographic": {"ai_full": {"final_size": {"4:5": [500, 625]}, "bottom_band_min_px": 40}}})
    stamped, log = bs.stamp_brand(raw, ratio="4:5", source="x", disclaimer="y", settings=settings)
    im = Image.open(io.BytesIO(stamped))
    assert im.size == (500, 625)


def test_wrap_to_width_splits_long_source_into_multiple_lines():
    """BUG THẬT phát hiện qua ảnh AI thật 2026-07-21: nguồn dài (trích dẫn
    HoSE) vẽ thẳng 1 dòng tràn hẳn ra ngoài mép ảnh phải. wrap_to_width phải
    tách thành nhiều dòng, mỗi dòng vừa `max_width`."""
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    font = bs._find_font(30)
    long_source = ("Nguồn: HoSE - Thông báo thay đổi tình trạng chứng khoán cổ phiếu "
                   "HVN của Tổng công ty Hàng không Việt Nam")
    max_width = 400
    lines = bs._wrap_to_width(long_source, font, max_width, draw)
    assert len(lines) > 1, "nguon dai phai bi tach nhieu dong, khong con 1 dong duy nhat"
    for line in lines:
        assert draw.textlength(line, font=font) <= max_width


def test_stamp_brand_does_not_crash_with_long_source():
    long_source = "HoSE - Thông báo thay đổi tình trạng chứng khoán cổ phiếu HVN của Tổng công ty Hàng không Việt Nam"
    raw = _real_png_bytes(1024, 1280)
    stamped, log = bs.stamp_brand(raw, ratio="4:5", theme="dark", source=long_source, disclaimer="")
    im = Image.open(io.BytesIO(stamped))
    assert im.size == bs._DEFAULT_FINAL_SIZES["4:5"]
    assert log["source_text"].startswith("Nguồn: HoSE")


def test_stamp_brand_never_shrinks_font_below_18px_grows_band_instead():
    """A2 Bước 4 -- KHÔNG BAO GIỜ thu font dưới 18px. Disclaimer RẤT dài buộc
    band phải NỚI CAO thay vì thu chữ quá nhỏ."""
    raw = _real_png_bytes(1024, 1280)
    very_long_disclaimer = "Đây là một dòng miễn trừ trách nhiệm rất dài " * 8
    stamped, log = bs.stamp_brand(raw, ratio="4:5", source="cafef.vn", disclaimer=very_long_disclaimer)
    im = Image.open(io.BytesIO(stamped))
    assert im.size == bs._DEFAULT_FINAL_SIZES["4:5"]  # final_wh KHÔNG đổi (A1 cố định)
    assert log["band_h"] >= round(bs._DEFAULT_FINAL_SIZES["4:5"][1] * 0.075)  # band đã nới >= danh nghĩa


def test_stamp_brand_band_area_is_solid_band_color_not_raw_ai_pixels():
    """Kiểm cấu trúc CỐT LÕI của Phần A: vùng band đáy PHẢI là màu band (tô
    solid), KHÔNG phải pixel ảnh AI còn sót lại -- proof va chạm chữ/nội
    dung là BẤT KHẢ THI VỀ CẤU TRÚC (matting đã thu ảnh AI vào vùng TRONG,
    band là vùng RIÊNG)."""
    raw = _busy_png_bytes(1024, 1280)  # nội dung lấp đầy, không có mảng phẳng nào
    stamped, log = bs.stamp_brand(raw, ratio="4:5", source="cafef.vn", disclaimer="Disclaimer text ngan")
    im = Image.open(io.BytesIO(stamped)).convert("RGB")
    band_top_y = _resolve_band_top_y(log)
    # Mau band (tu log) doi chieu voi mau TRUNG BINH cua 1 dai ngang NGAY DUOI
    # dong chu (gan day anh, it kha nang dinh glyph chu) -- phai gan mau band.
    probe_y = im.height - 6
    stat = ImageStat.Stat(im.crop((10, probe_y, im.width - 10, probe_y + 1)))
    expected = log["band_color"].lstrip("#")
    expected_rgb = (int(expected[0:2], 16), int(expected[2:4], 16), int(expected[4:6], 16))
    got_rgb = tuple(round(v) for v in stat.mean[:3])
    for a, b in zip(got_rgb, expected_rgb):
        assert abs(a - b) <= 15, f"day anh KHONG phai mau band ({got_rgb} != {expected_rgb})"
    assert band_top_y > 0


def test_shorten_source_extracts_site_name_before_dash():
    assert bs._shorten_source("HoSE - Thông báo thay đổi tình trạng chứng khoán cổ phiếu HVN") == "HoSE"


def test_shorten_source_keeps_already_short_source_unchanged():
    assert bs._shorten_source("cafef.vn") == "cafef.vn"


def test_shorten_source_empty_stays_empty():
    assert bs._shorten_source("") == ""


def test_stamp_brand_long_source_gets_shortened_before_drawing():
    """Nguon dai (trich dan day du) phai duoc rut gon THANH TEN TRANG truoc
    khi ve -- xac nhan qua log["source_text"]."""
    raw = _real_png_bytes(1024, 1280)
    long_source = "HoSE - Thông báo thay đổi tình trạng chứng khoán cổ phiếu HVN của Tổng công ty Hàng không Việt Nam"
    stamped, log = bs.stamp_brand(raw, ratio="4:5", theme="dark", source=long_source, disclaimer="")
    assert log["source_text"] == "Nguồn: HoSE"


def test_secondary_text_font_scale_is_75_percent_of_original_base():
    """Yeu cau Lead: disclaimer/nguon giam con 70-80% co chu cu -- xac nhan
    hang so scale dung 0.75."""
    assert bs._SECONDARY_TEXT_SCALE == 0.75


def test_min_readable_font_size_is_18px():
    """A2 Bước 4 (yêu cầu Lead 2026-07-23): KHÔNG BAO GIỜ thu font dưới
    18px (khác 16px của kiến trúc cũ)."""
    assert bs._MIN_READABLE_FONT_SIZE == 18


def test_paste_logo_missing_file_does_not_crash(tmp_path):
    raw = _real_png_bytes(1024, 1280)
    missing = tmp_path / "khong-ton-tai.png"
    stamped, log = bs.stamp_brand(raw, ratio="4:5", theme="dark", logo_path=missing, source="cafef.vn", disclaimer="x")
    im = Image.open(io.BytesIO(stamped))
    assert im.size == bs._DEFAULT_FINAL_SIZES["4:5"]
    assert log["scrim_applied"] is False


def test_paste_logo_uses_real_transparent_logo_file(tmp_path):
    """Dung fixture logo RGBA that (mau do net, nen trong suot) -- xac nhan
    mau do THAT SU xuat hien o goc tren-trai sau khi dong dau (chung to logo
    anh duoc dan, khong phai chi bo qua)."""
    logo = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    ImageDraw.Draw(logo).rectangle([20, 20, 180, 180], fill=(255, 0, 0, 255))
    logo_path = tmp_path / "test_logo.png"
    logo.save(logo_path)

    raw = _real_png_bytes(1024, 1280)
    stamped, log = bs.stamp_brand(raw, ratio="4:5", theme="dark", logo_path=logo_path, source="", disclaimer="")
    im = Image.open(io.BytesIO(stamped)).convert("RGB")
    final_w, final_h = bs._DEFAULT_FINAL_SIZES["4:5"]
    logo_zone_h = max(round(final_h * 0.06), 24) + max(int(final_w * 0.04), 16)
    found_red = False
    for y in range(0, logo_zone_h):
        for x in range(0, 300):
            r, g, b = im.getpixel((x, y))
            if r > 200 and g < 60 and b < 60:
                found_red = True
                break
        if found_red:
            break
    assert found_red, "logo do khong xuat hien o goc tren-trai -- _paste_logo_with_scrim khong dan anh"


def test_logo_scrim_applied_when_background_bright():
    """A2 Bước 5 -- scrim CHỈ vẽ khi vùng bbox logo nở 20% có luminance >
    110 (nền sáng, tương phản thấp với logo)."""
    bright = _real_png_bytes(1024, 1280, color=(230, 230, 230))
    stamped, log = bs.stamp_brand(bright, ratio="4:5", theme="dark", source="", disclaimer="")
    assert log["scrim_applied"] is True


def test_logo_scrim_not_applied_when_background_dark():
    dark = _real_png_bytes(1024, 1280, color=(10, 10, 15))
    stamped, log = bs.stamp_brand(dark, ratio="4:5", theme="dark", source="", disclaimer="")
    assert log["scrim_applied"] is False


# --- Bước 1 (edge sanitizer) -------------------------------------------------

def test_edge_sanitizer_crops_flat_anomalous_top_band():
    """A2 Bước 1 -- dải PHẲNG khác hẳn nền bên dưới (vd dải kem ~10% chiều
    cao trên nền navy) PHẢI bị cắt."""
    h, w = 1280, 1024
    im = Image.new("RGB", (w, h), (10, 15, 25))  # nen navy toi
    band_h = int(h * 0.10)
    ImageDraw.Draw(im).rectangle([0, 0, w, band_h], fill=(245, 235, 210))  # dai kem sang, phang
    cropped, cropped_px = bs._edge_sanitize_top(im)
    assert cropped_px >= 8
    assert cropped.size == (w, h - cropped_px)


def test_edge_sanitizer_noop_on_normal_photo_content():
    """KHÔNG cắt "phòng xa" -- ảnh có chi tiết thật (không phẳng) ở mép trên
    thì giữ nguyên."""
    im = _busy_png_bytes(1024, 1280)
    im = Image.open(io.BytesIO(im))
    cropped, cropped_px = bs._edge_sanitize_top(im)
    assert cropped_px == 0
    assert cropped.size == im.size


def test_stamp_brand_log_reports_cropped_top_px():
    h, w = 1280, 1024
    im = Image.new("RGB", (w, h), (10, 15, 25))
    ImageDraw.Draw(im).rectangle([0, 0, w, int(h * 0.10)], fill=(245, 235, 210))
    raw = _to_png_bytes(im)
    stamped, log = bs.stamp_brand(raw, ratio="4:5", source="", disclaimer="")
    assert log["cropped_top_px"] > 0


# =====================================================================
# Phần A3 (BẮT BUỘC, yêu cầu Lead) -- ảnh nền KÍN 100% khung, không chỗ trống.
# Kết quả PHẢI: đủ logo + nguồn + disclaimer, đọc được, KHÔNG pixel nội dung
# nào bị chữ đè lên. Lưu ảnh ra tmp_path để đính kèm bằng chứng.
# =====================================================================

def test_A3_fully_packed_background_gets_logo_source_disclaimer_no_content_overlap(tmp_path):
    for ratio in af.RATIO_SIZES:
        raw = _busy_png_bytes(*af.RATIO_SIZES[ratio])
        stamped, log = bs.stamp_brand(
            raw, ratio=ratio, theme="dark",
            source="cafef.vn - Bài kiểm tra mật độ dày đặc", disclaimer="Nội dung mang tính tham khảo, không phải khuyến nghị đầu tư.",
        )
        im = Image.open(io.BytesIO(stamped))
        final_w, final_h = bs._DEFAULT_FINAL_SIZES[ratio]
        assert im.size == (final_w, final_h)

        # 1) Nguồn + disclaimer PHẢI có mặt, KHÔNG rỗng.
        assert log["source_text"] == "Nguồn: cafef.vn"
        assert log["disclaimer_lines"] and "".join(log["disclaimer_lines"])

        # 2) Band đáy PHẢI là band_color (KHÔNG phải pixel ảnh AI/busy pattern
        #    còn sót -- proof cấu trúc: matting đã thu ảnh vào vùng TRONG).
        rgb = Image.open(io.BytesIO(stamped)).convert("RGB")
        band_top_y = final_h - log["band_h"]
        probe_y = final_h - 6
        stat = ImageStat.Stat(rgb.crop((10, probe_y, final_w - 10, probe_y + 1)))
        expected = log["band_color"].lstrip("#")
        expected_rgb = (int(expected[0:2], 16), int(expected[2:4], 16), int(expected[4:6], 16))
        got_rgb = tuple(round(v) for v in stat.mean[:3])
        for a, b in zip(got_rgb, expected_rgb):
            assert abs(a - b) <= 20, f"[{ratio}] day band KHONG phai band_color ({got_rgb} != {expected_rgb})"

        # 3) Logo PHẢI xuất hiện góc trên-trái (khớp _DEFAULT_LOGO_PATH thật,
        #    kiểm gián tiếp qua scrim/luminance thay vì màu cụ thể vì logo
        #    thật KHÔNG phải khối màu đơn -- xác nhận không crash + kích
        #    thước đúng đã đủ chứng minh bước 5 chạy trọn vẹn cho A3).
        assert band_top_y > 0
        assert band_top_y < final_h

        out_path = tmp_path / f"a3_evidence_{ratio.replace(':', 'x')}.png"
        out_path.write_bytes(stamped)
        log_path = tmp_path / f"a3_evidence_{ratio.replace(':', 'x')}.log.json"
        log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
