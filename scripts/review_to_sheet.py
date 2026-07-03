"""DEMO khép kín, $0 token: nguồn THẬT -> data sạch -> title + hook lên Google Sheet.

Luồng: SheetsBoard.ensure_tabs() -> đọc nguồn (ưu tiên tab SOURCES, fallback
config) -> đọc PriorityGroups LIVE từ tab SETTINGS -> HttpFirstCollector crawl
THẬT (nhỏ: 3 bài/nguồn, rate-limit 1.5s+jitter) -> normalize + relevance
(whitelist = watchlist CỐ ĐỊNH data/tickers.txt, ~325 mã do team quản lý thủ công
— đọc NGUYÊN file, KHÔNG có script nào tính/sinh lại nó)
-> FileDocumentStore persist -> mỗi bài giữ: classify (nhóm chủ đề) + marketing_score
+ hotness_pct (curation/enrich.py, $0) + HookAgent(MockLLM) sinh hook ($0) -> bỏ
qua nếu url trùng HOẶC tiêu đề gần trùng (is_near_duplicate) -> ghi 1 dòng PENDING
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
    classify, groups_from_settings, hotness_pct, is_near_duplicate, marketing_score,
)
from twmkt.models import ResearchBrief  # noqa: E402
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
    created = board.ensure_tabs()   # tạo 7 tab + header lần đầu
    if created:
        board.log("INFO", f"Tạo tab lần đầu: {', '.join(created)}")

    # ① Ưu tiên nguồn khai ở tab SOURCES; chưa có -> lấy từ config (settings.yaml).
    sources = board.read_sources() or factory.build_sources(settings)
    if not sources:
        raise SystemExit("Không có nguồn nào (tab SOURCES trống và config cũng trống).")

    # PriorityGroups: đọc LIVE từ tab SETTINGS MỖI LẦN CHẠY (team đổi theo pha
    # thị trường không cần sửa code/deploy lại).
    priority_groups = board.read_priority_groups(default=_DEFAULT_PRIORITY_GROUPS)
    board.log("INFO", f"PriorityGroups (từ SETTINGS): {', '.join(priority_groups)}")

    collector = factory.build_collector(settings, offline=False)   # HttpFirstCollector thật
    curation = _watchlist_curation(settings)
    groups = groups_from_settings(settings)
    weights = _score_weights(settings)
    store = factory.build_store(settings)
    llm = MockLLM()   # $0 token — hook chạy fallback tất định

    # Tiêu đề đã có trong CONTEXT (đọc 1 lần, cập nhật dần trong vòng lặp) —
    # chặn near-duplicate CẢ across-run lẫn giữa các nguồn trong CÙNG lần chạy
    # (vd 1 tin được cả doanh-nghiep lẫn vi-mo đưa lại).
    seen_titles = board.context_titles()

    totals = {"crawled": 0, "kept": 0, "stored": 0, "written": 0, "skipped_dup": 0}
    per_source: list[dict] = []
    for s in sources:
        print(f"[crawl] {s.name} ({s.url}) — limit {limit}...")
        raw = collector.collect(s, limit=limit)
        clean = normalize(raw, curation)              # dedup + whitelist watchlist cố định + relevance
        stored = store.upsert(clean)                  # persist (dedup across-run)

        written = skipped_dup = 0
        for doc in clean:
            if is_near_duplicate(doc.title, seen_titles):
                skipped_dup += 1
                continue

            full = f"{doc.title}. {doc.markdown}"
            macro_hits = curation.macro_hits(full)
            labels = classify(full, doc.tickers, tags=doc.tags, groups=groups)
            score = marketing_score(full, doc.tickers, macro_hits=macro_hits,
                                    **weights["marketing"])
            hot = hotness_pct(full, doc.tickers, labels, priority_groups=priority_groups,
                              macro_hits=macro_hits, **weights["hotness"])

            brief = ResearchBrief(topic=doc.title, tickers=doc.tickers,
                                  thesis=doc.title, key_points=[doc.title])
            hook = HookAgent(llm).run(brief)          # $0 (MockLLM -> fallback)

            if board.write_context(title=doc.title, hook_line=hook.headlines[0],
                                    url=doc.url, score=score, hot_pct=hot,
                                    group=", ".join(labels), tickers=doc.tickers):
                written += 1                # bỏ trùng theo url -> chỉ đếm dòng thực ghi
                seen_titles.append(doc.title)   # cập nhật ngay -> chặn trùng trong nguồn sau

        msg = (f"{s.name}: crawled {len(raw)} / kept {len(clean)} / stored {stored} / "
              f"CONTEXT {written} / bỏ (gần trùng) {skipped_dup}")
        board.log("INFO", msg)
        print("  " + msg)
        per_source.append({"name": s.name, "crawled": len(raw), "kept": len(clean),
                           "stored": stored, "written": written, "skipped_dup": skipped_dup})
        totals["crawled"] += len(raw); totals["kept"] += len(clean)
        totals["stored"] += stored; totals["written"] += written
        totals["skipped_dup"] += skipped_dup

    board.sort_context_by_hot()   # CONTEXT sắp theo Hot% giảm dần sau khi ghi xong
    board.log("INFO", f"TỔNG: crawled {totals['crawled']} / kept {totals['kept']} / "
                      f"stored {totals['stored']} / CONTEXT {totals['written']} / "
                      f"bỏ (gần trùng) {totals['skipped_dup']}")
    _print_summary(per_source, totals)
    return {"per_source": per_source, "totals": totals}


def _print_summary(per_source: list[dict], totals: dict) -> None:
    print("\n========== DEMO REVIEW -> GOOGLE SHEET (CONTEXT) ==========")
    for s in per_source:
        print(f"• {s['name']}: crawled {s['crawled']} | kept {s['kept']} | "
              f"stored {s['stored']} | ghi CONTEXT {s['written']} | "
              f"bỏ (gần trùng) {s['skipped_dup']}")
    print("---------- Tổng ----------")
    print(f"crawled {totals['crawled']} | kept {totals['kept']} | "
          f"stored {totals['stored']} | CONTEXT {totals['written']} dòng chờ duyệt | "
          f"bỏ (gần trùng) {totals['skipped_dup']}")
    print("Mở tab CONTEXT trên Google Sheet để duyệt (cột Status; tick Use để chọn dùng);"
         " đã sắp theo Hot% giảm dần.")


def _parse_args(argv: list[str]):
    import argparse
    ap = argparse.ArgumentParser(description="Crawl thật -> ghi title+hook lên Google Sheet để duyệt ($0).")
    ap.add_argument("--limit", type=int, default=3, help="Số bài tối đa/nguồn (demo nhỏ 2-3).")
    return ap.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    run(limit=args.limit)
