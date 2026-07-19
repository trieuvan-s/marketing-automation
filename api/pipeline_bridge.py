"""Điểm ráp DUY NHẤT giữa webhook và pipeline sản xuất thật — STUB, KHÔNG
gọi gì thật ở nấc này (xem tasks/ACTIVE_TASK.md / docs/VPS_MIGRATION_BACKLOG.md A1).

GIẢ ĐỊNH CHỮ KÝ (CHƯA XÁC NHẬN — đối chiếu với scripts/produce_from_sheet.py
THẬT khi ráp, KHÔNG tin giả định này mù quáng):
    produce_from_sheet(topic_key: str) -> status
    # status kiểu str, một trong {"DONE", "FAILED", "NEEDS_HUMAN"} — khớp
    # 3 trạng thái Execute cuối trong state machine
    # (empty -> RUN -> DONE/FAILED/NEEDS_HUMAN) đã có trên Sheet.

KHÔNG import `scripts.produce_from_sheet` hay bất kỳ module thật nào của
pipeline sản xuất ở đây — tại thời điểm viết module này, `scripts/
produce_from_sheet.py` đang nằm trong vùng agent-B sửa dở (diff lớn chưa
commit trên `develop`), import lúc này rủi ro lấy nhầm phiên bản/đụng độ.
RÁP SAU (xem api/README.md): thay thân `run_pipeline()` bằng lệnh gọi thật,
đối chiếu chữ ký/kiểu trả về ở trên trước khi thay.
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("webhook.pipeline_bridge")


async def run_pipeline(topic_key: str) -> str:
    """STUB — mô phỏng xử lý 1 `topic_key`, trả về status cuối cùng.

    RÁP SAU: thay toàn bộ thân hàm bằng lệnh gọi `produce_from_sheet`
    thật (đối chiếu chữ ký trong docstring module trước khi thay — CHƯA
    xác nhận đây là chữ ký đúng)."""
    logger.info("STUB run_pipeline(%s) bắt đầu", topic_key)
    await asyncio.sleep(0.1)  # mô phỏng độ trễ xử lý thật, KHÔNG có ý nghĩa gì khác
    logger.info("STUB run_pipeline(%s) kết thúc -- status giả lập DONE", topic_key)
    return "DONE"
