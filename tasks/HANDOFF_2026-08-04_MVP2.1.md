# BÀN GIAO — 2026-08-04, MVP 2.1 (agent-A)

> Đọc file này TRƯỚC nếu tiếp nhận phiên làm việc. Bàn giao nối tiếp
> `tasks/HANDOFF_2026-07-29_MVP.md` (MVP v2.0) — không lặp lại nội dung đã
> đúng ở đó, chỉ ghi những gì ĐỔI từ mốc đó tới nay.
>
> Lịch sử quyết định: `PROJECT_HANDOFF_P5.md`. Bản đồ code:
> `docs/MODULE_INDEX.md`. Quy tắc bất biến: `CLAUDE.md`. Nợ dài hạn:
> `docs/VPS_MIGRATION_BACKLOG.md`.

**MỤC LỤC** — §1 trạng thái · §2 việc đã làm từ MVP v2.0 · §3 SỰ CỐ THẬT (đã
sửa) · §3B Sheet UI (Ticker/Source/Type/Status) · §3C Brand-kit mới (ảnh +
video) · §4 hạ tầng đang chạy · §5 git · §6 test · §7 nợ còn lại.

---

## 1. TRẠNG THÁI

Hệ thống vẫn chạy END-TO-END như MVP v2.0 (crawl → Gate 1 → Composer →
Gate 2 → render asset → Gate 3), cộng thêm:

- **Long-Article** là 1 kênh sản xuất thật (dùng chung Producer với Article,
  nạp thêm rules bổ sung `content-rules-deep-v3.0.md`).
- Article/Long-Article upload Drive dạng **Google Docs native** (không phải
  file `.md` thô nữa), idempotent theo content-hash.
- Cột **Type** (tab CONTENT) hiển thị ĐÚNG nhãn dropdown Output Type
  (Article/Long-Article/Infographic/Video) thay vì key thô — có bảng dịch
  2 chiều (`raw_content_type()` / `_display_type()`).
- **AUTO thất bại toàn phần** → gộp 1 dòng lỗi duy nhất, dễ đọc; AUTO thành
  công 1 phần → ẩn dòng lỗi của các tuyến hỏng.
- **Notes** trên Sheet viết bằng ngôn ngữ nghiệp vụ cho biên tập viên (không
  còn thuật ngữ kỹ thuật/tên hàm/mã lý do thô).
- **Execute** (tab CONTEXT) phân biệt rõ `""` (mới crawl, chưa duyệt) và
  `"Waiting"` (đã duyệt Gate 1, đang chờ hàng đợi).
- **Sắp xếp CONTEXT/CONTENT** không còn theo Hot%/alphabet-topic_key nữa —
  theo NGÀY tăng dần rồi `first_created_at()` (thời điểm bản ghi đầu tiên) —
  dữ liệu mới luôn ở DƯỚI CÙNG, đúng thứ tự crawl/xử lý thật.
- **Output** (tab CONTENT) hiện tới 5000 ký tự (trước 1500), và là cột
  HYBRID DUY NHẤT: người có thể sửa tay trước khi duyệt Gate 2, sửa ghi
  ngược vào `content_output` (xem §3 — có sự cố + đã sửa xong).
- Tab CONTENT: Timestamp hiển thị theo **ngày ĐĂNG BÀI GỐC** (giống ý nghĩa
  cột Timestamp bên CONTEXT), băng NỀN xen kẽ giờ đánh dấu **khối NGÀY**
  (đồng bộ màu với CONTEXT — quyết định Lead qua hỏi trực tiếp, đảo lại quy
  ước TopicKey-là-băng-chính cũ 2026-07-23); TopicKey lùi xuống chỉ còn viền
  trên đậm. Thêm cột **"Người thực hiện"** (ngay sau AssetPath) — trống, do
  người tự gõ tay điều phối nhân sự, máy carry-forward không xoá mất.
- Lịch **crawl** đổi sang mốc cố định: 07:30, 10:30, 13:30, 16:30, 19:30,
  22:30, 01:30, 04:30 (8 lần/ngày, cách nhau 3h) — đăng ký qua Windows Task
  Scheduler (§4), không còn phụ thuộc giờ khởi động tiến trình.

---

## 2. VIỆC ĐÃ LÀM TỪ MVP v2.0 (tóm tắt theo thứ tự thời gian)

1. **5 việc Lead giao** (nhánh `feature/long-article-and-vi-notes`, đã merge
   develop): Long-Article, Google Docs upload, nhãn Type, gộp AUTO, Notes
   nghiệp vụ. Kèm sửa TRONG-PHẠM-VI: rules-loading Article từng bị hỏng lặng
   lẽ (0 ký tự nạp) — sửa cùng lượt.
2. **Bug thật #1** — `existing_content_keys()` coi MỌI trạng thái (kể cả
   ERROR/NEEDS_HUMAN) là "đã xong", chặn retry vĩnh viễn sau khi người
   re-approve Gate 1. Sửa: chỉ `status=="DONE"` mới tính là xong.
3. **Bug thật #2 (NGHIÊM TRỌNG)** — `ingest_content_from_sheet()` đọc THẲNG
   cột Type (giờ là nhãn hiển thị, do Việc 3 ở trên) làm khoá tra store →
   luôn tra rỗng → dòng bị bỏ qua ÂM THẦM → **Gate 2 approve của người dùng
   không bao giờ được ghi vào store**, và lượt render sau xoá mất thao tác
   đó (vẽ lại Sheet từ store cũ = "PENDING"). Sửa bằng `raw_content_type()`.
4. **Bug thật #3** — `_TEXT_OUTPUTS["video"]` cho phép upload kịch bản
   `.json` làm AssetPath giả cho video (Lead phát hiện qua ca "Thế Giới Di
   Động"). Xoá hẳn "video" khỏi `_TEXT_OUTPUTS` — AssetPath video CHỈ được
   coi hợp lệ khi có `.mp4` thật render qua aigen-pipeline + upload Drive.
5. **Merge `develop` → `main`, tag `MVP-v2.0`**, push cả 2 nhánh + tag lên
   remote (đã xong trước phiên này).
6. **Task #75** — bỏ sort Hot% (CONTEXT), thay bằng
   `document_store.first_created_at()`.
7. **Task #76** — Output 5000 ký tự + ghi 2 chiều Sheet↔store.
8. **Task #77** — CONTENT: Timestamp = published_at, sort giống CONTEXT,
   băng màu theo ngày (đổi hẳn kênh thị giác, xem trên), cột "Người thực
   hiện" mới.
9. **SỰ CỐ THẬT + đã sửa** — xem §3, KHÔNG được bỏ qua.
10. Restart `queue_worker.py`, đồng bộ Sheet thật (`sync_store_sheet.py`),
    bật lịch crawl qua Task Scheduler (§4).
11. **CONTEXT: cột Ticker/Source tràn ra ô khác** — thêm `wrapStrategy=WRAP`
    (trước đây 2 cột này có độ rộng cố định nhưng KHÔNG wrap, nên nội dung
    dài hơn độ rộng tràn ra ô kế bên, hoặc bị Sheets CẮT nếu ô kế bên có dữ
    liệu — đúng hiện tượng Lead mô tả "Source bị chui ẩn đi"). Xem §3B.
12. **CONTENT: Type/Status bị ghi đè màu Sheet UI** — sự cố THẬT, GỐC chính
    là việc thêm cột "Người thực hiện" ở #8 kích hoạt 1 lượt `format_board()`
    ĐẦY ĐỦ (dò header đổi), lượt đó XOÁ SẠCH mọi conditional-format rule +
    validation trên CONTEXT/CONTENT rồi CHỈ dựng lại đúng phần code tự quản
    — cấu hình màu Lead tự thêm tay cho Type/Status (validation/chip hoặc
    conditional formatting) bị xoá theo, không có gì dựng lại. Đã sửa GỐC
    (không chỉ vá triệu chứng) — xem §3B.
13. **Brand-kit/logo mới thay bản cũ nhoè màu** — cấu hình `config/brand.yaml`
    (`active_asset`/`assets`), wire vào `brand_stamp.py` (tuyến ai_full đang
    sản xuất thật), RE-RENDER 9 infographic của phiên 3/8 (cache-first, $0
    trừ 1 ca cache miss — xem §3C), VÀ sửa asset video bên `aigen-pipeline`
    (repo riêng, theo yêu cầu Lead). Xem §3C.

---

## 3. SỰ CỐ THẬT (2026-08-04) — Output write-back ghi đè 17 bản ghi thật, ĐÃ SỬA

**Xảy ra thế nào**: Task #76 cho phép người sửa tay ô Output rồi ghi ngược
vào `content_output`. Điều kiện ghi ban đầu chỉ so sánh độ dài
(`len(store_output) <= _OUTPUT_PREVIEW`) để quyết có "coi là đã sửa" hay
không. Lượt `sync_all()` ĐẦU TIÊN sau khi nâng ngưỡng 1500→5000: Sheet còn
giữ NGUYÊN bản CẮT Ở NGƯỠNG CŨ (1500) từ trước khi deploy. `ingest` chạy
TRƯỚC `render` (đúng thiết kế `sync_all()`) nên đọc phải bản cắt cũ đó, so
với store đủ dài (2000-5000 ký tự) → luôn "khác nhau" giả → **ghi ĐÈ
`content_output` THẬT bằng bản cắt 1550 ký tự + hậu tố giải thích**, cho
17 bản ghi (13 chủ đề, cả article/infographic/video).

**Phát hiện**: kiểm tra ngay sau lượt sync đầu tiên (query SQL trực tiếp
tìm chuỗi hậu tố cắt trong bản mới nhất) — phát hiện trong vòng vài phút,
KHÔNG để lan sang sản xuất tiếp (Gate 2 approve/render asset chưa kịp chạy
trên các dòng này).

**Phục hồi**: `document_store` append-only/versioned → bản ĐÚNG (version
ngay trước bản hỏng) vẫn còn nguyên trong DB. Đã ghi 1 version MỚI cho cả
17 cặp (topic_key, content_type), khôi phục ĐÚNG payload cũ (không chỉ
`output`, cả `status`/`notes`/`facts`/`timestamp`). Xác nhận lại bằng SQL:
0 bản ghi còn mang hậu tố cắt ở version mới nhất.

**Sửa gốc** (`store/sync_service.py`): thêm hằng số `_TRUNCATION_SUFFIX`
dùng CHUNG giữa `_preview_output()` (ghi) và `ingest_content_from_sheet()`
(đọc, kiểm tra) — cell Sheet có ĐUÔI trùng hậu tố này thì TUYỆT ĐỐI không
coi là người sửa tay, bất kể so khớp độ dài thế nào (loại bỏ khả năng ảnh
sót từ BẤT KỲ ngưỡng cắt nào trước đó, không riêng lần đổi 1500→5000 này —
đây là 1 quả bom hẹn giờ chung cho MỌI lần đổi `_OUTPUT_PREVIEW` sau này
nếu không sửa gốc).

**Test hồi quy**: `test_ingest_content_from_sheet_ignores_stale_truncated_
cell_as_edit` (store/test_sync_service.py) — dựng lại chính xác kịch bản
sự cố, khoá lại vĩnh viễn.

**Bài học cho lần sau**: BẤT KỲ thay đổi nào làm ngưỡng hiển thị/cắt đổi
(hoặc bất kỳ cột nào chuyển từ machine-only sang hybrid 2 chiều) PHẢI tự
hỏi "Sheet đang giữ ảnh của ngưỡng/quy tắc CŨ nào, và ingest sẽ đọc phải nó
trước khi render kịp làm mới không?" — kiểm tra ngay sau lượt sync đầu
tiên bằng SQL trực tiếp, đừng chỉ tin `n == 0`/`n > 0` ở log.

---

## 3B. SHEET UI — Ticker/Source tràn, Type/Status mất màu (ĐÃ SỬA)

**Ticker/Source tràn ô** (`src/twmkt/sheets_board.py::_WRAP_COLS`): thêm
`"tickers"` và `"source"` vào tập cột được áp `wrapStrategy=WRAP`. Trước đây
2 cột này CÓ độ rộng cố định (`_COL_WIDTH`) nhưng KHÔNG wrap — nội dung dài
hơn độ rộng tràn ngang (nếu ô kế trống) hoặc bị Sheets cắt/ẩn (nếu ô kế có
dữ liệu, đúng hiện tượng Lead báo). Đã áp lại lên Sheet thật qua
`board.format_board()`.

**Type/Status mất màu — SỰ CỐ THẬT, ĐÃ SỬA GỐC**: nguyên nhân là 2 cơ chế
trong `_tab_requests()`/`build_format_requests()`:

1. Code CHỦ ĐỘNG gửi `setDataValidation` KHÔNG kèm rule cho cột Type/Status
   mỗi lượt `format_board()` (ý định cũ: "dọn validation sót") — nhưng lệnh
   này XOÁ LUÔN dropdown Chip có màu nếu Lead đã tự cấu hình tay qua Sheet
   UI (giống hệt lý do Gate1/Gate2/Gate3/Output Type đã được CHỪA riêng từ
   trước — Type/Status trước đây KHÔNG có ngoại lệ này). **Đã xoá 2 nhánh
   này** — Type/Status giờ CÙNG quy tắc với 4 cột kia: code không đụng
   validation.
2. `build_format_requests()` XOÁ SẠCH MỌI conditional-format rule đang có
   trên CONTEXT/CONTENT (`deleteConditionalFormatRule` theo index, không
   phân biệt rule nào), rồi CHỈ dựng lại đúng rule code tự quản (Gate1/
   Execute/Score/Hot%/Gate2/Gate3) — rule Lead tự thêm cho cột KHÁC (vd tô
   màu Type/Status) bị xoá vĩnh viễn mỗi khi `ensure_tabs()` phát hiện
   header đổi (chính là điều đã xảy ra ở Việc #8 khi thêm cột "Người thực
   hiện"). **Đã sửa GỐC**: `TabMeta.cond_format_cols` giờ giữ CỘT của TỪNG
   rule hiện có (đọc từ `conditionalFormats[].ranges[0].startColumnIndex`
   qua Sheets API) — chỉ xoá rule nằm ĐÚNG cột code sắp ghi lại, rule ở cột
   khác GIỮ NGUYÊN vĩnh viễn, không phụ thuộc số lần `ensure_tabs()` chạy.

Test hồi quy: `test_build_format_requests_keeps_unmanaged_conditional_format_
rules` (tests/test_pipeline.py).

⚠️ **Màu Type/Status Lead đã cấu hình trước đó (nếu có) đã bị XOÁ THẬT bởi
sự cố ở Việc #8** — code giờ sẽ KHÔNG đụng gì nữa, nhưng phần đã mất thì
KHÔNG phục hồi được từ code (đó là cấu hình UI, không phải dữ liệu trong
store) — Lead cần cấu hình lại 1 LẦN DUY NHẤT trên Sheet thật, sau đó an
toàn vĩnh viễn.

---

## 3C. BRAND-KIT MỚI (2026-08-04, Lead: logo/brand-kit cũ nhoè màu)

**Asset mới** (Lead cung cấp): 4 file `assets/fva-{brand-kit,icon}-{navy,
white}-gold-transparent.png` — "brand-kit" = biểu tượng FVA + dòng chữ
"FINANCE | VALUATION | ANALYSIS" + tagline; "icon" = chỉ biểu tượng. 2 màu
(navy-gold cho nền sáng, white-gold cho nền tối) — code TỰ tô lại phần
trung tính (navy) theo màu chủ đạo theme lúc render (`overlay_brand_full_
canvas`, nhánh `theme in ("bright","light")`), phần vàng đồng giữ nguyên
mọi theme, nên CHỈ CẦN khai 1 đường dẫn (navy-gold) trong config cho phía
ảnh — bản white-gold còn lại là tham chiếu/dùng riêng cho phía video (nền
navy đặc, không qua cơ chế tự tô màu này).

**Config mới** (`config/brand.yaml`, theo Lead chỉ định):
```yaml
active_asset: "brand_kit"     # đổi sang "standard_icon" nếu muốn dùng bản gọn
assets:
  brand_kit:
    path: "assets/fva-brand-kit-navy-gold-transparent.png"
    width_ratio: 0.178
  standard_icon:
    path: "assets/fva-icon-navy-gold-transparent.png"
    width_ratio: 0.148
```
`brand_stamp.py::_resolve_active_logo_asset()` đọc config này;
`overlay_brand_full_canvas()` (tuyến ai_full ĐANG sản xuất thật — `stamp_
brand()` TOP_PAD cũ đã không còn caller nào, chỉ còn trong test) đổi từ neo
theo BỀ CAO (`logo_height_ratio` cũ) sang neo theo BỀ RỘNG (`logo_width_
ratio`) — brand-kit CÓ thêm chữ tagline nên khung ảnh RỘNG hơn icon cũ
(1536×1024 so với 1254×1254 vuông), neo theo cao sẽ làm bề rộng biến thiên
khó kiểm soát.

**Re-render infographic phiên 3/8**: 9/10 bản ghi `infographic` DONE có
`timestamp`/`published_at`=03/08/2026 (1 bản ERROR, không có nội dung để
render, bỏ qua) — render lại qua `render_one()` (cache-first: spec/theme/
ratio KHÔNG đổi nên HẦU HẾT trúng cache ảnh AI gốc, $0, chỉ tính lại lớp
brand-kit tất định), upload lại Drive CÙNG thư mục `03-08-2026/` (khớp tên
file → Drive tự GHI ĐÈ, không tạo bản trùng), ghi `asset_url` mới vào
`content_status` (version mới, lịch sử cũ vẫn còn). **1/9 bị cache MISS**
(chủ đề "giá bán H2SO4 tăng 249%...", topic_key `6736e4397cf1b5bc`) — tốn
1 lượt gọi OpenAI Images API thật (lý do nghi vấn: bản gốc có thể từng qua
1 lượt postflight-retry với `postflight_instruction` khác rỗng, không tái
lập được từ `content_output` lưu lại — KHÔNG phải lỗi, chỉ là chi phí nhỏ
không tránh được cho đúng 1 bài). Kết quả đã kiểm bằng mắt (xem ảnh mẫu
"FPT tái sinh") — brand-kit hiện rõ nét, đúng vị trí góc trên-trái, không
đè nội dung.

**Video (`aigen-pipeline`, repo riêng `D:/trung-temp/aigen-pipeline`)**:
theo yêu cầu Lead, đã sửa asset (KHÔNG phải code logic — hệ thống video
dùng file tĩnh tham chiếu qua `<img src="assets/fva-icon.png">` trong
template HTML, không có cơ chế width_ratio động như phía ảnh). Đã kiểm
NỀN của MỌI khung hình video đều NAVY ĐẬM (`#12224a`/`#13234c`/... hoặc tím
đậm `#1e1b4b` ở frame-liquid-bg-hero) → dùng bản **WHITE-GOLD** (KHÔNG phải
navy-gold) để đủ tương phản — navy trên navy sẽ gần như vô hình:
- 5 khung hiện `.brand-icon`/`.logo-img` NHỎ (50-96px, watermark góc) —
  `templates/{frame-avatar-presenter,frame-liquid-bg-hero,frame-market-
  ticker,frame-news-lower-third,frame-quote-pull}/assets/fva-icon.png` →
  ghi đè bằng `fva-icon-white-gold-transparent.png` (standard_icon).
- `templates/frame-logo-outro/assets/fva-icon.png` (khung ĐÓNG video, ô
  `.logo-wrap` 420×210/460×230, `object-fit:contain` nên không méo/không
  cắt) → ghi đè bằng `fva-brand-kit-white-gold-transparent.png` (brand-kit
  — ưu tiên theo đúng yêu cầu Lead "dùng brand-kit thay logo cũ" ở khung
  thương hiệu chính). File `fva-logo.png` cùng thư mục (trước đây KHÔNG
  được code nào tham chiếu, mồ côi) cũng cập nhật cho nhất quán.
- `npm test` (vitest) trong aigen-pipeline: **244 passed**, không hồi quy.
- ⚠️ **Thay đổi này CHƯA COMMIT trong repo `aigen-pipeline`** (git status
  cho thấy Lead đã tự XOÁ 4 asset cũ + thêm 4 asset mới trước khi tôi vào,
  cộng 7 file tôi vừa ghi đè — tất cả đang ở working tree). Tôi KHÔNG tự ý
  commit ở repo khác ngoài phạm vi được giao — Lead xác nhận rồi tự
  commit, hoặc yêu cầu tôi làm cụ thể ở repo đó.
- KHÔNG kiểm được bằng ảnh chụp thật (khung hình video render qua pipeline
  Node/HTML riêng, ngoài công cụ trình duyệt phiên này chạm tới do khác
  thư mục dự án) — chỉ xác nhận qua lý luận tương phản màu + test suite
  xanh. Đề nghị Lead xem 1 video render thật gần nhất để xác nhận logo rõ
  nét đúng ý trước khi coi là XONG HẲN.

---

## 4. HẠ TẦNG ĐANG CHẠY (tại thời điểm bàn giao)

```
python scripts/queue_worker.py       # ĐANG chạy nền (PID mới sau restart hôm nay)
```

**Windows Task Scheduler** — 9 task mới, TÊN `TWMKT-*` (trước đây KHÔNG có
task nào cho dự án này — toàn bộ lịch trước giờ chỉ chạy khi có người tự mở
tiến trình `system_power_on.py`/`queue_worker.py` tay):

| Task | Lịch | Job |
|---|---|---|
| `TWMKT-Crawl-0130` … `TWMKT-Crawl-2230` (8 task) | Hàng ngày, 07:30/10:30/13:30/16:30/19:30/22:30/01:30/04:30 | `scripts/run_scheduler.py --once` (crawl, section `schedule`) |
| `TWMKT-Draft` | Mỗi 30 phút | `scripts/run_scheduler.py --section schedule_draft --once` |

Cấu hình gốc: `config/settings.yaml` → `schedule.mode: "daily"` +
`schedule.at_times` (8 mốc trên). `schedule_draft` giữ nguyên
`interval_minutes: 30`.

⚠️ **`queue_worker.py` KHÔNG được quản lý bởi Task Scheduler** — vẫn là
tiến trình nền chạy tay (`nohup`/tương đương), PHẢI tự khởi động lại sau khi
máy reboot hoặc sau MỌI thay đổi code ảnh hưởng hành vi của nó (bài học lặp
lại nhiều lần trong các phiên trước — Python không tự nạp lại module).

⚠️ **`system_power_on.py`** (chạy CẢ 2 lịch trong 1 tiến trình, cách cũ)
KHÔNG chạy nữa — đã chuyển hẳn sang Task Scheduler + `run_scheduler.py
--once` (mẫu hình chính script này khuyến nghị cho "đặt-rồi-quên, sống qua
reboot", xem docstring `src/twmkt/schedule.py`). Nếu muốn quay lại cách cũ,
`system_power_on.py` vẫn còn nguyên, không bị xoá.

Đã chạy `scripts/sync_store_sheet.py` (2 chiều) 2 lần trong phiên này —
lần 1 gây sự cố §3 (đã sửa+phục hồi), lần 2 (sau khi sửa code) xác nhận
`ingest CONTENT=0 lần ghi` (không còn false-positive) và render đúng
42 dòng CONTEXT + 24 dòng CONTENT.

---

## 5. GIT

| Nhánh | Trạng thái tại thời điểm viết báo cáo này |
|---|---|
| `develop` | Có các thay đổi CHƯA COMMIT của phiên này (xem `git status`) — sẽ commit + merge vào `main` ngay sau báo cáo này |
| `main` | `e4008e6` (= tag `MVP-v2.0`, đã push trước phiên này) |

Sau khi commit (bước kế tiếp), sẽ merge `develop` → `main`. **KHÔNG tự
push lên remote** — chờ xác nhận riêng.

---

## 6. TEST

`python -m pytest` (đầy đủ, không lọc path, marketing-automation) —
**776 passed**, 0 fail, 43 warning (Pillow deprecation, không liên quan
code này).

`npm test` (aigen-pipeline, repo riêng) — **244 passed**, 0 fail.

---

## 7. NỢ CÒN LẠI / RỦI RO ĐÃ BIẾT

- **TOCTOU 2 máy ghi đồng thời** — vẫn CỐ Ý CHƯA xử lý (chờ VPS, xem
  `docs/VPS_MIGRATION_BACKLOG.md`), không đổi gì trong phiên này.
- **`feature/webhook-store`** — vẫn treo, chưa merge (xem HANDOFF MVP v2.0
  cũ để biết lý do).
- **Băng màu CONTENT đổi kênh thị giác** (nền=ngày, viền=TopicKey) — nếu
  Lead thấy khó phân biệt nhóm TopicKey hơn trước (đặc biệt khi 1 chủ đề có
  nhiều loại rơi vào NHIỀU ngày khác nhau, viền sẽ CHIA thành nhiều dải nhỏ
  thay vì 1 dải liền), đây là ĐÁNH ĐỔI đã được Lead xác nhận qua hỏi trực
  tiếp (chọn "đồng bộ nền với CONTEXT"), không phải bug.
- **Cột "Người thực hiện"** không có store backing — nếu sau này cần BÁO
  CÁO/lọc theo người thực hiện bằng code (không chỉ xem tay trên Sheet), sẽ
  cần thêm 1 layer store riêng, hiện CHƯA xây (đúng ý Lead: "để trống, tôi
  sẽ tự tạo trên sheet UI" — chỉ cần hiển thị + không mất, chưa cần machine
  đọc lại).
- **Cần Lead cấu hình lại màu Type/Status trên Sheet UI 1 lần** (nếu trước
  đây có) — đã bị sự cố §3B xoá mất, code giờ KHÔNG còn đụng tới nữa nên an
  toàn vĩnh viễn sau lần cấu hình lại này.
- **`aigen-pipeline` (repo riêng) có thay đổi CHƯA COMMIT** — 4 asset cũ đã
  xoá + 4 asset mới + 7 file logo template ghi đè theo brand-kit mới (xem
  §3C). KHÔNG tự ý commit ngoài phạm vi marketing-automation — Lead xác
  nhận rồi tự commit ở đó, hoặc giao việc rõ để làm tiếp.
- **Video brand-kit mới CHƯA kiểm bằng mắt** (không render/screenshot được
  qua công cụ phiên này, khác thư mục dự án) — chỉ xác nhận qua test suite
  + lý luận tương phản màu. Đề nghị Lead xem 1 video render thật để chốt.
