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

## Đã kiểm thật (smoke test, không phải mock) — 2026-07-19

Chạy `uvicorn api.main:app --host 127.0.0.1 --port 8899` foreground thật
trên PC-A, gọi bằng `curl` từ tiến trình khác (không phải `TestClient`):

| Ca | Lệnh | Kỳ vọng | Thực tế |
|---|---|---|---|
| 1 | `GET /health` | 200 | **200** — `{"status":"ok","time":"..."}` |
| 2 | `POST /webhook/execute` token sai | 401 | **401** — `{"detail":"Token không hợp lệ"}` |
| 3 | `POST /webhook/execute` hợp lệ | 202 | **202** — `{"accepted":true,"topic_key":"..."}` |
| 4 | `POST` lại NGAY cùng `topic_key` | 409 | **409** — `{"detail":"topic_key '...' đang được xử lý -- bỏ qua, chống double-fire."}` |

Ca 4 lúc đầu 2 lần liên tiếp trả về 202 thay vì 409 — nguyên nhân: độ trễ
giả lập của stub (`asyncio.sleep(0.1)`) quá ngắn so với khoảng cách thật
giữa 2 lệnh gọi tuần tự (mỗi lệnh là 1 vòng round-trip riêng, không phải
2 request bắn đồng thời) — cửa sổ 0,1s và cả 3s đều bị lỡ. Đã **TẠM** tăng
`asyncio.sleep()` lên 20s để có đủ thời gian gọi ca 4 trước khi stub tự
xong, xác nhận 409 hoạt động đúng, rồi **khôi phục lại 0,1s** ngay sau đó
(xác nhận bằng `git diff` rỗng trên file này + chạy lại 24/24 test xanh).
Đây là hạn chế của PHƯƠNG PHÁP TEST tuần tự bằng tay, KHÔNG phải lỗi logic
409 — 8 test tự động (`test_main.py`) đã chứng minh logic đúng bằng cách
chủ động set trạng thái registry, không phụ thuộc timing.

Quan sát phụ: log của `pipeline_bridge.py` (qua `logging.getLogger`) KHÔNG
hiện trong stdout uvicorn — logger tuỳ biến chưa có handler/level cấu hình,
chỉ log request (uvicorn tự log) mới hiện. Không ảnh hưởng hành vi (409 vẫn
đúng), nhưng đáng sửa khi ráp thật để dễ debug production.

`install_service.ps1` — **CHƯA chạy thật** (máy PC-A này không có NSSM để
cài đầy đủ, và cũng KHÔNG có venv tại `.venv\Scripts\python.exe` — venv
thật nằm trên VPS của agent-B, dùng để chạy pytest ở đó). **SỬA 2026-07-19**:
bỏ hẳn cơ chế fallback sang `python` hệ thống khi không thấy venv (rủi ro
hỏng ÂM THẦM nếu service chạy sai bộ package/version) — giờ KHÔNG thấy venv
tại đúng đường dẫn `<repo>\.venv\Scripts\python.exe` → script `Write-Error`
+ `exit 1` ngay, nêu rõ đường dẫn đã thử, không đoán mù (cùng nguyên tắc bài
học A5). Đã xác nhận `python -m uvicorn api.main:app` tự nó chạy được thật
(smoke test ở trên, dùng Python hệ thống trực tiếp không qua script này) —
nhưng **bản thân `install_service.ps1` với venv + NSSM thật vẫn CHƯA được
verify end-to-end trên máy nào cả**, chỉ verify logic path bằng đọc code.

## RÁP SAU (bắt buộc đọc trước khi coi webhook "xong")

1. **`api/pipeline_bridge.py::run_pipeline()`** — hiện là stub (sleep giả lập, luôn trả `"DONE"`). Phải thay bằng lệnh gọi `produce_from_sheet` thật — **chữ ký giả định `produce_from_sheet(topic_key: str) -> status` CHƯA được đối chiếu với code thật** (lúc viết module này, `scripts/produce_from_sheet.py` đang nằm trong vùng agent-B sửa dở, chưa commit — cố ý không đụng để tránh xung đột).
2. **`api/main.py::report_result()`** — hiện chỉ log, không ghi Sheet thật. Phải nối vào cơ chế ghi cột Execute (nghi vấn `sheets_board.py::set_execute_values`, **chưa xác nhận tên hàm/chữ ký thật**).
3. **Đăng ký endpoint với Apps Script** — chưa viết phía Apps Script (nút "Thực Thi" hiện chưa gọi HTTP đi đâu cả), và chưa có tunnel (ngrok/Cloudflare Tunnel/reverse proxy) để endpoint này ra được internet từ VPS.
4. **[ĐÃ CHỐT — Lead quyết định 2026-07-19]** KHÔNG xây trạng thái bền thứ hai cho double-fire. Lý do: idempotency bền vững ĐÃ tồn tại — cờ `Execute` trên Sheet (`empty→RUN→DONE/FAILED/NEEDS_HUMAN`). Hai cơ chế bền cho cùng một trạng thái = hai nguồn sự thật, cấm. **HỆ QUẢ BẮT BUỘC khi ráp**: `webhook_execute()` phải ĐỌC cờ `Execute` trên Sheet TRƯỚC khi nhận việc — thấy `RUN` → trả 409 giống như đang trùng registry. Registry in-memory hiện tại CHỈ là lưới nhanh cục bộ (đỡ 1 round-trip đọc Sheet cho ca double-click sát nhau trong cùng tiến trình), KHÔNG phải nguồn sự thật — cờ Sheet mới là nguồn sự thật.
   ⚠️ **Rủi ro đã ghi nhận, KHÔNG xử ở nấc này**: service chết giữa chừng lúc đang xử lý → cờ `Execute` kẹt ở `RUN` vĩnh viễn (không ai đặt lại `DONE`/`FAILED`). Nấc 1 xử tay (người vận hành tự xoá ô về rỗng). Xử tử tế hơn khi có Document Store (`store/`) theo dõi tiến trình bền hơn cờ Sheet đơn thuần. **Cần thêm mục C6 vào `docs/VPS_MIGRATION_BACKLOG.md`** — CHƯA làm được trong task này vì nằm ngoài phạm vi `api/`/`store/`/`apps_script/` đã chốt, Lead/phiên sau tự thêm.
5. **`requirements-webhook.txt` riêng** — cần hợp nhất vào `requirements.txt` gốc (hoặc giữ tách nếu muốn webhook là optional dependency) khi ráp.
