"""Collector HTTP-first: httpx + BeautifulSoup(html.parser) — $0 token, thuần Python.

CafeF render HTML sẵn ở server (nội dung bài có ngay trong HTML, không cần JS),
nên chỉ cần fetch HTTP tĩnh + parse DOM. KHÔNG cần crawl4ai / lxml / Playwright.
Nếu về sau gặp nguồn buộc chạy JS mới có nội dung -> đổi engine sang "crawl4ai"
(Crawl4aiCollector) cho riêng nguồn đó; lõi không đổi.

Luồng collect(): fetch trang chuyên mục (source.url) -> `extract_links` lấy link
bài khớp `article_url_pattern` (chỉ link nội miền, tự loại link mục/ads/ngoại
miền) -> lần lượt fetch từng bài (rate-limit + jitter cho lịch sự) ->
`extract_article` trích tiêu đề (`title_selector`, thường h1) + thân bài
(`body_selector`, vd '.detail-content'), loại các box nhiễu ("TIN MỚI"/ads theo
`noise_selectors`) -> RawDocument.

Config-first: TẤT CẢ selector & pattern đọc từ settings (không hard-code trong
lõi). `from_settings` dựng 1 `SourceSpec` cho mỗi source (khóa theo url).

Robots.txt: tôn trọng qua urllib.robotparser khi `respect_robots=True`; URL bị
chặn -> in cảnh báo & bỏ qua (không crawl chui). Lỗi mạng/5xx thoáng qua ->
thử lại với backoff.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from ..models import RawDocument, Source, SourceType
from .base import Collector

# --- Mặc định (chỉ dùng khi settings không cung cấp) -------------------------
_DEFAULT_ARTICLE_PATTERN = r"-\d{6,}\.chn$"
_DEFAULT_TITLE_SELECTOR = "h1"
_DEFAULT_BODY_SELECTOR = "div.detail-content.afcbc-body"
# Box nhiễu nhúng trong thân bài CafeF: "TIN MỚI" + widget xem trước ảnh/box.
_DEFAULT_NOISE_SELECTORS = (
    "#listNewsInContent",
    ".VCSortableInPreviewMode",
    "script",
    "style",
)
# Box mã CK CafeF (ẩn, JS bơm giá): text dạng "VHM: Giá hiện tại...". Đây là
# metadata mã liên quan do CafeF gắn — ta TRÍCH mã rồi mới loại phần chrome giá.
_DEFAULT_TICKER_BOX_SELECTOR = ".chisochungkhoan"
_TICKER_BOX_CODE_RE = re.compile(r"^\s*([A-Z0-9]{3})\s*:")
# ASCII-only: header HTTP (httpx/urllib) không chấp nhận giá trị ngoài
# ASCII/latin-1 -> dấu tiếng Việt trong User-Agent sẽ crash lúc dựng client.
_DEFAULT_USER_AGENT = (
    "TurtleWealthMktBot/0.2 (+marketing automation noi bo, thu thap tin tai "
    "chinh VN; lien he: trieuvanstock@gmail.com)"
)


@dataclass(frozen=True)
class SourceSpec:
    """Cấu hình bóc tách cho 1 nguồn (config-first, không hard-code trong lõi)."""

    article_url_re: re.Pattern[str]
    title_selector: str = _DEFAULT_TITLE_SELECTOR
    body_selector: str = _DEFAULT_BODY_SELECTOR
    noise_selectors: tuple[str, ...] = _DEFAULT_NOISE_SELECTORS
    ticker_box_selector: str = _DEFAULT_TICKER_BOX_SELECTOR


# =====================================================================
# Hàm bóc tách THUẦN (không mạng) — dễ test bằng HTML giả.
# =====================================================================
def extract_links(html: str, base_url: str, pattern: re.Pattern[str]) -> list[str]:
    """Lấy link bài khớp `pattern` trên trang mục.

    - Chỉ giữ link cùng miền với `base_url` (loại ads/đối tác ngoại miền).
    - Khớp `pattern` trên phần path (không tính query) để tách link bài khỏi
      link trang mục.
    - Giữ thứ tự xuất hiện, bỏ trùng.
    """
    from bs4 import BeautifulSoup

    base_host = urlparse(base_url).netloc
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        full = urljoin(base_url, href)
        parts = urlparse(full)
        if parts.netloc and parts.netloc != base_host:
            continue  # ngoại miền (quảng cáo/đối tác)
        if pattern.search(parts.path) and full not in seen:
            seen.add(full)
            out.append(full)
    return out


def extract_article(
    html: str,
    *,
    title_selector: str,
    body_selector: str,
    noise_selectors: tuple[str, ...] = (),
    ticker_box_selector: str = "",
) -> tuple[str, str]:
    """Trích (tiêu đề, thân bài) từ HTML 1 bài.

    - `ticker_box_selector` (nếu có): box mã CK CafeF gắn (vd '.chisochungkhoan',
      text "VHM: Giá hiện tại..."). TRÍCH mã liên quan từ đây trước, chèn dòng
      "Mã liên quan: ..." vào đầu thân bài (giúp bước trích mã bắt được mã dù bài
      chỉ gọi tên doanh nghiệp), rồi mới loại box (bỏ phần chrome giá).
    - Loại các box nhiễu (`noise_selectors`, vd "TIN MỚI"/ads) để thân bài sạch.
    - Trả text đã gộp khoảng trắng. Không thấy thân bài -> body rỗng (bỏ bài).
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    title_el = soup.select_one(title_selector)
    title = _collapse_ws(title_el.get_text(" ", strip=True)) if title_el else ""

    body_el = soup.select_one(body_selector)
    if body_el is None:
        return title, ""

    # Trích mã CK từ box tag (trước khi loại) — CafeF hay chỉ gọi tên DN trong
    # văn xuôi, mã thật nằm ở box này.
    ticker_prefix = ""
    if ticker_box_selector:
        codes: list[str] = []
        for box in body_el.select(ticker_box_selector):
            m = _TICKER_BOX_CODE_RE.match(box.get_text(" ", strip=True))
            if m and m.group(1) not in codes:
                codes.append(m.group(1))
            box.decompose()  # bỏ phần chrome giá ("Giá hiện tại/Thay đổi/...")
        if codes:
            ticker_prefix = f"Mã liên quan: {', '.join(codes)}. "

    for sel in noise_selectors:
        for junk in body_el.select(sel):
            junk.decompose()
    body = _collapse_ws(body_el.get_text(" ", strip=True))
    return title, (ticker_prefix + body if body else body)


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# =====================================================================
# Collector (adapter) — cùng giao diện với MockCollector/Crawl4aiCollector.
# =====================================================================
class HttpFirstCollector(Collector):
    def __init__(
        self,
        *,
        specs: dict[str, SourceSpec] | None = None,
        default_spec: SourceSpec | None = None,
        user_agent: str = _DEFAULT_USER_AGENT,
        rate_limit_s: float = 1.5,
        jitter_s: float = 0.7,
        respect_robots: bool = True,
        timeout_s: float = 30.0,
        max_retries: int = 3,
        backoff_base_s: float = 2.0,
    ):
        self.specs = specs or {}
        self.default_spec = default_spec or SourceSpec(
            article_url_re=re.compile(_DEFAULT_ARTICLE_PATTERN)
        )
        self.user_agent = user_agent
        self.rate_limit_s = rate_limit_s
        self.jitter_s = jitter_s
        self.respect_robots = respect_robots
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self._robots: dict[str, RobotFileParser | None] = {}

    @classmethod
    def from_settings(cls, settings) -> "HttpFirstCollector":
        """Dựng từ config/settings.yaml: crawl.* (toàn cục) + sources[].* (selector)."""
        default_pattern = settings.get("crawl.article_url_pattern", _DEFAULT_ARTICLE_PATTERN)
        default_title = settings.get("crawl.title_selector", _DEFAULT_TITLE_SELECTOR)
        default_body = settings.get("crawl.body_selector", _DEFAULT_BODY_SELECTOR)
        default_noise = _as_tuple(
            settings.get("crawl.noise_selectors"), _DEFAULT_NOISE_SELECTORS
        )
        default_ticker_box = settings.get("crawl.ticker_box_selector", _DEFAULT_TICKER_BOX_SELECTOR)
        default_spec = SourceSpec(
            article_url_re=re.compile(default_pattern),
            title_selector=default_title,
            body_selector=default_body,
            noise_selectors=default_noise,
            ticker_box_selector=default_ticker_box,
        )

        specs: dict[str, SourceSpec] = {}
        for s in settings.get("sources", []) or []:
            url = s.get("url")
            if not url:
                continue
            specs[url] = SourceSpec(
                article_url_re=re.compile(s.get("article_url_pattern", default_pattern)),
                title_selector=s.get("title_selector", default_title),
                body_selector=s.get("body_selector", default_body),
                noise_selectors=_as_tuple(s.get("noise_selectors"), default_noise),
                ticker_box_selector=s.get("ticker_box_selector", default_ticker_box),
            )

        return cls(
            specs=specs,
            default_spec=default_spec,
            user_agent=settings.get("crawl.user_agent", _DEFAULT_USER_AGENT) or _DEFAULT_USER_AGENT,
            rate_limit_s=float(settings.get("crawl.rate_limit_s", 1.5)),
            jitter_s=float(settings.get("crawl.rate_limit_jitter_s", 0.7)),
            respect_robots=bool(settings.get("crawl.respect_robots", True)),
            timeout_s=float(settings.get("crawl.timeout_s", 30.0)),
            max_retries=int(settings.get("crawl.max_retries", 3)),
            backoff_base_s=float(settings.get("crawl.backoff_base_s", 2.0)),
        )

    def collect(self, source: Source, *, limit: int = 10) -> list[RawDocument]:
        import httpx

        spec = self.specs.get(source.url, self.default_spec)
        headers = {"User-Agent": self.user_agent}
        with httpx.Client(
            headers=headers, timeout=self.timeout_s, follow_redirects=True
        ) as client:
            if not self._allowed(client, source.url):
                print(f"[CẢNH BÁO] robots.txt chặn trang mục: {source.url}")
                return []
            listing = self._fetch(client, source.url)
            if listing is None:
                print(f"[CẢNH BÁO] Không tải được trang mục: {source.url}")
                return []

            urls = extract_links(listing, source.url, spec.article_url_re)[:limit]
            docs: list[RawDocument] = []
            for i, url in enumerate(urls):
                if i:  # nghỉ giữa các bài (lịch sự với server), bỏ qua trước bài đầu
                    self._sleep()
                doc = self._fetch_and_extract(client, source, spec, url)
                if doc is not None:
                    docs.append(doc)
        return docs

    def fetch_one(self, source: Source, url: str) -> RawDocument | None:
        """Fetch + trích 1 bài (TẦNG 3 của mô hình 3 lớp thu thập: full-fetch CHỈ
        cho item RSS ĐÃ ĐƯỢC GIỮ ở tầng phát hiện/lọc — xem rss_collector.py).

        Selector tra theo `source.url` (đăng ký ở settings.sources[], khớp CẢ
        nguồn rss lẫn html — nguồn rss khai selector trang BÀI dưới FeedURL của
        chính nó). Không dùng listing/extract_links — `url` đã biết trước."""
        import httpx

        spec = self.specs.get(source.url, self.default_spec)
        headers = {"User-Agent": self.user_agent}
        with httpx.Client(
            headers=headers, timeout=self.timeout_s, follow_redirects=True
        ) as client:
            return self._fetch_and_extract(client, source, spec, url)

    def _fetch_and_extract(self, client, source: Source, spec: SourceSpec,
                           url: str) -> RawDocument | None:
        """Fetch 1 URL bài + trích tiêu đề/thân bài theo `spec`. Dùng chung bởi
        collect() (vòng lặp listing) và fetch_one() (1 URL biết trước)."""
        if not self._allowed(client, url):
            print(f"[CẢNH BÁO] robots.txt chặn bài: {url}")
            return None
        html = self._fetch(client, url)
        if html is None:
            return None
        title, body = extract_article(
            html,
            title_selector=spec.title_selector,
            body_selector=spec.body_selector,
            noise_selectors=spec.noise_selectors,
            ticker_box_selector=spec.ticker_box_selector,
        )
        if not body:
            return None
        return RawDocument(
            source=source.name,
            url=url,
            title=title or source.name,
            markdown=body,
            source_type=source.source_type,
        )

    # --- Hạ tầng mạng (có retry + backoff) ----------------------------------
    def _fetch(self, client, url: str) -> str | None:
        import httpx

        for attempt in range(1, self.max_retries + 1):
            try:
                r = client.get(url)
            except httpx.HTTPError as e:  # timeout/mạng: thử lại
                if attempt == self.max_retries:
                    print(f"[CẢNH BÁO] Lỗi mạng ({e!r}) bỏ qua: {url}")
                    return None
            else:
                if r.status_code == 200:
                    return r.text
                if r.status_code < 500:  # 4xx: lỗi cố định, không thử lại
                    print(f"[CẢNH BÁO] HTTP {r.status_code} bỏ qua: {url}")
                    return None
                # 5xx: lỗi tạm, thử lại
                if attempt == self.max_retries:
                    print(f"[CẢNH BÁO] HTTP {r.status_code} sau {attempt} lần: {url}")
                    return None
            time.sleep(self.backoff_base_s * attempt)
        return None

    def _allowed(self, client, url: str) -> bool:
        if not self.respect_robots:
            return True
        parts = urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            self._robots[origin] = self._load_robots(client, origin)
        rp = self._robots[origin]
        if rp is None:  # không đọc được robots.txt -> mặc định cho phép
            return True
        return rp.can_fetch(self.user_agent, url)

    def _load_robots(self, client, origin: str) -> RobotFileParser | None:
        import httpx

        try:
            r = client.get(f"{origin}/robots.txt")
        except httpx.HTTPError:
            return None
        if r.status_code != 200:
            return None
        rp = RobotFileParser()
        rp.parse(r.text.splitlines())
        return rp

    def _sleep(self) -> None:
        import random

        delay = self.rate_limit_s + random.uniform(0, self.jitter_s)
        time.sleep(delay)


def _as_tuple(value, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return (str(value),)
