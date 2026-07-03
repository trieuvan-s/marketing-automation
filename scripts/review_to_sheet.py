"""DEMO khép kín, $0 token: nguồn THẬT -> data sạch -> title + hook lên Google Sheet.

MÔ HÌNH THU THẬP 3 LỚP:
  1) PHÁT HIỆN — mỗi nguồn tự chọn collector theo SOURCES.Type (Source.fetch_type):
     "rss" -> RssCollector (nhẹ: title/summary/category, KHÔNG fetch full bài);
     "html" -> HttpFirstCollector (crawl trang mục + full bài luôn, như cũ).
  2) LỌC + GỘP — normalize (dedup content-hash + whitelist watchlist + relevance)
     trên TOÀN BỘ ứng viên (mọi nguồn) MỘT LƯỢT -> gom near-duplicate CHÉO NGUỒN
     theo tiêu đề (curation.enrich.is_near_duplicate): giữ 1 đại diện/cụm, gộp
     url các báo khác vào cột "Sources" -> loại tiếp cụm đã có trong CONTEXT
     (across-run).
  3) FULL-FETCH — CHỈ đại diện có nguồn gốc RSS (chưa có full bài) mới được
     HttpFirstCollector.fetch_one() tải full + normalize lại; đại diện gốc html
     đã có full body sẵn từ bước 1. Persist CHỈ bản full cuối cùng.

Sau đó: classify (nhóm + Field/Topic theo TAXONOMY) + marketing_score + hotness_pct
(curation/enrich.py, $0) + HookAgent(MockLLM) sinh hook ($0) -> ghi 1 dòng PENDING
vào tab CONTEXT. Sau khi xong TẤT CẢ nguồn: sắp CONTEXT theo Hot% giảm dần. Nhật
ký ghi tab LOG + in console.

KHÔNG scale: bản nếm thử. Không gọi LLM đắt (MockLLM), không sinh nội dung.

Chạy:
    python scripts/review_to_sheet.py
    python scripts/review_to_sheet.py --limit 3

spreadsheet_id/creds_path đọc theo thứ tự: biến môi trường (TWMKT_SHEET_ID /
TWMKT_SHEETS_CREDS) NẾU đặt, ngược lại lấy từ config/settings.yaml (mục sheets).
Không bắt buộc đặt ENV. Xem docs/google_sheets_setup.md để tạo service account.
"""
from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

from twmkt import factory  # noqa: E402
from twmkt.agents.base import MockLLM  # noqa: E402
from twmkt.agents.hook import HookAgent  # noqa: E402
from twmkt.config import load_settings  # noqa: E402
from twmkt.curation import normalize  # noqa: E402
from twmkt.curation.config import CurationConfig, _load_lines  # noqa: E402
from twmkt.curation.enrich import (  # noqa: E402
    classify, classify_field_topic, groups_from_settings, hotness_pct,
    is_near_duplicate, marketing_score, taxonomy_from_settings,
)
from twmkt.models import CleanDocument, ResearchBrief, Source  # noqa: E402
from twmkt.sheets_board import SheetsBoard  # noqa: E402

# Mặc định nhóm ưu tiên khi tab SETTINGS chưa có/thiếu khóa PriorityGroups
# (khớp seed row do SheetsBoard.ensure_tabs() ghi lần đầu).
_DEFAULT_PRIORITY_GROUPS = ["ChinhSach", "ViMoVN"]


def _watchlist_curation(settings) -> CurationConfig:
    """CurationConfig như config nhưng ÉP whitelist = watchlist CỐ ĐỊNH
    (curation.watchlist_file, mặc định data/tickers.txt) — danh sách mã do team
    tự quản lý/chỉnh trực tiếp, đọc NGUYÊN file; KHÔNG có script nào tính/sinh
    lại whitelist này (demo nhỏ, sạch hơn danh sách đầy đủ tickers_full.txt)."""
    base = CurationConfig.from_settings(settings)
    watchlist = {t.upper() for t in _load_lines(
        settings.get("curation.watchlist_file", "data/tickers.txt"))}
    return replace(base, tickers=watchlist)


def _score_weights(settings) -> dict:
    """Trọng số marketing_score/hotness_pct từ curation.score (config-first)."""
    def g(path: str, default: int) -> int:
        return int(settings.get(path, default))

    return {
        "marketing": dict(
            w_ticker=g("curation.score.marketing.ticker", 3),
            w_macro=g("curation.score.marketing.macro", 2),
            w_news=g("curation.score.marketing.news", 1),
        ),
        "hotness": dict(
            w_priority=g("curation.score.hotness.priority", 4),
            w_ticker=g("curation.score.hotness.ticker", 2),
            w_news=g("curation.score.hotness.news", 2),
            w_macro=g("curation.score.hotness.macro", 2),
        ),
    }


# =====================================================================
# Hàm THUẦN (không mạng) — LỚP 2: gộp near-duplicate CHÉO NGUỒN.
# =====================================================================
def cluster_near_duplicates(docs: list[CleanDocument]) -> list[dict]:
    """Gom `docs` (đã qua normalize — MỌI nguồn trộn chung) thành các cụm theo
    tiêu đề GẦN GIỐNG (curation.enrich.is_near_duplicate), bất kể nguồn gốc.

    Giữ đại diện ĐẦU TIÊN mỗi cụm (`doc`); url các bài trùng còn lại (nguồn
    KHÁC đưa cùng tin) gộp vào `other_urls`. Hàm THUẦN — test được, không mạng.
    """
    clusters: list[dict] = []
    for doc in docs:
        matched = next(
            (cl for cl in clusters if is_near_duplicate(doc.title, [cl["doc"].title])),
            None,
        )
        if matched:
            if doc.url != matched["doc"].url and doc.url not in matched["other_urls"]:
                matched["other_urls"].append(doc.url)
            continue
        clusters.append({"doc": doc, "other_urls": []})
    return clusters


def run(*, limit: int = 3) -> dict:
    settings = load_settings()

    # Ưu tiên ENV (ghi đè tạm) -> settings.yaml (mục sheets). ENV không bắt buộc.
    sheet_id = (os.environ.get("TWMKT_SHEET_ID") or settings.get("sheets.spreadsheet_id") or "").strip()
    creds = (os.environ.get("TWMKT_SHEETS_CREDS") or settings.get("sheets.creds_path") or "").strip()
    if not sheet_id or not creds:
        raise SystemExit(
            "Thiếu spreadsheet_id/creds_path. Đặt ở config/settings.yaml (mục sheets) "
            "hoặc biến môi trường TWMKT_SHEET_ID / TWMKT_SHEETS_CREDS. Xem "
            "docs/google_sheets_setup.md (tạo service account + chia sẻ Sheet)."
        )

    board = SheetsBoard(spreadsheet_id=sheet_id, creds_path=creds)
    created = board.ensure_tabs()   # tạo 8 tab + header lần đầu
    if created:
        board.log("INFO", f"Tạo tab lần đầu: {', '.join(created)}")

    # ① Ưu tiên nguồn khai ở tab SOURCES; chưa có -> lấy từ config (settings.yaml).
    sources = board.read_sources() or factory.build_sources(settings)
    if not sources:
        raise SystemExit("Không có nguồn nào (tab SOURCES trống và config cũng trống).")
    sources_by_name: dict[str, Source] = {s.name: s for s in sources}

    # PriorityGroups + TAXONOMY: đọc LIVE từ Sheet MỖI LẦN CHẠY (team đổi theo
    # pha thị trường/phân loại không cần sửa code/deploy lại).
    priority_groups = board.read_priority_groups(default=_DEFAULT_PRIORITY_GROUPS)
    taxonomy = board.read_taxonomy(default=taxonomy_from_settings(settings))
    board.log("INFO", f"PriorityGroups (từ SETTINGS): {', '.join(priority_groups)}")

    # Dựng SẴN cả 2 collector — tái dùng cho mọi nguồn theo fetch_type, tránh
    # dựng lại mỗi nguồn. html_collector CÒN dùng để full-fetch (tầng 3) item rss.
    html_collector = factory.build_collector_for_source(
        Source("_", "_", fetch_type="html"), settings)
    rss_collector = factory.build_collector_for_source(
        Source("_", "_", fetch_type="rss"), settings)

    curation = _watchlist_curation(settings)
    groups = groups_from_settings(settings)
    weights = _score_weights(settings)
    store = factory.build_store(settings)
    llm = MockLLM()   # $0 token — hook chạy fallback tất định

    # --- TẦNG 1: PHÁT HIỆN (rss nhẹ hoặc html full ngay) trên TỪNG nguồn -----
    raw_docs = []
    per_source: list[dict] = []
    for s in sources:
        collector = factory.build_collector_for_source(
            s, settings, html_collector=html_collector, rss_collector=rss_collector)
        print(f"[{s.fetch_type}] {s.name} ({s.url}) — limit {limit}...")
        docs = collector.collect(s, limit=limit)
        raw_docs.extend(docs)
        per_source.append({"name": s.name, "fetch_type": s.fetch_type, "crawled": len(docs)})

    # --- TẦNG 2: chuẩn hóa (dedup content-hash + whitelist + relevance) MỘT
    # LƯỢT trên TOÀN BỘ ứng viên, rồi gộp near-duplicate CHÉO NGUỒN theo tiêu đề. --
    clean = normalize(raw_docs, curation)
    clusters = cluster_near_duplicates(clean)

    seen_titles = board.context_titles()   # đã có trong CONTEXT (across-run)
    survivors = []
    skipped_dup_run = 0
    for cl in clusters:
        if is_near_duplicate(cl["doc"].title, seen_titles):
            skipped_dup_run += 1
            continue
        survivors.append(cl)
        seen_titles.append(cl["doc"].title)

    # --- TẦNG 3: full-fetch CHỈ cho đại diện gốc RSS (chưa có full bài) ------
    final: list[dict] = []
    full_fetch_failed = 0
    for cl in survivors:
        c = cl["doc"]
        src = sources_by_name.get(c.source)
        if src is not None and src.fetch_type == "rss":
            full_raw = html_collector.fetch_one(src, c.url)
            if full_raw is None:
                full_fetch_failed += 1
                continue
            full_raw.category_hint = c.category_hint or full_raw.category_hint
            full_clean = normalize([full_raw], curation)
            if not full_clean:
                full_fetch_failed += 1
                continue
            c = full_clean[0]
        final.append({"source": src, "doc": c, "other_urls": cl["other_urls"]})

    # --- Persist (CHỈ bản full cuối cùng) + ghi CONTEXT ----------------------
    stored = store.upsert([f["doc"] for f in final])
    written = 0
    for f in final:
        src, c, other_urls = f["source"], f["doc"], f["other_urls"]
        full = f"{c.title}. {c.markdown}"
        macro_hits = curation.macro_hits(full)
        labels = classify(full, c.tickers, tags=c.tags, groups=groups)
        hints = [c.category_hint, src.field_hint if src else ""]
        field_val, topic_val = classify_field_topic(full, hints=hints, taxonomy=taxonomy)
        score = marketing_score(full, c.tickers, macro_hits=macro_hits, **weights["marketing"])
        hot = hotness_pct(full, c.tickers, labels, priority_groups=priority_groups,
                          macro_hits=macro_hits, **weights["hotness"])

        brief = ResearchBrief(topic=c.title, tickers=c.tickers,
                              thesis=c.title, key_points=[c.title])
        hook = HookAgent(llm).run(brief)   # $0 (MockLLM -> fallback)

        if board.write_context(title=c.title, hook_line=hook.headlines[0], url=c.url,
                               score=score, hot_pct=hot, publisher=(src.name if src else c.source),
                               field=field_val, topic=topic_val, group=", ".join(labels),
                               other_sources=other_urls, tickers=c.tickers):
            written += 1   # bỏ trùng theo url (Source) -> chỉ đếm dòng thực ghi

    board.sort_context_by_hot()   # CONTEXT sắp theo Hot% giảm dần sau khi ghi xong

    totals = {
        "crawled": len(raw_docs), "kept": len(clean), "clusters": len(clusters),
        "stored": stored, "written": written,
        "skipped_dup": skipped_dup_run, "full_fetch_failed": full_fetch_failed,
    }
    board.log("INFO", f"TỔNG: crawled {totals['crawled']} / kept {totals['kept']} / "
                      f"cụm(gộp trùng chéo nguồn) {totals['clusters']} / stored {totals['stored']} / "
                      f"CONTEXT {totals['written']} / bỏ (đã có) {totals['skipped_dup']} / "
                      f"full-fetch lỗi {totals['full_fetch_failed']}")
    _print_summary(per_source, totals)
    return {"per_source": per_source, "totals": totals}


def _print_summary(per_source: list[dict], totals: dict) -> None:
    print("\n========== DEMO REVIEW -> GOOGLE SHEET (CONTEXT) ==========")
    for s in per_source:
        print(f"• [{s['fetch_type']}] {s['name']}: crawled {s['crawled']}")
    print("---------- Tổng (sau lọc + gộp near-duplicate chéo nguồn) ----------")
    print(f"crawled {totals['crawled']} | kept(sau normalize) {totals['kept']} | "
          f"cụm duy nhất {totals['clusters']} | full-fetch lỗi {totals['full_fetch_failed']}")
    print(f"stored {totals['stored']} | CONTEXT {totals['written']} dòng chờ duyệt | "
          f"bỏ (đã có trong CONTEXT) {totals['skipped_dup']}")
    print("Mở tab CONTEXT trên Google Sheet để duyệt (cột Status; tick Use để chọn dùng);"
         " đã sắp theo Hot% giảm dần.")


def _parse_args(argv: list[str]):
    import argparse
    ap = argparse.ArgumentParser(description="Phát hiện (rss)/crawl (html) thật -> "
                                 "ghi title+hook lên Google Sheet để duyệt ($0).")
    ap.add_argument("--limit", type=int, default=3, help="Số bài tối đa/nguồn (demo nhỏ 2-3).")
    return ap.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    run(limit=args.limit)
