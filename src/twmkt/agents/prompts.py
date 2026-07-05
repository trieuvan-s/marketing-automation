"""Nạp system prompt THEO PHIÊN BẢN — đổi văn phong KHÔNG cần sửa code/deploy lại.

Cơ chế:
  • Text prompt để trong repo: `prompts/<name>.<version>.md` (version-controlled,
    diff được, review qua PR như code).
  • Tab PROMPTS (Name|Version|Enable) trên Google Sheet = BẢNG KÍCH HOẠT: chọn
    Version nào đang dùng cho mỗi Name — KHÔNG chứa nội dung prompt.
  • Thiếu tab/dòng Enable/file tương ứng -> dùng default NỘI BỘ (hardcode trong
    agent) — không bao giờ crash vì thiếu prompt.

Hàm ở đây THUẦN (nhận sẵn `versions: dict[name, version]` đã đọc từ Sheet qua
sheets_board.SheetsBoard.read_prompt_versions — tách biệt I/O Sheets khỏi I/O file).
"""
from __future__ import annotations

from pathlib import Path

DEFAULT_PROMPTS_DIR = "prompts"


def read_prompt_file(name: str, version: str, *,
                     prompts_dir: str = DEFAULT_PROMPTS_DIR) -> str | None:
    """Đọc prompts/<name>.<version>.md (UTF-8). Thiếu file/rỗng -> None (nơi gọi
    tự fallback về default nội bộ, KHÔNG raise)."""
    p = Path(prompts_dir) / f"{name}.{version}.md"
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8").strip()
    return text or None


def resolve_prompts(versions: dict[str, str], defaults: dict[str, str], *,
                    prompts_dir: str = DEFAULT_PROMPTS_DIR) -> dict[str, str]:
    """Với mỗi `name` trong `defaults`: có version kích hoạt (từ tab PROMPTS) +
    đọc được file tương ứng -> DÙNG FILE; ngược lại giữ nguyên default nội bộ.
    Hàm THUẦN — test không cần mạng (chỉ cần file thật trên đĩa nếu muốn override)."""
    out = dict(defaults)
    for name, version in versions.items():
        if name not in defaults or not version:
            continue
        text = read_prompt_file(name, version, prompts_dir=prompts_dir)
        if text:
            out[name] = text
    return out
