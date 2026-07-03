"""Chạy job crawl theo LỊCH (config-first). Đọc mục `schedule` trong settings.yaml.

    python scripts/run_scheduler.py             # vòng lặp nội bộ (cần schedule.enabled=true)
    python scripts/run_scheduler.py --once      # chạy 1 lần rồi thoát (dùng cho OS scheduler)
    python scripts/run_scheduler.py --offline    # job = run_pipeline offline ($0, không mạng)
    python scripts/run_scheduler.py --force      # chạy loop dù enabled=false (test tạm)
    python scripts/run_scheduler.py --print-os   # in lệnh Task Scheduler (Windows) / cron

Job (adapter, chọn qua schedule.job):
  • review_to_sheet : crawl CafeF THẬT -> ghi title+hook lên Google Sheet (cần creds).
  • run_pipeline    : pipeline đến cổng 1, lưu storage/output (dùng --offline để $0).

Cả hai job dùng MockLLM -> KHÔNG tốn token khi crawl theo lịch.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

from twmkt.config import load_settings  # noqa: E402
from twmkt.schedule import ScheduleConfig, Scheduler  # noqa: E402


def build_job(settings, *, offline: bool, limit: int):
    """Dựng callable job theo config (adapter). --offline ép dùng run_pipeline offline."""
    name = "run_pipeline" if offline else settings.get("schedule.job", "review_to_sheet")
    if name == "review_to_sheet":
        from review_to_sheet import run as job_run
        return lambda: job_run(limit=limit)
    if name == "run_pipeline":
        from run_pipeline import run as job_run
        return lambda: job_run(offline=offline)
    raise SystemExit(f"schedule.job không hỗ trợ: {name!r} (review_to_sheet|run_pipeline)")


def _print_os_commands(cfg: ScheduleConfig) -> None:
    py = sys.executable
    script = str(REPO_ROOT / "scripts" / "run_scheduler.py")
    print("=== Windows Task Scheduler (schtasks) ===")
    if cfg.mode == "interval":
        print(f'schtasks /Create /TN "TWMKT-Crawl" /SC MINUTE /MO {cfg.interval_minutes} '
              f'/TR "\\"{py}\\" \\"{script}\\" --once"')
    else:
        for h, m in sorted(cfg.at_times):
            tn = f"TWMKT-Crawl-{h:02d}{m:02d}"
            print(f'schtasks /Create /TN "{tn}" /SC DAILY /ST {h:02d}:{m:02d} '
                  f'/TR "\\"{py}\\" \\"{script}\\" --once"')
    print("\n=== cron (Linux/macOS) ===")
    if cfg.mode == "interval":
        print(f"*/{cfg.interval_minutes} * * * * cd {REPO_ROOT} && {py} {script} --once")
    else:
        for h, m in sorted(cfg.at_times):
            print(f"{m} {h} * * * cd {REPO_ROOT} && {py} {script} --once")


def _parse_args(argv: list[str]):
    import argparse
    ap = argparse.ArgumentParser(description="Lập lịch tự động chạy crawl (config-first).")
    ap.add_argument("--once", action="store_true", help="Chạy job 1 lần rồi thoát.")
    ap.add_argument("--offline", action="store_true",
                    help="Job = run_pipeline offline ($0, không mạng/creds).")
    ap.add_argument("--force", action="store_true",
                    help="Chạy loop dù schedule.enabled=false.")
    ap.add_argument("--print-os", action="store_true",
                    help="In lệnh Task Scheduler/cron cho --once rồi thoát.")
    ap.add_argument("--limit", type=int, default=None, help="Số bài/nguồn (mặc định theo config).")
    return ap.parse_args(argv)


def main(argv: list[str]) -> None:
    args = _parse_args(argv)
    settings = load_settings()
    cfg = ScheduleConfig.from_settings(settings)

    if args.print_os:
        _print_os_commands(cfg)
        return

    limit = args.limit if args.limit is not None else int(settings.get("crawl.limit_per_source", 8))
    job = build_job(settings, offline=args.offline, limit=limit)

    if args.once:
        print("[schedule] chạy 1 lần (--once)...")
        job()
        return

    if not cfg.enabled and not args.force:
        print("[schedule] schedule.enabled=false. Bật trong settings.yaml, hoặc dùng "
              "--once (1 lần) / --force (loop tạm) / --print-os (đăng ký OS scheduler).")
        return

    print(f"[schedule] BẬT: {cfg.describe()}")
    Scheduler(job, cfg).run()


if __name__ == "__main__":
    main(sys.argv[1:])
