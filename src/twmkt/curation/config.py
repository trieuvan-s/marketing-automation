"""Cấu hình chuẩn hóa (config-first) — nạp từ settings + các file dữ liệu.

Nguyên tắc: các tham số lọc (whitelist mã, mã dễ nhầm, từ khóa vĩ mô, cửa sổ ngữ
cảnh, ngưỡng liên quan) KHÔNG hard-code trong code mà đọc từ config/settings.yaml
và các file trong data/. Toàn bộ tất định, $0 token.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # tránh phụ thuộc vòng khi type-check
    from ..config import Settings


def _load_lines(path: str | None) -> list[str]:
    """Đọc file danh sách (mỗi dòng 1 mục), bỏ dòng trống & comment. UTF-8."""
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        return []
    out: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


@dataclass
class CurationConfig:
    """Tham số cho bước chuẩn hóa/lọc tất định.

    - `tickers` rỗng => extract_tickers dùng chế độ regex + blocklist (tương thích
      ngược). Khi có whitelist => chỉ giữ mã nằm trong whitelist.
    - `ambiguous` = mã vừa là mã CK vừa là từ thường (vd GAS/BID); chỉ tính là mã
      khi quanh nó (trong `ambiguous_context_window` ký tự) có tín hiệu ngữ cảnh CK.
    - `macro_keywords` + `min_macro_keywords` = giữ bài vĩ mô (0 mã) khi đủ từ khóa.
    """

    tickers: set[str] = field(default_factory=set)
    ambiguous: set[str] = field(default_factory=set)
    macro_keywords: list[str] = field(default_factory=list)
    ambiguous_context_window: int = 40
    min_macro_keywords: int = 2

    @classmethod
    def from_settings(cls, settings: "Settings") -> "CurationConfig":
        tickers_file = settings.get("curation.tickers_file", "data/tickers.txt")
        ambiguous_file = settings.get("curation.ambiguous_file", "data/tickers_ambiguous.txt")
        keywords_file = settings.get(
            "curation.relevance.keywords_file", "data/keywords_macro.txt"
        )
        return cls(
            tickers={t.upper() for t in _load_lines(tickers_file)},
            ambiguous={t.upper() for t in _load_lines(ambiguous_file)},
            macro_keywords=[k.lower() for k in _load_lines(keywords_file)],
            ambiguous_context_window=int(settings.get("curation.ambiguous_context_window", 40)),
            min_macro_keywords=int(settings.get("curation.relevance.min_macro_keywords", 2)),
        )

    def macro_hits(self, text: str) -> int:
        """Số từ khóa vĩ mô (phân biệt) xuất hiện trong text."""
        low = text.lower()
        return sum(1 for kw in self.macro_keywords if kw in low)
