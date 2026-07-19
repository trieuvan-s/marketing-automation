# api/ — FastAPI webhook nấc 1

> Thay scheduler 30' hiện tại (`system_power_on.py`) cho luồng Execute=RUN.
> Xem `docs/VPS_MIGRATION_BACKLOG.md` mục A1. Module này **CHƯA RÁP** vào
> pipeline sản xuất thật — xem "RÁP SAU" cuối file trước khi coi module này
> là hoàn chỉnh.

## Chạy dev

```bash
pip install -r api/requirements-webhook.txt
export WEBHOOK_TOKEN=mot-chuoi-bi-mat-tuy-chon   # PowerShell: $env:WEBHOOK_TOKEN = "..."
uvicorn api.main:app --reload --port 8899
```

Kiểm tra: `curl http://127.0.0.1:8899/health`

## Chạy test

```bash
pip install -r api/requirements-webhook.txt
python -m pytest api/test_main.py -v
```

## 3 route

| Route | Method | Mục đích |
|---|---|---|
| `/webhook/execute` | POST | Body `{"topic_key": str, "token": str}` — trả **202** ngay (không chờ xử lý xong), xử lý thật chạy nền. Token sai → 401. `topic_key` đang xử lý → 409 (chống double-fire). |
| `/health` | GET | Cho NSSM/monitor kiểm tiến trình còn sống. Không kiểm gì sâu (không chạm DB/pipeline). |
| `/status/{topic_key}` | GET | `{"topic_key": ..., "running": bool}` — tham khảo cho Apps Script tự kiểm trước khi bắn lại. |

## Biến môi trường cần

- `WEBHOOK_TOKEN` (**bắt buộc**) — shared token, endpoint so khớp hằng-thời-gian (`secrets.compare_digest`). Thiếu biến này → mọi request đều 401.
- `WEBHOOK_PORT` (tuỳ chọn, mặc định 8899 nếu không set — chỉ dùng bởi `install_service.ps1`, KHÔNG được `main.py` tự đọc, port truyền qua `uvicorn --port` lúc chạy).

## Cài thành Windows Service (VPS)

```powershell
.\api\install_service.ps1
```

Xem chi tiết/cảnh báo trong docstring đầu file `install_service.ps1` — **CHƯA test thật** trên máy có NSSM, chỉ viết theo tài liệu NSSM.

## Chống double-fire — thiết kế nấc 1

Registry `set` in-memory + `threading.Lock`, đơn tiến trình. **Hạn chế đã biết**: mất trạng thái khi service restart (1 request đang chạy lúc restart sẽ "quên", request trùng sau đó không bị chặn). Chấp nhận được ở nấc 1 vì restart không thường xuyên — `store/document_store.py` (viết cùng lượt với module này) là ứng viên thay thế bằng trạng thái bền khi ráp thật, nhưng **CHƯA nối** — 2 module độc lập nhau ở nấc này.

## RÁP SAU (bắt buộc đọc trước khi coi webhook "xong")

1. **`api/pipeline_bridge.py::run_pipeline()`** — hiện là stub (sleep giả lập, luôn trả `"DONE"`). Phải thay bằng lệnh gọi `produce_from_sheet` thật — **chữ ký giả định `produce_from_sheet(topic_key: str) -> status` CHƯA được đối chiếu với code thật** (lúc viết module này, `scripts/produce_from_sheet.py` đang nằm trong vùng agent-B sửa dở, chưa commit — cố ý không đụng để tránh xung đột).
2. **`api/main.py::report_result()`** — hiện chỉ log, không ghi Sheet thật. Phải nối vào cơ chế ghi cột Execute (nghi vấn `sheets_board.py::set_execute_values`, **chưa xác nhận tên hàm/chữ ký thật**).
3. **Đăng ký endpoint với Apps Script** — chưa viết phía Apps Script (nút "Thực Thi" hiện chưa gọi HTTP đi đâu cả), và chưa có tunnel (ngrok/Cloudflare Tunnel/reverse proxy) để endpoint này ra được internet từ VPS.
4. **State machine Execute** — theo `docs/VPS_MIGRATION_BACKLOG.md` A1, Lead cần quyết định có cần trạng thái TRUNG GIAN (đã gọi webhook, chờ phản hồi) hay không, trước khi ráp thật — chưa quyết định ở nấc này.
5. **`requirements-webhook.txt` riêng** — cần hợp nhất vào `requirements.txt` gốc (hoặc giữ tách nếu muốn webhook là optional dependency) khi ráp.
