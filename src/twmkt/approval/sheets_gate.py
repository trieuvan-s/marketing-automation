"""Cổng duyệt qua Google Sheets — hiện thực nguyên tắc "Sheets chỉ là UI".

Sheets đóng vai control-plane cho cổng duyệt người-trong-vòng-lặp:
  1. Pipeline ghi 1 dòng "chờ duyệt" vào worksheet.
  2. Người dùng chọn Decision trong dropdown (APPROVE/REJECT/REVISE).
  3. Pipeline poll ô Decision tới khi có quyết định (hoặc hết giờ).

Vì lớp này implement đúng protocol ApprovalGate (review(label, payload) ->
Decision), sau này thay bằng Dashboard/React chỉ cần viết adapter khác — LÕI
KHÔNG ĐỔI. Đây là cách "Google Sheets chỉ là UI, thay được".

HỢP ĐỒNG CỘT mỗi worksheet:
  A: timestamp | B: gate | C: label | D: payload | E: Decision | F: Notes
Decision hợp lệ (không phân biệt hoa/thường): PENDING (mặc định), APPROVE,
REJECT, REVISE.

Phụ thuộc production: pip install gspread google-auth
Import được hoãn để môi trường offline/test không cần thư viện này.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from ..models import Decision

_HEADER = ["timestamp", "gate", "label", "payload", "Decision", "Notes"]
_MAP = {
    "APPROVE": Decision.APPROVE,
    "REJECT": Decision.REJECT,
    "REVISE": Decision.REVISE,
}


class SheetsApprovalGate:
    def __init__(
        self,
        *,
        spreadsheet_id: str,
        worksheet: str,
        creds_path: str,
        gate_name: str = "gate",
        poll_interval_s: int = 15,
        timeout_s: int = 86_400,
        on_timeout: Decision = Decision.REJECT,
    ):
        if not spreadsheet_id or not creds_path:
            raise ValueError(
                "Thiếu spreadsheet_id/creds_path — đặt TWMKT_SHEET_ID và "
                "TWMKT_SHEETS_CREDS rồi cấu hình trong settings.yaml (mục sheets)."
            )
        self.spreadsheet_id = spreadsheet_id
        self.worksheet = worksheet
        self.creds_path = creds_path
        self.gate_name = gate_name
        self.poll_interval_s = poll_interval_s
        self.timeout_s = timeout_s
        self.on_timeout = on_timeout
        self._ws = None

    # --- kết nối (lazy) --------------------------------------------
    def _open(self):
        if self._ws is not None:
            return self._ws
        try:
            import gspread
            from google.oauth2.service_account import Credentials
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "Cần: pip install gspread google-auth"
            ) from e

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(self.creds_path, scopes=scopes)
        client = gspread.authorize(creds)
        sh = client.open_by_key(self.spreadsheet_id)
        try:
            ws = sh.worksheet(self.worksheet)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=self.worksheet, rows=1000, cols=len(_HEADER))
            ws.append_row(_HEADER)
        # đảm bảo có header
        if ws.row_values(1) != _HEADER:
            ws.update("A1", [_HEADER])
        self._ws = ws
        return ws

    # --- ApprovalGate protocol -------------------------------------
    def review(self, label: str, payload: str) -> Decision:
        ws = self._open()
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        ws.append_row([ts, self.gate_name, label, payload, "PENDING", ""],
                      value_input_option="RAW")
        row = len(ws.get_all_values())  # dòng vừa thêm (MVP: 1 writer)

        waited = 0
        while waited < self.timeout_s:
            raw = (ws.cell(row, 5).value or "").strip().upper()  # cột E
            decision = _MAP.get(raw)
            if decision is not None:
                return decision
            time.sleep(self.poll_interval_s)
            waited += self.poll_interval_s
        return self.on_timeout


def from_settings(settings, *, gate: str) -> SheetsApprovalGate:
    """Khởi tạo gate từ Settings. gate = 'research' | 'content'."""
    ws_key = "research_worksheet" if gate == "research" else "content_worksheet"
    on_to = settings.get("sheets.on_timeout", "reject").upper()
    return SheetsApprovalGate(
        spreadsheet_id=settings.get("sheets.spreadsheet_id"),
        worksheet=settings.get(f"sheets.{ws_key}", f"{gate}Review"),
        creds_path=settings.get("sheets.creds_path"),
        gate_name=gate,
        poll_interval_s=int(settings.get("sheets.poll_interval_s", 15)),
        timeout_s=int(settings.get("sheets.timeout_s", 86_400)),
        on_timeout=_MAP.get(on_to, Decision.REJECT),
    )
