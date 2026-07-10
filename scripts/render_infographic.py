"""Render *-infographic.json (đã sinh ở --draft) -> ảnh SVG thật, $0 tất định.

Chạy:
    python scripts/render_infographic.py                    # render TẤT CẢ *-infographic.json hôm nay
    python scripts/render_infographic.py --date 2026-07-05  # render 1 ngày cụ thể
    python scripts/render_infographic.py --file <data_root>/output/2026-07-05/x-infographic.json

Ghi .svg CẠNH file .json nguồn (cùng slug, đổi đuôi .svg) — không cần cấu hình
thư mục riêng. Không LLM, không mạng.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

from twmkt.config import data_path, load_settings  # noqa: E402
from twmkt.render import brand_kit_from_settings, render_infographic_svg  # noqa: E402


def _today(settings) -> str:
    return datetime.now().strftime("%Y-%m-%d")


def render_file(spec_path: Path, brand: dict) -> Path:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    svg = render_infographic_svg(spec, brand)
    out_path = spec_path.with_suffix(".svg")
    out_path.write_text(svg, encoding="utf-8")
    return out_path


def run(*, file: str | None = None, date: str | None = None) -> dict:
    settings = load_settings()
    brand = brand_kit_from_settings(settings)

    if file:
        targets = [Path(file)]
    else:
        out_dir = data_path(settings.get("storage.output_dir", "output"), settings=settings)
        day_dir = out_dir / (date or _today(settings))
        targets = sorted(day_dir.glob("*-infographic.json"))

    if not targets:
        print(f"Không thấy *-infographic.json nào ({file or date or 'hôm nay'}).")
        return {"rendered": 0}

    rendered = []
    for spec_path in targets:
        if not spec_path.exists():
            print(f"[bỏ qua] không thấy file: {spec_path}")
            continue
        out_path = render_file(spec_path, brand)
        rendered.append(str(out_path))
        print(f"[render] {spec_path.name} -> {out_path.name}")

    print(f"\nXong: {len(rendered)} ảnh SVG. Mở trực tiếp bằng trình duyệt để xem trước.")
    return {"rendered": len(rendered), "files": rendered}


def _parse_args(argv: list[str]):
    import argparse
    ap = argparse.ArgumentParser(description="Render infographic spec JSON -> SVG ($0, tất định).")
    ap.add_argument("--file", default=None, help="Render đúng 1 file spec JSON.")
    ap.add_argument("--date", default=None, help="Ngày (YYYY-MM-DD) trong storage/output/ (mặc định hôm nay).")
    return ap.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    run(file=args.file, date=args.date)
