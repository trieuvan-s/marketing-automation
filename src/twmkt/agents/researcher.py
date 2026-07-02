"""Researcher Agent: truy hồi RAG trên dữ liệu crawl -> ResearchBrief.

Chất liệu nghiên cứu đến từ Knowledge Layer (RAG), không còn từ engine ervn.
Chỉ gửi các chunk LIÊN QUAN cho LLM (không gửi cả kho) => tiết kiệm token.
"""
from __future__ import annotations

from ..knowledge.rag import Retriever
from ..models import ResearchBrief
from .base import Agent


class ResearcherAgent(Agent):
    role = "Researcher"
    system = (
        "Bạn là chuyên viên phân tích tài chính. Viết luận điểm súc tích, trung "
        "lập, BÁM SÁT các trích đoạn được cung cấp. Không bịa số, không hứa lợi nhuận."
    )

    def run(self, topic: str, retriever: Retriever, *, k: int | None = None) -> ResearchBrief:
        # k=None -> dùng top_k đã cấu hình cho retriever (config-first).
        chunks = retriever.retrieve(topic, k=k)

        tickers: list[str] = []
        sources: list[str] = []
        for c in chunks:
            for t in c.tickers:
                if t not in tickers:
                    tickers.append(t)
            if c.url not in sources:
                sources.append(c.url)

        # key_points lấy tất định từ tiêu đề chunk (không để LLM tự chế danh sách).
        seen: list[str] = []
        for c in chunks:
            if c.title not in seen:
                seen.append(c.title)
        key_points = seen[:3]

        # Prompt BÁM tiêu đề + trích đoạn bài GIỮ LẠI, yêu cầu luận điểm về diễn
        # biến/doanh nghiệp cụ thể trong bài — KHÔNG nhắc lại cụm chủ đề thô.
        titles = "\n".join(f"- {t}" for t in key_points) or "- (không có)"
        context = "\n".join(f"- {c.text[:200]}" for c in chunks) or "- (không có trích đoạn)"
        prompt = (
            f"Chủ đề tra cứu (chỉ để định hướng, KHÔNG lặp lại nguyên văn): {topic}\n\n"
            f"Tiêu đề các bài liên quan giữ lại:\n{titles}\n\n"
            f"Trích đoạn liên quan:\n{context}\n\n"
            "Viết 1 câu luận điểm SÚC TÍCH về diễn biến/doanh nghiệp CỤ THỂ nêu "
            "trong các bài trên (nêu tên/mã nếu có), bám sát trích đoạn."
        )
        thesis = self._ask(prompt).strip()
        # LLM trả rỗng -> luận điểm tất định theo bài giữ lại (không echo topic thô).
        if not thesis:
            thesis = key_points[0] if key_points else topic

        return ResearchBrief(
            topic=topic,
            tickers=tickers,
            thesis=thesis,
            key_points=key_points,
            evidence=[c.text[:200] for c in chunks],
            sources=sources,
        )
