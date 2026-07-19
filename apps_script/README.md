# apps_script/ — nửa "Sheet" của dây webhook nấc 1

> Nửa còn lại: `api/main.py` (webhook nhận request). File này bắn HTTP đi
> khi user bấm menu "Thực Thi". Xem `docs/VPS_MIGRATION_BACKLOG.md` A1.

## ⚠️ CẢNH BÁO BẮT BUỘC ĐỌC TRƯỚC KHI CÀI

Script này **CHƯA từng chạy trên Sheet sống** — chỉ mới viết code + test
tay cục bộ (không thể test Apps Script ngoài môi trường Google Sheet thật).
Trước lần chạy thật ĐẦU TIÊN trên Sheet sản xuất:

1. **Snapshot toàn bộ Sheet** (File > Make a copy, hoặc export từng tab ra
   CSV) — theo đúng "QUY TẮC VÀNG KHI ĐỘNG VÀO SHEET" trong
   `docs/VPS_MIGRATION_BACKLOG.md`: `migrate_rows()`/đổi cấu trúc cột từng
   XOÁ RỖNG dữ liệu Gate 1 thật trong quá khứ — script MỚI luôn cần snapshot
   trước, không riêng gì script này.
2. Chạy thử trên 1 **Sheet TEST riêng** trước (không phải Sheet production)
   — script tự kiểm tên cột (`_buildHeaderIndex`) và sẽ tự báo lỗi rõ nếu
   không tìm thấy cột cần thiết, nhưng vẫn nên xác nhận hành vi thật trên
   dữ liệu không quan trọng trước.
3. **KHÔNG tự bật script này chạy production** — việc đó để Lead/user tự
   quyết định thời điểm, tách khỏi việc viết code (đúng phạm vi task này).

## Cách cài (thủ công, qua giao diện Google Sheet)

1. Mở Google Sheet → **Extensions → Apps Script**.
2. Tạo file mới (hoặc dán đè nếu đã có) → dán nguyên nội dung
   `execute_trigger.gs`.
3. **Project Settings** (biểu tượng bánh răng bên trái) → **Script
   Properties** → **Add script property** → thêm 2 khoá:
   - `WEBHOOK_URL` — URL đầy đủ tới endpoint (vd
     `https://<tunnel-domain>/webhook/execute`) — **CHƯA CÓ GIÁ TRỊ THẬT**,
     xem "RÁP SAU" bên dưới.
   - `WEBHOOK_TOKEN` — PHẢI khớp CHÍNH XÁC biến `WEBHOOK_TOKEN` phía
     `api/.env` trên máy chạy webhook.
   (Chỉ ghi TÊN 2 khoá ở đây — giá trị thật nhập trực tiếp trong giao diện
   Apps Script, KHÔNG BAO GIỜ hardcode trong file `.gs`, không dán vào tài
   liệu/chat/commit message.)
4. Lưu (Ctrl+S / File > Save).
5. Đóng tab Apps Script, quay lại Sheet, **reload trang** — menu
   **"Marketing Automation" → "Thực Thi (dòng đang chọn)"** sẽ xuất hiện.

## Quyền Apps Script sẽ xin (lúc chạy lần đầu)

- **Đọc/ghi Google Sheet hiện tại** — để đọc cột `Duyệt Context`/`TopicKey`
  và ghi cột `Execute`.
- **Kết nối dịch vụ bên ngoài (UrlFetchApp)** — để gọi HTTP tới webhook.

Không xin quyền nào khác (không đọc Gmail/Drive/Calendar...).

## Cách dùng (sau khi cài + có URL thật)

1. Chọn 1 dòng trên tab **CONTEXT** đã có `Duyệt Context = APPROVE`.
2. Menu **Marketing Automation → Thực Thi (dòng đang chọn)**.
3. Script tự kiểm: đúng tab CONTEXT? đã chọn dòng dữ liệu (không phải
   header)? `Duyệt Context = APPROVE`? có `TopicKey`? — thiếu điều kiện nào
   thì báo rõ, không gửi.
4. Gửi HTTP POST, xử lý phản hồi:
   - **202** → ghi `Execute = RUN`, báo "đã gửi, đang xử lý".
   - **409** → ghi `Execute = RUN` (idempotent — nghĩa là đã đang chạy),
     báo "đang chạy rồi".
   - **401** → KHÔNG ghi gì vào `Execute`, báo "sai token" (lỗi cấu hình hệ
     thống, không phải lỗi của dòng này).
   - Lỗi mạng/timeout → KHÔNG ghi gì, báo lỗi rõ, **KHÔNG tự động thử lại**
     (retry mù là nguồn double-fire — xem `api/README.md` mục chống
     double-fire).

## RÁP SAU

1. **`WEBHOOK_URL` là placeholder, chưa có giá trị thật** — phụ thuộc
   tunnel (ngrok/Cloudflare Tunnel/reverse proxy) đưa `api/main.py` ra
   internet từ VPS, **chưa dựng** (xem `api/README.md` mục RÁP SAU #3).
2. Chưa có cơ chế cập nhật `Execute` NGƯỢC LẠI khi webhook xử lý xong
   (DONE/FAILED/NEEDS_HUMAN) — Apps Script này chỉ ghi `RUN` lúc GỬI đi,
   không biết kết quả cuối. Cần 1 trong 2 hướng: (a) webhook tự ghi ngược
   qua Sheets API (xem `api/README.md::report_result()` RÁP SAU #2), hoặc
   (b) Apps Script có `onEdit`/trigger định kỳ tự đọc `/status/{topic_key}`
   — CHƯA quyết định hướng nào, để Lead chọn khi ráp.
3. Chưa test được thật (giới hạn môi trường — Apps Script chỉ chạy được
   trong Google Sheet thật, không mô phỏng được ở máy dev) — xem cảnh báo
   đầu file trước khi bật production.
