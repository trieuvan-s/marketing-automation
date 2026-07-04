"""Làm giàu tất định ($0 token): phân nhóm chủ đề marketing, điểm marketing,
phân loại Field/Topic theo TAXONOMY, và phát hiện trùng/near-duplicate.
Config-driven (nhận nhóm/taxonomy từ khóa + trọng số).

Mục tiêu: để CONTEXT phản ánh ĐÚNG nhu cầu marketing — nổi bài đáng làm, gắn nhãn
nhóm/Field/Topic để đội lọc, và chặn lặp (như 2 dòng Vinhomes/Iran từ 2 lần chạy).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Nhóm chủ đề mặc định (settings.yaml có thể override).
DEFAULT_GROUPS: dict[str, list[str]] = {
    "ChinhSach": ["nghị định", "nghị quyết", "thông tư", "chính phủ", "thủ tướng",
                  "sbv", "ngân hàng nhà nước", "nhnn", "bộ tài chính", "quốc hội",
                  "lãi suất điều hành", "room tín dụng"],
    "ViMoVN": ["gdp", "lạm phát", "cpi", "tỷ giá", "tỉ giá", "tăng trưởng",
               "xuất khẩu", "nhập khẩu", "fdi", "dự trữ ngoại hối", "cung tiền"],
    "ViMoTheGioi": ["fed", "phố wall", "dow jones", "nasdaq", "s&p", "ecb", "opec",
                    "trung quốc", "nhật bản", "châu âu", "giá dầu", "vàng thế giới",
                    "nga", "iran", "ukraine", "thị trường mỹ", "lao động mỹ"],
}

# Tín hiệu "đáng lên bài" (newsworthiness).
DEFAULT_NEWSWORTHY = ["%", "tỷ đồng", "nghìn tỷ", "kỷ lục", "tăng mạnh",
                      "giảm mạnh", "lần đầu", "cao nhất", "thấp nhất"]


def groups_from_settings(settings) -> dict[str, list[str]]:
    """Đọc curation.groups từ settings.yaml (config-first); rỗng -> DEFAULT_GROUPS
    (dự phòng, dùng khi chạy offline/test không truyền settings)."""
    raw = settings.get("curation.groups", {}) or {}
    if not raw:
        return DEFAULT_GROUPS
    return {str(name): [str(kw).lower() for kw in (kws or [])] for name, kws in raw.items()}


def classify(text: str, tickers: list[str], *, tags: list[str] | None = None,
             groups: dict[str, list[str]] | None = None) -> list[str]:
    """Gắn nhãn nhóm marketing. Bài có mã -> 'CoPhieu'; khớp từ khóa -> nhóm vĩ mô/CS."""
    groups = groups or DEFAULT_GROUPS
    low = text.lower()
    labels: list[str] = []
    if tickers:
        labels.append("CoPhieu")
    for name, kws in groups.items():
        if any(k in low for k in kws) and name not in labels:
            labels.append(name)
    for t in (tags or []):
        t = t.strip()
        if t and t not in labels:
            labels.append(t)
    return labels or ["Khac"]


def marketing_score(text: str, tickers: list[str], *, macro_hits: int = 0,
                    w_ticker: int = 3, w_macro: int = 2, w_news: int = 1,
                    newsworthy: list[str] | None = None) -> int:
    """Điểm marketing = liên quan (mã) + vĩ mô + tín hiệu đáng lên bài."""
    low = text.lower()
    signals = newsworthy or DEFAULT_NEWSWORTHY
    news = sum(1 for s in signals if s in low)
    return len(tickers) * w_ticker + int(macro_hits) * w_macro + min(news, 3) * w_news


# --- Near-duplicate theo tiêu đề (gom bài cùng sự kiện) ---------------------
def _title_tokens(t: str) -> set[str]:
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")  # bỏ dấu
    return set(w for w in re.sub(r"[^a-z0-9 ]", " ", t).split() if len(w) > 1)


def title_similarity(a: str, b: str) -> float:
    """Jaccard trên token tiêu đề (đã bỏ dấu)."""
    sa, sb = _title_tokens(a), _title_tokens(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def is_near_duplicate(title: str, seen_titles: list[str], *, threshold: float = 0.6) -> bool:
    return any(title_similarity(title, s) >= threshold for s in seen_titles)


# --- Gom SỰ KIỆN chéo nguồn: giữ báo Priority cao, gộp URL báo khác ----------
@dataclass
class EventItem:
    """1 ứng viên gom sự kiện: title + url + publisher + priority (SOURCES.Priority)."""
    title: str
    url: str
    publisher: str = ""
    priority: int = 0


@dataclass
class EventCluster:
    """1 cụm sự kiện: bản đại diện (Priority cao nhất) + url các báo khác cùng tin."""
    item: EventItem
    other_urls: list[str] = field(default_factory=list)


def cluster_by_event(items: list[EventItem], *, threshold: float = 0.6) -> list[EventCluster]:
    """Gom `items` cùng SỰ KIỆN (tiêu đề near-duplicate, Jaccard >= threshold),
    BẤT KỂ nguồn. Mỗi cụm GIỮ item Priority CAO NHẤT làm đại diện (hòa -> item
    xuất hiện trước); url các item còn lại (báo khác đưa cùng tin) gộp vào
    `other_urls` (giữ thứ tự, bỏ trùng, loại url đại diện). Hàm THUẦN, $0 —
    chống trùng chéo báo bằng Priority (xem scripts/review_to_sheet.py)."""
    buckets: list[list[EventItem]] = []
    for it in items:
        bucket = next(
            (b for b in buckets
             if is_near_duplicate(it.title, [m.title for m in b], threshold=threshold)),
            None,
        )
        if bucket is None:
            buckets.append([it])
        else:
            bucket.append(it)

    clusters: list[EventCluster] = []
    for b in buckets:
        rep = max(b, key=lambda m: m.priority)   # Priority cao nhất; hòa -> first (max ổn định)
        others: list[str] = []
        for m in b:
            if m.url != rep.url and m.url not in others:
                others.append(m.url)
        clusters.append(EventCluster(item=rep, other_urls=others))
    return clusters


# --- Ưu tiên theo pha thị trường + % độ hot --------------------------------
def in_priority(labels: list[str], priority_groups: list[str]) -> bool:
    return any(g in priority_groups for g in labels)


def hotness_pct(text: str, tickers: list[str], labels: list[str], *,
                priority_groups: list[str] | None = None, macro_hits: int = 0,
                newsworthy: list[str] | None = None,
                w_priority: int = 4, w_ticker: int = 2,
                w_news: int = 2, w_macro: int = 2) -> int:
    """Độ hot 0..100 cho team cân nhắc duyệt. Boost mạnh nếu thuộc nhóm ưu tiên
    hiện tại (pha thị trường). Tất cả tất định, $0."""
    priority_groups = priority_groups or []
    low = text.lower()
    signals = newsworthy or DEFAULT_NEWSWORTHY
    news = sum(1 for s in signals if s in low)

    raw = (w_priority * (1 if in_priority(labels, priority_groups) else 0)
           + w_ticker * min(len(tickers), 3)
           + w_news * min(news, 4)
           + w_macro * min(int(macro_hits), 4))
    max_raw = w_priority + w_ticker * 3 + w_news * 4 + w_macro * 4
    return round(100 * raw / max_raw) if max_raw else 0


# --- TAXONOMY: Field/Topic do user định nghĩa (tab TAXONOMY: Field|Topic|Keywords) ---
@dataclass
class TaxonomyRow:
    """1 hàng TAXONOMY: (Field, Topic) khớp khi text chứa >=1 từ khóa."""
    field: str
    topic: str
    keywords: list[str] = field(default_factory=list)


# Mặc định khi TAXONOMY sheet/config trống (dự phòng, offline/test).
DEFAULT_TAXONOMY: list[TaxonomyRow] = [
    TaxonomyRow("ChinhSach", "TienTe", ["lãi suất điều hành", "room tín dụng",
                                        "ngân hàng nhà nước", "nhnn", "sbv"]),
    TaxonomyRow("ChinhSach", "PhapLy", ["nghị định", "nghị quyết", "thông tư",
                                        "luật", "quốc hội"]),
    TaxonomyRow("ViMo", "TrongNuoc", ["gdp", "lạm phát", "cpi", "tăng trưởng",
                                      "xuất khẩu", "nhập khẩu", "fdi"]),
    TaxonomyRow("ViMo", "TheGioi", ["fed", "ecb", "phố wall", "dow jones",
                                    "trung quốc", "giá dầu"]),
    TaxonomyRow("DoanhNghiep", "KetQuaKinhDoanh", ["lợi nhuận", "doanh thu", "cổ tức"]),
    TaxonomyRow("DoanhNghiep", "BatDongSan", ["bất động sản", "dự án", "quy hoạch"]),
]


def taxonomy_from_settings(settings) -> list[TaxonomyRow]:
    """Đọc curation.taxonomy từ settings.yaml (config-first); rỗng -> DEFAULT_TAXONOMY."""
    raw = settings.get("curation.taxonomy", []) or []
    rows = [
        TaxonomyRow(
            field=str(r.get("field", "")).strip(),
            topic=str(r.get("topic", "")).strip(),
            keywords=[str(k).lower() for k in (r.get("keywords") or [])],
        )
        for r in raw
        if r.get("field")
    ]
    return rows or DEFAULT_TAXONOMY


def classify_field_topic(text: str, *, hints: list[str] | None = None,
                         taxonomy: list[TaxonomyRow] | None = None) -> tuple[str, str]:
    """Trả (field, topic) khớp NHIỀU tín hiệu nhất trong `text` theo TAXONOMY.

    Mỗi từ khóa khớp trong `text` (không phân biệt hoa/thường) +1 điểm. Mỗi
    `hints` (vd <category> RSS, SOURCES.Field) khớp field (chứa nhau, không
    phân biệt hoa/thường) +2 điểm — ưu tiên gợi ý nhưng KHÔNG override tuyệt
    đối (bằng chứng từ khóa mạnh vẫn có thể thắng). Không khớp gì -> ("Khac", "")."""
    taxonomy = taxonomy or DEFAULT_TAXONOMY
    low = text.lower()
    hint_low = [h.strip().lower() for h in (hints or []) if h and h.strip()]

    best: TaxonomyRow | None = None
    best_score = 0
    for row in taxonomy:
        score = sum(1 for kw in row.keywords if kw in low)
        row_field_low = row.field.lower()
        if any(h in row_field_low or row_field_low in h for h in hint_low):
            score += 2
        if score > best_score:
            best_score, best = score, row
    if best is None:
        return "Khac", ""
    return best.field, best.topic
