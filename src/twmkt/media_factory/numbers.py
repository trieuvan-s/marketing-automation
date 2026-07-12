"""Production Factory — chuẩn hoá SỐ VIẾT BẰNG CHỮ tiếng Việt -> giá trị số
THẬT. Cần vì `ProductionScene.voice_text` (Phase 2, kịch bản đọc TTS) BẮT BUỘC
viết số bằng chữ (máy đọc số dạng chữ số "13,8" nghe cứng/sai ngữ điệu) — nhưng
guardrail (`verify_spec`, `spec.py`) vẫn phải đối chiếu được số đó với
`facts[].canonical_value`, cùng nguyên tắc "AI hiểu ở Brief, CODE phán ở
Guardrail" đã áp dụng cho `agents/_numeric.py` (số dạng CHỮ SỐ, vd "585 tỷ").

CODE THUẦN, TẤT ĐỊNH, không LLM, không mạng.

PHẠM VI (đọc kỹ trước khi mở rộng):
  - Xử ĐÚNG dạng phổ biến trong facts tài chính: "[phần nguyên] [phẩy [phần
    thập phân]] [đơn vị cuối: tỷ|tỉ|triệu|nghìn|ngàn|phần trăm]" — vd "mười ba
    phẩy tám tỷ" -> 13.8e9, "hai mươi ba phần trăm" -> 23.0 (giữ nguyên số,
    CÙNG quy ước với `agents._numeric.parse_magnitude_token`: % không nhân hệ
    số, coi giá trị là số phần trăm chứ không phải phân số).
  - Phần thập phân (sau "phẩy") đọc TỪNG CHỮ SỐ ĐƠN (đúng cách đọc số thập
    phân tiếng Việt chuẩn: "phẩy không tám" = ".08", KHÔNG PHẢI ghép
    "không"+"tám" thành 1 số 2 chữ số "08"→8 rồi ghi ".8").
  - "nghìn"/"ngàn" được xử NHƯ BỘI SỐ NHÓM ×1.000 dù xuất hiện Ở ĐÂU trong
    phần nguyên (đầu/giữa/cuối) — nhờ vậy "mười ba nghìn tỷ" tự động ra ĐÚNG
    1.3e13 mà KHÔNG cần liệt "nghìn tỷ" thành 1 đơn vị ghép riêng.
  - KHÔNG xử số nguyên lớn đọc theo NHIỀU nhóm "tỷ ... triệu ... nghìn ..."
    lồng nhau (vd "một tỷ hai trăm triệu đồng" đọc như 1 số nguyên 1.200.000.000
    — khác hẳn "mười ba phẩy tám tỷ" chỉ có 1 đơn vị cuối). Ca này HIẾM gặp
    trong facts[] đã trích (Brief thường trả facts ở dạng canonical số+đơn vị
    ngắn gọn, không phải câu văn đọc số dài) — để ngỏ mở rộng sau nếu backtest
    thật cho thấy cần.

GIỚI HẠN ĐÃ BIẾT (phát hiện số THEO CỤM TỪ tự nhiên, xem `find_word_number_
phrases`): các từ số đơn ("một", "hai"...) cũng là từ thường dùng phi-số trong
tiếng Việt (vd "một" = mạo từ "a/an"). Để giảm dương tính giả, CHỈ coi là "cụm
số nghi vấn" khi cụm có >= 2 từ số LIÊN TIẾP, HOẶC 1 từ số đi kèm ngay 1 đơn vị
lớn/phần trăm (vd "một tỷ" vẫn được bắt dù chỉ 1 từ số, vì có "tỷ" theo sau).
KHÔNG hoàn hảo 100% (đây là nhận dạng theo mẫu, không phải NLP đầy đủ) — nếu
backtest thật cho nhiều dương tính giả, tinh chỉnh `_MIN_STANDALONE_LEN`/danh
sách hậu tố ở đây, KHÔNG sửa nơi gọi.
"""
from __future__ import annotations

import re

_ONES: dict[str, int] = {
    "không": 0, "một": 1, "mốt": 1, "hai": 2, "ba": 3, "bốn": 4, "tư": 4,
    "năm": 5, "lăm": 5, "nhăm": 5, "sáu": 6, "bảy": 7, "bẩy": 7, "tám": 8, "chín": 9,
}
_GROUP_WORDS = ("nghìn", "ngàn")           # bội số ×1.000, xử Ở BẤT KỲ ĐÂU trong phần nguyên
# "phẩy" PHẢI nằm trong từ-vựng số cốt lõi (dùng để phát hiện CỤM số liên tục
# ở find_word_number_phrases) dù bản thân nó không có giá trị số — thiếu nó,
# 1 cụm như "tám phẩy một tám" sẽ bị cắt làm 2 mảnh ("tám" và "một tám") ngay
# tại "phẩy", làm find_word_number_phrases bỏ sót phần thập phân.
_STRUCTURE_WORDS = ("mười", "mươi", "trăm", "phẩy") + _GROUP_WORDS
_NUMBER_CORE = set(_ONES) | set(_STRUCTURE_WORDS)
_CURRENCY_WORDS = ("đồng", "usd")   # hậu tố tiền tệ, KHÔNG đổi hệ số (giống %) — chỉ bỏ khỏi
                                    # chuỗi trước khi dò hệ số tỷ/triệu (vd "... tỷ đồng")

# Đơn vị CUỐI cụm (dài -> ngắn để so trước, dù ở đây không có cụm ghép nhiều
# từ ngoài "phần trăm"). Khớp _UNIT_SCALE của agents/_numeric.py cho nhất quán
# hệ số, nhưng KHÔNG import chéo (numbers.py giữ ĐỘC LẬP, không phụ thuộc
# agents/_numeric — quyết định #3/#4 Phase 1.0: Production Factory decoupled).
_TRAILING_SCALE = (("tỷ", 1e9), ("tỉ", 1e9), ("triệu", 1e6))
_PERCENT_MARKER = "phần trăm"


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _parse_small_group(words: list[str]) -> int:
    """0-999 từ tối đa 3 "từ số" (trăm/mười-mươi/đơn vị). Hàm THUẦN, nội bộ."""
    if not words:
        return 0
    total = 0
    i = 0
    if len(words) >= 2 and words[1] == "trăm" and words[0] in _ONES:
        total += _ONES[words[0]] * 100
        i = 2
    rest = words[i:]
    if not rest:
        return total
    if rest[0] == "mười":
        tail = _ONES.get(rest[1], 0) if len(rest) > 1 and rest[1] in _ONES else 0
        return total + 10 + tail
    if len(rest) >= 2 and rest[1] == "mươi" and rest[0] in _ONES:
        tail = _ONES.get(rest[2], 0) if len(rest) > 2 and rest[2] in _ONES else 0
        return total + _ONES[rest[0]] * 10 + tail
    if rest[0] in _ONES:
        return total + _ONES[rest[0]]
    return total


def _words_to_int(words: list[str]) -> int | None:
    """Phần NGUYÊN (trước 'phẩy' nếu có) -> int, xử 'nghìn'/'ngàn' như bội số
    ×1.000 ở BẤT KỲ vị trí nào. `words` rỗng -> None (không có gì để parse).
    Có từ KHÔNG thuộc từ-vựng số -> None (không đoán mò, để verify_spec() coi
    là không parse được thay vì âm thầm bỏ qua phần lạ)."""
    if not words:
        return None
    if any(w not in _NUMBER_CORE for w in words):
        return None
    total = 0
    group: list[str] = []
    for w in words:
        if w in _GROUP_WORDS:
            total += _parse_small_group(group) * 1000
            group = []
        else:
            group.append(w)
    total += _parse_small_group(group)
    return total


def _decimal_words_to_digits(words: list[str]) -> str | None:
    """Đọc TỪNG CHỮ SỐ ĐƠN sau 'phẩy' -> chuỗi thập phân (vd "không tám" ->
    "08"). None nếu gặp từ không phải chữ số đơn (0-9)."""
    digits: list[str] = []
    for w in words:
        d = _ONES.get(w)
        if d is None:
            return None
        digits.append(str(d))
    return "".join(digits)


def parse_vn_number_words(text: str) -> float | None:
    """Chuẩn hoá 1 CỤM số viết bằng chữ tiếng Việt -> giá trị số thật (đã nhân
    hệ số tỷ/triệu nếu có; % giữ nguyên số, không chia 100 — CÙNG quy ước
    `agents._numeric.parse_magnitude_token`). None nếu `text` không phải 1 cụm
    số hợp lệ theo phạm vi đã tài liệu hoá ở đầu module."""
    norm = _normalize_ws(text)
    if not norm:
        return None
    norm = norm.replace(_PERCENT_MARKER, "").strip()
    for currency in _CURRENCY_WORDS:   # bỏ hậu tố tiền tệ TRƯỚC khi dò hệ số
        if norm == currency or norm.endswith(" " + currency):
            norm = norm[: -len(currency)].strip()
            break

    scale = 1.0
    for word, mult in _TRAILING_SCALE:
        if norm == word or norm.endswith(" " + word):
            scale = mult
            norm = norm[: -len(word)].strip()
            break

    if not norm:
        return None   # chỉ có mỗi đơn vị, không có số -> không hợp lệ

    words = norm.split(" ")
    if "phẩy" in words:
        idx = words.index("phẩy")
        int_words, dec_words = words[:idx], words[idx + 1:]
    else:
        int_words, dec_words = words, []

    int_val = _words_to_int(int_words) if int_words else 0
    if int_val is None:
        return None

    if dec_words:
        dec_digits = _decimal_words_to_digits(dec_words)
        if dec_digits is None:
            return None   # có "phẩy" nhưng phần thập phân không parse được -> KHÔNG đoán mò
        value = float(f"{int_val}.{dec_digits}")
    else:
        value = float(int_val)

    return value * scale


# --- Số dạng CHỮ SỐ (digit) + từ xấp xỉ — bản SAO có chủ đích của
# agents/_numeric.py (parse_magnitude_token/has_approx_word/_UNIT_SCALE), KHÔNG
# import chéo: `twmkt.media_factory` giữ ĐỘC LẬP với `twmkt.agents` (Production
# Factory tách khỏi Content Factory, quyết định #3/#4 Phase 1.0) — cùng tiền
# lệ `render/infographic.py` đã tự sao `_RENDER_DISCLAIMER` thay vì import
# ngược `agents/production.py`. Đổi 1 bên KHÔNG tự đổi bên kia — nếu sửa quy
# tắc parse số, sửa CẢ 2 nơi.
_DIGIT_PREFIX_RE = re.compile(r"^\d[\d.,]*")
_DIGIT_UNIT_SCALE = (("nghìn tỷ", 1e12), ("tỷ đồng", 1e9), ("tỷ", 1e9), ("triệu", 1e6))
_DIGIT_MAGNITUDE_RE = re.compile(
    r"\d[\d.,]*\s*(?:%|tỷ đồng|nghìn tỷ|tỷ|triệu|usd|đồng)", re.IGNORECASE)
_APPROX_WORDS = ("gần", "khoảng", "xấp xỉ", "hơn", "trên", "dưới")
_APPROX_WORD_RE = re.compile("|".join(_APPROX_WORDS), re.IGNORECASE)


def parse_vn_decimal(num_text: str) -> float | None:
    """Chuỗi số thuần (dấu '.'/',' kiểu VN hoặc quốc tế) -> float. Xem
    agents/_numeric.parse_vn_decimal (heuristic giống hệt, bản sao độc lập)."""
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


def parse_digit_token(token: str) -> float | None:
    """1 token số+đơn vị dạng CHỮ SỐ (vd "600 tỷ", "12,61%") -> giá trị thật.
    Xem agents/_numeric.parse_magnitude_token (bản sao độc lập, xem ghi chú
    trên)."""
    m = _DIGIT_PREFIX_RE.match((token or "").strip())
    if not m:
        return None
    value = parse_vn_decimal(m.group(0))
    if value is None:
        return None
    unit_text = token[m.end():].strip().lower()
    for word, scale in _DIGIT_UNIT_SCALE:
        if word in unit_text:
            return value * scale
    return value


def has_approx_word(text: str) -> bool:
    """True nếu `text` chứa từ xấp xỉ (gần/khoảng/xấp xỉ/hơn/trên/dưới)."""
    return bool(_APPROX_WORD_RE.search(text or ""))


_MIN_STANDALONE_LEN = 2   # cụm < 2 từ CHỈ được nhận nếu có hậu tố lớn theo sau


def find_word_number_phrases(text: str) -> list[tuple[str, int]]:
    """Tìm các CỤM SỐ VIẾT BẰNG CHỮ trong `text` (chuỗi liên tiếp "từ số" +
    hậu tố lớn/% tuỳ chọn ngay sau) — trả [(cụm THÔ, vị trí ký tự bắt đầu)],
    CHƯA parse (gọi `parse_vn_number_words` từng cụm ở nơi cần). Vị trí trả về
    để nơi gọi soi được từ xấp xỉ (gần/khoảng...) đứng NGAY TRƯỚC cụm.

    Giới hạn dương-tính-giả: xem docstring đầu module — cụm 1 từ CHỈ được nhận
    khi có hậu tố lớn/% theo ngay sau (vd "một tỷ" nhận, "một" đứng lẻ KHÔNG)."""
    low = text.lower()
    # tokenize giữ vị trí ký tự để tính offset chính xác (khác text.split()).
    tokens = [(m.group(0), m.start()) for m in re.finditer(r"\S+", low)]
    out: list[tuple[str, int]] = []
    i, n = 0, len(tokens)
    while i < n:
        word, start = tokens[i]
        if word not in _NUMBER_CORE:
            i += 1
            continue
        j = i
        while j < n and tokens[j][0] in _NUMBER_CORE:
            j += 1
        end = j
        has_suffix = False
        if end < n and tokens[end][0] in ("tỷ", "tỉ", "triệu"):
            end += 1
            has_suffix = True
        elif end + 1 < n and tokens[end][0] == "phần" and tokens[end + 1][0] == "trăm":
            end += 2
            has_suffix = True
        core_len = j - i
        if core_len >= _MIN_STANDALONE_LEN or has_suffix:
            phrase_start = tokens[i][1]
            phrase_end_tok = tokens[end - 1]
            phrase_end = phrase_end_tok[1] + len(phrase_end_tok[0])
            out.append((low[phrase_start:phrase_end], phrase_start))
        i = end if end > i else i + 1
    return out
