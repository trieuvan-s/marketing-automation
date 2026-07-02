"""FileDocumentStore — lưu CleanDocument ra đĩa (storage/documents/*.json).

Thực hiện đúng protocol DocumentStore (upsert/all) nên thay InMemoryStore 1-1.
Hiện thực hóa yêu cầu 'lưu trữ': Documents được persist, audit được, và các lần
crawl sau dedup được ACROSS-RUN theo url (không lưu lại bài đã có).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from ..models import CleanDocument, SourceType


class FileDocumentStore:
    def __init__(self, root: str = "storage/documents"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, url: str) -> Path:
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        return self.root / f"{key}.json"

    def upsert(self, docs: list[CleanDocument]) -> int:
        new = 0
        for d in docs:
            p = self._path(d.url)
            if not p.exists():
                new += 1
            p.write_text(
                json.dumps(_ser(d), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return new

    def all(self) -> list[CleanDocument]:
        return [
            _de(json.loads(f.read_text(encoding="utf-8")))
            for f in sorted(self.root.glob("*.json"))
        ]


def _ser(d: CleanDocument) -> dict:
    st = d.source_type.value if hasattr(d.source_type, "value") else str(d.source_type)
    at = d.fetched_at.isoformat() if hasattr(d.fetched_at, "isoformat") else str(d.fetched_at)
    return {
        "source": d.source, "url": d.url, "title": d.title, "markdown": d.markdown,
        "tickers": list(d.tickers), "tags": list(d.tags),
        "source_type": st, "fetched_at": at,
    }


def _de(r: dict) -> CleanDocument:
    return CleanDocument(
        source=r["source"], url=r["url"], title=r["title"], markdown=r["markdown"],
        tickers=r.get("tickers", []), tags=r.get("tags", []),
        source_type=SourceType(r.get("source_type", "news")),
        fetched_at=datetime.fromisoformat(r["fetched_at"]),
    )
