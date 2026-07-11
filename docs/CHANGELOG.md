# CHANGELOG

## [Lớp 5 · Phase 1R.2] — TopicKey: write-once + re-key một lần (NGOẠI LỆ)
### Ngữ cảnh
Lớp 5 (Phase 1) thêm cột `TopicKey` (CONTEXT/CONTENT) làm danh tính bền cho 1
chủ đề, tính bằng `curation.keys.compute_topic_key()` = sha256(URL đã chuẩn
hoá). Bản Phase 1 GỐC (`normalize_url()` v1) **bỏ TOÀN BỘ query-string** khi
chuẩn hoá — rủi ro va chạm THẬT cho site dùng `?id=123` làm định danh bài
(2 bài khác nhau, cùng path, khác `?id=` → RA CÙNG khoá, SAI). Phase 1R sửa
`normalize_url()` v2: chỉ bỏ tham số TRACKING (denylist `utm_*`, `fbclid`...),
GIỮ mọi query khác.

### Đã làm (Phase 1R.2)
- **`curation.keys.assign_topic_key(existing_key, url=...)`** — hàm WRITE-ONCE:
  dòng ĐÃ có khoá → trả nguyên, KHÔNG BAO GIỜ tính lại (dù URL/normalize_url
  đổi sau này). Dòng chưa có khoá → tính từ URL, hoặc gán **surrogate `uuid4`**
  (tiền tố `sur-`) nếu không có URL hợp lệ — **không còn để lại khoá rỗng `""`
  nữa** (khác Phase 1, nơi `""` là trạng thái hợp lệ tạm chờ backfill).
- `SheetsBoard.set_topic_key_values()` — persist khoá MỚI gán xuống CONTEXT
  ngay lập tức (write-once chỉ có hiệu lực SAU khi ghi; `produce_from_sheet.py`
  giờ ghi lại mỗi khi `assign_topic_key()` trả khoá khác khoá cũ).
- `backfill_context_topic_keys()`/`backfill_content_topic_keys()` thêm tham
  số `force: bool = False`.

### NGOẠI LỆ — RE-KEY MỘT LẦN (chỉ vì repo đang ở `develop`, CHƯA lên `main`)
Vì khoá Phase 1 gốc có thể ĐÃ va chạm sai (tính bởi `normalize_url()` v1, bỏ
hết query), chạy **`python scripts/backfill_topic_keys.py --rekey` ĐÚNG 1
LẦN** để ghi đè mọi khoá URL-based bằng `compute_topic_key()` MỚI (v2,
canonical) — bypass write-once CÓ CHỦ ĐÍCH (`force=True`). Surrogate (dòng
không URL) KHÔNG bị đụng. Idempotent (chạy `--rekey` nhiều lần vẫn ra cùng
kết quả vì `compute_topic_key()` tất định) nhưng **CHỈ NÊN DÙNG 1 LẦN LÚC
MIGRATE** — **sau lần này, TUYỆT ĐỐI KHÔNG dùng `--rekey` nữa** trong vận
hành thường ngày; mọi lượt chạy sau đều KHÔNG cờ (write-once mặc định) để
khoá đã gán không bao giờ trôi nữa. Nếu sau này repo lên `main` và cần sửa
lại logic khoá lần nữa, đó sẽ là 1 NGOẠI LỆ MỚI, cần ghi chú riêng tại đây.

## [0.2.0] - Sprint MVP-002 (Config + Sheets + Charter)
### Added
- `config/settings.yaml` + `src/twmkt/config.py`: cấu hình trung tâm (config-first),
  truy cập dotted key, expand `${ENV}` cho bí mật.
- `src/twmkt/approval/sheets_gate.py`: cổng duyệt Google Sheets (implement
  ApprovalGate) — control-plane duyệt nội dung, thay Dashboard sau không đổi lõi.
- `docs/google_sheets_setup.md`: hướng dẫn service account + cấu hình.
- CLAUDE.md hợp nhất: tầm nhìn Information→Knowledge→Content→Media→Distribution,
  MVP flow ánh xạ vào module, 8 nguyên tắc cốt lõi.

### Notes
- Kế thừa ý tưởng tốt từ bản thiết kế ChatGPT (config-first, Sheets-as-UI,
  Signal→Context→Hook, kỷ luật release) trên nền engine twmkt đang chạy.
- Bước "Hook" (góc marketing) sẽ thêm ở agents/ — đang triển khai.

## [0.1.0] - Phase 0
- Scaffold pipeline offline: collect → curate → RAG → research → 2 gate →
  produce (4 định dạng) → publish. 7 test pass, chạy CafeF thật ở $0 token.
