# TEST_RESULT.md

> Ghi đè sau mỗi lần chạy `python tests/test_pipeline.py` liên quan tới 1 task
> đang làm — KHÔNG tích luỹ log. Đây là "test xanh" (điều kiện CẦN) — vẫn phải
> chấm trên output/dữ liệu thật riêng cho việc có rủi ro chất lượng thật (xem
> `CLAUDE.md` — "Chấm trên OUTPUT THẬT").

## Lần chạy gần nhất
- **Thời điểm:** 2026-07-27 (agent-A — fix dropdown "Output Type" (thiếu nhánh validation, lộ 4 giá trị cũ của Execute) + mặc định hiển thị "AUTO" cho ô rỗng; PHIÊN TRƯỚC trong cùng ngày: PHASE QUEUE — hàng đợi execution_queue + queue_worker.py + api/main.py ráp vào hàng đợi)
- **Lệnh:** `python -m pytest`

## Kết quả
- **Suite:** PASS
- **Số liệu:** 618 passed, 0 failed / 618 tổng (597 trước phiên này + 21 test mới)
- **Ghi chú:** Test mới cho PHASE QUEUE:
  - `store/test_queue_store.py` (17 test) — enqueue/dedup, `claim_next` atomic
    (2 kết nối SQLite "đồng thời"), FIFO theo `id`, `mark_done`/`mark_failed`,
    `release_stale_claims` (requeue + failed hẳn sau `max_attempts`).
  - `store/test_sync_service.py` (+5 test) — `ingest_context_from_sheet()`
    enqueue đúng lúc Execute chuyển "RUN" (bootstrap Gate1 APPROVE, topic mới
    đã duyệt sẵn, NEEDS_HUMAN→RUN), không enqueue khi Gate1 còn PENDING,
    không dồn job trùng qua 2 lần ingest.
  - `tests/test_pipeline.py` (+4 test) — `queue_worker.run_once()`: hàng đợi
    rỗng, claim→run()→mark_done, `run()` raise→mark_failed, giải phóng claim
    kẹt (lease timeout) rồi xử lý lại NGAY trong cùng lượt gọi.
  - `api/test_main.py` (viết lại hoàn toàn, 11 test) — webhook enqueue vào
    `queue_store` thay đọc/ghi Sheet + registry in-memory cũ; 409 khi đã
    `queued`/`claimed`, 202 khi job trước đã `done`, `/status` đọc từ hàng đợi.
  - Đã xác nhận THẬT (không chỉ test): enqueue 1 job cho topic Google thật đã
    DONE → `queue_worker.run_once()` thật → job chuyển `done`, KHÔNG gọi LLM
    (topic không còn `execute in (RUN,FAILED)`, đúng thiết kế idempotent).
    `uvicorn` thật (không phải TestClient) + `curl` thật xác nhận
    `POST /webhook/execute` → 202, lặp lại → 409, `/status` đúng — cả 2 job
    test đã dọn về `done`, không để lại trạng thái `queued` treo trong store
    thật.
- **Cập nhật 2026-07-27 (cùng ngày, phiên sau)** — fix dropdown "Output Type"
  (bug: cột này chưa từng có nhánh `setDataValidation`, lộ 4 giá trị cũ của
  Execute) + mặc định hiển thị chữ "AUTO" cho ô rỗng thay vì để trắng. Vẫn
  **618 passed, 0 failed** (2 test cũ sửa lại theo hành vi mới + 1 test tăng
  cường assertion, không thêm test mới ròng). **Đã xác nhận THẬT trên Sheet
  production**: gọi `board.format_board()` (idempotent, không đổi dữ liệu —
  đối chiếu snapshot trước/sau khớp 100%), đọc lại `dataValidation` qua Sheets
  API xác nhận Output Type = Article/Long-Article/Infographic/Video/AUTO,
  Execute = RUN/DONE/FAILED/NEEDS_HUMAN (không đổi). Chạy `sync_store_sheet.py`
  xác nhận cả 7 dòng CONTEXT thật đổi từ rỗng → "AUTO" hiển thị rõ ràng.
