# HANDOFF.md

> **GHI ĐÈ MỖI PHIÊN — KHÔNG TÍCH LUỸ.** File này chỉ phản ánh trạng thái NGAY
> LÚC KẾT THÚC phiên gần nhất — không phải log lịch sử (lịch sử/quyết định đã
> chốt nằm ở `PROJECT_HANDOFF_P5.md`). Phiên mới: đọc xong thì GHI ĐÈ TOÀN BỘ
> file này bằng trạng thái mới, đừng nối thêm vào cuối.

## Task vừa xong
"Sheet UI cleanup" (Phase 0-6) + follow-up 6b/6c/6d + đổi tên/vị trí lệnh hệ
thống — **đang chờ duyệt CUỐI CÙNG**:

- **Phase 0-5**: xác nhận 0 lệch TopicKey↔Output; ngừng `mergeCells` (band
  theo TopicKey thay merge ô, khôi phục 8 dòng CONTENT từng bị merge xoá —
  Timestamp 8 dòng này chỉ chính xác tới NGÀY); công cụ `reset_sheet.py`
  (chưa `--confirm` lên Sheet thật); đổi tên 3 cột Gate (`Duyệt Context`/
  `Duyệt Content`/`Duyệt Public` — **sự cố THẬT xảy ra + tự sửa**: đổi tên cột
  bị `migrate_rows()` coi là "cột mới", xoá rỗng Gate 1 thật 9 dòng, đã khôi
  phục thủ công + thêm default an toàn); ẩn cột máy-sở-hữu (TopicKey/Facts/
  AssetPath, round-trip 0 sai khác); chuyển 2 tab backup sang Sheet vận hành
  riêng (`sheets.archive_spreadsheet_id` trong settings.yaml, đối chiếu
  checksum 100% trước khi xoá tab gốc).
- **Phase 6**: thêm cột `Social Link`/`Posting Status`, hiện lại `AssetPath`
  (bỏ ý định thêm cột "Data URL" trùng vai trò) — đối chiếu 0 sai khác giá trị
  cột cũ + trạng thái ẩn/hiện đúng kỳ vọng sau khi chèn.
- **Phase 6b/6c**: AssetPath giờ là link BẤM ĐƯỢC — vòng 1 dùng `file://`
  **THẤT BẠI THẬT** (test trên Sheet sống: trình duyệt chặn điều hướng HTTPS→
  file://, đã xác nhận bằng ảnh chụp không phải suy đoán); vòng 2 dựng local
  static file server (`src/twmkt/asset_server.py`: `asset_url()`/
  `build_server()`, CHỈ bind `127.0.0.1`) — **click-test THẬT THÀNH CÔNG**
  (người vận hành xác nhận bằng ảnh chụp, SVG mở đúng qua
  `http://127.0.0.1:8899/...`). Thêm Protected Range THẬT cho cột AssetPath
  (chỉ Service Account + Owner ghi được, Google tự thêm Owner vào editors).
  Mọi worksheet/thư mục test tạm đã dọn sạch. Suite 388/388 xanh tại thời
  điểm này.
- **Phase 6d**: wire asset server vào lệnh khởi động hệ thống — TẮT mặc định
  (`storage.asset_server_enabled: false`), bật `true` khi lên VPS để chạy full
  service (crawl + draft + asset server) chỉ bằng 1 lệnh, không cần chạy tay
  `scripts/serve_assets.py` riêng. Rà toàn bộ codebase xác nhận đây là service
  DUY NHẤT thuộc dạng "đã viết sẵn, chỉ chờ bật cờ" — không còn service nào
  khác bị bỏ sót (web app/publisher thật/Telegram 2 chiều đều CHƯA có code,
  không phải gap wiring).
- **Đổi tên + chuyển vị trí lệnh hệ thống (phiên này)**: `scripts/power_on.py`
  → **`system_power_on.py` (THƯ MỤC GỐC dự án)**. Lý do (yêu cầu trực tiếp):
  đây là lệnh KHỞI ĐỘNG HỆ THỐNG (khác các script tiện ích/one-shot khác trong
  `scripts/`), đặt ở gốc để người vào thư mục dự án THẤY NGAY, không phải đào
  vào `scripts/` mới biết. Đã sửa:
  - `REPO_ROOT = Path(__file__).resolve().parent` (trước là `.parents[1]` —
    đúng khi file còn nằm trong `scripts/`, SAI nếu giữ nguyên sau khi chuyển
    ra gốc — đã tính đến khi viết lại file).
  - Mọi docstring/comment/print message bên trong file tự nhắc tên nó (thông
    báo lock conflict, `acquire_lock()` docstring...) — đổi từ `power_on.py`
    sang `system_power_on.py`.
  - **Tên file lock KHÔNG đổi** (`<data_root>/logs/power_on.lock`) — đây là
    artifact runtime nội bộ, độc lập với tên/vị trí script gọi lệnh, cố ý giữ
    nguyên để không phá dữ liệu lock cũ nếu có.
  - `tests/test_pipeline.py`: 6 chỗ `sys.path.insert(0, os.path.join(REPO_ROOT,
    "scripts")); import power_on as po` → `sys.path.insert(0, REPO_ROOT);
    import system_power_on as po`.
  - Cập nhật mọi tham chiếu path/tên file trong: `config/settings.yaml` (2
    khối comment), `docs/MODULE_INDEX.md`, `docs/system_design.html`,
    `PROJECT_HANDOFF_P5.md`, `CLAUDE.md`, `src/twmkt/sheets_board.py` (README
    seed data + 1 comment), `src/twmkt/config.py`, `src/twmkt/agents/writer.py`,
    `scripts/review_to_sheet.py`, `scripts/run_scheduler.py`,
    `scripts/ab_voice.py`, `scripts/ab_voice2.py` — đã grep toàn repo xác nhận
    không còn tham chiếu `scripts/power_on.py`/`import power_on` nào sót lại
    (trừ tên file lock, giữ nguyên có chủ đích).
  - Suite chạy lại xanh SAU khi đổi (xem "Trạng thái cây làm việc" bên dưới —
    cần re-run trước khi báo cáo cuối).

## Lệnh khởi động hệ thống (từ phiên này)
```
python system_power_on.py     # chạy TỪ THƯ MỤC GỐC dự án, không phải scripts/
```

## Header CONTENT hiện tại (đã áp lên Sheet sống)
`Timestamp | Context | Type | Status | Output | Notes | Duyệt Content |
TopicKey(ẩn) | Facts(ẩn) | AssetPath(hiện, HYPERLINK http://127.0.0.1:PORT/...
+ Protected Range chỉ SA/Owner ghi, ĐÃ CLICK-TEST THẬT thành công — cần
`scripts/serve_assets.py` chạy nền TRÊN MÁY RENDER, hoặc `system_power_on.py`
với `storage.asset_server_enabled: true` khi lên VPS) | Social Link |
Duyệt Public | Posting Status`

## Trạng thái cây làm việc
Chưa commit gì (đúng kỷ luật KHÔNG auto-commit). `git status` hiện có:
- `system_power_on.py` — **MỚI ở gốc dự án** (chuyển từ `scripts/power_on.py`,
  file cũ đã xoá).
- `CLAUDE.md`, `docs/HANDOFF.md`, `docs/MODULE_INDEX.md`,
  `docs/system_design.html`, `PROJECT_HANDOFF_P5.md` — cập nhật tham chiếu
  path lệnh hệ thống.
- `config/settings.yaml` — `sheets.archive_spreadsheet_id` (Phase 5),
  `storage.asset_server_port`/`asset_server_enabled` (Phase 6c/6d), cập nhật
  comment path (phiên này).
- `src/twmkt/sheets_board.py`, `src/twmkt/config.py`, `src/twmkt/agents/
  writer.py`, `scripts/review_to_sheet.py`, `scripts/run_scheduler.py`,
  `scripts/ab_voice.py`, `scripts/ab_voice2.py` — cập nhật tham chiếu tên file
  lệnh hệ thống (phiên này, KHÔNG đổi logic).
- `src/twmkt/asset_server.py` — MỚI (Phase 6c).
- `scripts/render_production_assets.py` — Phase 6b/6c: `asset_hyperlink_
  formula()` nhận URL http (không còn file://) + wire `asset_url()`.
- `tests/test_pipeline.py` — test Phase 1-6 + 6b/6c/6d + cập nhật import
  `system_power_on` (phiên này).
- `scripts/reset_sheet.py`, `scripts/toggle_machine_columns.py`,
  `scripts/protect_asset_path.py`, `scripts/serve_assets.py` — MỚI, chưa
  track.
- `src/twmkt/media_factory/spec.py` — từ task ProductionSpec TRƯỚC đó, không
  liên quan, để dở chờ Phase 3 riêng (guardrail alias-theo-kênh).

Sheet sống (chính): đúng 8 tab core, 9 dòng CONTEXT + 9 dòng CONTENT, header
đã đổi tên + 2 cột mới, TopicKey/Facts ẩn, AssetPath hiện + Protected Range +
HYPERLINK đã click-test thật. Sheet vận hành riêng (archive) chỉ còn 3 tab gốc
(banner "chỉ Owner được sửa"), không còn artefact test.

## Việc kế tiếp
- ~~Chạy lại suite sau khi đổi tên/di chuyển~~ — **ĐÃ XONG**: 390/390 xanh.
- ~~Smoke-check chạy được từ thư mục gốc~~ — **ĐÃ XONG**: `python
  system_power_on.py` chạy đúng (banner in ra, lịch crawl BẬT đọc đúng
  config), Ctrl+C/timeout dừng sạch. Lock file thừa do kill cứng đã dọn tay;
  xác nhận Sheet sống KHÔNG bị ghi gì trong lúc smoke-test (vẫn 9+9 dòng, kịp
  dừng trước khi crawl job kịp fetch+ghi xong).
- **Chờ duyệt CUỐI**: toàn bộ Phase 0→6d + đổi tên lệnh hệ thống — cần Lead
  xác nhận trước khi coi "Sheet UI cleanup" hoàn tất.
- Task ProductionSpec (`media_factory/spec.py`) đang PAUSE ở Phase 3 riêng
  (guardrail-2 alias-theo-kênh cấm ticker trong voice_text) — quay lại sau khi
  Sheet UI cleanup xong nếu người điều phối muốn tiếp tục.
