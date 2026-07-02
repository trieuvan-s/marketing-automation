"""DEMO khép kín, $0 token: nguồn THẬT -> data sạch -> title + hook lên Google Sheet.

Luồng: SheetsBoard.ensure_tabs() -> đọc nguồn (ưu tiên tab SOURCES, fallback
config) -> HttpFirstCollector crawl THẬT (nhỏ: 3 bài/nguồn, rate-limit 1.5s+jitter)
-> normalize + relevance (whitelist VN30 data/tickers.txt) -> FileDocumentStore
persist -> mỗi bài giữ: HookAgent(MockLLM) sinh hook ($0) + chấm điểm -> ghi 1 dòng
PENDING vào tab CONTEXT để user DUYỆT. Nhật ký ghi tab LOG + in console.

KHÔNG scale: bản nếm thử. Không gọi LLM đắt (MockLLM), không sinh nội dung.

Chạy:
    # PowerShell: $env:TWMKT_SHEET_ID="..."; $env:TWMKT_SHEETS_CREDS="secrets/sa.json"
    python scripts/review_to_sheet.py
    python scripts/review_to_sheet.py --limit 3
Xem docs/google_sheets_setup.md để tạo service account + chia sẻ Sheet.
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
from twmkt.models import ResearchBrief  # noqa: E402
from twmkt.sheets_board import SheetsBoard, score_item  # noqa: E402


def _vn30_curation(settings) -> CurationConfig:
    """CurationConfig như config nhưng ÉP whitelist = VN30 (demo nhỏ, sạch)."""
    base = CurationConfig.from_settings(settings)
    vn30 = {t.upper() for t in _load_lines(settings.get("curation.vn30_file", "data/tickers.txt"))}
    return replace(base, tickers=vn30)


def run(*, limit: int = 3) -> dict:
    settings = load_settings()

    sheet_id = os.environ.get("TWMKT_SHEET_ID", "").strip()
    creds = os.environ.get("TWMKT_SHEETS_CREDS", "").strip()
    if not sheet_id or not creds:
        raise SystemExit(
            "Chưa đặt TWMKT_SHEET_ID / TWMKT_SHEETS_CREDS. Xem "
            "docs/google_sheets_setup.md (tạo service account + chia sẻ Sheet)."
        )

    board = SheetsBoard(spreadsheet_id=sheet_id, creds_path=creds)
    created = board.ensure_tabs()   # tạo 6 tab + header lần đầu
    if created:
        board.log("INFO", f"Tạo tab lần đầu: {', '.join(created)}")

    # ① Ưu tiên nguồn khai ở tab SOURCES; chưa có -> lấy từ config (settings.yaml).
    sources = board.read_sources() or factory.build_sources(settings)
    if not sources:
        raise SystemExit("Không có nguồn nào (tab SOURCES trống và config cũng trống).")

    collector = factory.build_collector(settings, offline=False)   # HttpFirstCollector thật
    curation = _vn30_curation(settings)
    store = factory.build_store(settings)
    llm = MockLLM()   # $0 token — hook chạy fallback tất định

    totals = {"crawled": 0, "kept": 0, "stored": 0, "written": 0}
    per_source: list[dict] = []
    for s in sources:
        print(f"[crawl] {s.name} ({s.url}) — limit {limit}...")
        raw = collector.collect(s, limit=limit)
        clean = normalize(raw, curation)              # dedup + whitelist VN30 + relevance
        stored = store.upsert(clean)                  # persist (dedup across-run)

        written = 0
        for doc in clean:
            full = f"{doc.title}. {doc.markdown}"
            brief = ResearchBrief(topic=doc.title, tickers=doc.tickers,
                                  thesis=doc.title, key_points=[doc.title])
            hook = HookAgent(llm).run(brief)          # $0 (MockLLM -> fallback)
            score = score_item(doc.tickers, curation.macro_hits(full))
            board.write_context(title=doc.title, hook_line=hook.headlines[0],
                                 url=doc.url, score=score, tickers=doc.tickers)
            written += 1

        msg = f"{s.name}: crawled {len(raw)} / kept {len(clean)} / stored {stored} / CONTEXT {written}"
        board.log("INFO", msg)
        print("  " + msg)
        per_source.append({"name": s.name, "crawled": len(raw), "kept": len(clean),
                           "stored": stored, "written": written})
        totals["crawled"] += len(raw); totals["kept"] += len(clean)
        totals["stored"] += stored; totals["written"] += written

    board.log("INFO", f"TỔNG: crawled {totals['crawled']} / kept {totals['kept']} / "
                      f"stored {totals['stored']} / CONTEXT {totals['written']}")
    _print_summary(per_source, totals)
    return {"per_source": per_source, "totals": totals}


def _print_summary(per_source: list[dict], totals: dict) -> None:
    print("\n========== DEMO REVIEW -> GOOGLE SHEET (CONTEXT) ==========")
    for s in per_source:
        print(f"• {s['name']}: crawled {s['crawled']} | kept {s['kept']} | "
              f"stored {s['stored']} | ghi CONTEXT {s['written']}")
    print("---------- Tổng ----------")
    print(f"crawled {totals['crawled']} | kept {totals['kept']} | "
          f"stored {totals['stored']} | CONTEXT {totals['written']} dòng chờ duyệt")
    print("Mở tab CONTEXT trên Google Sheet để duyệt (cột Decision).")


def _parse_args(argv: list[str]):
    import argparse
    ap = argparse.ArgumentParser(description="Crawl thật -> ghi title+hook lên Google Sheet để duyệt ($0).")
    ap.add_argument("--limit", type=int, default=3, help="Số bài tối đa/nguồn (demo nhỏ 2-3).")
    return ap.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    run(limit=args.limit)
