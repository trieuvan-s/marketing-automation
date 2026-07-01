"""Adapter phân phối ra nền tảng MXH — cùng pattern với collectors.

LƯU Ý THỰC TẾ về API đăng bài (cần xác minh khi triển khai):
- YouTube Data API, LinkedIn, X (trả phí bậc cao): có API đăng chính thức.
- Facebook/Instagram: chỉ đăng được qua Page/Business + Graph API, không đăng
  lên tài khoản cá nhân; cần app review.
- TikTok: Content Posting API yêu cầu đăng ký nhà phát triển và xét duyệt.
=> Khuyến nghị: bắt đầu với 1-2 nền tảng có API ổn (YouTube/LinkedIn/Facebook
   Page), các nền tảng còn lại để "draft + đẩy thủ công" giai đoạn đầu.
"""
from __future__ import annotations

from typing import Protocol

from ..models import ContentDraft, PublishResult


class Publisher(Protocol):
    platform: str
    def publish(self, draft: ContentDraft) -> PublishResult: ...


class ConsolePublisher(Publisher):
    """Bản giả lập: in ra màn hình thay vì đăng thật. Dùng demo/test."""

    platform = "console"

    def publish(self, draft: ContentDraft) -> PublishResult:
        print(f"\n----- ĐĂNG [{self.platform}] {draft.fmt.value} -----")
        print(draft.title)
        return PublishResult(
            platform=self.platform, fmt=draft.fmt, ok=True, ref="console://printed"
        )


class StubPublisher(Publisher):
    """Khung cho nền tảng thật — chưa nối API, raise rõ ràng nếu gọi."""

    def __init__(self, platform: str):
        self.platform = platform

    def publish(self, draft: ContentDraft) -> PublishResult:  # pragma: no cover
        raise NotImplementedError(
            f"Adapter '{self.platform}' chưa nối API. Xem ghi chú đầu file."
        )
