"""Lớp LLM trừu tượng + Agent base.

Nguyên tắc: LLM chỉ sinh NGÔN NGỮ (diễn giải, văn phong). Mọi CON SỐ phải đến
từ ervn (tất định). MockLLM cho phép chạy offline, AnthropicLLM cho production.
"""
from __future__ import annotations

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
    """Production: gọi Claude. Import hoãn để offline không cần SDK/khóa API."""

    def __init__(self, model: str = "claude-sonnet-4-6", max_tokens: int = 1500):
        self.model = model
        self.max_tokens = max_tokens

    def complete(self, system: str, prompt: str) -> str:
        try:
            import anthropic  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("pip install anthropic để dùng AnthropicLLM") from e
        import anthropic

        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in msg.content if b.type == "text")


class Agent:
    """Agent chuyên biệt = vai trò (system prompt) + một LLMClient."""

    role: str = "agent"
    system: str = "You are a helpful assistant."
    uses_llm: bool = True   # False = tất định, 0 token

    def __init__(self, llm: LLMClient | None = None):
        self.llm = llm or MockLLM()

    def _ask(self, prompt: str) -> str:
        sys = f"{self.role}\n{self.system}"
        return self.llm.complete(sys, prompt)
