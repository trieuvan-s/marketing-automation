"""Nạp cấu hình từ config/settings.yaml (nguyên tắc config-first).

- Truy cập bằng đường dẫn chấm: settings.get("crawl.rate_limit_s", 1.5)
- Bí mật tham chiếu qua ${ENV}: tự expand từ biến môi trường (không hard-code
  id/khóa trong repo).
- Luôn đọc UTF-8 (tránh lỗi cp1252 trên Windows).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:  # phụ thuộc tùy chọn để import offline không vỡ
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

DEFAULT_PATH = "config/settings.yaml"
DEFAULT_DOTENV_PATH = "secrets/.env"


def _load_dotenv() -> None:
    """Nạp bí mật BỀN từ secrets/.env (gitignored) qua python-dotenv, vd
    ANTHROPIC_API_KEY — khỏi phải `set`/`export` lại mỗi phiên shell.

    override=False: biến đã có sẵn trong môi trường (CI, shell) LUÔN thắng file.
    Thiếu thư viện python-dotenv hoặc chưa tạo file -> bỏ qua êm (không lỗi),
    đường dẫn override được qua TWMKT_DOTENV (cùng nếp với TWMKT_CONFIG).
    """
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - phụ thuộc tùy chọn
        return
    p = Path(os.environ.get("TWMKT_DOTENV", DEFAULT_DOTENV_PATH))
    if p.exists():
        load_dotenv(p, override=False)


def _expand(node: Any) -> Any:
    if isinstance(node, str):
        return os.path.expandvars(node)          # $VAR và ${VAR}
    if isinstance(node, dict):
        return {k: _expand(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_expand(v) for v in node]
    return node


class Settings:
    def __init__(self, data: dict):
        self._data = data or {}

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self._data
        for part in dotted.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur

    def section(self, name: str) -> dict:
        v = self._data.get(name, {})
        return v if isinstance(v, dict) else {}

    def enabled_sources(self) -> list[dict]:
        return [s for s in self._data.get("sources", []) if s.get("enabled")]

    @property
    def raw(self) -> dict:
        return self._data


def load_settings(path: str | os.PathLike | None = None) -> Settings:
    _load_dotenv()   # secrets/.env -> os.environ TRƯỚC khi expand ${ANTHROPIC_API_KEY}...
    p = Path(path or os.environ.get("TWMKT_CONFIG", DEFAULT_PATH))
    if yaml is None:
        raise RuntimeError("Cần cài PyYAML: pip install pyyaml")
    if not p.exists():
        raise FileNotFoundError(f"Không thấy file cấu hình: {p}")
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Settings(_expand(data))


class ProductionSheetBlocked(SystemExit):
    """Raise khi 1 luồng THỬ NGHIỆM (benchmark/A-B) cố đọc sheet production mà
    KHÔNG có cờ allow_production=True tường minh — xem resolve_sheet_id()."""


def resolve_sheet_id(settings: Settings, *, allow_production: bool = False) -> str:
    """RÀO CHẮN MÔI TRƯỜNG (Content Factory Phase D) — chọn spreadsheet_id cho
    CÁC LUỒNG THỬ NGHIỆM (benchmark/A-B/Phase 3 trở đi). KHÁC HẲN cách các
    script sản xuất (produce_from_sheet.py, render_production_assets.py...) tự
    đọc `os.environ.get("TWMKT_SHEET_ID") or settings.get("sheets.spreadsheet_
    id")` trực tiếp — NHỮNG NƠI ĐÓ cố ý trỏ production, KHÔNG đổi.

    MẶC ĐỊNH (`allow_production=False`, PHẢI LÀ MẶC ĐỊNH Ở MỌI NƠI GỌI — không
    dựa vào trí nhớ người chạy): LUÔN đọc `sheets.test_spreadsheet_id` (hoặc
    ENV `TWMKT_TEST_SHEET_ID`) — KHÔNG BAO GIỜ, DÙ TWMKT_SHEET_ID/sheets.
    spreadsheet_id (production) CÓ SET SẴN TRONG MÔI TRƯỜNG, tự ý lùi về đó.
    Thiếu cấu hình sheet TEST -> raise ProductionSheetBlocked (SystemExit) —
    THÀ DỪNG HẲN còn hơn lỡ ghi nhầm production.

    Chỉ trả sheet production khi `allow_production=True` ĐƯỢC TRUYỀN TƯỜNG
    MINH bởi nơi gọi (vd cờ CLI `--production`, người vận hành phải tự gõ
    thêm, KHÔNG BAO GIỜ là giá trị mặc định của cờ đó)."""
    if allow_production:
        sheet_id = (os.environ.get("TWMKT_SHEET_ID") or settings.get("sheets.spreadsheet_id") or "").strip()
        if not sheet_id:
            raise ProductionSheetBlocked(
                "allow_production=True nhưng thiếu TWMKT_SHEET_ID / sheets.spreadsheet_id.")
        return sheet_id
    test_id = (os.environ.get("TWMKT_TEST_SHEET_ID") or settings.get("sheets.test_spreadsheet_id") or "").strip()
    if not test_id:
        raise ProductionSheetBlocked(
            "Thiếu sheets.test_spreadsheet_id / ENV TWMKT_TEST_SHEET_ID — benchmark/A-B "
            "PHẢI trỏ sheet TEST, KHÔNG tự ý lùi về sheet production. Tạo 1 Google Sheet "
            "TEST riêng rồi set biến này, hoặc truyền allow_production=True (cờ --production) "
            "nếu THẬT SỰ cần chạy trên production.")
    return test_id


DEFAULT_BRAND_PATH = "config/brand.yaml"


def load_brand(path: str | os.PathLike | None = None) -> dict:
    """Nạp `config/brand.yaml` — brand kit MỘT NGUỒN (màu/font/wordmark/
    footer), TÁCH khỏi settings.yaml có chủ đích (Production Factory Phase
    1.2, quyết định #4): nhiều renderer (SVG `render/infographic.py` hiện tại,
    CSS cho template video sau — Phase 2) đều đọc CHUNG file này thay vì mỗi
    renderer tự khai màu riêng. `render.infographic.*` trong settings.yaml VẪN
    giữ vai trò LAYOUT (width/height — kích thước, khác brand identity) và có
    thể GHI ĐÈ TỪNG token brand riêng lẻ nếu cần (xem
    render/infographic.brand_kit_from_settings).

    LÙI MƯỢT (khác load_settings — brand.yaml là bổ trợ, không bắt buộc để hệ
    thống chạy): thiếu PyYAML/thiếu file/lỗi parse -> trả `{}`, KHÔNG raise —
    caller (renderer) tự có màu mặc định nội bộ khi thiếu."""
    p = Path(path or os.environ.get("TWMKT_BRAND", DEFAULT_BRAND_PATH))
    if yaml is None or not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return {}
    brand = _expand(data).get("brand", {})
    return brand if isinstance(brand, dict) else {}


def default_user_agent(*, version: str = "0.2", contact: str = "") -> str:
    """User-Agent mặc định cho collector HTTP/RSS (crawl.user_agent trong
    settings.yaml GHI ĐÈ giá trị này khi cấu hình) — tên bot ghép từ
    brand.name (config/brand.yaml, MỘT NGUỒN — Content Factory Phase D, vá rò
    brand cũ: hằng số hard-code cũ trong collectors/ không theo kịp lúc đổi
    brand). ASCII-only (header HTTP không nhận ký tự ngoài ASCII/latin-1) — bỏ
    dấu/khoảng trắng khỏi tên bằng cách chỉ giữ ký tự ASCII chữ/số."""
    name = str(load_brand().get("name") or "").strip()
    token = "".join(c for c in name if c.isascii() and c.isalnum()) or "Marketing"
    ua = f"{token}MktBot/{version} (+marketing automation noi bo, thu thap tin tai chinh VN"
    return f"{ua}; lien he: {contact})" if contact else f"{ua})"


# =====================================================================
# PHASE DATA-ROOT — GỐC DUY NHẤT cho mọi dữ liệu runtime (documents/output/
# state/logs/ab), TÁCH khỏi repo. Trước phase này, mỗi nơi tự ghép chuỗi
# "storage/..." rải rác (factory.py, file_store.py, produce_from_sheet.py,
# power_on.py...) -> dữ liệu nằm LẪN trong repo (rủi ro commit nhầm, khó tách
# khi deploy VPS). Từ đây, TẤT CẢ đường dẫn dữ liệu PHẢI đi qua data_path().
# =====================================================================
_DEFAULT_DATA_ROOT = "../marketing-automation-database"


def data_root(settings: Settings | None = None) -> Path:
    """Gốc dữ liệu runtime — ưu tiên biến môi trường DATA_ROOT (đặt khi deploy
    máy khác/VPS, CÙNG NẾP với TWMKT_SHEET_ID/TWMKT_CONFIG đã dùng ở nơi khác
    trong repo này — os.environ.get(...) or settings.get(...), KHÔNG dùng cú
    pháp ${VAR} trong YAML vì đó là quy ước dành riêng cho BÍ MẬT, xem docstring
    module), không có thì đọc `storage.data_root` trong settings.yaml (mặc
    định "../marketing-automation-database" — NGOÀI repo). Đường dẫn TƯƠNG ĐỐI
    tính theo THƯ MỤC LÀM VIỆC lúc chạy — cùng quy ước với load_settings() tự
    tìm config/settings.yaml theo CWD (mọi script trong repo LUÔN được chạy từ
    repo root, xem README/CLAUDE.md)."""
    settings = settings or load_settings()
    raw = os.environ.get("DATA_ROOT") or settings.get("storage.data_root", _DEFAULT_DATA_ROOT)
    return Path(str(raw))


def data_path(*parts: str, settings: Settings | None = None) -> Path:
    """Resolve 1 đường dẫn con trong data_root(settings) -> Path TUYỆT ĐỐI/
    tương đối-theo-CWD nhất quán, TỰ TẠO thư mục cần thiết (idempotent, mkdir
    parents=True/exist_ok=True) — mọi nơi đọc/ghi dữ liệu runtime PHẢI gọi hàm
    này thay vì tự Path("storage/...") rải rác (adapter ở điểm nối ổ đĩa, cùng
    triết lý CLAUDE.md áp cho collector/publisher/LLM).

    Phần tử CUỐI có dấu "." (vd "router_decisions.json", "power_on.lock") ->
    coi là FILE, tạo thư mục CHA; không có dấu "." (vd "documents",
    "2026-07-10") -> coi là THƯ MỤC, tự tạo CHÍNH nó. Không truyền `parts` ->
    trả về chính data_root (đã tạo nếu chưa có)."""
    root = data_root(settings)
    p = root.joinpath(*parts) if parts else root
    target_dir = p.parent if "." in p.name else p
    target_dir.mkdir(parents=True, exist_ok=True)
    return p
