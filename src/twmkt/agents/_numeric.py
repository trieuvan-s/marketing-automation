"""Phase 4.8 Mục C — parser số CANONICAL. CODE THUẦN, tất định, KHÔNG qua LLM.

Nguyên tắc (đã chốt): sự giòn với NGÔN NGỮ số ("gần 600 tỷ"/"585 tỉ"/"585 tỷ
đồng" cùng 1 số thật) được xử bằng AI ở khâu TRÍCH (agents/brief.py — AI nhận
diện các biến thể cách viết cùng chỉ 1 số). Guardrail (agents/production.py)
vẫn là CODE, phán bằng PHÉP TÍNH SỐ HỌC TẤT ĐỊNH trên số đã chuẩn hoá —
LLM KHÔNG BAO GIỜ là quan toà cuối cùng phán 1 số là an toàn.

Dùng CHUNG bởi agents/brief.py (tính Fact.canonical_value từ value+unit AI đã
trích) và agents/production.py (guardrail parse số TRONG BÀI để so khớp số học
với canonical_value của facts[]) — tách module riêng (không đặt trong
production.py) để brief.py (bước SỚM hơn trong pipeline) không phải import
production.py (bước SAU) chỉ để dùng 1 hàm tiện ích thuần.
"""
from __future__ import annotations

import re

_NUM_PREFIX_RE = re.compile(r"^\d[\d.,]*")

# DÀI -> NGẮN: khớp cụm dài trước, tránh "tỷ" ăn nhầm vào giữa "tỷ đồng"/
# "nghìn tỷ" (kiểm tra bằng `in` theo ĐÚNG thứ tự này).
_UNIT_SCALE = (
    ("nghìn tỷ", 1e12),
    ("tỷ đồng", 1e9),
    ("tỷ", 1e9),
    ("triệu", 1e6),
)

APPROX_WORDS = ("gần", "khoảng", "xấp xỉ", "hơn", "trên", "dưới")
_APPROX_WORD_RE = re.compile("|".join(APPROX_WORDS), re.IGNORECASE)


def parse_vn_decimal(num_text: str) -> float | None:
    """Chuỗi số thuần (dấu '.'/',' kiểu VN hoặc quốc tế, có thể lẫn cả 2) ->
    float. Heuristic (không hoàn hảo 100% nhưng đủ cho miền dữ liệu tài chính
    VN thực tế đã gặp trong repo này):
      - Có CẢ '.' và ',': dấu XUẤT HIỆN SAU CÙNG là thập phân, dấu còn lại là
        phân cách nghìn — đúng bất kể quy ước VN ("4.072,69") hay quốc tế
        ("4,072.69"), cả 2 cho CÙNG 1 giá trị 4072.69.
      - Chỉ có ',': coi là thập phân (quy ước VN phổ biến cho %/growth, vd
        "8,18%").
      - Chỉ có '.': theo SAU đúng 3 chữ số -> phân cách nghìn (quy ước VN cho
        tiền, vd "1.200" = 1200); khác 3 chữ số -> thập phân (vd "12.61" —
        đúng ca false-positive fix 1: evidence kiểu bảng dùng '.' thập phân).
      - Không dấu: số nguyên/thập phân thường.
    None nếu không parse được (chuỗi rỗng/không phải số)."""
    text = (num_text or "").strip()
    if not text:
        return None
    has_dot, has_comma = "." in text, "," in text
    if has_dot and has_comma:
        last_dot, last_comma = text.rfind("."), text.rfind(",")
        dec_sep = "," if last_comma > last_dot else "."
        thou_sep = "." if dec_sep == "," else ","
        text = text.replace(thou_sep, "").replace(dec_sep, ".")
    elif has_comma:
        text = text.replace(",", ".")
    elif has_dot:
        frac = text.split(".")[-1]
        if len(frac) == 3:
            text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def parse_magnitude_token(token: str) -> float | None:
    """1 token số+đơn vị (vd "600 tỷ", "12,61%", "4.072,69USD", "585tỷ đồng")
    -> giá trị THẬT (float, đã nhân hệ số tỷ/triệu/nghìn tỷ). %/usd/đồng/
    không đơn vị -> hệ số 1 (giữ nguyên số). None nếu không parse được phần số
    (token rỗng/không bắt đầu bằng chữ số)."""
    m = _NUM_PREFIX_RE.match((token or "").strip())
    if not m:
        return None
    value = parse_vn_decimal(m.group(0))
    if value is None:
        return None
    unit_text = token[m.end():].strip().lower()
    for word, scale in _UNIT_SCALE:
        if word in unit_text:
            return value * scale
    return value


def has_approx_word(text: str) -> bool:
    """True nếu `text` chứa 1 trong các từ xấp xỉ (gần/khoảng/xấp xỉ/hơn/
    trên/dưới) — dùng CẢ ở Brief (đánh dấu Fact.approx từ cụm `raw`) LẪN
    Guardrail (nới dung sai khi số TRONG BÀI đi kèm từ xấp xỉ ngay trước nó)."""
    return bool(_APPROX_WORD_RE.search(text or ""))
