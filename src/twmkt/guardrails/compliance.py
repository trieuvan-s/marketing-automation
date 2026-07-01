"""Kiểm tra tuân thủ cho nội dung tài chính. Tất định, chạy trước cổng duyệt 2.

Bắt các tuyên bố cấm (hứa lợi nhuận, "chắc chắn thắng"...) và yêu cầu disclaimer.
Đây là tuyến phòng thủ tự động; con người vẫn duyệt lần cuối ở Gate 2.
"""
from __future__ import annotations

import re

from ..models import ContentDraft, ContentFormat

# Cụm từ rủi ro pháp lý/uy tín cho một thương hiệu tư vấn tài chính.
_BANNED = [
    r"chắc chắn (thắng|lãi|lời)",
    r"cam kết lợi nhuận",
    r"đảm bảo (sinh lời|lợi nhuận|x\d)",
    r"không bao giờ (lỗ|thua)",
    r"lãi \d+%/(tháng|tuần|ngày)",
    r"khuyến nghị mua ngay",
    r"all[- ]?in",
]
_BANNED_RE = [re.compile(p, re.IGNORECASE) for p in _BANNED]

_DISCLAIMER_MARKERS = ("không phải khuyến nghị", "tự chịu trách nhiệm")


def check(draft: ContentDraft) -> list[str]:
    issues: list[str] = []
    text = draft.body.lower()

    for rx in _BANNED_RE:
        m = rx.search(text)
        if m:
            issues.append(f"Cụm từ cấm: '{m.group(0)}'")

    # Bài viết và kịch bản video bắt buộc có disclaimer (infographic dùng footer).
    if draft.fmt in (ContentFormat.ARTICLE, ContentFormat.VIDEO_SCRIPT):
        if not any(mk in text for mk in _DISCLAIMER_MARKERS):
            issues.append("Thiếu disclaimer miễn trừ trách nhiệm")

    return issues


def apply(draft: ContentDraft) -> ContentDraft:
    """Gắn kết quả kiểm tra vào draft và trả lại."""
    draft.compliance_issues = check(draft)
    return draft
