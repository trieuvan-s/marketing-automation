"""Các agent sản xuất nội dung. Mỗi định dạng = một agent chuyên biệt.

Infographic KHÔNG sinh ảnh ở đây — nó sinh SPEC (JSON) để khâu thiết kế/render
sau (có thể đẩy sang Claude Design hoặc công cụ đồ họa). Tách "nội dung" khỏi
"render" để kiểm duyệt văn bản trước khi tốn công dựng hình.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ..models import ContentDraft, ContentFormat, ResearchBrief
from .base import Agent

if TYPE_CHECKING:
    from .hook import MarketingHook

_DISCLAIMER = (
    "Nội dung chỉ mang tính thông tin, không phải khuyến nghị đầu tư. "
    "Nhà đầu tư tự chịu trách nhiệm với quyết định của mình."
)


class ArticleWriter(Agent):
    role = "ArticleWriter"
    system = "Viết bài phân tích cổ phiếu, văn phong rõ ràng, trung lập, có disclaimer."

    def run(self, brief: ResearchBrief,
            hook: "MarketingHook | None" = None) -> ContentDraft:
        points = "\n".join(f"- {p}" for p in brief.key_points)
        narrative = self._ask(f"Viết bài về: {brief.topic}\nLuận điểm: {brief.thesis}")
        # Có hook -> dùng headline gợi ý làm tiêu đề + CTA từ hook; không có -> hành vi cũ.
        title = hook.headlines[0] if hook and hook.headlines else brief.topic
        cta = f"\n\n{hook.cta}" if hook and hook.cta else ""
        body = (
            f"{narrative}\n\nĐiểm chính:\n{points}\n\n"
            f"Mã liên quan: {', '.join(brief.tickers) or 'N/A'}{cta}\n\n_{_DISCLAIMER}_"
        )
        return ContentDraft(
            fmt=ContentFormat.ARTICLE,
            title=title,
            body=body,
            brief_topic=brief.topic,
        )


class InfographicDesigner(Agent):
    role = "InfographicDesigner"
    system = "Tạo spec infographic dạng JSON từ brief nghiên cứu."
    uses_llm = False   # tất định, 0 token

    def run(self, brief: ResearchBrief,
            hook: "MarketingHook | None" = None) -> ContentDraft:
        spec = {
            "headline": (hook.headlines[0] if hook and hook.headlines else brief.topic),
            "tickers": brief.tickers,
            "highlights": brief.evidence[:4],
            "takeaways": brief.key_points[:3],
            "footer": _DISCLAIMER,
        }
        return ContentDraft(
            fmt=ContentFormat.INFOGRAPHIC,
            title=f"[Infographic] {brief.topic}",
            body=json.dumps(spec, ensure_ascii=False, indent=2),
            brief_topic=brief.topic,
        )


class VideoScripter(Agent):
    role = "VideoScripter"
    system = "Viết kịch bản video ngắn (~60s) gồm hook, thân, CTA, có disclaimer."

    def run(self, brief: ResearchBrief,
            hook: "MarketingHook | None" = None) -> ContentDraft:
        # Có hook (tất định) -> dùng góc + headline + CTA từ hook, KHÔNG gọi LLM lại.
        # Không có hook -> giữ hành vi cũ (gọi LLM sinh câu hook).
        if hook:
            hook_line = hook.angle or (hook.headlines[0] if hook.headlines else brief.topic)
            title = hook.headlines[0] if hook.headlines else f"[Video] {brief.topic}"
            cta = hook.cta or "Theo dõi Turtle Wealth để cập nhật phân tích."
        else:
            hook_line = self._ask(f"Viết câu hook 1 dòng cho video về: {brief.topic}")
            title = f"[Video] {brief.topic}"
            cta = "Theo dõi Turtle Wealth để cập nhật phân tích."
        scenes = "\n".join(
            f"[Cảnh {i+1}] {p}" for i, p in enumerate(brief.key_points[:3])
        )
        body = (
            f"HOOK: {hook_line}\n\n{scenes}\n\n"
            f"[CTA] {cta}\n\n{_DISCLAIMER}"
        )
        return ContentDraft(
            fmt=ContentFormat.VIDEO_SCRIPT,
            title=title,
            body=body,
            brief_topic=brief.topic,
        )


class NewsletterBuilder(Agent):
    role = "NewsletterBuilder"
    system = "Lắp newsletter từ brief — tất định, không LLM."
    uses_llm = False   # tất định, 0 token

    def run(self, brief: ResearchBrief,
            hook: "MarketingHook | None" = None) -> ContentDraft:
        points = "\n".join(f"• {p}" for p in brief.key_points)
        body = (
            f"# Bản tin Turtle Wealth\n\n## {brief.topic}\n\n"
            f"{brief.thesis}\n\n### Điểm chính\n{points}\n\n"
            f"Mã liên quan: {', '.join(brief.tickers) or 'N/A'}\n\n_{_DISCLAIMER}_"
        )
        return ContentDraft(
            fmt=ContentFormat.NEWSLETTER,
            title=f"[Newsletter] {brief.topic}",
            body=body,
            brief_topic=brief.topic,
        )


def all_producers(llm=None) -> list[Agent]:
    return [
        ArticleWriter(llm),         # LLM
        VideoScripter(llm),         # LLM
        InfographicDesigner(llm),   # tất định
        NewsletterBuilder(llm),     # tất định
    ]
