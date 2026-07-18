"""AigenAdapter Phase 2 — xuất `VALID_TICKERS` (curation/vn_tickers.py, 1526 mã
thật HOSE/HNX/UPCOM) sang JSON cho validator alias-theo-kênh phía AIGEN (TS,
repo riêng `../aigen-pipeline/`, github.com/trieuvan-s/aigen-pipeline) dùng.
XUẤT DỮ LIỆU, KHÔNG xuất logic — TS
tự viết validator riêng đọc file JSON này (xem AIGEN src/adapter/alias-
guardrail.ts). Một chiều: marketing-automation LÀ nguồn thật (whitelist gốc),
AIGEN chỉ đọc.

Chạy lại khi `vn_tickers.py` cập nhật (sau `scripts/update_tickers.py`):
    python scripts/export_ticker_whitelist_for_aigen.py
    python scripts/export_ticker_whitelist_for_aigen.py --out <path khác>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

from twmkt.curation.vn_tickers import VALID_TICKERS  # noqa: E402

# Sibling repo, ranh giới cứng theo ACTIVE_TASK.md — output nằm TRONG AIGEN
# (src/adapter/, cạnh visual-kind-map.ts của Phase 1), KHÔNG trong marketing-
# automation. Repo AIGEN chính thức = aigen-pipeline (package.json ở GỐC
# repo, KHÔNG có thư mục con "aigen/" như aigen-fva-capital cũ — xem
# docs/VPS_MIGRATION_BACKLOG.md A3).
_DEFAULT_OUT = REPO_ROOT.parent / "aigen-pipeline" / "src" / "adapter" / "vn-tickers.json"


def export_tickers(out_path: Path) -> int:
    tickers = sorted(VALID_TICKERS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(tickers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(tickers)


def _parse_args(argv: list[str]):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=_DEFAULT_OUT,
                    help=f"Đường dẫn file JSON output (mặc định: {_DEFAULT_OUT}).")
    return ap.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    n = export_tickers(args.out)
    print(f"Đã xuất {n} mã ticker -> {args.out}")
