"""Collector RSS — TẦNG 1 (phát hiện) trong mô hình thu thập 3 lớp, $0, THUẦN stdlib.

Mô hình 3 lớp:
  1) RssCollector (đây) — đọc feed RSS 2.0, NHẸ: chỉ title/link/summary/category/
     pubDate. KHÔNG fetch full bài — mục đích DUY NHẤT là phát hiện bài mới +
     tóm tắt + gợi ý phân loại (category) nhanh, rẻ.
  2) curation.normalize + curation.enrich (relevance/classify/score/near-dup) —
     quyết bài nào ĐƯỢC GIỮ dựa trên summary ở tầng 1 (xem scripts/review_to_sheet.py).
  3) HttpFirstCollector.fetch_one — CHỈ fetch full bài cho item ĐƯỢC GIỮ ở tầng 2,
     rồi mới persist. Tránh tải full HTML cho những bài sẽ bị loại.

THUẦN stdlib (urllib.request + xml.etree.ElementTree) — không thêm phụ thuộc
ngoài (không feedparser/httpx) — chạy được ngay cả khi chưa cài httpx/bs4.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

from ..models import RawDocument, Source
from .base import Collector

# ASCII-only: urllib.request (stdlib) đòi header giá trị latin-1/ASCII, KHÔNG
# chấp nhận dấu tiếng Việt (khác httpx dùng ở http_collector.py — mã hóa khoan
# dung hơn). Đây là lý do RssCollector không tái dùng thẳng hằng số user agent
# có dấu của http_collector.py.
_DEFAULT_USER_AGENT = (
    "TurtleWealthMktBot/0.2 (+marketing automation noi bo, thu thap tin tai "
    "chinh VN; lien he: trieuvanstock@gmail.com)"
)
_DEFAULT_TIMEOUT_S = 20.0
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


@dataclass
class RssItem:
    """1 mục RSS THUẦN (chưa fetch full bài) — dùng cho tầng phát hiện + phân loại."""

    title: str
    link: str
    summary: str = ""            # <description>, đã bỏ thẻ HTML
    category: str = ""           # <category> đầu tiên (gợi ý Field, có thể rỗng)
    published_at: datetime | None = None


# =====================================================================
# Hàm THUẦN (không mạng) — test trực tiếp bằng fixture XML.
# =====================================================================
def parse_rss(xml_text: str) -> list[RssItem]:
    """Parse RSS 2.0 (xml.etree, $0, không mạng). Bỏ qua item thiếu <link>; XML
    hỏng -> trả [] (không raise, để collector có thể log cảnh báo & bỏ qua nguồn)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items: list[RssItem] = []
    for item_el in root.iter("item"):
        link = _text(item_el, "link")
        if not link:
            continue
        items.append(RssItem(
            title=_strip_html(_text(item_el, "title")),
            link=link,
            summary=_strip_html(_text(item_el, "description")),
            category=_text(item_el, "category"),
            published_at=_parse_date(_text(item_el, "pubDate")),
        ))
    return items


def _text(el: ET.Element, tag: str) -> str:
    child = el.find(tag)
    return (child.text or "").strip() if child is not None and child.text else ""


def _strip_html(s: str) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", s or "")).strip()


def _parse_date(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        return None


# =====================================================================
# Collector (adapter) — cùng giao diện với HttpFirstCollector/MockCollector.
# =====================================================================
class RssCollector(Collector):
    def __init__(self, *, user_agent: str = _DEFAULT_USER_AGENT,
                timeout_s: float = _DEFAULT_TIMEOUT_S):
        self.user_agent = user_agent
        self.timeout_s = timeout_s

    @classmethod
    def from_settings(cls, settings) -> "RssCollector":
        """Dựng từ config/settings.yaml: crawl.user_agent/crawl.timeout_s (dùng
        chung với HttpFirstCollector, không cần mục cấu hình riêng)."""
        return cls(
            user_agent=settings.get("crawl.user_agent", _DEFAULT_USER_AGENT) or _DEFAULT_USER_AGENT,
            timeout_s=float(settings.get("crawl.timeout_s", _DEFAULT_TIMEOUT_S)),
        )

    def collect(self, source: Source, *, limit: int = 10) -> list[RawDocument]:
        """Trả RawDocument với markdown = summary RSS (CHƯA fetch full bài — xem
        module docstring). `category_hint` mang gợi ý Field từ <category> RSS."""
        xml_text = self._fetch(source.url)
        if xml_text is None:
            return []
        items = parse_rss(xml_text)[:limit]
        return [
            RawDocument(
                source=source.name,
                url=it.link,
                title=it.title or source.name,
                markdown=it.summary,
                source_type=source.source_type,
                fetched_at=it.published_at or datetime.now(timezone.utc),
                category_hint=it.category,
            )
            for it in items
        ]

    def _fetch(self, url: str) -> str | None:
        # Header HTTP (stdlib urllib) chỉ chấp nhận ASCII/latin-1 -> ép an toàn
        # phòng khi crawl.user_agent lỡ có dấu tiếng Việt (không raise, chỉ bỏ dấu).
        ua = self.user_agent.encode("ascii", errors="ignore").decode("ascii") or "TurtleWealthMktBot/0.2"
        req = urllib.request.Request(url, headers={"User-Agent": ua})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:  # noqa: S310
                charset = resp.headers.get_content_charset() or "utf-8"
                return resp.read().decode(charset, errors="replace")
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            print(f"[CẢNH BÁO] Không tải được RSS: {url} ({e!r})")
            return None
