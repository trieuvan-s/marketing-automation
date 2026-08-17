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
from twmkt.utils.telegram_notifier import make_notifier  # noqa: E402 -- TASK-037

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
    hệ thống chỉ nhận 1, 4 lượt duyệt BỊ XOÁ SẠCH) VÀ LẠI TÁI PHÁT ở Gate 2
    tab CONTENT ngày 15/08 (TASK-035): `render_*_to_sheet()` từng dựng lại
    TOÀN BỘ tab từ store, kể cả cột NGƯỜI-SỞ-HỮU. TASK-035 sửa TẬN GỐC (không
    còn vá kiểu CAS/rebuild) -- `render_context_to_sheet()`/`render_content_
    to_sheet()` giờ CHỈ ghi dải cột MÁY-SỞ-HỮU cho dòng đã tồn tại, KHÔNG BAO
    GIỜ đụng cột người dù ingest có chạy trước hay không -- xem docstring
    module `store/sync_service.py`. Ingest TRƯỚC render ở đây vẫn giữ (cột
    "Output" của CONTENT là ngoại lệ hybrid cần ingest trước để không mất bản
    sửa tay -- xem `_CONTENT_USER_COLS`)."""
    ss.ingest_context_from_sheet(board)
    ss.ingest_content_from_sheet(board)
    ss.render_context_to_sheet(board)
    ss.render_content_to_sheet(board)


def _handle_produce_business_outcome(job: dict, result: dict, *, settings) -> None:
    """TASK-037 (2026-08-17) — đóng lỗ hổng "Execute=FAILED nằm im vô thời
    hạn" (Lead đo trực tiếp 14-15/08). Gọi SAU khi `produce_from_sheet.run()`
    dispatch job "produce" THÀNH CÔNG (không raise — crash hạ tầng thật đã có
    nhánh except riêng ở run_once(), KHÔNG đi qua đây).

    `result["failed"]` > 0 nghĩa là ĐÚNG topic của job này (run_once() luôn
    gọi run() với topic_keys=[job['topic_key']], limit=1 — CHỈ 1 topic có thể
    khớp) kết thúc agents.writer.WriterOutcome.FAILED (lỗi TẠM THỜI hạ tầng
    gọi LLM — writer ĐÃ tự retry NỘI BỘ hết `writer.max_retries` lần rồi mới
    tới đây). WriterOutcome.NEEDS_HUMAN (guardrail reject — lỗi VĨNH VIỄN)
    rơi vào `result["needs_human"]`, KHÔNG BAO GIỜ vào `result["failed"]` —
    hàm này do đó KHÔNG BAO GIỜ retry ca NEEDS_HUMAN, đúng ranh giới
    agents/writer.py đã định nghĩa (xem CLAUDE.md "AI hiểu ở Brief, CODE phán
    ở Guardrail" — hàm này chỉ ĐỌC lại ranh giới đó, không tự vẽ thêm).

    ĐẾM BỀN qua `payload_json` của chính job (KHÔNG đổi schema execution_queue
    — cột đã có sẵn, chỉ dùng thêm 1 khoá JSON `produce_retry_attempt`): job
    tự retry MANG payload này sang job MỚI khi enqueue lại, nên số lần đã thử
    sống sót qua khởi động lại worker (dữ liệu nằm trong SQLite trên đĩa,
    KHÔNG phải biến RAM của tiến trình worker). Hết trần
    (`queue.produce_retry_max_attempts`, mặc định 1 theo quyết định chủ dự án
    "retry ít nhất 1 lần") -> KHÔNG enqueue nữa (chặn lặp vô hạn/đốt ngân
    sách) -> báo Telegram kèm lý do THẬT lấy từ `result["failed_details"]`
    (agents/writer.WriterResult.reason, xem produce_from_sheet.py)."""
    failed = int(result.get("failed") or 0)
    topic_key = job["topic_key"]
    prior_attempts = int((job.get("payload") or {}).get("produce_retry_attempt", 0))

    if failed <= 0:
        # KHÔNG FAILED lần này -- nếu bản thân job NÀY là 1 lần tự retry
        # (prior_attempts > 0) thì đây là "tự phục hồi" -- báo (tuỳ chọn, mặc
        # định TẮT, xem settings.yaml queue.notify_on_retry_success) để Lead
        # biết cơ chế retry có tác dụng thật, KHÔNG chỉ im lặng.
        if prior_attempts > 0 and bool(settings.get("queue.notify_on_retry_success", False)):
            print(f"[queue-worker] Job #{job['id']} topic_key={topic_key!r} PHỤC HỒI sau "
                 f"{prior_attempts} lần tự retry trước đó — báo Telegram "
                 f"(queue.notify_on_retry_success=true).")
            make_notifier(settings).notify(
                "produce_retry_recovered", topic_key=topic_key, attempts=prior_attempts + 1)
        return

    detail = (result.get("failed_details") or {}).get(topic_key, {})
    reason = detail.get("reason") or "(không rõ lý do — run() không trả chi tiết)"
    title = detail.get("title") or topic_key
    max_attempts = int(settings.get("queue.produce_retry_max_attempts", 1))
    backoff_s = float(settings.get("queue.produce_retry_backoff_s", 60))

    if prior_attempts < max_attempts:
        next_attempt = prior_attempts + 1
        print(f"[queue-worker] Job #{job['id']} topic_key={topic_key!r} Execute=FAILED "
             f"(lỗi tạm thời hạ tầng) — TỰ tạo lại job, lần thử {next_attempt}/{max_attempts}, "
             f"chờ {backoff_s:.0f}s trước khi enqueue. Lý do: {reason}")
        time.sleep(backoff_s)
        new_job_id = qs.enqueue(topic_key, job_type="produce",
                                payload={"produce_retry_attempt": next_attempt})
        print(f"[queue-worker] Đã tạo lại job #{new_job_id} cho topic_key={topic_key!r} "
             f"(lần tự động {next_attempt}/{max_attempts}).")
    else:
        total_attempts = prior_attempts + 1
        print(f"[queue-worker] Job #{job['id']} topic_key={topic_key!r} Execute=FAILED "
             f"HẾT TRẦN tự retry ({total_attempts} lần đã thử, giới hạn queue."
             f"produce_retry_max_attempts={max_attempts}) — CHỐT trạng thái, KHÔNG thử nữa. "
             f"Báo Telegram. Lý do: {reason}")
        make_notifier(settings).notify(
            "produce_retry_exhausted", topic=title, topic_key=topic_key,
            attempts=total_attempts, reason=reason)


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

    produce_result = None
    try:
        if job_type == "render_assets":
            # run() tự quét CONTENT tìm dòng Gate2=APPROVE chưa có AssetPath và
            # tự idempotent -> KHÔNG cần lọc theo topic_key ở đây; topic_key
            # trên job chỉ để truy vết "ai kích hoạt lượt render này".
            render_production_assets.run()
        else:
            # TASK-031 — payload force=True (gắn lúc enqueue bởi
            # ingest_context_from_sheet() khi người chọn "Xử lý lại" ở Gate 1)
            # -> truyền `force` xuống run() để BỎ QUA existing_content_keys()
            # cho ĐÚNG topic này. KHÔNG truyền kwarg `force` khi job KHÔNG có
            # cờ này (tường minh — giữ nguyên chữ ký gọi cũ cho rerun bình
            # thường, tránh mọi hiểu lầm "APPROVE lại là ép chạy lại"). KHÔNG
            # áp cho job re-enqueue tự động của TASK-037 (payload chỉ mang
            # "produce_retry_attempt", KHÔNG mang "force") — retry tự động
            # PHẢI giữ hành vi idempotent bình thường (existing_content_keys()
            # vẫn chặn ghi trùng nếu vì lý do gì đó đã có CONTENT), KHÁC hẳn
            # luồng "Xử lý lại" chủ động của người (TASK-031).
            run_kwargs = {"topic_keys": [job["topic_key"]], "limit": 1}
            if (job.get("payload") or {}).get("force"):
                run_kwargs["force"] = {job["topic_key"]}
            produce_result = produce_from_sheet.run(**run_kwargs)
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

    # TASK-037 -- NGOÀI try/except phía trên có chủ ý: job này ĐÃ được chốt
    # done/failed rồi (dòng trên) -- 1 lỗi ở BƯỚC RETRY (vd qs.
    # enqueue() DB lỗi) không được phép lật ngược trạng thái job GỐC vừa ghi
    # (mark_done rồi lại bị except phía trên đè thành 'failed' là SAI, đánh
    # lừa lịch sử dispatch thật). Cùng nếp KHÔNG bọc try như _sync_sheet() bên
    # dưới -- lỗi ở đây (hiếm, chỉ khi SQLite hỏng) được phép nổ rõ.
    if job_type == "produce" and produce_result is not None:
        _handle_produce_business_outcome(job, produce_result, settings=settings)

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
