"""Knowledge Layer — RAG tối giản, chạy offline & miễn phí.

Tất cả ở đây là Tầng 0-1 (free/rẻ): chunk tất định, embed cục bộ, vector search
thuần stdlib. KHÔNG gọi LLM. Production chỉ cần thay:
  - HashingEmbedder -> sentence-transformers (local, multilingual/Vietnamese) => vẫn $0 token
  - InMemoryVectorStore -> Qdrant (theo notes)
Giao diện giữ nguyên nên phần còn lại không đổi.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Protocol

from ..models import CleanDocument


# ---- Tầng 0: chunk tất định ------------------------------------------------
def chunk_text(text: str, *, size: int = 500, overlap: int = 80) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks, start = [], 0
    step = max(1, size - overlap)
    while start < len(words):
        chunks.append(" ".join(words[start : start + size]))
        start += step
    return chunks


@dataclass
class Chunk:
    text: str
    source: str
    url: str
    title: str
    tickers: list[str] = field(default_factory=list)
    vec: list[float] = field(default_factory=list)


# ---- Tầng 1: embedding (cục bộ, free) --------------------------------------
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder(Embedder):
    """Embed tất định bằng hashing bag-of-words. Không cần model/mạng.

    Đủ dùng cho demo/test. Production: đổi sang SentenceTransformer local để
    chất lượng ngữ nghĩa tốt hơn (vẫn không tốn token API).
    """

    _tok = re.compile(r"\w+", re.UNICODE)

    def __init__(self, dim: int = 256):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for tok in self._tok.findall(t.lower()):
                v[hash(tok) % self.dim] += 1.0
            out.append(_l2(v))
        return out


def _l2(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


# ---- Tầng 0: vector store --------------------------------------------------
class VectorStore(Protocol):
    def add(self, chunks: list[Chunk]) -> None: ...
    def search(self, qvec: list[float], k: int) -> list[tuple[float, Chunk]]: ...


class InMemoryVectorStore(VectorStore):
    def __init__(self) -> None:
        self._chunks: list[Chunk] = []

    def add(self, chunks: list[Chunk]) -> None:
        self._chunks.extend(chunks)

    def search(self, qvec: list[float], k: int) -> list[tuple[float, Chunk]]:
        scored = [(_cos(qvec, c.vec), c) for c in self._chunks if c.vec]
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:k]


# ---- Retriever: gói chunk + embed + store ----------------------------------
class Retriever:
    def __init__(self, embedder: Embedder | None = None, store: VectorStore | None = None):
        self.embedder = embedder or HashingEmbedder()
        self.store = store or InMemoryVectorStore()

    def index(self, docs: list[CleanDocument], *, size: int = 500) -> int:
        chunks: list[Chunk] = []
        for d in docs:
            for piece in chunk_text(f"{d.title}. {d.markdown}", size=size):
                chunks.append(
                    Chunk(text=piece, source=d.source, url=d.url,
                          title=d.title, tickers=d.tickers)
                )
        if chunks:
            for c, v in zip(chunks, self.embedder.embed([c.text for c in chunks])):
                c.vec = v
            self.store.add(chunks)
        return len(chunks)

    def retrieve(self, query: str, k: int = 5) -> list[Chunk]:
        qvec = self.embedder.embed([query])[0]
        return [c for _, c in self.store.search(qvec, k)]
