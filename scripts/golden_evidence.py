"""Phase 3.0 — Đảm bảo evidence cho golden set (`tests/golden/*.json`) nằm
trong corpus của MÁY NÀY, tra theo `topic_key` — KHÔNG phụ thuộc
`tests/golden/_raw/*.txt` (dữ liệu vận hành, không còn dùng để benchmark).

Vì sao tách khỏi `_raw/*.txt`: `data_root`/corpus KHÔNG đồng bộ giữa máy — evidence
crawl ở máy A có thể không tồn tại ở máy B. Golden set (`tests/golden/*.json`,
facts người liệt kê tay) là THƯỚC ĐO, ở trong git, bất biến. Evidence để CHẤM
model (Brief) phải đọc từ corpus THẬT của máy đang chạy benchmark — script này
kiểm tra + tự crawl bù (qua chính collector pipeline, $0, tất định) nếu thiếu.

Dùng bởi Phase 3.0 (khảo + đảm bảo, không benchmark) VÀ Phase 3.1 (harness A/B
Brief import `evidence_text_for_golden()` để lấy evidence — KHÔNG đọc `_raw/`).

Chạy:
    python scripts/golden_evidence.py            # khảo + tự crawl bù nếu thiếu
    python scripts/golden_evidence.py --check-only # chỉ khảo, KHÔNG crawl
"""
from __future__ import annotations

import json
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

from twmkt import factory  # noqa: E402
from twmkt.config import load_settings  # noqa: E402
from twmkt.curation.keys import compute_topic_key  # noqa: E402
from twmkt.curation.normalize import normalize  # noqa: E402
from twmkt.models import CleanDocument, Source  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from produce_from_sheet import match_source_by_domain  # noqa: E402

GOLDEN_DIR = REPO_ROOT / "tests" / "golden"


def _nfc(s: str) -> str:
    """Chuẩn hoá NFC — dấu tiếng Việt tổ hợp (NFD) làm so khớp substring SAI IM
    LẶNG (bug đã bắt được trước đây); mọi so khớp source_sentence PHẢI qua đây."""
    return unicodedata.normalize("NFC", s or "")


@dataclass
class GoldenEntry:
    slug: str
    url: str
    topic_key: str
    facts: list[dict]
    path: Path
    raw: dict = field(repr=False)


def load_golden_entries() -> list[GoldenEntry]:
    """Đọc `tests/golden/*.json`, tính `topic_key` từ `url` (Lớp 5 — cùng hàm
    compute_topic_key dùng ở pipeline thật). KHÔNG đọc `_raw/*.txt`."""
    out = []
    for f in sorted(GOLDEN_DIR.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        url = d.get("url", "")
        key = compute_topic_key(url) or ""
        out.append(GoldenEntry(slug=d["slug"], url=url, topic_key=key,
                                facts=d.get("facts", []), path=f, raw=d))
    return out


def _doc_topic_key(doc: CleanDocument) -> str:
    """Cùng thứ tự ưu tiên với review_to_sheet.py: canonical_url trước, url sau."""
    return compute_topic_key(doc.canonical_url or doc.url) or ""


def find_in_corpus(golden_key: str, docs: list[CleanDocument]) -> CleanDocument | None:
    for d in docs:
        if _doc_topic_key(d) == golden_key:
            return d
    return None


def crawl_one(settings, url: str) -> CleanDocument | None:
    """Crawl 1 URL qua chính collector pipeline (HttpFirstCollector, $0, tất
    định) — KHÔNG scrape ngoài, KHÔNG gọi LLM. LUÔN dùng HttpFirstCollector cho
    full-fetch 1 URL biết trước (fetch_one) — kể cả khi nguồn đăng ký fetch_type
    'rss' (RssCollector không có fetch_one, chỉ phát hiện) — nhưng vẫn tra
    nguồn ĐĂNG KÝ theo TÊN MIỀN (match_source_by_domain, cùng hàm
    produce_from_sheet.fetch_full_evidence dùng) để lấy ĐÚNG selector spec khi
    gọi fetch_one — thiếu bước này khiến trích rỗng ở site cần selector riêng
    (vd cafebiz.vn), dù fetch HTTP vẫn 200 OK. Y HỆT pattern
    produce_from_sheet.fetch_full_evidence (html_collector riêng + matched
    source chỉ để tra spec)."""
    sources = factory.build_sources(settings)
    matched = match_source_by_domain(url, sources)
    html_collector = factory.build_collector_for_source(
        Source("_", "_", fetch_type="html"), settings)
    raw = html_collector.fetch_one(matched or Source("_", url), url)
    if raw is None or not (raw.markdown or "").strip():
        return None
    cleaned = normalize([raw])
    return cleaned[0] if cleaned else None


def evidence_text(doc: CleanDocument) -> str:
    return f"{doc.title}\n\n{doc.markdown}"


def evidence_text_for_golden(slug: str, settings=None) -> str | None:
    """API dùng bởi Phase 3.1 harness: evidence (title+markdown) cho 1 golden
    slug, tra corpus theo topic_key. Trả None nếu THIẾU — caller (Phase 3.1)
    PHẢI raise rõ ràng, KHÔNG được âm thầm chạy trên evidence rỗng."""
    settings = settings or load_settings()
    entries = {e.slug: e for e in load_golden_entries()}
    if slug not in entries:
        return None
    e = entries[slug]
    store = factory.build_store(settings)
    doc = find_in_corpus(e.topic_key, store.all())
    return evidence_text(doc) if doc else None


def main(*, check_only: bool = False) -> list[dict]:
    settings = load_settings()
    entries = load_golden_entries()
    store = factory.build_store(settings)

    report = []
    for e in entries:
        docs = store.all()
        doc = find_in_corpus(e.topic_key, docs)
        status = "CÓ_SẴN" if doc else "THIẾU"
        crawled = False

        if doc is None and not check_only:
            fetched = crawl_one(settings, e.url)
            if fetched is not None:
                store.upsert([fetched])
                crawled = True
                fetched_key = _doc_topic_key(fetched)
                if fetched_key != e.topic_key:
                    status = "CRAWL_LẠI_NHƯNG_KHÁC_KHOÁ"
                else:
                    status = "CRAWL_LẠI_OK"
                doc = fetched
            else:
                status = "CRAWL_LẠI_THẤT_BẠI"

        mismatches: list[str] = []
        if doc is not None:
            ev_nfc = _nfc(evidence_text(doc))
            for f in e.facts:
                ss = f.get("source_sentence", "")
                if ss and _nfc(ss) not in ev_nfc:
                    mismatches.append(ss[:100])

        # Persist topic_key vào golden JSON — tham chiếu theo khoá, không path.
        if e.raw.get("topic_key") != e.topic_key:
            new_raw = {k: v for k, v in e.raw.items()}
            new_raw["topic_key"] = e.topic_key
            e.path.write_text(json.dumps(new_raw, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")

        report.append({
            "slug": e.slug, "topic_key": e.topic_key, "status": status,
            "crawled": crawled, "n_facts": len(e.facts),
            "n_source_sentence_mismatch": len(mismatches),
            "mismatches": mismatches,
        })

    return report


if __name__ == "__main__":
    check_only = "--check-only" in sys.argv
    rows = main(check_only=check_only)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    n_missing = sum(1 for r in rows if r["status"] in ("THIẾU", "CRAWL_LẠI_THẤT_BẠI"))
    n_mismatch = sum(r["n_source_sentence_mismatch"] for r in rows)
    print(f"\n== TỔNG: {len(rows)} bài | thiếu/lỗi crawl: {n_missing} | "
         f"source_sentence lệch: {n_mismatch} ==")
