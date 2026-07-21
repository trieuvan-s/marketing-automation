"""Test api/main.py -- mock hoàn toàn: KHÔNG mạng thật, KHÔNG gọi
pipeline_bridge.run_pipeline() thật, KHÔNG chạm Sheet thật
(`_read_topic_context` luôn được monkeypatch — xem fixture `_reset_state`).

VIỆC 5.5/5.6: thứ tự kiểm của POST /webhook/execute là
token(401) -> Sheet Execute=RUN(409) -> chưa duyệt(400) -> registry(409) -> 202.
`run()` là NƠI DUY NHẤT ghi Execute; webhook chỉ đọc lại (GET /status)."""
import pytest
from fastapi.testclient import TestClient

import api.main as webhook_main


def _ctx(execute: str = "", topic_key: str = "t1") -> dict:
    """1 dòng CONTEXT giả — hình dạng như `read_approved_context()` trả về
    (đã lọc Status=APPROVE)."""
    return {"context": "Bài test", "hook": "", "source": "", "tickers": [],
            "group": "", "topic": "", "execute": execute, "row": 2,
            "topic_key": topic_key}


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """Mỗi test bắt đầu sạch: token cố định + registry rỗng + Sheet giả
    (topic ĐÃ duyệt, Execute rỗng = hợp lệ để fire). Test cần trạng thái khác
    thì tự monkeypatch lại `_read_topic_context`."""
    monkeypatch.setenv("WEBHOOK_TOKEN", "test-token-123")
    webhook_main._running.clear()
    monkeypatch.setattr(webhook_main, "_read_topic_context", lambda tk: _ctx(topic_key=tk))
    yield
    webhook_main._running.clear()


@pytest.fixture()
def client():
    return TestClient(webhook_main.app)


def test_health_returns_200(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# --- 5.6 ca 1: token ---------------------------------------------------
def test_execute_wrong_token_returns_401(client):
    resp = client.post("/webhook/execute", json={"topic_key": "t1", "token": "sai-token"})
    assert resp.status_code == 401


def test_execute_missing_env_token_returns_401(client, monkeypatch):
    monkeypatch.delenv("WEBHOOK_TOKEN", raising=False)
    resp = client.post("/webhook/execute", json={"topic_key": "t1", "token": "bat-ky-gi"})
    assert resp.status_code == 401


def test_execute_wrong_token_checked_before_sheet_read(client, monkeypatch):
    """Token sai -> 401 NGAY, KHÔNG đọc Sheet (thứ tự 5.5: token trước)."""
    reads: list[str] = []
    monkeypatch.setattr(webhook_main, "_read_topic_context",
                        lambda tk: reads.append(tk) or _ctx(topic_key=tk))
    resp = client.post("/webhook/execute", json={"topic_key": "t1", "token": "sai"})
    assert resp.status_code == 401
    assert reads == []


# --- 5.6 ca 2: chưa duyệt -> 400 --------------------------------------
def test_execute_topic_not_approved_returns_400(client, monkeypatch):
    """Không có dòng CONTEXT Status=APPROVE mang topic_key -> 400 (kiểm phía
    SERVER, không tin client: request có thể đến từ nơi khác qua tunnel)."""
    monkeypatch.setattr(webhook_main, "_read_topic_context", lambda tk: None)
    resp = client.post("/webhook/execute", json={"topic_key": "t-chua-duyet", "token": "test-token-123"})
    assert resp.status_code == 400
    assert "chưa duyệt" in resp.json()["detail"]


# --- 5.6 ca 3: đang RUN trên Sheet -> 409 ------------------------------
def test_execute_sheet_execute_run_returns_409(client, monkeypatch):
    """Execute=RUN trên Sheet -> 409. Webhook KHÔNG tự đặt cờ (run() lo)."""
    monkeypatch.setattr(webhook_main, "_read_topic_context", lambda tk: _ctx("RUN", tk))
    resp = client.post("/webhook/execute", json={"topic_key": "t-run", "token": "test-token-123"})
    assert resp.status_code == 409
    assert "RUN" in resp.json()["detail"]


# --- 5.6 ca 4: DONE / NEEDS_HUMAN -> 409 (idempotent) ------------------
@pytest.mark.parametrize("execute", ["DONE", "NEEDS_HUMAN"])
def test_execute_already_done_or_needs_human_returns_409(client, monkeypatch, execute):
    monkeypatch.setattr(webhook_main, "_read_topic_context", lambda tk: _ctx(execute, tk))
    resp = client.post("/webhook/execute", json={"topic_key": "t-x", "token": "test-token-123"})
    assert resp.status_code == 409


# --- 5.6 ca 5: hợp lệ -> 202 + chạy pipeline ---------------------------
@pytest.mark.parametrize("execute", ["", "FAILED"])
def test_execute_fireable_returns_202_and_runs_pipeline(client, monkeypatch, execute):
    """Execute rỗng (chưa chạy) hoặc FAILED (lỗi tạm, tái chạy được) -> 202."""
    called: list[str] = []

    async def _fake_run_pipeline(topic_key):
        called.append(topic_key)
        return "{'approved': 1}"

    monkeypatch.setattr(webhook_main, "_read_topic_context", lambda tk: _ctx(execute, tk))
    monkeypatch.setattr(webhook_main, "run_pipeline", _fake_run_pipeline)

    resp = client.post("/webhook/execute", json={"topic_key": "t1", "token": "test-token-123"})
    assert resp.status_code == 202
    assert resp.json() == {"accepted": True, "topic_key": "t1"}
    # TestClient chạy background task đồng bộ trước khi trả -> đã kịp chạy.
    assert called == ["t1"]


# --- 5.6 ca 6: registry in-memory -> 409 -------------------------------
def test_execute_duplicate_topic_key_returns_409(client):
    """Lưới NHANH cùng tiến trình: chặn khoảng hở trước khi run() kịp đặt
    Execute=RUN trên Sheet (Sheet vẫn báo fireable)."""
    with webhook_main._lock:
        webhook_main._running.add("t-dang-chay")

    resp = client.post("/webhook/execute", json={"topic_key": "t-dang-chay", "token": "test-token-123"})
    assert resp.status_code == 409
    assert "registry" in resp.json()["detail"]


# --- 5.6 ca 7: /status ĐỌC Execute từ Sheet ----------------------------
def test_status_reads_execute_from_sheet(client, monkeypatch):
    """5.4: /status trả trạng thái THẬT (cờ Execute), đây là nơi client biết
    kết quả sau khi POST trả 202."""
    monkeypatch.setattr(webhook_main, "_read_topic_context", lambda tk: _ctx("DONE", tk))
    resp = client.get("/status/t-xong")
    assert resp.status_code == 200
    assert resp.json() == {"topic_key": "t-xong", "execute": "DONE", "running": False}


def test_status_execute_none_when_topic_not_found(client, monkeypatch):
    monkeypatch.setattr(webhook_main, "_read_topic_context", lambda tk: None)
    resp = client.get("/status/t-khong-ton-tai")
    assert resp.status_code == 200
    assert resp.json() == {"topic_key": "t-khong-ton-tai", "execute": None, "running": False}


def test_status_reports_running_true_when_in_registry(client, monkeypatch):
    monkeypatch.setattr(webhook_main, "_read_topic_context", lambda tk: _ctx("RUN", tk))
    with webhook_main._lock:
        webhook_main._running.add("t-dang-chay")
    resp = client.get("/status/t-dang-chay")
    assert resp.status_code == 200
    assert resp.json() == {"topic_key": "t-dang-chay", "execute": "RUN", "running": True}


# --- dọn registry khi pipeline lỗi -------------------------------------
def test_process_removes_topic_key_from_registry_after_failure(client, monkeypatch):
    """run_pipeline raise -> report_result("FAILED") (CHỈ LOG, không ghi Sheet)
    + registry PHẢI được dọn (finally), không kẹt "đang chạy" mãi mãi."""
    async def _fake_run_pipeline_raises(topic_key):
        raise RuntimeError("lỗi giả lập")

    monkeypatch.setattr(webhook_main, "run_pipeline", _fake_run_pipeline_raises)

    resp = client.post("/webhook/execute", json={"topic_key": "t2", "token": "test-token-123"})
    assert resp.status_code == 202
    assert "t2" not in webhook_main._running


def test_report_result_does_not_write_sheet(monkeypatch):
    """5.3: report_result CHỈ LOG. Bảo đảm KHÔNG có đường ghi Sheet nào ở đây
    (run() là nơi duy nhất ghi Execute — không tạo nguồn trạng thái thứ hai)."""
    import inspect
    src = inspect.getsource(webhook_main.report_result)
    for forbidden in ("set_execute", "update_cell", "append_row", "_open_board",
                      "ensure_tabs", "migrate_rows", "SheetsBoard"):
        assert forbidden not in src, f"report_result KHÔNG được ghi/mở Sheet: thấy {forbidden!r}"
