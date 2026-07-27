"""P2 STORE-AS-TRUTH -- PHASE QUEUE (2026-07-27, theo chỉ đạo Lead) -- hàng
đợi request thực thi (`execution_queue`, xem schema.sql). CÙNG file DB với
`document_store.py`/`pipeline_store.py` nhưng module RIÊNG: bảng này CÓ
UPDATE (chuyển trạng thái job tại chỗ), khác hẳn tinh thần append-only của
`documents` -- tách module để không ai nhầm tưởng `write_document()` cũng
dùng được cho đây.

VÌ SAO CẦN HÀNG ĐỢI (không chỉ cờ `gate_status.execute` như trước): cờ
Execute không có claim/lease (không đánh dấu "ai đang xử lý", "từ lúc nào")
và không có thứ tự FIFO thật (`document_store.list_topics()` sắp theo
topic_key/hash). Bảng này giải quyết ĐÚNG 2 khoảng trống đó, KHÔNG thay thế
`gate_status.execute` -- cột đó VẪN là nguồn hiển thị Sheet (DONE/FAILED/
NEEDS_HUMAN do `produce_from_sheet.py::run()` tự ghi, không đổi). Hàng đợi là
khái niệm KHÁC: "đã dispatch xử lý topic này chưa", không phải "kết quả
nghiệp vụ ra sao" -- 2 khái niệm khác nhau, không phải 2 nguồn sự thật cho
CÙNG 1 trạng thái.

ATOMICITY: `claim_next()`/`enqueue()`/`release_stale_claims()` dùng
`BEGIN IMMEDIATE` tường minh (isolation_level=None -- tự quản transaction,
KHÔNG dựa transaction ngầm mặc định của sqlite3) để an toàn khi NHIỀU worker
cùng gọi (dù phiên này chỉ chạy đúng 1 worker, xem scripts/queue_worker.py) --
khác `document_store.write_document()` (SELECT MAX rồi INSERT rời, chấp nhận
race hiếm vì giả định 1-nguồn-ghi); ở đây atomic thật vì bản chất "claim 1
job, đúng 1 worker được nhận" cần đảm bảo mạnh hơn "ghi version mới"."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

_VALID_STATUSES = frozenset({"queued", "claimed", "done", "failed"})


def _default_db_path() -> Path:
    """Trùng logic `document_store._default_db_path()` (cùng ENV
    `DOCUMENT_STORE_PATH`, cùng file DB) -- lặp lại 2 dòng ở đây thay vì
    import hàm private xuyên module, tránh phụ thuộc vào tên có gạch dưới
    của module khác."""
    raw = os.environ.get("DOCUMENT_STORE_PATH", "store/document_store.db")
    return Path(raw)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connect(db_path: str | Path | None = None):
    path = Path(db_path) if db_path is not None else _default_db_path()
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def find_pending(topic_key: str, *, job_type: str = "produce",
                 db_path: str | Path | None = None) -> dict | None:
    """Job 'queued'/'claimed' HIỆN CÓ cho topic_key+job_type này (nếu có) --
    dùng bởi caller cần PHÂN BIỆT "vừa enqueue job mới" với "đã có job đang
    chờ/đang chạy" (vd `api/main.py::webhook_execute()` trả 409 thay vì 202
    cho ca double-fire) TRƯỚC KHI gọi `enqueue()` (bản thân `enqueue()` vẫn
    tự dedup atomic, hàm này chỉ phục vụ QUYẾT ĐỊNH của caller, không thay
    thế lưới an toàn atomic trong `enqueue()`)."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM execution_queue WHERE topic_key = ? AND job_type = ? "
            "AND status IN ('queued', 'claimed') LIMIT 1",
            (topic_key, job_type),
        ).fetchone()
    return dict(row) if row is not None else None


def enqueue(topic_key: str, *, job_type: str = "produce", payload: dict | None = None,
           db_path: str | Path | None = None) -> int:
    """Thêm 1 job MỚI, trạng thái 'queued'. CHẶN double-enqueue: nếu
    topic_key+job_type ĐÃ có job 'queued'/'claimed', KHÔNG chèn thêm -- trả
    id job đã có (idempotent, để Gate1 đổi qua lại nhiều lần hay
    `ingest_context_from_sheet()`/webhook gọi lặp không dồn nhiều job trùng
    cho cùng 1 chủ đề)."""
    if not topic_key:
        raise ValueError("topic_key rỗng/None -- KHÔNG được phép enqueue.")
    payload_json = json.dumps(payload or {}, ensure_ascii=False)
    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing = conn.execute(
                "SELECT id FROM execution_queue WHERE topic_key = ? AND job_type = ? "
                "AND status IN ('queued', 'claimed') LIMIT 1",
                (topic_key, job_type),
            ).fetchone()
            if existing is not None:
                conn.execute("COMMIT")
                return existing["id"]
            cur = conn.execute(
                "INSERT INTO execution_queue (topic_key, job_type, status, requested_at, payload_json) "
                "VALUES (?, ?, 'queued', ?, ?)",
                (topic_key, job_type, _now(), payload_json),
            )
            job_id = cur.lastrowid
            conn.execute("COMMIT")
            return job_id
        except BaseException:
            conn.execute("ROLLBACK")
            raise


def claim_next(worker_id: str, *, job_type: str | None = None,
              db_path: str | Path | None = None) -> dict | None:
    """Lấy job 'queued' CŨ NHẤT (FIFO thật theo `id`, khác thứ tự hash của
    `document_store.list_topics()`) và chuyển 'claimed' ATOMIC trong 1
    transaction -- `None` nếu hàng đợi rỗng (không job nào khớp `job_type`).
    An toàn cho nhiều worker gọi đồng thời: chỉ đúng 1 lệnh gọi nhận được job
    đó, các lệnh gọi khác thấy hàng đợi đã trống/job khác."""
    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if job_type is not None:
                row = conn.execute(
                    "SELECT id, topic_key, job_type, payload_json, attempt_count FROM execution_queue "
                    "WHERE status = 'queued' AND job_type = ? ORDER BY id LIMIT 1",
                    (job_type,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT id, topic_key, job_type, payload_json, attempt_count FROM execution_queue "
                    "WHERE status = 'queued' ORDER BY id LIMIT 1"
                ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            now = _now()
            conn.execute(
                "UPDATE execution_queue SET status = 'claimed', claimed_at = ?, claimed_by = ? WHERE id = ?",
                (now, worker_id, row["id"]),
            )
            conn.execute("COMMIT")
            return {
                "id": row["id"], "topic_key": row["topic_key"], "job_type": row["job_type"],
                "payload": json.loads(row["payload_json"]), "attempt_count": row["attempt_count"],
                "claimed_at": now, "claimed_by": worker_id,
            }
        except BaseException:
            conn.execute("ROLLBACK")
            raise


def mark_done(job_id: int, *, db_path: str | Path | None = None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE execution_queue SET status = 'done', finished_at = ? WHERE id = ?",
            (_now(), job_id),
        )


def mark_failed(job_id: int, error: str, *, db_path: str | Path | None = None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE execution_queue SET status = 'failed', finished_at = ?, error = ? WHERE id = ?",
            (_now(), str(error), job_id),
        )


def release_stale_claims(lease_timeout_s: float, *, max_attempts: int = 3,
                         db_path: str | Path | None = None) -> int:
    """Job 'claimed' quá `lease_timeout_s` giây (worker chết giữa chừng --
    rủi ro C8 đã ghi nhận ở docs/VPS_MIGRATION_BACKLOG.md, "Execute kẹt RUN
    vĩnh viễn") -- dưới `max_attempts` lần thử -> đưa về 'queued' (tự thử
    lại); đạt/vượt `max_attempts` -> 'failed' hẳn (tránh vòng lặp vô hạn cho
    1 job luôn crash). Trả số job vừa xử lý (0 nếu không có job nào kẹt)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=lease_timeout_s)).isoformat()
    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            stale = conn.execute(
                "SELECT id, attempt_count FROM execution_queue "
                "WHERE status = 'claimed' AND claimed_at < ?",
                (cutoff,),
            ).fetchall()
            for row in stale:
                if row["attempt_count"] + 1 >= max_attempts:
                    conn.execute(
                        "UPDATE execution_queue SET status = 'failed', finished_at = ?, "
                        "attempt_count = attempt_count + 1, error = ? WHERE id = ?",
                        (_now(), f"lease timeout sau {max_attempts} lần thử", row["id"]),
                    )
                else:
                    conn.execute(
                        "UPDATE execution_queue SET status = 'queued', claimed_at = NULL, "
                        "claimed_by = NULL, attempt_count = attempt_count + 1 WHERE id = ?",
                        (row["id"],),
                    )
            conn.execute("COMMIT")
            return len(stale)
        except BaseException:
            conn.execute("ROLLBACK")
            raise


def list_queue(*, status: str | None = None, db_path: str | Path | None = None) -> list[dict]:
    """Quan sát/debug -- toàn bộ job (hoặc lọc theo `status`), sắp theo `id`
    (thứ tự enqueue thật)."""
    with _connect(db_path) as conn:
        if status is not None:
            rows = conn.execute(
                "SELECT * FROM execution_queue WHERE status = ? ORDER BY id", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM execution_queue ORDER BY id").fetchall()
    return [dict(r) for r in rows]
