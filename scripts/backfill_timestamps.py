"""Backfill `timestamp` cho dòng ghi TRƯỚC bản vá 2026-07-29 (chạy 1 lần).

    python scripts/backfill_timestamps.py --dry-run
    python scripts/backfill_timestamps.py

VÌ SAO CẦN: trước bản vá, `render_*_to_sheet()` không truyền `ts` nên
`context_row()`/`content_row()` lấy `_now_ddmmyyyy()` — MỖI LƯỢT RENDER ghi đè
Timestamp thành hôm nay. Bản vá dừng được việc trôi tiếp, nhưng dòng CŨ không
có `timestamp` trong store thì vẫn rơi vào nhánh `now()` mãi mãi.

NGUỒN KHÔI PHỤC (theo thứ tự tin cậy):
  1. CONTEXT — corpus tài liệu `<data_root>/documents/<YYYY-MM-DD>/`: thư mục
     NGÀY chính là ngày crawl thật. Khớp về topic_key bằng cách tính lại
     `compute_topic_key(canonical_url or url)` — CÙNG hàm review_to_sheet.py
     dùng, nên ra đúng khoá. Đây là ngày THẬT, không phải đoán.
  2. Không khớp corpus -> lấy Timestamp ĐANG hiển thị trên Sheet. Giá trị này
     có thể ĐÃ SAI (bị ghi đè thành hôm nay) nhưng ít nhất từ nay nó ĐỨNG YÊN.
  3. CONTENT — không có corpus tương ứng; lấy từ Sheet như (2).

GIỚI HẠN THẲNG THẮN: dòng nào corpus không còn (quá `retention_days`) thì ngày
gốc đã MẤT THẬT, không khôi phục được. Script chỉ đóng băng giá trị hiện tại
để hết trôi, KHÔNG bịa ra ngày.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

import os  # noqa: E402

from twmkt.config import data_path, load_settings  # noqa: E402
from twmkt.curation.keys import compute_topic_key  # noqa: E402
from twmkt.sheets_board import SheetsBoard  # noqa: E402

from store import document_store as ds  # noqa: E402
from store import pipeline_store as ps  # noqa: E402


def corpus_dates(settings) -> dict[str, str]:
    """{topic_key: "DD/MM/YYYY"} suy từ thư mục NGÀY của corpus tài liệu."""
    root = data_path(settings.get("storage.documents_dir", "documents"), settings=settings)
    out: dict[str, str] = {}
    if not root.exists():
        return out
    for day_dir in sorted(root.iterdir()):
        if not day_dir.is_dir():
            continue
        try:
            y, m, d = day_dir.name.split("-")
        except ValueError:
            continue
        ddmmyyyy = f"{d}/{m}/{y}"
        for f in day_dir.glob("*.json"):
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
            except Exception:   # noqa: BLE001
                continue
            url = (doc.get("canonical_url") or doc.get("url") or "").strip()
            if not url:
                continue
            out.setdefault(compute_topic_key(url), ddmmyyyy)
    return out


def sheet_dates(settings) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    sid = (os.environ.get("TWMKT_SHEET_ID") or settings.get("sheets.spreadsheet_id") or "").strip()
    creds = (os.environ.get("TWMKT_SHEETS_CREDS") or settings.get("sheets.creds_path") or "").strip()
    board = SheetsBoard(spreadsheet_id=sid, creds_path=creds)
    ctx: dict[str, str] = {}
    rows = board._tab("CONTEXT").get_all_values()
    if rows:
        h = [c.strip().lower() for c in rows[0]]
        i_ts, i_tk = h.index("timestamp"), h.index("topickey")
        for r in rows[1:]:
            if len(r) > max(i_ts, i_tk) and r[i_tk].strip():
                ctx[r[i_tk].strip()] = r[i_ts].strip()
    con: dict[tuple[str, str], str] = {}
    rows = board._tab("CONTENT").get_all_values()
    if rows:
        h = [c.strip().lower() for c in rows[0]]
        i_ts, i_tk, i_ty = h.index("timestamp"), h.index("topickey"), h.index("type")
        for r in rows[1:]:
            if len(r) > max(i_ts, i_tk, i_ty) and r[i_tk].strip():
                con[(r[i_tk].strip(), r[i_ty].strip())] = r[i_ts].strip()
    return ctx, con


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    settings = load_settings()
    from_corpus = corpus_dates(settings)
    ctx_sheet, con_sheet = sheet_dates(settings)
    print(f"Corpus khớp được {len(from_corpus)} topic_key theo ngày crawl thật.")

    n_ctx = n_ctx_corpus = 0
    for tk in ds.list_topics(layer="raw"):
        raw = ps.read_raw(tk) or {}
        if (raw.get("timestamp") or "").strip():
            continue
        ts = from_corpus.get(tk)
        src = "corpus"
        if not ts:
            ts, src = ctx_sheet.get(tk, ""), "sheet"
        if not ts:
            continue
        print(f"  CONTEXT {tk[:8]} <- {ts} [{src}]")
        n_ctx += 1
        n_ctx_corpus += 1 if src == "corpus" else 0
        if not dry:
            ps.write_raw(tk, {**raw, "timestamp": ts})

    n_con = 0
    for tk in ds.list_topics(layer="content_output"):
        for type_ in ("article", "infographic", "video"):
            rec = ps.read_content_output(tk, type_)
            if rec is None or (rec.get("timestamp") or "").strip():
                continue
            ts = con_sheet.get((tk, type_), "")
            if not ts:
                continue
            print(f"  CONTENT {tk[:8]}/{type_} <- {ts} [sheet]")
            n_con += 1
            if not dry:
                ps.write_content_output(tk, type_, {**rec, "timestamp": ts})

    print(f"\nCONTEXT: {n_ctx} dòng ({n_ctx_corpus} lấy được NGÀY THẬT từ corpus)")
    print(f"CONTENT: {n_con} dòng (từ Sheet — giá trị có thể đã bị ghi đè trước đó)")
    if dry:
        print("--dry-run: KHÔNG ghi store.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
