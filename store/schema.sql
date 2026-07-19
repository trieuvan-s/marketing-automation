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
CREATE TABLE IF NOT EXISTS documents (
    id            INTEGER PRIMARY KEY,
    topic_key     TEXT NOT NULL,
    layer         TEXT NOT NULL CHECK (layer IN ('raw', 'brief', 'content_output', 'infographic', 'video')),
    -- '' (rỗng) cho layer KHÔNG có đa loại (raw/brief/infographic/video --
    -- mỗi topic_key chỉ có 1 bản/layer đó). content_output BẮT BUỘC giá trị
    -- thật ('article'/'infographic'/'video' -- khớp CONTENT.Type trên Sheet,
    -- xem BUG 2) -- enforce ở document_store.py::write_document(), KHÔNG ở
    -- CHECK constraint (schema không biết layer nào "hiện tại" cần bắt buộc
    -- theo quy tắc nghiệp vụ, chỉ Python mới biết).
    content_type  TEXT NOT NULL DEFAULT '',
    version       INTEGER NOT NULL,
    payload_json  TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    -- Quyền ghi TÁCH BẠCH, enforce Ở SCHEMA (không dựa kỷ luật code):
    -- marketing-automation ('ma') ghi 4 layer đầu; aigen-pipeline ('aigen')
    -- CHỈ ghi 'video'. Không bảng nào 2 bên cùng ghi -- ghi sai layer cho
    -- written_by -> SQLite tự raise IntegrityError.
    written_by    TEXT NOT NULL CHECK (
        (written_by = 'ma'    AND layer IN ('raw', 'brief', 'content_output', 'infographic'))
        OR
        (written_by = 'aigen' AND layer = 'video')
    ),
    UNIQUE (topic_key, layer, content_type, version)
);

CREATE INDEX IF NOT EXISTS idx_documents_topic_layer ON documents (topic_key, layer);
