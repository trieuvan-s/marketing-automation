"""WATCHDOG queue_worker.py (2026-08-04, Lead: "hệ thống chạy full tính năng
mà không cần thông qua agent") -- kiểm tra tiến trình queue_worker.py còn
sống qua lock file (CÙNG cơ chế `system_power_on.acquire_lock()`/
`is_pid_alive()`, không phát minh lại), khởi động lại nếu KHÔNG.

TẠI SAO KHÔNG DÙNG TRIGGER "At log on"/"At startup" TRỰC TIẾP: Task
Scheduler trên máy này từ chối đăng ký 2 loại trigger đó qua tài khoản hiện
tại ("Access is denied" -- cần quyền nâng cao/lưu mật khẩu, không có trong
môi trường chạy agent). Trigger "MINUTE"/"DAILY" (đã dùng cho lịch crawl,
xem TWMKT-Crawl-*/TWMKT-Draft) KHÔNG cần quyền nâng cao -- watchdog này chạy
lịch MINUTE (vd mỗi 5 phút, xem lệnh đăng ký trong tasks/HANDOFF_*.md) để đạt
HIỆU QUẢ TƯƠNG ĐƯƠNG "tự khởi động lại khi crash", chỉ trễ tối đa 1 chu kỳ
thay vì tức thời.

Chạy:
    python scripts/queue_worker_watchdog.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
# Cùng lý do run_scheduler.py/queue_worker.py -- ép cwd đúng bất kể ai/gì
# khởi động tiến trình (Task Scheduler chạy với cwd mặc định KHÁC repo).
os.chdir(REPO_ROOT)

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

import system_power_on as spo  # noqa: E402 -- tái dùng is_pid_alive()/_read_lock()
from twmkt.config import data_path  # noqa: E402


def _queue_worker_lock_path() -> Path:
    """CÙNG đường dẫn `queue_worker.py::_lock_path()` -- KHÔNG định nghĩa
    lại hằng số riêng, lệch tên là watchdog kiểm nhầm lock của tiến trình
    khác."""
    return data_path("logs", "queue_worker.lock")


def should_relaunch(lock_content: str | None, *, is_pid_alive_fn=spo.is_pid_alive) -> tuple[bool, str]:
    """Hàm THUẦN (không đụng subprocess/đĩa) -- quyết định có cần khởi động
    lại queue_worker.py hay không, dựa trên NỘI DUNG lock file (đã đọc sẵn,
    None nếu file không tồn tại/đọc lỗi). Trả (có_cần_khởi_động, lý_do) để
    log rõ ràng và test được không cần chạm tiến trình thật."""
    if lock_content is None:
        return True, "chưa có lock -- khởi động lần đầu"
    parsed = spo.parse_lock_content(lock_content)
    if parsed is None:
        return True, f"lock hỏng ({lock_content!r}) -- khởi động lại"
    _host, pid = parsed
    if is_pid_alive_fn(pid):
        return False, f"đang chạy (PID {pid})"
    return True, f"lock cũ (PID {pid}) đã chết -- khởi động lại"


def main() -> None:
    lock_path = _queue_worker_lock_path()
    try:
        lock_content = lock_path.read_text(encoding="utf-8")
    except OSError:
        lock_content = None

    relaunch, reason = should_relaunch(lock_content)
    print(f"[watchdog] {reason}")
    if not relaunch:
        return

    python_exe = sys.executable
    script = str(REPO_ROOT / "scripts" / "queue_worker.py")
    subprocess.Popen(
        [python_exe, script],
        cwd=str(REPO_ROOT),
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,  # type: ignore[attr-defined]
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        close_fds=True,
    )
    print("[watchdog] Đã khởi động lại queue_worker.py.")


if __name__ == "__main__":
    main()
