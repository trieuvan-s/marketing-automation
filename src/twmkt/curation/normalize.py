"""Chuẩn hóa tất định: dedup, trích mã cổ phiếu, gắn tag. Không LLM ở đây."""
from __future__ import annotations

import re

from ..models import CleanDocument, RawDocument

# Mã cổ phiếu VN: 3 ký tự in hoa. Lọc bớt từ viết hoa thông dụng không phải mã.
_TICKER_RE = re.compile(r"\b([A-Z]{3})\b")
_NON_TICKER = {
    "CNT", "CNG", "CEO", "USD", "VND", "GDP", "CPI", "EPS", "ROE", "ROA",
    "BCT", "NDH", "TIN", "VNĐ", "FDI", "API", "SaaS",
}

_TAG_RULES = {
    "kết quả kinh doanh": "earnings",
    "lợi nhuận": "earnings",
    "doanh thu": "earnings",
    "cổ tức": "dividend",
    "sản lượng": "operations",
    "biên lợi nhuận": "margins",
}


def extract_tickers(text: str) -> list[str]:
    found = [t for t in _TICKER_RE.findall(text) if t not in _NON_TICKER]
    # giữ thứ tự, bỏ trùng
    seen: dict[str, None] = {}
    for t in found:
        seen.setdefault(t, None)
    return list(seen)


def derive_tags(text: str) -> list[str]:
    low = text.lower()
    tags: list[str] = []
    for kw, tag in _TAG_RULES.items():
        if kw in low and tag not in tags:
            tags.append(tag)
    return tags


def normalize(raw_docs: list[RawDocument]) -> list[CleanDocument]:
    """Dedup theo content_hash rồi làm giàu metadata."""
    seen_hashes: set[str] = set()
    clean: list[CleanDocument] = []
    for d in raw_docs:
        h = d.content_hash
        if h in seen_hashes:
            continue
        seen_hashes.add(h)
        full = f"{d.title}. {d.markdown}"
        clean.append(
            CleanDocument(
                source=d.source,
                url=d.url,
                title=d.title.strip(),
                markdown=" ".join(d.markdown.split()),
                tickers=extract_tickers(full),
                tags=derive_tags(full),
                source_type=d.source_type,
                fetched_at=d.fetched_at,
            )
        )
    return clean
