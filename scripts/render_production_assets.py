"""Production Factory Phase 1.3 — render asset (SVG, $0, tất định) cho dòng
CONTENT infographic ĐÃ qua Gate 2 (Approve(gate 2)=APPROVE), ghi đường dẫn vào
cột AssetPath (neo TopicKey — kỷ luật Lớp 5) rồi mở Gate 3 (duyệt asset).

GUARDRAIL CHẠY LẦN THỨ HAI Ở ĐÂY, NGAY TRƯỚC KHI RENDER (quyết định #1 Phase
1.0 — KHÔNG thương lượng lại): `verify_spec()` chạy trên `ProductionSpec` DẪN
XUẤT từ CONTENT.Output HIỆN TẠI (SAU khi người có thể đã sửa tay ở Gate 2 —
người có thể gõ nhầm số) + CONTENT.Facts (snapshot facts[] MÁY-SỞ-HỮU, ghi lúc
Composer sinh CONTENT — xem sheets_board.py comment cạnh CONTENT_HEADER và
PROJECT_HANDOFF_P5.md). Lần (a) đã có (agents/production.apply_guardrails,
chạy ngay sau Composer, TRƯỚC khi ghi CONTENT lần đầu). Trượt lần (b) -> KHÔNG
render, ghi NEEDS_HUMAN vào Notes, AssetPath GIỮ RỖNG.

IDEMPOTENT: dòng đã có AssetPath (đã render) -> BỎ QUA HOÀN TOÀN, không render
lại/không ghi đè — kể cả nếu Gate3 CHƯA duyệt (chỉ người mới được đổi asset đã
có, bằng cách tự xoá AssetPath rồi chạy lại — KHÔNG có cờ --force ở đây, cố ý,
tránh xoá nhầm asset đã hoặc đang chờ duyệt Gate 3).

Chạy:
    python scripts/render_production_assets.py               # render tối đa 20 dòng
    python scripts/render_production_assets.py --limit 5
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

from twmkt.config import data_path, load_settings  # noqa: E402
from twmkt.media_factory.spec import build_spec_from_content, verify_spec  # noqa: E402
from twmkt.render import brand_kit_from_settings, render_infographic_svg  # noqa: E402
from twmkt.sheets_board import SheetsBoard, facts_from_json  # noqa: E402


def _today() -> str:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date().isoformat()
    except Exception:
        return datetime.now(timezone.utc).date().isoformat()


def _slug(text: str, n: int = 40) -> str:
    keep = "".join(c if c.isalnum() else "-" for c in (text or "").lower())
    while "--" in keep:
        keep = keep.replace("--", "-")
    return keep.strip("-")[:n] or "san-pham"


def _open_board(settings) -> SheetsBoard:
    sheet_id = (os.environ.get("TWMKT_SHEET_ID") or settings.get("sheets.spreadsheet_id") or "").strip()
    creds = (os.environ.get("TWMKT_SHEETS_CREDS") or settings.get("sheets.creds_path") or "").strip()
    if not sheet_id or not creds:
        raise SystemExit("Thiếu sheets.spreadsheet_id/creds_path (settings.yaml hoặc ENV).")
    return SheetsBoard(spreadsheet_id=sheet_id, creds_path=creds)


def render_one(item: dict, brand: dict) -> tuple[str | None, list, str]:
    """Xử 1 dòng CONTENT (từ SheetsBoard.read_content_for_render) -> (svg hoặc
    None, violations, lý do bỏ qua nếu có). Hàm THUẦN (không ghi Sheet/đĩa) —
    tách riêng để test được không cần mạng."""
    try:
        output_data = json.loads(item["output"])
    except json.JSONDecodeError:
        return None, [], "Output không phải JSON hợp lệ (đã bị sửa hỏng ở Gate 2?)"
    facts = facts_from_json(item["facts"])
    spec = build_spec_from_content(output_data, facts, topic_key=item["topic_key"],
                                   title=item["context"])
    violations = verify_spec(spec)
    if violations:
        return None, violations, ""
    return render_infographic_svg(output_data, brand), [], ""


def run(*, limit: int = 20) -> dict:
    settings = load_settings()
    board = _open_board(settings)
    brand = brand_kit_from_settings(settings)

    candidates = board.read_content_for_render(type_="infographic")
    out_dir = data_path(settings.get("storage.output_dir", "output"), _today(), "assets", settings=settings)
    out_dir.mkdir(parents=True, exist_ok=True)

    rendered = skipped_not_approved = skipped_already_rendered = needs_human = 0
    for item in candidates:
        if item["asset_path"]:
            skipped_already_rendered += 1
            continue   # IDEMPOTENT: đã render -> KHÔNG đụng lại (có thể đã/đang chờ Gate 3)
        if item["approve_gate2"] != "APPROVE":
            skipped_not_approved += 1
            continue   # chưa qua Gate 2 -> chưa tới lượt render

        svg, violations, parse_error = render_one(item, brand)
        if parse_error:
            board.set_content_cell(item["row"], "Notes",
                                   f"NEEDS_HUMAN (trước render): {parse_error}")
            print(f"[NEEDS_HUMAN] '{item['context'][:60]}': {parse_error}")
            needs_human += 1
            continue
        if violations:
            summary = "; ".join(f"{v.field}={v.token!r}" for v in violations[:5])
            note = (f"NEEDS_HUMAN (guardrail lần 2, trước render): {len(violations)} số "
                   f"không khớp facts[] (có thể do sửa tay ở Gate 2) — {summary}")
            board.set_content_cell(item["row"], "Notes", note)
            print(f"[NEEDS_HUMAN] '{item['context'][:60]}': {len(violations)} vi phạm — {summary}")
            needs_human += 1
            continue

        fn = out_dir / f"{_slug(item['context'])}.svg"
        fn.write_text(svg, encoding="utf-8")
        board.set_content_cell(item["row"], "AssetPath", str(fn))
        print(f"[render] '{item['context'][:60]}' -> {fn}")
        rendered += 1
        if rendered >= limit:
            break

    print(f"\nTổng: render {rendered} | bỏ qua (đã render) {skipped_already_rendered} | "
         f"bỏ qua (chưa qua Gate 2) {skipped_not_approved} | NEEDS_HUMAN {needs_human}")
    return {"rendered": rendered, "skipped_already_rendered": skipped_already_rendered,
           "skipped_not_approved": skipped_not_approved, "needs_human": needs_human}


def _parse_args(argv: list[str]):
    import argparse
    ap = argparse.ArgumentParser(
        description="Render asset (SVG) cho CONTENT infographic đã qua Gate 2 (Production Factory Phase 1.3).")
    ap.add_argument("--limit", type=int, default=20, help="Số asset tối đa render mỗi lượt.")
    return ap.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    run(limit=args.limit)
