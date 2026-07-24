"""P2 STORE-AS-TRUTH (2026-07-23, nhánh `feature/store-as-truth`) -- lớp
NGHIỆP VỤ giữa pipeline (`scripts/produce_from_sheet.py`) và
`document_store.py` (CRUD thô theo layer/content_type/version). Cung cấp
đúng các thao tác pipeline cần, tương đương ngữ nghĩa các hàm `SheetsBoard`
cũ (`read_approved_context`, `existing_content_keys`,
`append_content_rows`, `set_execute_values`, `mark_execute_done`...) nhưng
đọc/ghi STORE, KHÔNG đụng Sheet -- xem docstring `document_store.py` +
docs/VPS_MIGRATION_BACKLOG.md mục P2 cho bối cảnh đầy đủ.

QUYỀN GHI: mọi hàm ở đây ghi `written_by="ma"` (module này CHẠY TRONG tiến
trình marketing-automation, dù caller là pipeline hay sync service -- cả 2
đều 'ma', KHÔNG phải 2 "written_by" khác nhau).

MERGE-ON-WRITE cho gate_status/content_status: 2 layer này gộp NHIỀU field
độc lập (vd gate1/execute/output_type) vào 1 payload -- ghi 1 field mới
KHÔNG được xoá field khác đã có (khác content_output/raw, vốn ghi NGUYÊN
payload mới mỗi lần). `write_gate_status()`/`write_content_status()` tự
đọc bản MỚI NHẤT, merge tham số truyền vào (bỏ qua tham số `None` -- giữ
nguyên field cũ), rồi ghi version mới -- caller KHÔNG cần tự đọc-sửa-ghi."""
from __future__ import annotations

from typing import Any

from . import document_store as ds

_WRITTEN_BY = "ma"


# --- raw (crawl output, topic-level) ----------------------------------------

def write_raw(topic_key: str, payload: dict, *, db_path=None) -> int:
    """Ghi bản crawl/nghiên cứu thô -- title/context/hook/source/tickers/
    group/topic (khớp field `approved_context_from_rows()` cũ, TRỪ execute/
    row/topic_key vốn không thuộc "raw" -- xem gate_status)."""
    return ds.write_document(topic_key, "raw", payload, _WRITTEN_BY, db_path=db_path)


def read_raw(topic_key: str, *, db_path=None) -> dict | None:
    return ds.read_latest(topic_key, "raw", "", db_path=db_path)


# --- gate_status (topic-level: gate1, execute, output_type, notes) ---------

def _merge_write(topic_key: str, layer: str, content_type: str, updates: dict[str, Any], *, db_path=None) -> int:
    current = ds.read_latest(topic_key, layer, content_type, db_path=db_path) or {}
    merged = {**current, **{k: v for k, v in updates.items() if v is not None}}
    return ds.write_document(topic_key, layer, merged, _WRITTEN_BY, content_type=content_type, db_path=db_path)


def write_gate_status(
    topic_key: str, *, gate1: str | None = None, execute: str | None = None,
    output_type: list[str] | None = None, notes: str | None = None, db_path=None,
) -> int:
    """MERGE-ON-WRITE (xem docstring module) -- chỉ truyền field muốn đổi,
    field khác giữ nguyên bản trước. `output_type` LIST (Bước 4 -- cho chọn
    nhiều loại, mặc định 1)."""
    return _merge_write(topic_key, "gate_status", "", {
        "gate1": gate1, "execute": execute, "output_type": output_type, "notes": notes,
    }, db_path=db_path)


def read_gate_status(topic_key: str, *, db_path=None) -> dict:
    """Trả {} nếu chưa từng ghi (KHÔNG None -- caller luôn .get() an toàn)."""
    return ds.read_latest(topic_key, "gate_status", "", db_path=db_path) or {}


def mark_execute_done(topic_key: str, *, db_path=None) -> int:
    return write_gate_status(topic_key, execute="DONE", db_path=db_path)


def mark_execute(topic_key: str, value: str, *, db_path=None) -> int:
    """`value` -- 'RUN'/'DONE'/'FAILED'/'NEEDS_HUMAN' (khớp state machine
    Execute cũ trên Sheet, xem produce_from_sheet.py::run() docstring)."""
    return write_gate_status(topic_key, execute=value, db_path=db_path)


def list_approved_topics(*, db_path=None) -> list[dict]:
    """Tương đương `SheetsBoard.read_approved_context()` lọc
    `execute in (RUN, FAILED)` -- JOIN raw + gate_status theo topic_key.
    Trả list dict {topic_key, context, hook, source, tickers, group, topic,
    execute, gate1, output_type}. KHÔNG có field "row" (khái niệm Sheet,
    không còn ý nghĩa -- caller dùng topic_key để ghi lại trạng thái)."""
    out: list[dict] = []
    for topic_key in ds.list_topics(layer="gate_status", db_path=db_path):
        gate = read_gate_status(topic_key, db_path=db_path)
        if gate.get("gate1") != "APPROVE":
            continue
        if gate.get("execute") not in ("RUN", "FAILED"):
            continue
        raw = read_raw(topic_key, db_path=db_path) or {}
        out.append({
            "topic_key": topic_key,
            "context": raw.get("context", ""),
            "hook": raw.get("hook", ""),
            "source": raw.get("source", ""),
            "tickers": raw.get("tickers", []),
            "group": raw.get("group", ""),
            "topic": raw.get("topic", ""),
            "execute": gate.get("execute", ""),
            "gate1": gate.get("gate1", ""),
            "output_type": gate.get("output_type") or [],
        })
    return out


# --- content_output (per content_type, sinh RA bởi Content Factory) --------

def write_content_output(topic_key: str, content_type: str, payload: dict, *, db_path=None) -> int:
    return ds.write_document(topic_key, "content_output", payload, _WRITTEN_BY,
                             content_type=content_type, db_path=db_path)


def read_content_output(topic_key: str, content_type: str, *, db_path=None) -> dict | None:
    return ds.read_latest(topic_key, "content_output", content_type, db_path=db_path)


def existing_content_keys(*, db_path=None) -> set[tuple[str, str]]:
    """(topic_key, content_type) đã có content_output -- tương đương
    `SheetsBoard.existing_content_keys()` (Lớp 5 Phase 2, dedupe across-run)."""
    out: set[tuple[str, str]] = set()
    for topic_key in ds.list_topics(layer="content_output", db_path=db_path):
        for content_type in ("article", "infographic", "video"):
            if ds.read_latest(topic_key, "content_output", content_type, db_path=db_path) is not None:
                out.add((topic_key, content_type))
    return out


# --- content_status (per content_type: gate2, gate3, notes, social_link,
# posting_status, asset_url, asset_local_path, asset_drive_file_id,
# asset_content_hash -- Bước 3.4) -------------------------------------------

def write_content_status(
    topic_key: str, content_type: str, *, gate2: str | None = None, gate3: str | None = None,
    notes: str | None = None, social_link: str | None = None, posting_status: str | None = None,
    asset_url: str | None = None, asset_local_path: str | None = None,
    asset_drive_file_id: str | None = None, asset_content_hash: str | None = None, db_path=None,
) -> int:
    return _merge_write(topic_key, "content_status", content_type, {
        "gate2": gate2, "gate3": gate3, "notes": notes, "social_link": social_link,
        "posting_status": posting_status, "asset_url": asset_url,
        "asset_local_path": asset_local_path, "asset_drive_file_id": asset_drive_file_id,
        "asset_content_hash": asset_content_hash,
    }, db_path=db_path)


def read_content_status(topic_key: str, content_type: str, *, db_path=None) -> dict:
    return ds.read_latest(topic_key, "content_status", content_type, db_path=db_path) or {}


# --- log (nhật ký toàn cục, thay tab LOG cũ trên Sheet -- BẮT BUỘC vào store,
# không phải "được để lại tạm": sync service store->Sheet (Bước 3) dựng lại
# TOÀN BỘ view mỗi lần chạy -- log() ghi thẳng Sheet sẽ bị XOÁ ở lần sync kế
# tiếp, xem schema.sql comment 'log') ------------------------------------

_LOG_TOPIC_KEY = "_system"   # surrogate cố định -- log không gắn 1 topic_key thật nào


def write_log(level: str, message: str, *, engine: str = "", db_path=None) -> int:
    """Ghi 1 dòng nhật ký MỚI (version mới dưới _LOG_TOPIC_KEY -- KHÔNG merge,
    mỗi lời gọi là 1 sự kiện riêng, khác gate_status/content_status)."""
    return ds.write_document(_LOG_TOPIC_KEY, "log", {
        "level": level.upper(), "message": message, "engine": engine,
    }, _WRITTEN_BY, db_path=db_path)


def read_log_history(*, db_path=None) -> list[tuple[int, dict, str]]:
    """Toàn bộ nhật ký, xuôi theo version (1, 2, 3, ...) -- (version, payload,
    created_at), dùng cho sync service render lại tab LOG."""
    return ds.read_history(_LOG_TOPIC_KEY, "log", "", db_path=db_path)
