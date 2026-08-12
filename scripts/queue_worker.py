"""PHASE QUEUE (2026-07-27, theo chỉ đạo Lead) — worker ĐỘC LẬP xử lý
`execution_queue` (store/queue_store.py). Thay cơ chế "quét Sheet 30 phút/lần"
(`system_power_on.py::schedule_draft`, vẫn giữ NGUYÊN cho luồng --draft khác)
bằng poll NGẮN (config `queue.poll_interval_s`, mặc định 3s) trên hàng đợi
trong store — đưa độ trễ từ "tới 30 phút" xuống "vài giây", KHÔNG cần
endpoint always-on/VPS (đó là Phần B — Redis/RabbitMQ + webhook thật, xem
`docs/VPS_MIGRATION_BACKLOG.md`).

Script ĐỘC LẬP (chạy như 1 tiến trình riêng, KHÔNG phải thread trong
`system_power_on.py` — theo đúng lựa chọn Lead), khoá 1-worker-1-máy bằng
lock file CÙNG PATTERN `system_power_on.py::acquire_lock()`/`release_lock()`
(tái dùng nguyên hàm, chỉ khác tên file lock — KHÔNG phát minh cơ chế mới).

`run()` (produce_from_sheet.py) VẪN là nơi DUY NHẤT ghi outcome nghiệp vụ
(DONE/FAILED/NEEDS_HUMAN) vào `gate_status.execute` — worker này CHỈ quyết
định KHI NÀO gọi `run()` cho ĐÚNG 1 topic_key đã claim, và đánh dấu job hàng
đợi done/failed dựa trên `run()` có crash hay không (crash hạ tầng thật sự,
KHÁC hẳn NEEDS_HUMAN/FAILED nghiệp vụ mà `run()` tự bắt gọn, không raise).

Chạy:
    python scripts/queue_worker.py

Dừng: Ctrl+C.
"""
from __future__ import annotations

import os
import socket
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
# SỬA LỖI THẬT (2026-08-04, cùng nguyên nhân run_scheduler.py) -- Task
# Scheduler/khởi động tự động chạy tiến trình với cwd MẶC ĐỊNH (thường
# System32), KHÔNG PHẢI thư mục repo. `twmkt.config.load_settings()` đọc
# "config/settings.yaml"/"secrets/.env" theo ĐƯỜNG DẪN TƯƠNG ĐỐI -- ép cwd =
# REPO_ROOT NGAY ĐẦU để worker chạy đúng bất kể ai/gì khởi động tiến trình.
os.chdir(REPO_ROOT)

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

import system_power_on  # noqa: E402 -- tái dùng acquire_lock()/release_lock()
import produce_from_sheet  # noqa: E402
import render_production_assets  # noqa: E402 -- job "render_assets" (Gate 2)
from twmkt.config import data_path, load_settings  # noqa: E402
from twmkt.sheets_board import EXECUTE_FAILED, EXECUTE_RUNNING, SheetsBoard  # noqa: E402

from store import pipeline_store as ps  # noqa: E402
from store import queue_store as qs  # noqa: E402
from store import sync_service as ss  # noqa: E402


def _lock_path() -> Path:
    """Tên file lock KHÁC `power_on.lock` (script khác, khoá riêng — 1 máy có
    thể chạy CẢ system_power_on.py LẪN queue_worker.py cùng lúc, đây là 2
    tiến trình khác vai trò, không tranh nhau)."""
    return data_path("logs", "queue_worker.lock")


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _open_board(settings) -> SheetsBoard:
    sheet_id = (os.environ.get("TWMKT_SHEET_ID") or settings.get("sheets.spreadsheet_id") or "").strip()
    creds = (os.environ.get("TWMKT_SHEETS_CREDS") or settings.get("sheets.creds_path") or "").strip()
    if not sheet_id or not creds:
        raise SystemExit("Thiếu sheets.spreadsheet_id/creds_path (settings.yaml hoặc ENV).")
    return SheetsBoard(spreadsheet_id=sheet_id, creds_path=creds)


def _sync_sheet(board) -> None:
    """INGEST TRƯỚC, RENDER SAU — LUÔN LUÔN, không bao giờ render trần.

    BUG THẬT (2026-07-28, bắt được ở lượt e2e đầu tiên — Lead duyệt 5 chủ đề,
    hệ thống chỉ nhận 1, 4 lượt duyệt BỊ XOÁ SẠCH): `render_*_to_sheet()` dựng
    lại TOÀN BỘ tab từ store, kể cả các cột NGƯỜI-SỞ-HỮU (Duyệt Context/Notes/
    Output Type). Một lượt `run()` chạy hàng phút (gọi LLM); người duyệt thêm
    chủ đề TRONG quãng đó; xong việc, worker render từ store — store chưa biết
    những lượt duyệt mới nên ghi đè PENDING lên chúng. Thao tác người biến mất
    KHÔNG một tiếng báo.

    Ingest ngay trước mỗi lần render thu hẹp cửa sổ mất mát từ "cả lượt chạy
    job" (phút) xuống "giữa 2 lệnh gọi API liền nhau" (giây). CỬA SỔ NÀY VẪN
    CÒN — đóng hẳn cần render CHỈ các cột máy-sở-hữu thay vì clear+ghi cả tab,
    xem ghi chú trong docs/VPS_MIGRATION_BACKLOG.md.

    `rebuild=False` (TASK-032) -- lượt gọi này lặp lại SAU MỖI job, đúng kịch
    bản có race thật giữa job KHÁC và ingest (TASK-029) nên PHẢI qua CAS
    (`render_context_to_sheet()` mặc định BỎ QUA CAS từ TASK-032, xem docstring
    hàm đó -- lối gọi trực tiếp/thủ công KHÔNG ingest trước mới dùng default)."""
    ss.ingest_context_from_sheet(board)
    ss.ingest_content_from_sheet(board)
    ss.render_context_to_sheet(board, rebuild=False)
    ss.render_content_to_sheet(board)


def run_once(*, settings, worker_id: str, board=None) -> bool:
    """1 vòng: (0) NẾU có `board` — ingest Sheet trước (bắt thao tác người vừa
    duyệt Gate1/Gate2/Gate3, ĐÚNG chỗ `store/sync_service.py::ingest_context_
    from_sheet()` tự enqueue job mới — xem VIỆC PHÁT SINH 2026-07-27: KHÔNG có
    bước này, hàng đợi sẽ KHÔNG BAO GIỜ tự thấy thao tác duyệt trên Sheet, vì
    trước đây KHÔNG có gì gọi ingest định kỳ). CHỈ gọi ingest MỖI VÒNG (đọc +
    ghi có điều kiện, rẻ) — KHÔNG gọi render_*_to_sheet() (rebuild toàn bảng,
    tốn quota) khi hàng đợi RỖNG. (1) dọn claim kẹt -> (2) lấy 1 job -> xử lý
    -> (3) NẾU có `board` VÀ vừa xử lý xong 1 job — render lại Sheet NGAY (xem
    VIỆC PHÁT SINH #2, 2026-07-27: thiếu bước này -> Sheet đứng hình mãi ở
    Execute="RUN"/CONTENT trống dù store ĐÃ có kết quả DONE/FAILED/ERROR thật,
    khiến người nhìn Sheet tưởng "không xử lý được" dù hệ thống đã chạy xong).
    Trả True nếu VỪA xử lý 1 job (để caller quyết có sleep hay lặp lại NGAY —
    hàng đợi còn nhiều job thì xử liên tục, không đợi hết `poll_interval_s`
    mỗi job)."""
    if board is not None:
        ss.ingest_context_from_sheet(board)
        ss.ingest_content_from_sheet(board)
    # Lưới an toàn cho "chuyển tiếp bị mất" — chỉ đọc store, không tốn quota
    # Sheets. Xem docstring reconcile_pending_requests().
    ss.reconcile_pending_requests()

    lease_timeout_s = float(settings.get("queue.lease_timeout_s", 600))
    max_attempts = int(settings.get("queue.max_attempts", 3))
    released = qs.release_stale_claims(lease_timeout_s, max_attempts=max_attempts)
    if released:
        print(f"[queue-worker] Giải phóng {released} job kẹt (claim quá hạn lease).")

    # KHÔNG lọc job_type: worker phục vụ CẢ 2 cổng (2026-07-28) — "produce"
    # (Gate 1 duyệt Context -> sinh nội dung) và "render_assets" (Gate 2 duyệt
    # Content -> render ảnh, mở đường tới Gate 3). Lọc cứng "produce" như bản
    # cũ sẽ khiến job Gate 2 nằm lại hàng đợi VĨNH VIỄN, không ai xử lý.
    job = qs.claim_next(worker_id)
    if job is None:
        return False

    job_type = job.get("job_type") or "produce"
    print(f"[queue-worker] Nhận job #{job['id']} [{job_type}] topic_key={job['topic_key']!r}")
    if job_type == "produce":
        # Cờ "Running..." ghi NGAY sau claim, TRƯỚC khi gọi run() (một lượt
        # run() thật mất hàng chục giây tới vài phút vì gọi LLM) -- và render
        # lên Sheet luôn, để người duyệt thấy "đang chạy" thay vì nhìn ô đứng
        # im tưởng hệ thống không nhận. Đây là lý do CHÍNH của cờ Running...
        # (2026-07-28, yêu cầu Lead): phản hồi thị giác cho quãng chờ dài.
        # KHÔNG áp cho render_assets: Execute là cờ của tuyến CONTEXT/Gate 1,
        # tiến trình Gate 2 phản ánh qua cột AssetPath, không phải cột này.
        ps.mark_execute(job["topic_key"], EXECUTE_RUNNING)
        if board is not None:
            _sync_sheet(board)

    try:
        if job_type == "render_assets":
            # run() tự quét CONTENT tìm dòng Gate2=APPROVE chưa có AssetPath và
            # tự idempotent -> KHÔNG cần lọc theo topic_key ở đây; topic_key
            # trên job chỉ để truy vết "ai kích hoạt lượt render này".
            render_production_assets.run()
        else:
            produce_from_sheet.run(topic_keys=[job["topic_key"]], limit=1)
        qs.mark_done(job["id"])
        print(f"[queue-worker] Job #{job['id']} DONE (dispatch) — xem gate_status.execute "
             f"trên Sheet cho kết quả NGHIỆP VỤ thật (DONE/FAILED/NEEDS_HUMAN).")
    except Exception as e:   # noqa: BLE001 -- lưới an toàn crash hạ tầng, KHÁC outcome nghiệp vụ
        qs.mark_failed(job["id"], str(e))
        # run() crash TRƯỚC khi kịp tự ghi outcome -> Execute còn kẹt ở
        # "Running..." vĩnh viễn nếu không hạ ở đây. FAILED (không phải
        # NEEDS_HUMAN) vì crash hạ tầng là lỗi TẠM, lượt sau thử lại được.
        if job_type == "produce":
            ps.mark_execute(job["topic_key"], EXECUTE_FAILED)
        print(f"[queue-worker] Job #{job['id']} FAILED (crash hạ tầng, không phải NEEDS_HUMAN "
             f"nghiệp vụ — cái đó run() tự bắt gọn): {e!r}")

    if board is not None:
        _sync_sheet(board)
        print(f"[queue-worker] Đã đồng bộ lại CONTEXT/CONTENT trên Sheet (job #{job['id']}).")
    return True


def run_forever() -> None:
    settings = load_settings()
    system_power_on.acquire_lock(_lock_path())
    board = _open_board(settings)
    poll_interval_s = float(settings.get("queue.poll_interval_s", 3))
    worker_id = _worker_id()
    print(f"[queue-worker] Bắt đầu ({worker_id}), poll {poll_interval_s}s khi hàng đợi rỗng "
         f"(mỗi vòng tự ingest Sheet trước khi kiểm hàng đợi).")
    try:
        while True:
            handled = run_once(settings=settings, worker_id=worker_id, board=board)
            if not handled:
                time.sleep(poll_interval_s)
    except KeyboardInterrupt:
        print("[queue-worker] Dừng theo yêu cầu (Ctrl+C).")


if __name__ == "__main__":
    run_forever()
