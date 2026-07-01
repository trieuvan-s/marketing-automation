# Thiết lập Google Sheets làm cổng duyệt (control-plane)

Mục tiêu: đội Turtle Wealth duyệt nội dung ngay trên một Google Sheet, không cần
web app. Sau này thay bằng Dashboard mà không đổi lõi (Sheets chỉ là UI).

## 1. Tạo service account (một lần)
1. Vào Google Cloud Console → tạo project (hoặc dùng project sẵn có).
2. Bật **Google Sheets API** cho project.
3. Tạo **Service Account** → tạo **key JSON** → tải file về máy, ví dụ lưu tại
   `D:\turtle-wealth-marketing-phase0\secrets\sheets-sa.json` (KHÔNG commit).
4. Mở Google Sheet của bạn → bấm Share → mời **email của service account**
   (dạng `...@....iam.gserviceaccount.com`) với quyền **Editor**.
5. Lấy **spreadsheet_id** từ URL:
   `https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit`

## 2. Khai báo biến môi trường (không hard-code trong repo)
Trên Windows PowerShell (đặt cho phiên hiện tại):
```powershell
$env:TWMKT_SHEET_ID   = "<SPREADSHEET_ID>"
$env:TWMKT_SHEETS_CREDS = "D:\turtle-wealth-marketing-phase0\secrets\sheets-sa.json"
```
`config/settings.yaml` đã tham chiếu 2 biến này qua `${...}` nên không cần sửa code.
Thêm `secrets/` vào `.gitignore`.

## 3. Cấu trúc worksheet (tự tạo nếu chưa có)
Adapter tự tạo 2 tab với hàng tiêu đề:
- `ResearchReview` — cổng 1 (duyệt nghiên cứu)
- `ContentReview` — cổng 2 (duyệt nội dung)

Cột: `timestamp | gate | label | payload | Decision | Notes`

Nên đặt **Data Validation** cho cột `Decision` (dropdown):
`PENDING, APPROVE, REJECT, REVISE` để người duyệt chỉ việc chọn.

## 4. Cách hoạt động
- Pipeline ghi 1 dòng `PENDING` cho mỗi mục chờ duyệt.
- Người duyệt đổi `Decision` thành APPROVE/REJECT/REVISE (có thể ghi lý do ở Notes).
- Pipeline poll mỗi `poll_interval_s` giây; hết `timeout_s` thì áp `on_timeout`
  (mặc định reject cho an toàn).

## 5. Bật trong cấu hình
Trong `config/settings.yaml`:
```yaml
gates:
  research: { type: "sheets" }
  content:  { type: "sheets" }
```
Cài thư viện: `pip install gspread google-auth`.

## Lưu ý MVP
- Poll đồng bộ đơn giản, hợp cho 1 tiến trình/1 người ghi. Khi mở rộng nhiều
  luồng, chuyển sang webhook/Apps Script trigger (không đổi giao diện gate).
- Không để file JSON service account lọt vào git.
