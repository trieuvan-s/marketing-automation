"""Các agent sản xuất nội dung. Mỗi định dạng = một agent chuyên biệt.

Infographic KHÔNG sinh ảnh ở đây — nó sinh SPEC (JSON) để khâu thiết kế/render
sau (có thể đẩy sang Claude Design hoặc công cụ đồ họa). Tách "nội dung" khỏi
"render" để kiểm duyệt văn bản trước khi tốn công dựng hình.
"""
from __future__ import annotations

import json

from ..models import ContentDraft, ContentFormat, ResearchBrief
from .base import Agent

_DISCLAIMER = (
    "Nội dung chỉ mang tính thông tin, không phải khuyến nghị đầu tư. "
    "Nhà đầu tư tự chịu trách nhiệm với quyết định của mình."
)


class ArticleWriter(Agent):
    role = "ArticleWriter"
    system = "Viết bài phân tích cổ phiếu, văn phong rõ ràng, trung lập, có disclaimer."

    def run(self, brief: ResearchBrief) -> ContentDraft:
        points = "\n".join(f"- {p}" for p in brief.key_points)
        narrative = self._ask(f"Viết bài về: {brief.topic}\nLuận điểm: {brief.thesis}")
        body = (
            f"{narrative}\n\nĐiểm chính:\n{points}\n\n"
            f"Mã liên quan: {', '.join(brief.tickers) or 'N/A'}\n\n_{_DISCLAIMER}_"
        )
        return ContentDraft(
            fmt=ContentFormat.ARTICLE,
            title=brief.topic,
            body=body,
            brief_topic=brief.topic,
        )


class InfographicDesigner(Agent):
    role = "InfographicDesigner"
    system = "Tạo spec infographic dạng JSON từ brief nghiên cứu."
    uses_llm = False   # tất định, 0 token

    def run(self, brief: ResearchBrief) -> ContentDraft:
        spec = {
            "headline": brief.topic,
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

    def run(self, brief: ResearchBrief) -> ContentDraft:
        hook = self._ask(f"Viết câu hook 1 dòng cho video về: {brief.topic}")
        scenes = "\n".join(
            f"[Cảnh {i+1}] {p}" for i, p in enumerate(brief.key_points[:3])
        )
        body = (
            f"HOOK: {hook}\n\n{scenes}\n\n"
            f"[CTA] Theo dõi Turtle Wealth để cập nhật phân tích.\n\n{_DISCLAIMER}"
        )
        return ContentDraft(
            fmt=ContentFormat.VIDEO_SCRIPT,
            title=f"[Video] {brief.topic}",
            body=body,
            brief_topic=brief.topic,
        )


class NewsletterBuilder(Agent):
    role = "NewsletterBuilder"
    system = "Lắp newsletter từ brief — tất định, không LLM."
    uses_llm = False   # tất định, 0 token

    def run(self, brief: ResearchBrief) -> ContentDraft:
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
