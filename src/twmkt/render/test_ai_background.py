"""Test render/ai_background.py -- MOCK hoàn toàn httpx.post, KHÔNG mạng
thật, KHÔNG tốn tiền API khi chạy CI/test. Dùng tmp_path làm assets_dir cô
lập mỗi test."""
import base64
import json

import httpx
import pytest

from twmkt.render import ai_background as ab

# 1x1 PNG trong suốt thật (giữ test rẻ, không cần ảnh lớn) -- base64 hợp lệ.
_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
_TINY_PNG_BYTES = base64.b64decode(_TINY_PNG_B64)


def _fake_success_response(*a, **kw):
    return httpx.Response(
        200, json={"data": [{"b64_json": _TINY_PNG_B64}]}, request=httpx.Request("POST", ab._API_URL)
    )


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key-not-real")
    yield


def test_default_assets_dir_resolves_under_data_root_not_repo(monkeypatch, tmp_path):
    """Dữ liệu SINH RA (kể cả cache ảnh AI) KHÔNG BAO GIỜ được ghi trong repo
    -- assets_dir=None (mặc định) PHẢI resolve qua config.data_path(), dưới
    storage.data_root, KHÔNG phải 1 thư mục "assets" tương đối trong repo
    (bug thật đã xảy ra, xem docs/VPS_MIGRATION_BACKLOG.md + assets/README.md
    mục "Nợ hiển nhiên KHÔNG được lặp lại")."""
    from twmkt.config import Settings

    monkeypatch.setattr(httpx, "post", _fake_success_response)
    fake_data_root = tmp_path / "fake-data-root"
    settings = Settings({"storage": {"data_root": str(fake_data_root)}})

    path, warning = ab.get_or_generate_background("chu de data root", settings=settings)

    assert warning == ""
    assert path is not None
    assert fake_data_root.resolve() in path.resolve().parents
    assert "assets" in path.parts


def test_cache_key_deterministic_same_input_same_key():
    k1 = ab._cache_key("chu de A", "prompt X", "v1")
    k2 = ab._cache_key("chu de A", "prompt X", "v1")
    assert k1 == k2


def test_cache_key_differs_when_topic_differs():
    k1 = ab._cache_key("chu de A", "prompt X", "v1")
    k2 = ab._cache_key("chu de B", "prompt X", "v1")
    assert k1 != k2


def test_missing_api_key_returns_none_with_warning(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    path, warning = ab.get_or_generate_background("chu de test", assets_dir=tmp_path)
    assert path is None
    assert "OPENAI_API_KEY" in warning
    assert "pure_html" in warning


def test_successful_generation_writes_cache_and_manifest(monkeypatch, tmp_path):
    monkeypatch.setattr(httpx, "post", _fake_success_response)
    path, warning = ab.get_or_generate_background("chu de moi", assets_dir=tmp_path)
    assert warning == ""
    assert path is not None
    assert path.exists()
    assert path.read_bytes() == _TINY_PNG_BYTES

    manifest_path = tmp_path / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(iter(manifest.values()))
    assert entry["topic"] == "chu de moi"
    assert "prompt" in entry and "cost_estimate_usd" in entry and "generated_at" in entry


def test_cache_hit_does_not_call_api(monkeypatch, tmp_path):
    call_count = {"n": 0}

    def _tracked_post(*a, **kw):
        call_count["n"] += 1
        return _fake_success_response(*a, **kw)

    monkeypatch.setattr(httpx, "post", _tracked_post)
    path1, _ = ab.get_or_generate_background("chu de cache", assets_dir=tmp_path)
    assert call_count["n"] == 1

    # Lần gọi THỨ HAI, cùng topic -- phải cache HIT, KHÔNG gọi API lần nữa.
    monkeypatch.setattr(httpx, "post", _tracked_post)
    path2, warning2 = ab.get_or_generate_background("chu de cache", assets_dir=tmp_path)
    assert call_count["n"] == 1, "cache HIT nhưng vẫn gọi API -- SAI"
    assert warning2 == ""
    assert path1 == path2


def test_regenerate_flag_bypasses_cache(monkeypatch, tmp_path):
    call_count = {"n": 0}

    def _tracked_post(*a, **kw):
        call_count["n"] += 1
        return _fake_success_response(*a, **kw)

    monkeypatch.setattr(httpx, "post", _tracked_post)
    ab.get_or_generate_background("chu de regen", assets_dir=tmp_path)
    assert call_count["n"] == 1

    ab.get_or_generate_background("chu de regen", assets_dir=tmp_path, regenerate=True)
    assert call_count["n"] == 2, "--regenerate phải gọi lại API dù cache đã có"


def test_api_http_error_returns_none_with_warning_not_raise(monkeypatch, tmp_path):
    def _fake_error_response(*a, **kw):
        return httpx.Response(429, text="rate limit exceeded", request=httpx.Request("POST", ab._API_URL))

    monkeypatch.setattr(httpx, "post", _fake_error_response)
    path, warning = ab.get_or_generate_background("chu de loi", assets_dir=tmp_path)
    assert path is None
    assert "429" in warning
    assert "pure_html" in warning.lower() or "fallback" in warning.lower()


def test_api_timeout_returns_none_with_warning_not_raise(monkeypatch, tmp_path):
    def _fake_timeout(*a, **kw):
        raise httpx.TimeoutException("simulated timeout")

    monkeypatch.setattr(httpx, "post", _fake_timeout)
    path, warning = ab.get_or_generate_background("chu de timeout", assets_dir=tmp_path)
    assert path is None
    assert "timeout" in warning.lower()


def test_api_malformed_response_returns_none_with_warning(monkeypatch, tmp_path):
    def _fake_bad_shape(*a, **kw):
        return httpx.Response(200, json={"unexpected": "shape"}, request=httpx.Request("POST", ab._API_URL))

    monkeypatch.setattr(httpx, "post", _fake_bad_shape)
    path, warning = ab.get_or_generate_background("chu de bad shape", assets_dir=tmp_path)
    assert path is None
    assert warning != ""


def test_build_background_prompt_forbids_text_and_numbers():
    prompt = ab.build_background_prompt("cang bien Viet Nam")
    lower = prompt.lower()
    assert "no text" in lower
    assert "no numbers" in lower
    assert "no letters" in lower
    assert "no watermark" in lower
    assert "no labels" in lower
    assert "axis labels" in lower


def test_build_background_prompt_uses_topic_not_raw_numbers():
    prompt = ab.build_background_prompt("tang truong GDP 6.5%")
    # topic được nhúng NGUYÊN VĂN (đây là điều B2 cho phép — cấm là cấm AI
    # VẼ số vào ảnh, không cấm nhắc chủ đề có số trong câu mô tả) -- nhưng
    # hướng dẫn "no numbers" vẫn phải có để chặn AI vẽ số ra ảnh.
    assert "tang truong GDP 6.5%" in prompt
    assert "no numbers" in prompt.lower()
