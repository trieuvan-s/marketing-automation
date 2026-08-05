## Bước 3 — Xác nhận Sheet sống (kiểm lại bằng API thật, không suy đoán)

- **3.1** Tab CONTEXT hiện có 33 dòng dữ liệu, cột Timestamp trải đủ
  **28/07, 29/07, 02/08, 03/08** (`sheets.display_days=7` đủ rộng, không cần
  chỉnh).
- **3.2** Kiểm trực tiếp `dataValidation` qua Sheets API raw (không qua wrapper
  code, vì code cố ý KHÔNG ghi `setDataValidation` lên 2 cột này để tránh đè
  cấu hình Dropdown-chip Lead tự đặt tay): cột **Output Type** vẫn còn
  `ONE_OF_LIST` {Article, Long-Article, Infographic, Video, AUTO},
  `showCustomUi: true` — dropdown chip nguyên vẹn, chọn được. Cột
  **Duyệt Context** vẫn còn `ONE_OF_LIST` {APPROVE, PENDING, REJECT, DELETE},
  `showCustomUi: true` — không bị lượt e2e này ghi đè/hạ cấp.
- **3.3** Nhãn tiếng Việt trên CONTENT tab đúng cấu hình `labels.vi` trong
  `settings.yaml`: `Status="BỎ QUA"` (map từ SKIPPED), Notes có mã lý do dịch
  ("Không hợp định dạng:", "Nguồn lỗi:"...). `Status="ERROR"` hiển thị
  nguyên (tiếng Anh) là ĐÚNG THIẾT KẾ — ERROR không nằm trong bảng
  `labels.vi.sheet_status` (chỉ map SKIPPED/NEEDS_HUMAN), không phải thiếu sót.

# E2E Đối chứng — 28/07+29/07 (baseline) vs sau lượt e2e 03/08

Nguồn: store (`document_store.db`), đọc trực tiếp sau khi queue rỗng hoàn toàn
(job cuối #45, `queue_worker` PID 19588 vẫn sống, poll rỗng). Baseline gốc:
[e2e-baseline-2807-2907.md](e2e-baseline-2807-2907.md).

## Bước 5.1-5.2 — Bảng đối chứng 13 chủ đề gốc 28-29/07

Lưu ý quan trọng: sau khi Lead tự tay chỉnh lại Gate 1 trên Sheet (phiên
29/07, 02-03/08), Lead **chỉ re-approve 2/13** chủ đề gốc. Store đã xoá layer
đã xử lý (Bước 1.2) cho cả 13 nên 11 chủ đề còn lại quay về `PENDING` (chưa
được thẩm định lại bằng Brief/Router mới) — đây KHÔNG phải "vẫn SKIPPED", mà
là "chưa được thử lại" vì Lead chưa duyệt. Raw của cả 13 vẫn còn nguyên vẹn.

| TopicKey | Trạng thái CŨ (baseline) | Trạng thái MỚI | Mã lý do |
|---|---|---|---|
| `f6c92386` | infographic SKIPPED (Router: không đủ số liệu) | PENDING (chưa re-approve) | — |
| `12f69cac` | article DONE | PENDING (chưa re-approve) | — |
| `57f1cec3` | chưa duyệt (Waiting) | PENDING (không đổi) | — |
| `8225cec5` | chưa duyệt (Waiting) | PENDING (không đổi) | — |
| `affaac5a` | chưa duyệt (Waiting) | PENDING (không đổi) | — |
| `71120571` | article DONE (job từng bị force-kill giữa job #24, đã fix bằng mark_failed+mark_execute) | PENDING (chưa re-approve) | — |
| `09d08d43` | article DONE | **article DONE** (re-approve, chạy lại, vẫn DONE) | — |
| `6859c4fe` | article DONE + infographic ERROR/NEEDS_HUMAN (facts rỗng) + video DONE | PENDING (chưa re-approve) | — |
| `cbce7186` | article DONE + infographic SKIPPED (Router: chỉ 2 số) + video DONE | PENDING (chưa re-approve) | — |
| `703db4c2` | chưa duyệt (Waiting) | PENDING (không đổi) | — |
| `6736e439` | **video SKIPPED** (Router: thiếu narrative) | **infographic DONE** ✅ | SKIPPED→DONE (Lead đổi Output Type Video→Infographic khi re-approve; Router chấp nhận tuyến infographic) |
| `aadba3da` | chưa duyệt (Waiting) | PENDING (không đổi) | — |
| `995d0d8d` | chưa duyệt (Waiting) | PENDING (không đổi) | — |

**Tóm tắt 5.2:**
- SKIPPED → DONE: **1 trường hợp** — `6736e439` (đổi Output Type Video→Infographic,
  Router chấp nhận). Đây là bằng chứng Router/Brief thay đổi có tác dụng, NHƯNG
  phép thử là "đổi kênh xuất", không phải "Router tự đảo ngược quyết định trên
  cùng kênh" — 3 ca SKIPPED-infographic khác (`f6c92386`, `6859c4fe` phần
  infographic, `cbce7186`) chưa được thử lại vì Lead không re-approve.
- Vẫn SKIPPED với mã lý do cũ: **0** (vì layer đã xử lý bị xoá theo đúng phạm
  vi Bước 1.2 — các ca này ở trạng thái PENDING, không phải SKIPPED lưu trữ).
  Muốn kiểm "Brief/Router mới có gỡ được không" cho 11 ca còn lại, cần Lead
  re-approve Gate 1 cho chúng ở lượt sau.
- 3 chủ đề định hướng video từng bị Router từ chối (nêu ở Bước 0.2): trong dữ
  liệu HIỆN TẠI (toàn bộ 33 chủ đề 28/07-03/08), quét lại chỉ còn **2 ca
  video bị từ chối/lỗi**, cả hai đều thuộc lô MỚI 03/08, không phải 3 chủ đề
  gốc: `03a4b55f` (FORMAT_MISMATCH — thiếu narrative) và `a4c41a49`
  (NEEDS_HUMAN — số liệu 96% không thấy trong evidence). Ca video-reject gốc
  duy nhất xác nhận được (`6736e439`) đã được Lead đổi sang Infographic nên
  không còn tồn tại ở tuyến video nữa.

## Bước 5.3 — Kiểm tay 5 bài DONE (thực chất, có nguồn, không claim ngoài nguồn)

Đã đọc trực tiếp `output` + `facts[]` trong store (không phải qua Sheet):

1. **`09d08d43` (article)** — "PNJ và một phiên giao dịch...". Có số liệu cụ
   thể (32.650 đồng/cp, -0,76%), mỗi fact có field `source` trỏ đúng câu gốc
   ("Kết phiên 28/7, thị giá PNJ dừng ở mức 32.650 đồng/cp..."). Không boilerplate.
2. **`347782e1` (article)** — "Cuộc đua chạm mốc 500m...". Có góc nhìn phân
   tích riêng (Vingroup/BRG/Thaiholdings), không phải liệt kê khô.
3. **`a4222b7f` (article)** — "Quốc hội họp bất thường...15 luật". Nội dung
   bám sát sự kiện thật, có câu hỏi mở đúng phong cách H1/H3 đã cấu hình.
4. **`6736e439` (infographic)** — CSV, giá H2SO4 +249%, lợi nhuận Q2 +87%. Facts
   có `source` trỏ câu gốc, không lẫn số liệu suy diễn.
5. **`30da9ff2` (infographic)** — MBS/dòng vốn FTSE. Cấu trúc 4 giai đoạn rõ,
   khớp nguồn.

Kết luận 5.3: **cả 5 đạt** — thực chất, không boilerplate, facts[] truy được
câu nguồn, không thấy claim vượt khỏi evidence.

## Bước 5.4 — Ca boilerplate

Không xác định được ca "boilerplate rõ ràng" nào trong 13 chủ đề baseline hay
lô 03/08 mới — tất cả SKIPPED trong dữ liệu đều do Router-reject kênh
(thiếu số liệu/narrative) hoặc NEEDS_HUMAN (facts rỗng/không khớp evidence),
không phải do guardrail boilerplate bắt được nội dung rác. Cần Lead xác nhận
lại nếu có ca boilerplate cụ thể muốn kiểm — hiện chưa có mẫu để đối chứng.

## Lô 8+1 chủ đề Lead tự duyệt (29/07-03/08, ngoài 13 gốc)

| TopicKey | Chủ đề | Output Type | Kết quả |
|---|---|---|---|
| `347782e1` | Cuộc đua Vingroup/BRG/Thaiholdings | Article | DONE |
| `30da9ff2` | CTCK hé lộ 30 mã FTSE | Infographic | DONE (đã render ảnh) |
| `978dfe2b` | BCTC Q2 3/8 | Infographic | DONE (đã render ảnh) |
| `a4222b7f` | Chủ tịch Quốc hội — 15 luật | Article | DONE |
| `0cc4ec40` | Thế giới Di động vượt Vinhomes/Viettel | Video | DONE (MOCK, chưa bật Sonnet) |
| `91d09f03` | PMI Việt Nam tăng cao nhất 5 tháng | **Long-Article** | exec=DONE nhưng **0 content_output** — xác nhận lại hạn chế đã biết: "Long-Article" chưa có producer thật, chọn trên Sheet nhưng không sinh gì |
| `a4c41a49` | Nafoods Group — lợi nhuận +96% | AUTO | **NEEDS_HUMAN** cả 3 kênh — guardrail bắt đúng: "Số liệu 96% không thấy trong evidence/background" |
| `03a4b55f` | Kỳ vọng VN-Index 1.850 điểm | AUTO | article DONE + infographic DONE (đã render ảnh) + video SKIPPED (FORMAT_MISMATCH) |
| `fc8c0163` | Kiến tạo động lực tăng trưởng mới (chủ đề Lead tự crawl+duyệt thêm, không nằm trong 8 chủ đề ban đầu) | Infographic | DONE |

## Bước 6 — 3 thứ đang treo

**6.1 Task Scheduler Waiting→Running→DONE:** xác nhận qua log thật — job #30
đến #45 đều đi đúng chuỗi `Nhận job [type] → ... → DONE (dispatch)` không có
job nào đứng hình ở "Running...". Duy nhất job #24 (topic `71120571`, TRƯỚC
khi tôi force-kill worker) bị kẹt ở "Running..." — đã xử lý bằng
`mark_failed()` + `mark_execute('FAILED')`, không phải lỗi cơ chế, mà do tôi
chủ động dừng tiến trình giữa chừng.

**6.2 Notes RENDER_RANKING_GUARD sống sót qua sync:** quét toàn bộ 33 chủ đề
28/07-03/08, **0 ca nào có Notes RENDER_RANKING_GUARD** trong lượt e2e này —
nghĩa là cơ chế guard không bị kích hoạt (không có infographic nào vượt
ngưỡng mật độ ranking cần cắt bớt), không phải guard bị hỏng. Không có dữ
liệu để xác nhận "sống sót qua sync" trong lượt này — cần một ca thật kích
hoạt guard ở lượt sau để kiểm.

**6.3 Ảnh render — Nguồn/band/logo:** đã mở trực tiếp 2/3 ảnh PNG đã render
(`kỳ-vọng-vn-index...4x5.png`, `cập-nhật-bctc...4x5.png`):
- Cả 2 đều có band "Nguồn: cafef.vn" + disclaimer ở đáy, không đè lên nội
  dung phía trên.
- Ảnh BCTC (Vietnam Airlines/Smart Mind Securities): logo góc trên-trái tách
  biệt rõ với tiêu đề — OK.
- Ảnh VN-Index 1.850: logo góc trên-trái **khá sát** chữ "M" của tiêu đề
  "MBS:" — chưa chạm hẳn nhưng khoảng cách hẹp hơn ảnh còn lại, nên xem lại
  nếu Lead thấy khó chịu khi nhìn thật.
- Đã mở thêm ảnh 9:16 (`ctck-hé-lộ...9x16.png`): logo tách biệt rõ tiêu đề,
  band đáy sạch — OK, không lặp lại vấn đề của ảnh 4:5 VN-Index.

Tổng: 3/3 ảnh đã kiểm — 2/3 hoàn toàn ổn, 1/3 (VN-Index 4:5) có khoảng cách
logo/tiêu đề hẹp đáng lưu ý nhưng chưa tới mức chạm chữ.
