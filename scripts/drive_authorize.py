"""Uỷ quyền Drive MỘT LẦN — chạy tay, KHÔNG phải job tự động.

    python scripts/drive_authorize.py

VÌ SAO CẦN (kiểm chứng thật 2026-07-28): Service Account KHÔNG upload được
file vào My Drive — Google chặn cứng "Service Accounts do not have storage
quota", kể cả khi thư mục đã share quyền Editor cho SA. Shared Drive gỡ được
rào đó nhưng cần Google Workspace trả phí. Với tài khoản Gmail thường, OAuth
là đường DUY NHẤT: file upload dưới danh nghĩa CHÍNH LEAD, do Lead sở hữu.

CHUẨN BỊ (làm 1 lần trên Google Cloud Console, project của Service Account —
xem `project_id` trong secrets/sa.json):

 1. APIs & Services -> OAuth consent screen
      · User type: External
      · Điền tên app + email hỗ trợ + email liên hệ (nội dung không quan trọng,
        app này chỉ mình bạn dùng)
      · Scope: KHÔNG cần thêm tay, script tự xin `drive.file`
      · ⚠️ QUAN TRỌNG — Publishing status: bấm "PUBLISH APP" để chuyển sang
        "In production". Để ở "Testing" thì refresh token HẾT HẠN SAU 7 NGÀY
        và hệ thống nền sẽ chết lặng lẽ mỗi tuần. `drive.file` là scope KHÔNG
        nhạy cảm nên publish được NGAY, không cần Google xét duyệt.

 2. APIs & Services -> Credentials -> Create credentials -> OAuth client ID
      · Application type: **Desktop app**
      · Tải JSON về, lưu thành `secrets/oauth_client.json`
        (thư mục secrets/ đã nằm trong .gitignore — KHÔNG commit)

 3. Chạy script này. Trình duyệt mở ra -> đăng nhập ĐÚNG tài khoản sở hữu thư
    mục Drive -> Allow. Màn hình "Google hasn't verified this app" là BÌNH
    THƯỜNG với app tự dựng: Advanced -> Go to <tên app> (unsafe).

 4. Token lưu vào `secrets/drive_token.json`. Từ đó mọi tiến trình nền tự dùng,
    KHÔNG phải đăng nhập lại.

CHẠY TRÊN VPS KHÔNG CÓ TRÌNH DUYỆT: chạy script này trên máy CÓ trình duyệt
rồi copy `secrets/drive_token.json` (kèm `secrets/oauth_client.json`) sang VPS
— token không gắn với máy nào cả.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

from twmkt.config import load_settings  # noqa: E402
from twmkt.publishers.drive_store import _SCOPES  # noqa: E402


def main() -> int:
    settings = load_settings()
    client_path = Path(str(settings.get("drive.oauth_client_path", "secrets/oauth_client.json")))
    token_path = Path(str(settings.get("drive.oauth_token_path", "secrets/drive_token.json")))

    if not client_path.exists():
        print(f"[LỖI] Không thấy {client_path} — làm bước 1+2 trong docstring đầu file này "
              f"(tạo OAuth client kiểu 'Desktop app' rồi lưu JSON vào đúng đường dẫn đó).")
        return 1

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client_path), _SCOPES)
    # access_type=offline + prompt=consent: BẮT BUỘC để Google phát
    # refresh_token. Thiếu, lần uỷ quyền thứ 2 trở đi Google chỉ trả access
    # token 1 giờ -> tiến trình nền chết sau 1 tiếng, rất khó đoán nguyên nhân.
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    print(f"[OK] Đã lưu token vào {token_path}")
    print(f"[OK] refresh_token: {'CÓ' if creds.refresh_token else 'KHÔNG — chạy lại, thiếu cái này tiến trình nền sẽ chết sau 1 giờ'}")
    print("\nKiểm chứng: python scripts/drive_authorize.py --check")
    return 0


def check() -> int:
    """Gọi Drive thật bằng token đã lưu — xác nhận uỷ quyền dùng được."""
    settings = load_settings()
    from twmkt.publishers.drive_store import build_drive_store

    st = build_drive_store(settings)
    if st is None:
        print("[LỖI] drive.enabled=false trong settings.yaml.")
        return 1
    about = st.svc.about().get(fields="user(emailAddress),storageQuota(limit,usage)").execute()
    print(f"[OK] Uỷ quyền dưới tài khoản: {about['user']['emailAddress']}")
    q = about.get("storageQuota", {})
    if q.get("limit"):
        print(f"[OK] Dung lượng đã dùng: {int(q.get('usage', 0))/2**30:.2f} GB "
              f"/ {int(q['limit'])/2**30:.2f} GB")
    return 0


if __name__ == "__main__":
    raise SystemExit(check() if "--check" in sys.argv[1:] else main())
