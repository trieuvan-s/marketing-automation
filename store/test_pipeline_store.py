"""Test store/pipeline_store.py -- lớp nghiệp vụ giữa produce_from_sheet.py
và document_store.py. Cùng fixture db_path (file SQLite tạm) như
test_document_store.py -- xem docstring file đó cho lý do KHÔNG dùng
":memory:" literal."""
import pytest

from store import document_store as ds
from store import pipeline_store as ps


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "test.db"
    ds.init_db(path)
    return path


def test_write_raw_and_read_raw_round_trip(db_path):
    ps.write_raw("topic-1", {"context": "abc", "hook": "h", "source": "s",
                              "tickers": ["FPT"], "group": "g", "topic": "t"}, db_path=db_path)
    assert ps.read_raw("topic-1", db_path=db_path)["context"] == "abc"


def test_write_gate_status_merges_fields_not_overwrites(db_path):
    ps.write_gate_status("topic-1", gate1="APPROVE", db_path=db_path)
    ps.write_gate_status("topic-1", execute="RUN", db_path=db_path)
    status = ps.read_gate_status("topic-1", db_path=db_path)
    assert status["gate1"] == "APPROVE"
    assert status["execute"] == "RUN"


def test_write_gate_status_output_type_list_preserved(db_path):
    ps.write_gate_status("topic-1", output_type=["infographic", "video"], db_path=db_path)
    assert ps.read_gate_status("topic-1", db_path=db_path)["output_type"] == ["infographic", "video"]


def test_mark_execute_done_only_changes_execute_field(db_path):
    ps.write_gate_status("topic-1", gate1="APPROVE", output_type=["article"], db_path=db_path)
    ps.mark_execute_done("topic-1", db_path=db_path)
    status = ps.read_gate_status("topic-1", db_path=db_path)
    assert status["execute"] == "DONE"
    assert status["gate1"] == "APPROVE"
    assert status["output_type"] == ["article"]


def test_read_gate_status_returns_empty_dict_when_never_written(db_path):
    assert ps.read_gate_status("nope", db_path=db_path) == {}


def test_list_approved_topics_filters_gate1_and_execute(db_path):
    ps.write_raw("t-approved-run", {"context": "c1"}, db_path=db_path)
    ps.write_gate_status("t-approved-run", gate1="APPROVE", execute="RUN", db_path=db_path)

    ps.write_raw("t-approved-failed", {"context": "c2"}, db_path=db_path)
    ps.write_gate_status("t-approved-failed", gate1="APPROVE", execute="FAILED", db_path=db_path)

    ps.write_raw("t-approved-done", {"context": "c3"}, db_path=db_path)
    ps.write_gate_status("t-approved-done", gate1="APPROVE", execute="DONE", db_path=db_path)

    ps.write_raw("t-not-approved", {"context": "c4"}, db_path=db_path)
    ps.write_gate_status("t-not-approved", gate1="PENDING", execute="RUN", db_path=db_path)

    topics = {t["topic_key"] for t in ps.list_approved_topics(db_path=db_path)}
    assert topics == {"t-approved-run", "t-approved-failed"}


def test_list_approved_topics_includes_raw_fields(db_path):
    ps.write_raw("topic-1", {"context": "ctx", "hook": "hk", "source": "src",
                              "tickers": ["FPT"], "group": "grp", "topic": "top"}, db_path=db_path)
    ps.write_gate_status("topic-1", gate1="APPROVE", execute="RUN", db_path=db_path)
    result = ps.list_approved_topics(db_path=db_path)[0]
    assert result["context"] == "ctx"
    assert result["hook"] == "hk"
    assert result["source"] == "src"
    assert result["tickers"] == ["FPT"]
    assert result["group"] == "grp"
    assert result["topic"] == "top"


def test_existing_content_keys(db_path):
    ps.write_content_output("topic-1", "article", {"body": "a"}, db_path=db_path)
    ps.write_content_output("topic-1", "infographic", {"body": "b"}, db_path=db_path)
    ps.write_content_output("topic-2", "video", {"body": "c"}, db_path=db_path)
    keys = ps.existing_content_keys(db_path=db_path)
    assert keys == {("topic-1", "article"), ("topic-1", "infographic"), ("topic-2", "video")}


def test_write_content_status_merges_fields_per_content_type(db_path):
    ps.write_content_status("topic-1", "infographic", gate2="APPROVE", db_path=db_path)
    ps.write_content_status("topic-1", "infographic", asset_url="https://drive/x", db_path=db_path)
    ps.write_content_status("topic-1", "video", gate2="PENDING", db_path=db_path)

    infographic_status = ps.read_content_status("topic-1", "infographic", db_path=db_path)
    assert infographic_status["gate2"] == "APPROVE"
    assert infographic_status["asset_url"] == "https://drive/x"

    video_status = ps.read_content_status("topic-1", "video", db_path=db_path)
    assert video_status["gate2"] == "PENDING"
    assert "asset_url" not in video_status


def test_read_content_status_returns_empty_dict_when_never_written(db_path):
    assert ps.read_content_status("topic-1", "article", db_path=db_path) == {}


def test_write_log_and_read_log_history_round_trip(db_path):
    ps.write_log("INFO", "LLM active: MOCK", engine="mock", db_path=db_path)
    ps.write_log("WARN", "full-fetch rỗng", db_path=db_path)
    history = ps.read_log_history(db_path=db_path)
    assert [h[1]["message"] for h in history] == ["LLM active: MOCK", "full-fetch rỗng"]
    assert history[0][1]["level"] == "INFO" and history[0][1]["engine"] == "mock"
    assert history[1][1]["level"] == "WARN" and history[1][1]["engine"] == ""


def test_write_log_never_overwrites_previous_entries(db_path):
    for i in range(3):
        ps.write_log("INFO", f"event {i}", db_path=db_path)
    assert len(ps.read_log_history(db_path=db_path)) == 3
