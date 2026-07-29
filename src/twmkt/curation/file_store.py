"""FileDocumentStore — lưu CleanDocument ra đĩa, PARTITION THEO NGÀY + retention.

Layout: <root>/<YYYY-MM-DD>/<content_hash>.json — mỗi ngày 1 folder (yêu cầu
"data nhiều ngày lưu folder khác nhau"). `root` do CALLER truyền vào (KHÔNG tự
biết gì về storage.data_root) — factory.build_store() resolve qua
config.data_path() (Phase DATA-ROOT), giữ class này thuần/độc lập, tái dùng
được ở nơi khác (test truyền thẳng thư mục tạm).

Chống trùng ($0):
  • Khoá theo NỘI DUNG (hash của title+markdown), KHÔNG theo url — nên chạy crawl
    NHIỀU LẦN TRONG NGÀY không tạo bản trùng (cùng bài = cùng hash = 1 file).
  • Dedup CHÉO các ngày CÒN GIỮ: bài đã có ở bất kỳ folder ngày nào trong cửa sổ
    retention -> KHÔNG ghi lại (upsert trả về 0 "mới").

Retention: chỉ giữ `retention_days` folder ngày MỚI NHẤT (mặc định 10) — folder
cũ hơn bị xoá tự động mỗi lần upsert.

Vẫn đúng protocol DocumentStore (upsert/all) nên thay InMemoryStore 1-1.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from ..models import CleanDocument, SourceType

_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _resolve_today(tz_name: str) -> str:
    """Ngày hiện tại (YYYY-MM-DD) theo timezone cấu hình; fallback giờ máy."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz_name)).date().isoformat()
    except Exception:  # pragma: no cover - thiếu dữ liệu tz -> dùng giờ local
        return datetime.now().date().isoformat()


def _content_key(d: CleanDocument) -> str:
    """Khoá dedup theo NỘI DUNG (title+markdown chuẩn hoá) -> tên file."""
    norm = " ".join(f"{d.title}\n{d.markdown}".split()).lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


class FileDocumentStore:
    def __init__(self, root: str = "storage/documents", *, retention_days: int = 10,
                 today: str | None = None, tz: str = "Asia/Ho_Chi_Minh"):
        self.root = Path(root)
        self.retention_days = max(1, int(retention_days))
        self.today = today or _resolve_today(tz)
        self.day_dir = self.root / self.today
        self.day_dir.mkdir(parents=True, exist_ok=True)

    # --- folder ngày -------------------------------------------------------
    def _day_dirs(self) -> list[Path]:
        """Các folder ngày hợp lệ (tên YYYY-MM-DD), sắp TĂNG dần (ISO = niên đại)."""
        if not self.root.exists():
            return []
        return sorted(d for d in self.root.iterdir()
                      if d.is_dir() and _DAY_RE.match(d.name))

    def _seen_keys(self) -> set[str]:
        """Tập content_hash đã có trong MỌI folder ngày còn giữ (dedup chéo ngày)."""
        seen: set[str] = set()
        for d in self._day_dirs():
            for f in d.glob("*.json"):
                seen.add(f.stem)
        return seen

    # --- DocumentStore protocol -------------------------------------------
    def upsert(self, docs: list[CleanDocument]) -> int:
        """Ghi các bài CHƯA từng thấy (theo nội dung) vào folder HÔM NAY; trả số
        bài MỚI. Bài đã có ở bất kỳ ngày còn giữ -> bỏ qua (dedup chéo lần chạy/ngày)."""
        seen = self._seen_keys()
        new = 0
        for d in docs:
            key = _content_key(d)
            if key in seen:
                continue
            (self.day_dir / f"{key}.json").write_text(
                json.dumps(_ser(d), ensure_ascii=False, indent=2), encoding="utf-8")
            seen.add(key)
            new += 1
        self._enforce_retention()
        return new

    def all(self) -> list[CleanDocument]:
        """Mọi tài liệu trong cửa sổ retention (gộp các folder ngày)."""
        out: list[CleanDocument] = []
        for d in self._day_dirs():
            for f in sorted(d.glob("*.json")):
                out.append(_de(json.loads(f.read_text(encoding="utf-8"))))
        return out

    def _enforce_retention(self) -> None:
        """Giữ tối đa `retention_days` folder ngày mới nhất; xoá phần cũ hơn."""
        dirs = self._day_dirs()
        for old in dirs[:-self.retention_days]:
            shutil.rmtree(old, ignore_errors=True)


def _ser(d: CleanDocument) -> dict:
    st = d.source_type.value if hasattr(d.source_type, "value") else str(d.source_type)
    at = d.fetched_at.isoformat() if hasattr(d.fetched_at, "isoformat") else str(d.fetched_at)
    # 2026-07-28: THÊM published_at/category_hint/canonical_url. Trước đó _ser
    # chỉ giữ 8 trường và ÂM THẦM bỏ rơi 3 trường còn lại của CleanDocument:
    #  - published_at: mất luôn khả năng truy "bài này đăng ngày nào" sau khi
    #    crawl xong -> không kiểm được bộ lọc ngày có đúng không (Lead hỏi
    #    "sao chưa thấy tin 27/07" mà không ai trả lời được từ dữ liệu).
    #  - canonical_url: NGHIÊM TRỌNG hơn -- đây là đầu vào của TopicKey
    #    (curation/keys.compute_topic_key ưu tiên `canonical_url or url`). Đọc
    #    lại document từ đĩa mà thiếu nó -> tính ra TopicKey KHÁC với lượt
    #    crawl gốc, phá kỷ luật "write-once" của Lớp 5.
    #  - category_hint: gợi ý Field từ RSS, dùng ở enrich.
    pub = d.published_at.isoformat() if getattr(d, "published_at", None) is not None else None
    return {
        "source": d.source, "url": d.url, "title": d.title, "markdown": d.markdown,
        "tickers": list(d.tickers), "tags": list(d.tags),
        "source_type": st, "fetched_at": at,
        "published_at": pub, "category_hint": d.category_hint,
        "canonical_url": d.canonical_url,
    }


def _de(r: dict) -> CleanDocument:
    return CleanDocument(
        source=r["source"], url=r["url"], title=r["title"], markdown=r["markdown"],
        tickers=r.get("tickers", []), tags=r.get("tags", []),
        source_type=SourceType(r.get("source_type", "news")),
        fetched_at=datetime.fromisoformat(r["fetched_at"]),
        # `.get()` + None-check: file CŨ (ghi trước 2026-07-28) không có 3 khoá
        # này -> đọc lại vẫn được, chỉ thiếu thông tin, KHÔNG nổ.
        published_at=(datetime.fromisoformat(r["published_at"])
                      if r.get("published_at") else None),
        category_hint=r.get("category_hint", ""),
        canonical_url=r.get("canonical_url", ""),
    )
