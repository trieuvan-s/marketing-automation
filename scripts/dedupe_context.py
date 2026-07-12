"""Fix (a) Phase 2 — dọn dòng CONTEXT trùng TopicKey CŨ (dữ liệu TRƯỚC khi Fix
(a) Phase 1 chặn trùng mới ở SheetsBoard.upsert_context_rows — xem đó cho lý
do gốc: Source-URL literal-match cũ bỏ sót trùng khi 2 lượt crawl ghi Source-
text khác nhau cho CÙNG chủ đề). $0, tất định, không LLM, không mạng ngoài
Sheets API.

AN TOÀN-TRƯỚC: luôn DRY-RUN trước (mặc định, KHÔNG sửa gì) — chỉ xoá thật khi
--apply, và --apply LUÔN backup CONTEXT+CONTENT (duplicate_sheet, tab mới
"<name>_backup_<YYYY-MM-DD>") TRƯỚC khi xoá bất kỳ dòng nào.

RECOVERY URL: xác minh mỗi ô Source (dòng sẽ GIỮ lẫn dòng sẽ XOÁ) qua
spreadsheets.get (SheetsBoard.fetch_context_source_cells), KHÔNG dựa
get_all_values() — 1 ô có thể hiển thị TIÊU ĐỀ trong khi hyperlink ẩn bên
dưới là URL thật ("title-chip", xem sheets_board.extract_cell_url/
is_title_chip). Dòng GIỮ nào đang là title-chip -> đề xuất "chép" URL thật
(tự nó hoặc từ dòng XOÁ cùng nhóm, đã xác minh khớp nhau) vào Source, SURFACE
rõ trong dry-run để duyệt trước khi ghi.

Chạy:
    python scripts/dedupe_context.py                # dry-run: in kế hoạch, KHÔNG sửa gì
    python scripts/dedupe_context.py --apply         # backup + xoá + chép URL thật (sau khi đã duyệt dry-run)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

from twmkt.config import load_settings  # noqa: E402
from twmkt.sheets_board import (  # noqa: E402
    SheetsBoard, choose_keep_row, content_topic_keys,
    extract_cell_url, find_duplicate_context_groups, is_title_chip,
)


def _open_board(settings) -> SheetsBoard:
    sheet_id = (os.environ.get("TWMKT_SHEET_ID") or settings.get("sheets.spreadsheet_id") or "").strip()
    creds = (os.environ.get("TWMKT_SHEETS_CREDS") or settings.get("sheets.creds_path") or "").strip()
    if not sheet_id or not creds:
        raise SystemExit("Thiếu sheets.spreadsheet_id/creds_path (settings.yaml hoặc ENV).")
    return SheetsBoard(spreadsheet_id=sheet_id, creds_path=creds)


def _row_field(header_low: list[str], row: list[str], name: str) -> str:
    if name not in header_low:
        return ""
    i = header_low.index(name)
    return row[i].strip() if i < len(row) else ""


def build_plan(ctx_header: list[str], ctx_rows: list[list[str]],
               content_keys: set[tuple[str, str]]) -> list[dict]:
    """Kế hoạch dedupe (HÀM THUẦN, không mạng): với mỗi nhóm TopicKey trùng,
    xác định dòng GIỮ (choose_keep_row) + các dòng XOÁ. `content_keys` = tập
    (TopicKey, Type) đã có ở CONTENT (content_topic_keys()) -> tiebreak "có
    CONTENT con". Trả list[{"topic_key", "keep", "delete": [...]}]."""
    header_low = [h.strip().lower() for h in ctx_header]
    groups = find_duplicate_context_groups(ctx_header, ctx_rows)
    plan = []
    for tk, row_numbers in sorted(groups.items()):
        candidates = []
        for rn in row_numbers:
            row = ctx_rows[rn - 2]   # rn=2 -> ctx_rows[0]
            has_content = any(tk == k[0] for k in content_keys)
            candidates.append({
                "row": rn,
                "status": _row_field(header_low, row, "status"),
                "execute": _row_field(header_low, row, "execute"),
                "has_content": has_content,
            })
        keep_row = choose_keep_row(candidates)
        plan.append({
            "topic_key": tk,
            "keep": keep_row,
            "delete": sorted(rn for rn in row_numbers if rn != keep_row),
        })
    return plan


def _fmt_cell(cell: dict, formatted: str) -> str:
    url = extract_cell_url(cell)
    if url is None:
        return "KHÔNG có hyperlink (text thuần)"
    chip = " [TITLE-CHIP — hiển thị KHÁC href!]" if is_title_chip(cell, formatted) else ""
    return f"href={url!r}{chip}"


def dry_run(*, verbose: bool = True) -> dict:
    settings = load_settings()
    board = _open_board(settings)
    ctx_ws = board._tab("CONTEXT")
    ctx_values = ctx_ws.get_all_values()
    if len(ctx_values) < 2:
        print("CONTEXT trống hoặc chỉ có header — không có gì để dọn.")
        return {"groups": [], "warnings": []}
    ctx_header, ctx_rows = ctx_values[0], ctx_values[1:]
    header_low = [h.strip().lower() for h in ctx_header]

    content_ws = board._tab("CONTENT")
    content_values = content_ws.get_all_values()
    content_keys: set[tuple[str, str]] = set()
    content_missing: list[str] = []
    if len(content_values) >= 2:
        content_keys, content_missing = content_topic_keys(content_values[0], content_values[1:])

    plan = build_plan(ctx_header, ctx_rows, content_keys)
    if not plan:
        print("Không có TopicKey trùng nào trong CONTEXT — không cần dọn.")
        return {"groups": [], "warnings": []}

    all_delete_rows = sorted({r for g in plan for r in g["delete"]})
    all_keep_rows = sorted({g["keep"] for g in plan})
    cells = board.fetch_context_source_cells(all_delete_rows + all_keep_rows)

    warnings: list[str] = []
    repairs: dict[int, str] = {}   # keep_row -> URL nên chép vào Source

    print(f"\n{'=' * 70}\nDRY-RUN — Fix (a) Phase 2a: {len(plan)} nhóm TopicKey trùng "
         f"({sum(len(g['delete']) for g in plan)} dòng sẽ XOÁ)\n{'=' * 70}")

    for g in plan:
        tk, keep_row, del_rows = g["topic_key"], g["keep"], g["delete"]
        keep_data = ctx_rows[keep_row - 2]
        keep_context = _row_field(header_low, keep_data, "context")
        keep_cell = cells.get(keep_row, {})
        keep_formatted = _row_field(header_low, keep_data, "source")

        print(f"\n[TopicKey {tk}] — \"{keep_context[:70]}\"")
        print(f"  GIỮ  dòng {keep_row} (status={_row_field(header_low, keep_data, 'status')}, "
             f"execute={_row_field(header_low, keep_data, 'execute')}): "
             f"Source={keep_formatted[:60]!r} | {_fmt_cell(keep_cell, keep_formatted)}")

        delete_urls: list[str] = []
        for rn in del_rows:
            row = ctx_rows[rn - 2]
            formatted = _row_field(header_low, row, "source")
            cell = cells.get(rn, {})
            url = extract_cell_url(cell)
            chip = is_title_chip(cell, formatted)
            looks_url = formatted.strip().lower().startswith("http")
            status_msg = "OK — URL literal thật, KHÔNG phải title-chip" if (looks_url and not chip) else (
                "!! CẢNH BÁO: title-chip (hiển thị KHÁC href)" if chip else
                "!! CẢNH BÁO: Source không phải URL literal và không có hyperlink -> KHÔNG xác minh được")
            print(f"  XOÁ  dòng {rn} (status={_row_field(header_low, row, 'status')}, "
                 f"execute={_row_field(header_low, row, 'execute')}): "
                 f"Source={formatted[:60]!r} | {status_msg}")
            if not looks_url or chip:
                warnings.append(f"Dòng {rn} (TopicKey {tk}): {status_msg}")
            if url:
                delete_urls.append(url)

        # Đề xuất URL chép vào dòng GIỮ nếu nó đang là title-chip/không có URL.
        keep_url_own = extract_cell_url(keep_cell)
        needs_repair = keep_url_own is None or is_title_chip(keep_cell, keep_formatted)
        if needs_repair:
            candidate = keep_url_own or (delete_urls[0] if delete_urls else None)
            if candidate and delete_urls and any(u != candidate for u in delete_urls):
                warnings.append(f"TopicKey {tk}: các dòng XOÁ có href KHÔNG khớp nhau "
                               f"({set(delete_urls)}) — KHÔNG tự chọn, cần bạn xác nhận tay.")
            elif candidate:
                repairs[keep_row] = candidate
                print(f"  ==> ĐỀ XUẤT chép vào Source dòng {keep_row}: {candidate!r}")
            else:
                warnings.append(f"TopicKey {tk}: dòng GIỮ ({keep_row}) KHÔNG có URL nào "
                               f"khôi phục được (không hyperlink, các dòng XOÁ cũng vậy).")
        else:
            print(f"  (Source dòng {keep_row} đã là URL literal đúng — không cần chép gì.)")

    print(f"\n{'-' * 70}\nQuét CONTENT tìm (TopicKey,Type) trùng...")
    seen_ct: set[tuple[str, str]] = set()
    content_dups = 0
    if len(content_values) >= 2:
        for k in content_keys:
            if k in seen_ct:
                content_dups += 1
            seen_ct.add(k)
    print(f"  (TopicKey,Type) trùng ở CONTENT: {content_dups} (kỳ vọng 0)")
    print(f"  Dòng CONTENT TopicKey RỖNG (chưa backfill): {len(content_missing)} "
         f"(kỳ vọng 0 — {content_missing[:5]}{'...' if len(content_missing) > 5 else ''})")

    today = datetime.now().strftime("%Y-%m-%d")
    print(f"\n{'-' * 70}\nKế hoạch backup (khi --apply): tạo tab "
         f"'CONTEXT_backup_{today}' và 'CONTENT_backup_{today}' (copy toàn bộ, "
         f"idempotent — ghi đè bản backup cùng ngày nếu chạy lại).")

    if warnings:
        print(f"\n{'!' * 70}\n{len(warnings)} CẢNH BÁO CẦN XEM TRƯỚC KHI DUYỆT:")
        for w in warnings:
            print(f"  - {w}")
    else:
        print("\nKHÔNG có cảnh báo — mọi dòng XOÁ đều xác minh được URL literal thật "
             "qua hyperlink (spreadsheets.get), không phải title-chip.")

    print(f"\n{'=' * 70}\nTổng: {len(ctx_rows)} dòng CONTEXT hiện có -> "
         f"{len(ctx_rows) - len(all_delete_rows)} dòng sau khi xoá "
         f"({len(all_delete_rows)} dòng XOÁ, {len(repairs)} dòng GIỮ sẽ được chép URL).")
    print("Chạy `python scripts/dedupe_context.py --apply` SAU KHI đã duyệt danh sách trên.")

    return {"groups": plan, "warnings": warnings, "repairs": repairs,
            "delete_rows": all_delete_rows, "before": len(ctx_rows)}


def apply(*, plan_result: dict | None = None) -> dict:
    settings = load_settings()
    board = _open_board(settings)
    result = plan_result or dry_run(verbose=False)
    if not result["groups"]:
        print("Không có gì để xoá.")
        return {"deleted": 0, "repaired": 0}

    today = datetime.now().strftime("%Y-%m-%d")
    ctx_backup = board.backup_tab("CONTEXT", suffix=today)
    content_backup = board.backup_tab("CONTENT", suffix=today)
    print(f"[backup] {ctx_backup} , {content_backup}")

    for row, url in result["repairs"].items():
        board.set_context_cell(row, "Source", url)
    print(f"[repair] chép URL vào {len(result['repairs'])} dòng GIỮ.")

    board.delete_context_rows(result["delete_rows"])
    print(f"[delete] xoá {len(result['delete_rows'])} dòng CONTEXT.")

    ctx_after = board._tab("CONTEXT").get_all_values()
    missing = board.existing_content_missing_keys()
    print(f"\n[verify] CONTEXT: {result['before']} -> {len(ctx_after) - 1} dòng "
         f"(giảm {len(result['delete_rows'])}).")
    print(f"[verify] existing_content_missing_keys(): {len(missing)} "
         f"(kỳ vọng 0 mồ côi) — {missing}")

    return {"deleted": len(result["delete_rows"]), "repaired": len(result["repairs"]),
            "before": result["before"], "after": len(ctx_after) - 1, "orphans": missing}


def _parse_args(argv: list[str]):
    import argparse
    ap = argparse.ArgumentParser(description="Dọn dòng CONTEXT trùng TopicKey (Fix (a) Phase 2).")
    ap.add_argument("--apply", action="store_true",
                    help="Backup + xoá thật (mặc định dry-run, KHÔNG sửa gì).")
    return ap.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    if args.apply:
        apply()
    else:
        dry_run()
