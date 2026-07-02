"""Registry các nguồn thu thập THẬT — khai báo, không phải logic crawl.

Thêm nguồn mới = thêm 1 SourceConfig vào SOURCES, không sửa Crawl4aiCollector.
CafeF cho `Allow: /` trong robots.txt (không có Crawl-delay) nên ta tự áp
rate-limit ~1 req/1.5s cho lịch sự. Bắt đầu chỉ bật "doanh-nghiep"; hai mục
còn lại đã khai báo sẵn, bật khi cần (đổi `enabled=True`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import Source, SourceType

# Link bài viết CafeF có dạng /<slug>-<id-số-dài>.chn, khác link trang mục
# (vd /doanh-nghiep.chn, /vi-mo-dau-tu.chn không có phần số dài).
_CAFEF_ARTICLE_RE = re.compile(r"/[a-z0-9-]+-\d{10,}\.chn$")


@dataclass(frozen=True)
class SourceConfig:
    """Cấu hình crawl cho 1 chuyên mục: trang mục -> nhận diện link bài -> tốc độ."""

    source: Source          # source.url = trang chuyên mục (danh sách bài)
    article_link_re: re.Pattern[str]
    rate_limit_s: float = 1.5   # nghỉ giữa các request bài viết, tránh dồn dập
    respect_robots: bool = True
    enabled: bool = False


CAFEF_DOANH_NGHIEP = SourceConfig(
    source=Source("CafeF - Doanh nghiệp", "https://cafef.vn/doanh-nghiep.chn", SourceType.NEWS),
    article_link_re=_CAFEF_ARTICLE_RE,
    enabled=True,
)

CAFEF_VI_MO = SourceConfig(
    source=Source("CafeF - Vĩ mô đầu tư", "https://cafef.vn/vi-mo-dau-tu.chn", SourceType.NEWS),
    article_link_re=_CAFEF_ARTICLE_RE,
    enabled=False,
)

CAFEF_TAI_CHINH_QUOC_TE = SourceConfig(
    source=Source("CafeF - Tài chính quốc tế", "https://cafef.vn/tai-chinh-quoc-te.chn", SourceType.NEWS),
    article_link_re=_CAFEF_ARTICLE_RE,
    enabled=False,
)

SOURCES: dict[str, SourceConfig] = {
    "doanh-nghiep": CAFEF_DOANH_NGHIEP,
    "vi-mo": CAFEF_VI_MO,
    "tai-chinh-quoc-te": CAFEF_TAI_CHINH_QUOC_TE,
}


def get_source(key: str) -> SourceConfig:
    try:
        return SOURCES[key]
    except KeyError as e:
        raise KeyError(f"Không tìm thấy nguồn '{key}'. Có: {list(SOURCES)}") from e


def enabled_sources() -> list[SourceConfig]:
    return [cfg for cfg in SOURCES.values() if cfg.enabled]
