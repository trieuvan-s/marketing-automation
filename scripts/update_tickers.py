"""Làm mới whitelist mã cổ phiếu VN — chạy TAY khi cần, không phải runtime dependency.

extract_tickers() trong curation/normalize.py chỉ cần đọc file dữ liệu tĩnh
`src/twmkt/curation/vn_tickers.py` (đã bake sẵn) — script này chỉ dùng để tái
tạo file đó từ nguồn dữ liệu sàn thật (qua thư viện vnstock, mã nguồn mở, kéo
dữ liệu niêm yết HOSE/HNX/UPCOM). Không cài vnstock vào dependencies chính của
twmkt; đây là công cụ bảo trì độc lập.

Chạy:
    pip install vnstock
    python scripts/update_tickers.py
"""
from __future__ import annotations

import datetime
import os

OUT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "src", "twmkt", "curation", "vn_tickers.py"
)


def main() -> None:
    from vnstock import Listing

    df = Listing().all_symbols()
    symbols = sorted(set(df["symbol"].astype(str).str.strip().str.upper().tolist()))
    print(f"Lấy được {len(symbols)} mã từ vnstock (HOSE/HNX/UPCOM).")

    today = datetime.date.today().isoformat()
    lines = [
        '"""Whitelist mã cổ phiếu niêm yết VN (HOSE/HNX/UPCOM) — dữ liệu tĩnh.',
        "",
        f"Nguồn: vnstock (Listing().all_symbols()), lấy ngày {today}, {len(symbols)} mã.",
        "Làm mới: pip install vnstock && python scripts/update_tickers.py",
        "",
        "Whitelist thay cho cách cũ (regex 3 chữ hoa + blacklist từ loại trừ) vì",
        'blacklist không scale — vd "HCM" vừa là mã thật (Chứng khoán TP.HCM)',
        'vừa là viết tắt "TP.HCM", không quy tắc phi ngữ cảnh nào tách được.',
        '"""',
        "from __future__ import annotations",
        "",
        "VALID_TICKERS: frozenset[str] = frozenset({",
    ]
    for i in range(0, len(symbols), 10):
        chunk = ", ".join(f'"{s}"' for s in symbols[i : i + 10])
        lines.append(f"    {chunk},")
    lines.append("})")
    lines.append("")

    with open(OUT_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    print(f"Đã ghi {OUT_PATH}")


if __name__ == "__main__":
    main()
