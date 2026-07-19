-- SQLite Document Store (docs/VPS_MIGRATION_BACKLOG.md A6/A7 -- "Sheet CHỈ
-- LÀ UI/view; mọi dữ liệu neo TopicKey trong store"). APPEND-ONLY: không
-- UPDATE, không DELETE ở tầng ứng dụng (document_store.py không có hàm nào
-- làm 2 việc đó) -- mỗi lần ghi = version mới. Lý do: sự cố migrate_rows()
-- từng XOÁ RỖNG dữ liệu thật trên Sheet (xem "QUY TẮC VÀNG KHI ĐỘNG VÀO
-- SHEET" trong docs/VPS_MIGRATION_BACKLOG.md) -- thiết kế này loại bỏ hẳn
-- khả năng tái diễn vì schema không có đường nào để UPDATE/DELETE.

CREATE TABLE IF NOT EXISTS documents (
    id            INTEGER PRIMARY KEY,
    topic_key     TEXT NOT NULL,
    layer         TEXT NOT NULL CHECK (layer IN ('raw', 'brief', 'content_output', 'infographic', 'video')),
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
    UNIQUE (topic_key, layer, version)
);

CREATE INDEX IF NOT EXISTS idx_documents_topic_layer ON documents (topic_key, layer);
