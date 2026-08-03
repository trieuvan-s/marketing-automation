"""ADAPTER Google Drive — đẩy sản phẩm CUỐI CÙNG lên Drive rồi trả link CÔNG
KHAI dùng làm AssetPath trên Sheet (2026-07-28, yêu cầu Lead).

VÌ SAO CẦN: AssetPath trước đây là `http://127.0.0.1:8898/...` (asset server
cục bộ) — CHỈ mở được trên chính máy đã render. Lên VPS thì người duyệt Gate 3
ngồi máy khác, link đó vô dụng. Drive cho link chia sẻ thật, không phải mở cổng
firewall trên VPS.

CẤU TRÚC THƯ MỤC (tạo tự động, idempotent):
    <thư mục gốc cấu hình>/<loại nội dung>/<dd-mm-yyyy>/<tên chủ đề>/<file>
vd: Marketing-DB/infographic/28-07-2026/bctc-quy-2-2026-msr/...9x16.png

QUYỀN (theo quyết định Lead):
  - Owner (Lead) + Service Account: ghi/sửa/xoá. Có SẴN, không phải cấp ở đây —
    thư mục gốc do Lead sở hữu và đã share Editor cho SA.
  - Mọi người khác: XEM/TẢI qua link (`anyone` / `reader`), đặt trên TỪNG FILE
    (không đặt trên thư mục) — hẹp nhất có thể mà vẫn đủ dùng: chia sẻ 1 ảnh
    KHÔNG kéo theo lộ toàn bộ thư mục ngày hay cả kho.

GIỚI HẠN PHẢI BIẾT: service account KHÔNG có quota Drive riêng. File tạo ở đây
tính vào quota của CHỦ thư mục gốc (Lead), và Lead vẫn là người sở hữu — đúng
điều Lead đã chọn. Nếu thư mục gốc không được share Editor cho SA, mọi lời gọi
sẽ lỗi 404 (Drive giấu sự tồn tại của thứ bạn không có quyền, KHÔNG trả 403) —
`DriveConfigError` bên dưới dịch lại cho dễ hiểu thay vì để lỗi thô khó đoán.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

# `drive.file` (KHÔNG phải `drive` đầy đủ) — quyết định có chủ đích, 2 lý do:
#  1. `drive.file` là scope KHÔNG NHẠY CẢM -> màn hình OAuth chuyển sang "In
#     production" được NGAY, không cần Google xét duyệt. Để ở "Testing" thì
#     refresh token HẾT HẠN SAU 7 NGÀY — hệ thống chạy nền trên VPS sẽ chết
#     lặng lẽ mỗi tuần. Scope `drive` đầy đủ là NHẠY CẢM, muốn production phải
#     qua verification (nhiều tuần).
#  2. Quyền hẹp nhất đủ dùng: app CHỈ đụng được file/thư mục do CHÍNH NÓ tạo,
#     không đọc được phần còn lại trong Drive của Lead. Thư mục gốc vẫn dùng
#     được vì ta chỉ truyền id nó làm `parents`, không cần đọc nội dung nó.
_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
_FOLDER_MIME = "application/vnd.google-apps.folder"
# VIỆC 2 (2026-08-03, Lead) — mimeType ĐÍCH khi muốn Drive convert file văn bản
# thành Google Docs NATIVE (heading/mục lục thật, không còn hiển thị dấu #).
# ĐỪNG tự dựng bộ chuyển đổi markdown->docx — Drive tự parse khi mimeType
# metadata KHÁC mimeType của phần media upload (xem upload()).
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"


class DriveConfigError(RuntimeError):
    """Cấu hình/quyền Drive sai — thông điệp nêu rõ việc NGƯỜI phải làm."""


def slug_folder(text: str, n: int = 60) -> str:
    """Tên thư mục chủ đề: bỏ dấu tiếng Việt KHÔNG cần thiết (Drive nhận
    Unicode tốt), chỉ gọn hoá khoảng trắng và ký tự gây rối khi copy đường
    dẫn. Cắt `n` ký tự để tên không dài lê thê."""
    keep = re.sub(r"[\\/:*?\"<>|]+", "-", (text or "").strip())
    keep = re.sub(r"\s+", " ", keep)
    return keep[:n].strip(" -.") or "khong-ten"


def load_user_credentials(token_path: str, client_path: str = ""):
    """Credential NGƯỜI DÙNG (OAuth) đọc từ `token_path`, tự làm mới khi hết
    hạn access token và ghi lại file.

    VÌ SAO KHÔNG DÙNG SERVICE ACCOUNT (kiểm chứng THẬT 2026-07-28, không phải
    suy đoán từ tài liệu): SA tạo được THƯ MỤC trong My Drive nhưng upload FILE
    thì Google chặn cứng —
      `Service Accounts do not have storage quota. Leverage shared drives, or
       use OAuth delegation instead.`
    Chia sẻ thư mục quyền Editor cho SA KHÔNG gỡ được rào này; nó là giới hạn
    hạ tầng, không phải thiếu quyền. Shared Drive cần Google Workspace trả phí,
    nên với tài khoản Gmail thường OAuth là đường DUY NHẤT. File upload theo
    đường này do CHÍNH LEAD sở hữu, tính vào quota 15GB của Lead."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    p = Path(token_path)
    if not p.exists():
        raise DriveConfigError(
            f"Chưa uỷ quyền Drive: không thấy {token_path}. Chạy MỘT LẦN:\n"
            f"    python scripts/drive_authorize.py\n"
            f"(cần {client_path or 'file OAuth client'} tải từ Google Cloud Console — "
            f"xem hướng dẫn trong chính script đó).")
    creds = Credentials.from_authorized_user_file(str(p), _SCOPES)
    if not creds.valid:
        if not (creds.expired and creds.refresh_token):
            raise DriveConfigError(
                f"Token Drive ({token_path}) hỏng hoặc thiếu refresh_token — chạy lại "
                f"`python scripts/drive_authorize.py`.")
        creds.refresh(Request())
        p.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _service(*, token_path: str, client_path: str = ""):
    from googleapiclient.discovery import build

    creds = load_user_credentials(token_path, client_path)
    # cache_discovery=False: tránh cảnh báo oauth2client + ghi cache đĩa không
    # cần thiết (tiến trình worker chạy dài, không hưởng lợi từ cache này).
    return build("drive", "v3", credentials=creds, cache_discovery=False)


class DriveAssetStore:
    """Đẩy file lên Drive theo cây `<loại>/<ngày>/<chủ đề>` và trả link xem.

    `folder_id` = ID thư mục GỐC (config `drive.folder_id`) — KHÔNG hard-code
    trong code, đổi thư mục chỉ sửa config đúng kỷ luật config-first.
    `service` tiêm được để test không chạm mạng."""

    def __init__(self, *, folder_id: str, token_path: str = "", client_path: str = "",
                 service=None, make_public: bool = True):
        if not (folder_id or "").strip():
            raise DriveConfigError(
                "Thiếu drive.folder_id trong config/settings.yaml — điền ID thư mục gốc "
                "trên Drive (phần sau /folders/ trong URL).")
        self.folder_id = folder_id.strip()
        self._token_path = token_path
        self._client_path = client_path
        self._svc = service
        self.make_public = make_public

    @property
    def svc(self):
        if self._svc is None:
            self._svc = _service(token_path=self._token_path, client_path=self._client_path)
        return self._svc

    # --- thư mục ------------------------------------------------------------
    def ensure_folder(self, name: str, parent_id: str) -> str:
        """ID thư mục `name` dưới `parent_id` — tìm trước, chưa có mới tạo
        (IDEMPOTENT: chạy lại cùng ngày/cùng chủ đề KHÔNG đẻ thư mục trùng).

        Drive CHO PHÉP 2 thư mục trùng tên cùng cấp — nên bắt buộc phải tìm
        trước; nếu chỉ create() thì mỗi lượt render lại sinh thêm 1 thư mục
        cùng tên, vài ngày là loạn."""
        safe = name.replace("'", r"\'")
        q = (f"name = '{safe}' and mimeType = '{_FOLDER_MIME}' "
             f"and '{parent_id}' in parents and trashed = false")
        res = self.svc.files().list(
            q=q, fields="files(id,name)", pageSize=1,
            supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        found = res.get("files") or []
        if found:
            return found[0]["id"]
        meta = {"name": name, "mimeType": _FOLDER_MIME, "parents": [parent_id]}
        created = self.svc.files().create(
            body=meta, fields="id", supportsAllDrives=True).execute()
        return created["id"]

    def ensure_path(self, parts: list[str]) -> str:
        """Tạo/tìm cả chuỗi thư mục lồng nhau từ `folder_id`, trả ID lá."""
        parent = self.folder_id
        for p in parts:
            parent = self.ensure_folder(p, parent)
        return parent

    # --- file ---------------------------------------------------------------
    def topic_folder_parts(self, topic: str, folder_date: datetime | None = None,
                           topic_key: str = "") -> list[str]:
        """Đường thư mục cho 1 chủ đề: `["<dd-mm-yyyy>", "<TopicKey>-<5 chữ đầu>"]`
        (2026-07-28, quyết định Lead).

        Gom theo NGÀY ở tầng ngoài (mỗi ngày 1 thư mục, dễ tìm/dọn theo lô),
        rồi tới thư mục chủ đề. Tên chủ đề dùng TopicKey ĐỨNG TRƯỚC — danh tính
        BỀN, không đổi khi tiêu đề bài được sửa (kỷ luật Lớp 5) — kèm 5 chữ đầu
        của nội dung để người liếc còn đoán được đó là bài gì, vì TopicKey trần
        (sha256) thì không ai đọc nổi.

        MỌI định dạng đầu ra của chủ đề (article/infographic/video) nằm CHUNG
        thư mục này — cây cũ `<loại>/<ngày>/<chủ đề>` xẻ lẻ sản phẩm cùng bài
        ra 3 nhánh, muốn xem đủ bộ phải mở 3 chỗ."""
        day = (folder_date or datetime.now()).strftime("%d-%m-%Y")
        head = slug_folder(topic, n=5) if topic else ""
        key = (topic_key or "").strip() or "khong-khoa"
        return [day, f"{key}-{head}" if head else key]

    def upload(self, local_path: Path | str, *, content_type: str = "",
               folder_date: datetime | None = None, topic: str = "",
               topic_key: str = "", mime_type: str = "image/png",
               target_mime_type: str = "") -> dict:
        """Đẩy 1 file lên `<tên chủ đề>-<dd-mm-yyyy>/` và trả
        {"id", "view_link", "download_link", "folder_id"}. `content_type` giữ
        lại cho tương thích chữ ký cũ nhưng KHÔNG còn tạo tầng thư mục riêng.

        `target_mime_type` (VIỆC 2, 2026-08-03) — khi khác rỗng (vd
        GOOGLE_DOC_MIME), Drive TỰ convert nội dung `mime_type` (vd
        "text/markdown") sang định dạng native đó lúc upload — KHÔNG tự dựng
        bộ chuyển đổi markdown->docx ở đây, chỉ khai đúng 2 mimeType để Drive
        làm hộ (metadata mimeType KHÁC mimeType media -> Drive hiểu là yêu cầu
        convert). Rỗng (mặc định) -> giữ nguyên hành vi cũ (ảnh/video/json,
        không convert gì).

        Trùng tên trong CÙNG thư mục -> GHI ĐÈ (update) thay vì tạo bản thứ 2:
        render lại cùng 1 chủ đề trong ngày là chuyện thường (sửa Output rồi
        duyệt lại), 2 file cùng tên khiến người duyệt Gate 3 không biết tin cái
        nào. `update()` KHÔNG nhận lại `mimeType` (Drive không cho đổi mimeType
        qua update cho file NATIVE đã tồn tại) — media convertible (text/
        markdown) tự động re-convert vào ĐÚNG file Docs đã có, không tạo file mới."""
        from googleapiclient.http import MediaFileUpload

        path = Path(local_path)
        if not path.exists():
            raise FileNotFoundError(f"Không thấy file để upload: {path}")
        folder_id = self.ensure_path(self.topic_folder_parts(topic, folder_date, topic_key))

        safe = path.name.replace("'", r"\'")
        existing = self.svc.files().list(
            q=f"name = '{safe}' and '{folder_id}' in parents and trashed = false",
            fields="files(id)", pageSize=1,
            supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get("files") or []

        media = MediaFileUpload(str(path), mimetype=mime_type, resumable=False)
        if existing:
            file_id = self.svc.files().update(
                fileId=existing[0]["id"], media_body=media, fields="id",
                supportsAllDrives=True).execute()["id"]
        else:
            body = {"name": path.name, "parents": [folder_id]}
            if target_mime_type:
                body["mimeType"] = target_mime_type
            file_id = self.svc.files().create(
                body=body, media_body=media,
                fields="id", supportsAllDrives=True).execute()["id"]

        if self.make_public:
            self.share_public(file_id)
        return {
            "id": file_id,
            "view_link": f"https://drive.google.com/file/d/{file_id}/view",
            "download_link": f"https://drive.google.com/uc?export=download&id={file_id}",
            "folder_id": folder_id,
        }

    def share_public(self, file_id: str) -> None:
        """`anyone` / `reader` — ai có link đều XEM và TẢI được, KHÔNG sửa được
        (quyết định Lead). Đặt trên TỪNG FILE, không phải thư mục.

        Bỏ qua lỗi "đã tồn tại quyền này" -> idempotent khi upload đè."""
        try:
            self.svc.permissions().create(
                fileId=file_id, body={"type": "anyone", "role": "reader"},
                fields="id", supportsAllDrives=True).execute()
        except Exception as e:   # noqa: BLE001
            if "duplicate" not in str(e).lower() and "already" not in str(e).lower():
                raise


def build_drive_store(settings) -> DriveAssetStore | None:
    """Dựng adapter theo config (`drive.*`) — `None` khi `drive.enabled=false`,
    để caller LÙI MƯỢT về asset server cục bộ thay vì nổ. CÙNG NẾP các adapter
    khác (xem twmkt/factory.py)."""
    if not bool(settings.get("drive.enabled", False)):
        return None
    return DriveAssetStore(
        folder_id=str(settings.get("drive.folder_id", "") or ""),
        token_path=str(settings.get("drive.oauth_token_path", "secrets/drive_token.json")),
        client_path=str(settings.get("drive.oauth_client_path", "secrets/oauth_client.json")),
        make_public=bool(settings.get("drive.make_public", True)),
    )
