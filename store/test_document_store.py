"""Test store/document_store.py -- dùng file SQLite TẠM (pytest tmp_path),
KHÔNG phải sqlite3.connect(":memory:") literal: document_store.py mở 1
connection MỚI mỗi lần gọi (_connect() context manager, đóng ngay sau mỗi
thao tác) -- ":memory:" của sqlite3 tạo 1 DB RIÊNG BIỆT cho MỖI connection
(không share giữa các lần gọi), nên dùng thẳng ":memory:" sẽ khiến
write_document() và read_latest() thấy 2 DB rỗng khác nhau, không round-trip
được. tmp_path (file thật trên đĩa tạm, pytest tự dọn) đạt đúng tinh thần
"cô lập, nhanh, không đụng DB thật" mà "in-memory" hướng tới, chỉ khác cơ
chế lưu trữ vật lý."""
import sqlite3

import pytest

from store import document_store as ds


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "test.db"
    ds.init_db(path)
    return path


def test_write_and_read_latest_round_trip(db_path):
    v = ds.write_document("topic-1", "raw", {"a": 1}, "ma", db_path=db_path)
    assert v == 1
    assert ds.read_latest("topic-1", "raw", db_path=db_path) == {"a": 1}


def test_version_auto_increments_per_topic_and_layer(db_path):
    ds.write_document("topic-1", "brief", {"n": 1}, "ma", db_path=db_path)
    v2 = ds.write_document("topic-1", "brief", {"n": 2}, "ma", db_path=db_path)
    assert v2 == 2
    assert ds.read_latest("topic-1", "brief", db_path=db_path) == {"n": 2}
    # layer khác -> version đếm riêng, không lẫn
    v_other_layer = ds.write_document("topic-1", "raw", {"m": 1}, "ma", db_path=db_path)
    assert v_other_layer == 1


def test_unique_constraint_blocks_duplicate_version_insert(db_path):
    ds.write_document("topic-1", "raw", {"a": 1}, "ma", db_path=db_path)
    with sqlite3.connect(str(db_path)) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO documents (topic_key, layer, version, payload_json, created_at, written_by) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("topic-1", "raw", 1, "{}", "2026-01-01T00:00:00+00:00", "ma"),
            )


def test_check_constraint_blocks_aigen_writing_content_output(db_path):
    with pytest.raises(sqlite3.IntegrityError):
        ds.write_document("topic-1", "content_output", {}, "aigen", db_path=db_path)


def test_check_constraint_blocks_ma_writing_video(db_path):
    with pytest.raises(sqlite3.IntegrityError):
        ds.write_document("topic-1", "video", {}, "ma", db_path=db_path)


def test_check_constraint_allows_aigen_writing_video(db_path):
    v = ds.write_document("topic-1", "video", {"script": "x"}, "aigen", db_path=db_path)
    assert v == 1


def test_check_constraint_allows_ma_writing_all_four_non_video_layers(db_path):
    for layer in ("raw", "brief", "content_output", "infographic"):
        v = ds.write_document("topic-1", layer, {"layer": layer}, "ma", db_path=db_path)
        assert v == 1


def test_read_history_returns_all_versions_in_ascending_order(db_path):
    ds.write_document("topic-1", "raw", {"n": 1}, "ma", db_path=db_path)
    ds.write_document("topic-1", "raw", {"n": 2}, "ma", db_path=db_path)
    ds.write_document("topic-1", "raw", {"n": 3}, "ma", db_path=db_path)
    hist = ds.read_history("topic-1", "raw", db_path=db_path)
    assert [v for v, _, _ in hist] == [1, 2, 3]
    assert [p for _, p, _ in hist] == [{"n": 1}, {"n": 2}, {"n": 3}]
    # created_at phải là chuỗi ISO khác rỗng
    assert all(isinstance(c, str) and c for _, _, c in hist)


def test_read_latest_returns_none_when_no_document_written(db_path):
    assert ds.read_latest("khong-ton-tai", "raw", db_path=db_path) is None


def test_read_history_returns_empty_list_when_no_document_written(db_path):
    assert ds.read_history("khong-ton-tai", "raw", db_path=db_path) == []


def test_list_topics_filters_by_layer(db_path):
    ds.write_document("t1", "raw", {}, "ma", db_path=db_path)
    ds.write_document("t2", "brief", {}, "ma", db_path=db_path)
    assert ds.list_topics(layer="raw", db_path=db_path) == ["t1"]
    assert ds.list_topics(layer="brief", db_path=db_path) == ["t2"]


def test_list_topics_without_layer_returns_all_distinct_topics(db_path):
    ds.write_document("t1", "raw", {}, "ma", db_path=db_path)
    ds.write_document("t2", "brief", {}, "ma", db_path=db_path)
    ds.write_document("t1", "brief", {}, "ma", db_path=db_path)  # cùng t1, layer khác
    assert ds.list_topics(db_path=db_path) == ["t1", "t2"]


def test_invalid_layer_raises_value_error_before_touching_db(db_path):
    with pytest.raises(ValueError):
        ds.write_document("t1", "not-a-real-layer", {}, "ma", db_path=db_path)


def test_invalid_written_by_raises_value_error(db_path):
    with pytest.raises(ValueError):
        ds.write_document("t1", "raw", {}, "khong-phai-ma-hay-aigen", db_path=db_path)


def test_payload_not_json_serializable_raises_type_error(db_path):
    with pytest.raises(TypeError):
        ds.write_document("t1", "raw", {"x": object()}, "ma", db_path=db_path)


def test_init_db_is_idempotent(db_path):
    ds.init_db(db_path)  # gọi lại lần 2, không được raise
    ds.write_document("t1", "raw", {"ok": True}, "ma", db_path=db_path)
    assert ds.read_latest("t1", "raw", db_path=db_path) == {"ok": True}
