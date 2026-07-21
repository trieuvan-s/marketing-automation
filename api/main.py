"""FastAPI webhook nấc 1 — thay scheduler 30' (docs/VPS_MIGRATION_BACKLOG.md
A1). User duyệt Context=APPROVE + bấm "Thực Thi" trên Sheet -> Apps Script
bắn HTTP POST /webhook/execute -> endpoint này kích hoạt sản xuất ĐÚNG topic_key
đó ngay, không chờ scheduler quét 30 phút/lần.

RÁP THẬT (VIỆC 5, Lead chốt hướng 1 — 2026-07-20):
- `pipeline_bridge.run_pipeline()` gọi `produce_from_sheet.run(topic_keys=[k])`.
- `run()` là NƠI DUY NHẤT ghi cờ Execute (DONE/FAILED/NEEDS_HUMAN). Webhook KHÔNG
  tự đặt/ghi Execute (tránh 2 nguồn trạng thái — 5.2/5.3). `report_result()` chỉ
  còn LOG.
- GET /status/{topic_key} ĐỌC cờ Execute từ Sheet -> trạng thái THẬT cho client
  (POST vẫn trả 202 ngay vì Apps Script timeout ngắn).
- Đọc Sheet ở đây LÀ ĐỌC TRỰC TIẾP: dựng SheetsBoard THẲNG, KHÔNG qua
  produce_from_sheet._open_board (nó gọi ensure_tabs). CHỈ ĐỌC, không ghi, KHÔNG
  ensure_tabs()/migrate_rows() (QUY TẮC VÀNG, 5.5 ⚠️).

Chạy dev: uvicorn api.main:app --reload --port 8899

`WEBHOOK_TOKEN` tự nạp từ `api/.env` (nếu có, qua python-dotenv), KHÔNG override
ENV đã set (`override=False`). `api/.env` PHẢI gitignore — KHÔNG BAO GIỜ commit.
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

# import pipeline_bridge TRƯỚC: nó thêm scripts/ + src/ vào sys.path (module-level)
# nên các import `twmkt.*` phía dưới (đường đọc Sheet) chạy được.
from api.pipeline_bridge import run_pipeline

load_dotenv(Path(__file__).parent / ".env", override=False)

logger = logging.getLogger("webhook.main")

app = FastAPI(title="Marketing Automation Webhook", version="0.2.0")

# --- Chống double-fire (in-memory, lưới NHANH cùng tiến trình). Idempotency BỀN
# là cờ Execute trên Sheet (5.2). HẠN CHẾ: registry MẤT khi restart -> chấp nhận
# ở nấc 1 (Execute trên Sheet đỡ ca cross-restart). ---
_lock = threading.Lock()
_running: set[str] = set()

# Trạng thái Execute coi là "đang chạy" -> chặn fire mới (409).
_RUNNING_EXECUTE = "RUN"
# Trạng thái Execute cho phép fire (chưa chạy / lỗi tạm thời tái chạy được).
_FIREABLE_EXECUTE = {"", "FAILED"}


class ExecuteRequest(BaseModel):
    topic_key: str
    token: str


def _check_token(token: str) -> None:
    """So khớp hằng-thời-gian (secrets.compare_digest) — endpoint ra internet
    qua tunnel, không so sánh chuỗi thường."""
    expected = os.environ.get("WEBHOOK_TOKEN")
    if not expected or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Token không hợp lệ")


def _read_topic_context(topic_key: str) -> dict | None:
    """ĐỌC TRỰC TIẾP dòng CONTEXT khớp `topic_key` (đã lọc Status=APPROVE).

    QUY TẮC VÀNG (5.5 ⚠️): dựng SheetsBoard THẲNG (KHÔNG qua _open_board ->
    KHÔNG ensure_tabs()/migrate_rows()). read_approved_context()/_tab() chỉ
    get_all_values() — thuần ĐỌC. Trả dict {context, execute, topic_key, ...}
    hoặc None nếu không có dòng APPROVE nào mang topic_key này."""
    from twmkt.config import load_settings
    from twmkt.sheets_board import SheetsBoard

    settings = load_settings()
    sheet_id = (os.environ.get("TWMKT_SHEET_ID") or settings.get("sheets.spreadsheet_id") or "").strip()
    creds = (os.environ.get("TWMKT_SHEETS_CREDS") or settings.get("sheets.creds_path") or "").strip()
    if not sheet_id or not creds:
        raise HTTPException(status_code=500, detail="Thiếu cấu hình Sheet (spreadsheet_id/creds).")
    board = SheetsBoard(spreadsheet_id=sheet_id, creds_path=creds)  # KHÔNG ensure_tabs
    for item in board.read_approved_context():
        if item.get("topic_key") == topic_key:
            return item
    return None


def report_result(topic_key: str, status: str) -> None:
    """CHỈ LOG (5.3, Lead chốt): `run()` đã ghi DONE/FAILED/NEEDS_HUMAN lên cột
    Execute — webhook KHÔNG ghi Sheet ở đây (một nguồn trạng thái duy nhất).
    Giữ lại để _process log kết quả/lỗi cho quan sát."""
    logger.info("report_result(topic_key=%s, status=%s) — chỉ log (run() đã ghi Execute)",
                topic_key, status)


async def _process(topic_key: str) -> None:
    """Background task — webhook đã trả 202 trước khi hàm này xong."""
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
    """Thứ tự kiểm (5.5): a) token; b) Execute trên Sheet đang RUN -> 409;
    c) chưa duyệt (server-side, không tin client) -> 400; d) registry in-memory
    -> 409; e) 202 + background run(topic_keys=[topic_key]). KHÔNG tự đặt cờ
    Execute — run() lo."""
    # a) token sai -> 401
    _check_token(req.token)

    # b/c) ĐỌC TRỰC TIẾP Sheet — kiểm điều kiện phía SERVER (Apps Script đã chặn
    # nhưng request có thể đến từ nơi khác qua tunnel).
    item = _read_topic_context(req.topic_key)
    if item is None:
        # c) không có dòng APPROVE nào mang topic_key này -> chưa duyệt.
        raise HTTPException(
            status_code=400,
            detail=f"topic_key '{req.topic_key}' chưa duyệt (không thấy dòng CONTEXT Status=APPROVE).",
        )
    execute = (item.get("execute") or "").upper()
    if execute == _RUNNING_EXECUTE:
        # b) đang RUN -> 409 (KHÔNG tự đặt cờ, run() lo).
        raise HTTPException(
            status_code=409,
            detail=f"topic_key '{req.topic_key}' đang xử lý (Execute=RUN trên Sheet).",
        )
    if execute not in _FIREABLE_EXECUTE:
        # DONE/NEEDS_HUMAN -> không tái kích hoạt (idempotent).
        raise HTTPException(
            status_code=409,
            detail=f"topic_key '{req.topic_key}' Execute='{execute}' — đã xong/đang chờ người, bỏ qua.",
        )

    # d) registry in-memory (lưới nhanh cùng tiến trình, khoảng hở trước khi
    # run() kịp đặt Execute=RUN).
    with _lock:
        if req.topic_key in _running:
            raise HTTPException(
                status_code=409,
                detail=f"topic_key '{req.topic_key}' đang được xử lý (registry) — chống double-fire.",
            )
        _running.add(req.topic_key)

    # e) 202 + background.
    background_tasks.add_task(_process, req.topic_key)
    return {"accepted": True, "topic_key": req.topic_key}


@app.get("/health")
async def health() -> dict:
    """Cho NSSM/monitor kiểm sống — KHÔNG chạm DB/pipeline."""
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/status/{topic_key}")
async def status(topic_key: str) -> dict:
    """ĐỌC cờ Execute từ Sheet -> trạng thái THẬT (5.4). Đây là nơi client (Apps
    Script) biết kết quả sau khi POST trả 202. Kèm cờ `running` in-memory (tham
    khảo). Không thấy dòng APPROVE -> execute=None (chưa duyệt/đã đổi Status)."""
    item = _read_topic_context(topic_key)
    execute = item.get("execute") if item else None
    with _lock:
        is_running = topic_key in _running
    return {"topic_key": topic_key, "execute": execute, "running": is_running}
