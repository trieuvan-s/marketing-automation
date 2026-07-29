"""Tập đóng `visual_kind` cho trục VIDEO — phần CÒN LẠI của module này sau khi
dọn dead code 2026-07-28 (đóng gói MVP).

LỊCH SỬ RÚT GỌN (đọc để không ai khôi phục nhầm):
File này TỪNG chứa `ProductionSpec`/`ProductionScene`/`verify_spec()` —
guardrail số LẦN 2 cho video, đối chiếu `scenes[]` với `facts[]` TRƯỚC khi
render. Toàn bộ phần đó ĐÃ XOÁ vì bị THAY THẾ, KHÔNG phải vì bỏ tính năng:

  1. Nhánh ẢNH (`ProductionBlock`/`blocks[]`) xoá 2026-07-21 cùng lượt đảo
     hướng render Infographic sang AI-only (`render/ai_full.py`) — quyết định
     Lead, xem docs/VPS_MIGRATION_BACKLOG.md C16.
  2. Nhánh VIDEO đã PORT sang TypeScript: `aigen-pipeline/src/production-spec/
     guardrail/verify-spec.ts`. PHA 1.1 đối chiếu TAY từng hàm, kết luận port
     TRUNG THÀNH 100% semantics (5 shape fact, dung sai 0.05 / lookback 12,
     `_iter_slot_texts`, `_check_plain_list_item_entity`, parser số chữ-số lẫn
     viết-bằng-chữ). Xem tasks/ACTIVE_TASK.md §PHA 1.1 +
     docs/ARCHITECTURE_MODULES.md §"PORT guardrail-2 nhánh VIDEO".
  3. Bản TS đã CHẠY THẬT 2026-07-28 trên `CONTENT.Output` do CHÍNH repo này
     sinh, đi trọn tới `video.mp4` — guardrail-2 hoạt động đúng. Không còn
     nghi ngờ nào về việc bản Python có cần giữ hay không.

⚠️ ĐỪNG NHẦM 2 THỨ TRÙNG TÊN Ở 2 REPO (đã gây hiểu lầm 1 lượt, xem
tasks/HANDOFF_2026-07-26.md):
  - `aigen-pipeline/src/production-spec/` (TypeScript) = CÂY CẦU THẬT, đang
    chạy, GIỮ.
  - `media_factory/spec.py::ProductionSpec` (Python) = bản vừa xoá ở đây.

CÒN LẠI GÌ VÀ VÌ SAO: 2 hằng dưới đây — `agents/production.py` import THẬT
(`VideoScriptAgent` kiểm tập đóng `visual_kind` khi sinh scene). Đó là lý do
DUY NHẤT file này còn tồn tại.

KHÔNG dọn `media_factory/numbers.py` (đã kiểm): `agents/production.py` import
`find_spelled_number_phrases` cho guardrail lần 1 — vẫn đang chạy thật.
KHÔNG dọn `media_factory/aigen_seam.py`: từ 2026-07-28 đã có caller thật
(`scripts/render_production_assets.py::render_video_one`).
"""
from __future__ import annotations

# Tập đóng visual_kind (video, trục THỜI GIAN) — 10 giá trị, chốt sau khi đối
# chiếu 15 template AIGEN thật. PHẢI KHỚP `visual_kind` bên
# aigen-pipeline/src/production-spec/ — đổi ở đây thì đổi CẢ HAI repo.
VISUAL_KINDS = frozenset({
    "title", "stat", "statement", "list", "comparison", "quote",
    "ticker", "news", "avatar", "outro",
})

# "avatar" (frame-avatar-presenter) nằm TRONG VISUAL_KINDS nhưng CHƯA kích
# hoạt — cần clip talking-head thật (chờ HeyGen), chưa nguồn nào sinh giá trị
# này.
DEFERRED_VISUAL_KINDS = frozenset({"avatar"})
