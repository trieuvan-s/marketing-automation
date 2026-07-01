"""Adapter Crawl4AI cho production.

Crawl4AI là async + Playwright nên KHÔNG nhúng vào process FastAPI; chạy ở
worker riêng. Import được hoãn (lazy) để demo/test offline không cần cài đặt nó.

Cài đặt khi triển khai thật:
    pip install crawl4ai
    crawl4ai-setup            # tải Playwright browser
"""
from __future__ import annotations

import asyncio

from ..models import RawDocument, Source
from .base import Collector


class Crawl4aiCollector(Collector):
    def __init__(self, *, respect_robots: bool = True, timeout_s: int = 30):
        self.respect_robots = respect_robots
        self.timeout_s = timeout_s

    def collect(self, source: Source, *, limit: int = 10) -> list[RawDocument]:
        return asyncio.run(self._collect_async(source, limit))

    async def _collect_async(self, source: Source, limit: int) -> list[RawDocument]:
        try:
            from crawl4ai import AsyncWebCrawler  # noqa: F401
        except ImportError as e:  # pragma: no cover - phụ thuộc tùy chọn
            raise RuntimeError(
                "Chưa cài crawl4ai. Chạy: pip install crawl4ai && crawl4ai-setup"
            ) from e

        from crawl4ai import AsyncWebCrawler

        docs: list[RawDocument] = []
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=source.url)
            if result.success:
                docs.append(
                    RawDocument(
                        source=source.name,
                        url=source.url,
                        title=(result.metadata or {}).get("title", source.name),
                        markdown=result.markdown or "",
                        source_type=source.source_type,
                    )
                )
        return docs[:limit]
