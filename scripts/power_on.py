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

LOCK FILE (<data_root>/logs/power_on.lock, ghi "hostname:pid" — data_root NGOÀI
repo, xem Phase DATA-ROOT / config.data_path()): tự CHẶN 2 tiến trình
power_on.py chạy CÙNG LÚC trên CÙNG máy (2 tiến trình cùng gọi Sheets API dễ
vượt quota 429 gấp đôi). Máy KHÁC ghi lock trước -> chỉ CẢNH BÁO (1 file cục bộ
không thể chặn liên-máy) — tự kiểm tra máy đó nếu dùng CHUNG service account.
"""
from __future__ import annotations

import atexit
import os
import socket
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

from twmkt import factory  # noqa: E402
from twmkt.config import data_path, load_settings  # noqa: E402
from twmkt.schedule import ScheduleConfig, Scheduler  # noqa: E402


def _lock_path() -> Path:
    """Phase DATA-ROOT: lock file giờ nằm dưới data_root (NGOÀI repo), KHÔNG
    còn hard-code REPO_ROOT/"storage"/... — resolve LAZY (không phải hằng số
    module-level) để tránh đọc settings.yaml ngay lúc import."""
    return data_path("logs", "power_on.lock")


# --- Lock file (thuần, test được: parse/pid-alive không cần chạm đĩa/mạng) ---
def parse_lock_content(content: str) -> tuple[str, int] | None:
    """Parse nội dung lock "hostname:pid" -> (hostname, pid); None nếu hỏng."""
    host, sep, pid_s = content.strip().partition(":")
    if not sep:
        return None
    try:
        return host, int(pid_s)
    except ValueError:
        return None


def is_pid_alive(pid: int) -> bool:
    """True nếu tiến trình PID còn sống. os.kill(pid, 0) KHÔNG gửi tín hiệu thật
    (đã kiểm chứng an toàn trên Windows lẫn POSIX) — chỉ kiểm tra tồn tại."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True   # tồn tại nhưng không đủ quyền gửi signal -> coi là còn sống
    except OSError:
        return False
    return True


def _read_lock(path: Path) -> tuple[str, int] | None:
    try:
        return parse_lock_content(path.read_text(encoding="utf-8"))
    except OSError:
        return None


def acquire_lock(path: Path | None = None) -> None:
    """Tự chặn 2 tiến trình power_on.py CÙNG LÚC trên CÙNG máy. Máy KHÁC (khác
    hostname) đang giữ lock -> chỉ CẢNH BÁO rồi tiếp tục (không có cách chặn
    liên-máy từ 1 file cục bộ) — gợi ý user tự kiểm tra tránh đụng quota chung.
    `path=None` -> tự resolve qua _lock_path() (data_root, Phase DATA-ROOT)."""
    path = path or _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    hostname = socket.gethostname()
    pid = os.getpid()

    existing = _read_lock(path)
    if existing is not None:
        old_host, old_pid = existing
        if old_host == hostname:
            if is_pid_alive(old_pid):
                raise SystemExit(
                    f"[power-on] Đã có tiến trình power_on.py khác đang chạy trên máy này "
                    f"(PID {old_pid}, lock: {path}). Dừng tiến trình đó trước (hoặc xoá "
                    f"file lock nếu chắc chắn nó đã chết) rồi chạy lại."
                )
            print(f"[power-on] Lock cũ (PID {old_pid}) không còn sống trên máy này — dọn và tiếp tục.")
        else:
            print(f"[power-on] CẢNH BÁO: lock file hiện do máy khác ghi (hostname={old_host!r}, "
                  f"PID {old_pid}). Nếu máy đó ĐANG chạy power_on.py dùng CHUNG service account "
                  f"Google Sheets với máy này, cả 2 sẽ cùng gọi API và dễ vượt quota (429). "
                  f"KHÔNG thể tự chặn liên-máy chỉ từ 1 file cục bộ — hãy tự kiểm tra máy "
                  f"{old_host!r} trước khi chạy đồng thời.")

    path.write_text(f"{hostname}:{pid}", encoding="utf-8")
    atexit.register(release_lock, path)


def release_lock(path: Path | None = None) -> None:
    """Xoá lock NẾU vẫn còn là của tiến trình này (tránh xoá lock tiến trình
    khác đã ghi đè sau khi mình dọn chậm). `path=None` -> tự resolve qua
    _lock_path() (data_root, Phase DATA-ROOT)."""
    path = path or _lock_path()
    try:
        if _read_lock(path) == (socket.gethostname(), os.getpid()):
            path.unlink()
    except OSError:
        pass

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
    acquire_lock()   # chặn 2 tiến trình power_on.py cùng máy; cảnh báo nếu máy khác đang giữ

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
