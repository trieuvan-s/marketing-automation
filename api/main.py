"""FastAPI webhook nấc 1 — thay scheduler 30' (docs/VPS_MIGRATION_BACKLOG.md
A1). User duyệt Context=APPROVE + bấm "Thực Thi" trên Sheet -> Apps Script
bắn HTTP POST /webhook/execute -> endpoint này **ENQUEUE 1 job vào
`store/queue_store.py`** (bảng `execution_queue`) — KHÔNG tự chạy pipeline,
KHÔNG đọc/ghi Sheet nữa. `scripts/queue_worker.py` (tiến trình RIÊNG, poll
hàng đợi vài giây/lần) mới THẬT SỰ tiêu thụ job và gọi
`produce_from_sheet.run()`.

PHASE QUEUE (2026-07-27, theo chỉ đạo Lead — "ráp luôn api/ webhook vào hàng
đợi"): ĐẢO NGƯỢC 1 quyết định Lead cũ (2026-07-19, xem `api/README.md` mục
"RÁP SAU" #4 — "KHÔNG xây trạng thái bền thứ hai cho double-fire", lúc đó cờ
Execute trên Sheet là nguồn DUY NHẤT). Nay Lead muốn ĐÚNG 1 trạng thái bền
MỚI: hàng đợi trong store. `execution_queue` giờ là nguồn double-fire DUY
NHẤT — thay CẢ đọc Sheet trực tiếp LẪN registry in-memory cũ (giải quyết dứt
điểm rủi ro C8 đã ghi nhận: service chết giữa chừng -> registry mất, Sheet
không có lease/timestamp — `execution_queue.claimed_at` giờ theo dõi đúng
việc này, xem `queue_store.release_stale_claims()`).

KHÔNG kiểm "đã duyệt Gate1 chưa" ở đây nữa — `produce_from_sheet.run(topic_
keys=[...])` tự an toàn với topic_key chưa duyệt (lọc qua
`list_approved_topics()`, không thấy -> no-op, không crash), nên webhook
không cần đọc Sheet để biết trước; kết quả thật xem qua GET /status.

Chạy dev: uvicorn api.main:app --reload --port 8899

`WEBHOOK_TOKEN` tự nạp từ `api/.env` (nếu có, qua python-dotenv), KHÔNG override
ENV đã set (`override=False`). `api/.env` PHẢI gitignore — KHÔNG BAO GIỜ commit.
"""
from __future__ import annotations

import logging
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# api/ -> repo root; thêm root vào sys.path Ở MODULE-LEVEL để import `store`
# (execution_queue) — webhook KHÔNG còn cần scripts/ hay src/ (không gọi
# produce_from_sheet/twmkt trực tiếp nữa, xem docstring trên).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from store import queue_store as qs  # noqa: E402

load_dotenv(Path(__file__).parent / ".env", override=False)

logger = logging.getLogger("webhook.main")

app = FastAPI(title="Marketing Automation Webhook", version="0.3.0")


class ExecuteRequest(BaseModel):
    topic_key: str
    token: str


def _check_token(token: str) -> None:
    """So khớp hằng-thời-gian (secrets.compare_digest) — endpoint ra internet
    qua tunnel, không so sánh chuỗi thường."""
    expected = os.environ.get("WEBHOOK_TOKEN")
    if not expected or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Token không hợp lệ")


@app.post("/webhook/execute", status_code=202)
async def webhook_execute(req: ExecuteRequest) -> dict:
    """Thứ tự kiểm: a) token -> 401; b) đã có job 'queued'/'claimed' cho
    topic_key này trong hàng đợi -> 409 (chống double-fire — nguồn sự thật
    DUY NHẤT giờ là `execution_queue`, xem `queue_store.find_pending()`);
    c) enqueue job mới -> 202 kèm `job_id` (client dùng GET /status để theo
    dõi)."""
    _check_token(req.token)

    existing = qs.find_pending(req.topic_key, job_type="produce")
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"topic_key '{req.topic_key}' đã có job #{existing['id']} "
                   f"đang '{existing['status']}' trong hàng đợi.",
        )

    job_id = qs.enqueue(req.topic_key, job_type="produce")
    return {"accepted": True, "topic_key": req.topic_key, "job_id": job_id}


@app.get("/health")
async def health() -> dict:
    """Cho NSSM/monitor kiểm sống — KHÔNG chạm DB/pipeline."""
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/status/{topic_key}")
async def status(topic_key: str) -> dict:
    """Job MỚI NHẤT (mọi job_type) của topic_key trong hàng đợi — thay đọc cờ
    Execute từ Sheet (Sheet không còn là nguồn trạng thái xử lý). `status`/
    `job_id` là `None` nếu topic_key chưa từng có job nào."""
    jobs = [j for j in qs.list_queue() if j["topic_key"] == topic_key]
    latest = jobs[-1] if jobs else None
    return {
        "topic_key": topic_key,
        "status": latest["status"] if latest else None,
        "job_id": latest["id"] if latest else None,
    }
