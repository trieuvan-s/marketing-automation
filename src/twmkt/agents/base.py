"""Lớp LLM trừu tượng + Agent base.

Nguyên tắc: LLM chỉ sinh NGÔN NGỮ (diễn giải, văn phong). Mọi CON SỐ phải đến
từ ervn (tất định). MockLLM cho phép chạy offline, AnthropicLLM cho production,
ClaudeCodeLLM dùng CLI `claude -p` (gói Pro/Max/Team, không cần API key riêng).

`complete(system, prompt, *, model=None, fail_loud=False, temperature=None)`: 3
tham số MỞ RỘNG (keyword-only, mặc định giữ hành vi CŨ) để pipeline mới
(factory.make_llm + llm.step_models) chọn model/độ ngẫu nhiên theo TỪNG BƯỚC —
mọi call site CŨ gọi `complete(system, prompt)` (2 tham số dương) vẫn chạy y
nguyên, kể cả xuyên qua LLMRouter (agents/router.py, KHÔNG đụng tới ở đây) vì
LLMRouter tự gọi `base.complete(system, prompt)` không kèm tham số mở rộng.
  - `model=None` -> backend tự dùng model mặc định của nó (constructor).
  - `fail_loud=False` (mặc định) -> LÙI MƯỢT như cũ (cảnh báo + trả ""). Bước
    QUAN TRỌNG (vd Writer — xem CLAUDE.md v3 roadmap) truyền `fail_loud=True`
    -> lỗi/timeout/is_error RAISE `LLMCallError` thay vì im lặng trả "" (không
    được sinh nội dung rỗng/ngầm rồi ghi CONTENT như thật).
  - `temperature=None` (Phase 3.6, ổn định StructureRouter) -> backend tự dùng
    mặc định của nó. AnthropicLLM: truyền THẲNG vào API (0.0-1.0, hỗ trợ đầy
    đủ). ClaudeCodeLLM: CLI `claude -p` KHÔNG expose tham số sampling nào (đã
    kiểm `claude -p --help` — không có `--temperature`/`--seed`) -> tham số bị
    BỎ QUA (no-op), cảnh báo 1 lần nếu có truyền giá trị, KHÔNG raise. Với
    backend này, độ ổn định dựa vào THƯỚC ĐO (residual_tension, xem
    agents/structure_router.py) thay vì tham số sampling.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Protocol


class LLMCallError(RuntimeError):
    """Raise khi backend gọi fail_loud=True mà lỗi/timeout/is_error — bước gọi
    (vd Writer) PHẢI thấy lỗi để đánh dấu dòng FAILED + log ERROR, không được
    âm thầm coi như "" rồi sinh nội dung rỗng."""


class LLMClient(Protocol):
    def complete(self, system: str, prompt: str, *, model: str | None = None,
                fail_loud: bool = False, temperature: float | None = None) -> str: ...


class MockLLM(LLMClient):
    """Trả lời tất định, không gọi mạng. Dùng cho demo/test. Không bao giờ lỗi
    -> `fail_loud`/`temperature` không có tác dụng (nhận tham số để khớp interface)."""

    def complete(self, system: str, prompt: str, *, model: str | None = None,
                fail_loud: bool = False, temperature: float | None = None) -> str:
        role = system.strip().splitlines()[0] if system.strip() else "agent"
        head = prompt.strip().splitlines()[0][:80] if prompt.strip() else ""
        return f"[MOCK::{role}] {head}"


class AnthropicLLM(LLMClient):
    """Production: gọi Claude. Import hoãn để offline không cần SDK/khóa API.

    LÙI MƯỢT (fail_loud=False, mặc định): thiếu SDK/khóa API hoặc call lỗi ->
    in cảnh báo (1 lần) rồi TRẢ RỖNG, KHÔNG raise. fail_loud=True -> raise
    LLMCallError thay vì trả rỗng (dùng cho bước không được phép âm thầm hỏng).
    """

    # alias (haiku|sonnet|opus) -> model id thật của API Anthropic. `model` truyền
    # vào complete() có thể là alias HOẶC id đầy đủ (map miss -> giữ nguyên, coi
    # như đã là id thật/tên tuỳ chỉnh).
    _ALIASES = {
        "haiku": "claude-haiku-4-5-20251001",
        "sonnet": "claude-sonnet-4-6",
        "opus": "claude-opus-4-8",
    }

    def __init__(self, model: str = "claude-sonnet-4-6", max_tokens: int = 1500):
        self.model = model
        self.max_tokens = max_tokens
        self._warned = False

    @staticmethod
    def is_available() -> tuple[bool, str]:
        """(gọi được API thật?, lý do nếu không) — kiểm SDK anthropic + ANTHROPIC_API_KEY."""
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False, "chưa cài SDK (pip install anthropic)"
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return False, "thiếu ANTHROPIC_API_KEY"
        return True, ""

    def _warn(self, msg: str) -> None:
        if not self._warned:
            print(f"[CẢNH BÁO] {msg} -> Hook/Researcher dùng fallback tất định ($0).")
            self._warned = True

    def _fail(self, msg: str, *, fail_loud: bool) -> str:
        if fail_loud:
            raise LLMCallError(msg)
        self._warn(msg)
        return ""

    def complete(self, system: str, prompt: str, *, model: str | None = None,
                fail_loud: bool = False, temperature: float | None = None) -> str:
        ok, why = self.is_available()
        if not ok:
            return self._fail(f"AnthropicLLM không dùng được ({why})", fail_loud=fail_loud)
        resolved_model = self._ALIASES.get(model, model) if model else self.model
        kwargs = {} if temperature is None else {"temperature": temperature}
        try:
            import anthropic
            client = anthropic.Anthropic()
            msg = client.messages.create(
                model=resolved_model, max_tokens=self.max_tokens,
                system=system, messages=[{"role": "user", "content": prompt}], **kwargs,
            )
            return "".join(b.text for b in msg.content if b.type == "text")
        except Exception as e:              # auth/mạng/quota... -> lùi mượt hoặc raise
            return self._fail(f"Gọi Anthropic lỗi ({e!r})", fail_loud=fail_loud)


class ClaudeCodeLLM(LLMClient):
    """Backend qua CLI `claude -p` (gói Pro/Max/Team hiện có — KHÔNG cần
    ANTHROPIC_API_KEY riêng, KHÔNG billing API). Shell tiến trình con, ghép
    system+prompt thành 1 prompt (`claude -p` không nhận system riêng ở đây),
    đọc `--output-format json`, trích field "result".

    `model` (alias haiku|sonnet|opus HOẶC id đầy đủ) truyền THẲNG vào `--model`
    — CLI `claude` tự nhận alias, KHÔNG cần bảng map riêng (khác AnthropicLLM).

    LÙI MƯỢT (fail_loud=False, mặc định, giống AnthropicLLM): thiếu binary/
    timeout/lỗi/is_error -> cảnh báo (1 lần) + trả "". fail_loud=True -> raise
    LLMCallError. `timeout_s` đọc từ config (llm.claude_code.timeout_s, xem
    factory.make_llm) — mặc định 120s nếu không truyền. `run_fn` tiêm được
    (mặc định subprocess.run) để test không gọi CLI thật.
    """

    def __init__(self, binary: str = "claude", timeout_s: float = 120.0, run_fn=subprocess.run):
        self.binary = binary
        self.timeout_s = timeout_s
        self._run_fn = run_fn
        self._warned = False
        self._temp_warned = False

    def _warn(self, msg: str) -> None:
        if not self._warned:
            print(f"[CẢNH BÁO] {msg} -> dùng fallback tất định ($0).")
            self._warned = True

    def _fail(self, msg: str, *, fail_loud: bool) -> str:
        if fail_loud:
            raise LLMCallError(msg)
        self._warn(msg)
        return ""

    def complete(self, system: str, prompt: str, *, model: str | None = None,
                fail_loud: bool = False, temperature: float | None = None) -> str:
        if temperature is not None and not self._temp_warned:
            print(f"[CẢNH BÁO] ClaudeCodeLLM: 'claude -p' không expose tham số sampling "
                 f"(temperature={temperature} bị BỎ QUA, no-op) — dựa vào thước đo "
                 f"(vd residual_tension) để giảm dao động thay vì tham số.")
            self._temp_warned = True
        full_prompt = f"{system}\n\n{prompt}" if system.strip() else prompt
        # shutil.which() resolve ĐÚNG file thật (vd "claude.cmd" trên Windows —
        # npm cài CLI global bằng shim .cmd/.ps1) -- subprocess.run(shell=False)
        # KHÔNG tự thử phần mở rộng PATHEXT như shell, nên bare "claude" luôn
        # FileNotFoundError trên Windows dù CLI cài đúng và có trong PATH.
        binary = shutil.which(self.binary) or self.binary
        # Prompt qua STDIN, KHÔNG qua argv (2026-07-23, xác nhận thật): claude.cmd
        # là shim .cmd -> Windows spawn qua cmd.exe, giới hạn command-line ~8KB
        # ("The command line is too long.") -- prompt bài viết thật (evidence +
        # background) vượt xa mức này. `claude -p` (không kèm query) tự đọc
        # stdin làm prompt -- CÙNG cách đã dùng khi test rules v2.1 qua CLI.
        cmd = [binary, "-p", "--output-format", "json"]
        if model:
            cmd += ["--model", model]
        try:
            proc = self._run_fn(cmd, input=full_prompt, capture_output=True, text=True,
                                encoding="utf-8", timeout=self.timeout_s)
        except FileNotFoundError:
            return self._fail(f"không thấy CLI '{self.binary}' (cài Claude Code / thêm vào PATH)",
                              fail_loud=fail_loud)
        except subprocess.TimeoutExpired:
            return self._fail(f"claude -p timeout sau {self.timeout_s:.0f}s", fail_loud=fail_loud)
        if proc.returncode != 0:
            return self._fail(f"claude -p lỗi (exit {proc.returncode}): {(proc.stderr or '')[:200]!r}",
                              fail_loud=fail_loud)
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return self._fail(f"claude -p trả JSON không hợp lệ: {proc.stdout[:200]!r}",
                              fail_loud=fail_loud)
        if data.get("is_error"):
            return self._fail(f"claude -p is_error=true: {str(data.get('result', ''))[:200]!r}",
                              fail_loud=fail_loud)
        return str(data.get("result", "")).strip()


class Agent:
    """Agent chuyên biệt = vai trò (system prompt) + một LLMClient.

    PHASE 4.11: `model` (tuỳ chọn, alias haiku|sonnet|opus) — cho phép 1 agent
    dùng model KHÁC với model mặc định của `llm` (vd InfographicSpecAgent muốn
    haiku/'Loại B rẻ' dù dùng chung LLMClient instance với agent khác). None
    (mặc định) -> hành vi CŨ y hệt, LLMClient tự dùng model mặc định của nó."""

    role: str = "agent"
    system: str = "You are a helpful assistant."
    uses_llm: bool = True   # False = tất định, 0 token
    model: str | None = None

    def __init__(self, llm: LLMClient | None = None, *, model: str | None = None):
        self.llm = llm or MockLLM()
        self.model = model

    def _ask(self, prompt: str, *, extra_system: str = "") -> str:
        sys = f"{self.role}\n{self.system}{extra_system}"
        # self.model=None (mặc định) -> gọi complete(sys, prompt) Y HỆT trước
        # Phase 4.11 (KHÔNG truyền kwarg "model" — tương thích LLMRouter/agents
        # cũ + mọi fake LLM 2 tham số trong test hiện có). CHỈ agent nào tự đặt
        # self.model (vd InfographicSpecAgent composer, Phase 4.11) mới truyền
        # thêm kwarg này.
        if self.model is not None:
            return self.llm.complete(sys, prompt, model=self.model)
        return self.llm.complete(sys, prompt)
