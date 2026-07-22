"""Bước 4.2 -- đóng dấu brand TẤT ĐỊNH lên ảnh do AI sinh (ai_full.py), bằng
Pillow, KHÔNG bao giờ để AI tự vẽ logo/nguồn/disclaimer (AI không vẽ logo
đúng được -- xem ai_full.py docstring). Vị trí/font/màu CỐ ĐỊNH theo Theme-
rules (prompts/themes/), không phụ thuộc nội dung AI sinh ra.

Vẽ trong đúng 2 dải trống mà prompt (ai_full.build_ai_full_prompt) đã yêu cầu
AI chừa lại (top/bottom safe %, xem ai_full._TOP_SAFE_PCT/_BOTTOM_SAFE_PCT) --
nếu AI không tuân thủ hoàn toàn, vẫn vẽ đè lên (opaque, không phụ thuộc AI).

SỬA LỖI P0 (2026-07-22, phát hiện qua ảnh thật CẢ 4 tỷ lệ -- bản "v2fix"
trước đó VẪN hỏng vì chỉ test bằng chuỗi ngắn, không bắt được lỗi ở chuỗi dài/
tỷ lệ hẹp): bản cũ dùng `line_h` ƯỚC LƯỢNG cố định (`bottom_h * 0.38`) không
khớp chiều cao chữ THẬT ở font size đã chọn -- khi disclaimer/nguồn wrap
nhiều dòng (chuỗi dài, tỷ lệ hẹp như 9:16), khối "Nguồn" bắt đầu vẽ ĐÈ LÊN
khối "disclaimer" chưa vẽ xong. Sửa tận gốc: đo chiều cao THẬT bằng
`draw.textbbox()` với ĐÚNG font/size sẽ render (không ước lượng), XẾP KHỐI
TỪ DƯỚI LÊN (khối "Nguồn" neo đáy trước, khối disclaimer xếp NGAY TRÊN nó),
và CO FONT (không bao giờ cắt cụt chữ) khi khối không vừa dải an toàn.

LOGO THẬT THAY WORDMARK CHỮ (2026-07-22, theo yêu cầu Lead): trước đây vẽ
chữ "FVA CAPITAL" bằng font -- giờ dán ẢNH logo thật (`assets/icon_transparent
.png`, xử lý từ `assets/icon.png` do Lead cung cấp -- bản gốc KHÔNG có kênh
alpha thật, nền "ca-rô" chỉ là pixel xám nhạt vẽ cứng, đã tách nền bằng
connected-component analysis + 1 vùng xác nhận bằng mắt là lỗ chữ "F", xem
lịch sử hội thoại 2026-07-22 -- KHÔNG dùng heuristic màu/kích thước/texture
đơn thuần vì mặt phẳng trắng thật của logo trùng dải màu với nền ca-rô, đã
thử và làm hỏng logo 2 lần trước khi tìm ra cách đúng). File gốc `icon.png`/
`logo.png` GIỮ NGUYÊN không sửa -- chỉ thêm bản `*_transparent.png` cạnh.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("twmkt.render.brand_stamp")

_TOP_SAFE_PCT = 0.10
_BOTTOM_SAFE_PCT = 0.08

# Font size tối thiểu tuyệt đối -- DƯỚI mức này dấu tiếng Việt (dấu mũ/móc/
# thanh điệu chồng) bắt đầu vỡ nét ở ảnh raster thường (DỪNG KHI #2, xem
# NHIỆM VỤ 2026-07-22) -- co font KHÔNG được vượt qua ngưỡng này; nếu khối
# chữ vẫn không vừa dải an toàn ở size này, PHẢI báo lỗi rõ ràng thay vì âm
# thầm vẽ đè/tràn.
_MIN_READABLE_FONT_SIZE = 16

_THEME_COLORS = {
    "dark": {"bg": (6, 21, 33), "text": (243, 235, 221), "muted": (200, 208, 212), "gold": (201, 161, 74)},
    "light": {"bg": (246, 240, 229), "text": (31, 31, 31), "muted": (96, 103, 107), "gold": (201, 161, 74)},
}

# Chuỗi ứng viên đường dẫn font TTF hỗ trợ dấu tiếng Việt -- thử LẦN LƯỢT,
# CÙNG NẾP config-first (settings.yaml có thể ghi đè qua render.ai_full.
# brand_font_path). Windows dev-machine (arial.ttf) lẫn Linux VPS phổ biến
# (DejaVuSans, Noto) đều liệt kê -- không hardcode CHỈ 1 máy.
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
]

_BOLD_HINT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

# Logo THẬT (ảnh, không phải chữ vẽ) -- mặc định trỏ tới bản đã tách nền
# (assets/icon_transparent.png, cạnh assets/icon.png gốc KHÔNG có alpha).
_DEFAULT_LOGO_PATH = Path(__file__).resolve().parents[3] / "assets" / "icon_transparent.png"

# Font disclaimer/nguồn = 75% cỡ chữ CŨ (yêu cầu Lead 2026-07-22: "thông tin
# phụ, giảm size 70-80% để tránh lấn chiếm/đè nội dung chính") -- áp dụng lên
# base_size TRƯỚC khi vào vòng co-font của _fit_block (min size sàn
# _MIN_READABLE_FONT_SIZE vẫn giữ nguyên, không hạ thêm).
_SECONDARY_TEXT_SCALE = 0.75


def _shorten_source(source: str) -> str:
    """Chỉ hiện TÊN TRANG BÁO (vd "CafeF"), KHÔNG hiện trích dẫn đầy đủ (vd
    "HoSE - Thông báo thay đổi tình trạng chứng khoán cổ phiếu HVN") -- yêu
    cầu Lead 2026-07-22. Tách theo dấu " - " đầu tiên (quy ước nguồn thật
    trong repo: "<tên trang> - <mô tả>", xem spec thật
    reports/phase2_verify/*.json) -- KHÔNG có " - " thì giữ nguyên chuỗi gốc
    (đã ngắn sẵn, vd "cafef.vn")."""
    if not source:
        return ""
    return source.split(" - ", 1)[0].strip()


def _paste_logo(overlay: Image.Image, *, logo_path: Path, pad: int, top_h: int) -> None:
    """Dán ẢNH logo thật (RGBA, đã có kênh alpha) vào góc trên-trái, chiều
    cao = 55% dải an toàn đỉnh, giữ nguyên tỉ lệ khung hình -- THAY hoàn toàn
    việc vẽ chữ "FVA CAPITAL" bằng font (AI/font không bao giờ vẽ ĐÚNG logo
    được, xem module docstring). Thiếu file logo -> ghi cảnh báo, KHÔNG crash
    (đóng dấu brand vẫn phải ra ảnh hợp lệ dù thiếu asset)."""
    if not logo_path.exists():
        logger.warning("brand_stamp: không tìm thấy file logo '%s' -- bỏ qua, KHÔNG đóng dấu logo.", logo_path)
        return
    try:
        logo = Image.open(logo_path).convert("RGBA")
    except Exception as e:
        logger.warning("brand_stamp: lỗi mở file logo '%s' (%s) -- bỏ qua, KHÔNG đóng dấu logo.", logo_path, e)
        return
    target_h = max(int(top_h * 0.55), 24)
    target_w = max(int(logo.width * (target_h / logo.height)), 1)
    logo = logo.resize((target_w, target_h), Image.LANCZOS)
    logo_y = int(top_h * 0.22)
    overlay.alpha_composite(logo, (pad, logo_y))


def _wrap_to_width(text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    """Bọc `text` thành nhiều dòng sao cho MỖI dòng vừa `max_width` px theo
    `font` -- đo bằng `draw.textlength` (Pillow >=8) với ĐÚNG font sẽ vẽ,
    KHÔNG ước lượng ký tự/dòng. Chỉ tách ở khoảng trắng (KHÔNG BAO GIỜ cắt
    giữa từ) -- nếu 1 TỪ ĐƠN LẺ đã dài hơn `max_width` (hiếm, vd URL dài),
    vẫn giữ nguyên từ đó trên 1 dòng riêng (tràn width còn hơn cắt vỡ từ)."""
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _draw_bottom_scrim(overlay: Image.Image, *, w: int, h: int, top_y: int, bg_color: tuple[int, int, int],
                       max_alpha: int = 235, fade_frac: float = 0.35) -> None:
    """Vẽ dải nền mờ dần (scrim) từ `top_y` xuống ĐÁY ẢNH THẬT, TRƯỚC khi vẽ
    chữ disclaimer/nguồn lên trên -- kỹ thuật CHUẨN cho phụ đề/caption (đảm
    bảo đọc được BẤT KỂ AI vẽ gì bên dưới, không cần đoán/phân tích pixel ảnh
    nền). SỬA LỖI P0 #4 (2026-07-22): trước đây khối chữ khi "nhô lên" khỏi
    dải AI chừa có thể đè trực tiếp lên nội dung AI (vd khối "Điểm nổi bật")
    KHÔNG có gì che phía sau -- chữ và nội dung AI trộn lẫn, không đọc được.
    Fade dần ở top_y (KHÔNG cắt cụt đột ngột) để không tạo viền cứng phản
    thẩm mỹ giữa vùng ảnh AI và vùng chữ."""
    scrim_h = h - top_y
    if scrim_h <= 0:
        return
    grad = Image.new("L", (1, scrim_h), max_alpha)
    fade_px = max(int(scrim_h * fade_frac), 1)
    for i in range(min(fade_px, scrim_h)):
        grad.putpixel((0, i), int(max_alpha * (i / fade_px)))
    grad = grad.resize((w, scrim_h))
    scrim_rgba = Image.new("RGBA", (w, scrim_h), (*bg_color, 0))
    scrim_rgba.putalpha(grad)
    overlay.alpha_composite(scrim_rgba, (0, top_y))


def _find_font(size: int, *, bold: bool = False, extra_path: str | None = None) -> ImageFont.FreeTypeFont:
    if bold:
        candidates = ([extra_path] if extra_path else []) + _BOLD_HINT_CANDIDATES + _FONT_CANDIDATES
    else:
        candidates = ([extra_path] if extra_path else []) + _FONT_CANDIDATES
    for path in candidates:
        if path and Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
    logger.warning("Không tìm thấy font TTF nào trong _FONT_CANDIDATES -- lùi về PIL default (có thể lỗi dấu tiếng Việt)")
    return ImageFont.load_default(size=size)


def _line_height(line: str, font: ImageFont.FreeTypeFont, draw: ImageDraw.ImageDraw) -> int:
    """Chiều cao THẬT của 1 dòng chữ theo font -- dùng `textbbox` (đo ink
    box thật, không ước lượng). Dùng chuỗi có dấu tiếng Việt CAO NHẤT có thể
    ("ẢỆÔ...") kèm `line` để chiều cao ổn định dù `line` không có dấu cao
    (tránh 2 dòng liền kề cao thấp khác nhau gây lệch baseline khó đọc)."""
    probe = line + "Ậ ẾỀ"
    bbox = draw.textbbox((0, 0), probe, font=font)
    return max(bbox[3] - bbox[1], 1)


def _fit_block(
    text: str, *, base_size: int, max_width: int, draw: ImageDraw.ImageDraw,
    bold: bool, font_path: str | None, max_lines: int,
) -> tuple[list[str], ImageFont.FreeTypeFont, int]:
    """Tìm font size LỚN NHẤT (từ `base_size` giảm dần, không dưới
    `_MIN_READABLE_FONT_SIZE`) sao cho `text` bọc vừa `max_lines` dòng trong
    `max_width`. KHÔNG BAO GIỜ cắt cụt chữ -- nếu ngay cả ở size tối thiểu
    vẫn cần nhiều dòng hơn `max_lines`, trả về NGUYÊN VẸN toàn bộ nội dung
    (nhiều dòng hơn dự kiến) ở size tối thiểu, KHÔNG bỏ bớt chữ. Trả
    (lines, font, chiều_cao_1_dòng)."""
    if not text:
        return [], _find_font(base_size, bold=bold, extra_path=font_path), 0
    size = base_size
    while size >= _MIN_READABLE_FONT_SIZE:
        font = _find_font(size, bold=bold, extra_path=font_path)
        lines = _wrap_to_width(text, font, max_width, draw)
        if len(lines) <= max_lines:
            return lines, font, _line_height(lines[0], font, draw)
        size -= 2
    font = _find_font(_MIN_READABLE_FONT_SIZE, bold=bold, extra_path=font_path)
    lines = _wrap_to_width(text, font, max_width, draw)
    return lines, font, _line_height(lines[0], font, draw)


def stamp_brand(
    png_bytes: bytes,
    *,
    theme: str = "dark",
    wordmark: str = "FVA CAPITAL",
    source: str = "",
    disclaimer: str = "",
    font_path: str | None = None,
    logo_path: str | Path | None = None,
) -> bytes:
    """Đóng dấu logo THẬT (ảnh, góc trên-trái, trong dải an toàn đỉnh -- xem
    `_paste_logo()`, `wordmark` giữ lại CHỈ để tương thích/log, KHÔNG còn vẽ
    chữ) + nguồn/disclaimer (đáy, trong dải an toàn đáy, cỡ chữ giảm còn 75%
    -- thông tin phụ, xem `_SECONDARY_TEXT_SCALE`) lên `png_bytes`. `source`
    tự động rút gọn CHỈ còn tên trang (xem `_shorten_source()`) trước khi vẽ.
    Trả PNG bytes mới. HÀM THUẦN theo nghĩa không I/O ngoài decode/encode ảnh
    + đọc file logo cục bộ -- không gọi mạng, chạy lại bất kỳ lúc nào ($0,
    không cần sinh ảnh AI lại nếu chỉ đổi brand/font/logo).

    XẾP KHỐI TỪ DƯỚI LÊN (sửa lỗi chồng đè P0): khối "Nguồn" neo NGAY TRÊN
    mép đáy trước, sau đó khối disclaimer xếp NGAY TRÊN khối "Nguồn" -- dòng
    trên = dòng dưới - chiều_cao_thật - khoảng_cách_tối_thiểu, không hardcode
    toạ độ Y cho bất kỳ dòng nào. Nếu tổng chiều cao 2 khối VƯỢT dải an toàn
    đáy đã đo, khối được phép vẽ NHÔ lên trên dải đó (vẫn LUÔN nằm trong biên
    ảnh -- không bao giờ tràn mép ảnh thật, chỉ có thể vượt dải ~8% AI chừa)."""
    theme = theme if theme in _THEME_COLORS else "dark"
    colors = _THEME_COLORS[theme]

    im = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    w, h = im.size
    top_h = int(h * _TOP_SAFE_PCT)
    bottom_h = int(h * _BOTTOM_SAFE_PCT)
    pad = max(int(w * 0.04), 16)
    max_text_width = w - 2 * pad

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # --- logo THẬT (đỉnh, thay chữ "FVA CAPITAL" vẽ bằng font) ---------------
    resolved_logo_path = Path(logo_path) if logo_path else _DEFAULT_LOGO_PATH
    _paste_logo(overlay, logo_path=resolved_logo_path, pad=pad, top_h=top_h)

    # --- đo THẬT trước khi vẽ (đáy) -- cỡ chữ = 75% cũ, thông tin phụ --------
    disclaimer_base = max(int(bottom_h * 0.30 * _SECONDARY_TEXT_SCALE), _MIN_READABLE_FONT_SIZE)
    disclaimer_lines, disclaimer_font, disclaimer_line_h = _fit_block(
        disclaimer, base_size=disclaimer_base,
        max_width=max_text_width, draw=draw, bold=False, font_path=font_path, max_lines=2,
    )
    source_short = _shorten_source(source)
    source_text = f"Nguồn: {source_short}" if source_short else ""
    source_base = max(int(bottom_h * 0.34 * _SECONDARY_TEXT_SCALE), _MIN_READABLE_FONT_SIZE)
    source_lines, source_font, source_line_h = _fit_block(
        source_text, base_size=source_base,
        max_width=max_text_width, draw=draw, bold=True, font_path=font_path, max_lines=2,
    )

    line_gap_ratio = 0.28   # khoảng cách GIỮA các dòng CÙNG khối, theo tỷ lệ chiều cao dòng
    block_gap_ratio = 0.55  # khoảng cách GIỮA 2 khối (disclaimer / nguồn), rộng hơn line_gap để phân biệt rõ 2 khối

    def _block_height(lines: list[str], line_h: int) -> int:
        if not lines:
            return 0
        spacing = int(line_h * line_gap_ratio)
        return len(lines) * line_h + (len(lines) - 1) * spacing

    disclaimer_h = _block_height(disclaimer_lines, disclaimer_line_h)
    source_h = _block_height(source_lines, source_line_h)
    block_gap = int(max(disclaimer_line_h, source_line_h, 1) * block_gap_ratio) if (disclaimer_lines and source_lines) else 0
    total_h = disclaimer_h + block_gap + source_h

    bottom_edge_margin = max(int(h * 0.015), 6)   # đệm nhỏ tới MÉP ẢNH THẬT -- ranh giới CỨNG, không bao giờ vượt
    if total_h > bottom_h - bottom_edge_margin:
        logger.warning(
            "brand_stamp: khối disclaimer+nguồn (%dpx) vượt dải an toàn đáy AI chừa (%dpx) dù đã co font "
            "xuống %dpx -- vẽ NHÔ lên trên dải đó (vẫn trong biên ảnh), dùng scrim nền để đảm bảo đọc được.",
            total_h, bottom_h, _MIN_READABLE_FONT_SIZE,
        )

    # --- scrim nền (LUÔN vẽ, không chỉ khi vượt dải -- đảm bảo đọc được nhất
    # quán trên MỌI ảnh, không phụ thuộc AI vẽ gì bên dưới) --------------------
    scrim_padding = max(int(h * 0.015), 8)
    scrim_top_y = max(0, h - bottom_edge_margin - total_h - scrim_padding)
    _draw_bottom_scrim(overlay, w=w, h=h, top_y=scrim_top_y, bg_color=colors["bg"])

    # --- xếp khối TỪ DƯỚI LÊN: "Nguồn" trước (đáy), disclaimer NGAY TRÊN nó --
    cursor_y = h - bottom_edge_margin - source_h   # đỉnh của khối "Nguồn"
    spacing_source = int(source_line_h * line_gap_ratio)
    y = cursor_y
    for line in source_lines:
        draw.text((pad, y), line, font=source_font, fill=(*colors["gold"], 255))
        y += source_line_h + spacing_source

    cursor_y -= block_gap + disclaimer_h   # đỉnh của khối disclaimer
    spacing_disclaimer = int(disclaimer_line_h * line_gap_ratio)
    y = cursor_y
    for line in disclaimer_lines:
        draw.text((pad, y), line, font=disclaimer_font, fill=(*colors["muted"], 255))
        y += disclaimer_line_h + spacing_disclaimer

    stamped = Image.alpha_composite(im, overlay).convert("RGB")
    out = io.BytesIO()
    stamped.save(out, format="PNG")
    return out.getvalue()
