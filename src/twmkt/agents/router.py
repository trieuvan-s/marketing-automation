"""LLMRouter — chốt kiểm soát chi phí token.

Bọc một LLMClient và thêm: chọn model rẻ mặc định (escalate khi cần), đo đếm
token/chi phí, cache output, và hạn mức ngân sách cứng. Vì nó cũng tuân thủ
giao diện LLMClient (complete(system, prompt)), mọi Agent dùng được trong suốt.

Lưu ý: bảng giá dưới đây là PLACEHOLDER — cập nhật theo bảng giá chính thức của
nhà cung cấp. Ước lượng token ở chế độ mock dùng heuristic ~4 ký tự/token;
production nên đọc usage thật từ phản hồi API.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum

from .base import LLMClient, MockLLM


class Tier(str, Enum):
    CHEAP = "cheap"   # việc thường: phân loại, brief, caption
    SMART = "smart"   # bài flagship, phân tích phức tạp


# model gắn với mỗi tier (đổi tên model theo nhu cầu)
TIER_MODEL = {
    Tier.CHEAP: "claude-haiku-4-5",
    Tier.SMART: "claude-sonnet-4-6",
}

# USD trên 1 triệu token (input, output) — PLACEHOLDER, cập nhật từ trang giá.
PRICE_PER_MTOK = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
}


class BudgetExceeded(RuntimeError):
    pass


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass
class Usage:
    calls: int = 0
    cache_hits: int = 0
    in_tokens: int = 0
    out_tokens: int = 0
    cost_usd: float = 0.0
    by_model: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "calls": self.calls,
            "cache_hits": self.cache_hits,
            "in_tokens": self.in_tokens,
            "out_tokens": self.out_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "by_model": dict(self.by_model),
        }


class LLMRouter(LLMClient):
    def __init__(
        self,
        base: LLMClient | None = None,
        *,
        default_tier: Tier = Tier.CHEAP,
        budget_usd: float | None = None,
        cache: bool = True,
    ):
        self.base = base or MockLLM()
        self.default_tier = default_tier
        self.budget_usd = budget_usd
        self.usage = Usage()
        self._cache: dict[str, str] = {} if cache else None

    def _model_for(self, tier: Tier | None) -> str:
        return TIER_MODEL[tier or self.default_tier]

    @staticmethod
    def _key(model: str, system: str, prompt: str) -> str:
        return hashlib.sha256(f"{model}\x00{system}\x00{prompt}".encode()).hexdigest()

    def complete(self, system: str, prompt: str, *, tier: Tier | None = None) -> str:
        model = self._model_for(tier)

        if self._cache is not None:
            k = self._key(model, system, prompt)
            if k in self._cache:
                self.usage.cache_hits += 1
                return self._cache[k]

        out = self.base.complete(system, prompt)

        in_tok = estimate_tokens(system + prompt)
        out_tok = estimate_tokens(out)
        p_in, p_out = PRICE_PER_MTOK.get(model, (0.0, 0.0))
        cost = (in_tok * p_in + out_tok * p_out) / 1_000_000

        if self.budget_usd is not None and self.usage.cost_usd + cost > self.budget_usd:
            raise BudgetExceeded(
                f"Vượt ngân sách: đã {self.usage.cost_usd:.4f}$ + {cost:.4f}$ "
                f"> {self.budget_usd:.4f}$"
            )

        self.usage.calls += 1
        self.usage.in_tokens += in_tok
        self.usage.out_tokens += out_tok
        self.usage.cost_usd += cost
        self.usage.by_model[model] = self.usage.by_model.get(model, 0) + 1

        if self._cache is not None:
            self._cache[k] = out
        return out
