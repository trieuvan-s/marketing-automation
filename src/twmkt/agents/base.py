"""Lớp LLM trừu tượng + Agent base.

Nguyên tắc: LLM chỉ sinh NGÔN NGỮ (diễn giải, văn phong). Mọi CON SỐ phải đến
từ ervn (tất định). MockLLM cho phép chạy offline, AnthropicLLM cho production.
"""
from __future__ import annotations

import os
from typing import Protocol


class LLMClient(Protocol):
    def complete(self, system: str, prompt: str) -> str: ...


class MockLLM(LLMClient):
    """Trả lời tất định, không gọi mạng. Dùng cho demo/test."""

    def complete(self, system: str, prompt: str) -> str:
        role = system.strip().splitlines()[0] if system.strip() else "agent"
        head = prompt.strip().splitlines()[0][:80] if prompt.strip() else ""
        return f"[MOCK::{role}] {head}"


class AnthropicLLM(LLMClient):
    """Production: gọi Claude. Import hoãn để offline không cần SDK/khóa API.

    LÙI MƯỢT: nếu thiếu SDK/khóa API hoặc call lỗi -> in cảnh báo (1 lần) rồi TRẢ
    RỖNG, KHÔNG raise. Agent nhận chuỗi rỗng sẽ tự dùng fallback tất định ($0),
    nên pipeline không bao giờ crash vì LLM.
    """

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

    def complete(self, system: str, prompt: str) -> str:
        ok, why = self.is_available()
        if not ok:
            self._warn(f"AnthropicLLM không dùng được ({why})")
            return ""                       # LÙI MƯỢT: KHÔNG raise
        try:
            import anthropic
            client = anthropic.Anthropic()
            msg = client.messages.create(
                model=self.model, max_tokens=self.max_tokens,
                system=system, messages=[{"role": "user", "content": prompt}],
            )
            return "".join(b.text for b in msg.content if b.type == "text")
        except Exception as e:              # auth/mạng/quota... -> lùi mượt
            self._warn(f"Gọi Anthropic lỗi ({e!r})")
            return ""


class Agent:
    """Agent chuyên biệt = vai trò (system prompt) + một LLMClient."""

    role: str = "agent"
    system: str = "You are a helpful assistant."
    uses_llm: bool = True   # False = tất định, 0 token

    def __init__(self, llm: LLMClient | None = None):
        self.llm = llm or MockLLM()

    def _ask(self, prompt: str, *, extra_system: str = "") -> str:
        sys = f"{self.role}\n{self.system}{extra_system}"
        return self.llm.complete(sys, prompt)
