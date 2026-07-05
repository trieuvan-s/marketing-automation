"""POWER ON — khởi động CẢ 2 lịch (crawl + sản xuất --draft) trong 1 tiến trình.

Chạy:
    python scripts/power_on.py

Dừng: Ctrl+C (dừng cả 2 lịch cùng lúc).

Mỗi lịch đọc 1 section riêng trong settings.yaml (schedule.schedule_config cho
crawl, schedule_draft cho --draft — xem src/twmkt/schedule.py) và chạy trong 1
thread daemon riêng (Scheduler.run() là vòng lặp chặn, không có cơ chế huỷ nội
bộ). Tiến trình chính chỉ chờ (join theo nhịp) và bắt Ctrl+C để thoát gọn.

Lịch nào `<section>.enabled=false` trong config thì KHÔNG khởi động (in rõ lý
do), không lỗi. Nếu KHÔNG lịch nào bật, in hướng dẫn rồi thoát ngay (không treo
tiến trình).
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

from twmkt import factory  # noqa: E402
from twmkt.config import load_settings  # noqa: E402
from twmkt.schedule import ScheduleConfig, Scheduler  # noqa: E402

# (section, prefix log, key limit mặc định trong config, giá trị limit dự phòng)
SCHEDULES = (
    ("schedule", "crawl", "crawl.limit_per_source", 8),
    ("schedule_draft", "draft", "production.draft_limit", 5),
)


def _prefixed_log(prefix: str):
    def log(msg: str) -> None:
        print(f"[{prefix}] {msg}")
    return log


def _build_job(settings, *, section: str, name: str, limit: int):
    if name == "review_to_sheet":
        import review_to_sheet
        # hook_offline=true (mặc định) -> Hook lịch tự động dùng fallback $0,
        # tránh phí Sonnet mỗi giờ 24/7 không giám sát (xem settings.yaml).
        hook_offline = bool(settings.get(f"{section}.hook_offline", True))
        return lambda: review_to_sheet.run(limit=limit, offline=hook_offline)
    if name == "produce_draft":
        import produce_from_sheet
        return lambda: produce_from_sheet.run_draft(limit=limit)
    if name == "run_pipeline":
        import run_pipeline
        return lambda: run_pipeline.run(offline=False)
    raise SystemExit(f"{section}.job không hỗ trợ: {name!r}")


def _start_schedule(settings, *, section: str, prefix: str,
                    limit_key: str, default_limit: int) -> threading.Thread | None:
    cfg = ScheduleConfig.from_settings(settings, section=section)
    if not cfg.enabled:
        print(f"[{prefix}] TẮT ({section}.enabled=false trong settings.yaml) — bỏ qua.")
        return None
    limit = int(settings.get(limit_key, default_limit))
    job = _build_job(settings, section=section, name=cfg.job, limit=limit)
    sched = Scheduler(job, cfg, log=_prefixed_log(prefix))
    print(f"[{prefix}] BẬT: {cfg.describe()}")
    t = threading.Thread(target=sched.run, name=prefix, daemon=True)
    t.start()
    return t


def main() -> None:
    settings = load_settings()

    print("=" * 60)
    print("  TURTLE WEALTH MARKETING — POWER ON")
    print("=" * 60)
    print(factory.llm_status(settings).banner)
    print()

    threads = [
        t for t in (
            _start_schedule(settings, section=section, prefix=prefix,
                           limit_key=limit_key, default_limit=default_limit)
            for section, prefix, limit_key, default_limit in SCHEDULES
        )
        if t is not None
    ]

    if not threads:
        print("\nKhông có lịch nào BẬT (schedule.enabled / schedule_draft.enabled đều false).")
        print("Bật trong config/settings.yaml rồi chạy lại, hoặc dùng script riêng lẻ:")
        print("  python scripts/review_to_sheet.py")
        print("  python scripts/produce_from_sheet.py --draft")
        return

    print(f"\n{len(threads)} lịch đang chạy nền. Nhấn Ctrl+C để dừng toàn bộ.\n")
    try:
        while any(t.is_alive() for t in threads):
            for t in threads:
                t.join(timeout=1.0)
    except KeyboardInterrupt:
        print("\n[power-on] Nhận Ctrl+C — đang dừng (job đang chạy sẽ hoàn tất lượt hiện tại)...")


if __name__ == "__main__":
    main()
