"""SYSTEM POWER ON — khởi động CẢ 2 lịch (crawl + sản xuất --draft) + local
asset server (Sheet UI cleanup Phase 6d, TẮT mặc định) trong 1 tiến trình.

Đặt ở THƯ MỤC GỐC dự án (không phải scripts/) — đây là lệnh gọi HỆ THỐNG
(khởi động toàn bộ automation), khác các script trong scripts/ vốn là công cụ
đơn lẻ (crawl 1 lượt, migrate Sheet, render 1 asset...). Đặt ở gốc để người
vào thư mục dự án THẤY NGAY đây là lệnh khởi động chính, không phải đào vào
scripts/ mới biết.

Chạy:
    python system_power_on.py

Dừng: Ctrl+C (dừng toàn bộ lịch + service cùng lúc).

Mỗi lịch đọc 1 section riêng trong settings.yaml (schedule.schedule_config cho
crawl, schedule_draft cho --draft — xem src/twmkt/schedule.py) và chạy trong 1
thread daemon riêng (Scheduler.run() là vòng lặp chặn, không có cơ chế huỷ nội
bộ). Tiến trình chính chỉ chờ (join theo nhịp) và bắt Ctrl+C để thoát gọn.

Lịch nào `<section>.enabled=false` trong config thì KHÔNG khởi động (in rõ lý
do), không lỗi. Nếu KHÔNG lịch/service nào bật, in hướng dẫn rồi thoát ngay
(không treo tiến trình).

`storage.asset_server_enabled` (mặc định `false`) — local static file server
(twmkt.asset_server, phục vụ AssetPath HYPERLINK trên Sheet, xem `scripts/
serve_assets.py` cho bản chạy tay riêng lẻ + `docs/HANDOFF.md` Phase 6c). ĐANG
TẮT trên máy dev cục bộ — bật (`true`) khi triển khai VPS để system_power_on.py
TỰ chạy full service, không cần lệnh tay riêng.

LOCK FILE (<data_root>/logs/power_on.lock, ghi "hostname:pid" — data_root NGOÀI
repo, xem Phase DATA-ROOT / config.data_path()): tự CHẶN 2 tiến trình
system_power_on.py chạy CÙNG LÚC trên CÙNG máy (2 tiến trình cùng gọi Sheets
API dễ vượt quota 429 gấp đôi). Máy KHÁC ghi lock trước -> chỉ CẢNH BÁO (1 file
cục bộ không thể chặn liên-máy) — tự kiểm tra máy đó nếu dùng CHUNG service
account.
"""
from __future__ import annotations

import atexit
import os
import socket
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

from twmkt import factory  # noqa: E402
from twmkt.asset_server import DEFAULT_PORT, build_server  # noqa: E402
from twmkt.config import data_path, load_brand, load_settings  # noqa: E402
from twmkt.schedule import ScheduleConfig, Scheduler  # noqa: E402


def _lock_path() -> Path:
    """Phase DATA-ROOT: lock file giờ nằm dưới data_root (NGOÀI repo), KHÔNG
    còn hard-code REPO_ROOT/"storage"/... — resolve LAZY (không phải hằng số
    module-level) để tránh đọc settings.yaml ngay lúc import. Tên file lock
    ("power_on.lock") KHÔNG đổi theo tên script — đây là artifact runtime nội
    bộ, độc lập với vị trí/tên file gọi lệnh."""
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
    """Tự chặn 2 tiến trình system_power_on.py CÙNG LÚC trên CÙNG máy. Máy
    KHÁC (khác hostname) đang giữ lock -> chỉ CẢNH BÁO rồi tiếp tục (không có
    cách chặn liên-máy từ 1 file cục bộ) — gợi ý user tự kiểm tra tránh đụng
    quota chung. `path=None` -> tự resolve qua _lock_path() (data_root, Phase
    DATA-ROOT)."""
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
                    f"[power-on] Đã có tiến trình system_power_on.py khác đang chạy trên máy "
                    f"này (PID {old_pid}, lock: {path}). Dừng tiến trình đó trước (hoặc xoá "
                    f"file lock nếu chắc chắn nó đã chết) rồi chạy lại."
                )
            print(f"[power-on] Lock cũ (PID {old_pid}) không còn sống trên máy này — dọn và tiếp tục.")
        else:
            print(f"[power-on] CẢNH BÁO: lock file hiện do máy khác ghi (hostname={old_host!r}, "
                  f"PID {old_pid}). Nếu máy đó ĐANG chạy system_power_on.py dùng CHUNG service "
                  f"account Google Sheets với máy này, cả 2 sẽ cùng gọi API và dễ vượt quota (429). "
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


def _start_asset_server(settings) -> threading.Thread | None:
    """Sheet UI cleanup Phase 6d — local static file server (twmkt.asset_
    server, dùng bởi AssetPath HYPERLINK http://127.0.0.1:PORT/... trên Sheet
    — xem scripts/render_production_assets.py + scripts/serve_assets.py cho
    bản chạy tay riêng lẻ). TẮT MẶC ĐỊNH (storage.asset_server_enabled=false)
    — CHƯA bật ngay bây giờ, chỉ VIẾT SẴN đường chạy để lên VPS chỉ cần đổi
    1 dòng config (asset_server_enabled: true) là system_power_on.py TỰ khởi
    động cùng 2 lịch crawl/draft, không cần sửa code.

    KHÁC 2 lịch trên (SCHEDULES/Scheduler — chạy job() LẶP theo interval):
    đây là 1 server serve_forever() DUY NHẤT, sống suốt vòng đời
    system_power_on.py — không có khái niệm "interval". Đăng ký atexit riêng
    để dừng CẢ vòng lặp lẫn socket khi system_power_on.py thoát (Ctrl+C hoặc
    lỗi), không phụ thuộc cơ chế join() của luồng Scheduler."""
    if not bool(settings.get("storage.asset_server_enabled", False)):
        print("[asset-server] TẮT (storage.asset_server_enabled=false trong settings.yaml) — bỏ qua.")
        return None
    output_root = data_path(settings.get("storage.output_dir", "output"), settings=settings)
    port = int(settings.get("storage.asset_server_port", DEFAULT_PORT))
    server = build_server(output_root, port=port)
    print(f"[asset-server] BẬT: phục vụ {output_root} tại http://127.0.0.1:{port}/")
    t = threading.Thread(target=server.serve_forever, name="asset-server", daemon=True)
    t.start()

    def _stop_asset_server() -> None:
        server.shutdown()
        server.server_close()
    atexit.register(_stop_asset_server)
    return t


def main() -> None:
    acquire_lock()   # chặn 2 tiến trình system_power_on.py cùng máy; cảnh báo nếu máy khác đang giữ

    settings = load_settings()

    brand_name = str(load_brand().get("name") or "").strip() or "Marketing Automation"
    print("=" * 60)
    print(f"  {brand_name.upper()} — POWER ON")
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
    asset_server_thread = _start_asset_server(settings)   # TẮT mặc định, xem docstring hàm
    if asset_server_thread is not None:
        threads.append(asset_server_thread)

    if not threads:
        print("\nKhông có lịch/service nào BẬT (schedule.enabled / schedule_draft.enabled / "
             "storage.asset_server_enabled đều false).")
        print("Bật trong config/settings.yaml rồi chạy lại, hoặc dùng script riêng lẻ:")
        print("  python scripts/review_to_sheet.py")
        print("  python scripts/produce_from_sheet.py --draft")
        print("  python scripts/serve_assets.py")
        return

    print(f"\n{len(threads)} lịch/service đang chạy nền. Nhấn Ctrl+C để dừng toàn bộ.\n")
    try:
        while any(t.is_alive() for t in threads):
            for t in threads:
                t.join(timeout=1.0)
    except KeyboardInterrupt:
        print("\n[power-on] Nhận Ctrl+C — đang dừng (job đang chạy sẽ hoàn tất lượt hiện tại)...")


if __name__ == "__main__":
    main()
