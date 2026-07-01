"""Lưu trữ tài liệu sạch. Bản này in-memory; production thay bằng Postgres.

Giữ nguyên giao diện -> đổi backend không ảnh hưởng phần còn lại của pipeline.
"""
from __future__ import annotations

from typing import Protocol

from ..models import CleanDocument


class DocumentStore(Protocol):
    def upsert(self, docs: list[CleanDocument]) -> int: ...
    def all(self) -> list[CleanDocument]: ...


class InMemoryStore(DocumentStore):
    def __init__(self) -> None:
        self._by_url: dict[str, CleanDocument] = {}

    def upsert(self, docs: list[CleanDocument]) -> int:
        n = 0
        for d in docs:
            if d.url not in self._by_url:
                n += 1
            self._by_url[d.url] = d
        return n

    def all(self) -> list[CleanDocument]:
        return list(self._by_url.values())
