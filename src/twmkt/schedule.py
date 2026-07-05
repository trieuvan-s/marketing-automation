"""Lập lịch tự động chạy job crawl — config-first, lõi TẤT ĐỊNH tách khỏi thời gian.

Nguyên tắc:
  • Adapter: Scheduler nhận `job` là callable bất kỳ (crawl->Sheet, pipeline offline,
    hay stub trong test) — lõi lập lịch KHÔNG biết job làm gì.
  • Tất định & test được: việc tính "giờ chạy kế" là hàm THUẦN `next_run_at(now, cfg)`;
    đồng hồ (`now_fn`) và giấc ngủ (`sleep_fn`) được TIÊM vào -> test không chờ thật.
  • Bền: 1 lần job lỗi KHÔNG làm chết scheduler (bắt exception, ghi log, chạy tiếp).

Hai chế độ:
  • interval : chạy lại mỗi `interval_minutes` phút.
  • daily    : chạy vào các mốc `at_times` (giờ địa phương theo `timezone`) mỗi ngày.

Vòng lặp nội bộ (`python scripts/run_scheduler.py`) hợp cho chạy nền đơn giản; để
"đặt-rồi-quên" (sống qua reboot) nên dùng `--once` + OS scheduler (Task Scheduler /
cron) — xem scripts/run_scheduler.py --print-os.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

try:  # zoneinfo có sẵn từ 3.9; fallback UTC nếu thiếu dữ liệu tz
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

MODES = ("interval", "daily")


def parse_hhmm(s: str) -> tuple[int, int]:
    """'08:30' -> (8, 30). Raise ValueError nếu sai định dạng/khoảng."""
    parts = str(s).strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Giờ phải dạng HH:MM, nhận: {s!r}")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(f"Giờ ngoài khoảng hợp lệ: {s!r}")
    return (h, m)


def _resolve_tz(name: str):
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    return timezone.utc


@dataclass
class ScheduleConfig:
    enabled: bool = False
    mode: str = "interval"
    interval_minutes: int = 60
    at_times: list[tuple[int, int]] = field(default_factory=lambda: [(8, 30)])
    timezone: str = "Asia/Ho_Chi_Minh"
    jitter_s: float = 0.0
    run_on_start: bool = True
    max_runs: int = 0                 # 0 = vô hạn; >0 = dừng sau N lần (test/CI)
    job: str = "review_to_sheet"

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"schedule.mode không hợp lệ: {self.mode!r} ({'|'.join(MODES)})")
        if self.mode == "interval" and self.interval_minutes <= 0:
            raise ValueError("schedule.interval_minutes phải > 0")
        if self.mode == "daily" and not self.at_times:
            raise ValueError("schedule.at_times trống cho mode=daily")

    @classmethod
    def from_settings(cls, settings, *, section: str = "schedule") -> "ScheduleConfig":
        """`section` cho phép nhiều lịch ĐỘC LẬP trong CÙNG settings.yaml (vd
        "schedule" cho crawl, "schedule_draft" cho --draft sản xuất) — mỗi lịch
        đọc key riêng dưới `<section>.*`, không đụng nhau. Mặc định "schedule"
        (tương thích ngược với cấu hình cũ)."""
        raw_times = settings.get(f"{section}.at_times", ["08:30"]) or ["08:30"]
        return cls(
            enabled=bool(settings.get(f"{section}.enabled", False)),
            mode=(settings.get(f"{section}.mode", "interval") or "interval").lower(),
            interval_minutes=int(settings.get(f"{section}.interval_minutes", 60)),
            at_times=[parse_hhmm(t) for t in raw_times],
            timezone=settings.get(f"{section}.timezone", "Asia/Ho_Chi_Minh"),
            jitter_s=float(settings.get(f"{section}.jitter_s", 0.0)),
            run_on_start=bool(settings.get(f"{section}.run_on_start", True)),
            max_runs=int(settings.get(f"{section}.max_runs", 0)),
            job=settings.get(f"{section}.job", "review_to_sheet"),
        )

    def describe(self) -> str:
        if self.mode == "interval":
            when = f"mỗi {self.interval_minutes} phút"
        else:
            when = "lúc " + ", ".join(f"{h:02d}:{m:02d}" for h, m in sorted(self.at_times))
        return f"{self.mode} ({when}), tz={self.timezone}, job={self.job}"


def next_run_at(now: datetime, cfg: ScheduleConfig) -> datetime:
    """Giờ chạy kế tiếp (hàm THUẦN). `now` nên là datetime aware theo timezone đích.

    - interval: now + interval_minutes.
    - daily: mốc at_times gần nhất SAU now trong hôm nay; hết -> mốc sớm nhất ngày mai.
    """
    if cfg.mode == "interval":
        return now + timedelta(minutes=cfg.interval_minutes)
    times = sorted(cfg.at_times)
    for h, m in times:
        cand = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if cand > now:
            return cand
    h, m = times[0]
    return (now + timedelta(days=1)).replace(hour=h, minute=m, second=0, microsecond=0)


class Scheduler:
    """Vòng lặp lập lịch. Tiêm now_fn/sleep_fn/jitter_fn để test không chờ thật."""

    def __init__(self, job, cfg: ScheduleConfig, *,
                 now_fn=None, sleep_fn=time.sleep, jitter_fn=random.uniform, log=print):
        self.job = job
        self.cfg = cfg
        self._tz = _resolve_tz(cfg.timezone)
        self.now_fn = now_fn or (lambda: datetime.now(self._tz))
        self.sleep_fn = sleep_fn
        self.jitter_fn = jitter_fn
        self.log = log

    def run(self) -> int:
        """Chạy tới khi đạt max_runs (nếu >0) hoặc mãi mãi. Trả số lần đã chạy."""
        runs = 0
        if self.cfg.run_on_start:
            self._run_once(runs + 1)
            runs += 1
            if self._should_stop(runs):
                return runs
        while True:
            now = self.now_fn()
            nxt = next_run_at(now, self.cfg)
            delay = max(0.0, (nxt - now).total_seconds()) + self._jitter()
            self.log(f"[schedule] lần kế: {nxt.isoformat()} (ngủ {delay:.0f}s)")
            self.sleep_fn(delay)
            self._run_once(runs + 1)
            runs += 1
            if self._should_stop(runs):
                return runs

    # --- nội bộ ----------------------------------------------------------
    def _jitter(self) -> float:
        return self.jitter_fn(0, self.cfg.jitter_s) if self.cfg.jitter_s > 0 else 0.0

    def _should_stop(self, runs: int) -> bool:
        return self.cfg.max_runs > 0 and runs >= self.cfg.max_runs

    def _run_once(self, n: int):
        started = self.now_fn()
        self.log(f"[schedule] === chạy #{n} @ {started.isoformat()} ===")
        try:
            result = self.job()
            self.log(f"[schedule] xong #{n}: {result}")
            return result
        except Exception as e:  # scheduler KHÔNG chết vì 1 lần crawl lỗi
            self.log(f"[schedule] LỖI #{n}: {e!r} -> tiếp tục lịch")
            return None
