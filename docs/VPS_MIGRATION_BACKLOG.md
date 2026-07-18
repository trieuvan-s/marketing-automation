# VPS_MIGRATION_BACKLOG.md — nợ dài hạn trước/khi/sau chuyển VPS

> **NGOẠI LỆ CÓ CHỦ ĐÍCH so với quy ước file khác trong repo.**
> `tasks/ACTIVE_TASK.md` và `docs/HANDOFF.md` đều **GHI ĐÈ MỖI PHIÊN** (chỉ
> phản ánh trạng thái hiện tại, không tích luỹ); `CLAUDE.md` chỉ chứa quy tắc
> chung, không phải backlog. Không file nào trong số đó giữ được nợ dài hạn
> qua nhiều phiên — dễ mất mục việc chưa làm khi phiên sau ghi đè.
>
> File này **CHỈ THÊM, KHÔNG GHI ĐÈ**. Đóng 1 mục: đánh dấu **ĐÃ XONG + ngày**
> ngay tại mục đó, KHÔNG xoá khỏi file (giữ làm lịch sử/tham chiếu).

---

## A. CHẶN — làm ngay khi lên VPS

### A1. WEBHOOK thay scheduler 30 phút
Hiện tại: `system_power_on` khởi chạy scheduler quét Sheet 30'/lần tìm cờ
Execute=RUN. User bấm "Thực Thi" có thể chờ tới 30' mới thấy chạy.

Đích: user duyệt Context=APPROVE + bấm "Thực Thi" → Apps Script bắn HTTP tới
endpoint always-on trên VPS → gọi produce_from_sheet xử lý Context→Content
THEO ĐÚNG TopicKey đó NGAY LẬP TỨC → phản hồi ngược ghi trạng thái
DONE / FAILED / NEEDS_HUMAN.

Lý do hoãn tới giờ: webhook cần endpoint always-on, môi trường local không có.

**CẦN HỎI LEAD TRƯỚC KHI CODE**: state machine Execute
(empty→RUN→DONE/FAILED/NEEDS_HUMAN) đang là cơ chế idempotency chính. Có cần
trạng thái trung gian (đã gọi webhook, chờ phản hồi) để chống double-fire khi
user bấm 2 lần hoặc webhook timeout không?

Khi làm: GỠ scheduler 30' khỏi system_power_on — không để 2 cơ chế song song.

### A2. HỢP NHẤT data_root — mục đích chính của việc lên VPS  [ĐÃ CHỐT]
data_root KHÔNG đồng bộ giữa 2 máy là nguồn nhiều bug thật (dòng trùng,
evidence thiếu khi đổi máy). Bản CHUẨN = PC-A. Lên VPS: copy từ PC-A lên, VPS
là nơi ở VĨNH VIỄN, không đồng bộ ngược, không giữ bản song song.

### A3. Hợp nhất repo thành sibling directory
marketing-automation và **aigen-pipeline** (KHÔNG phải aigen-fva-capital — đã
chết) nằm cạnh nhau. Sau đó mới test được seam THẬT.

### A4. serve_assets.py wire vào power_on
Hiện phải chạy tay mới mở được link AssetPath. Lên VPS: đổi `base_path`
config + cho chạy nền cùng power_on.

### A5. Seam path hardcode  [ĐÃ SỬA ngày 2026-07-19 — đưa vào config, xem BƯỚC 1]
Bằng chứng lỗi trước khi sửa: dry-run in ra `cwd=E:\aigen-fva-capital\aigen`
— repo đã chết, seam sẽ FAIL LÚC CHẠY THẬT. Đã sửa: `media_factory/
aigen_seam.py::run_aigen_pipeline()` giờ nhận `aigen_repo_path=None` mặc
định, resolve qua `twmkt.config.aigen_repo_path()` (ENV `AIGEN_REPO_PATH`
hoặc `media_factory.aigen_repo_path` trong `settings.yaml`, mặc định sibling
`"../aigen-pipeline"`, CÙNG NẾP `data_root()`). Path không tồn tại → raise
`AigenRepoPathNotFoundError` nêu rõ đường dẫn đã thử. Đổi máy (VPS) chỉ cần
đổi 1 dòng config hoặc set ENV, KHÔNG sửa code. Test phủ:
`test_aigen_seam_resolves_aigen_repo_path_from_config_when_path_exists`,
`test_aigen_seam_config_path_missing_raises_clear_error_naming_the_path`,
`test_aigen_seam_changing_config_changes_resolved_cwd_not_hardcoded`
(`tests/test_pipeline.py`).

---

## B. MODULE LỚN — sau khi A xong

### B1. TopicKey Document Store
Đã chốt: làm SAU VPS (2 máy sẽ tạo 2 store phân kỳ).

Đích: Sheet CHỈ LÀ UI/view; mọi dữ liệu (evidence, facts, output mọi format,
trạng thái từng Gate, asset path, lịch sử) nằm trong store neo theo TopicKey;
xóa Sheet rồi render lại từ store được.

⚠️ **HIỆN TRẠNG**: CHƯA CÓ store nào. Facts/Output/Gate status CHỈ tồn tại trên
Sheet — Sheet ĐANG LÀ database. TUYỆT ĐỐI KHÔNG xóa/reset Sheet trước khi
store tồn tại và đã backfill xong.

### B2. Video Scene Builder thật (CONTENT.Output → ProductionSpec.scenes[])
Hiện scenes[] LUÔN RỖNG; đang dùng fixture tay để chứng minh contract.

### B3. Attribution & Audit (Apps Script onEdit → LastEditedBy/LastEditedAt + tab LOG)
Phụ thuộc A1 (endpoint) và B1 (LOG neo theo TopicKey, không theo dòng).
Điều kiện tiên quyết: revoke token Telegram trước khi xây lớp này.

---

## C. NỢ NHỎ / RỦI RO ĐÃ BIẾT

- **C1.** `scripts/reset_sheet.py` CHƯA từng chạy `--confirm` lên Sheet thật.
- **C2.** Prompt caching cho `content_writer_rules.md` — nhúng `extra_system`
  MỖI lần gọi LLM; chưa bật caching = đốt tiền thật.
- **C3.** ElevenLabs chưa wire (thiếu API key + voiceID).
- **C4.** alias-guardrail chỉ chặn mã trong `VALID_TICKERS`. Viết tắt KHÔNG
  phải mã chứng khoán (ETF, GDP, FDI) lọt qua → TTS đọc sai. FVB đã tắt khỏi
  vòng render nên không còn gì đỡ. Hướng xử: siết `content_writer_rules.md`
  phía Content Factory, KHÔNG thêm từ điển vào adapter.
- **C5.** Quirk #1/#2 (demo placeholder lòi lên video) KHÔNG test nào bắt
  được — phải soi frame sau mỗi lần render thật.

---

## QUY TẮC VÀNG KHI ĐỘNG VÀO SHEET

`ensure_tabs()`/`migrate_rows()` tự chạy khi mở board, map theo TÊN cột — đổi
tên cột từng XÓA RỖNG dữ liệu thật (mất Gate 1 của 3 dòng). `mergeCells` từng
XÓA THẬT Context/Timestamp, không idempotent.

→ Mọi thao tác đổi cấu trúc Sheet: xác nhận đường gọi `_headers_need_setup()`/
migrate TRƯỚC → snapshot TRƯỚC → làm → đối chiếu SAU.
