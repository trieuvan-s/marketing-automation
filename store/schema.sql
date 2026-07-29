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
    -- CHECK length(topic_key) > 0 (2026-07-24, theo chỉ đạo Lead) -- NOT NULL
    -- một mình CHỈ chặn SQL NULL, KHÔNG chặn chuỗi rỗng "" (xác nhận thực
    -- nghiệm: write_document("", ...) từng ghi thành công trước khi có CHECK
    -- này VÀ trước guard Python ở document_store.py::write_document()).
    -- Guard Python vẫn giữ nguyên (raise ValueError SỚM, thông báo rõ hơn
    -- IntegrityError chung chung) -- CHECK này là LƯỚI AN TOÀN CUỐI ở tầng
    -- DB, phòng đường ghi nào đó (vd sync service Bước 3, tương lai) bỏ sót
    -- guard Python. KHÔNG migrate dữ liệu hiện có -- store trống ở nấc này
    -- (P2 chưa có dữ liệu thật, xem Bước 5.2 "clear sạch, khởi tạo lại từ
    -- schema"), constraint tự có hiệu lực từ lần init_db() kế tiếp.
    topic_key     TEXT NOT NULL CHECK (length(topic_key) > 0),
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

-- PHASE QUEUE (2026-07-27, theo chỉ đạo Lead) -- hàng đợi request thực thi,
-- BẢNG RIÊNG khỏi `documents` (khác bản chất: đây là bookkeeping VẬN HÀNH
-- dispatch 1 job, không phải lịch sử nội dung cần audit-theo-version --
-- CÓ UPDATE (chuyển trạng thái job tại chỗ), KHÔNG giống `documents`
-- append-only. Vẫn giữ kỷ luật KHÔNG DELETE -- job done/failed giữ lại để
-- xem lại lịch sử xử lý, xem store/queue_store.py). `id` tự tăng cho thứ tự
-- FIFO THẬT (khác `documents`: list_topics() ở đó sắp theo topic_key/hash,
-- không theo thời gian -- hàng đợi này mới thật sự có thứ tự đến trước-xử-
-- trước). `job_type` mặc định 'produce' (đường run() LLM trực tiếp, ĐANG
-- dùng thật) -- để hở cho loại job tương lai, KHÔNG tự thêm loại nào bây giờ.
CREATE TABLE IF NOT EXISTS execution_queue (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_key     TEXT NOT NULL CHECK (length(topic_key) > 0),
    job_type      TEXT NOT NULL DEFAULT 'produce',
    -- queued -> claimed (worker đã lấy, xem queue_store.claim_next()) ->
    -- done | failed. release_stale_claims() đưa claimed quá hạn (worker chết
    -- giữa chừng -- rủi ro C8 đã ghi nhận ở VPS_MIGRATION_BACKLOG.md) VỀ LẠI
    -- queued (thử lại) hoặc failed hẳn (vượt max_attempts).
    -- 'cancelled' THÊM 2026-07-28: người rút yêu cầu (bỏ APPROVE, đổi Output
    -- Type) trước khi worker kịp claim -> job KHÔNG được chạy nữa. KHÁC
    -- 'failed' (đã chạy và hỏng) — gộp 2 thứ này lại là mất khả năng phân biệt
    -- "hệ thống lỗi" với "người đổi ý", đúng thứ cần khi truy vết sau này.
    status        TEXT NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued', 'claimed', 'done', 'failed', 'cancelled')),
    requested_at  TEXT NOT NULL,
    claimed_at    TEXT,
    claimed_by    TEXT,
    finished_at   TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    payload_json  TEXT NOT NULL DEFAULT '{}',
    -- REQUEST ID (2026-07-28) — định danh 1 YÊU CẦU của người, khác `id` (=
    -- Queue ID, định danh 1 lượt dispatch). 1 request có thể sinh nhiều job
    -- (produce rồi render_assets). Đổi Output Type = HUỶ request cũ + tạo
    -- request MỚI: nhờ vậy phân biệt được "job của yêu cầu đã bị rút" với
    -- "job của yêu cầu hiện hành", thứ mà chỉ topic_key không nói được.
    request_id    TEXT
);

CREATE INDEX IF NOT EXISTS idx_queue_status_id ON execution_queue (status, id);
