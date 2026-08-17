"""Autouse: chặn CỨNG mọi lời gọi model THẬT (subprocess `claude -p` /
Anthropic API) trong toàn bộ suite (`tests/` + `store/`) -- TASK-015 VIỆC 2
(2026-08-16).

BỐI CẢNH (đo được, xem handoffs/TASK-015-agent-b.md): `llm_status()` TRƯỚC
ĐÂY coi `claude_code` là "không phải anthropic" -> use_llm=False ->
`build_content_llm()` LUÔN lùi về MockLLM DÙ config thật (config/
settings.yaml: llm.provider=claude_code) đã trỏ sang LLM thật. Test
`test_run_*()` (tests/test_pipeline.py, `_run_produce_scenario`) chạy
`produce_from_sheet.run()` THẬT với settings THẬT (`real_load_settings()`)
-- suốt thời gian đó suite được bảo vệ khỏi gọi model thật CHỈ VÌ bug đó,
KHÔNG phải chủ đích. Sửa bug ở factory.llm_status() (commit 447cfd3) làm lộ
ra: KHÔNG có gì khác chặn subprocess `claude -p` thật -- 1 lượt full suite từ
~90s vọt lên ~19 phút và tốn tiền thật (ngân sách Pro của chủ dự án).

CƠ CHẾ CHẶN (tầng LLMClient, KHÔNG chặn ở tầng settings/provider -- Lead yêu
cầu test PHẢI tự ép mock, không lệ thuộc llm_status()/provider trả ra gì):
  - ClaudeCodeLLM.__init__ có `run_fn=subprocess.run` làm default -- default
    argument chụp THAM CHIẾU hàm `subprocess.run` GỐC 1 LẦN lúc module nạp,
    nên patch `subprocess.run` sau đó KHÔNG có tác dụng gì (default đã bind
    xong). Patch ĐÚNG chỗ nó nằm: `ClaudeCodeLLM.__init__.__defaults__`.
  - `anthropic.Anthropic` (client SDK, gọi trong AnthropicLLM.complete()) bị
    thay bằng stub raise-ngay-khi-khởi-tạo.
  - Cả 2 raise `_RealLLMCallBlocked` kế thừa THẲNG `BaseException` (không
    phải `Exception`): ClaudeCodeLLM.complete() vốn chỉ bắt
    FileNotFoundError/TimeoutExpired quanh self._run_fn(...) nên đã tự nổ;
    AnthropicLLM.complete() có `except Exception` RỘNG (lùi mượt lỗi mạng
    thật) sẽ KHÔNG bắt được BaseException -- test nào lỡ gọi complete() thật
    sẽ GÃY NGAY (traceback rõ), KHÔNG lùi mượt trả "" rồi chạy tiếp âm thầm.

Test CỐ Ý kiểm hành vi provider thật (vd
test_llm_status_banner_active_for_claude_code_no_key_needed) chỉ gọi
llm_status()/kiểm kiểu đối tượng trả về, KHÔNG gọi .complete() -> không đụng
tới cơ chế chặn này. Test tự tiêm `ClaudeCodeLLM(run_fn=<fake>)` (đã có sẵn
nhiều test làm vậy, xem test_claude_code_llm_*) truyền run_fn RIÊNG -> override
default bị patch, KHÔNG bị chặn (đúng ý, đó là double hợp lệ)."""
from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

import pytest


class _RealLLMCallBlocked(BaseException):
    """Kế thừa BaseException (KHÔNG phải Exception) để xuyên qua mọi
    `except Exception` lùi-mượt trong agents/base.py -- xem docstring module."""


def _blocked_run_fn(cmd, **kwargs):
    raise _RealLLMCallBlocked(
        "CHẶN (TASK-015): test cố gọi `claude -p` THẬT qua subprocess.run(). "
        "Tiêm ClaudeCodeLLM(run_fn=<fake>) hoặc double cho "
        "factory.build_content_llm/make_llm/build_writer_llm -- ĐỪNG để code "
        "dựng ClaudeCodeLLM() mặc định chạy thật trong test."
    )


class _BlockedAnthropicClient:
    def __init__(self, *a, **kw):
        raise _RealLLMCallBlocked(
            "CHẶN (TASK-015): test cố gọi Anthropic API THẬT qua "
            "anthropic.Anthropic(). Patch AnthropicLLM/is_available hoặc "
            "double, ĐỪNG để complete() thật chạm mạng trong test."
        )


@pytest.fixture(autouse=True)
def _block_real_llm_calls(monkeypatch):
    from twmkt.agents import base as llm_base

    real_binary, real_timeout, _real_run_fn = llm_base.ClaudeCodeLLM.__init__.__defaults__
    monkeypatch.setattr(
        llm_base.ClaudeCodeLLM.__init__, "__defaults__",
        (real_binary, real_timeout, _blocked_run_fn),
    )

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", _BlockedAnthropicClient)

    # BUG THẬT lộ ra khi merge 2026-08-17 (Lead): 2 test xanh khi chạy RIÊNG, đỏ
    # khi chạy CẢ BỘ. Nguyên nhân: `config._load_dotenv()` bơm ANTHROPIC_API_KEY
    # từ secrets/.env vào `os.environ` ở MỌI lượt `load_settings()` — nên một test
    # gọi load_settings() là làm bẩn env cho TOÀN BỘ tiến trình pytest. Các test
    # giả định "thiếu key -> AnthropicLLM lùi mượt" (vd
    # test_llmclient_complete_old_2arg_call_sites_still_work) sau đó lại thấy CÓ
    # key -> đi nhánh dựng client THẬT. Kết quả test phụ thuộc THỨ TỰ CHẠY.
    # Dọn env ở đây, cùng chỗ với cơ chế chặn, để không test nào phụ thuộc/rò
    # trạng thái ambient. Test nào CỐ Ý cần key thì tự monkeypatch.setenv trong
    # thân test — chạy SAU fixture autouse này nên vẫn có hiệu lực.
    for _var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(_var, raising=False)

    yield
