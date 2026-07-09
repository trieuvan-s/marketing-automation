"""Cửa RE-ROUTE thủ công (Phase 4.8 Mục A) — owner xoá quyết định StructureRouter
đã đóng băng (agents/route_once.RouterDecisionStore) cho 1 chủ đề, khi thấy
khung (S1-S5/hook) chọn sai. Lần produce SAU sẽ route lại (agents/route_once.
get_or_route) — KHÔNG có gì tự động re-route, PHẢI chạy tay script này trước.

Chạy:
    python scripts/reroute.py "Lưới điện Cuba sụp toàn quốc lần thứ 8"   # tự slug hoá
    python scripts/reroute.py --key lưới-điện-cuba-sụp-toàn-quốc-lần-thứ  # slug đã biết
    python scripts/reroute.py --list                                    # in mọi quyết định đang đóng băng
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

from twmkt.agents.route_once import RouterDecisionStore  # noqa: E402
from twmkt.config import load_settings  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from produce_from_sheet import _slug  # noqa: E402


def _open_store() -> RouterDecisionStore:
    settings = load_settings()
    return RouterDecisionStore(settings.get("router.decisions_path", "storage/router_decisions.json"))


def main(argv: list[str]) -> None:
    import argparse
    ap = argparse.ArgumentParser(
        description="Xoá RouterDecision đã đóng băng của 1 chủ đề — lần produce SAU sẽ route lại.")
    ap.add_argument("topic", nargs="?", help="Context/tiêu đề chủ đề (tự động slug hoá).")
    ap.add_argument("--key", help="Slug đã biết chính xác (bỏ qua bước tự slug hoá).")
    ap.add_argument("--list", action="store_true", help="In mọi quyết định đang đóng băng.")
    args = ap.parse_args(argv)

    store = _open_store()

    if args.list:
        data = store.all()
        if not data:
            print(f"({store.path}) chưa có quyết định nào đóng băng.")
            return
        for k, v in data.items():
            sec = f"/{v.secondary_structure}" if v.secondary_structure else ""
            print(f"- {k}: structure={v.structure}{sec} hook={v.hook}")
        return

    key = args.key or (_slug(args.topic) if args.topic else None)
    if not key:
        ap.error("cần 1 trong 2: topic (vị trí) hoặc --key, hoặc --list.")
    if store.clear(key):
        print(f"Đã xoá quyết định đóng băng cho key={key!r} — lần produce SAU sẽ route lại.")
    else:
        print(f"Không tìm thấy quyết định đóng băng nào cho key={key!r} "
              f"(chưa từng route, hoặc slug không khớp — thử --list để xem key thật).")


if __name__ == "__main__":
    main(sys.argv[1:])
