"""Triage tất định: chấm điểm liên quan để chỉ đẩy top-K doc vào LLM.

Không gọi LLM ở đây — đây chính là tầng tiết kiệm token lớn nhất: thay vì nhồi
mọi tài liệu vào prompt, ta lọc trước bằng tín hiệu rẻ tiền (trùng mã, từ khóa,
tag, nguồn uy tín).
"""
from __future__ import annotations

import re

from .curation.normalize import extract_tickers
from .models import CleanDocument

# Trọng số độ tin cậy/ưu tiên theo nguồn (tùy chỉnh).
SOURCE_WEIGHT = {
    "HOSE": 4, "HNX": 4, "NHNN": 4, "SBV": 4,
    "Vietstock": 3, "CafeF": 2, "NDH": 2,
}

_WORD = re.compile(r"\w+", re.UNICODE)


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def score(doc: CleanDocument, topic: str, topic_tickers: list[str]) -> int:
    s = 0
    for t in doc.tickers:
        if t in topic_tickers:
            s += 5
    s += len(_words(topic) & _words(f"{doc.title} {doc.markdown}"))
    s += len(doc.tags)
    s += SOURCE_WEIGHT.get(doc.source, 1)
    return s


def rank(docs: list[CleanDocument], topic: str) -> list[tuple[CleanDocument, int]]:
    topic_tickers = extract_tickers(topic)
    scored = [(d, score(d, topic, topic_tickers)) for d in docs]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def select(docs: list[CleanDocument], topic: str, *, top_k: int = 5,
           min_score: int = 1) -> list[CleanDocument]:
    ranked = rank(docs, topic)
    return [d for d, sc in ranked if sc >= min_score][:top_k]
