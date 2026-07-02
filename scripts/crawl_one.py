"""Lát cắt dọc trên dữ liệu THẬT — 1 nguồn (CafeF), $0 token.

Chạy:
    pip install crawl4ai && crawl4ai-setup
    python scripts/crawl_one.py [--source doanh-nghiep] [--limit 8] [--topic "..."]

Luồng: Crawl4aiCollector (thật) -> normalize (dedup + trích mã + tag) ->
Retriever.index (RAG cục bộ) -> in số liệu tất định -> ResearcherAgent với
MockLLM -> in brief. Không giai đoạn nào ở đây gọi LLM đắt tiền.
"""
from __future__ import annotations

import argparse
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from twmkt.agents.researcher import ResearcherAgent  # noqa: E402
from twmkt.collectors.crawl4ai_collector import Crawl4aiCollector  # noqa: E402
from twmkt.collectors.sources import get_source  # noqa: E402
from twmkt.curation import normalize  # noqa: E402
from twmkt.knowledge.rag import Retriever  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="doanh-nghiep", help="Khóa nguồn trong registry")
    parser.add_argument("--limit", type=int, default=8, help="Số bài tối đa crawl")
    parser.add_argument(
        "--topic", default="doanh nghiệp Việt Nam kết quả kinh doanh",
        help="Chủ đề để Researcher truy hồi (RAG)",
    )
    args = parser.parse_args()

    cfg = get_source(args.source)
    print(f"== Nguồn: {cfg.source.name} ({cfg.source.url}) ==")

    collector = Crawl4aiCollector(
        article_link_pattern=cfg.article_link_re,
        rate_limit_s=cfg.rate_limit_s,
        respect_robots=cfg.respect_robots,
    )
    raw_docs = collector.collect(cfg.source, limit=args.limit)

    print(f"Bài thô crawl được: {len(raw_docs)}")
    if not raw_docs:
        print("Không lấy được bài nào (có thể robots.txt chặn, hoặc không tìm thấy "
              "link bài khớp mẫu trên trang mục). Xem cảnh báo phía trên nếu có.")
        return

    clean_docs = normalize(raw_docs)
    print(f"Còn lại sau dedup: {len(clean_docs)}")

    n_tickers = sum(len(d.tickers) for d in clean_docs)
    print(f"Số lượt mã cổ phiếu trích được: {n_tickers}")
    all_tickers = sorted({t for d in clean_docs for t in d.tickers})
    print(f"Mã cổ phiếu (duy nhất): {all_tickers}")

    retriever = Retriever()
    n_chunks = retriever.index(clean_docs)
    print(f"Số chunk index vào RAG: {n_chunks}")

    print(f"\n== ResearcherAgent (MockLLM, $0 token) — chủ đề: '{args.topic}' ==")
    brief = ResearcherAgent().run(args.topic, retriever)
    print("Luận điểm:", brief.thesis)
    print("Mã liên quan:", brief.tickers)
    print("Điểm chính:", brief.key_points)
    print("Nguồn trích:", brief.sources)


if __name__ == "__main__":
    main()
