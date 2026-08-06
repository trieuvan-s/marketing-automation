"""Cấu hình chuẩn hóa (config-first) — nạp từ settings + các file dữ liệu.

Nguyên tắc: các tham số lọc (whitelist mã, mã dễ nhầm, từ khóa vĩ mô, cửa sổ ngữ
cảnh, ngưỡng liên quan) KHÔNG hard-code trong code mà đọc từ config/settings.yaml
và các file trong data/. Toàn bộ tất định, $0 token.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # tránh phụ thuộc vòng khi type-check
    from ..config import Settings


def _load_lines(path: str | None) -> list[str]:
    """Đọc file danh sách (mỗi dòng 1 mục), bỏ dòng trống & comment. UTF-8."""
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        return []
    out: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


# TASK-012 (2026-08-06): fallback khi settings.yaml chưa có curation.groups.ChinhSach /
# curation.relevance.hotness_keywords — mirror đúng giá trị mặc định đang có trong
# enrich.DEFAULT_GROUPS["ChinhSach"] / enrich.DEFAULT_NEWSWORTHY (không import enrich.py
# vào đây để tránh phụ thuộc vòng/lệch trách nhiệm — config.py chỉ đọc settings).
_DEFAULT_POLICY_KEYWORDS = [
    "nghị định", "nghị quyết", "thông tư", "chính phủ", "thủ tướng",
    "sbv", "ngân hàng nhà nước", "nhnn", "bộ tài chính", "quốc hội",
    "lãi suất điều hành", "room tín dụng",
]
_DEFAULT_HOTNESS_KEYWORDS = [
    "%", "tỷ đồng", "nghìn tỷ", "kỷ lục", "tăng mạnh",
    "giảm mạnh", "lần đầu", "cao nhất", "thấp nhất",
]


@dataclass
class CurationConfig:
    """Tham số cho bước chuẩn hóa/lọc tất định.

    - `tickers` rỗng => extract_tickers dùng chế độ regex + blocklist (tương thích
      ngược). Khi có whitelist => chỉ giữ mã nằm trong whitelist.
    - `ambiguous` = mã vừa là mã CK vừa là từ thường (vd GAS/BID); chỉ tính là mã
      khi quanh nó (trong `ambiguous_context_window` ký tự) có tín hiệu ngữ cảnh CK.
    - `macro_keywords` + `min_macro_keywords` = giữ bài vĩ mô (0 mã) khi đủ từ khóa.

    TASK-012 (quy định biên tập chủ dự án, 2026-08-06) — nới `is_relevant()` theo
    3 trục, MỌI ngưỡng/danh sách/công tắc đọc từ settings.yaml (config-first):
    - `relevance_tickers` + `use_watchlist_for_relevance`: bài "có mã" chỉ tính khi
      mã thuộc watchlist TOP 300 (không phải toàn bộ `tickers`, có thể rộng hơn nếu
      whitelist trích mã khác watchlist). Rỗng -> coi như CHƯA cấu hình, lùi về
      `tickers` (hành vi cũ, không phải "tắt lọc" mà là fallback an toàn khi thiếu
      watchlist).
    - `policy_keywords` + `min_policy_keywords`: tín hiệu CHÍNH SÁCH VIỆT NAM riêng
      (ngưỡng thấp hơn `min_macro_keywords` vì từ khóa đặc hiệu hơn) — vĩ mô nước
      ngoài thuần túy (Fed, Dow Jones, ...) không nằm trong danh sách này nên KHÔNG
      tự nhiên đủ điều kiện qua nhánh này (đây là quyết định biên tập, không phải
      hiệu ứng phụ — xem `curation.groups.ViMoTheGioi` CHỦ Ý không được wire vào).
    - `hotness_keywords` + `min_hotness_keywords` + `enable_hotness_override`: bài
      "chủ đề nóng" (nhiều tín hiệu đáng lên bài cùng lúc) được giữ dù mã/macro/
      policy yếu. Độc lập với `enrich.hotness_pct` (dùng để SẮP XẾP CONTEXT sau khi
      đã qua lọc, cần `priority_groups` sống từ Sheet) — ở đây chỉ dùng tín hiệu
      tất định từ text để quyết định GIỮ/LOẠI tại bước crawl.
    """

    tickers: set[str] = field(default_factory=set)
    ambiguous: set[str] = field(default_factory=set)
    macro_keywords: list[str] = field(default_factory=list)
    ambiguous_context_window: int = 40
    min_macro_keywords: int = 2
    relevance_tickers: set[str] = field(default_factory=set)
    use_watchlist_for_relevance: bool = True
    policy_keywords: list[str] = field(default_factory=list)
    min_policy_keywords: int = 1
    hotness_keywords: list[str] = field(default_factory=list)
    min_hotness_keywords: int = 3
    enable_hotness_override: bool = True

    @classmethod
    def from_settings(cls, settings: "Settings") -> "CurationConfig":
        tickers_file = settings.get("curation.tickers_file", "data/tickers.txt")
        ambiguous_file = settings.get("curation.ambiguous_file", "data/tickers_ambiguous.txt")
        keywords_file = settings.get(
            "curation.relevance.keywords_file", "data/keywords_macro.txt"
        )
        watchlist_file = settings.get("curation.watchlist_file", "data/tickers.txt")
        policy_kws = settings.get("curation.groups.ChinhSach") or _DEFAULT_POLICY_KEYWORDS
        hotness_kws = settings.get("curation.relevance.hotness_keywords") or _DEFAULT_HOTNESS_KEYWORDS
        return cls(
            tickers={t.upper() for t in _load_lines(tickers_file)},
            ambiguous={t.upper() for t in _load_lines(ambiguous_file)},
            macro_keywords=[k.lower() for k in _load_lines(keywords_file)],
            ambiguous_context_window=int(settings.get("curation.ambiguous_context_window", 40)),
            min_macro_keywords=int(settings.get("curation.relevance.min_macro_keywords", 2)),
            relevance_tickers={t.upper() for t in _load_lines(watchlist_file)},
            use_watchlist_for_relevance=bool(
                settings.get("curation.relevance.use_watchlist_for_relevance", True)
            ),
            policy_keywords=[str(k).lower() for k in policy_kws],
            min_policy_keywords=int(settings.get("curation.relevance.min_policy_keywords", 1)),
            hotness_keywords=[str(k).lower() for k in hotness_kws],
            min_hotness_keywords=int(settings.get("curation.relevance.min_hotness_keywords", 3)),
            enable_hotness_override=bool(
                settings.get("curation.relevance.enable_hotness_override", True)
            ),
        )

    def macro_hits(self, text: str) -> int:
        """Số từ khóa vĩ mô (phân biệt) xuất hiện trong text."""
        low = text.lower()
        return sum(1 for kw in self.macro_keywords if kw in low)

    def policy_hits(self, text: str) -> int:
        """Số từ khóa CHÍNH SÁCH VIỆT NAM (phân biệt) xuất hiện trong text."""
        low = text.lower()
        return sum(1 for kw in self.policy_keywords if kw in low)

    def hotness_hits(self, text: str) -> int:
        """Số tín hiệu "đáng lên bài" (phân biệt) xuất hiện trong text."""
        low = text.lower()
        return sum(1 for kw in self.hotness_keywords if kw in low)
