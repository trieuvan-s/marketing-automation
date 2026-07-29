# api/ — FastAPI webhook nấc 1

> Thay scheduler 30' hiện tại (`system_power_on.py`) cho luồng Execute=RUN.
> Xem `docs/VPS_MIGRATION_BACKLOG.md` mục A1.

## PHASE QUEUE (2026-07-27) — ĐÃ RÁP vào `store/queue_store.py`

Webhook giờ **CHỈ ENQUEUE** job vào `execution_queue` (SQLite,
`store/queue_store.py`) — KHÔNG còn đọc/ghi Sheet trực tiếp, KHÔNG còn
registry in-memory. `scripts/queue_worker.py` (tiến trình RIÊNG, poll hàng
đợi vài giây/lần) là nơi THẬT SỰ gọi `produce_from_sheet.run()`.

**ĐẢO NGƯỢC quyết định Lead cũ (2026-07-19, xem lịch sử git mục "RÁP SAU" #4
bên dưới nếu cần đối chiếu)**: trước đây "KHÔNG xây trạng thái bền thứ hai
cho double-fire" (cờ Execute trên Sheet là nguồn DUY NHẤT). Lead nay
(2026-07-27) muốn đúng 1 trạng thái bền MỚI: hàng đợi trong store —
`execution_queue` giờ là nguồn double-fire DUY NHẤT, giải quyết dứt điểm rủi
ro "service chết giữa chừng → registry mất/Execute kẹt RUN" (mục C8 cũ) nhờ
`claimed_at` + `queue_store.release_stale_claims()`.

`pipeline_bridge.py` đã **XOÁ** (dead code sau khi webhook không còn gọi
`produce_from_sheet.run()` trực tiếp nữa — việc đó nay là của
`queue_worker.py`).

## Chạy dev

```bash
pip install -r api/requirements-webhook.txt
export WEBHOOK_TOKEN=mot-chuoi-bi-mat-tuy-chon   # PowerShell: $env:WEBHOOK_TOKEN = "..."
uvicorn api.main:app --reload --port 8899
```

Hoặc tạo file `api/.env` (tự gitignore, KHÔNG BAO GIỜ commit) với
`WEBHOOK_TOKEN=...` — `main.py` tự nạp qua `python-dotenv`
(`override=False`, ENV thật của process luôn thắng file).

Kiểm tra: `curl http://127.0.0.1:8899/health`

**Chạy song song `scripts/queue_worker.py`** để job thật sự được xử lý (xem
gốc repo `python scripts/queue_worker.py`) — webhook chỉ enqueue, không tự
chạy pipeline.

## Chạy test

```bash
pip install -r api/requirements-webhook.txt
python -m pytest api/test_main.py -v
```

## 3 route

| Route | Method | Mục đích |
|---|---|---|
| `/webhook/execute` | POST | Body `{"topic_key": str, "token": str}` — token sai → 401; đã có job `queued`/`claimed` cho topic_key này → 409 (chống double-fire, xem `queue_store.find_pending()`); ngược lại → **202** + `job_id` (enqueue, xử lý thật do `queue_worker.py` làm, không đồng bộ ở đây). |
| `/health` | GET | Cho NSSM/monitor kiểm tiến trình còn sống. Không kiểm gì sâu (không chạm DB/pipeline). |
| `/status/{topic_key}` | GET | `{"topic_key", "status", "job_id"}` — trạng thái job MỚI NHẤT trong hàng đợi (`queued`/`claimed`/`done`/`failed`, `None` nếu chưa từng có job). |

## Biến môi trường cần

- `WEBHOOK_TOKEN` (**bắt buộc**) — shared token, endpoint so khớp hằng-thời-gian (`secrets.compare_digest`). Thiếu biến này → mọi request đều 401.
- `DOCUMENT_STORE_PATH` (khớp `store/document_store.py`) — webhook đọc/ghi CÙNG file DB với pipeline/queue_worker, phải trỏ đúng.
- `WEBHOOK_PORT` (tuỳ chọn, mặc định 8899 nếu không set — chỉ dùng bởi `install_service.ps1`, KHÔNG được `main.py` tự đọc, port truyền qua `uvicorn --port` lúc chạy).

## Cài thành Windows Service (VPS)

```powershell
.\api\install_service.ps1
```

Xem chi tiết/cảnh báo trong docstring đầu file `install_service.ps1` —
**CHƯA test thật** trên máy có NSSM, chỉ viết theo tài liệu NSSM. Khi triển
khai thật, `queue_worker.py` CŨNG cần 1 service riêng (không tự khởi động
cùng webhook).

## Còn treo (chưa làm ở phiên này)

1. **Đăng ký endpoint với Apps Script** — chưa viết phía Apps Script (nút
   "Thực Thi" hiện chưa gọi HTTP đi đâu cả), và chưa có tunnel/VPS để endpoint
   này ra được internet. Xem đề xuất Phần B (Redis/RabbitMQ + webhook thật +
   VPS) ở `docs/VPS_MIGRATION_BACKLOG.md`.
2. **`requirements-webhook.txt` riêng** — cần hợp nhất vào `requirements.txt`
   gốc (hoặc giữ tách nếu muốn webhook là optional dependency) khi ráp thật.
3. **`install_service.ps1`** — vẫn chưa verify end-to-end trên máy có NSSM
   (như trước phiên này), và giờ cần cài THÊM 1 service cho `queue_worker.py`.
