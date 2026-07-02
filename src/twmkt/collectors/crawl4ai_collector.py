"""Adapter Crawl4AI cho production.

Crawl4AI là async + Playwright nên KHÔNG nhúng vào process FastAPI; chạy ở
worker riêng. Import được hoãn (lazy) để demo/test offline không cần cài đặt nó.

Tham số robustness (limit, rate limit + jitter, retries, http_first, user_agent)
đọc từ settings (mục `crawl`) qua from_settings — config-first, không hard-code.

Cài đặt khi triển khai thật:
    pip install crawl4ai
    crawl4ai-setup            # tải Playwright browser
"""
from __future__ import annotations

import asyncio
import random

from ..models import RawDocument, Source
from .base import Collector


class Crawl4aiCollector(Collector):
    def __init__(
        self,
        *,
        limit: int = 10,
        http_first: bool = True,
        respect_robots: bool = True,
        rate_limit_s: float = 1.5,
        rate_limit_jitter_s: float = 0.7,
        max_retries: int = 3,
        backoff_base_s: float = 2.0,
        user_agent: str = "TurtleWealthBot/0.2",
        timeout_s: int = 30,
    ):
        self.limit = limit
        self.http_first = http_first
        self.respect_robots = respect_robots
        self.rate_limit_s = rate_limit_s
        self.rate_limit_jitter_s = rate_limit_jitter_s
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.user_agent = user_agent
        self.timeout_s = timeout_s

    @classmethod
    def from_settings(cls, settings) -> "Crawl4aiCollector":
        return cls(
            limit=int(settings.get("crawl.limit_per_source", 10)),
            http_first=bool(settings.get("crawl.http_first", True)),
            respect_robots=bool(settings.get("crawl.respect_robots", True)),
            rate_limit_s=float(settings.get("crawl.rate_limit_s", 1.5)),
            rate_limit_jitter_s=float(settings.get("crawl.rate_limit_jitter_s", 0.7)),
            max_retries=int(settings.get("crawl.max_retries", 3)),
            backoff_base_s=float(settings.get("crawl.backoff_base_s", 2.0)),
            user_agent=settings.get("crawl.user_agent", "TurtleWealthBot/0.2"),
        )

    def collect(self, source: Source, *, limit: int | None = None) -> list[RawDocument]:
        limit = self.limit if limit is None else limit
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
            result = await self._arun_with_retry(crawler, source.url)
            if result is not None and result.success:
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

    async def _arun_with_retry(self, crawler, url):  # pragma: no cover - cần mạng
        """Thử lại với exponential backoff + jitter; tôn trọng rate limit."""
        last_exc = None
        for attempt in range(self.max_retries):
            try:
                await self._sleep_rate_limit()
                return await crawler.arun(url=url)
            except Exception as e:  # noqa: BLE001 - crawl có thể lỗi mạng đủ kiểu
                last_exc = e
                await asyncio.sleep(self.backoff_base_s * (2 ** attempt))
        if last_exc is not None:
            raise last_exc
        return None

    async def _sleep_rate_limit(self):  # pragma: no cover - cần mạng
        jitter = random.uniform(0, self.rate_limit_jitter_s)
        await asyncio.sleep(self.rate_limit_s + jitter)
