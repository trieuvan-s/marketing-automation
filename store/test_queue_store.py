"""Test store/queue_store.py -- SQLite thật (tmp_path), KHÔNG mock -- bảng
`execution_queue` là bookkeeping vận hành thật, atomic qua BEGIN IMMEDIATE
(khác `document_store.write_document()` chấp nhận race hiếm). Chạy cùng bộ
`python -m pytest` hoặc riêng `python -m pytest store/test_queue_store.py`."""
import os
import sys
from datetime import datetime, timedelta, timezone

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

import pytest

from store import document_store as ds
from store import queue_store as qs


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "test.db"
    ds.init_db(path)
    return path


def test_enqueue_returns_new_job_id(db_path):
    job_id = qs.enqueue("tk-1", db_path=db_path)
    assert job_id == 1
    rows = qs.list_queue(db_path=db_path)
    assert len(rows) == 1
    assert rows[0]["topic_key"] == "tk-1"
    assert rows[0]["job_type"] == "produce"
    assert rows[0]["status"] == "queued"
    assert rows[0]["payload_json"] == "{}"


def test_enqueue_dedupes_when_already_queued_or_claimed(db_path):
    """Đúng chủ đề gọi enqueue nhiều lần (Gate1 đổi qua lại/webhook gọi lặp)
    -- KHÔNG dồn nhiều job trùng, trả lại id job đã có."""
    id1 = qs.enqueue("tk-1", db_path=db_path)
    id2 = qs.enqueue("tk-1", db_path=db_path)
    assert id1 == id2
    assert len(qs.list_queue(db_path=db_path)) == 1

    # Vẫn dedupe khi job đã 'claimed' (chưa done/failed).
    qs.claim_next("worker-a", db_path=db_path)
    id3 = qs.enqueue("tk-1", db_path=db_path)
    assert id3 == id1
    assert len(qs.list_queue(db_path=db_path)) == 1


def test_enqueue_allows_new_job_after_previous_one_finished(db_path):
    """Job CŨ đã done/failed -- KHÔNG chặn enqueue job MỚI cho cùng topic_key
    (khác dedup 'đang chờ/đang chạy', đây là 'đã xong, muốn chạy lại')."""
    id1 = qs.enqueue("tk-1", db_path=db_path)
    qs.mark_done(id1, db_path=db_path)
    id2 = qs.enqueue("tk-1", db_path=db_path)
    assert id2 != id1
    assert len(qs.list_queue(db_path=db_path)) == 2


def test_enqueue_different_topics_and_job_types_are_independent(db_path):
    id1 = qs.enqueue("tk-1", job_type="produce", db_path=db_path)
    id2 = qs.enqueue("tk-1", job_type="render", db_path=db_path)
    id3 = qs.enqueue("tk-2", job_type="produce", db_path=db_path)
    assert len({id1, id2, id3}) == 3


def test_enqueue_rejects_empty_topic_key(db_path):
    with pytest.raises(ValueError):
        qs.enqueue("", db_path=db_path)


def test_find_pending_returns_none_when_no_job(db_path):
    assert qs.find_pending("tk-khong-ton-tai", db_path=db_path) is None


def test_find_pending_returns_job_only_while_queued_or_claimed(db_path):
    job_id = qs.enqueue("tk-1", db_path=db_path)
    pending = qs.find_pending("tk-1", db_path=db_path)
    assert pending is not None and pending["id"] == job_id

    qs.claim_next("worker-a", db_path=db_path)
    still_pending = qs.find_pending("tk-1", db_path=db_path)
    assert still_pending is not None and still_pending["status"] == "claimed"

    qs.mark_done(job_id, db_path=db_path)
    assert qs.find_pending("tk-1", db_path=db_path) is None


def test_claim_next_fifo_order_by_id_not_alphabetical(db_path):
    """FIFO THẬT theo thứ tự enqueue (`id`), KHÔNG theo bảng chữ cái topic_key
    (khác `document_store.list_topics()` -- xem docstring module)."""
    qs.enqueue("tk-z", db_path=db_path)   # id 1, enqueue TRƯỚC dù tên "z"
    qs.enqueue("tk-a", db_path=db_path)   # id 2, enqueue SAU dù tên "a"

    job1 = qs.claim_next("worker-a", db_path=db_path)
    job2 = qs.claim_next("worker-a", db_path=db_path)
    assert job1["topic_key"] == "tk-z"
    assert job2["topic_key"] == "tk-a"


def test_claim_next_returns_none_when_queue_empty(db_path):
    assert qs.claim_next("worker-a", db_path=db_path) is None


def test_claim_next_filters_by_job_type(db_path):
    qs.enqueue("tk-1", job_type="render", db_path=db_path)
    render_first = qs.enqueue("tk-2", job_type="produce", db_path=db_path)
    job = qs.claim_next("worker-a", job_type="produce", db_path=db_path)
    assert job["id"] == render_first and job["topic_key"] == "tk-2"


def test_claim_next_is_atomic_across_two_connections(db_path):
    """Mô phỏng 2 worker gọi claim_next() 'đồng thời' trên CÙNG job -- BEGIN
    IMMEDIATE phải đảm bảo chỉ ĐÚNG 1 bên nhận được job, không có chuyện cả
    2 cùng claim thành công (đây là lý do chọn transaction tường minh thay vì
    kiểu SELECT-rồi-UPDATE rời của document_store.write_document())."""
    qs.enqueue("tk-1", db_path=db_path)

    job_a = qs.claim_next("worker-a", db_path=db_path)
    job_b = qs.claim_next("worker-b", db_path=db_path)   # chạy SAU (transaction A đã COMMIT)

    assert job_a is not None and job_b is None   # chỉ 1 bên nhận được job
    rows = qs.list_queue(db_path=db_path)
    assert rows[0]["status"] == "claimed" and rows[0]["claimed_by"] == "worker-a"


def test_mark_done_sets_status_and_finished_at(db_path):
    job_id = qs.enqueue("tk-1", db_path=db_path)
    qs.claim_next("worker-a", db_path=db_path)
    qs.mark_done(job_id, db_path=db_path)
    row = qs.list_queue(db_path=db_path)[0]
    assert row["status"] == "done"
    assert row["finished_at"] is not None


def test_mark_failed_sets_status_and_error(db_path):
    job_id = qs.enqueue("tk-1", db_path=db_path)
    qs.claim_next("worker-a", db_path=db_path)
    qs.mark_failed(job_id, "boom", db_path=db_path)
    row = qs.list_queue(db_path=db_path)[0]
    assert row["status"] == "failed"
    assert row["error"] == "boom"
    assert row["finished_at"] is not None


def _age_claim(db_path, job_id: int, seconds_ago: float) -> None:
    """Helper CHỈ dùng trong test -- lùi `claimed_at` để mô phỏng lease hết
    hạn (worker chết giữa chừng), không có API công khai nào cho việc này."""
    import sqlite3
    old_ts = (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE execution_queue SET claimed_at = ? WHERE id = ?", (old_ts, job_id))
    conn.commit()
    conn.close()


def test_release_stale_claims_requeues_job_under_max_attempts(db_path):
    job_id = qs.enqueue("tk-1", db_path=db_path)
    qs.claim_next("worker-a", db_path=db_path)
    _age_claim(db_path, job_id, seconds_ago=9999)

    released = qs.release_stale_claims(600, max_attempts=3, db_path=db_path)
    assert released == 1
    row = qs.list_queue(db_path=db_path)[0]
    assert row["status"] == "queued"
    assert row["claimed_at"] is None and row["claimed_by"] is None
    assert row["attempt_count"] == 1


def test_release_stale_claims_marks_failed_after_max_attempts(db_path):
    """VIỆC C8 (docs/VPS_MIGRATION_BACKLOG.md): job cứ claim-rồi-kẹt lặp lại
    PHẢI dừng hẳn sau `max_attempts`, không vòng lặp vô hạn."""
    job_id = qs.enqueue("tk-1", db_path=db_path)
    for _ in range(3):
        qs.claim_next("worker-a", db_path=db_path)
        _age_claim(db_path, job_id, seconds_ago=9999)
        qs.release_stale_claims(600, max_attempts=3, db_path=db_path)

    row = qs.list_queue(db_path=db_path)[0]
    assert row["status"] == "failed"
    assert row["attempt_count"] == 3
    assert "lease timeout" in row["error"]


def test_release_stale_claims_ignores_fresh_claims(db_path):
    qs.enqueue("tk-1", db_path=db_path)
    qs.claim_next("worker-a", db_path=db_path)   # claimed_at = vừa xong, chưa hết hạn
    released = qs.release_stale_claims(600, max_attempts=3, db_path=db_path)
    assert released == 0
    assert qs.list_queue(db_path=db_path)[0]["status"] == "claimed"


def test_list_queue_filters_by_status(db_path):
    id1 = qs.enqueue("tk-1", db_path=db_path)
    qs.enqueue("tk-2", db_path=db_path)
    qs.mark_done(id1, db_path=db_path)

    done_rows = qs.list_queue(status="done", db_path=db_path)
    queued_rows = qs.list_queue(status="queued", db_path=db_path)
    assert [r["topic_key"] for r in done_rows] == ["tk-1"]
    assert [r["topic_key"] for r in queued_rows] == ["tk-2"]
