"""Chạy 1 job theo LỊCH (config-first). Đọc mục `<section>` trong settings.yaml
(mặc định "schedule" — crawl; dùng --section schedule_draft cho lịch sản xuất).

    python scripts/run_scheduler.py                        # loop crawl (cần schedule.enabled=true)
    python scripts/run_scheduler.py --once                 # chạy 1 lần rồi thoát (OS scheduler)
    python scripts/run_scheduler.py --section schedule_draft --once   # 1 lần lịch --draft
    python scripts/run_scheduler.py --offline               # job = run_pipeline offline ($0)
    python scripts/run_scheduler.py --force                 # chạy loop dù enabled=false (test tạm)
    python scripts/run_scheduler.py --print-os              # in lệnh Task Scheduler (Windows)/cron

Job (adapter, chọn qua <section>.job):
  • review_to_sheet : crawl CafeF THẬT -> ghi title+hook lên Google Sheet (cần creds).
  • run_pipeline    : pipeline đến cổng 1, lưu storage/output (dùng --offline để $0).
  • produce_draft   : full-fetch bài APPROVE + tạo request chờ Claude Code viết
                      (produce_from_sheet.py --draft) — KHÔNG tự --ingest.

Muốn chạy CẢ 2 lịch (crawl + produce_draft) CÙNG LÚC trong 1 tiến trình: xem
system_power_on.py (thư mục gốc dự án). Script này (run_scheduler.py) chỉ
chạy 1 lịch/lần gọi — hợp để đăng ký riêng lẻ vào OS Task Scheduler (xem
--print-os).
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


def build_job(settings, *, offline: bool, limit: int, section: str = "schedule"):
    """Dựng callable job theo config (adapter). --offline ép dùng run_pipeline offline."""
    name = "run_pipeline" if offline else settings.get(f"{section}.job", "review_to_sheet")
    if name == "review_to_sheet":
        from review_to_sheet import run as job_run
        # hook_offline=true (mặc định) -> Hook lịch tự động dùng fallback $0,
        # tránh phí Sonnet mỗi giờ 24/7 không giám sát (xem settings.yaml).
        hook_offline = bool(settings.get(f"{section}.hook_offline", True))
        return lambda: job_run(limit=limit, offline=hook_offline)
    if name == "run_pipeline":
        from run_pipeline import run as job_run
        return lambda: job_run(offline=offline)
    if name == "produce_draft":
        from produce_from_sheet import run_draft as job_run
        return lambda: job_run(limit=limit)
    raise SystemExit(f"{section}.job không hỗ trợ: {name!r} "
                     "(review_to_sheet|run_pipeline|produce_draft)")


def _print_os_commands(cfg: ScheduleConfig, *, section: str) -> None:
    py = sys.executable
    script = str(REPO_ROOT / "scripts" / "run_scheduler.py")
    tag = "Crawl" if section == "schedule" else "Draft"
    section_arg = "" if section == "schedule" else f" --section {section}"
    print(f"=== Windows Task Scheduler (schtasks) — section={section} ===")
    if cfg.mode == "interval":
        print(f'schtasks /Create /TN "TWMKT-{tag}" /SC MINUTE /MO {cfg.interval_minutes} '
              f'/TR "\\"{py}\\" \\"{script}\\"{section_arg} --once"')
    else:
        for h, m in sorted(cfg.at_times):
            tn = f"TWMKT-{tag}-{h:02d}{m:02d}"
            print(f'schtasks /Create /TN "{tn}" /SC DAILY /ST {h:02d}:{m:02d} '
                  f'/TR "\\"{py}\\" \\"{script}\\"{section_arg} --once"')
    print("\n=== cron (Linux/macOS) ===")
    if cfg.mode == "interval":
        print(f"*/{cfg.interval_minutes} * * * * cd {REPO_ROOT} && {py} {script}{section_arg} --once")
    else:
        for h, m in sorted(cfg.at_times):
            print(f"{m} {h} * * * cd {REPO_ROOT} && {py} {script}{section_arg} --once")


def _parse_args(argv: list[str]):
    import argparse
    ap = argparse.ArgumentParser(description="Lập lịch tự động chạy 1 job (config-first).")
    ap.add_argument("--section", default="schedule",
                    help="Mục cấu hình đọc trong settings.yaml (mặc định 'schedule' = crawl; "
                        "dùng 'schedule_draft' cho lịch --draft sản xuất).")
    ap.add_argument("--once", action="store_true", help="Chạy job 1 lần rồi thoát.")
    ap.add_argument("--offline", action="store_true",
                    help="Job = run_pipeline offline ($0, không mạng/creds).")
    ap.add_argument("--force", action="store_true",
                    help="Chạy loop dù <section>.enabled=false.")
    ap.add_argument("--print-os", action="store_true",
                    help="In lệnh Task Scheduler/cron cho --once rồi thoát.")
    ap.add_argument("--limit", type=int, default=None, help="Số bài/nguồn (mặc định theo config).")
    return ap.parse_args(argv)


def main(argv: list[str]) -> None:
    args = _parse_args(argv)
    settings = load_settings()
    cfg = ScheduleConfig.from_settings(settings, section=args.section)

    if args.print_os:
        _print_os_commands(cfg, section=args.section)
        return

    default_limit_key = ("production.draft_limit" if args.section == "schedule_draft"
                         else "crawl.limit_per_source")
    default_limit = 5 if args.section == "schedule_draft" else 8
    limit = args.limit if args.limit is not None else int(settings.get(default_limit_key, default_limit))
    job = build_job(settings, offline=args.offline, limit=limit, section=args.section)

    if args.once:
        print("[schedule] chạy 1 lần (--once)...")
        job()
        return

    if not cfg.enabled and not args.force:
        print(f"[schedule] {args.section}.enabled=false. Bật trong settings.yaml, hoặc dùng "
              "--once (1 lần) / --force (loop tạm) / --print-os (đăng ký OS scheduler).")
        return

    print(f"[schedule] BẬT: {cfg.describe()}")
    Scheduler(job, cfg).run()


if __name__ == "__main__":
    main(sys.argv[1:])
