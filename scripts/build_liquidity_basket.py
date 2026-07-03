"""Dựng rổ 'top-N mã thanh khoản tốt nhất' -> ghi data/tickers.txt.

NGUỒN DỮ LIỆU (theo thứ tự ưu tiên):
  1) data/liquidity.csv  — export từ HỆ DỮ LIỆU TỰ ĐỘNG CỦA BẠN (Amibroker/DB).
     Cột tối thiểu: ticker, avg_value   (hoặc: ticker, close, volume để tự tính).
     => Đây là nguồn CHÍNH XÁC NHẤT (trung bình nhiều phiên) và khớp rổ nội bộ của bạn.
  2) vnstock  — fallback nếu không có CSV. Lấy `accumulated_value` (giá trị khớp
     lệnh PHIÊN GẦN NHẤT, VND) qua Trading.price_board — gọi THEO LÔ (batch, mặc
     định 200 mã/lần) cho toàn bộ mã ở data/tickers_full.txt, KHÔNG gọi lịch sử
     từng mã (chậm, dễ vượt rate-limit với ~1500 mã). Vì chỉ 1 phiên (không trung
     bình nhiều phiên như CSV) nên ồn hơn — ưu tiên dùng CSV khi có.

Chạy: pip install vnstock pandas && python scripts/build_liquidity_basket.py
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

TOP_N = 300
BATCH_SIZE = 200          # số mã/lần gọi Trading.price_board (batch, không phải per-symbol)
RATE_LIMIT_S = 1.0        # nghỉ giữa các lô, lịch sự với server
OUT = REPO_ROOT / "data" / "tickers.txt"
CSV_IN = REPO_ROOT / "data" / "liquidity.csv"
TICKERS_FULL = REPO_ROOT / "data" / "tickers_full.txt"   # whitelist đã curate sẵn ($0, offline)


def from_csv(path: Path) -> list[tuple[str, float]]:
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    out: list[tuple[str, float]] = []
    for r in rows:
        t = (r.get("ticker") or r.get("symbol") or "").strip().upper()
        if not t:
            continue
        if r.get("avg_value"):
            v = float(r["avg_value"])
        elif r.get("close") and r.get("volume"):
            v = float(r["close"]) * float(r["volume"])
        else:
            continue
        out.append((t, v))
    return out


def _load_symbols(path: Path) -> list[str]:
    return [
        s.strip().upper() for s in path.read_text(encoding="utf-8").splitlines()
        if s.strip() and not s.startswith("#")
    ]


def from_vnstock(*, batch_size: int = BATCH_SIZE,
                 rate_limit_s: float = RATE_LIMIT_S) -> list[tuple[str, float]]:  # pragma: no cover - cần mạng
    """Fallback: cần mạng ra vnstock. Lấy accumulated_value (giá trị khớp lệnh
    phiên gần nhất) qua Trading.price_board, gọi THEO LÔ cho toàn bộ mã ở
    data/tickers_full.txt (tái dùng whitelist đã curate, không gọi lại Listing)."""
    from vnstock import Trading

    symbols = _load_symbols(TICKERS_FULL)
    trading = Trading(source="vci")
    rows: list[tuple[str, float]] = []
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]
        try:
            df = trading.price_board(batch)
        except Exception as e:
            print(f"[CẢNH BÁO] Lỗi lô {i}-{i + len(batch)}: {e!r} — bỏ qua lô này.")
            continue
        for _, row in df.iterrows():
            sym = str(row[("listing", "symbol")]).strip().upper()
            val = row.get(("match", "accumulated_value"), 0) or 0
            rows.append((sym, float(val)))
        print(f"  lô {i // batch_size + 1}: {len(batch)} mã -> lấy được {len(df)} dòng")
        if i + batch_size < len(symbols):
            time.sleep(rate_limit_s)
    return rows


def build(top_n: int = TOP_N) -> list[str]:
    if CSV_IN.exists():
        print(f"Nguồn: {CSV_IN} (hệ dữ liệu của bạn)")
        data = from_csv(CSV_IN)
    else:
        print("Không thấy data/liquidity.csv -> thử vnstock (cần mạng)...")
        data = from_vnstock()

    if not data:
        sys.exit("Không có dữ liệu thanh khoản. Hãy export data/liquidity.csv từ hệ của bạn.")

    data.sort(key=lambda x: x[1], reverse=True)
    top = [t for t, _ in data[:top_n]]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(top) + "\n", encoding="utf-8")
    print(f"Đã ghi {len(top)} mã (top {top_n} thanh khoản) -> {OUT}")
    return top


if __name__ == "__main__":
    build()
