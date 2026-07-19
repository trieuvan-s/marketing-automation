"""FastAPI webhook nấc 1 — thay scheduler 30' (docs/VPS_MIGRATION_BACKLOG.md
A1). User duyệt Context=APPROVE + bấm "Thực Thi" trên Sheet -> Apps Script
bắn HTTP POST /webhook/execute -> endpoint này xử lý ĐÚNG topic_key đó ngay,
không chờ tới lượt scheduler quét 30 phút/lần.

NẤC 1 (module này): webhook + chống double-fire in-memory + stub gọi
pipeline. CHƯA RÁP: xem "RÁP SAU" trong README.md — KHÔNG import gì từ
scripts/produce_from_sheet.py hay module pipeline thật (xem
pipeline_bridge.py), KHÔNG ghi Sheet thật (report_result() là stub).

Chạy dev: uvicorn api.main:app --reload --port 8899

`WEBHOOK_TOKEN` tự nạp từ `api/.env` (nếu file tồn tại, qua `python-dotenv`)
-- KHÔNG override biến môi trường ĐÃ set sẵn (`override=False`, cùng nếp
`twmkt.config._load_dotenv()` bên marketing-automation: ENV thật của
process/CI luôn thắng file). `api/.env` PHẢI gitignore (đã khớp pattern
`.env` sẵn có trong `.gitignore` gốc) -- KHÔNG BAO GIỜ commit file đó.
"""
from __future__ import annotations

import logging
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

from api.pipeline_bridge import run_pipeline

load_dotenv(Path(__file__).parent / ".env", override=False)

logger = logging.getLogger("webhook.main")

app = FastAPI(title="Marketing Automation Webhook", version="0.1.0")

# --- Chống double-fire (lý do tồn tại, xem docs/VPS_MIGRATION_BACKLOG.md A1
# "CẦN HỎI LEAD TRƯỚC KHI CODE"): state machine Execute
# (empty->RUN->DONE/FAILED/NEEDS_HUMAN) là cơ chế idempotency CHÍNH của toàn
# hệ thống. User bấm 2 lần hoặc Apps Script tự retry khi timeout sẽ gọi
# webhook 2 lần cho CÙNG topic_key trước khi Execute kịp đổi khỏi "RUN" --
# registry in-memory này chặn đúng khoảng hở đó.
#
# HẠN CHẾ ĐÃ BIẾT: registry MẤT khi service restart (in-memory, không
# persist) -- 1 request đang RUN lúc service restart sẽ "quên" mất, request
# trùng sau đó KHÔNG bị chặn nữa. CHẤP NHẬN Ở NẤC 1 (dict+lock đủ dùng, đơn
# tiến trình, restart không thường xuyên) -- store/document_store.py (đã
# viết cùng lượt này, CHƯA ráp) sẽ thay bằng trạng thái bền khi ráp thật. ---
_lock = threading.Lock()
_running: set[str] = set()


class ExecuteRequest(BaseModel):
    topic_key: str
    token: str


def _check_token(token: str) -> None:
    """So khớp hằng-thời-gian (secrets.compare_digest) -- endpoint này ra
    internet qua tunnel, không dùng so sánh chuỗi thường."""
    expected = os.environ.get("WEBHOOK_TOKEN")
    if not expected or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Token không hợp lệ")


def report_result(topic_key: str, status: str) -> None:
    """STUB -- RÁP SAU: ghi kết quả DONE/FAILED/NEEDS_HUMAN ngược về cột
    Execute trên Sheet (khớp cơ chế `sheets_board.py::set_execute_values`
    đã có -- CHƯA xác nhận chữ ký, chỉ nêu tên hàm khả nghi nhất để đối
    chiếu khi ráp). Hiện chỉ log, không ghi gì thật."""
    logger.info("report_result(topic_key=%s, status=%s) -- STUB, chưa ráp ghi Sheet",
                topic_key, status)


async def _process(topic_key: str) -> None:
    """Chạy trong background task -- webhook đã trả 202 trước khi hàm này
    chạy xong, Apps Script (timeout ngắn) không phải chờ."""
    try:
        status = await run_pipeline(topic_key)
        report_result(topic_key, status)
    except Exception:
        logger.exception("run_pipeline(%s) lỗi không bắt được", topic_key)
        report_result(topic_key, "FAILED")
    finally:
        with _lock:
            _running.discard(topic_key)


@app.post("/webhook/execute", status_code=202)
async def webhook_execute(req: ExecuteRequest, background_tasks: BackgroundTasks) -> dict:
    _check_token(req.token)
    with _lock:
        if req.topic_key in _running:
            raise HTTPException(
                status_code=409,
                detail=f"topic_key '{req.topic_key}' đang được xử lý -- bỏ qua, chống double-fire.",
            )
        _running.add(req.topic_key)
    background_tasks.add_task(_process, req.topic_key)
    return {"accepted": True, "topic_key": req.topic_key}


@app.get("/health")
async def health() -> dict:
    """Cho NSSM/monitor kiểm sống -- KHÔNG kiểm tra gì sâu hơn (không chạm
    DB/pipeline), chỉ xác nhận tiến trình FastAPI còn phản hồi."""
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/status/{topic_key}")
async def status(topic_key: str) -> dict:
    """Phục vụ chống double-fire phía Apps Script (tự kiểm trước khi bắn
    lại) -- KHÔNG phải nguồn sự thật (registry in-memory, xem hạn chế ở
    trên), chỉ tham khảo."""
    with _lock:
        is_running = topic_key in _running
    return {"topic_key": topic_key, "running": is_running}
