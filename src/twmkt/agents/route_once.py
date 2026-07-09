"""Phase 4.8 Mục A — ROUTE-ONCE + ĐÓNG BĂNG.

Vấn đề (báo cáo Phase 4.7): ClaudeCodeLLM (`claude -p`) không expose tham số
sampling nên temperature=0.0 ở run_route() là no-op — gọi router 2 LẦN cho
CÙNG evidence có thể ra 2 quyết định KHÁC NHAU (đo thực tế: 0/3 khớp trên 3
chủ đề thử ở Phase 4.7). Nếu nhiều content-type (article/video_script/
infographic) của CÙNG 1 chủ đề tự gọi run_route() riêng lẻ, nguy cơ LỆCH
KHUNG giữa các loại content của cùng chủ đề là CÓ THẬT, không phải giả thuyết.

Giải pháp: KHÔNG đuổi theo ép tất định ở tầng model (Phase 3.6 đã thử thước đo
residual_tension, không thắng được giới hạn CLI). Giải ở tầng VẬN HÀNH — route
ĐÚNG 1 LẦN/chủ đề, ĐÓNG BĂNG quyết định, mọi content-type SAU đó đọc lại CÙNG
quyết định đã đóng băng, KHÔNG gọi router lần 2.

State store — CHỌN FILE JSON (`router.decisions_path`, mặc định
storage/router_decisions.json), KHÔNG dùng cột Sheet mới:
  - RouterDecision có field lồng (`signals`: 5 khoá bao gồm rationale/drivers/
    residual_tension) — khó biểu diễn gọn trong 1 ô Sheet mà không mất thông
    tin audit hoặc phải tách thành nhiều cột.
  - Thêm cột Sheet kéo theo migrate_rows()/format_board()/CONTEXT_HEADER —
    ĐỔI SCHEMA Sheet, không phải "ít xâm lấn nhất" (Sheet đã trải qua nhiều
    vòng migration trong các phase trước).
  - File JSON độc lập, không đụng ensure_tabs/migrate_rows/format_board,
    không tốn thêm lượt gọi Sheets API.
  - KHÔNG day-partition (khác storage/output, storage/documents) — quyết định
    đóng băng là trạng thái "đã chốt cho 1 chủ đề", không phải dữ liệu-theo-
    ngày; owner chủ động xoá bằng RouterDecisionStore.clear() hoặc
    scripts/reroute.py khi thấy khung chọn sai, KHÔNG tự động hết hạn.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .base import LLMClient
from .production import ProductionBrief
from .structure_router import RouterDecision, run_route


def _decision_to_dict(d: RouterDecision) -> dict:
    return asdict(d)


def _decision_from_dict(data: dict) -> RouterDecision:
    return RouterDecision(
        content_type=data.get("content_type", "article"),
        structure=data.get("structure", "S1"),
        hook=data.get("hook", "H3"),
        secondary_structure=data.get("secondary_structure"),
        rationale=data.get("rationale", ""),
        signals=data.get("signals") or {},
        fallback=bool(data.get("fallback", False)),
    )


class RouterDecisionStore:
    """1 file JSON, key = topic key do caller chọn (khuyến nghị: slug ổn định
    của CONTEXT.Context, vd produce_from_sheet._slug(context)). Đọc/ghi TOÀN
    BỘ file mỗi lần — đơn giản, khối lượng nhỏ (vài trăm chủ đề, không cần DB)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, key: str) -> RouterDecision | None:
        raw = self._load().get(key)
        return _decision_from_dict(raw) if raw else None

    def set(self, key: str, decision: RouterDecision) -> None:
        data = self._load()
        data[key] = _decision_to_dict(decision)
        self._save(data)

    def clear(self, key: str) -> bool:
        """Cửa RE-ROUTE thủ công cho owner (xem scripts/reroute.py) — xoá
        quyết định đóng băng của `key`. True nếu có để xoá (False nếu chưa
        từng route). KHÔNG tự động route lại ở đây — lần get_or_route() SAU
        sẽ route lại vì `key` không còn trong store nữa."""
        data = self._load()
        if key not in data:
            return False
        del data[key]
        self._save(data)
        return True

    def all(self) -> dict[str, RouterDecision]:
        return {k: _decision_from_dict(v) for k, v in self._load().items()}


def get_or_route(
    llm: LLMClient, brief: ProductionBrief, classification: dict | None = None, *,
    store: RouterDecisionStore, key: str,
    model: str | None = None, fail_loud: bool = False,
) -> RouterDecision:
    """route-once: `key` đã có quyết định đóng băng trong `store` -> trả lại
    NGAY, KHÔNG gọi run_route() (không tốn lượt LLM, không có nguy cơ ra kết
    quả khác lần trước — đây là cơ chế chống lệch khung giữa các content-type
    của CÙNG 1 chủ đề). Chưa có -> route ĐÚNG 1 LẦN rồi đóng băng NGAY LẬP
    TỨC (set trước khi return — an toàn cho tiến trình đơn luồng hiện tại của
    pipeline, không có khoảng hở race giữa route và persist)."""
    cached = store.get(key)
    if cached is not None:
        return cached
    decision = run_route(llm, brief, classification, model=model, fail_loud=fail_loud)
    store.set(key, decision)
    return decision
