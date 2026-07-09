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
$0) + HookAgent(MockLLM) sinh hook ($0). UPSERT vào CONTEXT THEO URL: url ĐÃ CÓ
-> BỎ QUA HOÀN TOÀN (giữ nguyên dòng cũ — Status/Execute/Hook/Notes không đổi,
KHÔNG xoá/ghi đè); url CHƯA CÓ -> thêm dòng PENDING mới. Sắp lại TOÀN BẢNG theo
Hot% giảm dần sau khi ghi. Nhật ký ghi tab LOG + console.

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
from twmkt.agents.hook import HookAgent, _try_json  # noqa: E402
from twmkt.config import load_settings  # noqa: E402
from twmkt.curation import normalize  # noqa: E402
from twmkt.curation.config import CurationConfig, _load_lines  # noqa: E402
from twmkt.curation.enrich import (  # noqa: E402
    classify, cluster_by_event, groups_from_settings, hotness_pct, marketing_score,
)
from twmkt.models import ResearchBrief, Source  # noqa: E402
from twmkt.sheets_board import CONTEXT_HEADER, SheetsBoard, context_row  # noqa: E402
from twmkt.utils.telegram_notifier import make_notifier  # noqa: E402

_I_CONTEXT = [h.strip().lower() for h in CONTEXT_HEADER].index("context")
_I_SOURCE = [h.strip().lower() for h in CONTEXT_HEADER].index("source")

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


def run(*, limit: int = 3, sync_sources: bool = False, from_config: bool = False,
        debug: bool = False, offline: bool = False, setup: bool = False) -> dict:
    settings = load_settings()
    notifier = make_notifier(settings)   # PHASE TELE — no-op êm nếu chưa cấu hình

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
    # ensure_tabs() mặc định RẺ (chỉ tạo/format khi phát hiện tab thiếu/header sai,
    # xem SheetsBoard._headers_need_setup) — giảm lượt gọi Sheets API mỗi lần chạy
    # lịch (né quota 429). --setup ép chạy đầy đủ (tạo tab/seed/format lại).
    created = board.ensure_tabs(force=setup)
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

    # PriorityGroups: đọc LIVE từ tab SETTINGS MỖI LẦN CHẠY (team đổi theo pha
    # thị trường không cần sửa code/deploy lại).
    priority_groups = board.read_priority_groups(default=_DEFAULT_PRIORITY_GROUPS)
    board.log("INFO", f"PriorityGroups (từ SETTINGS): {', '.join(priority_groups)}")

    # Sheet KHÔNG có trigger đẩy (push) sang Python -> đồng bộ Execute PULL-based
    # ở đây (bổ sung produce_from_sheet.py) để dòng người dùng vừa bấm APPROVE
    # thủ công trên Sheet cũng được đặt Execute=RUN kể cả khi chỉ lịch crawl chạy
    # (schedule 4h) trước lịch --draft (30'). Muốn ĐỒNG BỘ NGAY không đợi lịch ->
    # python scripts/produce_from_sheet.py --sync-only.
    n_synced = board.sync_approve_execute_flags()
    if n_synced:
        board.log("INFO", f"Đồng bộ Execute=RUN cho {n_synced} dòng vừa APPROVE.")

    # --- LLM cho HOOK (tầng content_model = Sonnet, bọc LLMRouter đo token/chi phí)
    # LÙI MƯỢT nhưng CÓ CẢNH BÁO RÕ: banner IN RA mỗi lần chạy, không im lặng.
    # CHỈ Hook gọi LLM ở script này (Researcher không chạy ở đây).
    # `offline=True` ép Hook $0 (fallback tất định) BẤT KỂ API key có hiệu lực
    # hay không -- dùng cho lịch chạy tự động không giám sát (xem run_scheduler.py
    # / power_on.py, tránh phát sinh chi phí API mỗi giờ ngoài ý muốn).
    llm = factory.llm_status(settings)
    print(llm.banner)
    use_llm = llm.use_llm and not offline
    hook_llm = factory.build_hook_llm(settings, offline=not use_llm)   # Sonnet (content_model)
    engine = factory.model_engine_label(llm.hook_model, use_llm=use_llm)
    board.log("INFO", llm.banner, engine=engine)

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
    # cao (cluster_by_event, item = dict), url báo khác gộp vào ô Source. --
    clean = normalize(raw_docs, curation)
    by_url = {c.url: c for c in clean}
    items = [
        {"title": c.title, "url": c.url, "publisher": c.source,   # publisher/priority nội bộ
         "priority": (sources_by_name[c.source].priority if c.source in sources_by_name else 0)}
        for c in clean
    ]
    clusters = cluster_by_event(items, threshold=0.6)

    # --- TẦNG 3: full-fetch CHỈ cho đại diện gốc RSS (chưa có full bài) ------
    final: list[dict] = []
    full_fetch_failed = 0
    for cl in clusters:
        c = by_url[cl["rep"]["url"]]
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
        final.append({"doc": c, "other_urls": cl["sources"]})

    # --- Persist + dựng hàng CONTEXT (Hook qua Haiku/fallback), sắp Hot% giảm dần
    stored = store.upsert([f["doc"] for f in final])
    hook_agent = HookAgent(hook_llm)   # 1 instance dùng chung -> soi được last_prompt/last_raw
    scored_rows: list[tuple[int, list[str]]] = []
    for i, f in enumerate(final):
        c, other_urls = f["doc"], f["other_urls"]
        full = f"{c.title}. {c.markdown}"
        macro_hits = curation.macro_hits(full)
        labels = classify(full, c.tickers, tags=c.tags, groups=groups)
        group = ", ".join(labels[:2])              # Group tối đa 2 nhãn
        topic = labels[0] if labels else ""        # Topic = nhãn chính (thay taxonomy)
        score = marketing_score(full, c.tickers, macro_hits=macro_hits, **weights["marketing"])
        hot = hotness_pct(full, c.tickers, labels, priority_groups=priority_groups,
                          macro_hits=macro_hits, **weights["hotness"])
        hook = hook_agent.run(ResearchBrief(   # Sonnet (content_model) hoặc fallback $0
            topic=c.title, tickers=c.tickers, thesis=c.title,
            key_points=[c.title], evidence=[c.markdown[:400]]))
        if debug and i == 0:
            _print_hook_debug(hook_agent)
        scored_rows.append((hot, context_row(
            title=c.title, hook_line=hook.headlines[0], source_url=c.url, score=score,
            hot_pct=hot, topic=topic, group=group, other_sources=other_urls,
            tickers=c.tickers)))

    scored_rows.sort(key=lambda x: x[0], reverse=True)   # thứ tự chèn (thứ tự cuối do sort_context_by_hot)
    # UPSERT theo url: dòng ĐÃ CÓ giữ nguyên (không đụng Status/Execute/Hook/Notes
    # người dùng đã sửa), dòng MỚI mới được thêm. Rồi sắp LẠI TOÀN BẢNG theo Hot%.
    new_rows = board.upsert_context_rows([row for _, row in scored_rows])
    written = len(new_rows)
    board.sort_context_by_hot()

    # PHASE 4.6: mỗi dòng CONTEXT thật sự MỚI (không phải url trùng bị bỏ qua)
    # -> báo Telegram kèm link bài viết (Source = url gốc, có thể nhiều dòng
    # nếu gộp sự kiện chéo nguồn -> lấy dòng ĐẦU = url chính, khớp primary_url()
    # trong SheetsBoard.upsert_context_rows).
    for row in new_rows:
        topic = row[_I_CONTEXT] if _I_CONTEXT < len(row) else ""
        url = row[_I_SOURCE].splitlines()[0] if _I_SOURCE < len(row) and row[_I_SOURCE] else ""
        notifier.notify("new_topic", topic=topic, url=url)

    usage = hook_llm.usage.as_dict()
    totals = {
        "crawled": len(raw_docs), "kept": len(clean), "clusters": len(clusters),
        "stored": stored, "written": written, "full_fetch_failed": full_fetch_failed,
        "llm": usage, "use_llm": use_llm,
    }
    board.log("INFO", f"TỔNG: crawled {totals['crawled']} / kept {totals['kept']} / "
                      f"cụm(gộp sự kiện chéo nguồn) {totals['clusters']} / stored {totals['stored']} / "
                      f"CONTEXT +{totals['written']} dòng mới (url trùng đã bỏ qua) / "
                      f"full-fetch lỗi {totals['full_fetch_failed']}",
              engine=engine)
    _print_summary(per_source, totals)
    return {"per_source": per_source, "totals": totals}


def _print_hook_debug(hook_agent: HookAgent) -> None:
    """3 dòng debug (--debug --limit 1): soi vì sao Hook rơi về fallback hay
    không — llm type (LLMRouter -> base thật), raw response, parse JSON được không."""
    base = getattr(hook_agent.llm, "base", hook_agent.llm)
    print("\n----- [DEBUG] HookAgent lần gọi đầu tiên -----")
    print(f"[DEBUG] llm type: {type(hook_agent.llm).__name__}(base={type(base).__name__})")
    print(f"[DEBUG] raw: {hook_agent.last_raw!r}")
    print(f"[DEBUG] _try_json(raw) is None: {_try_json(hook_agent.last_raw) is None}")
    print("-----------------------------------------------\n")


def _print_summary(per_source: list[dict], totals: dict) -> None:
    print("\n========== DEMO REVIEW -> GOOGLE SHEET (CONTEXT) ==========")
    for s in per_source:
        print(f"• [{s['fetch_type']}] {s['name']}: crawled {s['crawled']}")
    print("---------- Tổng (sau lọc + gộp sự kiện chéo nguồn, giữ báo Priority cao) ----------")
    print(f"crawled {totals['crawled']} | kept(sau normalize) {totals['kept']} | "
          f"cụm duy nhất {totals['clusters']} | full-fetch lỗi {totals['full_fetch_failed']}")
    print(f"stored {totals['stored']} | CONTEXT +{totals['written']} dòng mới "
          f"(url đã có trong CONTEXT giữ nguyên, không đụng)")
    u = totals.get("llm", {})
    n = totals["written"] or 1
    if totals.get("use_llm") and u.get("calls"):
        per = u["cost_usd"] / n
        print(f"LLM Hook (Sonnet thật): {u['calls']} lượt ({u.get('by_model', {})}) | "
              f"in {u['in_tokens']} / out {u['out_tokens']} tok | "
              f"~${u['cost_usd']:.4f} tổng (~${per:.4f}/bài) | cache_hits {u['cache_hits']}")
    else:
        # Fallback: KHÔNG gọi API ($0 thật). Router vẫn đếm để ước tính nếu bật LLM.
        print(f"LLM Hook: FALLBACK tất định $0 (không gọi API). "
              f"Ước tính nếu bật LLM: ~${u.get('cost_usd', 0):.4f} "
              f"(~${u.get('cost_usd', 0) / n:.4f}/bài).")
    print("Mở tab CONTEXT trên Google Sheet để duyệt (cột Status: APPROVE -> tự đặt "
         "Execute=RUN, chờ produce_from_sheet.py sản xuất); đã sắp theo Hot% giảm dần.")


def _parse_args(argv: list[str]):
    import argparse
    ap = argparse.ArgumentParser(description="Phát hiện (rss)/crawl (html) thật -> "
                                 "ghi title+hook lên Google Sheet để duyệt ($0).")
    ap.add_argument("--limit", type=int, default=3, help="Số bài tối đa/nguồn (demo nhỏ 2-3).")
    ap.add_argument("--sync-sources", action="store_true",
                    help="Ghi đè tab SOURCES bằng nguồn trong settings.yaml (schema mới) rồi chạy.")
    ap.add_argument("--from-config", action="store_true",
                    help="Lấy nguồn thẳng từ settings.yaml, bỏ qua tab SOURCES (kiểm chứng nhanh).")
    ap.add_argument("--debug", action="store_true",
                    help="In 3 dòng debug Hook (llm type/raw/parsed) cho bài ĐẦU TIÊN.")
    ap.add_argument("--offline", action="store_true",
                    help="Ép Hook fallback tất định $0, bỏ qua Sonnet dù có API key.")
    ap.add_argument("--setup", action="store_true",
                    help="Ép chạy đầy đủ ensure_tabs (tạo/seed/format tab) dù header đã đúng "
                        "— mặc định BỎ QUA để giảm lượt gọi Sheets API (né quota 429).")
    return ap.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    run(limit=args.limit, sync_sources=args.sync_sources, from_config=args.from_config,
        debug=args.debug, offline=args.offline, setup=args.setup)
