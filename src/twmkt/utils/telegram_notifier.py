"""Telegram Notifier (PHASE TELE) — kênh thông báo MỘT CHIỀU, KHÔNG chặn luồng
chính. Dùng để báo trạng thái vận hành (bắt đầu xử lý, đổi nội dung, duyệt xong
Gate 2, lỗi) qua Telegram — KHÔNG thay guardrail/gate, chỉ là kênh xem-cho-biết.

Cấu hình (config-first, xem config/settings.yaml khối `notifications.telegram`):
  enabled      bật/tắt (mặc định false nếu thiếu key)
  bot_token    ${TELEGRAM_BOT_TOKEN} — secrets/.env (KHÔNG hardcode/commit)
  chat_id      ${TELEGRAM_CHAT_ID}  — secrets/.env
  parse_mode   "HTML" (mặc định) — nội dung ĐỘNG luôn được escape (xem escape_html)
  timeout_s    timeout HTTP (giây)

NON-BLOCKING TUYỆT ĐỐI: TelegramNotifier bắt MỌI lỗi (network/timeout/HTTP≠200/
Telegram trả ok=false/thiếu SDK httpx) NGAY BÊN TRONG — KHÔNG BAO GIỜ raise ra
caller, chỉ log.warning rồi trả về False. enabled=false hoặc thiếu bot_token/
chat_id (kể cả khi ${ENV} chưa set — os.path.expandvars GIỮ NGUYÊN chuỗi
"${VAR}" thay vì rỗng, xem _is_unset) -> NullNotifier, no-op HOÀN TOÀN, KHÔNG
log (đây là trạng thái BÌNH THƯỜNG lúc chưa cấu hình, không phải lỗi).

make_notifier(settings) chọn implementation theo notifications.telegram.enabled
(+ có đủ bot_token/chat_id thật), giống triết lý factory.make_llm() — KHÔNG
raise khi thiếu key/SDK.

CỜ THỦ CÔNG: ENV `TWMKT_TELEGRAM_ENABLED` (1/true/yes/on | 0/false/no/off) đè
`notifications.telegram.enabled` khi có mặt — bật/tắt nhanh 1 lượt chạy mà
không cần sửa/commit settings.yaml, xem make_notifier().
"""
from __future__ import annotations

import logging
import os
import re
from html import escape as _html_escape
from typing import Protocol

from ..config import Settings

logger = logging.getLogger("twmkt.notify")

_EMOJI = {
    "start": "⏳",
    "draft_changed": "✍️",
    "gate2_done": "✅",
    "error": "🚨",
    "manual_sent": "📤",
    # Phase 4.6 — map thêm tên event mà run_writer_with_retry (agents/writer.py,
    # Phase 4.5) thật sự bắn ra (retry/failed/needs_human), trước đây rơi vào
    # emoji mặc định "ℹ️" trung tính dù bản chất là lỗi/cần người can thiệp.
    # Phase 4.7: TÁCH "retry" (còn đang thử lại, chưa chắc lỗi cuối) khỏi
    # "failed"/"needs_human" (lỗi CUỐI, cần chú ý ngay) — độ khẩn khác nhau.
    "retry": "⚠️",
    "failed": "🚨",
    "needs_human": "🚨",
    # crawl phát hiện + ghi CONTEXT thành công 1 tin MỚI (scripts/review_to_sheet.py)
    "new_topic": "🆕",
    # Phase 4.12: bỏ qua HỢP LỆ (vd infographic cho tin thuần định tính,
    # KHÔNG phải lỗi) — tách khỏi "error"/"needs_human" (🚨) để không báo động giả.
    "skipped": "ℹ️",
}

_UNEXPANDED_ENV_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")


class Notifier(Protocol):
    def notify(self, event: str, **ctx) -> bool: ...


def escape_html(value: object) -> str:
    """Escape HTML an toàn cho parse_mode=HTML — tránh vỡ tin khi ctx (vd Topic)
    chứa <, >, &. Hàm THUẦN, test được không cần mạng."""
    return _html_escape(str(value), quote=False)


def format_message(event: str, ctx: dict) -> str:
    """Dựng nội dung tin nhắn: emoji + tên event (in đậm) + từng cặp key: value
    trong `ctx`, MỖI GIÁ TRỊ ĐỘNG đều escape HTML. Hàm THUẦN — test được, không
    cần mạng. Event lạ (không có emoji định sẵn) -> dùng "ℹ️" trung tính."""
    emoji = _EMOJI.get(event, "ℹ️")
    lines = [f"{emoji} <b>{escape_html(event)}</b>"]
    for k, v in ctx.items():
        lines.append(f"<b>{escape_html(k)}:</b> {escape_html(v)}")
    return "\n".join(lines)


def _is_unset(value: object) -> bool:
    """True nếu rỗng HOẶC vẫn còn nguyên dạng "${VAR}" chưa expand (ENV chưa
    set — os.path.expandvars GIỮ NGUYÊN chuỗi gốc thay vì trả rỗng, xem
    config._expand). Cả 2 trường hợp đều coi là "thiếu cấu hình"."""
    v = str(value or "").strip()
    return not v or bool(_UNEXPANDED_ENV_RE.fullmatch(v))


class NullNotifier:
    """notifications.telegram.enabled=false hoặc thiếu bot_token/chat_id ->
    dùng cái này — no-op HOÀN TOÀN, KHÔNG log (trạng thái bình thường, không
    phải lỗi)."""

    def notify(self, event: str, **ctx) -> bool:
        return False


class ConsoleNotifier:
    """In ra console — dùng khi demo/test cục bộ không cần Telegram thật."""

    def notify(self, event: str, **ctx) -> bool:
        print(f"[notify] {format_message(event, ctx)}")
        return True


class TelegramNotifier:
    """Gửi thật qua Telegram Bot API (sendMessage). NON-BLOCKING TUYỆT ĐỐI —
    mọi lỗi bị bắt trong notify()/send_message(), KHÔNG BAO GIỜ raise ra caller."""

    def __init__(self, *, bot_token: str, chat_id: str, parse_mode: str = "HTML",
                timeout_s: float = 5.0):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.parse_mode = parse_mode
        self.timeout_s = timeout_s

    def send_message(self, text: str, *, parse_mode: str | None = None) -> bool:
        """POST Bot API sendMessage. Trả True nếu Telegram xác nhận ok=true;
        False cho MỌI lỗi khác (thiếu SDK/network/timeout/HTTP≠200/ok=false) —
        KHÔNG BAO GIỜ raise, luôn log.warning trước khi trả False."""
        try:
            import httpx
        except ImportError:
            logger.warning("TelegramNotifier: chưa cài httpx (pip install httpx) -> bỏ qua.")
            return False
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text,
                  "parse_mode": parse_mode or self.parse_mode}
        try:
            resp = httpx.post(url, json=payload, timeout=self.timeout_s)
            if resp.status_code != 200:
                logger.warning(f"TelegramNotifier: HTTP {resp.status_code}: {resp.text[:200]!r}")
                return False
            data = resp.json()
            if not data.get("ok"):
                logger.warning(f"TelegramNotifier: Telegram trả ok=false: {data!r}")
                return False
            return True
        except Exception as e:   # network/timeout/JSON lỗi... -> KHÔNG BAO GIỜ raise
            logger.warning(f"TelegramNotifier: lỗi gửi ({e!r}) -> bỏ qua, không chặn luồng chính.")
            return False

    def notify(self, event: str, **ctx) -> bool:
        return self.send_message(format_message(event, ctx))


_ENABLED_ENV_VAR = "TWMKT_TELEGRAM_ENABLED"
_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


def make_notifier(settings: Settings) -> Notifier:
    """Chọn Notifier theo notifications.telegram.enabled + có đủ bot_token/
    chat_id THẬT (đã expand ${ENV}) hay chưa — KHÔNG raise khi thiếu cấu hình,
    trả NullNotifier (no-op êm), giống triết lý factory.make_llm().

    CỜ THỦ CÔNG (ENV `TWMKT_TELEGRAM_ENABLED`, đè `notifications.telegram.
    enabled` trong settings.yaml khi có mặt): bật/tắt Telegram ngay KHÔNG cần
    sửa/commit file config — set "1"/"true"/"yes"/"on" để BẬT, "0"/"false"/
    "no"/"off" để TẮT (không phân biệt hoa/thường). Giá trị lạ hoặc ENV không
    set -> lùi về settings.yaml như cũ. Dùng khi cần tắt/bật nhanh 1 lượt chạy
    (vd `TWMKT_TELEGRAM_ENABLED=0 python scripts/produce_from_sheet.py ...`)
    mà không đụng git-tracked config."""
    override = os.environ.get(_ENABLED_ENV_VAR, "").strip().lower()
    if override in _TRUTHY:
        enabled = True
    elif override in _FALSY:
        enabled = False
    else:
        enabled = bool(settings.get("notifications.telegram.enabled", False))
    bot_token = settings.get("notifications.telegram.bot_token", "")
    chat_id = settings.get("notifications.telegram.chat_id", "")
    if not enabled or _is_unset(bot_token) or _is_unset(chat_id):
        return NullNotifier()
    parse_mode = str(settings.get("notifications.telegram.parse_mode", "HTML") or "HTML")
    timeout_s = float(settings.get("notifications.telegram.timeout_s", 5))
    return TelegramNotifier(bot_token=str(bot_token), chat_id=str(chat_id),
                            parse_mode=parse_mode, timeout_s=timeout_s)
