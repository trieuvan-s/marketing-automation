"""Bước 4.2 -- đóng dấu brand TẤT ĐỊNH lên ảnh do AI sinh (ai_full.py), bằng
Pillow, KHÔNG bao giờ để AI tự vẽ logo/nguồn/disclaimer (AI không vẽ logo
đúng được -- xem ai_full.py docstring). Vị trí/font/màu CỐ ĐỊNH theo Theme-
rules (prompts/themes/), không phụ thuộc nội dung AI sinh ra.

ĐẢO HƯỚNG P0 (2026-07-23, QUYẾT ĐỊNH LEAD -- xem STOP-REPORT phiên
feature/infographic-frame): CHẨN ĐOÁN GỐC khác giả định cũ -- disclaimer đè
chữ KHÔNG phải lỗi vị trí, mà là hệ quả CẤU TRÚC: nội dung do AI sinh lấp kín
tới sát mép, không còn chỗ trống nào để đóng dấu. Scrim đáy (bản 2026-07-22)
chỉ làm chữ đè TRÔNG đẹp hơn trong khi vẫn CHE MẤT một dòng dữ liệu thật --
lỗi trở nên VÔ HÌNH thay vì được sửa. THAY bằng KHUNG CỨNG ĐÁY: brand_stamp
KHÔNG BAO GIỜ ghi đè lên pixel nội dung -- nó THU ảnh AI vào vùng trong rồi vẽ
band đáy RIÊNG trên phần diện tích còn lại (matting, không phải scrim). Va
chạm chữ/nội dung khi đó là BẤT KHẢ THI VỀ CẤU TRÚC, không phải "đã canh cho
khỏi đụng" (khác biệt cốt lõi, xem docstring `stamp_brand`).

QUY TRÌNH MỚI (đúng thứ tự, xem `stamp_brand`):
  1. EDGE SANITIZER (`_edge_sanitize_top`) -- lưới an toàn cắt dải màu phẳng
     bất thường ở mép trên (vd dải kem do model sinh ảnh coi "safe zone" là
     vật thể cần vẽ, xem ai_full.py Phần B) -- KHÔNG thay cho việc sửa prompt
     (Phần B), chỉ là lưới an toàn tầng dưới.
  2. MATTING (`_matte`) -- resize ảnh AI (sau bước 1) vừa khít vùng trong
     FINAL_W x (FINAL_H - BAND_H), giữ tỷ lệ (cover-fit + cắt cân giữa nếu
     lệch), không kéo giãn méo.
  3. MÀU BAND (`_band_color`) -- màu TRUNG VỊ 20 hàng pixel cuối ảnh đã resize;
     tối (luminance <=140) -> dùng thẳng (mối nối vô hình); sáng -> fallback
     navy FVA cố định (config infographic.ai_full.navy_fallback).
  4. NỘI DUNG BAND (`_layout_band_text`) -- Trái "Nguồn: ...", Phải disclaimer,
     font = 0.30*BAND_H, KHÔNG BAO GIỜ cắt chữ/thu font dưới 18px -- band TỰ
     NỚI cao (matting lại với inner_h nhỏ hơn) nếu 1 dòng không đủ chỗ dù đã
     xuống 2 dòng.
  5. LOGO (`_paste_logo` + scrim CÓ ĐIỀU KIỆN) -- ảnh AI vẫn tràn viền mép
     trên (KHÔNG matting ở đỉnh, chỉ đáy) -- CHỖ DUY NHẤT còn dùng scrim: chỉ
     vẽ khi luminance vùng bbox logo nở 20% > 110 (tương phản thật sự thấp).
  6. LOG JSON (`build_stamp_log`) -- trả kèm bytes để ai_full.py ghi cạnh ảnh,
     Lead kiểm không cần mở ảnh (xem A2 Bước 6, STOP-REPORT).

LOGO THẬT THAY WORDMARK CHỮ (2026-07-22, theo yêu cầu Lead): dán ẢNH logo thật
(`assets/icon_transparent.png`) thay vì vẽ chữ "FVA CAPITAL" bằng font -- xem
lịch sử hội thoại 2026-07-22. File gốc `icon.png`/`logo.png` GIỮ NGUYÊN không
sửa -- chỉ thêm bản `*_transparent.png` cạnh.
"""
from __future__ import annotations

import io
import logging
import statistics
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageStat

logger = logging.getLogger("twmkt.render.brand_stamp")

# 2026-07-23 (Phần A1) -- kích thước khung CUỐI mặc định (dùng khi không có
# `settings`, vd test/gọi trực tiếp) -- ĐỌC ĐƯỢC qua config infographic.
# ai_full.final_size, đây CHỈ là fallback nội bộ, KHÔNG hardcode ở call site.
_DEFAULT_FINAL_SIZES: dict[str, tuple[int, int]] = {
    "4:5": (1080, 1350),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
}
_DEFAULT_BOTTOM_BAND_MIN_PX = 72
_DEFAULT_NAVY_FALLBACK = (6, 21, 33)   # #061521 -- khớp _THEME_COLORS["dark"]["bg"] dưới đây

# Font size tối thiểu tuyệt đối -- DƯỚI mức này dấu tiếng Việt (dấu mũ/móc/
# thanh điệu chồng) bắt đầu vỡ nét ở ảnh raster thường (DỪNG KHI #2, xem
# NHIỆM VỤ 2026-07-22) -- co font KHÔNG được vượt qua ngưỡng này; nếu khối
# chữ vẫn không vừa dải an toàn ở size này, band TỰ NỚI CAO (2026-07-23,
# THAY "báo lỗi rõ ràng" cũ -- kiến trúc mới không còn khái niệm "dải cố định
# không đủ chỗ", band co giãn theo nhu cầu chữ).
_MIN_READABLE_FONT_SIZE = 18

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
# phụ, giảm size 70-80% để tránh lấn chiếm/đè nội dung chính") -- GIỮ áp dụng
# lên base_size TRƯỚC khi vào vòng co-font (min size sàn _MIN_READABLE_FONT_
# SIZE vẫn giữ nguyên, không hạ thêm) -- 2026-07-23: base_size giờ tính từ
# BAND_H (0.30*BAND_H, xem A2 Bước 4) chứ không còn từ top_h/bottom_h cũ,
# nhưng hệ số giảm 75% này vẫn giữ để không đổi CẢM GIÁC kích thước tương đối
# so với bản trước khi Lead so sánh ảnh cũ/mới.
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


def _resolve_final_size(ratio: str, settings=None) -> tuple[int, int]:
    if settings is not None:
        cfg = settings.get("infographic.ai_full.final_size")
        if isinstance(cfg, dict) and ratio in cfg:
            w, h = cfg[ratio]
            return int(w), int(h)
    if ratio in _DEFAULT_FINAL_SIZES:
        return _DEFAULT_FINAL_SIZES[ratio]
    raise ValueError(f"brand_stamp: không có final_size cho tỷ lệ '{ratio}' (config infographic.ai_full.final_size)")


def _resolve_band_min_px(settings=None) -> int:
    if settings is not None:
        v = settings.get("infographic.ai_full.bottom_band_min_px")
        if v is not None:
            return int(v)
    return _DEFAULT_BOTTOM_BAND_MIN_PX


def _resolve_navy_fallback(settings=None) -> tuple[int, int, int]:
    if settings is not None:
        hex_v = settings.get("infographic.ai_full.navy_fallback")
        if isinstance(hex_v, str) and hex_v.strip():
            h = hex_v.strip().lstrip("#")
            if len(h) == 6:
                try:
                    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
                except ValueError:
                    pass
    return _DEFAULT_NAVY_FALLBACK


def _luminance(rgb: tuple[float, float, float]) -> float:
    r, g, b = rgb[:3]
    return 0.299 * r + 0.587 * g + 0.114 * b


# =====================================================================
# Bước 1 -- EDGE SANITIZER (lưới an toàn, KHÔNG thay cho việc sửa prompt)
# =====================================================================

def _edge_sanitize_top(im: Image.Image, *, scan_pct: float = 0.12, min_run: int = 8,
                       std_threshold: float = 12.0, lum_delta_threshold: float = 60.0,
                       below_rows: int = 30) -> tuple[Image.Image, int]:
    """Quét `scan_pct` số hàng pixel trên cùng của ảnh AI. Tìm dải LIÊN TỤC TỪ
    MÉP TRÊN (row 0) dài >= `min_run` hàng thoả CẢ HAI: (a) độ lệch chuẩn màu
    trong mỗi hàng < `std_threshold` (dải PHẲNG màu, không phải ảnh chụp có
    chi tiết thật); (b) luminance trung bình của dải LỆCH (|delta| lớn hơn)
    `lum_delta_threshold` so với luminance TRUNG VỊ của `below_rows` hàng NGAY
    BÊN DƯỚI dải (dải này khác hẳn nền thật bên dưới -- dấu hiệu dải giả do
    model sinh ảnh, KHÔNG phải nền/bầu trời thật trong ảnh chụp). Có cả 2 ->
    CẮT bỏ dải đó, log CROPPED_TOP_BAND=<n>px. Không có -> không làm gì
    (TUYỆT ĐỐI không cắt "phòng xa"). Trả (ảnh có thể đã cắt, số px đã cắt)."""
    w, h = im.size
    scan_h = max(int(h * scan_pct), 1)
    rgb = im.convert("RGB")

    row_std: list[float] = []
    row_lum: list[float] = []
    for r in range(scan_h):
        row = rgb.crop((0, r, w, r + 1))
        stat = ImageStat.Stat(row)
        row_std.append(sum(stat.stddev) / len(stat.stddev))
        row_lum.append(_luminance(tuple(stat.mean)))

    run_len = 0
    for r in range(scan_h):
        if row_std[r] < std_threshold:
            run_len += 1
        else:
            break

    if run_len < min_run:
        return im, 0

    band_mean_lum = sum(row_lum[:run_len]) / run_len

    below_end = min(run_len + below_rows, h)
    below_lums: list[float] = list(row_lum[run_len:min(scan_h, below_end)])
    extra_start = max(scan_h, run_len)
    for r in range(extra_start, below_end):
        row = rgb.crop((0, r, w, r + 1))
        stat = ImageStat.Stat(row)
        below_lums.append(_luminance(tuple(stat.mean)))

    if not below_lums:
        return im, 0
    below_median = statistics.median(below_lums)

    if abs(band_mean_lum - below_median) <= lum_delta_threshold:
        return im, 0

    logger.warning("brand_stamp: EDGE SANITIZER cắt dải mép trên bất thường CROPPED_TOP_BAND=%dpx "
                   "(band_lum=%.1f, below_median=%.1f, delta=%.1f)",
                   run_len, band_mean_lum, below_median, abs(band_mean_lum - below_median))
    cropped = im.crop((0, run_len, w, h))
    return cropped, run_len


# =====================================================================
# Bước 2 -- MATTING (thu ảnh AI vào vùng trong, không đè band đáy)
# =====================================================================

def _matte(im: Image.Image, *, target_w: int, target_h: int) -> Image.Image:
    """Resize `im` vừa khít (target_w, target_h) theo kiểu "cover" (giữ tỷ lệ,
    KHÔNG kéo giãn méo) rồi CẮT CÂN GIỮA phần dư nếu tỷ lệ khung lệch. Đây là
    kỹ thuật object-fit:cover chuẩn -- ảnh LUÔN lấp đầy khung đích, không có
    viền/khoảng trống nào lộ ra."""
    target_w, target_h = max(int(target_w), 1), max(int(target_h), 1)
    src_w, src_h = im.size
    scale = max(target_w / src_w, target_h / src_h)
    new_w, new_h = max(round(src_w * scale), 1), max(round(src_h * scale), 1)
    resized = im.resize((new_w, new_h), Image.LANCZOS)
    left = max((new_w - target_w) // 2, 0)
    top = max((new_h - target_h) // 2, 0)
    return resized.crop((left, top, left + target_w, top + target_h))


# =====================================================================
# Bước 3 -- MÀU BAND (tự khớp bảng màu ảnh AI, fallback navy khi nền sáng)
# =====================================================================

def _median_color(region: Image.Image) -> tuple[int, int, int]:
    """Màu TRUNG VỊ từng kênh (KHÔNG dùng mean -- median bền hơn trước 1-2
    điểm ảnh cực trị, vd 1 highlight sáng lọt vào dải quét). Không có numpy
    trong môi trường này -- tính tay bằng statistics.median (đủ nhanh, vùng
    quét chỉ 20 hàng pixel)."""
    pixels = list(region.convert("RGB").getdata())
    if not pixels:
        return (0, 0, 0)
    return (
        int(statistics.median(p[0] for p in pixels)),
        int(statistics.median(p[1] for p in pixels)),
        int(statistics.median(p[2] for p in pixels)),
    )


def _band_color(matted: Image.Image, *, navy_fallback: tuple[int, int, int],
                lum_threshold: float = 140.0, sample_rows: int = 20) -> tuple[tuple[int, int, int], str]:
    """Màu band = màu TRUNG VỊ của `sample_rows` hàng pixel CUỐI CÙNG của ảnh
    AI ĐÃ RESIZE (matted) -- mối nối band/ảnh AI trở nên VÔ HÌNH vì cùng màu.
    Tối (luminance <= `lum_threshold`) -> dùng thẳng ("matched"). Sáng (band
    sẽ tương phản kém với chữ sáng cố định) -> fallback navy FVA
    ("fallback_navy")."""
    w, h = matted.size
    n = min(sample_rows, h)
    region = matted.crop((0, h - n, w, h))
    color = _median_color(region)
    if _luminance(color) <= lum_threshold:
        return color, "matched"
    return navy_fallback, "fallback_navy"


# =====================================================================
# Chữ -- helper dùng chung (đo THẬT bằng textbbox/textlength, không ước lượng)
# =====================================================================

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


def _block_height(lines: list[str], line_h: int, *, line_gap_ratio: float = 0.28) -> int:
    if not lines:
        return 0
    spacing = int(line_h * line_gap_ratio)
    return len(lines) * line_h + (len(lines) - 1) * spacing


# =====================================================================
# Bước 4 -- NỘI DUNG BAND (Trái "Nguồn:", Phải disclaimer -- band TỰ NỚI CAO)
# =====================================================================

def _layout_band_text(
    draw: ImageDraw.ImageDraw, *, source_text: str, disclaimer_text: str,
    band_w: int, nominal_band_h: int, margin_x: int, font_path: str | None,
) -> dict:
    """Đo (KHÔNG vẽ) khối "Nguồn:" (trái) + disclaimer (phải) -- font =
    0.30*nominal_band_h (Yêu cầu Lead, A2 Bước 4), tối đa 2 dòng/khối, KHÔNG
    BAO GIỜ dưới `_MIN_READABLE_FONT_SIZE`. Trả dict đủ để vẽ + `band_h` THẬT
    (>= nominal_band_h -- band TỰ NỚI nếu chữ cần nhiều chỗ hơn dải danh
    nghĩa, KHÔNG BAO GIỜ cắt chữ)."""
    base_size = max(int(nominal_band_h * 0.30), _MIN_READABLE_FONT_SIZE)
    half_w = band_w // 2
    gap = max(int(band_w * 0.02), 8)
    side_max_w = max(half_w - margin_x - gap // 2, 10)

    src_lines, src_font, src_line_h = _fit_block(
        source_text, base_size=base_size, max_width=side_max_w, draw=draw,
        bold=True, font_path=font_path, max_lines=2,
    )
    dis_lines, dis_font, dis_line_h = _fit_block(
        disclaimer_text, base_size=base_size, max_width=side_max_w, draw=draw,
        bold=False, font_path=font_path, max_lines=2,
    )
    src_h = _block_height(src_lines, src_line_h)
    dis_h = _block_height(dis_lines, dis_line_h)
    v_pad = max(int(nominal_band_h * 0.18), 8)
    needed_h = max(src_h, dis_h) + 2 * v_pad
    band_h = max(nominal_band_h, needed_h)

    return {
        "band_h": band_h, "margin_x": margin_x, "side_max_w": side_max_w,
        "src_lines": src_lines, "src_font": src_font, "src_line_h": src_line_h, "src_h": src_h,
        "dis_lines": dis_lines, "dis_font": dis_font, "dis_line_h": dis_line_h, "dis_h": dis_h,
    }


def _draw_left_block(draw: ImageDraw.ImageDraw, lines: list[str], font: ImageFont.FreeTypeFont,
                     line_h: int, *, x: int, y_center: int, color: tuple[int, int, int, int]) -> None:
    total_h = _block_height(lines, line_h)
    y = y_center - total_h // 2
    spacing = int(line_h * 0.28)
    for line in lines:
        draw.text((x, y), line, font=font, fill=color)
        y += line_h + spacing


def _draw_right_block(draw: ImageDraw.ImageDraw, lines: list[str], font: ImageFont.FreeTypeFont,
                      line_h: int, *, right_x: int, y_center: int, color: tuple[int, int, int, int]) -> None:
    total_h = _block_height(lines, line_h)
    y = y_center - total_h // 2
    spacing = int(line_h * 0.28)
    for line in lines:
        tw = draw.textlength(line, font=font)
        draw.text((right_x - tw, y), line, font=font, fill=color)
        y += line_h + spacing


# =====================================================================
# Bước 5 -- LOGO (ảnh tràn viền mép trên -- scrim CÓ ĐIỀU KIỆN, CHỖ DUY NHẤT)
# =====================================================================

def _region_luminance(im: Image.Image, bbox: tuple[int, int, int, int]) -> float | None:
    x0, y0, x1, y1 = bbox
    w, h = im.size
    x0, y0 = max(x0, 0), max(y0, 0)
    x1, y1 = min(x1, w), min(y1, h)
    if x1 <= x0 or y1 <= y0:
        return None
    region = im.convert("RGB").crop((x0, y0, x1, y1))
    stat = ImageStat.Stat(region)
    return _luminance(tuple(stat.mean))


def _draw_top_scrim(overlay: Image.Image, *, w: int, h: int, scrim_h: int, max_alpha: int = 140) -> None:
    """Scrim gradient ĐEN, alpha 0 (y=0, mép trên) -> `max_alpha` (y=scrim_h)
    -- CHỖ DUY NHẤT còn dùng scrim (A2 Bước 5) -- chỉ gọi khi vùng bbox logo
    nở 20% có luminance > 110 (tương phản thật sự thấp), KHÔNG vẽ mặc định.
    max_alpha=140/255 ~= 0.55 (đúng yêu cầu Lead "alpha 0->0.55")."""
    if scrim_h <= 0:
        return
    grad = Image.new("L", (1, scrim_h))
    for i in range(scrim_h):
        grad.putpixel((0, i), int(max_alpha * (i / max(scrim_h - 1, 1))))
    grad = grad.resize((w, scrim_h))
    scrim_rgba = Image.new("RGBA", (w, scrim_h), (0, 0, 0, 0))
    scrim_rgba.putalpha(grad)
    overlay.alpha_composite(scrim_rgba, (0, 0))


def _paste_logo_with_scrim(canvas: Image.Image, overlay: Image.Image, *, logo_path: Path,
                           pad: int, final_w: int, final_h: int) -> bool:
    """Dán ẢNH logo thật góc trên-trái, lề `pad` (4% chiều rộng, xem
    `stamp_brand`). Đo luminance vùng bbox logo NỞ RA 20% (đo trên `canvas`
    TRƯỚC khi dán logo -- vùng nền thật AI vẽ) -- >110 (tương phản thấp) ->
    vẽ scrim đen (A2 Bước 5) LÊN `overlay` trước khi dán logo. Trả True nếu
    đã vẽ scrim (ghi vào log JSON `scrim_applied`)."""
    scrim_applied = False
    if not logo_path.exists():
        logger.warning("brand_stamp: không tìm thấy file logo '%s' -- bỏ qua, KHÔNG đóng dấu logo.", logo_path)
        return scrim_applied
    try:
        logo = Image.open(logo_path).convert("RGBA")
    except Exception as e:
        logger.warning("brand_stamp: lỗi mở file logo '%s' (%s) -- bỏ qua, KHÔNG đóng dấu logo.", logo_path, e)
        return scrim_applied

    logo_h = max(round(final_h * 0.06), 24)
    logo_w = max(round(logo.width * (logo_h / logo.height)), 1)
    logo_x, logo_y = pad, pad

    expand_x = int(logo_w * 0.20)
    expand_y = int(logo_h * 0.20)
    bbox = (logo_x - expand_x, logo_y - expand_y, logo_x + logo_w + expand_x, logo_y + logo_h + expand_y)
    lum = _region_luminance(canvas, bbox)
    if lum is not None and lum > 110:
        scrim_h = max(round(final_h * 0.14), logo_y + logo_h)
        _draw_top_scrim(overlay, w=final_w, h=final_h, scrim_h=scrim_h)
        scrim_applied = True

    logo_resized = logo.resize((logo_w, logo_h), Image.LANCZOS)
    overlay.alpha_composite(logo_resized, (logo_x, logo_y))
    return scrim_applied


# =====================================================================
# ĐIỂM VÀO CHÍNH
# =====================================================================

def stamp_brand(
    png_bytes: bytes,
    *,
    ratio: str,
    theme: str = "dark",
    wordmark: str = "FVA CAPITAL",
    source: str = "",
    disclaimer: str = "",
    font_path: str | None = None,
    logo_path: str | Path | None = None,
    settings=None,
) -> tuple[bytes, dict]:
    """Đóng dấu brand THEO KIẾN TRÚC KHUNG CỨNG ĐÁY (2026-07-23, THAY hoàn
    toàn hướng scrim đáy 2026-07-22 -- xem module docstring, đây là ĐẢO
    HƯỚNG P0 quyết định bởi Lead sau khi xem ảnh thật cho thấy scrim che mất
    dữ liệu thật thay vì sửa lỗi).

    KHÁC BIỆT CỐT LÕI với bản cũ: brand_stamp KHÔNG BAO GIỜ vẽ ĐÈ lên pixel
    ảnh AI. Nó THU ảnh AI (matting, Bước 2) vào 1 vùng NHỎ HƠN khung cuối rồi
    vẽ band đáy TRÊN PHẦN DIỆN TÍCH RIÊNG còn lại (Bước 3-4) -- va chạm chữ
    với nội dung là BẤT KHẢ THI VỀ CẤU TRÚC (không có pixel chung giữa vùng
    ảnh AI và vùng band), khác "canh toạ độ cho khỏi đụng" (có thể sai khi dữ
    liệu đổi) của kiến trúc cũ.

    Trả (PNG bytes ĐÃ đóng dấu, log dict) -- log PHẢI được ai_full.py ghi
    cạnh ảnh (JSON) để Lead kiểm không cần mở ảnh (A2 Bước 6): {cropped_top_
    px, band_h, band_color, band_color_source, scrim_applied, source_text,
    disclaimer_lines, final_wh}."""
    theme = theme if theme in _THEME_COLORS else "dark"
    colors = _THEME_COLORS[theme]

    im = Image.open(io.BytesIO(png_bytes)).convert("RGB")

    # --- Bước 1: edge sanitizer (lưới an toàn, KHÔNG thay cho sửa prompt) ---
    im, cropped_top_px = _edge_sanitize_top(im)

    # --- Bước 2: matting vào vùng trong (final_h - band_h danh nghĩa) -------
    final_w, final_h = _resolve_final_size(ratio, settings)
    band_min_px = _resolve_band_min_px(settings)
    nominal_band_h = max(round(final_h * 0.075), band_min_px)
    matted = _matte(im, target_w=final_w, target_h=final_h - nominal_band_h)

    # --- Bước 3: màu band tự khớp -------------------------------------------
    navy_fallback = _resolve_navy_fallback(settings)
    band_color, band_color_source = _band_color(matted, navy_fallback=navy_fallback)

    # --- Bước 4: đo nội dung band (CÓ THỂ khiến band nới cao hơn danh nghĩa) -
    margin_x = max(int(final_w * 0.04), 12)
    source_short = _shorten_source(source)
    source_text = f"Nguồn: {source_short}" if source_short else ""
    probe_canvas = Image.new("RGB", (final_w, final_h))
    probe_draw = ImageDraw.Draw(probe_canvas)
    layout = _layout_band_text(
        probe_draw, source_text=source_text, disclaimer_text=disclaimer,
        band_w=final_w, nominal_band_h=nominal_band_h, margin_x=margin_x, font_path=font_path,
    )
    band_h = layout["band_h"]
    if band_h != nominal_band_h:
        # NỚI band -- re-matte với inner_h nhỏ hơn (final_h GIỮ NGUYÊN, xem A1
        # -- khung xuất bản cố định, phần hy sinh là diện tích ảnh AI, KHÔNG
        # BAO GIỜ là chữ bị cắt).
        matted = _matte(im, target_w=final_w, target_h=final_h - band_h)
        band_color, band_color_source = _band_color(matted, navy_fallback=navy_fallback)

    # --- Dựng canvas cuối: ảnh AI (đã matte) TRÊN + band màu ĐÁY, KHÔNG chồng
    canvas = Image.new("RGB", (final_w, final_h), band_color)
    canvas.paste(matted, (0, 0))
    overlay = Image.new("RGBA", (final_w, final_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    band_top_y = final_h - band_h
    band_center_y = band_top_y + band_h // 2
    draw.rectangle((0, band_top_y, final_w, final_h), fill=(*band_color, 255))
    if source_text:
        _draw_left_block(draw, layout["src_lines"], layout["src_font"], layout["src_line_h"],
                         x=margin_x, y_center=band_center_y, color=(*colors["gold"], 255))
    if disclaimer:
        _draw_right_block(draw, layout["dis_lines"], layout["dis_font"], layout["dis_line_h"],
                          right_x=final_w - margin_x, y_center=band_center_y, color=(*colors["muted"], 255))

    # --- Bước 5: logo (tràn viền mép trên) + scrim CÓ ĐIỀU KIỆN ------------
    resolved_logo_path = Path(logo_path) if logo_path else _DEFAULT_LOGO_PATH
    pad = max(int(final_w * 0.04), 16)
    scrim_applied = _paste_logo_with_scrim(canvas, overlay, logo_path=resolved_logo_path,
                                          pad=pad, final_w=final_w, final_h=final_h)

    stamped = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    out = io.BytesIO()
    stamped.save(out, format="PNG")

    log = {
        "cropped_top_px": cropped_top_px,
        "band_h": band_h,
        "band_color": "#%02x%02x%02x" % band_color,
        "band_color_source": band_color_source,
        "scrim_applied": scrim_applied,
        "source_text": source_text,
        "disclaimer_lines": layout["dis_lines"],
        "final_wh": [final_w, final_h],
    }
    return out.getvalue(), log
