"""Demo toàn pipeline offline: python -m twmkt.demo

MockCollector + MockLLM + RAG cục bộ + AutoApproveGate + ConsolePublisher.
Không cần mạng, không cần khóa API, $0 token.
"""
from __future__ import annotations

from ._encoding import ensure_utf8_stdio
from .collectors.mock import MockCollector
from .models import Source, SourceType
from .orchestrator import MarketingPipeline


def main() -> None:
    ensure_utf8_stdio()
    sources = [
        Source("CafeF", "https://cafef.vn", SourceType.NEWS),
        Source("Vietstock", "https://vietstock.vn", SourceType.NEWS),
    ]
    pipe = MarketingPipeline(MockCollector())
    state = pipe.run(
        topic="FPT tăng trưởng lợi nhuận và triển vọng ngành CNTT",
        sources=sources,
    )

    print("\n========== NHẬT KÝ PIPELINE ==========")
    for line in state.log:
        print(" ", line)

    print("\n========== KẾT QUẢ ==========")
    print("Stage cuối:", state.stage.value)
    print("Tài liệu sạch:", len(state.clean_docs))
    print("Bản nháp:", [d.fmt.value for d in state.drafts])
    print("Đã đăng:", [(p.platform, p.fmt.value) for p in state.published])


if __name__ == "__main__":
    main()
