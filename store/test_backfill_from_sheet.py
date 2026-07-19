"""Test store/backfill_from_sheet.py::analyze() -- dữ liệu GIẢ, KHÔNG cần
Sheet thật (analyze() là hàm THUẦN, tách riêng khỏi read_sheet_rows() đúng
mục đích test được không cần mạng). read_sheet_rows()/write_to_temp_store()
KHÔNG test ở đây -- cần Sheet/gspread thật, đã verify bằng tay ở STOP-REPORT."""
from store.backfill_from_sheet import analyze, _rows_as_dicts


def test_rows_as_dicts_maps_header_to_values():
    values = [["A", "B"], ["1", "2"]]
    assert _rows_as_dicts(values) == [{"A": "1", "B": "2"}]


def test_rows_as_dicts_pads_short_rows():
    values = [["A", "B", "C"], ["1"]]
    assert _rows_as_dicts(values) == [{"A": "1", "B": "", "C": ""}]


def test_rows_as_dicts_empty_values_returns_empty_list():
    assert _rows_as_dicts([]) == []


def _context_row(topic_key="tk1", **overrides):
    row = {"Topic": "t", "Context": "c", "Hook": "h", "Source": "s", "tickers": "PNJ", "TopicKey": topic_key}
    row.update(overrides)
    return row


def _content_row(topic_key="tk1", content_type="article", output="output text", facts="", asset_path="", **overrides):
    row = {"Type": content_type, "Output": output, "Facts": facts, "AssetPath": asset_path, "TopicKey": topic_key}
    row.update(overrides)
    return row


def test_analyze_maps_context_row_to_raw_layer():
    report = analyze([_context_row("tk1")], [])
    assert report["raw"] == [("tk1", {"Topic": "t", "Context": "c", "Hook": "h", "Source": "s", "tickers": "PNJ"})]


def test_analyze_maps_content_output_to_content_output_layer():
    report = analyze([], [_content_row("tk1", output="bai viet that")])
    assert report["content_output"] == [("tk1", {"type": "article", "output": "bai viet that"})]


def test_analyze_maps_facts_json_to_brief_layer():
    report = analyze([], [_content_row("tk1", facts='{"n": 1}')])
    assert report["brief"] == [("tk1", {"facts": {"n": 1}})]


def test_analyze_invalid_facts_json_recorded_as_parse_error_not_crash():
    report = analyze([], [_content_row("tk1", facts="{khong phai json}")])
    assert report["brief"] == []
    assert report["brief_json_parse_errors"] == ["tk1"]


def test_analyze_maps_asset_path_to_infographic_layer():
    report = analyze([], [_content_row("tk1", content_type="infographic", asset_path="path/to.svg")])
    assert report["infographic"] == [("tk1", {"type": "infographic", "asset_path": "path/to.svg"})]


def test_analyze_video_layer_always_empty_no_sheet_source():
    report = analyze([_context_row()], [_content_row()])
    assert report["video"] == []


def test_analyze_counts_empty_topic_key_separately_for_context_and_content():
    report = analyze([_context_row(topic_key="")], [_content_row(topic_key="")])
    assert report["context_empty_topic_key"] == 1
    assert report["content_empty_topic_key"] == 1
    assert report["raw"] == []
    assert report["content_output"] == []


def test_analyze_detects_duplicate_topic_key_in_context():
    report = analyze([_context_row("tk1"), _context_row("tk1")], [])
    assert report["context_duplicate_topic_key"] == ["tk1"]


def test_analyze_no_duplicate_when_topic_keys_all_unique():
    report = analyze([_context_row("tk1"), _context_row("tk2")], [])
    assert report["context_duplicate_topic_key"] == []


def test_analyze_detects_multiple_types_sharing_same_topic_key():
    """Đúng phát hiện quan trọng nhất tìm thấy trên Sheet thật: 1 topic_key
    có nhiều Type (article/video/infographic) -- register nhưng KHÔNG tự
    quyết định đúng/sai, chỉ đếm."""
    rows = [
        _content_row("tk1", content_type="article"),
        _content_row("tk1", content_type="video"),
        _content_row("tk1", content_type="infographic"),
    ]
    report = analyze([], rows)
    assert report["content_topic_key_types"]["tk1"] == {"article", "video", "infographic"}


def test_analyze_content_type_counts_tally_correctly():
    rows = [_content_row("tk1", content_type="article"), _content_row("tk2", content_type="article"),
            _content_row("tk3", content_type="video")]
    report = analyze([], rows)
    assert report["content_type_counts"]["article"] == 2
    assert report["content_type_counts"]["video"] == 1
