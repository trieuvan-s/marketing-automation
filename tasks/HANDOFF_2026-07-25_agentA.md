# BÀN GIAO — phiên 2026-07-25 (P2 store-as-truth, agent-A)

> Đọc file này TRƯỚC khi làm gì tiếp trên nhánh `feature/store-as-truth`.
> Đây là việc **P2 store-as-truth** (SQLite Document Store làm nguồn sự
> thật, Sheet thành VIEW thuần) — KHÔNG liên quan `tasks/ACTIVE_TASK.md`
> (đó là luồng video/aigen restructuring, người khác, treo riêng — đừng
> đụng). Cũng KHÔNG liên quan `tasks/HANDOFF_2026-07-24.md` (agent-B,
> infographic-frame render — đã merge vào `develop`, xong).

## VÌ SAO DỪNG Ở ĐÂY

Gói Plus của người vận hành hết tài nguyên usage giữa chừng Bước 5.3. KHÔNG
phải do lỗi kỹ thuật chặn — việc đang chạy đúng hướng, có bug thật mới phát
hiện cần Lead quyết (xem mục "CHẶN THẬT — CẦN LEAD QUYẾT" bên dưới). Agent
tiếp nhận đóng vai trò **agent-A** y hệt, tiếp tục ĐÚNG chỗ dừng.

## TÌNH TRẠNG NGAY LÚC DỪNG

- **Branch**: `feature/store-as-truth`. **CHƯA push lên origin** (không có
  `origin/feature/store-as-truth`). `develop` (origin, đã push) đang ở
  `801a6ef` — nhánh này hơn `develop` đúng 1 commit local: `502a7f9`.
- **⚠️ WORKING TREE CHƯA COMMIT** — 2 file, xem `git status --short`:
  `store/sync_service.py`, `store/test_sync_service.py`. Đây là 1 fix thật
  (bootstrap Execute=RUN khi Gate1 vừa APPROVE — xem mục "Fix mới nhất, chưa
  commit" bên dưới) + test đi kèm. **Việc ĐẦU TIÊN của phiên sau: tự
  `git add`/`commit`** 2 file này trước khi làm gì khác — đừng mất công sức.
- **Test**: `python -m pytest` **593/593 xanh** (bao gồm cả 2 file chưa
  commit ở trên).
- **⚠️ SHEET THẬT (production spreadsheet) ĐÃ BỊ THAY ĐỔI THẬT trong phiên
  này** — không phải test, là spreadsheet Lead dùng thật. Xem mục "TRẠNG
  THÁI SHEET THẬT" bên dưới — quan trọng, đọc kỹ trước khi thao tác tiếp.

## BỐI CẢNH NHIỆM VỤ (tóm tắt — đọc `CLAUDE.md` trước để hiểu quy tắc chung)

Nhiệm vụ gốc từ Lead (nguyên văn dài, tóm tắt): dựng **TopicKey Document
Store** (`store/`) thành **NGUỒN SỰ THẬT**, Sheet thành **VIEW thuần** (đọc
để xem/thao tác, không phải database). 4 nguyên tắc không được phá:
1. Pipeline (`produce_from_sheet.py`) CHỈ đọc/ghi STORE, TUYỆT ĐỐI không
   đọc/ghi Sheet trực tiếp (trừ 2 ngoại lệ Lead cho phép ở lại tạm:
   `read_sources()`/`read_prompt_versions()` — người quản lý trực tiếp trên
   Sheet, không phải trạng thái nội dung).
2. `store/sync_service.py` là adapter DUY NHẤT nối 2 chiều store↔Sheet.
3. Pipeline và Sheet KHÔNG BIẾT NHAU (đã kiểm bằng test thật: tắt hẳn
   credential Sheet, pipeline vẫn chạy hết logic store, chỉ chết đúng ở 2
   điểm đọc config còn lại).
4. Store APPEND-ONLY → Sheet xoá nhầm → chạy lại sync → phục hồi từ store
   (đã kiểm bằng test thật, xem `test_sync_all_full_recovery_after_accidental_deletion`).

**Ranh giới file** (đã giữ nguyên suốt phiên): CHỈ `store/`, sync service,
`sheets_board.py`, `produce_from_sheet.py`. KHÔNG đụng `ai_full.py`,
`brand_stamp.py`, aigen-pipeline (agent-B). KHÔNG đụng `validators/`
(agent-C). KHÔNG đụng `content-rules/` (READ-ONLY). KHÔNG auto-commit.

## ĐÃ LÀM — theo Bước (tất cả đã test, phần lớn đã commit)

### Bước 1 — Sơ đồ tầng + liệt kê chỗ pipeline gọi Sheet trực tiếp — XONG (báo cáo, không code)

### Bước 2 — Pipeline chỉ đọc/ghi store — XONG, ĐÃ COMMIT + MERGE `develop`
- `store/document_store.py` + `store/schema.sql`: SQLite append-only, khoá
  `(topic_key, layer, content_type, version)`. Layer: `raw`, `brief`,
  `content_output`, `infographic`, `video`, **`gate_status`** (mới, topic-
  level: gate1/execute/output_type/notes), **`content_status`** (mới,
  content_type-level: gate2/gate3/notes/social_link/posting_status/
  asset_url/asset_local_path/asset_drive_file_id/asset_content_hash),
  **`log`** (mới, nhật ký toàn cục, topic_key surrogate `_system`).
- **`topic_key` guard 2 tầng**: application code (`write_document()` raise
  `ValueError` nếu rỗng) + **CHECK constraint DB** (`length(topic_key) > 0`,
  thêm ở Bước 3 phiên trước — schema `NOT NULL` một mình KHÔNG chặn chuỗi
  rỗng, đã xác nhận thực nghiệm).
- `store/pipeline_store.py`: lớp nghiệp vụ (`write_raw`, `read_raw`,
  `write_gate_status`/`read_gate_status` merge-on-write, `list_approved_topics`,
  `write_content_output`/`read_content_output`, `write_content_status`/
  `read_content_status`, `existing_content_keys`, `mark_execute`/
  `mark_execute_done`, `write_log`/`read_log_history`).
- `scripts/produce_from_sheet.py::run()`/`run_draft()`/`run_ingest()`: đọc/
  ghi store thay Sheet. `_open_board()` **lazy-load** (chỉ khởi tạo khi
  `read_sources()`/`read_prompt_versions()` thật sự gọi — KHÔNG đầu hàm) —
  đã kiểm bằng test credential-off thật.
- **Móc nối chéo đã biết, CHƯA giải quyết dứt điểm**: `scripts/
  review_to_sheet.py` (crawl → CONTEXT mới) NGOÀI ranh giới file, vẫn ghi
  THẲNG Sheet, KHÔNG qua store. `sync_service.ingest_context_from_sheet()`
  coi "TopicKey có trên Sheet, store chưa có raw" là CẦU NỐI TẠM, tự nạp —
  giữ Nguyên tắc 1 đúng cho pipeline dù `review_to_sheet.py` chưa migrate.
  **Nếu có phiên riêng migrate `review_to_sheet.py` sang ghi store thẳng,
  cầu nối này có thể bỏ (không bắt buộc bỏ, vẫn vô hại nếu giữ).**

### Bước 3 — Sync service 2 chiều — CORE XONG (commit `502a7f9`) + 1 fix mới CHƯA commit
`store/sync_service.py` (module mới):
- `render_context_to_sheet()` / `render_content_to_sheet()`: dựng lại TOÀN
  BỘ tab từ store (clear + ghi lại), **đọc THẲNG từ `gate_status`/
  `content_status`** (KHÔNG đọc lại Sheet hiện tại trước khi xoá — tự bắt 1
  bug thiết kế thật lúc viết test, xem comment trong code). Đây CHÍNH LÀ
  lệnh phục hồi khi xoá nhầm (Bước 5.4 sẽ kiểm).
- `ingest_context_from_sheet()` / `ingest_content_from_sheet()`: đọc thao
  tác người trên Sheet (Duyệt Context/Content/Public, Notes, Output Type,
  Social Link, Posting Status), ghi version mới vào store. Cũng là nơi CẦU
  NỐI TẠM (topic mới từ review_to_sheet.py, xem trên).
- **Cột máy-sở-hữu vs người-sở-hữu tách bạch** (`_CONTEXT_MACHINE_COLS` /
  `_CONTEXT_USER_COLS` / `_CONTENT_MACHINE_COLS` / `_CONTENT_USER_COLS`).
  **2 khe hẹp đã biết** cho cột Execute (không phải 2 chiều đầy đủ, chỉ đọc
  ĐÚNG 2 transition):
  1. NEEDS_HUMAN → RUN (người tự đổi để thử lại, đã tài liệu hoá từ trước).
  2. **rỗng → RUN khi Gate1 vừa APPROVE** — đây là **fix CHƯA COMMIT** (xem
     mục riêng bên dưới), thay `SheetsBoard.sync_approve_execute_flags()` cũ.
- **Bước 3.4 (upload Google Drive) — BỊ CHẶN, CHƯA LÀM**: Drive API CHƯA
  bật trên GCP project `248905047549` (service account `secrets/sa.json`).
  Đã xác nhận bằng lệnh gọi thật → `403 accessNotConfigured`. Cần Lead/người
  có quyền IAM bấm Enable tại:
  `https://console.developers.google.com/apis/api/drive.googleapis.com/overview?project=248905047549`
  Sau khi bật, kiểm lại bằng đúng lệnh thử (xem lịch sử chat nếu cần script
  mẫu — dùng `google.oauth2.service_account.Credentials` + scope
  `drive.file`, gọi thẳng REST API qua `httpx`, KHÔNG cần thêm
  `google-api-python-client`).
- Test: `store/test_sync_service.py`, hiện **27 test** (render/ingest/
  idempotent-recovery/cầu-nối-topic-mới/ngoại-lệ-Execute/invariant-Gate3/
  Output-Type/bootstrap-Execute).

### Bước 4 — Cột "Output Type" — XONG, ĐÃ COMMIT + MERGE `develop`
- `sheets_board.py`: thêm `OUTPUT_TYPE_COL = "Output Type"` +
  `OUTPUT_TYPE_VALUES = ("Article", "Long-Article", "Infographic", "Video", "AUTO")`
  vào `CONTEXT_HEADER`, đặt **SAU "Duyệt Context"** (đặc tả gốc Lead ghi
  "sau Duyệt Content" — xác định là nhầm cột, đã sửa + **Lead đã XÁC NHẬN
  ĐÚNG** vị trí mới này).
- `produce_from_sheet.py::run()`: gate sinh nội dung theo `output_type`
  người chọn, **AND** với quyết định router (2 lớp gate độc lập, Notes phân
  biệt rõ lý do SKIPPED). **AUTO = không thêm giới hạn** (để nguyên quyết
  định router) — **Lead đã XÁC NHẬN**: năng lực "Composer tự đọc facts[]
  chọn loại" mà đặc tả gốc nói "đang tắt, bật lại" **KHÔNG TỒN TẠI trong
  code** (đã grep toàn repo xác nhận) — đây là lỗ hổng đặc tả của Lead, đã
  cài đặt hợp lý thay vì cố dựng thứ tưởng tượng. "Long-Article" là giá trị
  hợp lệ nhưng CHƯA có producer — chọn nó không sinh gì, không crash (chấp
  nhận, producer là việc TƯƠNG LAI, Lead đã xác nhận không lan man).
- Test: 4 test Output Type + 1 test cột cũ cập nhật theo header mới.

### Bước 5.1 — DỪNG báo Lead trước khi xoá — ĐÃ QUA (Lead xác nhận 3 câu)
Lead đã trả lời cả 3 câu treo ở 5.1: (1) cho xoá thật NHƯNG phải commit
Bước 3+4 trước (đã làm), (2) Output Type OK như trên, (3) phân vai rõ: Bước
5.2/5.3 do agent-A (tôi) làm, KHÔNG cần chờ agent-B; kết quả ảnh 5.3 sẽ là
bằng chứng cho agent-B quyết dọn dead code ProductionSpec (việc của
agent-B, KHÔNG phải việc của agent-A).

### Bước 5.2 — Reset store + Sheet + crawl mới — XONG THẬT (side effect thật trên Sheet)
Xem mục "TRẠNG THÁI SHEET THẬT" bên dưới cho chi tiết đầy đủ.

### Bước 5.3 — Chạy 1 bài thật end-to-end qua render — CHẠY ĐẾN Content Factory THÀNH CÔNG, CHẶN Ở RENDER PNG
Xem mục "CHẶN THẬT — CẦN LEAD QUYẾT" bên dưới.

### Bước 5.4 (test phục hồi) — CHƯA LÀM (chờ 5.3 xong trước)

## ⚠️ TRẠNG THÁI SHEET THẬT (production spreadsheet, ID trong `config/settings.yaml: sheets.spreadsheet_id`)

**Đã có backup TRƯỚC khi xoá** — 2 tab mới trên chính spreadsheet đó:
`CONTEXT_backup_p2-truoc-buoc52-20260725`, `CONTENT_backup_p2-truoc-buoc52-20260725`
(chứa TOÀN BỘ 22 dòng CONTEXT + CONTENT thật trước khi reset, gồm cả 2 bài
Techcombank/PNJ đã điều tra ở phiên trước — GIỮ NGUYÊN, đừng xoá tab backup
này trừ khi Lead xác nhận không cần nữa).

**Sau đó đã làm THẬT** (không phải test, không phải mô phỏng):
1. Xoá sạch store cục bộ (`store/document_store.db`), khởi tạo lại từ
   schema mới (có `gate_status`/`content_status`/`log` + CHECK constraint).
2. Xoá sạch dữ liệu CONTEXT/CONTENT trên Sheet thật, dựng lại header mới
   (CONTEXT có cột "Output Type") qua `sync_service.render_*_to_sheet()`
   trên store rỗng — 0 dòng dữ liệu.
3. Chạy `python scripts/review_to_sheet.py --limit 2` THẬT — **7 dòng
   CONTEXT thật mới** đã ghi vào Sheet (crawl RSS/HTML thật từ CafeF/
   CafeBiz/Vietstock, KHÔNG phải mock — Hook Agent dùng fallback tất định vì
   thiếu `ANTHROPIC_API_KEY`, nhưng title/source/tickers là dữ liệu thật).
4. Duyệt Gate1 (Duyệt Context = APPROVE) cho 1 dòng thật: **"Chỉ trong nửa
   năm, công ty mẹ Google thu hơn 6 triệu tỷ đồng, bằng 90% GDP Việt Nam"**
   (nguồn cafef.vn, TopicKey `c3a6a0ca39a13f24`).
5. Chạy `sync_all()` → topic này đã nạp vào store (raw + gate_status,
   execute bootstrap thành RUN).
6. Chạy `python scripts/produce_from_sheet.py --limit 1` THẬT → **3 sản
   phẩm sinh ra thành công** (article/infographic/video), dùng LLM THẬT qua
   backend `claude_code` (gọi `claude -p` CLI cục bộ, KHÔNG cần
   `ANTHROPIC_API_KEY` riêng) — facts trích xuất chính xác, khớp evidence
   (29 fact số liệu thật: 6 triệu tỷ đồng, 90% GDP, +23%, Google Cloud
   +82%...). **`"source": "cafef.vn"` — KHÔNG RỖNG** (xác nhận Techcombank/
   PNJ rỗng trước đây là dữ liệu soạn tay, không phải lỗi hệ thống — đúng dự
   đoán của Lead).
7. Duyệt Gate2 (Duyệt Content = APPROVE) cho dòng infographic (dòng 3 trên
   CONTENT tab).
8. Chạy `render_production_assets.py --limit 1` → **THẤT BẠI**, xem mục
   "CHẶN THẬT" bên dưới.

**Trạng thái Sheet HIỆN TẠI**: CONTEXT có 7 dòng thật (1 dòng đã
APPROVE+RUN+DONE-content, 6 dòng còn PENDING). CONTENT có 3 dòng thật cho
topic đã duyệt (article=DONE/PENDING-gate2, infographic=DONE/**APPROVE**-
gate2 nhưng AssetPath vẫn RỖNG vì render thất bại, video=DONE/PENDING-gate2).
KHÔNG có gì cần dọn gấp — đây là dữ liệu thật hợp lệ, cứ để nguyên cho
phiên sau tiếp tục từ đây (KHÔNG cần lặp lại bước 5.2/crawl).

## 🔴 CHẶN THẬT — CẦN LEAD QUYẾT (đây là việc ĐẦU TIÊN nên làm ở phiên sau, sau khi commit)

`render_production_assets.py --limit 1` báo:
```
[NEEDS_HUMAN] 'Chỉ trong nửa năm, công ty mẹ Google thu hơn 6 triệu tỷ đồng':
Output không phải JSON hợp lệ (đã bị sửa hỏng ở Gate 2?)
```

**Nguyên nhân đã xác định CHÍNH XÁC** (không phải đoán): `render_production_
assets.py::render_one()` đọc `item["output"]` (từ ô Sheet CONTENT.Output,
qua `board.read_content_for_render()`) rồi `json.loads()` THẲNG. Nhưng cột
Output chỉ lưu **bản PREVIEW cắt ở 1500 ký tự** (`_OUTPUT_PREVIEW` trong
`produce_from_sheet.py`, kèm hậu tố `"…(xem file.json)"`) — infographic
JSON thật của bài này dài **1565 ký tự**, vượt ngưỡng, bị cắt giữa chừng →
không còn là JSON hợp lệ → `json.loads()` raise → NEEDS_HUMAN.

**Đây là hành vi CŨ, KHÔNG phải P2 tạo ra** — logic cắt 1500 ký tự tồn tại
từ trước (tôi chỉ mang nguyên `_OUTPUT_PREVIEW` sang `_write_content()`
trong store). Bug này CHƯA từng lộ vì nội dung test/mock trước giờ luôn
ngắn hơn 1500 ký tự — nội dung THẬT (facts phong phú, như bài này) mới đủ
dài để trúng ngưỡng. Đã xác nhận độ dài thật bằng lệnh đọc trực tiếp store
(`ps.read_content_output(...)['output']` → `len() == 1565`).

**File JSON ĐẦY ĐỦ (không bị cắt) đã có sẵn cục bộ**, không mất dữ liệu:
`../marketing-database/marketing-automation/output/2026-07-25/chỉ-trong-nửa-năm-công-ty-mẹ-google-thu--infographic.json`
— đã đọc, `"source": "cafef.vn"` xác nhận đúng, facts đầy đủ. Vấn đề CHỈ ở
chỗ `render_production_assets.py` đọc SHEET CELL (đã cắt) thay vì file này.

**Ai sửa, sửa thế nào — CẦN LEAD QUYẾT, KHÔNG tự sửa**: root cause chạm 2
vùng ranh giới khác nhau:
- `_OUTPUT_PREVIEW = 1500` trong `produce_from_sheet.py` (vùng agent-A).
- Đường đọc của `render_production_assets.py::render_one()` (vùng agent-B
  — "Không đụng đường render infographic" đã được Lead nhắc lại rõ ràng ở
  phiên trước cho agent-A).

Hướng sửa hợp lý nhất (nhận định, KHÔNG phải quyết định): `render_production_
assets.py` nên đọc file `.json` đầy đủ cục bộ (đường dẫn có thể suy ra từ
`slug(context)` + ngày, giống cách `produce_from_sheet.py` tự ghi) thay vì
dựa vào ô Sheet đã cắt cho mục đích hiển thị. Nhưng đây là thay đổi trong
file agent-B sở hữu — **DỪNG, báo Lead trước khi bất kỳ ai sửa.**

**Do 5.3 chưa hoàn tất, CHƯA có ảnh để kiểm 3 tiêu chí Lead đặt ra** ("Nguồn:
CafeF" không rỗng, không cắt cụt khung, số khớp facts).

## Thay đổi code (uncommitted — 2 file, xem đầu file)

| File | Tóm tắt |
|---|---|
| `store/sync_service.py` | Fix: `ingest_context_from_sheet()` bootstrap Execute="RUN" khi Gate1 vừa chuyển APPROVE và Execute đang rỗng (thay `SheetsBoard.sync_approve_execute_flags()` cũ chưa có ai migrate) — nếu KHÔNG có fix này, `list_approved_topics()` sẽ không bao giờ thấy topic vừa duyệt (execute mãi rỗng), pipeline không chạy được gì. **Fix này BẮT BUỘC phải có, đã kiểm bằng chính Bước 5.3 thật ở trên.** |
| `store/test_sync_service.py` | 3 test mới cho fix trên (bootstrap cho topic đã có trong store, bootstrap cho topic mới bridge vào, KHÔNG bootstrap khi Gate1 còn PENDING) |

## Fix mới nhất, chưa commit — VÌ SAO CẦN, đừng bỏ qua khi review

Trước khi có fix này: `ingest_context_from_sheet()` chỉ đọc 1 ngoại lệ
(NEEDS_HUMAN→RUN). Khi thử Bước 5.3 THẬT, duyệt Gate1 xong chạy `sync_all()`
thì Execute vẫn rỗng trong store → `list_approved_topics()` lọc theo
`execute in (RUN, FAILED)` → KHÔNG thấy gì → `produce_from_sheet.py` báo
"Không có topic nào" dù đã duyệt. Phát hiện qua chạy thật, không phải đọc
code suy luận — đã sửa + test + xác nhận chạy thật thành công (mục 5.3 ở
trên chính là bằng chứng fix đúng).

## Nguyên tắc đã học trong phiên (đừng lặp lại)

- **`render()` (store→Sheet) phải đọc TỪ STORE, không đọc lại Sheet hiện
  tại** — tưởng "giữ giá trị người đã có" bằng cách đọc Sheet trước khi xoá
  nghe hợp lý nhưng SAI nếu ingest chưa kịp chạy trước đó (xoá Sheet →
  render dựa vào Sheet đã xoá → mất). Bài học tự phát hiện qua chính test
  phục hồi (`test_sync_all_full_recovery_after_accidental_deletion`).
- **`_OUTPUT_PREVIEW` (1500 ký tự) là bẫy ẩn** cho bất kỳ code nào sau này
  đọc lại `CONTENT.Output` để `json.loads()` — chỉ dùng được cho MỤC ĐÍCH
  HIỂN THỊ (người đọc lướt), KHÔNG BAO GIỜ dùng làm nguồn parse lại. File
  `.json` đầy đủ cục bộ mới là nguồn đáng tin.
- **Encoding console Windows (cp1252) crash khi print tiếng Việt** — luôn
  ghi ra file (`open(..., encoding="utf-8")`) khi cần xem output dài có dấu,
  đừng `print()` thẳng ra terminal nếu không set `PYTHONIOENCODING=utf-8`.
- **`sync_approve_execute_flags()` cũ có nhiều hành vi ẩn hơn tưởng** — khi
  thay thế 1 hàm cũ bằng sync service mới, kiểm bằng CHẠY THẬT (không chỉ
  đọc code) mới lộ hết — bootstrap-execute chỉ lộ ra khi chạy Bước 5.3 thật.

## Việc kế tiếp (theo thứ tự đề nghị)

1. **Commit 2 file uncommitted** (`store/sync_service.py`,
   `store/test_sync_service.py`) — fix thật, đã kiểm bằng chạy thật.
2. **Báo Lead bug `_OUTPUT_PREVIEW`/render đọc Sheet cell đã cắt** — chờ
   quyết ai sửa (agent-A hay agent-B) và sửa thế nào, TRƯỚC khi tự ý đụng.
3. Sau khi có hướng sửa + render lại thành công → kiểm 3 tiêu chí ảnh
   ("Nguồn: CafeF", không cắt cụt, số khớp facts) → hoàn tất Bước 5.3.
4. Bước 5.4: xoá vài dòng Sheet CONTEXT thật (đã có 7 dòng để thử) → chạy
   `sync_service.sync_all()` → xác nhận phục hồi đúng, không mất gì.
5. STOP-REPORT cho Lead, kèm bằng chứng 5.3+5.4.
6. Sau 5.4 xanh: merge `feature/store-as-truth` → `develop` (**CHƯA merge
   — Lead dặn chờ agent-B có thể cần rebase lên trạng thái sau 5.3, và cần
   xác nhận rõ ràng trước khi merge, không tự ý**).
7. Bước 3.4 (Drive upload) — làm khi Drive API đã được bật (xem link Enable
   ở trên) — nợ riêng, không chặn 5.4/webapp.
8. Việc lớn tiếp theo (Lead đã nói): sau 5.4 xanh, store chạy thật + qua
   test phục hồi là điều kiện tiên quyết cho **webapp** — Lead sẽ giao
   riêng, CHƯA bắt đầu.

## KHÔNG LÀM (nhắc lại ranh giới)

Không đụng `ai_full.py`/`brand_stamp.py`/aigen-pipeline (agent-B) — kể cả
để sửa bug `_OUTPUT_PREVIEW`, PHẢI có xác nhận Lead trước. Không đụng
`validators/` (agent-C). Không đụng `content-rules/` (READ-ONLY). Không
merge `feature/store-as-truth` vào `develop` khi chưa có xác nhận. Không
push. Không tự sửa nếu ảnh render tiếp tục rỗng "Nguồn:" hay sai số — báo
Lead, đó là tín hiệu cho agent-B (vùng render), không phải cho agent-A tự
vá. Không lặp lại Bước 5.2 (reset+crawl) — dữ liệu hiện tại trên Sheet là
thật và hợp lệ, cứ dùng tiếp.

## DỪNG KHI (kế thừa từ nhiệm vụ gốc, vẫn còn hiệu lực)

1. Trước khi xoá bất kỳ dữ liệu thật nào khác (đã qua cổng 5.1 cho lượt
   reset ĐÃ làm — nhưng bất kỳ thao tác xoá THÊM nào ngoài phạm vi đã báo ở
   file này vẫn cần hỏi lại).
2. Phát hiện móc nối chéo pipeline↔Sheet phức tạp hơn dự kiến.
3. Test phục hồi (5.4) không khôi phục đủ.
4. Việc chạm tới `aigen-pipeline`/repo khác ngoài `marketing-automation`.
