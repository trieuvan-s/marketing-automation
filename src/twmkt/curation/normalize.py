"""Chuẩn hóa tất định: dedup, trích mã cổ phiếu, gắn tag. Không LLM ở đây.

Nhận `CurationConfig` (config-first): khi có whitelist mã thì lọc theo whitelist +
xử lý mã dễ nhầm theo ngữ cảnh, và lọc bài không liên quan theo từ khóa vĩ mô. Khi
không truyền config -> giữ nguyên hành vi cũ (regex + blocklist), không lọc bài.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ..models import CleanDocument, RawDocument

if TYPE_CHECKING:
    from .config import CurationConfig

# Mã cổ phiếu VN: 3 ký tự in hoa. Lọc bớt từ viết hoa thông dụng không phải mã.
_TICKER_RE = re.compile(r"\b([A-Z]{3})\b")

# Tín hiệu cho biết một mã "dễ nhầm" (vd GAS) đang được dùng như mã CK.
_TICKER_CONTEXT_MARKERS = ("cổ phiếu", "mã ", "(", ")", "hose", "hnx", "upcom")
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


def extract_tickers(text: str, config: "CurationConfig | None" = None) -> list[str]:
    """Trích mã CK từ text.

    - Có whitelist (config.tickers) -> chỉ giữ mã trong whitelist; mã dễ nhầm phải
      có ngữ cảnh CK quanh nó.
    - Không có config/whitelist -> regex + blocklist (tương thích ngược).
    """
    if config is not None and config.tickers:
        return _extract_whitelist(text, config)
    found = [t for t in _TICKER_RE.findall(text) if t not in _NON_TICKER]
    # giữ thứ tự, bỏ trùng
    seen: dict[str, None] = {}
    for t in found:
        seen.setdefault(t, None)
    return list(seen)


def _extract_whitelist(text: str, config: "CurationConfig") -> list[str]:
    win = config.ambiguous_context_window
    low = text.lower()
    result: list[str] = []
    for m in _TICKER_RE.finditer(text):
        tok = m.group(1)
        if tok not in config.tickers:
            continue
        if tok in config.ambiguous:
            lo, hi = max(0, m.start() - win), min(len(text), m.end() + win)
            if not _has_ticker_context(text[lo:hi], low[lo:hi], config, exclude=tok):
                continue
        if tok not in result:
            result.append(tok)
    return result


def _has_ticker_context(ctx_raw: str, ctx_low: str, config: "CurationConfig",
                        *, exclude: str) -> bool:
    if any(mk in ctx_low for mk in _TICKER_CONTEXT_MARKERS):
        return True
    # Có mã CK XÁC ĐỊNH (không phải mã dễ nhầm) đứng gần -> đang liệt kê mã CK.
    # Chỉ tính mã non-ambiguous để 2 token dễ nhầm (vd USD ~ HCM trong "tỷ USD cho
    # TP.HCM") KHÔNG tự xác nhận lẫn nhau -> tránh dương tính giả.
    for other in _TICKER_RE.findall(ctx_raw):
        if other != exclude and other in config.tickers and other not in config.ambiguous:
            return True
    return False


def is_relevant(text: str, tickers: list[str], config: "CurationConfig") -> bool:
    """Bài liên quan khi có ít nhất 1 mã, hoặc đủ từ khóa vĩ mô (bài macro)."""
    if tickers:
        return True
    return config.macro_hits(text) >= config.min_macro_keywords


def derive_tags(text: str) -> list[str]:
    low = text.lower()
    tags: list[str] = []
    for kw, tag in _TAG_RULES.items():
        if kw in low and tag not in tags:
            tags.append(tag)
    return tags


def normalize(raw_docs: list[RawDocument],
              config: "CurationConfig | None" = None) -> list[CleanDocument]:
    """Dedup theo content_hash rồi làm giàu metadata.

    Khi truyền `config`: dùng whitelist mã và LỌC bỏ bài không liên quan
    (0 mã và không đủ từ khóa vĩ mô). Không truyền config -> không lọc (cũ).
    """
    seen_hashes: set[str] = set()
    clean: list[CleanDocument] = []
    for d in raw_docs:
        h = d.content_hash
        if h in seen_hashes:
            continue
        seen_hashes.add(h)
        full = f"{d.title}. {d.markdown}"
        tickers = extract_tickers(full, config)
        if config is not None and not is_relevant(full, tickers, config):
            continue
        clean.append(
            CleanDocument(
                source=d.source,
                url=d.url,
                title=d.title.strip(),
                markdown=" ".join(d.markdown.split()),
                tickers=tickers,
                tags=derive_tags(full),
                source_type=d.source_type,
                fetched_at=d.fetched_at,
            )
        )
    return clean
