"""SQLite Document Store (docs/VPS_MIGRATION_BACKLOG.md A6/A7) -- nền cho
"Sheet CHỈ LÀ UI/view; mọi dữ liệu (evidence, facts, output mọi format,
trạng thái từng Gate, asset path, lịch sử) neo TopicKey trong store".

APPEND-ONLY: module này KHÔNG có hàm update/delete nào -- mỗi lần ghi luôn
là 1 version MỚI (xem `write_document()`). Lý do ghi vào đây (không chỉ
comment SQL): sự cố `migrate_rows()` từng XOÁ RỖNG dữ liệu Gate 1 thật trên
Sheet khi đổi tên cột (xem docs/VPS_MIGRATION_BACKLOG.md "QUY TẮC VÀNG KHI
ĐỘNG VÀO SHEET") -- thiết kế append-only loại bỏ hẳn khả năng tái diễn ở
tầng store này, vì không tồn tại thao tác nào có thể xoá/ghi đè.

Quyền ghi tách bạch ENFORCE Ở SCHEMA (CHECK constraint trong schema.sql),
KHÔNG dựa kỷ luật code Python -- ghi sai layer cho written_by sẽ luôn raise
`sqlite3.IntegrityError` dù code gọi có kiểm tra trước hay không.

CHƯA NỐI vào pipeline/Sheet ở nấc này (docs/VPS_MIGRATION_BACKLOG.md A6 ghi
rõ: "LÀM SAU khi luồng thông" -- Sheet HIỆN vẫn đang là database, TUYỆT ĐỐI
không dùng module này để thay Sheet cho tới khi có bước backfill riêng).
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

_VALID_LAYERS = frozenset({"raw", "brief", "content_output", "infographic", "video"})
_VALID_WRITERS = frozenset({"ma", "aigen"})


def _default_db_path() -> Path:
    """Đường dẫn DB đọc từ ENV `DOCUMENT_STORE_PATH` -- KHÔNG hardcode,
    cùng bài học A5 (đường dẫn hardcode `aigen-fva-capital` gãy khi đổi
    máy -- xem docs/VPS_MIGRATION_BACKLOG.md A5). Mặc định
    "store/document_store.db" TƯƠNG ĐỐI theo CWD lúc chạy nếu ENV không
    set -- chỉ hợp lý cho dev/test cục bộ, triển khai thật PHẢI set ENV
    tường minh."""
    raw = os.environ.get("DOCUMENT_STORE_PATH", "store/document_store.db")
    return Path(raw)


def init_db(db_path: str | Path | None = None) -> None:
    """Tạo file DB + bảng (nếu chưa có) -- idempotent, gọi lại nhiều lần
    an toàn (schema.sql dùng `CREATE TABLE IF NOT EXISTS`)."""
    path = Path(db_path) if db_path is not None else _default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    with sqlite3.connect(str(path)) as conn:
        conn.executescript(schema_sql)


@contextmanager
def _connect(db_path: str | Path | None = None):
    path = Path(db_path) if db_path is not None else _default_db_path()
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def write_document(
    topic_key: str,
    layer: str,
    payload: dict,
    written_by: str,
    *,
    content_type: str = "",
    db_path: str | Path | None = None,
) -> int:
    """Ghi 1 bản MỚI (APPEND-ONLY, không ghi đè) -> trả version vừa ghi
    (bắt đầu từ 1, tự tăng theo `topic_key`+`layer`+`content_type`).

    `content_type` (BUG 1, phát hiện qua backfill --dry-run trên Sheet thật
    2026-07-19): 1 topic_key có thể có NHIỀU content_type trong layer
    'content_output' (vd article/infographic/video CÙNG 1 chủ đề, xác nhận
    thật trên Sheet -- KHÔNG phải giả thuyết). Bỏ qua tham số này (mặc định
    "") -> mọi content_type cùng topic_key+layer bị coi là version của CÙNG
    1 tài liệu, "chôn" mất các content_type khác khi đọc lại. BẮT BUỘC
    truyền `content_type` thật (khớp CONTENT.Type trên Sheet -- xem BUG 2:
    "article"/"infographic"/"video", ĐÃ xác nhận đối chiếu ký tự-với-ký tự
    với dữ liệu thật) khi `layer="content_output"` -- raise `ValueError`
    SỚM nếu thiếu, không âm thầm nhận "" rồi gây bug y hệt BUG 1 lần nữa.
    Layer khác (raw/brief/infographic/video) không có đa loại -- để mặc
    định "" là đúng, không cần truyền.

    `payload` PHẢI JSON-serializable -- lỗi serialize raise `TypeError` từ
    `json.dumps()`, không tự bắt/nuốt ở đây. `layer`/`written_by` sai giá
    trị -> `ValueError` (kiểm SỚM, thông báo rõ, tránh round-trip DB vô
    ích). `written_by` ghi SAI layer cho phép của nó (theo CHECK constraint
    trong schema.sql, vd 'aigen' ghi 'content_output') -> để SQLite tự
    raise `sqlite3.IntegrityError`, KHÔNG tự kiểm tra lại logic đó ở Python
    (schema là nguồn sự thật DUY NHẤT cho quyền ghi, tránh 2 nơi có thể
    lệch nhau).

    Race hiếm (2 tiến trình ghi CÙNG topic_key+layer+content_type cùng lúc,
    cả 2 cùng tính ra 1 version): UNIQUE(topic_key, layer, content_type,
    version) trong schema.sql là lưới an toàn cuối -- 1 trong 2 sẽ nhận
    `sqlite3.IntegrityError` thay vì âm thầm ghi đè, đúng tinh thần
    append-only. Ở nấc này (VPS 1 nguồn ghi/layer theo thiết kế A6) race
    này không nên xảy ra trong vận hành bình thường."""
    if layer not in _VALID_LAYERS:
        raise ValueError(f"layer không hợp lệ: {layer!r} (phải trong {sorted(_VALID_LAYERS)})")
    if written_by not in _VALID_WRITERS:
        raise ValueError(f"written_by không hợp lệ: {written_by!r} (phải trong {sorted(_VALID_WRITERS)})")
    if layer == "content_output" and not content_type:
        raise ValueError(
            "layer='content_output' BẮT BUỘC content_type (vd 'article'/'infographic'/'video') "
            "-- 1 topic_key có thể có nhiều content_type, thiếu tham số này sẽ tái diễn BUG 1 "
            "(content_type khác nhau bị coi là version của cùng 1 tài liệu, chôn mất nhau)."
        )

    payload_json = json.dumps(payload, ensure_ascii=False)
    created_at = datetime.now(timezone.utc).isoformat()

    with _connect(db_path) as conn:
        cur = conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM documents "
            "WHERE topic_key = ? AND layer = ? AND content_type = ?",
            (topic_key, layer, content_type),
        )
        next_version = cur.fetchone()[0] + 1
        conn.execute(
            "INSERT INTO documents (topic_key, layer, content_type, version, payload_json, created_at, written_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (topic_key, layer, content_type, next_version, payload_json, created_at, written_by),
        )
        conn.commit()
        return next_version


def read_latest(
    topic_key: str, layer: str, content_type: str, *, db_path: str | Path | None = None
) -> dict | None:
    """Bản MỚI NHẤT (version cao nhất) của ĐÚNG `content_type` -- `None`
    nếu chưa từng ghi. `content_type` BẮT BUỘC (không mặc định) kể từ BUG 1
    -- truyền `""` cho layer không có đa loại (raw/brief/infographic/video),
    truyền giá trị thật ('article'/'infographic'/'video') cho
    layer='content_output'. Không có tham số này thì không có cách nào phân
    biệt "muốn đọc bản nào trong số nhiều content_type cùng topic_key"."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT payload_json FROM documents "
            "WHERE topic_key = ? AND layer = ? AND content_type = ? "
            "ORDER BY version DESC LIMIT 1",
            (topic_key, layer, content_type),
        ).fetchone()
    return json.loads(row["payload_json"]) if row else None


def read_history(
    topic_key: str, layer: str, content_type: str, *, db_path: str | Path | None = None
) -> list[tuple[int, dict, str]]:
    """Toàn bộ lịch sử (version, payload, created_at) của ĐÚNG `content_type`,
    sắp XUÔI theo version (1, 2, 3, ...) -- danh sách rỗng nếu chưa từng ghi
    (KHÔNG raise). `content_type` BẮT BUỘC, cùng lý do `read_latest()`."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT version, payload_json, created_at FROM documents "
            "WHERE topic_key = ? AND layer = ? AND content_type = ? ORDER BY version ASC",
            (topic_key, layer, content_type),
        ).fetchall()
    return [(r["version"], json.loads(r["payload_json"]), r["created_at"]) for r in rows]


def list_topics(layer: str | None = None, *, db_path: str | Path | None = None) -> list[str]:
    """`topic_key` DISTINCT, sắp xếp theo bảng chữ cái -- lọc theo `layer`
    nếu truyền, không thì trả mọi topic_key có ít nhất 1 bản ghi ở BẤT KỲ
    layer nào."""
    with _connect(db_path) as conn:
        if layer is not None:
            rows = conn.execute(
                "SELECT DISTINCT topic_key FROM documents WHERE layer = ? ORDER BY topic_key",
                (layer,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT topic_key FROM documents ORDER BY topic_key"
            ).fetchall()
    return [r["topic_key"] for r in rows]
