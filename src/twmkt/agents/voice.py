"""Voice-lock ĐỘNG (Phase 4, CLAUDE.md lộ trình v3) — lắp system prompt Writer
theo quyết định của StructureRouterAgent (agents/structure_router.py), KHÔNG
còn khung tĩnh hardcode (v1/v2). $0 (chỉ đọc file cục bộ, không gọi API).

Cấu hình (config-first, xem config/settings.yaml khối `voice`):
  voice.enabled          bật/tắt toàn bộ cơ chế (mặc định false nếu thiếu key)
  voice.examples_path    đường dẫn file markdown chứa luật giọng + menu khung + ví dụ

Cấu trúc file examples_path (docs/voice_examples.md v4, xem §0 trong file đó):
  "## 1. ..."   Luật giọng            -> LUÔN nối nguyên văn
  "## 2. ..."   Menu khung (S1-S5)    -> chứa nhiều khối "**S<N> · <tên>**" —
                                          CHỌN đúng 1 (khung chính) + 1 nữa nếu
                                          có khung phụ (bài lai, vd S1+S4)
  "## 2b. ..."  Menu hook + chuyển ý -> LUÔN nối, nhưng khối "Menu hook" bên
                                          trong (3 bullet "- **H<N> · ...**")
                                          bị THU HẸP còn ĐÚNG 1 bullet khớp
                                          hook đã chọn; phần "Luật hook"/"Luật
                                          chuyển ý mượt" giữ NGUYÊN
  "## 2c. ..."  Luật kết chung        -> LUÔN nối nguyên văn
  "## 3. ..."   Nên/Tránh             -> LUÔN nối nguyên văn
  "## 5. ..."   Ví dụ anchor          -> chứa nhiều "### Ví dụ <Chữ>" con, CHỌN
                                          đúng 1 theo khung chính (map mặc định
                                          _DEFAULT_ANCHOR_BY_STRUCTURE)

assemble_voice(decision=None, *, settings=None):
  - `decision` = RouterDecision (agents/structure_router.RouterDecision) HOẶC bất
    kỳ object nào có .structure/.secondary_structure/.hook/.content_type — KHÔNG
    import RouterDecision trực tiếp ở đây để tránh VÒNG IMPORT (structure_router.py
    -> production.py -> voice.py -> structure_router.py nếu import ngược).
  - `decision=None` -> fallback AN TOÀN cùng nghĩa với StructureRouter._fallback()
    (S1 + H3, không khung phụ, anchor D) — dùng ở nơi CHƯA chạy router.

LÙI MƯỢT (không bao giờ raise):
  - voice.enabled=false (hoặc thiếu key)           -> "" (rỗng)
  - file KHÔNG tồn tại                             -> cảnh báo (1 lần) + "" (không có gì để inject)
  - file tồn tại nhưng parse hỏng (thiếu mục bắt buộc,
    hoặc không tìm thấy khung/ví dụ khớp)           -> cảnh báo + inject NGUYÊN file (degrade an toàn)
"""
from __future__ import annotations

import re
from pathlib import Path

from ..config import Settings, load_settings

_SECTION_RE = re.compile(r"^## (\d+[a-z]?)\.\s", re.MULTILINE)
_EXAMPLE_RE = re.compile(r"^### Ví dụ ([A-Z])\b", re.MULTILINE)
_STRUCTURE_RE = re.compile(
    r"^\*\*S(\d)\s*·.*?(?=\n\*\*S\d\s*·|\n\*\*Được phép lai khung|\Z)",
    re.MULTILINE | re.DOTALL)
_HOOK_BULLET_RE = re.compile(
    r"^- \*\*H(\d)\s*·.*?(?=\n- \*\*H\d\s*·|\n\n\*\*Luật hook|\Z)",
    re.MULTILINE | re.DOTALL)

# Luôn nối nguyên văn, bất kể router chọn khung nào (§0 voice_examples.md).
_ALWAYS_SECTIONS = ("1", "2b", "2c", "3")

# Map anchor mặc định theo khung CHÍNH (router hiện chưa có field anchor riêng
# trong schema — xem structure_router.py — nên suy ra từ structure/content_type,
# khớp bảng "Map anchor mặc định" ở §0 voice_examples.md).
_DEFAULT_ANCHOR_BY_STRUCTURE = {"S1": "D", "S2": "B", "S3": "B", "S4": "D", "S5": "A"}

_warned: set[str] = set()   # tránh spam cảnh báo lặp lại trong 1 tiến trình


def _warn(msg: str) -> None:
    if msg in _warned:
        return
    _warned.add(msg)
    print(f"[CẢNH BÁO] voice-lock: {msg}")


def _split_top_sections(text: str) -> dict[str, str]:
    """{"1": "nội dung mục 1 (kèm header)", ...} theo header "## N. " (N có thể
    kèm hậu tố chữ, vd "2b"/"2c" — PHẢI tách riêng, không nuốt lẫn vào "2")."""
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


def _extract_structure_block(section2: str, digit: str) -> str | None:
    """Trích ĐÚNG 1 khối "**S<digit> · ...**...**" trong nội dung mục 2 (menu
    S1-S5). None nếu không có khung khớp `digit` (vd digit="1" -> khối S1)."""
    for m in _STRUCTURE_RE.finditer(section2):
        if m.group(1) == digit:
            return m.group(0).rstrip()
    return None


def _filter_hook_menu(section2b: str, digit: str) -> str:
    """Trong §2b, thu hẹp khối "Menu hook" (3 bullet H1/H2/H3) xuống ĐÚNG 1
    bullet khớp `digit` — GIỮ NGUYÊN phần còn lại (header, blockquote, "Luật
    hook", "Luật chuyển ý mượt"...). Không tìm thấy bullet khớp -> giữ NGUYÊN
    cả 3 (an toàn, không crash — hook lạ vẫn còn đủ menu để writer tự chọn)."""
    matches = list(_HOOK_BULLET_RE.finditer(section2b))
    chosen = next((m for m in matches if m.group(1) == digit), None)
    if not matches or chosen is None:
        return section2b
    start, end = matches[0].start(), matches[-1].end()
    return section2b[:start] + chosen.group(0) + section2b[end:]


def assemble_voice(decision=None, *, settings: Settings | None = None) -> str:
    """Lắp ĐỘNG chuỗi voice-lock theo `decision` (RouterDecision hoặc None) để
    nối THÊM vào system prompt Writer — KHÔNG thay guardrail/compliance (vẫn
    chạy sau như cũ). Xem docstring module để biết cơ chế LUÔN-nối vs nối-động."""
    settings = settings or load_settings()
    if not settings.get("voice.enabled", False):
        return ""

    path = Path(settings.get("voice.examples_path", "docs/voice_examples.md"))
    if not path.exists():
        _warn(f"không thấy file {path} -> bỏ qua voice-lock (rỗng).")
        return ""

    text = path.read_text(encoding="utf-8")
    sections = _split_top_sections(text)

    missing = [n for n in (*_ALWAYS_SECTIONS, "2", "5") if n not in sections]
    if missing:
        _warn(f"parse {path} hỏng (thiếu mục {missing}) -> inject NGUYÊN file (degrade an toàn).")
        return text.strip()

    structure = str(getattr(decision, "structure", None) or "S1").strip().upper()
    secondary = getattr(decision, "secondary_structure", None)
    hook = str(getattr(decision, "hook", None) or "H3").strip().upper()
    content_type = str(getattr(decision, "content_type", None) or "article").strip().lower()

    parts: list[str] = [sections["1"]]

    primary_block = _extract_structure_block(sections["2"], structure.removeprefix("S"))
    if primary_block is None:
        _warn(f"không tìm thấy khung {structure} trong §2 -> dùng NGUYÊN §2 (degrade an toàn).")
        primary_block = sections["2"]
    parts.append(f"## Khung chính đã chọn ({structure})\n\n{primary_block}")

    if secondary and secondary != structure:
        secondary_block = _extract_structure_block(sections["2"], str(secondary).removeprefix("S"))
        if secondary_block:
            parts.append(f"## Khung phụ — dùng cho 1 đoạn trong bài ({secondary})\n\n{secondary_block}")

    parts.append(_filter_hook_menu(sections["2b"], hook.removeprefix("H")))
    parts.append(sections["2c"])
    parts.append(sections["3"])

    anchor_letter = "C" if content_type == "video" else _DEFAULT_ANCHOR_BY_STRUCTURE.get(structure, "D")
    example = _extract_example(sections["5"], anchor_letter)
    if example is None:
        example = _extract_example(sections["5"], "D") or sections["5"]
    parts.append(example)

    return "\n\n---\n\n".join(parts)
