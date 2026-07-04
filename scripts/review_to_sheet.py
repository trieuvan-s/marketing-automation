"""DEMO khép kín, $0 token: nguồn THẬT -> data sạch -> title + hook lên Google Sheet.

MÔ HÌNH THU THẬP 3 LỚP:
  1) PHÁT HIỆN — mỗi nguồn tự chọn collector theo SOURCES.Type (Source.fetch_type):
     "rss" -> RssCollector (nhẹ: title/summary/category, KHÔNG fetch full bài);
     "html" -> HttpFirstCollector (crawl trang mục + full bài luôn, như cũ).
  2) LỌC + GỘP — normalize (dedup content-hash + whitelist watchlist + relevance)
     trên TOÀN BỘ ứng viên (mọi nguồn) MỘT LƯỢT -> gom SỰ KIỆN chéo nguồn
     (curation.enrich.cluster_by_event): mỗi cụm GIỮ báo Priority CAO NHẤT làm
     đại diện, url các báo khác gộp vào cột "Sources".
  3) FULL-FETCH — CHỈ đại diện có nguồn gốc RSS (chưa có full bài) mới được
     HttpFirstCollector.fetch_one() tải full + normalize lại; đại diện gốc html
     đã có full body sẵn từ bước 1. Persist CHỈ bản full cuối cùng.

Sau đó: classify (nhóm, tối đa 2 nhãn) + Field/Topic CHỈ theo TAXONOMY (keyword,
KHÔNG dùng <category> thô RSS) + marketing_score + hotness_pct (curation/enrich.py,
$0) + HookAgent(MockLLM) sinh hook ($0). Sắp theo Hot% giảm dần rồi UPSERT tab
CONTEXT (XÓA vùng dữ liệu, ghi lại) -> hết trộn dòng cũ. Nhật ký ghi tab LOG + console.

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
    EventItem, classify, classify_field_topic, cluster_by_event,
    groups_from_settings, hotness_pct, marketing_score, taxonomy_from_settings,
)
from twmkt.models import ResearchBrief, Source  # noqa: E402
from twmkt.sheets_board import SheetsBoard, context_row  # noqa: E402

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


def run(*, limit: int = 3, sync_sources: bool = False, from_config: bool = False) -> dict:
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

    # --sync-sources: ghi ĐÈ tab SOURCES bằng nguồn đã verify trong settings.yaml
    # (schema mới), xoá dòng cũ/URL rỗng — sửa lỗi lệch schema gây crawled 0.
    if sync_sources:
        n = board.sync_sources_from_settings(settings)
        board.log("INFO", f"Đồng bộ {n} nguồn settings.yaml -> tab SOURCES (schema mới)")
        print(f"[sync] ghi {n} nguồn vào tab SOURCES (schema mới, xoá dòng cũ).")

    # ① Nguồn: --from-config -> LẤY THẲNG từ settings.yaml (bỏ qua sheet, kiểm
    #    chứng nhanh); mặc định -> ưu tiên tab SOURCES, chưa có/không hợp lệ ->
    #    fallback config.
    if from_config:
        sources = factory.build_sources(settings)
        print(f"[from-config] dùng {len(sources)} nguồn trực tiếp từ settings.yaml (bỏ qua SOURCES).")
    else:
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
    # LƯỢT trên TOÀN BỘ ứng viên, rồi gộp SỰ KIỆN chéo nguồn — GIỮ báo Priority
    # cao (cluster_by_event), url báo khác gộp vào cột Sources. --
    clean = normalize(raw_docs, curation)
    by_url = {c.url: c for c in clean}
    items = [
        EventItem(
            title=c.title, url=c.url, publisher=c.source,
            priority=(sources_by_name[c.source].priority if c.source in sources_by_name else 0),
        )
        for c in clean
    ]
    clusters = cluster_by_event(items, threshold=0.6)

    # --- TẦNG 3: full-fetch CHỈ cho đại diện gốc RSS (chưa có full bài) ------
    final: list[dict] = []
    full_fetch_failed = 0
    for cl in clusters:
        c = by_url[cl.item.url]
        src = sources_by_name.get(c.source)
        if src is not None and src.fetch_type == "rss":
            full_raw = html_collector.fetch_one(src, c.url)
            if full_raw is None:
                full_fetch_failed += 1
                continue
            full_clean = normalize([full_raw], curation)
            if not full_clean:
                full_fetch_failed += 1
                continue
            c = full_clean[0]
        final.append({"source": src, "doc": c, "other_urls": cl.other_urls})

    # --- Persist + dựng hàng CONTEXT (tất định, $0), sắp Hot% giảm dần -------
    stored = store.upsert([f["doc"] for f in final])
    scored_rows: list[tuple[int, list[str]]] = []
    for f in final:
        src, c, other_urls = f["source"], f["doc"], f["other_urls"]
        full = f"{c.title}. {c.markdown}"
        macro_hits = curation.macro_hits(full)
        labels = classify(full, c.tickers, tags=c.tags, groups=groups)[:2]  # Group tối đa 2 nhãn
        # Field/Topic CHỈ theo TAXONOMY (keyword) — KHÔNG dùng <category> thô RSS.
        field_hint = [src.field_hint] if src and src.field_hint else None
        field_val, topic_val = classify_field_topic(full, hints=field_hint, taxonomy=taxonomy)
        score = marketing_score(full, c.tickers, macro_hits=macro_hits, **weights["marketing"])
        hot = hotness_pct(full, c.tickers, labels, priority_groups=priority_groups,
                          macro_hits=macro_hits, **weights["hotness"])
        hook = HookAgent(llm).run(ResearchBrief(   # $0 (MockLLM -> fallback)
            topic=c.title, tickers=c.tickers, thesis=c.title, key_points=[c.title]))
        scored_rows.append((hot, context_row(
            title=c.title, hook_line=hook.headlines[0], source_url=c.url, score=score,
            hot_pct=hot, publisher=(src.name if src else c.source), field=field_val,
            topic=topic_val, group=", ".join(labels), other_sources=other_urls,
            tickers=c.tickers)))

    scored_rows.sort(key=lambda x: x[0], reverse=True)   # Hot% giảm dần
    # UPSERT: xóa vùng dữ liệu CONTEXT (giữ header) rồi ghi lại -> hết trộn dòng cũ.
    written = board.replace_context([row for _, row in scored_rows])

    totals = {
        "crawled": len(raw_docs), "kept": len(clean), "clusters": len(clusters),
        "stored": stored, "written": written, "full_fetch_failed": full_fetch_failed,
    }
    board.log("INFO", f"TỔNG: crawled {totals['crawled']} / kept {totals['kept']} / "
                      f"cụm(gộp sự kiện chéo nguồn) {totals['clusters']} / stored {totals['stored']} / "
                      f"CONTEXT {totals['written']} (UPSERT) / full-fetch lỗi {totals['full_fetch_failed']}")
    _print_summary(per_source, totals)
    return {"per_source": per_source, "totals": totals}


def _print_summary(per_source: list[dict], totals: dict) -> None:
    print("\n========== DEMO REVIEW -> GOOGLE SHEET (CONTEXT) ==========")
    for s in per_source:
        print(f"• [{s['fetch_type']}] {s['name']}: crawled {s['crawled']}")
    print("---------- Tổng (sau lọc + gộp sự kiện chéo nguồn, giữ báo Priority cao) ----------")
    print(f"crawled {totals['crawled']} | kept(sau normalize) {totals['kept']} | "
          f"cụm duy nhất {totals['clusters']} | full-fetch lỗi {totals['full_fetch_failed']}")
    print(f"stored {totals['stored']} | CONTEXT {totals['written']} dòng (UPSERT — ghi đè mỗi lần chạy)")
    print("Mở tab CONTEXT trên Google Sheet để duyệt (cột Status; tick Use để chọn dùng);"
         " đã sắp theo Hot% giảm dần.")


def _parse_args(argv: list[str]):
    import argparse
    ap = argparse.ArgumentParser(description="Phát hiện (rss)/crawl (html) thật -> "
                                 "ghi title+hook lên Google Sheet để duyệt ($0).")
    ap.add_argument("--limit", type=int, default=3, help="Số bài tối đa/nguồn (demo nhỏ 2-3).")
    ap.add_argument("--sync-sources", action="store_true",
                    help="Ghi đè tab SOURCES bằng nguồn trong settings.yaml (schema mới) rồi chạy.")
    ap.add_argument("--from-config", action="store_true",
                    help="Lấy nguồn thẳng từ settings.yaml, bỏ qua tab SOURCES (kiểm chứng nhanh).")
    return ap.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    run(limit=args.limit, sync_sources=args.sync_sources, from_config=args.from_config)
