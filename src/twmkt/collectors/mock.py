"""Collector giả lập để chạy offline (demo + test). Không cần mạng."""
from __future__ import annotations

from ..models import RawDocument, Source, SourceType
from .base import Collector

# Vài tài liệu mẫu mô phỏng tin tức/CBTT tiếng Việt.
_SAMPLE = [
    RawDocument(
        source="CafeF",
        url="https://cafef.vn/fpt-bao-lai-quy.html",
        title="FPT báo lãi quý tăng trưởng hai chữ số",
        markdown=(
            "Công ty Cổ phần FPT công bố kết quả kinh doanh với doanh thu và lợi "
            "nhuận sau thuế tăng so với cùng kỳ. Mảng công nghệ và dịch vụ CNTT "
            "nước ngoài tiếp tục là động lực chính. EPS cải thiện so với năm trước."
        ),
        source_type=SourceType.NEWS,
    ),
    RawDocument(
        source="Vietstock",
        url="https://vietstock.vn/hpg-cong-bo.html",
        title="HPG: Sản lượng thép phục hồi",
        markdown=(
            "Tập đoàn Hòa Phát (HPG) ghi nhận sản lượng tiêu thụ thép tăng nhờ nhu "
            "cầu xây dựng hồi phục. Biên lợi nhuận gộp cải thiện trong bối cảnh giá "
            "nguyên liệu ổn định."
        ),
        source_type=SourceType.NEWS,
    ),
    # Bản trùng lặp gần như y hệt (để chứng minh dedup hoạt động).
    RawDocument(
        source="NDH",
        url="https://ndh.vn/fpt-loi-nhuan.html",
        title="FPT báo lãi quý tăng trưởng hai chữ số",
        markdown=(
            "Công ty Cổ phần FPT công bố kết quả kinh doanh với doanh thu và lợi "
            "nhuận sau thuế tăng so với cùng kỳ. Mảng công nghệ và dịch vụ CNTT "
            "nước ngoài tiếp tục là động lực chính. EPS cải thiện so với năm trước."
        ),
        source_type=SourceType.NEWS,
    ),
]


class MockCollector(Collector):
    def collect(self, source: Source, *, limit: int = 10) -> list[RawDocument]:
        return _SAMPLE[:limit]
