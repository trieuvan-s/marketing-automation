-- SQLite Document Store (docs/VPS_MIGRATION_BACKLOG.md A6/A7 -- "Sheet CHỈ
-- LÀ UI/view; mọi dữ liệu neo TopicKey trong store"). APPEND-ONLY: không
-- UPDATE, không DELETE ở tầng ứng dụng (document_store.py không có hàm nào
-- làm 2 việc đó) -- mỗi lần ghi = version mới. Lý do: sự cố migrate_rows()
-- từng XOÁ RỖNG dữ liệu thật trên Sheet (xem "QUY TẮC VÀNG KHI ĐỘNG VÀO
-- SHEET" trong docs/VPS_MIGRATION_BACKLOG.md) -- thiết kế này loại bỏ hẳn
-- khả năng tái diễn vì schema không có đường nào để UPDATE/DELETE.

-- BUG 1 (phát hiện qua backfill --dry-run trên Sheet thật, 2026-07-19): 1
-- topic_key có THỂ có NHIỀU content_type trong layer 'content_output' (vd
-- article + infographic + video CÙNG 1 chủ đề, xác nhận thật trên Sheet: cả
-- 3/3 topic_key thử đều vậy) -- UNIQUE(topic_key, layer, version) CŨ coi 3
-- content_type đó là 3 VERSION NỐI TIẾP của CÙNG 1 tài liệu, read_latest()
-- chỉ thấy content_type ghi SAU CÙNG, 2 cái kia "chìm" (vẫn còn trong DB,
-- chỉ không đọc lại được qua read_latest/read_history nếu không biết
-- version chính xác). Thêm cột content_type vào khoá UNIQUE để mỗi
-- content_type có dải version RIÊNG, độc lập nhau.
--
-- P2 STORE-AS-TRUTH (2026-07-23, nhánh feature/store-as-truth) -- thêm 2
-- layer MỚI để Sheet trở thành VIEW thuần (Sheet KHÔNG còn là nơi giữ trạng
-- thái duy nhất, xem docs/VPS_MIGRATION_BACKLOG.md mục P2):
--   'gate_status'    -- TOPIC-LEVEL (content_type='' luôn, giống raw/brief).
--                        Gộp CONTEXT.Duyệt Context/Execute/Output Type/Notes
--                        thành 1 payload versioned cùng nhau (đọc 1 lần,
--                        không cần merge nhiều layer). Payload:
--                        {gate1, execute, output_type: [...], notes}.
--   'content_status' -- CONTENT-LEVEL, content_type BẮT BUỘC (giống
--                        content_output -- 1 topic_key có nhiều content_type,
--                        mỗi content_type có trạng thái duyệt/đăng RIÊNG,
--                        vd infographic đã Duyệt Public trong khi video còn
--                        PENDING). Gộp CONTENT.Duyệt Content/Duyệt Public/
--                        Notes/Social Link/Posting Status + asset_url/
--                        asset_local_path/asset_drive_file_id (Bước 3.4).
--                        Payload: {gate2, gate3, notes, social_link,
--                        posting_status, asset_url, asset_local_path,
--                        asset_drive_file_id, asset_content_hash}.
--   'log'             -- NHẬT KÝ TOÀN CỤC (thay tab LOG cũ trên Sheet) --
--                        KHÔNG gắn 1 topic_key cụ thể (banner LLM active, tổng
--                        kết 1 lượt run()...) nên dùng topic_key SURROGATE cố
--                        định "_system" (xem store/pipeline_store.py::
--                        _LOG_TOPIC_KEY) -- mỗi lời gọi write_log() = 1
--                        version MỚI dưới CÙNG topic_key này, read_history()
--                        trả ĐÚNG thứ tự thời gian = toàn bộ nhật ký, tái dùng
--                        NGUYÊN CƠ CHẾ append-only/versioned đã có, KHÔNG cần
--                        bảng riêng. Payload: {level, message, engine}. LÝ DO
--                        BẮT BUỘC chuyển layer này vào store (2026-07-23, theo
--                        chỉ đạo Lead): sync service store->Sheet (Bước 3) sẽ
--                        DỰNG LẠI TOÀN BỘ view Sheet từ store mỗi lần chạy --
--                        log() ghi THẲNG Sheet (không qua store) sẽ bị XOÁ ở
--                        lần sync kế tiếp (2 bộ ghi tranh 1 mặt phẳng, bộ có
--                        thẩm quyền là store).
-- CỐ Ý TÁCH khỏi content_output/infographic/video (nội dung SINH RA, coi như
-- bất biến 1 khi Content Factory ghi xong) -- gate_status/content_status là
-- TRẠNG THÁI VẬN HÀNH, đổi liên tục do người bấm trên Sheet (qua sync
-- service), tách riêng để KHÔNG phải ghi lại toàn bộ nội dung (có thể rất
-- dài) chỉ để đổi 1 cờ duyệt.
CREATE TABLE IF NOT EXISTS documents (
    id            INTEGER PRIMARY KEY,
    topic_key     TEXT NOT NULL,
    layer         TEXT NOT NULL CHECK (layer IN (
                      'raw', 'brief', 'content_output', 'infographic', 'video',
                      'gate_status', 'content_status', 'log'
                  )),
    -- '' (rỗng) cho layer KHÔNG có đa loại (raw/brief/infographic/video/
    -- gate_status -- mỗi topic_key chỉ có 1 bản/layer đó). content_output VÀ
    -- content_status BẮT BUỘC giá trị thật ('article'/'infographic'/'video'
    -- -- khớp CONTENT.Type trên Sheet, xem BUG 2) -- enforce ở
    -- document_store.py::write_document(), KHÔNG ở CHECK constraint (schema
    -- không biết layer nào "hiện tại" cần bắt buộc theo quy tắc nghiệp vụ,
    -- chỉ Python mới biết).
    content_type  TEXT NOT NULL DEFAULT '',
    version       INTEGER NOT NULL,
    payload_json  TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    -- Quyền ghi TÁCH BẠCH, enforce Ở SCHEMA (không dựa kỷ luật code):
    -- marketing-automation ('ma') ghi 7 layer (gồm cả gate_status/
    -- content_status/log -- sync service LÀ 1 phần 'ma', KHÔNG phải bên thứ
    -- 3); aigen-pipeline ('aigen') CHỈ ghi 'video'. Không bảng nào 2 bên cùng
    -- ghi -- ghi sai layer cho written_by -> SQLite tự raise IntegrityError.
    written_by    TEXT NOT NULL CHECK (
        (written_by = 'ma'    AND layer IN ('raw', 'brief', 'content_output', 'infographic', 'gate_status', 'content_status', 'log'))
        OR
        (written_by = 'aigen' AND layer = 'video')
    ),
    UNIQUE (topic_key, layer, content_type, version)
);

CREATE INDEX IF NOT EXISTS idx_documents_topic_layer ON documents (topic_key, layer);
