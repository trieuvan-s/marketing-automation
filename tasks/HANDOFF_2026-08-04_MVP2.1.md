# BÀN GIAO — 2026-08-04, MVP 2.1 (agent-A)

> Đọc file này TRƯỚC nếu tiếp nhận phiên làm việc. Bàn giao nối tiếp
> `tasks/HANDOFF_2026-07-29_MVP.md` (MVP v2.0) — không lặp lại nội dung đã
> đúng ở đó, chỉ ghi những gì ĐỔI từ mốc đó tới nay.
>
> Lịch sử quyết định: `PROJECT_HANDOFF_P5.md`. Bản đồ code:
> `docs/MODULE_INDEX.md`. Quy tắc bất biến: `CLAUDE.md`. Nợ dài hạn:
> `docs/VPS_MIGRATION_BACKLOG.md`.

**MỤC LỤC** — §1 trạng thái · §2 việc đã làm từ MVP v2.0 · §3 SỰ CỐ THẬT (đã
sửa) · §4 hạ tầng đang chạy · §5 git · §6 test · §7 nợ còn lại · §8 lệnh hay
dùng.

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

`python -m pytest` (đầy đủ, không lọc path) — **774 passed**, 0 fail, 40
warning (Pillow deprecation, không liên quan code này).

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
