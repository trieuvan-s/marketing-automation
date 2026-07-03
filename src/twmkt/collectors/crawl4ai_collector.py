"""Adapter Crawl4AI cho production.

Crawl4AI import được hoãn (lazy) để demo/test offline không cần cài đặt nó.

Cài đặt khi triển khai thật:
    pip install crawl4ai
    crawl4ai-setup            # tải Playwright browser (dự phòng, xem ghi chú dưới)

CafeF render HTML sẵn ở server (không cần JS để có nội dung bài) nên ta dùng
`AsyncHTTPCrawlerStrategy` của crawl4ai — fetch HTTP thuần (aiohttp), KHÔNG mở
Playwright/Chromium. Việc này vừa nhanh hơn nhiều lần vừa né được hẳn lớp lỗi
renderer headless không ổn định (đã thấy trên máy Windows dùng để phát triển:
Chromium crash ngẫu nhiên khi crawl nhiều bài liên tiếp). Nếu sau này có nguồn
cần JS để render nội dung, đổi strategy này sang AsyncPlaywrightCrawlerStrategy
cho riêng nguồn đó — không ảnh hưởng các nguồn HTTP-only khác.

Luồng collect(): crawl trang chuyên mục (source.url) -> tìm link bài khớp
`article_link_pattern` (chỉ xét link nội bộ cùng domain, tự loại link
mục/quảng cáo/ngoại miền) -> crawl đồng thời từng bài bằng `arun_many` (giới
hạn 1 request/lần + nghỉ `rate_limit_s` giây, dùng SemaphoreDispatcher +
RateLimiter của crawl4ai) -> trả RawDocument (markdown đã cắt gọn theo
`content_css_selector`, bỏ box liên quan/quảng cáo theo `excluded_selector`).

Tôn trọng robots.txt qua cơ chế `check_robots_txt` sẵn có của crawl4ai — bài
nào bị chặn sẽ có `success=False, status_code=403`, ta in cảnh báo rõ và bỏ
qua thay vì crawl chui. Bài lỗi vì lý do khác (timeout/mạng — sự cố tạm thời)
được thử lại đúng 1 lần.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from ..models import RawDocument, Source
from .base import Collector

# Fallback nếu không truyền pattern riêng: link có phần đuôi nhiều chữ số
# (id bài viết) trước phần mở rộng .chn/.html — khác link trang mục.
_DEFAULT_ARTICLE_RE = re.compile(r"/[a-z0-9-]+-\d{10,}\.(?:chn|html?)$")

# Selector thân bài CafeF (soi từ 1 bài mẫu: div.detail-content.afcbc-body),
# loại bỏ box "TIN MỚI" nhúng trong thân bài (#listNewsInContent).
_CAFEF_CONTENT_SELECTOR = "div.detail-content.afcbc-body"
_CAFEF_EXCLUDED_SELECTOR = "#listNewsInContent"

# User-Agent mô tả rõ danh tính bot, tôn trọng lịch sự với server nguồn.
# ASCII-only: header HTTP không chấp nhận giá trị ngoài ASCII/latin-1.
_USER_AGENT = (
    "TurtleWealthMktBot/0.1 (+marketing automation noi bo, thu thap tin tai "
    "chinh VN; lien he: trieuvanstock@gmail.com)"
)


class Crawl4aiCollector(Collector):
    def __init__(
        self,
        *,
        article_link_pattern: re.Pattern[str] = _DEFAULT_ARTICLE_RE,
        content_css_selector: str = _CAFEF_CONTENT_SELECTOR,
        excluded_selector: str = _CAFEF_EXCLUDED_SELECTOR,
        rate_limit_s: float = 1.5,
        respect_robots: bool = True,
        timeout_s: int = 30,
    ):
        self.article_link_pattern = article_link_pattern
        self.content_css_selector = content_css_selector
        self.excluded_selector = excluded_selector
        self.rate_limit_s = rate_limit_s
        self.respect_robots = respect_robots
        self.timeout_s = timeout_s

    @classmethod
    def from_settings(cls, settings) -> "Crawl4aiCollector":
        """Dựng từ config/settings.yaml (config-first). Crawl4AI dùng 1 bộ selector
        chung cho mọi nguồn nên lấy từ crawl.* (mặc định = selector CafeF)."""
        pattern = settings.get("crawl.article_url_pattern")
        content = settings.get("crawl.body_selector") or _CAFEF_CONTENT_SELECTOR
        return cls(
            article_link_pattern=re.compile(pattern) if pattern else _DEFAULT_ARTICLE_RE,
            content_css_selector=content,
            excluded_selector=settings.get("crawl.excluded_selector", _CAFEF_EXCLUDED_SELECTOR),
            rate_limit_s=float(settings.get("crawl.rate_limit_s", 1.5)),
            respect_robots=bool(settings.get("crawl.respect_robots", True)),
            timeout_s=int(settings.get("crawl.timeout_s", 30)),
        )

    def collect(self, source: Source, *, limit: int = 10) -> list[RawDocument]:
        import asyncio

        return asyncio.run(self._collect_async(source, limit))

    async def _collect_async(self, source: Source, limit: int) -> list[RawDocument]:
        try:
            from crawl4ai import (  # noqa: F401
                AsyncWebCrawler,
                BrowserConfig,
                CrawlerRunConfig,
                HTTPCrawlerConfig,
                RateLimiter,
                SemaphoreDispatcher,
            )
            from crawl4ai.async_crawler_strategy import AsyncHTTPCrawlerStrategy
        except ImportError as e:  # pragma: no cover - phụ thuộc tùy chọn
            raise RuntimeError(
                "Chưa cài crawl4ai. Chạy: pip install crawl4ai && crawl4ai-setup"
            ) from e

        # config= chỉ dùng để robots.txt-checker biết User-Agent xưng danh gì;
        # việc fetch thật sự đi qua AsyncHTTPCrawlerStrategy (không mở trình duyệt).
        browser_cfg = BrowserConfig(user_agent=_USER_AGENT)
        http_strategy = AsyncHTTPCrawlerStrategy(
            browser_config=HTTPCrawlerConfig(headers={"User-Agent": _USER_AGENT})
        )

        timeout_ms = self.timeout_s * 1000
        listing_cfg = CrawlerRunConfig(
            check_robots_txt=self.respect_robots, page_timeout=timeout_ms,
        )
        article_cfg = CrawlerRunConfig(
            check_robots_txt=self.respect_robots,
            css_selector=self.content_css_selector,
            excluded_selector=self.excluded_selector,
            page_timeout=timeout_ms,
        )

        docs: list[RawDocument] = []
        async with AsyncWebCrawler(crawler_strategy=http_strategy, config=browser_cfg) as crawler:
            listing = await crawler.arun(url=source.url, config=listing_cfg)
            if not listing.success:
                if listing.status_code == 403:
                    print(f"[CẢNH BÁO] robots.txt chặn crawl trang mục: {source.url}")
                else:
                    print(f"[CẢNH BÁO] Không crawl được trang mục: {source.url} "
                          f"({listing.error_message})")
                return []

            article_urls = self._extract_article_links(listing, source.url)[:limit]
            if not article_urls:
                return []

            dispatcher = SemaphoreDispatcher(
                semaphore_count=1,
                rate_limiter=RateLimiter(
                    base_delay=(self.rate_limit_s, self.rate_limit_s),
                    max_delay=self.rate_limit_s * 4,
                ),
            )
            results = await crawler.arun_many(
                urls=article_urls, config=article_cfg, dispatcher=dispatcher
            )

            docs, retry_urls = self._collect_results(results, source)

            # Lỗi mạng/timeout thoáng qua -> thử lại 1 lần cho các URL đó.
            if retry_urls:
                retry_results = await crawler.arun_many(
                    urls=retry_urls, config=article_cfg, dispatcher=dispatcher
                )
                retry_docs, _ = self._collect_results(retry_results, source)
                docs.extend(retry_docs)
        return docs

    def _collect_results(
        self, results, source: Source
    ) -> tuple[list[RawDocument], list[str]]:
        docs: list[RawDocument] = []
        retry_urls: list[str] = []
        for result in results:
            if not result.success:
                if result.status_code == 403:
                    print(f"[CẢNH BÁO] robots.txt chặn crawl bài: {result.url}")
                else:
                    retry_urls.append(result.url)
                continue
            if not (result.markdown or "").strip():
                continue
            title = (result.metadata or {}).get("title") or source.name
            docs.append(
                RawDocument(
                    source=source.name,
                    url=result.url,
                    title=title,
                    markdown=str(result.markdown),
                    source_type=source.source_type,
                )
            )
        return docs, retry_urls

    def _extract_article_links(self, listing_result, base_url: str) -> list[str]:
        """Chỉ xét link nội bộ (internal) — crawl4ai đã tự loại link ngoại miền
        (quảng cáo/đối tác) khỏi danh sách này."""
        seen: set[str] = set()
        links: list[str] = []
        internal = (listing_result.links or {}).get("internal", [])
        for link in internal:
            href = (link or {}).get("href")
            if not href:
                continue
            full = urljoin(base_url, href)
            path = urlparse(full).path
            if self.article_link_pattern.search(path) and full not in seen:
                seen.add(full)
                links.append(full)
        return links
