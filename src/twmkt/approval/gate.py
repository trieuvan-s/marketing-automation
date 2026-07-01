"""Cổng kiểm duyệt người-trong-vòng-lặp.

Trong production, cổng này map sang node 'User Approval' của LangGraph: graph
DỪNG (interrupt), chờ người bấm duyệt/từ chối trên React UI, rồi chạy tiếp.
Ở đây cung cấp 2 bản: Auto (demo/test) và Console (CLI thủ công).
"""
from __future__ import annotations

from typing import Protocol

from ..models import Decision


class ApprovalGate(Protocol):
    def review(self, label: str, payload: str) -> Decision: ...


class AutoApproveGate(ApprovalGate):
    """Tự duyệt — chỉ dùng demo/test."""

    def __init__(self, decision: Decision = Decision.APPROVE):
        self.decision = decision

    def review(self, label: str, payload: str) -> Decision:
        return self.decision


class ConsoleApprovalGate(ApprovalGate):
    """Hỏi người dùng qua terminal (dùng khi chạy pipeline thủ công)."""

    def review(self, label: str, payload: str) -> Decision:
        print(f"\n===== CẦN DUYỆT: {label} =====")
        print(payload)
        ans = input("[a]pprove / [r]eject / re[v]ise > ").strip().lower()
        return {"a": Decision.APPROVE, "r": Decision.REJECT}.get(ans, Decision.REVISE)
