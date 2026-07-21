"""Điểm ráp DUY NHẤT webhook -> pipeline sản xuất thật (VIỆC 5.2, ráp
2026-07-20 sau khi produce_from_sheet.run() có tham số `topic_keys`).

NGUYÊN TẮC (Lead chốt 5.2/5.3): `run()` là NƠI DUY NHẤT ghi cờ Execute
(DONE/FAILED/NEEDS_HUMAN) lên Sheet. Bridge CHỈ kích hoạt
`run(topic_keys=[topic_key])`; client đọc lại trạng thái THẬT qua
GET /status/{topic_key} (VIỆC 5.4). KHÔNG ghi Execute ở đây (tránh 2 nguồn
trạng thái cho cùng dữ liệu — chính điều 5.2 cấm).

`produce_from_sheet` nằm trong `scripts/` (KHÔNG phải package) -> thêm `scripts/`
vào sys.path để import `run` (cùng nếp `tests/test_pipeline.py`).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

logger = logging.getLogger("webhook.pipeline_bridge")

# api/ -> repo root; thêm CẢ scripts/ (import `run`) LẪN src/ (import `twmkt`,
# dùng bởi đường đọc Sheet trực tiếp ở api/main.py::_read_topic_context) vào
# sys.path Ở MODULE-LEVEL — main.py import module này TRƯỚC khi phục vụ request,
# nên twmkt importable ngay cả khi produce_from_sheet chưa được import (lazy).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_REPO_ROOT, "scripts"), os.path.join(_REPO_ROOT, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


async def run_pipeline(topic_key: str) -> str:
    """Gọi `produce_from_sheet.run(topic_keys=[topic_key])` trong THREAD (run()
    đồng bộ + nặng: full-fetch/LLM/Sheet) để KHÔNG chẹn event loop FastAPI.

    Trả CHUỖI tóm tắt CHỈ để log — trạng thái THẬT (DONE/FAILED/NEEDS_HUMAN) do
    `run()` tự ghi lên cột Execute, client đọc qua GET /status/{topic_key}."""
    from produce_from_sheet import run  # import trễ (sau khi set sys.path)

    logger.info("run_pipeline(%s): produce_from_sheet.run(topic_keys=[...])", topic_key)
    result = await asyncio.to_thread(run, topic_keys=[topic_key])
    logger.info("run_pipeline(%s) xong: %s", topic_key, result)
    return str(result)
