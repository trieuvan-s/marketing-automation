"""Cửa RE-ROUTE thủ công (Phase 4.8 Mục A) — owner xoá quyết định StructureRouter
đã đóng băng (agents/route_once.RouterDecisionStore) cho 1 chủ đề, khi thấy
khung (S1-S5/hook) chọn sai. Lần produce SAU sẽ route lại (agents/route_once.
get_or_route) — KHÔNG có gì tự động re-route, PHẢI chạy tay script này trước.

Phase 4.13 Mục A — CHANNEL OVERRIDE: owner bật/tắt TAY 1 tuyến (article/
infographic/video) của quyết định ĐÃ đóng băng, KHÔNG cần route lại cả quyết
định (structure/hook giữ nguyên) — dùng khi router chọn sai tuyến (vd tự động
tắt infographic nhưng owner thấy vẫn đủ chất liệu).

Chạy:
    python scripts/reroute.py "Lưới điện Cuba sụp toàn quốc lần thứ 8"   # tự slug hoá
    python scripts/reroute.py --key lưới-điện-cuba-sụp-toàn-quốc-lần-thứ  # slug đã biết
    python scripts/reroute.py --list                                    # in mọi quyết định đang đóng băng
    python scripts/reroute.py "Tên chủ đề" --channel infographic --set off  # tắt tay 1 tuyến
    python scripts/reroute.py --key <slug> --channel video --set on         # bật tay 1 tuyến
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

from twmkt.agents.route_once import RouterDecisionStore  # noqa: E402
from twmkt.config import data_path, load_settings  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from produce_from_sheet import _slug  # noqa: E402


def _open_store() -> RouterDecisionStore:
    settings = load_settings()
    return RouterDecisionStore(
        data_path(settings.get("router.decisions_path", "state/router_decisions.json"), settings=settings))


def main(argv: list[str]) -> None:
    import argparse
    ap = argparse.ArgumentParser(
        description="Xoá RouterDecision đã đóng băng của 1 chủ đề — lần produce SAU sẽ route lại.")
    ap.add_argument("topic", nargs="?", help="Context/tiêu đề chủ đề (tự động slug hoá).")
    ap.add_argument("--key", help="Slug đã biết chính xác (bỏ qua bước tự slug hoá).")
    ap.add_argument("--list", action="store_true", help="In mọi quyết định đang đóng băng.")
    ap.add_argument("--channel", choices=["article", "infographic", "video"],
                    help="Phase 4.13: tuyến muốn owner override tay (đi kèm --set).")
    ap.add_argument("--set", choices=["on", "off"], dest="set_value",
                    help="Phase 4.13: bật (on) hoặc tắt (off) tuyến --channel — KHÔNG route lại.")
    args = ap.parse_args(argv)

    store = _open_store()

    if args.list:
        data = store.all()
        if not data:
            print(f"({store.path}) chưa có quyết định nào đóng băng.")
            return
        for k, v in data.items():
            sec = f"/{v.secondary_structure}" if v.secondary_structure else ""
            print(f"- {k}: structure={v.structure}{sec} hook={v.hook} "
                 f"| channels={v.output_channels}")
        return

    key = args.key or (_slug(args.topic) if args.topic else None)
    if not key:
        ap.error("cần 1 trong 2: topic (vị trí) hoặc --key, hoặc --list.")

    if args.channel or args.set_value:
        if not (args.channel and args.set_value):
            ap.error("--channel và --set phải đi cùng nhau.")
        enabled = args.set_value == "on"
        if store.set_channel(key, args.channel, enabled):
            print(f"Đã {'bật' if enabled else 'tắt'} tay tuyến {args.channel!r} cho "
                 f"key={key!r} (structure/hook giữ nguyên, KHÔNG route lại).")
        else:
            print(f"Không tìm thấy quyết định đóng băng nào cho key={key!r} "
                 f"(chưa từng route — thử --list để xem key thật).")
        return

    if store.clear(key):
        print(f"Đã xoá quyết định đóng băng cho key={key!r} — lần produce SAU sẽ route lại.")
    else:
        print(f"Không tìm thấy quyết định đóng băng nào cho key={key!r} "
              f"(chưa từng route, hoặc slug không khớp — thử --list để xem key thật).")


if __name__ == "__main__":
    main(sys.argv[1:])
