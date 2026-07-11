"""LỚP 5 Phase 1/1R.2 — Backfill/Re-key TopicKey (curation/keys.py) cho các
dòng CONTEXT/CONTENT hiện có trên Sheet.

Mặc định (WRITE-ONCE, an toàn chạy nhiều lần/theo lịch): chỉ điền TopicKey
RỖNG — dòng ĐÃ có khoá GIỮ NGUYÊN TUYỆT ĐỐI, không tính lại dù URL đổi gì.

`--rekey` (NGOẠI LỆ CÓ CHỦ Ý, Phase 1R.2 — xem docs/CHANGELOG.md): ghi ĐÈ mọi
khoá URL-based bằng compute_topic_key() MỚI (canonical, giữ query định danh)
— sửa khoá SAI tính bởi normalize_url phiên bản Phase 1 gốc (bỏ hết query,
có thể đã va chạm giữa 2 bài khác nhau cùng path khác `?id=`). Surrogate
(dòng không URL) KHÔNG bị đụng. CHỈ chạy `--rekey` ĐÚNG 1 LẦN khi migrate —
sau đó luôn chạy KHÔNG cờ (mặc định) để write-once có hiệu lực thật.

Chạy:
    python scripts/backfill_topic_keys.py            # write-once (mặc định, an toàn lặp lại)
    python scripts/backfill_topic_keys.py --rekey     # NGOẠI LỆ: re-key một lần (xem CHANGELOG)
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

import os  # noqa: E402

from twmkt.config import load_settings  # noqa: E402
from twmkt.sheets_board import SheetsBoard  # noqa: E402


def main(*, rekey: bool = False) -> dict:
    settings = load_settings()
    sheet_id = (os.environ.get("TWMKT_SHEET_ID") or settings.get("sheets.spreadsheet_id") or "").strip()
    creds = (os.environ.get("TWMKT_SHEETS_CREDS") or settings.get("sheets.creds_path") or "").strip()
    if not sheet_id or not creds:
        raise SystemExit("Thiếu sheets.spreadsheet_id/creds_path (settings.yaml hoặc ENV).")
    board = SheetsBoard(spreadsheet_id=sheet_id, creds_path=creds)
    if rekey:
        print("[CẢNH BÁO] --rekey: NGOẠI LỆ ghi đè mọi khoá URL-based bằng compute_topic_key() "
              "MỚI — bypass write-once có chủ đích. CHỈ chạy 1 lần khi migrate (xem CHANGELOG.md).")
    result = board.backfill_topic_keys(force=rekey)
    verb = "Re-key" if rekey else "Backfill"
    print(f"{verb} TopicKey: CONTEXT +{result['context']} dòng | CONTENT +{result['content']} dòng.")
    if result["warnings"]:
        print(f"[CẢNH BÁO] {len(result['warnings'])} dòng CONTENT không tra được TopicKey "
              "(Context không còn ở CONTEXT, hoặc CONTEXT dòng đó cũng chưa có khoá):")
        for ctx in result["warnings"]:
            print(f"  - {ctx[:80]}")
    return result


def _parse_args(argv: list[str]):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rekey", action="store_true",
                    help="NGOẠI LỆ: ghi đè khoá URL-based bằng hàm mới (Phase 1R.2, dùng 1 lần khi migrate).")
    return ap.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    main(rekey=args.rekey)
