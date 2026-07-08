"""Voice-lock — nối giọng văn cố định (docs/voice_examples.md) vào system
prompt các agent sản xuất nội dung. $0 (chỉ đọc file cục bộ, không gọi API).

Cấu hình (config-first, xem config/settings.yaml khối `voice`):
  voice.enabled          bật/tắt toàn bộ cơ chế (mặc định false nếu thiếu key)
  voice.examples_path    đường dẫn file markdown chứa luật giọng + ví dụ
  voice.format_example   {format: chữ cái ví dụ} — vd analysis -> "D" ("### Ví dụ D")

Cấu trúc file examples_path mà loader cần thấy (docs/voice_examples.md):
  "## 1. ..."    Luật giọng          -> LUÔN lấy nguyên văn
  "## 2. ..."    Chiêu chữ ký        -> LUÔN lấy nguyên văn
  "## 2b. ..."   Menu hook + chuyển ý -> LUÔN lấy nguyên văn (header dạng "N<chữ>." —
                                          vd "2b" — PHẢI tách được, không được nuốt lẫn vào §2)
  "## 3. ..."    Nên/Tránh           -> LUÔN lấy nguyên văn
  "## 5. ..."    Ví dụ anchor        -> chứa nhiều "### Ví dụ <Chữ>" con, CHỌN đúng 1
                                        theo voice.format_example[fmt] (tiết kiệm context).

LÙI MƯỢT (không bao giờ raise):
  - voice.enabled=false (hoặc thiếu key)           -> "" (rỗng)
  - file KHÔNG tồn tại                             -> cảnh báo (1 lần) + "" (không có gì để inject)
  - file tồn tại nhưng parse hỏng (thiếu mục 1/2/2b/3
    hoặc không tìm thấy ví dụ khớp format)          -> cảnh báo + inject NGUYÊN file (degrade an toàn)
"""
from __future__ import annotations

import re
from pathlib import Path

from ..config import Settings, load_settings

_SECTION_RE = re.compile(r"^## (\d+[a-z]?)\.\s", re.MULTILINE)
_EXAMPLE_RE = re.compile(r"^### Ví dụ ([A-Z])\b", re.MULTILINE)
_RULE_SECTIONS = ("1", "2", "2b", "3")

_warned: set[str] = set()   # tránh spam cảnh báo lặp lại trong 1 tiến trình


def _warn(msg: str) -> None:
    if msg in _warned:
        return
    _warned.add(msg)
    print(f"[CẢNH BÁO] voice-lock: {msg}")


def _split_top_sections(text: str) -> dict[str, str]:
    """{"1": "nội dung mục 1 (kèm header)", ...} theo header "## N. "."""
    matches = list(_SECTION_RE.finditer(text))
    out: dict[str, str] = {}
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out[m.group(1)] = text[start:end].rstrip()
    return out


def _extract_example(section5: str, letter: str) -> str | None:
    """Trích ĐÚNG 1 khối "### Ví dụ <letter>" trong nội dung mục 5. None nếu
    không có ví dụ khớp `letter`."""
    matches = list(_EXAMPLE_RE.finditer(section5))
    for i, m in enumerate(matches):
        if m.group(1) != letter:
            continue
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(section5)
        return section5[start:end].rstrip()
    return None


def load_voice_lock(fmt: str, *, settings: Settings | None = None) -> str:
    """Chuỗi voice-lock (§1+§2+§3 + đúng 1 ví dụ) để nối THÊM vào system prompt
    agent sản xuất — KHÔNG thay guardrail/compliance (vẫn chạy sau như cũ).
    `fmt` khớp key trong voice.format_example (vd "analysis"). `settings` tuỳ
    chọn (mặc định load_settings() thật) — dùng để test không đụng file thật."""
    settings = settings or load_settings()
    if not settings.get("voice.enabled", False):
        return ""

    path = Path(settings.get("voice.examples_path", "docs/voice_examples.md"))
    if not path.exists():
        _warn(f"không thấy file {path} -> bỏ qua voice-lock (rỗng).")
        return ""

    text = path.read_text(encoding="utf-8")
    sections = _split_top_sections(text)
    letter = str(settings.get(f"voice.format_example.{fmt}", "")).strip()

    missing = [n for n in _RULE_SECTIONS if n not in sections]
    example = None
    if not missing and letter and "5" in sections:
        example = _extract_example(sections["5"], letter)

    if missing or not letter or example is None:
        _warn(f"parse {path} hỏng (thiếu mục {missing}, hoặc không thấy ví dụ "
              f"{letter!r} cho format {fmt!r}) -> inject NGUYÊN file (degrade an toàn).")
        return text.strip()

    return "\n\n---\n\n".join(sections[n] for n in _RULE_SECTIONS) + "\n\n---\n\n" + example
