"""Test api/main.py -- mock hoàn toàn, KHÔNG mạng thật, KHÔNG gọi
pipeline_bridge.run_pipeline() thật (đã monkeypatch)."""
import os

import pytest
from fastapi.testclient import TestClient

import api.main as webhook_main


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """Mỗi test bắt đầu sạch: token cố định + registry rỗng -- tránh test
    trước rò trạng thái sang test sau."""
    monkeypatch.setenv("WEBHOOK_TOKEN", "test-token-123")
    webhook_main._running.clear()
    yield
    webhook_main._running.clear()


@pytest.fixture()
def client():
    return TestClient(webhook_main.app)


def test_health_returns_200(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_execute_wrong_token_returns_401(client):
    resp = client.post("/webhook/execute", json={"topic_key": "t1", "token": "sai-token"})
    assert resp.status_code == 401


def test_execute_missing_env_token_returns_401(client, monkeypatch):
    monkeypatch.delenv("WEBHOOK_TOKEN", raising=False)
    resp = client.post("/webhook/execute", json={"topic_key": "t1", "token": "bat-ky-gi"})
    assert resp.status_code == 401


def test_execute_valid_request_returns_202(client, monkeypatch):
    called = []

    async def _fake_run_pipeline(topic_key):
        called.append(topic_key)
        return "DONE"

    monkeypatch.setattr(webhook_main, "run_pipeline", _fake_run_pipeline)

    resp = client.post("/webhook/execute", json={"topic_key": "t1", "token": "test-token-123"})
    assert resp.status_code == 202
    assert resp.json() == {"accepted": True, "topic_key": "t1"}
    # TestClient chạy background task đồng bộ trước khi __exit__ -- với
    # "with" context (dùng ngầm trong .post khi không mở context riêng),
    # background task đã kịp chạy xong tại đây.
    assert called == ["t1"]


def test_execute_duplicate_topic_key_returns_409(client):
    with webhook_main._lock:
        webhook_main._running.add("t-dang-chay")

    resp = client.post("/webhook/execute", json={"topic_key": "t-dang-chay", "token": "test-token-123"})
    assert resp.status_code == 409


def test_status_reports_running_true_when_in_registry(client):
    with webhook_main._lock:
        webhook_main._running.add("t-dang-chay")
    resp = client.get("/status/t-dang-chay")
    assert resp.status_code == 200
    assert resp.json() == {"topic_key": "t-dang-chay", "running": True}


def test_status_reports_running_false_when_not_in_registry(client):
    resp = client.get("/status/t-khong-ton-tai")
    assert resp.status_code == 200
    assert resp.json() == {"topic_key": "t-khong-ton-tai", "running": False}


def test_process_removes_topic_key_from_registry_after_failure(client, monkeypatch):
    """run_pipeline raise -> report_result("FAILED") + registry PHẢI được
    dọn (finally), không kẹt "đang chạy" mãi mãi."""
    async def _fake_run_pipeline_raises(topic_key):
        raise RuntimeError("lỗi giả lập")

    monkeypatch.setattr(webhook_main, "run_pipeline", _fake_run_pipeline_raises)

    resp = client.post("/webhook/execute", json={"topic_key": "t2", "token": "test-token-123"})
    assert resp.status_code == 202
    assert "t2" not in webhook_main._running
