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


# 2026-07-23 (nghiệm thu Phần A-B-C, yêu cầu Lead): render ĐỦ 3 tỷ lệ/bài,
# KHÔNG còn chỉ "4:5" như bản cũ -- AssetPath (1 cột duy nhất trên Sheet,
# KHÔNG đổi schema -- ranh giới file, sheets_board.py là vùng agent-A) vẫn
# trỏ tỷ lệ CHÍNH (_PRIMARY_RATIO); 2 tỷ lệ còn lại ghi đường dẫn vào Notes
# (cột đã có sẵn, KHÔNG phải thêm cột mới).
_RATIOS: tuple[str, ...] = ("4:5", "9:16", "1:1")
_PRIMARY_RATIO = "4:5"


def render_one(item: dict, *, settings) -> tuple[dict[str, bytes | None], dict[str, str], dict[str, dict]]:
    """Xử 1 dòng CONTENT (từ SheetsBoard.read_content_for_render) -> (png
    bytes theo tỷ lệ, cảnh báo theo tỷ lệ, log JSON theo tỷ lệ -- xem
    ai_full.render_ai_full()). Hàm THUẦN về mặt Sheet (không tự ghi Sheet)
    nhưng CÓ gọi mạng thật (OpenAI Images API qua ai_full, cache-first) --
    khác quy ước "Hàm THUẦN" cũ của renderer SVG $0."""
    try:
        output_data = json.loads(item["output"])
    except json.JSONDecodeError:
        err = "Output không phải JSON hợp lệ (đã bị sửa hỏng ở Gate 2?)"
        return {r: None for r in _RATIOS}, {r: err for r in _RATIOS}, {}
    results, logs = render_ai_full(output_data, ratios=_RATIOS, settings=settings)
    png_map = {r: results[r][0] for r in _RATIOS}
    warn_map = {r: results[r][1] for r in _RATIOS}
    return png_map, warn_map, logs


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

        png_map, warn_map, logs = render_one(item, settings=settings)
        if png_map.get(_PRIMARY_RATIO) is None:
            warning = warn_map.get(_PRIMARY_RATIO, "lỗi không rõ")
            board.set_content_cell(item["row"], "Notes", f"NEEDS_HUMAN (render ai_full {_PRIMARY_RATIO}): {warning}")
            print(f"[NEEDS_HUMAN] '{item['context'][:60]}': {warning}")
            needs_human += 1
            continue

        slug = _slug(item["context"])
        written: dict[str, Path] = {}
        for ratio in _RATIOS:
            png_bytes = png_map.get(ratio)
            if png_bytes is None:
                print(f"[CẢNH BÁO] '{item['context'][:60]}' tỷ lệ {ratio} thất bại: {warn_map.get(ratio)}")
                continue
            suffix = ratio.replace(":", "x")
            fn = out_dir / f"{slug}_{suffix}.png"
            fn.write_bytes(png_bytes)
            # A2 Bước 6 -- log JSON CẠNH ảnh (Lead kiểm không cần mở ảnh).
            log_fn = out_dir / f"{slug}_{suffix}.log.json"
            log_fn.write_text(json.dumps(logs.get(ratio, {}), ensure_ascii=False, indent=2), encoding="utf-8")
            written[ratio] = fn

        primary_fn = written[_PRIMARY_RATIO]
        url = asset_url(primary_fn, root=output_root, port=asset_port)
        board.set_content_cell(item["row"], "AssetPath", asset_hyperlink_formula(url))
        other = "; ".join(f"{r}: {p}" for r, p in written.items() if r != _PRIMARY_RATIO)
        if other:
            board.set_content_cell(item["row"], "Notes", f"Tỷ lệ khác (chưa có cột riêng): {other}")
        print(f"[render] '{item['context'][:60]}' -> {len(written)}/{len(_RATIOS)} tỷ lệ, "
             f"primary={primary_fn} ({url})")
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
