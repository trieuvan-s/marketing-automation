# store/ — SQLite Document Store (viết sẵn chờ ráp)

> Nền cho "Sheet chỉ là UI/view; mọi dữ liệu neo TopicKey trong store". Xem
> `docs/VPS_MIGRATION_BACKLOG.md` mục **A7** (trạng thái mới nhất, đã xác
> thực bằng dữ liệu thật) và **A6** (bối cảnh kiến trúc gốc). Module này
> **CHƯA RÁP** vào pipeline/Sheet thật — xem "RÁP SAU" cuối file.

## Chạy test

```bash
python -m pytest store/ -v
```

42 test hiện có (8 `api/test_main.py` + 14 `test_backfill_from_sheet.py` +
20 `test_document_store.py`) — tất cả mock/DB tạm, KHÔNG mạng thật.

## Schema (`schema.sql`)

Bảng `documents`, APPEND-ONLY (không UPDATE/DELETE nào trong
`document_store.py`) — mỗi lần ghi luôn là **version mới**, không ghi đè.

| Cột | Ý nghĩa |
|---|---|
| `topic_key` | Neo danh tính chủ đề (khớp `TopicKey` trên Sheet) |
| `layer` | 1 trong `raw`/`brief`/`content_output`/`infographic`/`video` |
| `content_type` | **Thêm 2026-07-19 (BUG 1)** — `''` cho layer không có đa loại; `'article'`/`'infographic'`/`'video'` cho `content_output` (khớp `CONTENT.Type` trên Sheet — xem BUG 2) |
| `version` | Tự tăng theo `(topic_key, layer, content_type)` |
| `written_by` | `'ma'` (4 layer đầu) hoặc `'aigen'` (chỉ `video`) — enforce bằng CHECK constraint, không dựa kỷ luật code |

`UNIQUE(topic_key, layer, content_type, version)` — khoá đã sửa sau khi
phát hiện qua dữ liệu thật: 1 topic_key thường có **3 content_type**
(article/infographic/video) cùng layer `content_output`; thiếu
`content_type` trong khoá sẽ khiến 3 nội dung khác nhau bị coi là 3 version
nối tiếp của CÙNG 1 tài liệu (2/3 bị "chôn" khi đọc lại) — xem A7 trong
`docs/VPS_MIGRATION_BACKLOG.md` để biết đầy đủ.

## `document_store.py` — 4 hàm

```python
write_document(topic_key, layer, payload, written_by, *, content_type="", db_path=None) -> int
read_latest(topic_key, layer, content_type, *, db_path=None) -> dict | None
read_history(topic_key, layer, content_type, *, db_path=None) -> list[tuple[int, dict, str]]
list_topics(layer=None, *, db_path=None) -> list[str]
```

`content_type` **BẮT BUỘC** ở `read_latest`/`read_history` (không có mặc
định — phải luôn truyền `""` cho layer không đa loại, giá trị thật cho
`content_output`). `write_document` với `layer="content_output"` mà thiếu
`content_type` → `ValueError` ngay, không âm thầm ghi sai.

Đường dẫn DB đọc từ ENV `DOCUMENT_STORE_PATH` (mặc định
`store/document_store.db` tương đối theo CWD — chỉ hợp lý cho dev/test cục
bộ, triển khai thật PHẢI set ENV tường minh, cùng bài học A5).

## `backfill_from_sheet.py` — xác thực schema bằng Sheet thật, CHỈ ĐỌC

```bash
python -m store.backfill_from_sheet              # --dry-run (mặc định) — chỉ in báo cáo
python -m store.backfill_from_sheet --write       # ghi vào DB TẠM (tempfile), KHÔNG phải DB thật
```

⚠️ **CHỈ ĐỌC Sheet** — dựng `SheetsBoard` trực tiếp (`board._spreadsheet()`),
KHÔNG qua `_open_board()`/`ensure_tabs()`/`migrate_rows()` (2 hàm sau tự
chạy khi mở board bình thường và TỪNG XOÁ RỖNG dữ liệu Gate 1 thật khi đổi
tên cột — xem "QUY TẮC VÀNG KHI ĐỘNG VÀO SHEET" trong
`docs/VPS_MIGRATION_BACKLOG.md`).

Đã chạy trên Sheet production thật (2026-07-19) — kết quả đầy đủ trong A7
(`docs/VPS_MIGRATION_BACKLOG.md`): 27/27 bản ghi thành công, 3/3 topic_key
đa content_type đọc lại độc lập đúng, phát hiện 7+8 cột Sheet không map vào
layer nào (cột trạng thái vận hành — Duyệt Context/Execute/Approve/Gate3...),
`AssetPath` rỗng ở cả 9/9 dòng CONTENT thật (Production Factory chưa từng
render).

## RÁP SAU (bắt buộc đọc trước khi coi Document Store "xong")

1. **Chưa dual-write thật** — `document_store.py` chỉ được gọi qua
   `backfill_from_sheet.py --write` (ghi vào DB TẠM để test schema), CHƯA
   có code path nào ghi vào `store/document_store.db` thật.
2. **Chưa nối vào `scripts/produce_from_sheet.py`/pipeline thật** — theo
   đúng quyết định A6 "LÀM SAU khi luồng thông" (chờ aigen-pipeline render
   video thật ít nhất 1 lần, tránh ráp trên contract còn có thể đổi).
3. **7 cột CONTEXT + 8 cột CONTENT không map vào layer nào** (toàn bộ là
   cột trạng thái vận hành, không phải nội dung) — CHƯA quyết định có cần 1
   nơi neo khác ngoài Sheet hay không, xem A7.
4. **`scripts/produce_from_sheet.py` còn dùng `"video_script"` cũ** (chưa
   khớp `ContentFormat.VIDEO_SCRIPT="video"` đã sửa ở `models.py`) — CỐ Ý
   CHƯA sửa vì file đó đang là vùng agent-B sửa dở, xem C7 trong
   `docs/VPS_MIGRATION_BACKLOG.md`. Người merge sau cùng cần rà lại.
5. **`aigen_repo_path`/`DOCUMENT_STORE_PATH` trên VPS** — chưa set ENV thật
   trên môi trường triển khai, chỉ mặc định tương đối cho dev/test.
