"""Production Factory — render asset (PNG, AI ai_full) cho dòng CONTENT
infographic ĐÃ qua Gate 2 (Approve(gate 2)=APPROVE), ghi đường dẫn vào cột
AssetPath (neo TopicKey — kỷ luật Lớp 5) rồi mở Gate 3 (duyệt asset).

ĐẢO HƯỚNG (2026-07-21, QUYẾT ĐỊNH LEAD — xem docs/VPS_MIGRATION_BACKLOG.md):
renderer đổi từ SVG tất định (`render_infographic_svg`) sang AI-only
(`render/ai_full.py`, model gpt-image-2). GUARDRAIL-2 NHÁNH ẢNH (verify_spec
trên ProductionBlock/block_kind) ĐÃ XOÁ CÙNG LƯỢT theo đúng quyết định Lead —
KHÔNG còn bước đối chiếu output_data với facts[] NGAY TRƯỚC RENDER cho
infographic (khác trục video, vẫn giữ nguyên qua ProductionScene). Rủi ro
ĐÃ BIẾT: nếu người sửa tay output_data ở Gate 2 gõ nhầm số, AI (ai_full) sẽ vẽ
NGUYÊN VĂN số sai đó vào ảnh mà không có gì tự động bắt trước khi ghi
AssetPath — Gate 2 (duyệt người) + Gate 3 (duyệt asset) là 2 lớp chặn còn lại.

IDEMPOTENT: dòng đã có AssetPath (đã render) -> BỎ QUA HOÀN TOÀN, không render
lại/không ghi đè — kể cả nếu Gate3 CHƯA duyệt (chỉ người mới được đổi asset đã
có, bằng cách tự xoá AssetPath rồi chạy lại — KHÔNG có cờ --force ở đây, cố ý,
tránh xoá nhầm asset đã hoặc đang chờ duyệt Gate 3). ai_full tự cache theo
hash(spec+theme+ratio) — dòng render lại (sau khi tự xoá AssetPath) KHÔNG gọi
API lần nữa nếu input không đổi.

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

from twmkt.asset_server import DEFAULT_PORT, asset_url  # noqa: E402
from twmkt.config import data_path, load_settings  # noqa: E402
from twmkt.render.ai_full import render_ai_full  # noqa: E402
from twmkt.sheets_board import SheetsBoard  # noqa: E402


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


def asset_hyperlink_formula(url: str) -> str:
    """Sheet UI cleanup Phase 6b/6c — bọc `url` (HTTP, xem twmkt.asset_server.
    asset_url) bằng HYPERLINK() để cột AssetPath (đã HIỂN THỊ từ Phase 6) là
    link NGƯỜI BẤM ĐƯỢC thay vì text đường dẫn thô.

    LỊCH SỬ (Phase 6b -> 6c): bản đầu dùng `file://` (Path.as_uri()) — test
    THẬT trên Sheet sống cho thấy KHÔNG hoạt động (Google Sheets chạy qua
    HTTPS, trình duyệt chặn điều hướng HTTPS -> file:// cục bộ). Đổi sang
    `http://127.0.0.1:PORT/...` (twmkt.asset_server, cần `scripts/
    serve_assets.py` chạy nền) — scheme http là web-an-toàn nên hoạt động
    bình thường trong Sheets.

    GIỚI HẠN ĐÃ BIẾT (chấp nhận, xem docs/HANDOFF.md): link CHỈ mở được trên
    MÁY đã render asset VÀ đang chạy `scripts/serve_assets.py` — không phải
    link chia sẻ được cho máy khác. Khi lên VPS: assets được serve qua web
    server/cloud storage THẬT (không phải localhost), chỉ cần đổi cách build
    `url` ở call site, KHÔNG cần sửa hàm này hay cấu trúc cột/Sheet."""
    return f'=HYPERLINK("{url}", "Mở file")'


def _open_board(settings) -> SheetsBoard:
    sheet_id = (os.environ.get("TWMKT_SHEET_ID") or settings.get("sheets.spreadsheet_id") or "").strip()
    creds = (os.environ.get("TWMKT_SHEETS_CREDS") or settings.get("sheets.creds_path") or "").strip()
    if not sheet_id or not creds:
        raise SystemExit("Thiếu sheets.spreadsheet_id/creds_path (settings.yaml hoặc ENV).")
    return SheetsBoard(spreadsheet_id=sheet_id, creds_path=creds)


def render_one(item: dict, *, settings) -> tuple[bytes | None, str]:
    """Xử 1 dòng CONTENT (từ SheetsBoard.read_content_for_render) -> (png
    bytes hoặc None, cảnh báo/lý do bỏ qua nếu có). Hàm THUẦN về mặt Sheet
    (không tự ghi Sheet) nhưng CÓ gọi mạng thật (OpenAI Images API qua
    ai_full, cache-first) — khác quy ước "Hàm THUẦN" cũ của renderer SVG $0."""
    try:
        output_data = json.loads(item["output"])
    except json.JSONDecodeError:
        return None, "Output không phải JSON hợp lệ (đã bị sửa hỏng ở Gate 2?)"
    results = render_ai_full(output_data, ratios=("4:5",), settings=settings)
    png_bytes, warning = results["4:5"]
    return png_bytes, warning


def run(*, limit: int = 20) -> dict:
    settings = load_settings()
    board = _open_board(settings)

    candidates = board.read_content_for_render(type_="infographic")
    output_root = data_path(settings.get("storage.output_dir", "output"), settings=settings)
    out_dir = output_root / _today() / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    asset_port = int(settings.get("storage.asset_server_port", DEFAULT_PORT))

    rendered = skipped_not_approved = skipped_already_rendered = needs_human = 0
    for item in candidates:
        if item["asset_path"]:
            skipped_already_rendered += 1
            continue   # IDEMPOTENT: đã render -> KHÔNG đụng lại (có thể đã/đang chờ Gate 3)
        if item["approve_gate2"] != "APPROVE":
            skipped_not_approved += 1
            continue   # chưa qua Gate 2 -> chưa tới lượt render

        png_bytes, warning = render_one(item, settings=settings)
        if png_bytes is None:
            board.set_content_cell(item["row"], "Notes", f"NEEDS_HUMAN (render ai_full): {warning}")
            print(f"[NEEDS_HUMAN] '{item['context'][:60]}': {warning}")
            needs_human += 1
            continue

        fn = out_dir / f"{_slug(item['context'])}.png"
        fn.write_bytes(png_bytes)
        url = asset_url(fn, root=output_root, port=asset_port)
        board.set_content_cell(item["row"], "AssetPath", asset_hyperlink_formula(url))
        print(f"[render] '{item['context'][:60]}' -> {fn} ({url})")
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
