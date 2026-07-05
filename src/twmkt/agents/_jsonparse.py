"""Parse JSON object từ output LLM — dùng chung cho mọi agent (Hook, Production).

HARDENING: bóc code fence ```json ... ``` (hoặc ``` ... ``` không ghi ngôn ngữ)
nếu có; sau đó lấy vùng {...} NGOÀI CÙNG (đề phòng model vẫn kèm lời dẫn dù đã
dặn "CHỈ trả JSON"). Không parse được -> None (nơi gọi tự rơi về fallback tất định).
"""
from __future__ import annotations

import json
import re

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def try_json_object(s: str) -> dict | None:
    if not s:
        return None
    s = s.strip()
    m = _FENCE_RE.match(s)
    if m:
        s = m.group(1).strip()
    a, b = s.find("{"), s.rfind("}")
    if a == -1 or b <= a:
        return None
    try:
        obj = json.loads(s[a:b + 1])
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None
