"""Xác thực schema Document Store (`store/schema.sql`) bằng DỮ LIỆU THẬT trên
Google Sheet — TRƯỚC khi dual-write thật (docs/VPS_MIGRATION_BACKLOG.md A6/A7).

⚠️ CHỈ ĐỌC SHEET. TUYỆT ĐỐI KHÔNG GHI, KHÔNG đổi cấu trúc, KHÔNG gọi
`SheetsBoard.ensure_tabs()`/`migrate_rows()` (2 hàm này tự chạy khi mở board
bình thường qua `_open_board()` và TỪNG XOÁ RỖNG dữ liệu Gate 1 thật khi đổi
tên cột — xem docs/VPS_MIGRATION_BACKLOG.md "QUY TẮC VÀNG KHI ĐỘNG VÀO
SHEET"). Module này dựng `SheetsBoard` TRỰC TIẾP (KHÔNG qua `_open_board()`)
rồi đọc `get_all_values()` thẳng từ gspread — đường đọc RẺ NHẤT, không chạm
bất kỳ code path ghi/format nào.

2 chế độ:
    python -m store.backfill_from_sheet              # --dry-run (mặc định)
    python -m store.backfill_from_sheet --write       # ghi vào DB TẠM (KHÔNG
                                                        # phải store thật)

KHÔNG tự sửa schema theo phát hiện của script này — chỉ báo cáo, chờ Lead
quyết định (xem "Điểm ma sát" cuối output).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from twmkt.config import load_settings  # noqa: E402
from twmkt.sheets_board import SheetsBoard  # noqa: E402
from store import document_store as ds  # noqa: E402

# --- Ánh xạ cột Sheet -> layer, THIẾT KẾ (không phải đã xác nhận với Lead) --
# raw:            CONTEXT — dữ liệu crawl/curation THÔ, TRƯỚC Composer.
# brief:           CONTENT.Facts — facts[] JSON snapshot (output của Brief).
# content_output:  CONTENT.Output — SPEC/text Composer sinh ra (mọi Type).
# infographic:     CONTENT.AssetPath — đường dẫn ẢNH ĐÃ RENDER (chỉ có ý
#                   nghĩa khi Type=infographic).
# video:            KHÔNG có nguồn Sheet tương ứng ở marketing-automation —
#                   layer này written_by='aigen' theo schema, dữ liệu thật
#                   (nếu có) sẽ tới từ aigen-pipeline, không phải Sheet này.

_CONTEXT_RAW_FIELDS = ["Topic", "Context", "Hook", "Source", "tickers"]
_CONTEXT_UNMAPPED_FIELDS = ["Timestamp", "Hot%", "Score", "Group", "Duyệt Context", "Execute", "Notes"]
_CONTENT_UNMAPPED_FIELDS = ["Timestamp", "Context", "Status", "Notes", "Approve(gate 2)",
                            "Social Link", "Gate3", "Posting Status"]


def _rows_as_dicts(values: list[list[str]]) -> list[dict[str, str]]:
    """`get_all_values()` trả list[list[str]] (hàng 0 = header) -> list dict
    theo TÊN cột (an toàn hơn chỉ số cột cố định — đúng nguyên tắc dự án)."""
    if not values:
        return []
    header = values[0]
    rows = []
    for raw_row in values[1:]:
        # Sheet có thể trả hàng NGẮN HƠN header (ô trống cuối dòng bị cắt) —
        # pad bằng "" để zip không mất cột.
        padded = raw_row + [""] * (len(header) - len(raw_row))
        rows.append(dict(zip(header, padded)))
    return rows


def read_sheet_rows() -> tuple[list[dict], list[dict]]:
    """Đọc CONTEXT + CONTENT TRỰC TIẾP, KHÔNG qua `_open_board()`/
    `ensure_tabs()`. `SheetsBoard.__init__` là lazy (không tự kết nối) —
    `_spreadsheet()` mới thật sự gọi Sheets API, và KHÔNG có ensure_tabs/
    migrate_rows nào bị gọi kèm theo."""
    settings = load_settings()
    sheet_id = settings.get("sheets.spreadsheet_id", "")
    creds_path = settings.get("sheets.creds_path", "")
    board = SheetsBoard(spreadsheet_id=sheet_id, creds_path=creds_path)
    sh = board._spreadsheet()  # noqa: SLF001 -- cố ý dùng đường đọc trực tiếp, xem docstring module
    context_values = sh.worksheet("CONTEXT").get_all_values()
    content_values = sh.worksheet("CONTENT").get_all_values()
    return _rows_as_dicts(context_values), _rows_as_dicts(content_values)


def analyze(context_rows: list[dict], content_rows: list[dict]) -> dict:
    """Thống kê THUẦN (không I/O) — tách riêng khỏi `read_sheet_rows()` để
    test được bằng dữ liệu giả, không cần Sheet thật."""
    report = {
        "raw": [],            # list[(topic_key, payload)]
        "brief": [],
        "content_output": [],
        "infographic": [],
        "video": [],           # LUÔN RỖNG từ nguồn Sheet -- xem docstring module
        "context_empty_topic_key": 0,
        "content_empty_topic_key": 0,
        "context_duplicate_topic_key": [],  # topic_key xuất hiện >1 lần TRONG CONTEXT (bất thường -- CONTEXT là 1-dòng-1-topic)
        "content_type_counts": Counter(),
        "content_topic_key_types": defaultdict(set),  # topic_key -> {Type,...} -- PHÁT HIỆN QUAN TRỌNG, xem cuối output
    }

    context_topic_key_seen = Counter()
    for row in context_rows:
        tk = (row.get("TopicKey") or "").strip()
        if not tk:
            report["context_empty_topic_key"] += 1
            continue
        context_topic_key_seen[tk] += 1
        payload = {f: row.get(f, "") for f in _CONTEXT_RAW_FIELDS}
        report["raw"].append((tk, payload))
    report["context_duplicate_topic_key"] = [tk for tk, n in context_topic_key_seen.items() if n > 1]

    for row in content_rows:
        tk = (row.get("TopicKey") or "").strip()
        content_type = (row.get("Type") or "").strip()
        if content_type:
            report["content_type_counts"][content_type] += 1
        if not tk:
            report["content_empty_topic_key"] += 1
            continue
        report["content_topic_key_types"][tk].add(content_type or "(rỗng)")

        facts_raw = (row.get("Facts") or "").strip()
        if facts_raw:
            try:
                facts_parsed = json.loads(facts_raw)
                report["brief"].append((tk, {"facts": facts_parsed}))
            except json.JSONDecodeError:
                report.setdefault("brief_json_parse_errors", []).append(tk)

        output_raw = (row.get("Output") or "").strip()
        if output_raw:
            report["content_output"].append((tk, {"type": content_type, "output": output_raw}))

        asset_path = (row.get("AssetPath") or "").strip()
        if asset_path:
            report["infographic"].append((tk, {"type": content_type, "asset_path": asset_path}))

    return report


def print_report(report: dict) -> None:
    print("=== Thống kê map theo layer ===")
    for layer in ("raw", "brief", "content_output", "infographic", "video"):
        print(f"  {layer:16s}: {len(report[layer])} bản ghi")
    if not report["video"]:
        print("  -> 'video' KHÔNG có dữ liệu thật từ Sheet -- ĐÚNG DỰ KIẾN, layer này"
              " written_by='aigen' (xem docstring module), nguồn thật (nếu có) ở"
              " aigen-pipeline, không phải Sheet.")

    print()
    print("=== Cột Sheet KHÔNG map vào layer nào (dữ liệu sẽ MẤT khi chuyển sang store) ===")
    print(f"  CONTEXT: {', '.join(_CONTEXT_UNMAPPED_FIELDS)}")
    print(f"  CONTENT: {', '.join(_CONTENT_UNMAPPED_FIELDS)}")
    print("  -> Đây đều là cột TRẠNG THÁI VẬN HÀNH (Duyệt Context/Execute/Approve/"
          "Gate3/Posting Status/Notes/Timestamp/Hot%/Score/Group), KHÔNG phải NỘI"
          " DUNG tài liệu -- HỢP LÝ nếu store chỉ giữ nội dung, còn trạng thái vận"
          " hành vẫn ở Sheet (đúng kiến trúc A6: 'Sheet chỉ là UI/view'). NHƯNG nếu"
          " dự định sau này Sheet KHÔNG còn giữ trạng thái nữa, các cột này cần 1"
          " nơi khác để neo -- CHƯA có trong schema hiện tại, cần Lead xác nhận có"
          " cố ý bỏ hay chưa nghĩ tới.")

    print()
    print("=== TopicKey rỗng ===")
    print(f"  CONTEXT: {report['context_empty_topic_key']} dòng")
    print(f"  CONTENT: {report['content_empty_topic_key']} dòng")

    print()
    print("=== TopicKey trùng TRONG CONTEXT (bất thường -- CONTEXT lẽ ra 1-dòng-1-topic) ===")
    dup = report["context_duplicate_topic_key"]
    print(f"  {len(dup)} topic_key trùng" + (f": {dup[:10]}{'...' if len(dup) > 10 else ''}" if dup else ""))

    print()
    print("=== [ĐÃ SỬA — BUG 1, 2026-07-19] Nhiều Type cùng 1 TopicKey trong CONTENT ===")
    multi = {tk: types for tk, types in report["content_topic_key_types"].items() if len(types) > 1}
    print(f"  {len(multi)}/{len(report['content_topic_key_types'])} topic_key có >1 Type"
          f" (vd article + video + infographic CÙNG 1 chủ đề)")
    if multi:
        sample_tk = next(iter(multi))
        print(f"  Ví dụ: {sample_tk!r} -> {sorted(multi[sample_tk])}")
    print("  -> ĐÃ SỬA: schema.sql thêm cột content_type vào khoá UNIQUE"
          " (topic_key, layer, content_type, version) -- mỗi Type giờ có dải"
          " version RIÊNG, độc lập nhau. write_document() layer='content_output'"
          " giờ BẮT BUỘC content_type (raise ValueError nếu thiếu). Xem"
          " write_to_temp_store() bên dưới -- tự lấy content_type từ payload['type'].")

    print()
    print("=== Type trong CONTENT (đối chiếu ContentFormat enum) ===")
    for t, n in report["content_type_counts"].most_common():
        print(f"  {t}: {n}")

    if report.get("brief_json_parse_errors"):
        print()
        print(f"⚠️  {len(report['brief_json_parse_errors'])} dòng CONTENT.Facts KHÔNG parse được JSON: "
              f"{report['brief_json_parse_errors'][:5]}")


def write_to_temp_store(report: dict) -> Path:
    """Chỉ gọi khi --write -- ghi vào DB TẠM (tempfile), KHÔNG BAO GIỜ đụng
    store/document_store.db thật. Trả đường dẫn DB tạm để người gọi tự xem/xoá."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="backfill_dry_run_"))
    db_path = tmp_dir / "backfill_test.db"
    ds.init_db(db_path)

    written = Counter()
    errors = []
    for layer in ("raw", "brief", "content_output", "infographic"):
        for topic_key, payload in report[layer]:
            # BUG 1 (2026-07-19): content_output BẮT BUỘC content_type -- payload
            # của layer này luôn có key "type" (gán ở analyze(), từ CONTENT.Type
            # thật trên Sheet). Layer khác không có đa loại -> "" (mặc định).
            content_type = payload.get("type", "") if layer == "content_output" else ""
            try:
                ds.write_document(topic_key, layer, payload, "ma", content_type=content_type, db_path=db_path)
                written[layer] += 1
            except Exception as e:  # noqa: BLE001 -- backfill thử nghiệm, muốn thấy MỌI lỗi, không phân loại trước
                errors.append((layer, topic_key, str(e)))

    print()
    print(f"=== Đã ghi vào DB TẠM: {db_path} ===")
    total_written = sum(written.values())
    for layer, n in written.items():
        print(f"  {layer}: {n} bản ghi thành công")
    print(f"  TỔNG: {total_written} bản ghi")
    if errors:
        print(f"  ⚠️  {len(errors)} lỗi ghi (ví dụ 5 đầu): {errors[:5]}")

    # Xác nhận yêu cầu #6: sau khi đổi khoá UNIQUE, đọc lại TỪNG content_type
    # của MỖI topic_key có >1 Type -- PHẢI đọc được ĐỘC LẬP, không cái nào
    # "chôn" mất (đúng ý BUG 1 vừa sửa).
    multi_type_topics = {tk: types for tk, types in report["content_topic_key_types"].items() if len(types) > 1}
    if multi_type_topics:
        print()
        print("=== Xác minh đọc lại độc lập (BUG 1 fix) — mọi topic_key đa Type ===")
        all_ok = True
        for tk, types in multi_type_topics.items():
            readback = {t: ds.read_latest(tk, "content_output", t, db_path=db_path) for t in types}
            missing = [t for t, v in readback.items() if v is None]
            if missing:
                all_ok = False
                print(f"  ⚠️  {tk!r}: THIẾU content_type {missing} (đáng lẽ đọc được)")
            else:
                print(f"  OK {tk!r}: đọc được độc lập cả {sorted(types)}")
        print("  -> TẤT CẢ topic_key đa Type đọc lại ĐÚNG, ĐỘC LẬP, không cái nào chôn."
              if all_ok else "  -> ⚠️ CÓ topic_key đọc lại THIẾU dữ liệu -- BUG 1 CHƯA sửa hết, kiểm lại.")
    return db_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help="Ghi vào DB TẠM (tempfile) thay vì chỉ in báo cáo. "
                             "KHÔNG BAO GIỜ ghi vào store thật.")
    args = parser.parse_args()

    print("Đang đọc Sheet (CHỈ ĐỌC, không ensure_tabs/migrate_rows)...")
    context_rows, content_rows = read_sheet_rows()
    print(f"Đọc được {len(context_rows)} dòng CONTEXT, {len(content_rows)} dòng CONTENT.")
    print()

    report = analyze(context_rows, content_rows)
    print_report(report)

    if args.write:
        write_to_temp_store(report)
    else:
        print()
        print("(--dry-run, mặc định -- không ghi gì. Dùng --write để thử ghi vào DB TẠM.)")


if __name__ == "__main__":
    main()
