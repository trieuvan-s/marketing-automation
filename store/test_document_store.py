"""Test store/document_store.py -- dùng file SQLite TẠM (pytest tmp_path),
KHÔNG phải sqlite3.connect(":memory:") literal: document_store.py mở 1
connection MỚI mỗi lần gọi (_connect() context manager, đóng ngay sau mỗi
thao tác) -- ":memory:" của sqlite3 tạo 1 DB RIÊNG BIỆT cho MỖI connection
(không share giữa các lần gọi), nên dùng thẳng ":memory:" sẽ khiến
write_document() và read_latest() thấy 2 DB rỗng khác nhau, không round-trip
được. tmp_path (file thật trên đĩa tạm, pytest tự dọn) đạt đúng tinh thần
"cô lập, nhanh, không đụng DB thật" mà "in-memory" hướng tới, chỉ khác cơ
chế lưu trữ vật lý.

`content_type` (BUG 1, 2026-07-19): read_latest()/read_history() giờ BẮT
BUỘC tham số content_type -- test dưới truyền "" cho layer không có đa loại
(raw/brief/infographic/video), giá trị thật cho content_output."""
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
    assert ds.read_latest("topic-1", "raw", "", db_path=db_path) == {"a": 1}


def test_version_auto_increments_per_topic_and_layer(db_path):
    ds.write_document("topic-1", "brief", {"n": 1}, "ma", db_path=db_path)
    v2 = ds.write_document("topic-1", "brief", {"n": 2}, "ma", db_path=db_path)
    assert v2 == 2
    assert ds.read_latest("topic-1", "brief", "", db_path=db_path) == {"n": 2}
    # layer khác -> version đếm riêng, không lẫn
    v_other_layer = ds.write_document("topic-1", "raw", {"m": 1}, "ma", db_path=db_path)
    assert v_other_layer == 1


def test_unique_constraint_blocks_duplicate_version_insert(db_path):
    ds.write_document("topic-1", "raw", {"a": 1}, "ma", db_path=db_path)
    with sqlite3.connect(str(db_path)) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO documents (topic_key, layer, content_type, version, payload_json, created_at, written_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("topic-1", "raw", "", 1, "{}", "2026-01-01T00:00:00+00:00", "ma"),
            )


def test_check_constraint_blocks_aigen_writing_content_output(db_path):
    with pytest.raises(sqlite3.IntegrityError):
        ds.write_document("topic-1", "content_output", {}, "aigen", content_type="article", db_path=db_path)


def test_check_constraint_blocks_ma_writing_video(db_path):
    with pytest.raises(sqlite3.IntegrityError):
        ds.write_document("topic-1", "video", {}, "ma", db_path=db_path)


def test_check_constraint_allows_aigen_writing_video(db_path):
    v = ds.write_document("topic-1", "video", {"script": "x"}, "aigen", db_path=db_path)
    assert v == 1


def test_check_constraint_allows_ma_writing_all_four_non_video_layers(db_path):
    for layer in ("raw", "brief", "infographic"):
        v = ds.write_document("topic-1", layer, {"layer": layer}, "ma", db_path=db_path)
        assert v == 1
    v_content_output = ds.write_document(
        "topic-1", "content_output", {"layer": "content_output"}, "ma", content_type="article", db_path=db_path
    )
    assert v_content_output == 1


def test_read_history_returns_all_versions_in_ascending_order(db_path):
    ds.write_document("topic-1", "raw", {"n": 1}, "ma", db_path=db_path)
    ds.write_document("topic-1", "raw", {"n": 2}, "ma", db_path=db_path)
    ds.write_document("topic-1", "raw", {"n": 3}, "ma", db_path=db_path)
    hist = ds.read_history("topic-1", "raw", "", db_path=db_path)
    assert [v for v, _, _ in hist] == [1, 2, 3]
    assert [p for _, p, _ in hist] == [{"n": 1}, {"n": 2}, {"n": 3}]
    # created_at phải là chuỗi ISO khác rỗng
    assert all(isinstance(c, str) and c for _, _, c in hist)


def test_read_latest_returns_none_when_no_document_written(db_path):
    assert ds.read_latest("khong-ton-tai", "raw", "", db_path=db_path) is None


def test_read_history_returns_empty_list_when_no_document_written(db_path):
    assert ds.read_history("khong-ton-tai", "raw", "", db_path=db_path) == []


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
    assert ds.read_latest("t1", "raw", "", db_path=db_path) == {"ok": True}


# --- BUG 1 (2026-07-19): content_type trong khoá UNIQUE ---------------------

def test_content_output_requires_content_type_raises_value_error(db_path):
    with pytest.raises(ValueError):
        ds.write_document("t1", "content_output", {"x": 1}, "ma", db_path=db_path)  # thiếu content_type


def test_multiple_content_types_same_topic_key_all_readable_independently(db_path):
    """Đúng ca thật tìm thấy trên Sheet: 1 topic_key có 3 content_type
    (article/infographic/video) trong layer content_output -- BUG 1 cũ sẽ
    khiến 2 trong 3 bị "chôn". Sau khi sửa: cả 3 đọc lại độc lập, không cái
    nào bị mất."""
    ds.write_document("t1", "content_output", {"body": "bai viet"}, "ma", content_type="article", db_path=db_path)
    ds.write_document("t1", "content_output", {"spec": "infographic spec"}, "ma", content_type="infographic", db_path=db_path)
    ds.write_document("t1", "content_output", {"scenes": []}, "ma", content_type="video", db_path=db_path)

    assert ds.read_latest("t1", "content_output", "article", db_path=db_path) == {"body": "bai viet"}
    assert ds.read_latest("t1", "content_output", "infographic", db_path=db_path) == {"spec": "infographic spec"}
    assert ds.read_latest("t1", "content_output", "video", db_path=db_path) == {"scenes": []}


def test_version_counter_independent_per_content_type(db_path):
    """version của 'article' và 'video' đếm RIÊNG -- không lẫn số dù cùng
    topic_key+layer (đây chính xác là điều BUG 1 làm SAI trước khi sửa)."""
    v1 = ds.write_document("t1", "content_output", {"n": 1}, "ma", content_type="article", db_path=db_path)
    v2 = ds.write_document("t1", "content_output", {"n": 2}, "ma", content_type="article", db_path=db_path)
    v_video = ds.write_document("t1", "content_output", {"n": 1}, "ma", content_type="video", db_path=db_path)
    assert (v1, v2, v_video) == (1, 2, 1)
    hist_article = ds.read_history("t1", "content_output", "article", db_path=db_path)
    assert [v for v, _, _ in hist_article] == [1, 2]
    hist_video = ds.read_history("t1", "content_output", "video", db_path=db_path)
    assert [v for v, _, _ in hist_video] == [1]


def test_unique_constraint_now_includes_content_type(db_path):
    """Cùng topic_key+layer+version nhưng KHÁC content_type -- PHẢI được
    phép (đây chính là điều BUG 1 sửa: trước kia UNIQUE(topic_key,layer,
    version) sẽ chặn nhầm ca này)."""
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "INSERT INTO documents (topic_key, layer, content_type, version, payload_json, created_at, written_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("t1", "content_output", "article", 1, "{}", "2026-01-01T00:00:00+00:00", "ma"),
        )
        # KHÔNG raise -- content_type khác, version=1 trùng nhưng khoá đủ khác
        conn.execute(
            "INSERT INTO documents (topic_key, layer, content_type, version, payload_json, created_at, written_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("t1", "content_output", "video", 1, "{}", "2026-01-01T00:00:00+00:00", "ma"),
        )
        conn.commit()


# --- P2 store-as-truth (2026-07-23) -- layer gate_status/content_status ----

def test_gate_status_write_and_read_round_trip(db_path):
    """gate_status: content_type='' (TOPIC-level, giống raw/brief) -- không
    BẮT BUỘC content_type như content_output/content_status."""
    v = ds.write_document(
        "t1", "gate_status", {"gate1": "APPROVE", "execute": "RUN", "output_type": ["infographic"]},
        "ma", db_path=db_path,
    )
    assert v == 1
    assert ds.read_latest("t1", "gate_status", "", db_path=db_path) == {
        "gate1": "APPROVE", "execute": "RUN", "output_type": ["infographic"],
    }


def test_content_status_requires_content_type(db_path):
    """content_status CÙNG NẾP content_output -- thiếu content_type -> lỗi
    SỚM (ValueError), không âm thầm nhận '' rồi tái diễn BUG 1."""
    with pytest.raises(ValueError, match="content_status.*BẮT BUỘC content_type"):
        ds.write_document("t1", "content_status", {"gate2": "APPROVE"}, "ma", db_path=db_path)


def test_content_status_write_and_read_round_trip(db_path):
    v = ds.write_document(
        "t1", "content_status",
        {"gate2": "APPROVE", "gate3": "PENDING", "asset_url": "https://drive.google.com/x"},
        "ma", content_type="infographic", db_path=db_path,
    )
    assert v == 1
    payload = ds.read_latest("t1", "content_status", "infographic", db_path=db_path)
    assert payload["gate2"] == "APPROVE"
    assert payload["asset_url"] == "https://drive.google.com/x"


def test_gate_status_version_increments_on_repeated_writes(db_path):
    """gate_status đổi liên tục (mỗi lần user bấm duyệt) -- version phải tự
    tăng bình thường như mọi layer khác, không đặc cách."""
    v1 = ds.write_document("t1", "gate_status", {"gate1": "PENDING"}, "ma", db_path=db_path)
    v2 = ds.write_document("t1", "gate_status", {"gate1": "APPROVE"}, "ma", db_path=db_path)
    assert (v1, v2) == (1, 2)
    assert ds.read_latest("t1", "gate_status", "", db_path=db_path) == {"gate1": "APPROVE"}


def test_content_status_version_counter_independent_per_content_type(db_path):
    v1 = ds.write_document("t1", "content_status", {"gate2": "PENDING"}, "ma",
                           content_type="infographic", db_path=db_path)
    v2 = ds.write_document("t1", "content_status", {"gate2": "APPROVE"}, "ma",
                           content_type="infographic", db_path=db_path)
    v_video = ds.write_document("t1", "content_status", {"gate2": "PENDING"}, "ma",
                                content_type="video", db_path=db_path)
    assert (v1, v2, v_video) == (1, 2, 1)


def test_check_constraint_blocks_aigen_writing_gate_status(db_path):
    with pytest.raises(sqlite3.IntegrityError):
        ds.write_document("t1", "gate_status", {}, "aigen", db_path=db_path)


def test_check_constraint_blocks_aigen_writing_content_status(db_path):
    with pytest.raises(sqlite3.IntegrityError):
        ds.write_document("t1", "content_status", {}, "aigen", content_type="video", db_path=db_path)


def test_write_document_rejects_empty_topic_key(db_path):
    """P2 store-as-truth (2026-07-23) -- schema CHỈ có NOT NULL (chặn None),
    KHÔNG chặn chuỗi rỗng '' (xác nhận thực nghiệm: write_document('', ...)
    từng ghi thành công TRƯỚC guard này). Đây là test THAY cho
    test_run_content_row_missing_topic_key_marks_needs_human_no_production đã
    xoá ở produce_from_sheet -- INVARIANT "không document mồ côi" giờ enforce ở
    ĐÂY (tầng store, chặn TẠI NGUỒN) thay vì phòng thủ ở tầng pipeline."""
    with pytest.raises(ValueError, match="topic_key rỗng"):
        ds.write_document("", "raw", {"a": 1}, "ma", db_path=db_path)


def test_write_document_rejects_none_topic_key(db_path):
    with pytest.raises(ValueError, match="topic_key rỗng"):
        ds.write_document(None, "raw", {"a": 1}, "ma", db_path=db_path)
