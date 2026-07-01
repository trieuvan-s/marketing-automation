"""Adapter pattern cho nguồn crawl — giống provider pattern trong ervn."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import RawDocument, Source


@runtime_checkable
class Collector(Protocol):
    """Mọi nguồn thu thập phải tuân thủ giao diện này, nên dễ thay 1-1."""

    def collect(self, source: Source, *, limit: int = 10) -> list[RawDocument]:
        ...
