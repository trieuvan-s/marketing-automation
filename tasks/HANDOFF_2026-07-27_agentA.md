# BÀN GIAO — phiên 2026-07-27 (P2 store-as-truth, agent-A)
## Fix "renderer đọc STORE thay Sheet preview" + Bước 5.4 (test phục hồi) THẬT

> Tiếp nối trực tiếp `tasks/HANDOFF_2026-07-25_agentA.md` — đọc file đó trước
> nếu chưa nắm bối cảnh P2 store-as-truth. File này là bàn giao MỚI NHẤT,
> KHÔNG phải cập nhật đè lên file cũ (giữ cả 2, theo đúng nếp handoff-theo-
> ngày của repo).

## TÓM TẮT 1 DÒNG

Bug Bước 5.3 (render vỡ vì đọc JSON cắt cụt) đã sửa TẬN GỐC theo đúng chỉ đạo
Lead: **store giờ giữ NGUYÊN VĂN, truncate chỉ còn ở điểm đẩy Sheet.** Đã xác
minh bằng render THẬT (ảnh đính kèm chat) + Bước 5.4 (test phục hồi THẬT trên
Sheet production, xoá 2 dòng CONTEXT thật rồi phục hồi đúng 100% qua
TopicKey). **597/597 test xanh.** Phát hiện 1 vấn đề MỚI (AssetPath bị
`sync_all()` xoá vì store chưa lưu — xem mục "CẦN LEAD/agent-B QUYẾT" dưới),
đã khôi phục dữ liệu thật, CHƯA tự sửa root cause vì đụng vùng Bước 3.4 (Drive
upload) chưa xong.

## VIỆC 1 — Renderer đọc STORE, KHÔNG còn đọc Sheet preview (XONG)

Root cause (đã xác nhận CHÍNH XÁC, không phải "renderer đọc nhầm chỗ" như
tưởng ban đầu — mà là **store bản thân cũng chỉ nhận bản cắt 1500 ký tự**,
y hệt Sheet):

| File | Trước | Sau |
|---|---|---|
| `scripts/produce_from_sheet.py` | `_write_content()` (5 điểm gọi: article DONE/NEEDS_HUMAN, infographic/video chính, `run_draft()`, `run_ingest()`) ghi `preview` (cắt 1500 ký tự + hậu tố `"…(xem file)"`) vào `content_output.output` | Ghi `draft.body` NGUYÊN VĂN. Xoá hằng số `_OUTPUT_PREVIEW` khỏi file này. |
| `store/sync_service.py` | `render_content_to_sheet()` đẩy thẳng `out.get("output","")` lên Sheet, không cắt | Thêm `_OUTPUT_PREVIEW = 1500` + `_preview_output()` — CHỈ cắt ở điểm này (đẩy Sheet), store vẫn giữ đầy đủ. |
| `scripts/render_production_assets.py` | `render_one()` đọc `json.loads(item["output"])` — `item["output"]` là ô Sheet CONTENT.Output (đã cắt) | Đọc `ps.read_content_output(item["topic_key"], "infographic")` — TỪ STORE, tra theo TopicKey. `item["output"]` không còn được dùng. |

**Sửa dữ liệu thật đã hỏng**: store thật (`topic_key=c3a6a0ca39a13f24`, bài
Google) đang giữ đúng bản cắt cụt (1565 ký tự, JSON đứt giữa `"priority":`).
Đã ghi **version 2** (append-only, KHÔNG sửa version 1) với JSON đầy đủ 2121
ký tự lấy từ file cục bộ
(`../marketing-database/marketing-automation/output/2026-07-25/chỉ-trong-nửa-năm-công-ty-mẹ-google-thu--infographic.json`),
đã `json.loads()` xác nhận sạch trước khi ghi.

## VIỆC 2 — Xác minh khép kín bằng render THẬT (XONG)

Chạy lại `python scripts/render_production_assets.py --limit 1` — gọi OpenAI
gpt-image-2 THẬT, KHÔNG mock:

```
[render] 'Chỉ trong nửa năm, công ty mẹ Google thu hơn 6 triệu tỷ đồng' -> 3/3 tỷ lệ
Tổng: render 1 | bỏ qua (đã render) 0 | bỏ qua (chưa qua Gate 2) 0 | NEEDS_HUMAN 0
```

3 tiêu chí Lead đặt ra:
1. ✅ **JSON parse được** — không còn "Output không phải JSON hợp lệ".
2. ⚠️ **Band đáy hiển thị "Nguồn: cafef.vn"** — không rỗng, NHƯNG in domain,
   không phải tên nguồn "CafeF" như Lead đã chốt trước đây. Đúng dự đoán Lead
   từng ghi ("nếu ảnh ra 'cafef.vn' thì còn chỗ dùng `domain_of()` trên đường
   hiển thị") — **vùng agent-B** (render infographic), tôi không tự sửa.
3. ✅ **Số khớp facts** — doanh thu 6 tháng ~6 triệu tỷ đồng, so GDP >90%,
   YoY +23%, Google Cloud +82%, đều khớp 29 facts đã trích từ phiên trước.

Ảnh đã gửi trực tiếp trong chat (không đính kèm file ở đây — tránh trùng bản
với `output/2026-07-27/assets/`).

**Quan sát phụ, không phải bug do fix này**: log render có dòng
`brand_stamp: EDGE SANITIZER cắt dải mép trên bất thường CROPPED_TOP_BAND=29px`
— cơ chế tự động sẵn có trong `render/brand_stamp.py`, ảnh ra không thấy
artifact bất thường. Ghi nhận, không chặn.

## VIỆC 3 — Test chống tái phát (XONG, 597/597 xanh)

File mới/sửa: `tests/test_pipeline.py`, `store/test_sync_service.py`.

4 test MỚI:
- `test_run_writes_full_body_to_store_over_1500_chars_not_truncated` —
  `produce_from_sheet.run()` với writer trả nội dung >1500 ký tự thật, khoá
  store phải giữ marker cuối bài (không bị cắt + không còn hậu tố "…(xem").
- `test_render_one_parses_full_json_over_1500_chars_from_store` — tái hiện
  ĐÚNG điều kiện gây bug (JSON >1500 ký tự) qua `render_one()` đọc từ store,
  phải render được (không NEEDS_HUMAN).
- `test_render_one_missing_topic_key_in_store_returns_error_reason` —
  ca robustness mới (topic_key không có trong store) phải báo lỗi RÕ, không
  crash, không lẫn với ca JSON hỏng.
- `test_render_content_to_sheet_truncates_output_but_store_keeps_full` —
  khoá lại: Sheet VẪN cắt 1500 ký tự (không nới giới hạn hiển thị), nhưng
  store đọc lại nguyên văn.

3 test CŨ sửa lại (vỡ do đổi hành vi đọc của `render_one()`, phải seed store
qua `pipeline_store.write_content_output()` thay vì truyền `item["output"]`
thẳng): `test_render_one_clean_spec_returns_png_bytes`,
`test_render_one_gate2_typo_flows_through_unchecked_known_risk`,
`test_render_one_bad_output_json_returns_error_reason`.

`python -m pytest` → **597 passed** (593 cũ + 4 mới), 0 failed. Đã cập nhật
`reports/TEST_RESULT.md`.

## FILE MỚI — `scripts/sync_store_sheet.py`

Không có CLI nào gọi `store/sync_service.py::sync_all()` trên Sheet THẬT
trước phiên này (chỉ có unit test dùng fake board) — cần để chạy Bước 5.4
thật, nên đã viết 1 file mỏng (cùng khuôn `_open_board()` như
`render_production_assets.py`/`produce_from_sheet.py`). Đây là lệnh vận hành
bình thường TỪ NAY VỀ SAU (đồng bộ 2 chiều store↔Sheet) lẫn "phục hồi khi xoá
nhầm":
```
python scripts/sync_store_sheet.py
```

## BƯỚC 5.4 — Test phục hồi THẬT trên Sheet production (XONG, PASS)

Đã làm THẬT trên spreadsheet thật (KHÔNG phải mock/fake board):

1. Snapshot CONTEXT (7 dòng) + CONTENT (3 dòng) trước khi xoá.
2. Xoá 2 dòng CONTEXT THẬT (`ws.delete_rows()`, gspread) — chọn 2 dòng PENDING
   an toàn (`90e8175b4a883d1c` "TP.HCM đề xuất...", `b588682a5e57dc27` "Nước
   láng giềng..."), KHÔNG đụng dòng Google đã duyệt/sản xuất.
3. Chạy `python scripts/sync_store_sheet.py` (ingest trước, render lại sau).
4. So sánh lại theo TopicKey (không theo vị trí dòng — đúng nguyên tắc Lớp 5):
   **7/7 dòng CONTEXT phục hồi ĐẦY ĐỦ**, mọi field khớp 100% (title/hook/
   source/tickers/status/execute/topic_key), **3/3 dòng CONTENT phục hồi ĐẦY
   ĐỦ**.

**2 khác biệt CÓ GIẢI THÍCH, KHÔNG PHẢI mất dữ liệu:**
- **Timestamp mọi dòng đổi từ "25/07/2026" → "27/07/2026"** — `context_row()`/
  `content_row()` luôn dùng `_now_ddmmyyyy()` khi không truyền `ts` tường
  minh, và `render_*_to_sheet()` không truyền → Timestamp bị RE-STAMP mỗi lần
  render lại từ store, không giữ ngày crawl/sinh gốc. **Cosmetic, nhưng đáng
  báo Lead**: nếu ai dùng cột Timestamp để sắp xếp/audit theo thời điểm THẬT
  phát sinh, giờ sẽ sai sau bất kỳ lần `sync_all()` nào.
- **Execute của dòng Google đổi "RUN" → "DONE"** — ĐÚNG, KHÔNG PHẢI lỗi: store
  đã ghi Execute=DONE từ 2026-07-25 (khi `produce_from_sheet.run()` sinh xong
  cả 3 sản phẩm), nhưng Sheet CHƯA BAO GIỜ được `sync_all()` chạy thật cho tới
  phiên này — Sheet chỉ đang hiển thị giá trị CŨ. Đây là bằng chứng
  store-as-truth hoạt động đúng: Sheet giờ phản ánh ĐÚNG trạng thái thật.

## 🔴 CẦN LEAD/agent-B QUYẾT — phát hiện MỚI khi chạy 5.4 thật

**`sync_all()` (qua `render_content_to_sheet()`) đã XOÁ MẤT AssetPath thật**
của bài Google (ô hiển thị "Mở file" → rỗng) ngay sau khi tôi vừa render xong
ở Việc 2. Nguyên nhân: `render_production_assets.py::run()` ghi AssetPath
**TRỰC TIẾP vào ô Sheet** qua `board.set_content_cell(item["row"], "AssetPath", ...)`
— **KHÔNG BAO GIỜ ghi vào `content_status.asset_url`/`asset_local_path` của
store**. Vì `render_content_to_sheet()` coi AssetPath là cột MÁY-SỞ-HỮU và
dựng lại HOÀN TOÀN từ `content_status.asset_url or asset_local_path`, bất kỳ
lần `sync_all()` nào chạy SAU khi render sẽ xoá sạch AssetPath cho tới khi
store biết về nó.

**Đã khôi phục dữ liệu thật** — chạy lại `render_production_assets.py --limit 1`
lần nữa (idempotent, ai_full cache theo hash nên KHÔNG tốn thêm tiền OpenAI),
AssetPath đã có lại "Mở file".

**Vì sao tôi KHÔNG tự sửa root cause**: hướng sửa hợp lý là
`render_production_assets.py` (file tôi ĐƯỢC giao sửa) gọi thêm
`ps.write_content_status(topic_key, "infographic", asset_local_path=str(primary_fn))`
ngay sau khi ghi Sheet — nhưng việc này chạm đúng vùng **Bước 3.4 (upload
Google Drive) — Lead đã ghi rõ "BỊ CHẶN, CHƯA LÀM" vì Drive API chưa bật**.
Tôi không biết đây có phải bước tạm (dùng `asset_local_path` = đường dẫn PNG
cục bộ trước, đổi sang `asset_url` Drive sau) hay Lead muốn gộp làm 1 lần với
Bước 3.4 luôn. **Dừng, chờ Lead quyết**, giống kỷ luật đã áp dụng suốt phiên
trước.

**Rủi ro nếu chưa sửa**: bất kỳ ai chạy `sync_store_sheet.py`/`sync_all()`
SAU KHI render 1 infographic mới (trước khi Bước 3.4 xong) sẽ làm AssetPath
biến mất trên Sheet — không mất ảnh (file PNG vẫn còn trên đĩa), chỉ mất
LIÊN KẾT hiển thị, tự khôi phục bằng cách render lại (cache hit, $0).

## GHI NHẬN LẠI (từ phiên trước, chưa đổi)

- **"Nguồn: cafef.vn" (domain) thay vì "CafeF" (tên nguồn)** — vùng agent-B,
  xem Việc 2 mục 2.
- **Bước 3.4 (Drive upload) vẫn CHƯA LÀM** — Drive API chưa bật trên GCP
  project, xem `HANDOFF_2026-07-25_agentA.md` cho link Enable.

## TRẠNG THÁI SHEET THẬT (sau phiên này)

CONTEXT: 7 dòng, nguyên vẹn theo TopicKey (Timestamp mọi dòng nay ghi
27/07/2026 do render lại — xem giải thích trên). CONTENT: 3 dòng cho bài
Google, infographic AssetPath đã khôi phục ("Mở file"), Output đầy đủ (không
còn cắt cụt JSON khi đọc lại từ store, Sheet vẫn hiển thị bản preview 1500 ký
tự như thiết kế).

## FILE THAY ĐỔI (working tree, CHƯA COMMIT)

```
M reports/TEST_RESULT.md
M scripts/produce_from_sheet.py
M scripts/render_production_assets.py
M store/sync_service.py
M store/test_sync_service.py
M tests/test_pipeline.py
?? scripts/sync_store_sheet.py   (file mới)
?? tasks/HANDOFF_2026-07-27_agentA.md   (file này)
```

`python -m pytest` → 597/597 xanh (chạy lần cuối SAU khi thêm
`scripts/sync_store_sheet.py`, xác nhận không phá gì).

## HƯỚNG DẪN COMMIT (người vận hành tự làm, đúng kỷ luật KHÔNG auto-commit)

Gợi ý 1 commit duy nhất (mọi thay đổi cùng 1 chủ đề: renderer đọc store thay
Sheet preview + Bước 5.4):

```
git add reports/TEST_RESULT.md scripts/produce_from_sheet.py \
        scripts/render_production_assets.py scripts/sync_store_sheet.py \
        store/sync_service.py store/test_sync_service.py tests/test_pipeline.py \
        tasks/HANDOFF_2026-07-27_agentA.md
git commit -m "P2 store-as-truth: renderer/store giữ nguyên văn Output (bỏ truncate 1500 ky tu o store), them CLI sync_store_sheet.py, Buoc 5.4 xac nhan phuc hoi that"
```

**KHÔNG merge vào `develop`** — theo đúng yêu cầu, chờ **agent-B kiểm nghiệm
kết quả** (đặc biệt mục "CẦN LEAD/agent-B QUYẾT" ở trên — AssetPath/
content_status, và ghi nhận "Nguồn: cafef.vn" domain) **trước khi merge**.

## KHÔNG LÀM (kế thừa + phát sinh mới)

Không tự sửa vùng hiển thị "Nguồn" trên ảnh (agent-B). Không tự wiring
`content_status.asset_url`/`asset_local_path` trong `render_production_
assets.py` (chờ Lead quyết quan hệ với Bước 3.4 Drive upload). Không đụng
`ai_full.py`/`brand_stamp.py`/aigen-pipeline/`validators/`/`content-rules/`.
Không push. Không merge `develop`.
