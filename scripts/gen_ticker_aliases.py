"""Bổ sung alias PHIÊN ÂM mã chứng khoán vào từ điển resolver của aigen-pipeline.

    python scripts/gen_ticker_aliases.py --dry-run   # xem sẽ thêm gì
    python scripts/gen_ticker_aliases.py             # ghi thật

VÌ SAO CẦN (phát hiện khi chạy thật 2026-07-28): `alias-guardrail` của aigen
CHẶN mọi `voiceText` còn chứa mã viết hoa chưa có phiên âm — TTS sẽ đọc "ACB"
thành từng chữ cái rời rạc (bài học "VNM = vi na miu"). Từ điển resolver chỉ
có 56 mục nên gần như bài nào nhắc tên mã cũng không render được video.

HAI KHO PHIÊN ÂM TỒN TẠI SONG SONG MÀ CHƯA AI NỐI (đây mới là gốc rễ):
  (1) `financial_voice_bible/normalizer/text_normalizer.py` — bảng 108 mục
      VIẾT TAY, đã kiểm chứng, gồm cả ca khó: `USD -> "đô la mỹ"` (KHÔNG phải
      đánh vần "u ét dê"), `VND -> "vê en đê"` kèm ghi chú phân biệt nghĩa
      tiền tệ. Nhưng bảng này nằm ở tầng Python của fvb, mà
      `config/tts.config.json` đang để `speechLayer: "off"` -> tầng đó KHÔNG
      chạy trong đường aigen.
  (2) `financial_voice_bible/data/pronunciation_dict.vi.json` — 56 mục, là
      thứ DUY NHẤT aigen (TypeScript) đọc qua `loadPronunciationDictionary()`.

Script này NỐI (1) vào (2), rồi mới sinh máy móc cho phần còn thiếu.

THỨ TỰ ƯU TIÊN (quan trọng — quyết định chất lượng phát âm):
  1. Mục ĐÃ CÓ trong dict resolver  -> GIỮ NGUYÊN, không đụng.
  2. Mục trong bảng 108 của fvb      -> CHÉP NGUYÊN VĂN (đã kiểm chứng).
  3. Mã còn lại trong VALID_TICKERS  -> sinh máy móc theo tên chữ cái tiếng
     Việt, khớp nếp các mục sẵn có ("VN-Index" -> "vê en in-đếch").

Nhờ (2), ca `USD` ra "đô la mỹ" chứ không phải "u ét dê" — đúng thứ test
`pronunciation.test.ts` ("no invented entries") sinh ra để bảo vệ.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

from twmkt.config import aigen_repo_path, load_settings  # noqa: E402
from twmkt.curation.vn_tickers import VALID_TICKERS  # noqa: E402

_FVB = Path("financial-voice-bible") / "financial_voice_bible"
_DICT_REL = _FVB / "data" / "pronunciation_dict.vi.json"
_NORMALIZER_REL = _FVB / "normalizer" / "text_normalizer.py"

# Cách đọc chữ cái trong NGÔN NGỮ TÀI CHÍNH của người Việt (quy tắc Lead chốt
# 2026-07-29) — KHÔNG thuần Việt cũng không thuần Anh, pha lẫn chủ yếu ở 5 ký
# tự: G="gờ" (HPG -> "hát pê gờ"), M="mờ" (MSN -> "mờ ét nờ"), N="nờ",
# L="lờ", J="gi". PHẢI KHỚP bảng trong financial_voice_bible/normalizer/
# text_normalizer.py — bảng đó là nguồn sự thật, đây chỉ là bản sinh cho mã
# chưa có mặt ở đó.
_LETTER = {
    "A": "a", "B": "bê", "C": "xê", "D": "dê", "E": "e", "F": "ép", "G": "gờ",
    "H": "hát", "I": "i", "J": "gi", "K": "ca", "L": "lờ", "M": "mờ", "N": "nờ",
    "O": "o", "P": "pê", "Q": "quy", "R": "rờ", "S": "ét", "T": "tê", "U": "u",
    "V": "vê", "W": "đắp liu", "X": "ích", "Y": "i", "Z": "dét",
    "0": "không", "1": "một", "2": "hai", "3": "ba", "4": "bốn",
    "5": "năm", "6": "sáu", "7": "bảy", "8": "tám", "9": "chín",
}
_ENTRY_RE = re.compile(r'^\s*"([A-Z0-9][A-Z0-9\-]{1,})":\s*"([^"]+)"', re.M)


def spell(ticker: str) -> str:
    """"ACB" -> "a xê bê". Ký tự lạ bị bỏ qua, KHÔNG đoán."""
    return " ".join(_LETTER[c] for c in ticker.upper() if c in _LETTER)


def load_fvb_verified(root: Path) -> dict[str, str]:
    """Bảng phiên âm VIẾT TAY trong fvb normalizer — nguồn ĐÃ KIỂM CHỨNG.

    Đọc bằng regex thay vì import module: fvb là package Python riêng, import
    nó kéo theo cả phụ thuộc của nó (adapters/api/audio) mà script này không
    cần và có thể chưa cài. Bảng là literal dict phẳng nên regex đủ chắc; đọc
    hụt vài dòng thì tệ nhất là mã đó rơi xuống nhánh sinh máy móc, KHÔNG phải
    ra giá trị sai."""
    path = root / _NORMALIZER_REL
    if not path.exists():
        print(f"[CẢNH BÁO] không thấy {path} — bỏ qua bảng fvb đã kiểm chứng.")
        return {}
    return dict(_ENTRY_RE.findall(path.read_text(encoding="utf-8")))


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    root = aigen_repo_path(settings=load_settings())
    path = (root / _DICT_REL).resolve()
    if not path.exists():
        print(f"[LỖI] Không thấy từ điển: {path}")
        return 1

    raw = json.loads(path.read_text(encoding="utf-8"))
    before = len([k for k in raw if not k.startswith("_")])

    verified = load_fvb_verified(root)
    from_fvb = generated = 0
    for key, val in verified.items():
        # fvb GHI ĐÈ mục sẵn có (2026-07-29): bảng normalizer là nơi Lead chốt
        # quy tắc phát âm (G="gờ", M="mờ", N="nờ", L="lờ", J="gi", và các từ
        # đọc nguyên như GAS="gát", VNM="vinamilk"). Nếu chỉ "điền chỗ trống"
        # thì mọi lần sửa quy tắc sẽ KHÔNG lan tới đây — đúng cái vừa xảy ra
        # với VNM/PNJ. Bảng fvb = nguồn sự thật, dict resolver = bản chiếu.
        if raw.get(key) != val:
            raw[key] = val
            from_fvb += 1
    for t in sorted(VALID_TICKERS):
        if t in raw:
            continue
        alias = spell(t)
        if alias:
            raw[t] = alias
            generated += 1

    after = len([k for k in raw if not k.startswith("_")])
    print(f"Từ điển  : {path}")
    print(f"Trước    : {before} mục")
    print(f"+ fvb     : {from_fvb} mục CHÉP NGUYÊN VĂN từ bảng đã kiểm chứng")
    print(f"+ sinh máy: {generated} mã còn lại")
    print(f"Sau      : {after} mục")
    for t in ("USD", "VND", "ACB", "FPT"):
        src = "fvb" if t in verified else ("sinh máy" if t in raw else "-")
        print(f"   {t:5} -> {raw.get(t, '(không có)'):18} [{src}]")
    if dry:
        print("\n--dry-run: KHÔNG ghi file.")
        return 0

    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\nĐã ghi. Mục sẵn có giữ nguyên; bảng fvb thắng phần sinh máy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
