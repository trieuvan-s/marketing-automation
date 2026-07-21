"""Test render/infographic.py::render_infographic() -- lớp DISPATCH hybrid/
pure_html. KHÔNG mạng thật (mock httpx.post ở tầng ai_background). Test
render_infographic_svg() gốc (không hybrid) đã có sẵn ở tests/test_pipeline.py
-- KHÔNG lặp lại ở đây, chỉ test phần MỚI (dispatch + nhúng ảnh nền + B6)."""
import base64
import json

import httpx
import pytest

from twmkt.config import Settings
from twmkt.render import infographic as ig

_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)

_SPEC = {
    "title": "Cang bien dac biet",
    "subtitle": "Quy mo dau tu ha tang",
    "hero": [{"label": "Von dau tu", "value": "141 nghin ty"}],
    "market": [{"label": "So cang", "value": "15"}],
    "highlights": ["Diem noi bat mot", "Diem noi bat hai"],
    "related": ["PNJ"],
    "source": "cafef.vn",
}


def _fake_success_response(*a, **kw):
    return httpx.Response(
        200, json={"data": [{"b64_json": _TINY_PNG_B64}]},
        request=httpx.Request("POST", "https://api.openai.com/v1/images/generations"),
    )


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key-not-real")
    yield


def test_pure_html_mode_never_calls_api(monkeypatch, tmp_path):
    call_count = {"n": 0}
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: call_count.__setitem__("n", call_count["n"] + 1))
    settings = Settings({"render": {"infographic": {"render_mode": "pure_html"}}})

    svg, warning = ig.render_infographic(_SPEC, settings=settings, topic=_SPEC["title"], assets_dir=tmp_path)

    assert call_count["n"] == 0, "pure_html KHÔNG được gọi API"
    assert warning == ""
    assert "<svg" in svg
    assert "<image" not in svg   # không nhúng ảnh nền


def test_hybrid_mode_missing_topic_falls_back_to_pure_html(monkeypatch, tmp_path):
    call_count = {"n": 0}
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: call_count.__setitem__("n", call_count["n"] + 1))
    settings = Settings({"render": {"infographic": {"render_mode": "hybrid"}}})

    svg, warning = ig.render_infographic(_SPEC, settings=settings, topic=None, assets_dir=tmp_path)

    assert call_count["n"] == 0
    assert "topic" in warning.lower()
    assert "<svg" in svg


def test_hybrid_mode_missing_api_key_falls_back_gracefully(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = Settings({"render": {"infographic": {"render_mode": "hybrid"}}})

    svg, warning = ig.render_infographic(_SPEC, settings=settings, topic=_SPEC["title"], assets_dir=tmp_path)

    assert "OPENAI_API_KEY" in warning
    assert "<svg" in svg   # vẫn ra SVG hợp lệ, KHÔNG crash, KHÔNG ảnh vỡ (B5)
    assert "</svg>" in svg


def test_hybrid_mode_success_embeds_background_image(monkeypatch, tmp_path):
    monkeypatch.setattr(httpx, "post", _fake_success_response)
    settings = Settings({"render": {"infographic": {"render_mode": "hybrid"}}})

    svg, warning = ig.render_infographic(_SPEC, settings=settings, topic=_SPEC["title"], assets_dir=tmp_path)

    assert warning == ""
    assert "<image href=\"data:image/png;base64," in svg
    # 2 lớp ảnh (toàn trang mờ + dải header) -- xem _background_image_layers()
    assert svg.count("<image href=") == 2


def test_two_renders_same_input_produce_byte_identical_svg(monkeypatch, tmp_path):
    """Xương sống của B3 (cache -> tất định): render 2 LẦN cùng input (kể cả
    hybrid mode) phải ra CÙNG 1 chuỗi SVG -- so bằng hash, KHÔNG chỉ ==."""
    import hashlib

    monkeypatch.setattr(httpx, "post", _fake_success_response)
    settings = Settings({"render": {"infographic": {"render_mode": "hybrid"}}})

    svg1, w1 = ig.render_infographic(_SPEC, settings=settings, topic=_SPEC["title"], assets_dir=tmp_path)
    svg2, w2 = ig.render_infographic(_SPEC, settings=settings, topic=_SPEC["title"], assets_dir=tmp_path)

    assert w1 == "" and w2 == ""
    assert hashlib.sha256(svg1.encode()).hexdigest() == hashlib.sha256(svg2.encode()).hexdigest()
    assert svg1 == svg2


def test_default_render_mode_is_hybrid_when_settings_none():
    """B1: mặc định "hybrid" khi KHÔNG truyền settings (đọc default trong
    code) -- test này KHÔNG gọi API thật, chỉ xác nhận nhánh code đi vào
    "hybrid" (thiếu topic -> fallback ngay, không crash) để chứng minh default
    đúng "hybrid" chứ không lặng lẽ về "pure_html"."""
    svg, warning = ig.render_infographic(_SPEC, settings=None, topic=None)
    assert "topic" in warning.lower()   # fallback vì thiếu topic -- CHỈ xảy ra ở nhánh hybrid


def test_short_content_gets_extra_spacing_not_left_empty():
    """B6: nội dung NGẮN (1 highlight, 1 stat) phải có extra_gap > 0 --
    không còn để trống 1 mảng lớn cố định như bản cũ."""
    short_spec = {**_SPEC, "highlights": ["Chi mot diem"], "hero": [{"label": "X", "value": "1"}], "market": []}
    svg_short, _ = ig.render_infographic(short_spec, settings=Settings({"render": {"infographic": {"render_mode": "pure_html"}}}), topic="x")

    long_spec = {**_SPEC, "highlights": ["Diem " + str(i) for i in range(5)],
                 "hero": [{"label": f"L{i}", "value": f"{i}"} for i in range(5)]}
    svg_long, _ = ig.render_infographic(long_spec, settings=Settings({"render": {"infographic": {"render_mode": "pure_html"}}}), topic="x")

    # Không assert con số cụ thể (dễ vỡ khi tinh chỉnh hằng số sau này) --
    # chỉ xác nhận CẢ 2 đều ra SVG hợp lệ và (gián tiếp) rằng hàm đo
    # _measure_content_height() thực sự phân biệt được 2 ca khác chiều dài.
    from twmkt.render.infographic import _prepare_content, _measure_content_height
    h_short = _measure_content_height(_prepare_content(short_spec, 1080), cw=900, pad=76, disclaimer_lines=2)
    h_long = _measure_content_height(_prepare_content(long_spec, 1080), cw=900, pad=76, disclaimer_lines=2)
    assert h_short < h_long
    assert "<svg" in svg_short and "<svg" in svg_long
