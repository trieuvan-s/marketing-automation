"""Hook Agent — sinh GÓC MARKETING từ ResearchBrief (bước 'Hook' trong MVP flow).

Vị trí: sau Researcher, trước cổng duyệt 1 — người duyệt thấy cả luận điểm lẫn
góc marketing rồi mới quyết cho sản xuất. Dùng tầng LLM rẻ (Haiku) vì đầu ra
ngắn. Có FALLBACK tất định nếu LLM không trả JSON hợp lệ → chạy offline $0 vẫn ra
hook dùng được.

Nguyên tắc: Hook chỉ tạo góc tiếp cận/tiêu đề, KHÔNG bịa số, KHÔNG hứa lợi nhuận.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .base import Agent

_DEFAULT_CTA = "Theo dõi Turtle Wealth để cập nhật phân tích."


@dataclass
class MarketingHook:
    topic: str
    angle: str                                   # góc tiếp cận, 1 dòng
    headlines: list[str] = field(default_factory=list)   # 2-3 tiêu đề ứng viên
    audience: str = "nhà đầu tư cá nhân"
    emotion: str = "tò mò"
    cta: str = _DEFAULT_CTA


_SYSTEM = (
    "Bạn là copywriter tài chính. Từ luận điểm nghiên cứu, tạo GÓC marketing "
    "ngắn gọn, trung lập, KHÔNG hứa lợi nhuận, KHÔNG bịa số. Trả về DUY NHẤT "
    'JSON: {"angle": str, "headlines": [3 chuỗi], "audience": str, '
    '"emotion": str, "cta": str}. Không thêm chữ nào ngoài JSON.'
)


class HookAgent(Agent):
    role = "HookStrategist"
    system = _SYSTEM

    def run(self, brief) -> MarketingHook:
        prompt = (
            f"Chủ đề: {brief.topic}\n"
            f"Luận điểm: {getattr(brief, 'thesis', '')}\n"
            f"Mã: {', '.join(getattr(brief, 'tickers', []))}\n"
            f"Điểm chính: {'; '.join(getattr(brief, 'key_points', []))}"
        )
        data = _try_json(self._ask(prompt))
        if data:
            return MarketingHook(
                topic=brief.topic,
                angle=str(data.get("angle", "")).strip()[:200],
                headlines=[str(h).strip() for h in (data.get("headlines") or [])][:3],
                audience=str(data.get("audience", "nhà đầu tư cá nhân")).strip(),
                emotion=str(data.get("emotion", "tò mò")).strip(),
                cta=str(data.get("cta", _DEFAULT_CTA)).strip() or _DEFAULT_CTA,
            )
        return _fallback(brief)   # offline / MockLLM


def _try_json(s: str):
    if not s:
        return None
    s = s.strip()
    if s.startswith("```"):
        s = s.strip("`")
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        obj = json.loads(s[start : end + 1])
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _fallback(brief) -> MarketingHook:
    tickers = getattr(brief, "tickers", [])
    tick = ", ".join(tickers) if tickers else "thị trường"
    topic = brief.topic
    return MarketingHook(
        topic=topic,
        angle=f"Điều nhà đầu tư nên chú ý về {tick}: {topic}",
        headlines=[
            f"{tick}: {topic}",
            f"3 điều rút ra từ {topic}",
            f"Vì sao {tick} đáng chú ý lúc này?",
        ],
    )
