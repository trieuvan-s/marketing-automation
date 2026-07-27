"""Test api/main.py -- PHASE QUEUE (2026-07-27): webhook giờ ENQUEUE vào
`store/queue_store.py` (SQLite tmp thật, KHÔNG mock) thay vì đọc/ghi Sheet
trực tiếp + registry in-memory cũ. KHÔNG mạng thật, KHÔNG chạm Sheet."""
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import pytest
from fastapi.testclient import TestClient

from store import document_store as ds
from store import queue_store as qs

import api.main as webhook_main


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch, tmp_path):
    """Mỗi test bắt đầu sạch: token cố định + store hàng đợi RIÊNG (tmp SQLite,
    isolate hoàn toàn khỏi store thật)."""
    monkeypatch.setenv("WEBHOOK_TOKEN", "test-token-123")
    db_path = tmp_path / "test.db"
    ds.init_db(db_path)
    monkeypatch.setenv("DOCUMENT_STORE_PATH", str(db_path))
    yield db_path


@pytest.fixture()
def client():
    return TestClient(webhook_main.app)


def test_health_returns_200(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# --- token ---------------------------------------------------------------
def test_execute_wrong_token_returns_401(client):
    resp = client.post("/webhook/execute", json={"topic_key": "t1", "token": "sai-token"})
    assert resp.status_code == 401


def test_execute_missing_env_token_returns_401(client, monkeypatch):
    monkeypatch.delenv("WEBHOOK_TOKEN", raising=False)
    resp = client.post("/webhook/execute", json={"topic_key": "t1", "token": "bat-ky-gi"})
    assert resp.status_code == 401


def test_execute_wrong_token_checked_before_enqueue(client, _reset_state):
    """Token sai -> 401 NGAY, KHÔNG enqueue gì vào hàng đợi."""
    resp = client.post("/webhook/execute", json={"topic_key": "t1", "token": "sai"})
    assert resp.status_code == 401
    assert qs.list_queue(db_path=_reset_state) == []


# --- enqueue thành công -> 202 --------------------------------------------
def test_execute_valid_request_returns_202_and_enqueues_job(client, _reset_state):
    resp = client.post("/webhook/execute", json={"topic_key": "t1", "token": "test-token-123"})
    assert resp.status_code == 202
    body = resp.json()
    assert body["accepted"] is True
    assert body["topic_key"] == "t1"
    assert isinstance(body["job_id"], int)

    rows = qs.list_queue(db_path=_reset_state)
    assert len(rows) == 1
    assert rows[0]["topic_key"] == "t1"
    assert rows[0]["job_type"] == "produce"
    assert rows[0]["status"] == "queued"


# --- double-fire -> 409 (nguồn sự thật DUY NHẤT giờ là execution_queue) ---
def test_execute_duplicate_while_queued_returns_409(client, _reset_state):
    first = client.post("/webhook/execute", json={"topic_key": "t-dup", "token": "test-token-123"})
    assert first.status_code == 202

    second = client.post("/webhook/execute", json={"topic_key": "t-dup", "token": "test-token-123"})
    assert second.status_code == 409
    assert "hàng đợi" in second.json()["detail"]
    # KHÔNG dồn thêm job trùng.
    assert len(qs.list_queue(db_path=_reset_state)) == 1


def test_execute_duplicate_while_claimed_returns_409(client, _reset_state):
    """Job ĐÃ được worker claim (đang xử lý, chưa done/failed) -- vẫn PHẢI
    chặn double-fire, không chỉ lúc còn 'queued'."""
    resp = client.post("/webhook/execute", json={"topic_key": "t-claimed", "token": "test-token-123"})
    job_id = resp.json()["job_id"]
    qs.claim_next("worker-a", db_path=_reset_state)

    dup = client.post("/webhook/execute", json={"topic_key": "t-claimed", "token": "test-token-123"})
    assert dup.status_code == 409
    assert f"#{job_id}" in dup.json()["detail"]


def test_execute_allows_new_request_after_previous_job_finished(client, _reset_state):
    """Job CŨ đã done -- request MỚI cho CÙNG topic_key vẫn phải được chấp
    nhận (khác ca double-fire, đây là 'đã xong, muốn chạy lại')."""
    first = client.post("/webhook/execute", json={"topic_key": "t1", "token": "test-token-123"})
    qs.mark_done(first.json()["job_id"], db_path=_reset_state)

    second = client.post("/webhook/execute", json={"topic_key": "t1", "token": "test-token-123"})
    assert second.status_code == 202
    assert second.json()["job_id"] != first.json()["job_id"]


# --- /status ---------------------------------------------------------------
def test_status_reflects_queued_job(client, _reset_state):
    resp = client.post("/webhook/execute", json={"topic_key": "t-xong", "token": "test-token-123"})
    job_id = resp.json()["job_id"]

    status_resp = client.get("/status/t-xong")
    assert status_resp.status_code == 200
    assert status_resp.json() == {"topic_key": "t-xong", "status": "queued", "job_id": job_id}


def test_status_reflects_done_job(client, _reset_state):
    resp = client.post("/webhook/execute", json={"topic_key": "t-xong", "token": "test-token-123"})
    job_id = resp.json()["job_id"]
    qs.mark_done(job_id, db_path=_reset_state)

    status_resp = client.get("/status/t-xong")
    assert status_resp.json() == {"topic_key": "t-xong", "status": "done", "job_id": job_id}


def test_status_none_when_topic_never_requested(client):
    resp = client.get("/status/t-khong-ton-tai")
    assert resp.status_code == 200
    assert resp.json() == {"topic_key": "t-khong-ton-tai", "status": None, "job_id": None}
