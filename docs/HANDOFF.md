# HANDOFF.md

> **GHI ĐÈ MỖI PHIÊN — KHÔNG TÍCH LUỸ.** File này chỉ phản ánh trạng thái NGAY
> LÚC KẾT THÚC phiên gần nhất — không phải log lịch sử (lịch sử/quyết định đã
> chốt nằm ở `PROJECT_HANDOFF_P5.md`). Phiên mới: đọc xong thì GHI ĐÈ TOÀN BỘ
> file này bằng trạng thái mới, đừng nối thêm vào cuối.

## Task vừa xong
"Sheet UI cleanup" — Phase 0-6/6 + follow-up 6b/6c đã làm xong VÀ đã click-test
THẬT thành công (ảnh chụp màn hình người vận hành xác nhận), **đang chờ duyệt
CUỐI CÙNG để coi cả task hoàn tất**:
- **Phase 0** (xác nhận): `existing_content_missing_keys()` = 0; kiểm mới đối
  chiếu Output.title↔CONTEXT.Context theo TopicKey = 0 lệch.
- **Phase 1** (ngừng mergeCells): `regroup_and_band_content()` — nhóm theo
  TopicKey, tô nền xen kẽ + viền trên đậm thay merge ô. Khôi phục 8 dòng
  CONTENT bị mergeCells cũ xoá Context/Timestamp — **Timestamp 8 dòng này chỉ
  chính xác tới NGÀY, không tới phút**.
- **Phase 2** (công cụ reset, CHƯA `--confirm` lên Sheet nào): `SheetsBoard.
  reset_plan()`/`reset_all()` + `scripts/reset_sheet.py --dry-run|--confirm`.
- **Phase 3** (đổi tên 3 cột Gate): `Duyệt Context`/`Duyệt Content`/
  `Duyệt Public` (`GATE1_COL`/`GATE2_COL`/`GATE3_COL`). **Sự cố THẬT đã xảy ra
  + tự sửa**: `migrate_rows()` từng xoá rỗng Gate 1 thật của 9 dòng do đổi tên
  bị coi là "cột mới" — khôi phục thủ công qua đối chiếu Execute=DONE, thêm
  `GATE1_COL: "PENDING"` vào `_MIGRATE_DEFAULTS` làm lưới an toàn. **Bài học
  này dẫn thẳng tới cách làm Phase 6 bên dưới** (luôn kiểm `migrate_rows()`
  trước khi đổi schema sống).
- **Phase 4** (ẩn cột máy-sở-hữu): `SheetsBoard.set_machine_columns_hidden()`
  — độc lập hoàn toàn với `ensure_tabs()`/`migrate_rows()`. Round-trip thật:
  snapshot → ẩn 4 cột (CONTEXT.TopicKey, CONTENT.TopicKey/Facts/AssetPath) →
  0 sai khác.
- **Phase 5** (chuyển tab backup sang Sheet vận hành riêng): tạo Sheet mới
  (Owner = người vận hành, share Editor cho Service Account — đã xác nhận
  quyền ghi bằng probe thật TRƯỚC khi copy), ID lưu vào `config/settings.yaml`
  → `sheets.archive_spreadsheet_id` **TRƯỚC** khi copy. Thứ tự đã theo đúng
  yêu cầu: COPY 2 tab backup (`CONTEXT_backup_2026-07-12`=18 dòng,
  `CONTENT_backup_2026-07-12`=13 dòng) sang Sheet đích → chèn banner "Thông
  tin dành cho người điều hành sheet — chỉ Owner được sửa." (gặp lỗi encoding
  do `-c` inline lần đầu, đã phát hiện + sửa lại đúng UTF-8) → ĐỐI CHIẾU 100%
  (số dòng khớp, checksum SHA-256 toàn nội dung khớp, spot-check 10 dòng ngẫu
  nhiên khớp cho cả 2 tab) → **chỉ sau khi xanh** mới xoá 2 tab gốc trên Sheet
  chính. Sheet chính hiện còn đúng 8 tab core, 0 tab backup.
- **Phase 6** (thêm cột, điều chỉnh theo yêu cầu bổ sung của Lead):
  - **Data URL bị HUỶ, thay bằng hiện lại AssetPath** — Lead xác nhận AssetPath
    đã đóng đúng vai "link mở thư mục/kho lưu trữ output", thêm Data URL sẽ
    trùng vai trò. `_MACHINE_OWNED_COLS["CONTENT"]` rút "assetpath" (chỉ còn
    TopicKey/Facts ẩn).
  - Thêm 2 cột NGƯỜI điền tay: **"Social Link"** (chen giữa AssetPath và
    Duyệt Public — CỐ Ý đặt SAU AssetPath để KHÔNG làm lệch chỉ số cột của
    TopicKey/Facts đang ẩn, vì `hiddenByUser` gắn theo INDEX không theo TÊN)
    và **"Posting Status"** (dropdown Đã đăng|Lỗi|Đang chờ, sau Duyệt Public).
  - **Trước khi chạm Sheet sống**: đọc lại `_headers_need_setup()`/
    `migrate_rows()` xác nhận THÊM cột mới (không đổi tên cột cũ) an toàn cho
    giá trị (mọi tên cột cũ vẫn khớp `old_low`) — CHỈ rủi ro ở
    `hiddenByUser` gắn theo index nếu chèn TRƯỚC cột đang ẩn, đã tránh bằng
    cách chèn Social Link SAU AssetPath.
  - **Phát hiện + báo cáo lệch trước khi snapshot**: yêu cầu Phase 6 ghi "18
    dòng CONTEXT + 13 dòng CONTENT" — đây thực ra là số dòng của 2 tab BACKUP
    vừa dọn ở Phase 5, KHÔNG phải Sheet sống (Sheet sống luôn là **9+9** suốt
    phiên này). Đã báo rõ, snapshot đúng theo số liệu THẬT (9+9), không âm
    thầm dùng 18/13.
  - Snapshot TOÀN BỘ CONTEXT+CONTENT (giá trị + trạng thái ẩn cột) trước khi
    chèn → chạy `ensure_tabs()` (migrate tự động theo tên cột, CONTEXT không
    đổi nên không migrate, CONTENT có → `migrate_rows()` map đúng theo tên) →
    hiện lại riêng cột AssetPath (1 `updateDimensionProperties` độc lập, vì
    `set_machine_columns_hidden()` không còn đụng tới AssetPath) → **đối
    chiếu lại: 0 sai khác** giá trị mọi cột cũ, số dòng vẫn 9+9, trạng thái ẩn
    đúng kỳ vọng (CONTEXT.TopicKey ẩn; CONTENT.TopicKey/Facts ẩn,
    CONTENT.AssetPath HIỆN).
  - Suite `tests/test_pipeline.py`: cập nhật `test_content_row_shape`,
    `test_content_row_facts_asset_path_gate3_fields`,
    `test_content_rows_for_render_filters_by_type_and_reads_all_columns`
    (Gate3 không còn ở cuối header, sửa từ `row_c[-1]` sang tra theo
    `CONTENT_HEADER.index(GATE3_COL)`),
    `test_set_machine_columns_hidden_*` (3 test, số request 4→3),
    `test_build_format_requests_covers_features_and_is_deterministic`
    (ONE_OF_LIST 5→6, thêm dropdown Posting Status). **379/379 xanh.**
- **Phase 6b** (follow-up: AssetPath bấm được + khoá ghi — 4 yêu cầu của Lead):
  1. **base_path đã config-driven từ trước, KHÔNG cần sửa**: renderer
     (`scripts/render_production_assets.py`) build đường dẫn qua
     `data_path()` (`twmkt/config.py`) → `data_root()` đọc `storage.data_root`
     (settings.yaml) hoặc ENV `DATA_ROOT`, KHÔNG hard-code ổ đĩa/đường dẫn
     tuyệt đối. Đã đọc code xác nhận, không sửa gì (tránh thay đổi thừa).
  2. **HYPERLINK() thật — 2 vòng, vòng 1 THẤT BẠI THẬT, vòng 2 THÀNH CÔNG THẬT
     (đã click-test xác nhận)**:
     - **Vòng 1 (Phase 6b, ĐÃ BỎ)**: `asset_hyperlink_formula(path: Path)` bọc
       `Path.as_uri()` thành `=HYPERLINK("file:///...", "Mở file")`. Test
       THẬT trên Sheet sống: **KHÔNG hoạt động** — hover/click ô không phản
       ứng gì (ảnh chụp: text đen thường, không xanh-gạch-chân). Nguyên nhân
       xác nhận: Google Sheets chạy qua HTTPS, trình duyệt CHẶN điều hướng
       HTTPS → `file://` cục bộ (giới hạn trình duyệt, không phải lỗi công
       thức).
     - **Vòng 2 (Phase 6c, ĐANG DÙNG)**: dựng local static file server —
       `src/twmkt/asset_server.py` (`asset_url()` build `http://127.0.0.1:
       PORT/<relative-path>` có `quote()` an toàn Unicode/khoảng trắng,
       `build_server()` dựng `ThreadingHTTPServer` CHỈ bind `127.0.0.1` —
       KHÔNG BAO GIỜ `0.0.0.0`) + `scripts/serve_assets.py` (CLI chạy nền,
       Ctrl+C dừng, cổng đọc từ `storage.asset_server_port` settings.yaml,
       mặc định 8899). `asset_hyperlink_formula(url: str)` đổi sang nhận URL
       string đã build sẵn (không còn nhận Path/file://) —
       `render_production_assets.py::run()` gọi `asset_url()` rồi bọc
       HYPERLINK. **Test THẬT round-trip đầy đủ**: dựng server nền, render 1
       SVG thật, tự GET qua `urllib.request` xác nhận nội dung khớp 100%
       → ghi HYPERLINK thật vào Sheet vận hành (archive) → **người vận hành
       tự click, XÁC NHẬN MỞ ĐƯỢC** (ảnh chụp: URL bar
       `127.0.0.1:8899/phase6c-test/...`, SVG render đúng "100%"/"Test").
       5 test (2 thuần `asset_url`, 1 round-trip THẬT qua HTTP cổng OS tự
       chọn, 1 xác nhận CHỈ bind localhost, 1 `asset_hyperlink_formula` bọc
       URL). **Vận hành thật cần chạy `python scripts/serve_assets.py` NỀN
       trên máy render trước khi click link trên Sheet** — nếu server không
       chạy, link sẽ báo lỗi kết nối (khác hẳn triệu chứng "im lặng không
       phản ứng" của `file://`, dễ chẩn đoán hơn).
  3. **Protected Range cho AssetPath (CONTENT)**: `SheetsBoard.
     protect_asset_path_column()` (+ `_service_account_email()` đọc DUY NHẤT
     `client_email` từ creds, không đọc/lộ `private_key`) — `addProtectedRange`
     phạm vi CHỈ cột AssetPath (cả cột, không giới hạn hàng), `editors=[SA
     email]`, `warningOnly=False`. **Đã ÁP LÊN SHEET SỐNG THẬT**: Google Sheets
     API tự động thêm CẢ Owner (`trieuvanstock@gmail.com`) vào `editors` khi
     tạo — xác nhận đúng ý "chỉ SA + Owner ghi được". Idempotent xác nhận
     bằng chạy script 2 lần (`scripts/protect_asset_path.py`) — lần 2 phát
     hiện `already_protected` qua mô tả `_ASSET_PATH_PROTECTION_DESC`, không
     tạo trùng. 3 test fixture (tạo mới/idempotent/thiếu cột).
  4. **Giới hạn cục bộ — GHI RÕ TẠI ĐÂY** (Lead yêu cầu): link CHỈ mở được
     trên MÁY đã render asset **VÀ đang chạy `scripts/serve_assets.py`**
     (không phải chỉ cần "cùng máy" như dự tính Phase 6b ban đầu — cần thêm
     server chạy nền, xem điểm 2 vòng 2) — đã biết, chấp nhận. **Khi lên
     VPS**: assets sẽ được serve qua web server/cloud storage THẬT (không
     phải `127.0.0.1`), chỉ cần đổi cách build URL ở `render_production_
     assets.py::run()` (1 điểm gọi `asset_url()`), KHÔNG cần sửa
     `asset_hyperlink_formula()`/cấu trúc cột/Sheet. `data_path()` vẫn đọc
     base_path từ config, không hard-code (xem điểm 1) — điều kiện cần cho
     bước chuyển này đã có sẵn.
  - **ĐÃ CLICK-TEST THẬT THÀNH CÔNG** (người vận hành xác nhận bằng ảnh chụp
    màn hình 2 lượt): lượt 1 (`file://`) — hover/click KHÔNG phản ứng, xác
    nhận giới hạn trình duyệt là CÓ THẬT chứ không phải suy đoán. Lượt 2
    (`http://127.0.0.1:8899/...` sau khi dựng `asset_server.py`) — click mở
    đúng tab mới, SVG hiển thị đúng nội dung đã render. Cả 2 worksheet tạm
    (`PHASE6B_HYPERLINK_TEST`, `PHASE6C_HTTP_LINK_TEST`) trên Sheet archive
    và 2 thư mục SVG test (`output/phase6b-test/`, `output/phase6c-test/`)
    đã dọn sạch sau khi xác nhận — Sheet archive hiện chỉ còn 3 tab gốc
    (`Sheet1`, 2 tab backup Phase 5), không còn artefact test nào.
  - Suite: +11 test so với Phase 6 (2 `asset_hyperlink_formula`,
    1 `_service_account_email`, 3 `protect_asset_path_column`, 5
    `asset_url`/`build_server`, trừ 2 test cũ đã thay ở vòng 1 file://).
    **388/388 xanh.**

## Header CONTENT hiện tại (đã áp lên Sheet sống)
`Timestamp | Context | Type | Status | Output | Notes | Duyệt Content |
TopicKey(ẩn) | Facts(ẩn) | AssetPath(hiện, HYPERLINK http://127.0.0.1:PORT/...
+ Protected Range chỉ SA/Owner ghi, ĐÃ CLICK-TEST THẬT thành công — cần
`scripts/serve_assets.py` chạy nền trên máy render để link hoạt động) |
Social Link | Duyệt Public | Posting Status`

## Trạng thái cây làm việc
Chưa commit gì (đúng kỷ luật KHÔNG auto-commit). `git status` hiện có:
- `CLAUDE.md`, `docs/HANDOFF.md` — cập nhật
- `config/settings.yaml` — thêm `sheets.archive_spreadsheet_id` (Phase 5) + `storage.asset_server_port` (Phase 6c)
- `scripts/dedupe_context.py`, `scripts/produce_from_sheet.py` — đổi tên gọi hàm/cột (Phase 1+3)
- `src/twmkt/curation/keys.py` — cập nhật comment (mergeCells đã bỏ)
- `src/twmkt/sheets_board.py` — core Phase 1 (band) + Phase 2 (reset_plan/reset_all) + Phase 3 (GATE1/2/3_COL) + Phase 4 (set_machine_columns_hidden) + Phase 6 (Social Link/Posting Status, AssetPath rút khỏi _MACHINE_OWNED_COLS) + Phase 6b (protect_asset_path_column/_service_account_email)
- `scripts/render_production_assets.py` — Phase 6b/6c: `asset_hyperlink_formula()` (nay nhận URL http, không còn file://) + wire `asset_url()` vào `run()`
- `src/twmkt/asset_server.py` — MỚI (Phase 6c): `asset_url()`/`build_server()`
- `tests/test_pipeline.py` — test Phase 1-4 + Phase 6 + Phase 6b/6c
- `scripts/reset_sheet.py`, `scripts/toggle_machine_columns.py`, `scripts/protect_asset_path.py`, `scripts/serve_assets.py` — MỚI, chưa track
- `src/twmkt/media_factory/spec.py` — từ task ProductionSpec TRƯỚC đó, không liên quan Sheet UI cleanup, để dở chờ Phase 3 riêng (guardrail alias-theo-kênh)

Sheet sống (chính): đúng 8 tab core (không còn tab backup), 9 dòng CONTEXT + 9
dòng CONTENT. Header đã đổi tên (Duyệt Context/Content/Public), dữ liệu Gate
đã khôi phục đúng, sạch mergeCells, đã band theo TopicKey, TopicKey/Facts ẩn
(CONTEXT+CONTENT), **AssetPath HIỆN + Protected Range thật (chỉ SA/Owner ghi)
đã áp, HYPERLINK http://127.0.0.1:PORT/... đã click-test THẬT thành công**,
2 cột mới Social Link/Posting Status (rỗng, người điền tay). Sheet vận hành
riêng (`archive_spreadsheet_id` trong `settings.yaml`) chứa ĐÚNG 3 tab gốc
(`Sheet1`, 2 tab backup Phase 5, banner "chỉ Owner được sửa") — mọi worksheet
test tạm (Phase 6b/6c) đã dọn sạch. Suite 388/388 xanh.

**LƯU Ý VẬN HÀNH MỚI**: link AssetPath chỉ hoạt động khi `python scripts/
serve_assets.py` đang chạy NỀN trên máy đã render asset (server tự đọc cổng
từ `storage.asset_server_port`, mặc định 8899, CHỈ bind 127.0.0.1). Chưa wire
vào `power_on.py` (giữ tách biệt, không mở rộng phạm vi ngoài yêu cầu) — cần
tự chạy lệnh trên khi muốn mở link từ Sheet.

## Việc kế tiếp
- **Chờ duyệt CUỐI**: toàn bộ 8 mảnh việc Phase 0→6c đã xong VÀ đã có bằng
  chứng thật (không chỉ test xanh) — cần Lead xác nhận trước khi coi "Sheet
  UI cleanup" hoàn tất.
- Task ProductionSpec (`media_factory/spec.py`) đang PAUSE ở Phase 3 riêng
  (guardrail-2 alias-theo-kênh cấm ticker trong voice_text) — quay lại sau khi
  Sheet UI cleanup xong nếu người điều phối muốn tiếp tục.
