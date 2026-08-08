"""Bước 4.2 -- đóng dấu brand TẤT ĐỊNH lên ảnh do AI sinh (ai_full.py), bằng
Pillow, KHÔNG bao giờ để AI tự vẽ logo/nguồn/disclaimer (AI không vẽ logo
đúng được -- xem ai_full.py docstring). Màu đọc trực tiếp từ bảng DESIGN
TOKENS trong Theme-rules (prompts/themes/); các mục layout D*/L* không được
áp dụng.

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

SỬA LỖI ĐẶC TẢ (2026-07-24, QUYẾT ĐỊNH LEAD -- Phần A2 bản 2026-07-23 ở trên
tự nó có 1 lỗi đặc tả tại BƯỚC 2/5): "resize vừa khít vùng trong, cắt cân
giữa nếu lệch" (center-crop/cover-fit) ăn mất nội dung ở CẢ HAI ĐẦU khi tỷ lệ
ảnh AI lệch tỷ lệ vùng trong -- bằng chứng ảnh thật 6/6: tiêu đề cụt ở ĐỈNH
VÀ dòng/chip cuối cùng cụt ở ĐÁY CÙNG LÚC (chữ ký kinh điển của center-crop:
cắt đối xứng 2 đầu). Đồng thời logo (Bước 5 cũ) vẫn đặt ĐÈ lên ảnh AI tràn
viền mép trên (không matting ở đỉnh) -- scrim chỉ che tạm, không sửa gốc.
SỬA: Bước 2 đổi hẳn sang FIT-INSIDE (contain, KHÔNG BAO GIỜ cover/crop, KHÔNG
phóng to quá độ phân giải gốc -- scale_factor luôn <=1.0), dành riêng đủ chỗ
TOP_PAD cho logo NGAY TRONG phép tính scale (trừ thẳng vào target_h trước khi
fit, xem `_matte`) -- logo giờ dán vào TOP_PAD (dải màu band phẳng, không còn
ảnh AI bên dưới để đè) THAY VÌ đè lên ảnh AI -- scrim (Bước 5 cũ) do đó VÔ
NGHĨA, XOÁ HẲN. Kích thước gọi API (`select_ai_size`) cũng tính lại khớp
ratio_inner = FINAL_W/(FINAL_H-BAND_H) thay vì bảng cố định cũ lệch xa tỷ lệ
thật (xác nhận qua gọi API thật 2026-07-24: gpt-image-2 chấp nhận size TUỲ Ý
chia hết 16, KHÔNG phải enum cố định -- xem `select_ai_size` docstring).

QUY TRÌNH (đúng thứ tự, xem `stamp_brand`):
  1. EDGE SANITIZER (`_edge_sanitize_top`) -- lưới an toàn cắt dải màu phẳng
     bất thường ở mép trên (vd dải kem do model sinh ảnh coi "safe zone" là
     vật thể cần vẽ, xem ai_full.py Phần B) -- KHÔNG thay cho việc sửa prompt
     (Phần B), chỉ là lưới an toàn tầng dưới.
  2. MATTING (`_matte`) -- FIT-INSIDE ảnh AI (sau bước 1) vào vùng trong
     FINAL_W x (FINAL_H - BAND_H), TRỪ SẴN chỗ TOP_PAD cho logo (2e) --
     scale_factor = min(1.0, target_w/src_w, (inner_h-TOP_PAD_MIN)/src_h) --
     KHÔNG BAO GIỜ vượt 1.0 (không phóng to), KHÔNG BAO GIỜ cắt (ảnh luôn nằm
     TRỌN VẸN trong vùng cho phép). Phần dư DỌC dồn hết lên ĐỈNH, phần dư
     NGANG chia đều 2 bên -- lấp bằng ĐÚNG màu band (mối nối vô hình).
  3. MÀU BAND (`_band_color`) -- màu TRUNG VỊ 20 hàng pixel cuối ảnh đã fit;
     tối (luminance <=140) -> dùng thẳng (mối nối vô hình); sáng -> fallback
     navy FVA cố định (config infographic.ai_full.navy_fallback).
  4. NỘI DUNG BAND (`_layout_band_text`) -- Trái "Nguồn: ...", Phải disclaimer,
     font = 0.30*BAND_H*text_scale, KHÔNG BAO GIỜ cắt chữ/thu font dưới 18px -- band TỰ
     NỚI cao (matting lại với inner_h nhỏ hơn) nếu 1 dòng không đủ chỗ dù đã
     xuống 2 dòng.
  5. LOGO (`_paste_logo`) -- dán vào TOP_PAD (dải màu band phẳng ở đỉnh, đã
     bảo đảm đủ chỗ ở Bước 2), vị trí đọc từ brand.yaml. KHÔNG còn scrim
     (nền phẳng 1 màu, không có gì để đè).
     ASSERT bbox logo nằm TRỌN trong TOP_PAD.
  6. LOG JSON (`build_stamp_log`) -- trả kèm bytes để ai_full.py ghi cạnh ảnh,
     Lead kiểm không cần mở ảnh (xem A2 Bước 6, STOP-REPORT) -- gồm cả
     scale_factor/top_pad_px/side_pad_px để CHẤM BẰNG SỐ, không dựa mắt (mắt
     không bắt được lỗi crop nếu band vẫn trông sạch, xem STOP-REPORT).

LOGO THẬT THAY WORDMARK CHỮ (2026-07-22, theo yêu cầu Lead): dán ẢNH logo thật
(`assets/icon_transparent.png`) thay vì vẽ chữ "FVA CAPITAL" bằng font -- xem
lịch sử hội thoại 2026-07-22. File gốc `icon.png`/`logo.png` GIỮ NGUYÊN không
sửa -- chỉ thêm bản `*_transparent.png` cạnh.
"""
from __future__ import annotations

import io
import logging
import re
import statistics
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageStat

from ..config import load_brand

logger = logging.getLogger("twmkt.render.brand_stamp")

# 2026-07-23 (Phần A1) -- kích thước khung CUỐI mặc định (dùng khi không có
# `settings`, vd test/gọi trực tiếp) -- ĐỌC ĐƯỢC qua config infographic.
# ai_full.final_size, đây CHỈ là fallback nội bộ, KHÔNG hardcode ở call site.
_DEFAULT_FINAL_SIZES: dict[str, tuple[int, int]] = {
    "4:5": (1080, 1350),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
}
_DEFAULT_FULL_CANVAS_AI_SIZES: dict[str, tuple[int, int]] = {
    "4:5": (1280, 1600),
    "9:16": (1152, 2048),
    "1:1": (1280, 1280),
}
_DEFAULT_BOTTOM_BAND_MIN_PX = 72

# Font size tối thiểu tuyệt đối -- DƯỚI mức này dấu tiếng Việt (dấu mũ/móc/
# thanh điệu chồng) bắt đầu vỡ nét ở ảnh raster thường (DỪNG KHI #2, xem
# NHIỆM VỤ 2026-07-22) -- co font KHÔNG được vượt qua ngưỡng này; nếu khối
# chữ vẫn không vừa dải an toàn ở size này, band TỰ NỚI CAO (2026-07-23,
# THAY "báo lỗi rõ ràng" cũ -- kiến trúc mới không còn khái niệm "dải cố định
# không đủ chỗ", band co giãn theo nhu cầu chữ).
_MIN_READABLE_FONT_SIZE = 18

_REPO_ROOT = Path(__file__).resolve().parents[3]
_THEME_TOKEN_ROW_RE = re.compile(
    r"^\|\s*`(?P<token>[a-z_.]+)`\s*\|\s*`(?P<value>#[0-9A-Fa-f]{6})`\s*\|",
    re.MULTILINE,
)
_THEME_ID_RE = re.compile(r"^theme_id:\s*(?P<value>[^\r\n]+?)\s*$", re.MULTILINE)
_REQUIRED_THEME_TOKENS = {
    "background.primary",
    "background.secondary",
    "text.primary",
    "text.secondary",
    "accent.gold",
}


class ThemeConfigError(ValueError):
    """Cấu hình theme hoặc design token màu không hợp lệ."""


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = value.strip().lstrip("#")
    if len(text) != 6:
        raise ThemeConfigError(f"Mã màu theme không hợp lệ: {value!r}")
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError as exc:
        raise ThemeConfigError(f"Mã màu theme không hợp lệ: {value!r}") from exc


def resolve_theme_name(theme: str | None = None, *, content_type: str | None = None) -> str:
    """Chọn theme bằng config; không suy luận nội dung từ câu chữ."""
    cfg = load_brand().get("infographic_theme")
    if not isinstance(cfg, dict):
        raise ThemeConfigError("Thiếu brand.infographic_theme trong config/brand.yaml")
    files = cfg.get("files")
    if not isinstance(files, dict) or not files:
        raise ThemeConfigError("Thiếu brand.infographic_theme.files trong config/brand.yaml")

    requested = str(theme or "").strip().lower()
    if requested:
        if requested not in files:
            raise ThemeConfigError(
                f"Theme {requested!r} chưa cấu hình; chỉ hỗ trợ {sorted(files)}")
        return requested

    content_key = str(content_type or "").strip().lower()
    content_map = cfg.get("content_map")
    if content_key and isinstance(content_map, dict):
        mapped = str(content_map.get(content_key) or "").strip().lower()
        if mapped:
            if mapped not in files:
                raise ThemeConfigError(
                    f"Theme {mapped!r} của content_type={content_key!r} chưa có file")
            return mapped

    default = str(cfg.get("default") or "").strip().lower()
    if default not in files:
        raise ThemeConfigError(
            f"Theme mặc định {default!r} chưa có trong brand.infographic_theme.files")
    return default


def load_theme_palette(
    theme: str | None = None,
    *,
    content_type: str | None = None,
) -> tuple[str, str, dict[str, str]]:
    """Đọc DUY NHẤT bảng design token màu từ file theme đã cấu hình.

    Các phần layout D*/L*, typography và density trong markdown không được
    parse hay đưa vào renderer.
    """
    resolved = resolve_theme_name(theme, content_type=content_type)
    cfg = load_brand()["infographic_theme"]
    configured_path = Path(str(cfg["files"][resolved]))
    path = configured_path if configured_path.is_absolute() else _REPO_ROOT / configured_path
    if not path.is_file():
        raise ThemeConfigError(f"Không tìm thấy file theme {resolved!r}: {path}")

    text = path.read_text(encoding="utf-8")
    tokens = {m.group("token"): m.group("value").upper()
              for m in _THEME_TOKEN_ROW_RE.finditer(text)}
    missing = sorted(_REQUIRED_THEME_TOKENS - set(tokens))
    if missing:
        raise ThemeConfigError(
            f"Theme {resolved!r} thiếu design token màu bắt buộc: {missing}")
    theme_id_match = _THEME_ID_RE.search(text)
    if not theme_id_match:
        raise ThemeConfigError(f"Theme {resolved!r} thiếu theme_id trong front matter")
    theme_id = theme_id_match.group("value").strip().strip("\"'")
    return resolved, theme_id, tokens

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

# SỬA LỖI THẬT (2026-08-04, Lead: logo/icon cũ nhoè màu) -- 2 file cũ
# (icon_transparent.png/logo_transparent.png) ĐÃ BỊ XOÁ khỏi assets/, thay
# bằng brand-kit/icon mới (xem config/brand.yaml: brand.active_asset/brand.
# assets). `_default_logo_path()` giờ là HÀM (không phải hằng số module-level)
# -- đọc LẠI config mỗi lần gọi, giống mọi `_resolve_*` khác trong file này,
# để đổi active_asset trong brand.yaml có hiệu lực NGAY không cần khởi động
# lại tiến trình. Rơi về đường dẫn cứng NÀY chỉ khi config thiếu/hỏng (an
# toàn -- không raise giữa chừng 1 lượt render).
_LEGACY_DEFAULT_LOGO_PATH = Path(__file__).resolve().parents[3] / "assets" / "icon_transparent.png"


def _resolve_active_logo_asset() -> dict:
    """Đọc `brand.active_asset` + `brand.assets[active_asset]` từ brand.yaml
    (VIỆC brand-kit mới 2026-08-04) -- trả {"path": Path, "white_gold_path":
    Path|None, "width_ratio": float}. Thiếu/hỏng config -> lùi về
    _LEGACY_DEFAULT_LOGO_PATH + tỷ lệ cũ 0.148 (KHÔNG raise -- lớp trình bày,
    hỏng cosmetic không đáng chặn render). `white_gold_path` (TASK-017,
    2026-08-07) là biến thể trắng-vàng CÙNG asset family, dùng khi nền vùng
    dán logo đo được TỐI (xem `_select_logo_variant`) -- None nếu chưa cấu
    hình (lùi mượt về hành vi cũ: luôn navy-gold)."""
    b = load_brand()
    active = b.get("active_asset") or "standard_icon"
    asset = (b.get("assets") or {}).get(active) or {}
    raw_path = asset.get("path")
    raw_white_path = asset.get("white_gold_path")
    width_ratio = asset.get("width_ratio")
    repo_root = Path(__file__).resolve().parents[3]
    path = (repo_root / raw_path) if raw_path else _LEGACY_DEFAULT_LOGO_PATH
    white_path = (repo_root / raw_white_path) if raw_white_path else None
    return {
        "path": path,
        "white_gold_path": white_path,
        "width_ratio": float(width_ratio) if width_ratio is not None else 0.148,
    }


def _default_logo_path() -> Path:
    return _resolve_active_logo_asset()["path"]

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


def _resolve_stamp_style() -> dict[str, float]:
    """Đọc thông số thẩm mỹ brand stamp từ brand.yaml.

    Các giới hạn ở đây chỉ xác thực config; bốn guardrail cấu trúc
    (fit-inside, TOP_PAD, band riêng, scale <= 1) vẫn do code bên dưới giữ.
    """
    cfg = load_brand().get("infographic_stamp") or {}
    logo_cfg = cfg.get("logo") or {}
    footer_cfg = cfg.get("footer") or {}
    style = {
        "logo_left_ratio": float(logo_cfg.get("left_ratio", 0.04)),
        "logo_vertical_bias": float(logo_cfg.get("vertical_bias", 0.50)),
        "footer_text_scale": float(
            footer_cfg.get("text_scale", _SECONDARY_TEXT_SCALE)
        ),
    }
    if not 0.0 <= style["logo_left_ratio"] <= 0.20:
        raise ValueError("brand.infographic_stamp.logo.left_ratio phải nằm trong [0, 0.20]")
    if not 0.0 <= style["logo_vertical_bias"] <= 1.0:
        raise ValueError("brand.infographic_stamp.logo.vertical_bias phải nằm trong [0, 1]")
    if not 0.50 <= style["footer_text_scale"] <= 1.0:
        raise ValueError("brand.infographic_stamp.footer.text_scale phải nằm trong [0.50, 1.0]")
    return style


def _resolve_overlay_style() -> dict[str, float]:
    """Đọc hình học overlay full-canvas từ brand.yaml.

    SỬA LỖI THẬT (2026-08-04, Lead: brand-kit mới) — kích thước logo giờ NEO
    THEO BỀ RỘNG (`logo_width_ratio`, nguồn = brand.assets[active_asset].
    width_ratio, xem _resolve_active_logo_asset()) thay vì bề cao
    (`logo_height_ratio` cũ) — brand-kit MỚI có thêm dòng chữ tagline bên
    dưới biểu tượng (khung ảnh gốc RỘNG hơn, không còn vuông như icon cũ),
    neo theo cao sẽ làm bề rộng biến thiên khó kiểm soát tuỳ khung ảnh gốc.
    `infographic_overlay.logo.height_ratio` trong config VẪN đọc được (lùi
    mượt/tương thích ngược) nhưng KHÔNG còn dùng để tính kích thước — chỉ giữ
    lại nếu code cũ/tài liệu còn tham chiếu tên khoá này."""
    cfg = load_brand().get("infographic_overlay") or {}
    logo_cfg = cfg.get("logo") or {}
    metadata_cfg = cfg.get("metadata") or {}
    style = {
        "logo_right_ratio": float(logo_cfg.get("right_ratio", 0.035)),
        "logo_top_ratio": float(logo_cfg.get("top_ratio", 0.025)),
        "logo_width_ratio": _resolve_active_logo_asset()["width_ratio"],
        # TASK-017 Phase 1/2 -- xem ghi chú ngưỡng đầy đủ trong config/brand.yaml.
        "logo_text_dark_pixel_floor": float(logo_cfg.get("text_dark_pixel_floor", 0.08)),
        "logo_low_contrast_floor": float(logo_cfg.get("low_contrast_floor", 0.6)),
        "logo_half_scan_top_fraction": float(logo_cfg.get("half_scan_top_fraction", 0.30)),
        # TASK-019 -- xem ghi chú ngưỡng đầy đủ trong config/brand.yaml + docstring
        # `_measure_illustration_half`.
        "logo_half_scan_near_bg_tolerance": int(logo_cfg.get("half_scan_near_bg_tolerance", 30)),
        "logo_half_scan_near_bg_floor": float(logo_cfg.get("half_scan_near_bg_floor", 0.35)),
        "logo_half_scan_near_bg_ceiling": float(logo_cfg.get("half_scan_near_bg_ceiling", 0.65)),
        "logo_corner_near_bg_floor": float(logo_cfg.get("corner_near_bg_floor", 0.40)),
        "metadata_side_ratio": float(metadata_cfg.get("side_ratio", 0.035)),
        "metadata_bottom_ratio": float(metadata_cfg.get("bottom_ratio", 0.012)),
        "image_body_font_ratio": float(metadata_cfg.get("image_body_font_ratio", 0.028)),
        "metadata_font_scale": float(metadata_cfg.get("font_scale", 0.80)),
        "metadata_backdrop_opacity": float(metadata_cfg.get("backdrop_opacity", 185)),
    }
    for key in (
        "logo_right_ratio", "logo_top_ratio", "metadata_side_ratio",
        "metadata_bottom_ratio",
    ):
        if not 0.0 <= style[key] <= 0.20:
            raise ValueError(f"brand.infographic_overlay.{key} phải nằm trong [0, 0.20]")
    if not 0.02 <= style["logo_width_ratio"] <= 0.30:
        raise ValueError("brand.assets.<active_asset>.width_ratio phải nằm trong [0.02, 0.30]")
    if not 0.0 <= style["logo_text_dark_pixel_floor"] <= 1.0:
        raise ValueError(
            "brand.infographic_overlay.logo.text_dark_pixel_floor phải nằm trong [0, 1]"
        )
    if not 0.0 <= style["logo_low_contrast_floor"] <= 1.0:
        raise ValueError(
            "brand.infographic_overlay.logo.low_contrast_floor phải nằm trong [0, 1]"
        )
    if not 0.05 <= style["logo_half_scan_top_fraction"] <= 1.0:
        raise ValueError(
            "brand.infographic_overlay.logo.half_scan_top_fraction phải nằm trong [0.05, 1]"
        )
    if not 0 <= style["logo_half_scan_near_bg_tolerance"] <= 120:
        raise ValueError(
            "brand.infographic_overlay.logo.half_scan_near_bg_tolerance phải nằm trong [0, 120]"
        )
    if not 0.0 <= style["logo_half_scan_near_bg_floor"] <= 1.0:
        raise ValueError(
            "brand.infographic_overlay.logo.half_scan_near_bg_floor phải nằm trong [0, 1]"
        )
    if not 0.0 <= style["logo_half_scan_near_bg_ceiling"] <= 1.0:
        raise ValueError(
            "brand.infographic_overlay.logo.half_scan_near_bg_ceiling phải nằm trong [0, 1]"
        )
    if style["logo_half_scan_near_bg_floor"] >= style["logo_half_scan_near_bg_ceiling"]:
        raise ValueError(
            "brand.infographic_overlay.logo.half_scan_near_bg_floor phải nhỏ hơn "
            "half_scan_near_bg_ceiling"
        )
    if not 0.0 <= style["logo_corner_near_bg_floor"] <= 1.0:
        raise ValueError(
            "brand.infographic_overlay.logo.corner_near_bg_floor phải nằm trong [0, 1]"
        )
    if not 0.01 <= style["image_body_font_ratio"] <= 0.08:
        raise ValueError(
            "brand.infographic_overlay.metadata.image_body_font_ratio phải nằm trong [0.01, 0.08]"
        )
    if not 0.50 <= style["metadata_font_scale"] <= 1.0:
        raise ValueError("brand.infographic_overlay.metadata.font_scale phải nằm trong [0.50, 1.0]")
    if not 0 <= style["metadata_backdrop_opacity"] <= 255:
        raise ValueError(
            "brand.infographic_overlay.metadata.backdrop_opacity phải nằm trong [0, 255]"
        )
    return style


def _resolve_navy_fallback(
    *,
    theme: str,
    theme_background: tuple[int, int, int],
    settings=None,
) -> tuple[int, int, int]:
    # `navy_fallback` là override legacy chỉ đúng cho Dark. Light phải lấy
    # background.primary từ chính file theme, nếu không band sáng sẽ bất ngờ
    # chuyển thành navy.
    if theme == "dark" and settings is not None:
        hex_v = settings.get("infographic.ai_full.navy_fallback")
        if isinstance(hex_v, str) and hex_v.strip():
            h = hex_v.strip().lstrip("#")
            if len(h) == 6:
                try:
                    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
                except ValueError:
                    pass
    return theme_background


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
# Bước 2 -- MATTING (fit-inside ảnh AI vào vùng trong, KHÔNG BAO GIỜ crop)
# =====================================================================

# Neo 1 chiều khi chọn kích thước gọi API (`select_ai_size`) -- ngân sách độ
# phân giải CÙNG BẬC chi phí/thời gian đã đo trước đây (~1024-1536px, xem
# assets/README_AI_FULL.md) -- KHÔNG phóng to tuỳ tiện chỉ để khớp tỷ lệ đẹp
# hơn (khớp tỷ lệ hoàn hảo sẽ triệt tiêu TOP_PAD tự nhiên, đẩy hết gánh nặng
# co ảnh sang bước dành chỗ logo -- không sai, nhưng lãng phí không cần
# thiết, xem báo cáo Δratio thật).
_AI_SIZE_ANCHOR_PX = 1024


def select_ai_size(ratio: str, *, settings=None) -> tuple[tuple[int, int], str]:
    """SỬA LỖI ĐẶC TẢ (2026-07-24, Phần A 2a) -- chọn kích thước gọi API
    gpt-image-2 khớp SÁT NHẤT ratio_inner = FINAL_W/(FINAL_H-BAND_H danh
    nghĩa), thay bảng cố định cũ (`ai_full.RATIO_SIZES`) từng lệch xa tỷ lệ
    vùng trong thật (vd 4:5 dùng 1024x1280 tỷ lệ 0.8 trong khi ratio_inner
    thật ~0.865).

    XÁC MINH THẬT (2026-07-24, KHÔNG suy đoán từ comment cũ) -- gọi API thật
    2 lượt: (1) size KHÔNG chia hết 16 (vd "1023x1184") -> HTTP 400
    "Invalid size '...'. Width and height must both be divisible by 16."
    (lỗi CHỈ nói về chia hết 16, không phải danh sách enum); (2) size TUỲ Ý
    chia hết 16 KHÔNG khớp bất kỳ giá trị "chuẩn" nào (vd "1024x1184",
    "1024x1680", "1024x944") -> HTTP 200, ảnh trả về ĐÚNG size đã yêu cầu
    (xác nhận bằng PIL.Image.size). Kết luận: gpt-image-2 chấp nhận size TUỲ
    Ý miễn chia hết 16 -- KHÔNG phải enum cố định nhỏ như gpt-image-1. Do đó
    thuật toán dưới đây tìm kích thước khớp NHẤT trong không gian chia-hết-16
    (neo 1 chiều ở `_AI_SIZE_ANCHOR_PX`, tính chiều còn lại), không phải chọn
    giữa vài lựa chọn liệt kê sẵn.

    Trả ((w, h), lý_do_string) -- lý_do vào log JSON `ai_size_reason`
    (`stamp_brand`)."""
    final_w, final_h = _resolve_final_size(ratio, settings)
    band_min_px = _resolve_band_min_px(settings)
    nominal_band_h = max(round(final_h * 0.075), band_min_px)
    inner_h = final_h - nominal_band_h
    ratio_inner = final_w / inner_h

    w = _AI_SIZE_ANCHOR_PX
    h = max(round(w / ratio_inner / 16) * 16, 16)
    ratio_ai = w / h
    reason = (
        f"neo width={w}px, ratio_inner=FINAL_W/(FINAL_H-BAND_H)={final_w}/{inner_h}"
        f"={ratio_inner:.4f} -> height khớp gần nhất chia hết 16 = {h}px "
        f"(ratio_ai={ratio_ai:.4f}, delta={abs(ratio_ai - ratio_inner):.4f}) -- "
        f"xác nhận API thật (2026-07-24): gpt-image-2 chấp nhận size tuỳ ý chia hết 16."
    )
    return (w, h), reason


def select_full_canvas_ai_size(
    ratio: str,
    *,
    settings=None,
) -> tuple[tuple[int, int], str]:
    """Chọn size API đúng tỷ lệ full-canvas và lớn hơn khung xuất bản.

    Không trừ TOP_PAD/bottom band vì overlay mới nằm trực tiếp trên ảnh.
    """
    configured = (
        settings.get(f"infographic.ai_full.generation_size.{ratio}")
        if settings is not None
        else None
    )
    if isinstance(configured, (list, tuple)) and len(configured) == 2:
        size = (int(configured[0]), int(configured[1]))
    else:
        size = _DEFAULT_FULL_CANVAS_AI_SIZES.get(ratio)
    if size is None:
        raise ValueError(f"Không có generation_size full-canvas cho tỷ lệ {ratio!r}")
    width, height = size
    if width % 16 or height % 16:
        raise ValueError(
            f"generation_size {ratio}={width}x{height} phải chia hết cho 16"
        )
    final_w, final_h = _resolve_final_size(ratio, settings)
    if width < final_w or height < final_h:
        raise ValueError(
            f"generation_size {ratio}={width}x{height} nhỏ hơn final_size "
            f"{final_w}x{final_h}; hậu kỳ không được phóng to ảnh"
        )
    ratio_delta = abs(width / height - final_w / final_h)
    if ratio_delta > 0.002:
        raise ValueError(
            f"generation_size {ratio} lệch tỷ lệ final_size (delta={ratio_delta:.4f})"
        )
    return size, (
        f"full-canvas {width}x{height}, đúng tỷ lệ {ratio}, lớn hơn final "
        f"{final_w}x{final_h}; chỉ downscale, không crop/matting"
    )


def _logo_dimensions(logo_path: Path, *, final_w: int, final_h: int) -> tuple[int, int, int]:
    """Trả (logo_w, logo_h, pad) -- pad = lề 4% chiều rộng (>=16px), logo_h =
    6% chiều cao cuối (>=24px), logo_w suy từ tỷ lệ khung file logo thật.
    Tính TRƯỚC matting (2e cần logo_h+2*pad để trừ vào TOP_PAD ngay trong
    scale) -- file logo KHÔNG tồn tại vẫn trả logo_h/pad hợp lệ (TOP_PAD
    không được đổi kích thước bất ngờ chỉ vì thiếu file logo)."""
    logo_h = max(round(final_h * 0.06), 24)
    pad = max(int(final_w * 0.04), 16)
    logo_w = logo_h
    if logo_path.exists():
        try:
            with Image.open(logo_path) as logo_im:
                logo_w = max(round(logo_im.width * (logo_h / logo_im.height)), 1)
        except Exception:
            pass
    return logo_w, logo_h, pad


def _matte(im: Image.Image, *, target_w: int, target_h: int, min_top_pad: int) -> dict:
    """FIT-INSIDE (contain) -- SỬA LỖI ĐẶC TẢ thay "cover-fit + cắt cân giữa"
    cũ (ăn mất nội dung CẢ HAI ĐẦU khi tỷ lệ lệch -- xem module docstring,
    bằng chứng ảnh thật 6/6 tiêu đề cụt đỉnh + chip cụt đáy CÙNG LÚC). Ảnh AI
    luôn nằm TRỌN VẸN trong (target_w, target_h) -- scale_factor KHÔNG BAO
    GIỜ vượt 1.0 (không phóng to ảnh gốc, chỉ có thể thu nhỏ hoặc giữ
    nguyên). `min_top_pad` (logo_h + 2*pad) trừ THẲNG vào target_h trước khi
    tính scale -- TOP_PAD đủ chỗ logo BẰNG TOÁN HỌC (bảo đảm cấu trúc, không
    dựa vào bước "co thêm" tách biệt dễ quên). Phần dư DỌC dồn hết lên ĐỈNH,
    phần dư NGANG chia đều 2 bên (2d) -- lấp bằng màu band ở nơi gọi (2c).

    Raise ValueError nếu: (a) scale_factor > 1.0 (đang phóng to, BUG); (b)
    ảnh sau scale vượt vùng trong (đang crop, BUG); (c) phải thu nhỏ quá 15%
    so với fit tự nhiên (không tính riêng TOP_PAD) mới đủ chỗ logo -- DỪNG
    KHI #2, cấu hình BAND_H/kích thước khung lệch quá xa, cần Lead quyết,
    KHÔNG tự ý nới ngưỡng."""
    target_w, target_h = max(int(target_w), 1), max(int(target_h), 1)
    src_w, src_h = im.size
    reduced_h = max(target_h - min_top_pad, 1)

    natural_scale = min(1.0, target_w / src_w, target_h / src_h)
    scale = min(1.0, target_w / src_w, reduced_h / src_h)

    if scale > 1.0 + 1e-9:
        raise ValueError(
            f"brand_stamp: scale_factor={scale:.4f} > 1.0 -- BUG (xem A2 Bước 2f, "
            "không được phóng to ảnh AI gốc)"
        )

    new_w = max(round(src_w * scale), 1)
    new_h = max(round(src_h * scale), 1)
    if new_w > target_w or new_h > target_h:
        raise ValueError(
            f"brand_stamp: ảnh sau scale ({new_w}x{new_h}) vượt vùng trong "
            f"({target_w}x{target_h}) -- đang crop, ĐÂY LÀ BUG (xem A2 Bước 2f)"
        )

    if natural_scale > 0 and (1 - scale / natural_scale) > 0.15:
        raise ValueError(
            "DỪNG (Lead quyết, xem A2 Bước 2e DỪNG KHI #2): ảnh phải thu nhỏ quá 15% "
            f"so với vùng trong mới đủ TOP_PAD (shrink={100 * (1 - scale / natural_scale):.1f}%, "
            f"min_top_pad={min_top_pad}px, target={target_w}x{target_h}px, "
            f"nguồn={src_w}x{src_h}px) -- tỷ lệ lệch quá nhiều, cần xem lại BAND_H "
            "hoặc kích thước khung, KHÔNG tự ý nới ngưỡng 15%."
        )

    resized = im if (new_w, new_h) == (src_w, src_h) else im.resize((new_w, new_h), Image.LANCZOS)
    top_pad_px = target_h - new_h
    side_total = target_w - new_w

    return {
        "resized": resized, "new_w": new_w, "new_h": new_h,
        "top_pad_px": top_pad_px, "side_pad_px": side_total // 2, "left": side_total // 2,
        "scale_factor": scale,
    }


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
                lum_threshold: float = 140.0, sample_rows: int = 20,
                fallback_source: str = "fallback_navy") -> tuple[tuple[int, int, int], str]:
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
    return navy_fallback, fallback_source


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
    text_scale: float = _SECONDARY_TEXT_SCALE,
) -> dict:
    """Đo (KHÔNG vẽ) khối "Nguồn:" (trái) + disclaimer (phải) -- font =
    0.30*nominal_band_h*text_scale, tối đa 2 dòng/khối, KHÔNG
    BAO GIỜ dưới `_MIN_READABLE_FONT_SIZE`. Trả dict đủ để vẽ + `band_h` THẬT
    (>= nominal_band_h -- band TỰ NỚI nếu chữ cần nhiều chỗ hơn dải danh
    nghĩa, KHÔNG BAO GIỜ cắt chữ)."""
    base_size = max(
        int(nominal_band_h * 0.30 * text_scale),
        _MIN_READABLE_FONT_SIZE,
    )
    gap = max(int(band_w * 0.02), 8)
    usable_w = max(band_w - 2 * margin_x - gap, 20)
    # Nguồn đã được rút về tên trang nên cần ít chỗ hơn disclaimer pháp lý.
    # Chia 34/66 giúp disclaimer ngắn chuẩn nằm gọn hơn, nhưng tổng hai vùng
    # vẫn không thể giao nhau vì đều được đo trong cùng `usable_w`.
    source_max_w = max(round(usable_w * 0.34), 10)
    disclaimer_max_w = max(usable_w - source_max_w, 10)

    src_lines, src_font, src_line_h = _fit_block(
        source_text, base_size=base_size, max_width=source_max_w, draw=draw,
        bold=True, font_path=font_path, max_lines=2,
    )
    dis_lines, dis_font, dis_line_h = _fit_block(
        disclaimer_text, base_size=base_size, max_width=disclaimer_max_w, draw=draw,
        bold=False, font_path=font_path, max_lines=2,
    )
    src_h = _block_height(src_lines, src_line_h)
    dis_h = _block_height(dis_lines, dis_line_h)
    v_pad = max(int(nominal_band_h * 0.18), 8)
    needed_h = max(src_h, dis_h) + 2 * v_pad
    band_h = max(nominal_band_h, needed_h)

    return {
        "band_h": band_h, "margin_x": margin_x,
        "source_max_w": source_max_w, "disclaimer_max_w": disclaimer_max_w,
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
# Bước 5 -- LOGO (dán vào TOP_PAD -- nền phẳng 1 màu, KHÔNG còn scrim)
# =====================================================================

def _paste_logo(overlay: Image.Image, *, logo_path: Path, top_pad_px: int, pad: int,
                logo_w: int, logo_h: int, final_w: int,
                left_ratio: float = 0.04, vertical_bias: float = 0.50,
                neutral_tint: tuple[int, int, int] | None = None) -> bool:
    """SỬA LỖI ĐẶC TẢ (2026-07-24, Phần A SỬA 2) -- dán ẢNH logo thật vào
    TOP_PAD (dải màu band phẳng ở đỉnh, matting Bước 2 đã bảo đảm đủ chỗ:
    top_pad_px >= logo_h + 2*pad) THAY VÌ đè lên ảnh AI tràn viền mép trên
    (bản cũ). KHÔNG CÒN ẢNH AI NÀO BÊN DƯỚI ĐỂ ĐÈ -- scrim (bản cũ, chỉ vẽ
    khi luminance nền sáng >110) trở nên VÔ NGHĨA, XOÁ HẲN cơ chế (không còn
    field log `scrim_applied`).

    Vị trí đọc từ config qua `left_ratio`/`vertical_bias`. Với Light, phần
    bạc gần trắng có thể được nhuộm bằng `neutral_tint` lấy từ token màu
    theme. ASSERT bbox logo nằm TRỌN trong TOP_PAD -- raise ValueError nếu vi
    phạm (BUG cấu trúc, xem A2 SỬA 2). Trả True nếu đã dán (ghi vào log JSON
    `logo_in_pad`), False nếu không có/lỗi file logo (KHÔNG raise, giữ hành
    vi cũ: thiếu logo không được chặn cả pipeline)."""
    if not logo_path.exists():
        logger.warning("brand_stamp: không tìm thấy file logo '%s' -- bỏ qua, KHÔNG đóng dấu logo.", logo_path)
        return False
    try:
        logo = Image.open(logo_path).convert("RGBA")
    except Exception as e:
        logger.warning("brand_stamp: lỗi mở file logo '%s' (%s) -- bỏ qua, KHÔNG đóng dấu logo.", logo_path, e)
        return False

    logo_x = max(round(final_w * left_ratio), 16)
    available_y = max(top_pad_px - logo_h, 0)
    logo_y = min(max(round(available_y * vertical_bias), 0), available_y)

    if logo_y + logo_h > top_pad_px or logo_x + logo_w > final_w:
        raise ValueError(
            f"brand_stamp: bbox logo ({logo_x},{logo_y})-({logo_x + logo_w},{logo_y + logo_h}) "
            f"vượt TOP_PAD (0,0)-({final_w},{top_pad_px}) -- BUG cấu trúc (xem A2 SỬA 2 ASSERT)"
        )

    logo_resized = logo.resize((logo_w, logo_h), Image.LANCZOS)
    if neutral_tint is not None:
        # Logo gốc có phần bạc gần trắng: rõ trên Dark nhưng chìm trên Light.
        # Chỉ nhuộm pixel gần trung tính; phần Gold có chroma cao được giữ
        # nguyên. Màu nhuộm lấy từ theme text.primary, không hardcode.
        pixels = []
        for red, green, blue, alpha in logo_resized.getdata():
            chroma = max(red, green, blue) - min(red, green, blue)
            if alpha and chroma < 38:
                pixels.append((*neutral_tint, alpha))
            else:
                pixels.append((red, green, blue, alpha))
        logo_resized.putdata(pixels)
    overlay.alpha_composite(logo_resized, (logo_x, logo_y))
    return True


# =====================================================================
# TASK-013 Phần B (2026-08-07, ADR-002) -- chọn góc logo CÓ CẤU TRÚC.
# TASK-017 (2026-08-07, quy định MỚI chủ dự án) -- ĐẢO HƯỚNG tiếp: chủ dự án
# BÁC bản TASK-013 (chưa merge) vì nó BỎ HẲN logo khi cả 2 góc "va chạm" --
# bằng chứng thật (Phase D ảnh BSR): top-right chỉ là MÂY TRỜI (dark_pixel_
# ratio=0.0) nhưng vẫn bị `scan["detected"]=True` vì hoạ tiết mây tạo nhiều
# cạnh tương phản giống chữ (`aligned_component_count=8`). Quy định mới: (1)
# logo LUÔN phải có, không được bỏ; (2) LUÔN đóng ở NỬA chứa ảnh minh hoạ,
# không còn thử cả 2 nửa như TASK-013; (3) đè lên hoạ tiết ảnh minh hoạ CHẤP
# NHẬN ĐƯỢC; (4) TUYỆT ĐỐI không đè phần chữ.
#
# Hai thay đổi cụ thể so với TASK-013:
#   a) `_measure_illustration_half()` đo dark_pixel_ratio nửa TRÁI/PHẢI để
#      XÁC NHẬN nửa nào là ảnh minh hoạ (không tin mù bố cục cứng trong
#      prompt) -- `_corners_for_half()` chỉ trả về ứng viên trong ĐÚNG nửa đó.
#   b) Quyết định "occupied" không còn dùng `scan["detected"]` (báo dương giả
#      trên hoạ tiết ảnh, xem trên) mà dùng ngưỡng `dark_pixel_ratio` đo trên
#      ĐÚNG bbox logo (config `infographic_overlay.logo.text_dark_pixel_floor`,
#      xem brand.yaml + docstring `select_logo_corner` cho lịch sử hiệu
#      chỉnh lại 2 lần sau khi Phase 3 bắt được 2 ca đè chữ thật bị lọt).
#
# Không còn ứng viên sạch trong nửa ảnh minh hoạ -> `chosen=None` ->
# `overlay_brand_full_canvas` RAISE (KHÔNG âm thầm bỏ logo) -- caller
# (`ai_full.render_ai_full`) sinh lại ảnh / NEEDS_HUMAN, xem contract TASK-017.
#
# TASK-019 (2026-08-08, chủ dự án chỉ ra trực tiếp) -- SỬA bước (a): chủ dự
# án BÁC luôn giả định ngầm "ưu tiên góc trên-phải" mà TASK-013/017 dựa vào
# (prompt không ép được bố cục ổn định -- bằng chứng: 2/8 ảnh bố cục ngược,
# ảnh minh hoạ ở TRÁI). `_measure_illustration_half()` dùng CHỈ dark_pixel_
# ratio hoá ra đo SAI nửa trên đúng 2 ảnh đó (ảnh chụp tối màu tự nhiên tối
# hơn khối tiêu đề) -- thêm tín hiệu `near_background_ratio` (tỷ lệ pixel gần
# màu nền theme) làm quyết định chính, dark_pixel_ratio lùi thành dự phòng.
# Xem docstring `_measure_illustration_half` cho chi tiết đầy đủ + số đo.
# =====================================================================


def _near_background_ratio(
    region: Image.Image, background: tuple[int, int, int], *, tolerance: int
) -> float:
    """Tỷ lệ pixel LỆCH mỗi kênh RGB <= `tolerance` so với màu nền theme
    (`background.primary`) -- đo TRỰC TIẾP "vùng trống" (nền phẳng/khoảng
    trắng quanh chữ) thay vì suy qua độ tối (xem `_measure_illustration_half`
    cho lý do dark_pixel_ratio một mình không đủ tin cậy, TASK-019)."""
    rgb = region.convert("RGB")
    pixels = list(rgb.getdata())
    if not pixels:
        return 0.0
    close = sum(
        1
        for r, g, b in pixels
        if abs(r - background[0]) <= tolerance
        and abs(g - background[1]) <= tolerance
        and abs(b - background[2]) <= tolerance
    )
    return close / len(pixels)


def _measure_illustration_half(
    canvas: Image.Image,
    *,
    final_w: int,
    final_h: int,
    background: tuple[int, int, int],
    top_fraction: float = 0.10,
    near_bg_tolerance: int = 30,
    near_bg_floor: float = 0.35,
    near_bg_ceiling: float = 0.65,
) -> dict:
    """Đo nửa TRÁI/PHẢI ảnh chứa khối tiêu đề (chữ) vs. ảnh minh hoạ -- không
    tin bố cục cứng "tiêu đề trái/minh hoạ phải" ép trong prompt (TASK-013
    Phần A); prompt là xác định, đo là tất định (yêu cầu chủ dự án TASK-017).

    SỬA LỖI THẬT (2026-08-08, TASK-019, chủ dự án chỉ ra trực tiếp) -- bản
    TASK-017 chỉ dùng `dark_pixel_ratio` (nửa nào tối hơn = có chữ) SAI trên
    2/8 ảnh thật khi ảnh minh hoạ ở bên TRÁI (`091d9428...` Bách Hóa Xanh mở
    rộng miền Bắc, `bb8f9ddf...` BHX x WinCommerce): cả hai đều là ẢNH CHỤP
    TỐI MÀU (kệ hàng/màn hình) darker hơn hẳn khối tiêu đề (chữ navy thưa
    trên nền ivory gần trắng) -- dark_pixel_ratio khi đó cho kết luận NGƯỢC
    (nửa ảnh minh hoạ bị đo là nửa "có chữ"). Xác nhận bằng mắt trên ảnh thật
    (không chỉ qua số đo) -- xem `_tmp-task019/analyze_half*.py` (ngoài repo).

    TÍN HIỆU MỚI, ƯU TIÊN: `_near_background_ratio` -- tỷ lệ pixel gần màu
    NỀN THEME (`background.primary`, KHÔNG hardcode trắng -- theme Dark nền
    navy, near-white sẽ vô nghĩa). Khối tiêu đề luôn có nhiều khoảng trống
    nền thật quanh chữ (near_bg cao); ảnh chụp phủ kín khung nên near_bg thấp,
    BẤT KỂ ảnh sáng hay tối -- tín hiệu này sống sót qua đúng trường hợp làm
    dark_pixel_ratio sai (ảnh tối). Đối chiếu trên đúng bộ 8 ảnh thật (TASK-013
    Phase D + TASK-017 Phase 3): near_bg 2 nửa lệch xa nhau (>=30 điểm % qua
    ngưỡng floor/ceiling) trên 4/8 ảnh có bố cục 2 cột rõ (kể cả đúng 2 ảnh
    lỗi ở trên) -- dùng làm quyết định TRỰC TIẾP khi lệch xa. 4/8 ảnh còn lại
    (bố cục ảnh phủ toàn chiều rộng, không chia 2 cột rõ) near_bg 2 nửa GẦN
    NHAU -- không đủ tin cậy để quyết -- LÙI VỀ `dark_pixel_ratio` cũ (đã đúng
    trên cả 4 ca này, xem TASK-017) làm tín hiệu dự phòng, KHÔNG thay hẳn.
    Kết hợp 2 tín hiệu độc lập thay vì tin một chỉ số duy nhất (bài học
    TASK-017: `aligned_component_count` từng bị glyph-merging đánh lừa).

    CHỈ đo dải TRÊN CÙNG (`top_fraction` * final_h, mặc định 10%, xem config
    `infographic_overlay.logo.half_scan_top_fraction`) -- KHÔNG đo cả chiều
    cao ảnh. Bằng chứng thật (ảnh POM, TASK-017 Phase 3): đo cả ảnh khiến
    khối thẻ số liệu ở NỬA DƯỚI (không liên quan gì tới góc đặt logo, vốn chỉ
    ở dải trên) áp đảo phép đo, xác định SAI nửa chứa tiêu đề."""
    from .postflight import scan_text_collision

    half_w = max(final_w // 2, 1)
    band_h = max(round(final_h * top_fraction), 1)
    left_bbox = (0, 0, half_w, band_h)
    right_bbox = (half_w, 0, final_w, band_h)

    left_near_bg = _near_background_ratio(
        canvas.crop(left_bbox), background, tolerance=near_bg_tolerance
    )
    right_near_bg = _near_background_ratio(
        canvas.crop(right_bbox), background, tolerance=near_bg_tolerance
    )

    left_scan = scan_text_collision(canvas, left_bbox)
    right_scan = scan_text_collision(canvas, right_bbox)
    left_ratio = left_scan.get("dark_pixel_ratio", 0.0)
    right_ratio = right_scan.get("dark_pixel_ratio", 0.0)

    if left_near_bg <= near_bg_floor and right_near_bg >= near_bg_ceiling:
        image_half, decision_method = "left", "near_background_ratio"
    elif right_near_bg <= near_bg_floor and left_near_bg >= near_bg_ceiling:
        image_half, decision_method = "right", "near_background_ratio"
    else:
        text_half = "left" if left_ratio >= right_ratio else "right"
        image_half = "right" if text_half == "left" else "left"
        decision_method = "dark_pixel_ratio_fallback"
    text_half = "right" if image_half == "left" else "left"
    return {
        "text_half": text_half,
        "image_half": image_half,
        "left_dark_pixel_ratio": left_ratio,
        "right_dark_pixel_ratio": right_ratio,
        "left_near_background_ratio": round(left_near_bg, 4),
        "right_near_background_ratio": round(right_near_bg, 4),
        "decision_method": decision_method,
        "scan_band_h": band_h,
    }


def _corners_for_half(image_half: str) -> tuple[str, ...]:
    """Ứng viên góc CHỈ trong nửa chứa ảnh minh hoạ (TASK-017 quy định 2:
    "LUÔN đóng logo ở PHÍA CÓ ẢNH MINH HOẠ") -- ưu tiên góc TRÊN (yêu cầu trực
    tiếp chủ dự án). Mở rộng thêm ứng viên (vd góc dưới cùng nửa) sau này chỉ
    cần thêm tên vào tuple + 1 nhánh toạ độ trong `_logo_corner_xy`."""
    if image_half == "right":
        return ("top_right",)
    if image_half == "left":
        return ("top_left",)
    raise ValueError(f"brand_stamp: image_half không hợp lệ: {image_half!r}")


def _logo_corner_xy(
    corner: str, *, logo_margin: int, logo_w: int, logo_y: int, final_w: int
) -> tuple[int, int]:
    if corner == "top_right":
        return final_w - logo_margin - logo_w, logo_y
    if corner == "top_left":
        return logo_margin, logo_y
    raise ValueError(f"brand_stamp: logo corner candidate không hỗ trợ: {corner!r}")


def select_logo_corner(
    content_canvas: Image.Image,
    *,
    logo_w: int,
    logo_h: int,
    logo_margin: int,
    logo_y: int,
    final_w: int,
    final_h: int,
    corners: tuple[str, ...],
    dark_pixel_floor: float,
    background: tuple[int, int, int] | None = None,
    near_bg_tolerance: int = 30,
    corner_near_bg_floor: float = 0.40,
) -> dict:
    """Quét từng ứng viên góc (đúng thứ tự ưu tiên, đã giới hạn về ĐÚNG nửa
    chứa ảnh minh hoạ bởi caller qua `_corners_for_half`) và trả kết quả CÓ
    CẤU TRÚC: `{"chosen": <corner|None>, "all_occupied": bool, "candidates":
    [{"corner", "x", "y", "bbox", "occupied", "dark_pixel_ratio", ...}, ...]}`.

    SỬA LỖI THẬT #1 (TASK-017 Phase 3, ảnh Bách Hóa Xanh mở rộng miền Bắc)
    -- quét ĐÚNG bbox logo (KHÔNG mở rộng 20% như bản đầu): bản mở rộng cộng
    thêm khoảng đệm RỖNG phía trên logo vào phép tính trung bình, PHA LOÃNG
    tín hiệu chữ thật ở phần DƯỚI bbox trong khi logo thật sự đè lên nửa
    dưới chữ "Xanh" (nhìn thấy khi mở ảnh) -- xem `_full_canvas_logo_geometry`.

    SỬA LỖI THẬT #2 (TASK-017 Phase 3, ảnh Bách Hóa Xanh × WinCommerce) --
    ĐÃ THỬ kết hợp thêm tín hiệu cấu trúc (aligned_component_count, đếm cụm
    nét cùng hàng/cỡ giống glyph) để tách "chữ thật" khỏi "hoạ tiết/biểu đồ
    dày đặc" cùng mức dark_pixel_ratio -- BỎ vì không bền: chữ đậm/kerning
    sát nhau bị dilation (`MaxFilter` trong `_contrast_mask`) NỐI LIỀN các
    glyph thành 1 khối lớn, bị chính bộ lọc bề rộng (loại component rộng hơn
    70% bbox, coi là "không phải glyph đơn lẻ") loại khỏi component_count --
    bằng chứng thật: chữ "XANH" bị logo đè rõ ràng nhưng component_count đo
    được = 0. "occupied" (TASK-017, thay `scan["detected"]` cũ -- báo dương
    giả trên hoạ tiết ảnh chụp như mây/kim loại) giờ CHỈ dùng MỘT ngưỡng
    dark_pixel_ratio, hiệu chỉnh lại trên 16 mẫu góc thật (8 ảnh x 2 góc,
    TASK-013 Phase D + TASK-017 Phase 3) SAU KHI sửa #1: mọi góc chỉ có hoạ
    tiết ảnh (mây, kim loại, biểu đồ) đo được <= 0.038; mọi góc CÓ CHỮ THẬT
    (kể cả chỉ đè MỘT PHẦN bbox) đo được >= 0.125 -- đặt giữa khoảng hở đó
    (xem config `infographic_overlay.logo.text_dark_pixel_floor`).

    SỬA LỖI THẬT #3 (2026-08-08, TASK-019) -- ngưỡng dark_pixel_ratio ĐƠN ở
    trên chỉ hiệu chỉnh trên góc ẢNH SÁNG MÀU (mây, kim loại, biểu đồ nền
    sáng) -- CHƯA từng gặp góc rơi vào ẢNH MINH HOẠ TỐI MÀU tự nhiên (đèn
    trần/kệ hàng, màn hình giao dịch tối) cho tới khi sửa Phase 1
    (`_measure_illustration_half`) chọn ĐÚNG nửa ảnh minh hoạ ở 2 ảnh trước
    đây luôn bị đo sai nửa. Ảnh thật (091d9428... Bách Hóa Xanh mở rộng miền
    Bắc, góc trên-trái = đèn trần) đo được dark_pixel_ratio=0.48 (gấp ~4 lần
    ngưỡng 0.125 dù KHÔNG có chữ thật -- xác nhận bằng mắt) -- dark_pixel_ratio
    một mình KHÔNG phân biệt được "tối vì có mực chữ" với "tối vì bản thân
    ảnh chụp tối màu".

    Tín hiệu bổ sung: `near_background_ratio` (CÙNG hàm `_near_background_ratio`
    dùng ở `_measure_illustration_half`) đo trên ĐÚNG bbox logo. Chữ tiêu đề do
    pipeline SINH RA luôn nằm trên nền theme PHẲNG (ivory/navy), nên bbox
    quanh nó LUÔN còn nhiều khoảng nền lộ ra quanh/giữa các glyph -- đo trên
    16 mẫu góc thật (8 ảnh x 2 góc, TASK-013 Phase D + TASK-017 Phase 3 +
    2 góc mới lộ ra sau khi sửa Phase 1): mọi góc CÓ CHỮ TIÊU ĐỀ THẬT đo
    near_background_ratio >= 0.73; mọi góc chỉ có ảnh minh hoạ (dù là hoạ
    tiết thuần hay có chi tiết/chữ NHỎ tình cờ xuất hiện trong ảnh chụp, vd
    số liệu mờ trên màn hình giao dịch nền ảnh -- KHÔNG phải chữ do pipeline
    tạo ra) đo được <= 0.13 -- đặt ngưỡng 0.40 giữa khoảng hở đó
    (`infographic_overlay.logo.corner_near_bg_floor`). "occupied" giờ đòi
    hỏi CẢ HAI tín hiệu cùng vượt ngưỡng (kết hợp, không tin một chỉ số duy
    nhất) -- ĐÂY LÀ ĐK CHẶT HƠN bản cũ (chỉ SIẾT thêm điều kiện, không bỏ
    điều kiện cũ) nên KHÔNG thể biến 1 góc cũ đã "occupied" đúng (dark cao +
    near_bg cao, chữ tiêu đề thật) thành "sạch" sai -- chỉ gỡ oan cho góc ảnh
    minh hoạ tối màu (dark cao nhưng near_bg thấp, không có nền theme lộ ra).
    Thiếu `background` (caller cũ không truyền) -> lùi mượt về dark_pixel_ratio
    một mình (hành vi TASK-017), KHÔNG raise.

    `chosen=None` khi KHÔNG ứng viên nào sạch -- caller quyết định (sinh lại
    ảnh), hàm này KHÔNG BAO GIỜ tự dán đè lên chữ."""
    from .postflight import scan_text_collision

    candidates: list[dict] = []
    chosen: str | None = None
    for corner in corners:
        x, y = _logo_corner_xy(
            corner, logo_margin=logo_margin, logo_w=logo_w, logo_y=logo_y, final_w=final_w
        )
        bbox = (x, y, x + logo_w, y + logo_h)
        scan = scan_text_collision(content_canvas, bbox)
        dark_hit = scan.get("dark_pixel_ratio", 0.0) >= dark_pixel_floor
        near_bg_ratio = None
        if background is not None:
            near_bg_ratio = _near_background_ratio(
                content_canvas.crop(bbox), background, tolerance=near_bg_tolerance
            )
            occupied = dark_hit and near_bg_ratio >= corner_near_bg_floor
        else:
            occupied = dark_hit
        candidates.append(
            {
                "corner": corner, "x": x, "y": y, "bbox": list(bbox), "occupied": occupied,
                "near_background_ratio": near_bg_ratio, **scan,
            }
        )
        if chosen is None and not occupied:
            chosen = corner
    return {"chosen": chosen, "all_occupied": chosen is None, "candidates": candidates}


def _full_canvas_logo_geometry(
    logo: Image.Image, *, final_w: int, final_h: int, style: dict
) -> tuple[int, int, int, int]:
    """logo_w, logo_h, logo_margin, logo_y dùng chung giữa `overlay_brand_full_canvas`
    và `precheck_logo_corner` -- MỘT nguồn hình học, tránh lệch nhau khi sửa."""
    logo_w = max(round(final_w * style["logo_width_ratio"]), 24)
    logo_h = max(round(logo.height * logo_w / max(logo.width, 1)), 1)
    logo_margin = max(round(final_w * style["logo_right_ratio"]), 16)
    logo_y = max(round(final_h * style["logo_top_ratio"]), 12)
    return logo_w, logo_h, logo_margin, logo_y


def precheck_logo_corner(
    png_bytes: bytes,
    *,
    ratio: str,
    theme: str | None = None,
    settings=None,
    logo_path: str | Path | None = None,
) -> dict:
    """TASK-013 Phần C: quét ảnh AI THÔ (chưa đóng dấu brand) để biết TRƯỚC
    có góc trống cho logo hay không -- dùng ở `ai_full.render_ai_full` để
    quyết định sinh lại ảnh (giống khuôn retry ranking đã có,
    `detect_ordinal_markers` ở `ai_full.py`) TRƯỚC KHI tốn công đóng dấu.
    Dùng ĐÚNG hình học `overlay_brand_full_canvas` sẽ dùng cho lượt đóng dấu
    thật (qua `_full_canvas_logo_geometry` + `select_logo_corner` dùng
    chung) -- không có rủi ro lệch kết quả giữa 2 lượt quét.

    TASK-017 (2026-08-07): giờ CŨNG đo nửa chứa ảnh minh hoạ trước
    (`_measure_illustration_half`) và chỉ quét ứng viên trong ĐÚNG nửa đó
    (`_corners_for_half`) -- trả thêm `image_half`/`half_measurement` để
    caller/log đối chiếu được. `chosen=None` ở mọi nhánh sớm (thiếu file/vượt
    biên) giờ đi kèm `all_occupied=True` (trước đây `False`, KHÔNG NHẤT QUÁN
    với `chosen is None` -- sửa luôn, bug có sẵn không liên quan trực tiếp
    logic va chạm chữ).

    TASK-019 (2026-08-08): `_measure_illustration_half` giờ cần màu nền theme
    (`background.primary`) để đo `near_background_ratio` -- nhận thêm `theme`
    (CÙNG theme caller đã chốt cho lượt sinh ảnh này, xem `ai_full.
    render_ai_full`; KHÔNG tự suy theme mặc định riêng ở đây vì có thể LỆCH
    với theme thật sẽ dùng để đóng dấu, làm sai màu nền tham chiếu)."""
    style = _resolve_overlay_style()
    final_w, final_h = _resolve_final_size(ratio, settings)
    _resolved_theme, _theme_id, palette = load_theme_palette(theme)
    background = _hex_to_rgb(palette["background.primary"])
    source_image = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    content_canvas = source_image.resize((final_w, final_h), Image.LANCZOS).convert("RGBA")
    resolved_logo_path = Path(logo_path) if logo_path else _default_logo_path()
    if not resolved_logo_path.is_file():
        return {"chosen": None, "all_occupied": True, "candidates": [], "image_half": None}
    logo = Image.open(resolved_logo_path).convert("RGBA")
    logo_w, logo_h, logo_margin, logo_y = _full_canvas_logo_geometry(
        logo, final_w=final_w, final_h=final_h, style=style
    )
    if logo_margin + logo_w > final_w or logo_y + logo_h > final_h:
        return {"chosen": None, "all_occupied": True, "candidates": [], "image_half": None}
    half = _measure_illustration_half(
        content_canvas, final_w=final_w, final_h=final_h, background=background,
        top_fraction=style["logo_half_scan_top_fraction"],
        near_bg_tolerance=style["logo_half_scan_near_bg_tolerance"],
        near_bg_floor=style["logo_half_scan_near_bg_floor"],
        near_bg_ceiling=style["logo_half_scan_near_bg_ceiling"],
    )
    result = select_logo_corner(
        content_canvas,
        logo_w=logo_w,
        logo_h=logo_h,
        logo_margin=logo_margin,
        logo_y=logo_y,
        final_w=final_w,
        final_h=final_h,
        corners=_corners_for_half(half["image_half"]),
        dark_pixel_floor=style["logo_text_dark_pixel_floor"],
        background=background,
        near_bg_tolerance=style["logo_half_scan_near_bg_tolerance"],
        corner_near_bg_floor=style["logo_corner_near_bg_floor"],
    )
    result["image_half"] = half["image_half"]
    result["half_measurement"] = half
    return result


def _select_logo_variant(
    canvas: Image.Image,
    bbox: tuple[int, int, int, int],
    *,
    navy_path: Path,
    white_path: Path | None,
    low_contrast_floor: float,
) -> dict:
    """TASK-017 Phase 2 -- chọn biến thể logo (navy-gold/white-gold) theo ĐỘ
    TƯƠNG PHẢN ĐỌC ĐƯỢC tại ĐÚNG vùng bbox sẽ dán logo (không phải cả ảnh).
    Dùng lại `dark_pixel_ratio` đã có sẵn trong `scan_text_collision` (KHÔNG
    viết bộ đo mới, xem contract) làm điểm tương phản của mỗi biến thể: nền
    càng TỐI thì mực TRẮNG (white-gold) càng dễ đọc (điểm = dark_pixel_ratio),
    nền càng SÁNG thì mực TỐI (navy-gold) càng dễ đọc (điểm = 1 -
    dark_pixel_ratio). Không cấu hình file white-gold -> luôn navy (hành vi
    cũ, lùi mượt). Cả 2 điểm đều dưới `low_contrast_floor` -- yêu cầu chủ dự
    án (2026-08-07): VẪN chọn biến thể điểm cao hơn (không được bỏ logo),
    chỉ ghi log rõ để xem lại tài sản logo nếu lặp lại nhiều."""
    from .postflight import scan_text_collision

    scan = scan_text_collision(canvas, bbox)
    bg_dark_pixel_ratio = scan.get("dark_pixel_ratio", 0.0)
    if white_path is None or not Path(white_path).is_file():
        return {
            "path": navy_path,
            "variant": "navy_gold",
            "bg_dark_pixel_ratio": bg_dark_pixel_ratio,
            "navy_contrast_score": round(1.0 - bg_dark_pixel_ratio, 4),
            "white_contrast_score": None,
            "both_variants_low_contrast": False,
            "reason": "white_gold_asset_not_configured",
        }
    navy_score = 1.0 - bg_dark_pixel_ratio
    white_score = bg_dark_pixel_ratio
    if white_score > navy_score:
        path, variant, winning_score = white_path, "white_gold", white_score
    else:
        path, variant, winning_score = navy_path, "navy_gold", navy_score
    both_poor = winning_score < low_contrast_floor
    return {
        "path": path,
        "variant": variant,
        "bg_dark_pixel_ratio": bg_dark_pixel_ratio,
        "navy_contrast_score": round(navy_score, 4),
        "white_contrast_score": round(white_score, 4),
        "both_variants_low_contrast": both_poor,
        "reason": (
            "both_variants_low_contrast_picked_higher" if both_poor
            else ("dark_background" if variant == "white_gold" else "light_background")
        ),
    }


def overlay_brand_full_canvas(
    png_bytes: bytes,
    *,
    ratio: str,
    theme: str | None = None,
    source: str = "",
    disclaimer: str = "",
    logo_path: str | Path | None = None,
    font_path: str | None = None,
    settings=None,
) -> tuple[bytes, dict]:
    """Overlay brand trực tiếp lên ảnh GPT full-canvas.

    Không crop, matting, padding hoặc tạo khung con. Đây là implementation
    Pillow của lớp trình bày tất định mà HTML/webapp sẽ sở hữu sau này.
    """
    theme, theme_id, palette = load_theme_palette(theme)
    style = _resolve_overlay_style()
    colors = {
        "background": _hex_to_rgb(palette["background.primary"]),
        "primary": _hex_to_rgb(palette["text.primary"]),
        "secondary": _hex_to_rgb(palette["text.secondary"]),
        "gold": _hex_to_rgb(palette["accent.gold"]),
    }
    source_image = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    source_w, source_h = source_image.size
    final_w, final_h = _resolve_final_size(ratio, settings)
    ratio_delta = abs(source_w / source_h - final_w / final_h)
    # Fixture 1x1 của test cũ không đại diện response API. Ảnh thật phải đúng
    # tỷ lệ để resize không làm biến dạng nội dung.
    if min(source_w, source_h) > 64 and ratio_delta > 0.01:
        raise ValueError(
            f"Ảnh GPT {source_w}x{source_h} lệch tỷ lệ {ratio} "
            f"(delta={ratio_delta:.4f}); không crop hoặc ép méo để cứu."
        )
    from .postflight import scan_text_collision

    content_canvas = source_image.resize((final_w, final_h), Image.LANCZOS).convert("RGBA")

    body_font_px = max(round(final_w * style["image_body_font_ratio"]), 1)
    metadata_font_px = max(
        round(body_font_px * style["metadata_font_scale"]),
        _MIN_READABLE_FONT_SIZE,
    )
    source_font = _find_font(metadata_font_px, bold=True, extra_path=font_path)
    disclaimer_font = _find_font(metadata_font_px, bold=False, extra_path=font_path)
    source_short = _shorten_source(source)
    source_text = f"Nguồn: {source_short}" if source_short else ""
    side = max(round(final_w * style["metadata_side_ratio"]), 12)
    bottom = max(round(final_h * style["metadata_bottom_ratio"]), 8)
    gap = max(round(final_w * 0.025), 16)
    measure = ImageDraw.Draw(content_canvas)
    source_w_px = round(measure.textlength(source_text, font=source_font)) if source_text else 0
    disclaimer_w_px = (
        round(measure.textlength(disclaimer, font=disclaimer_font)) if disclaimer else 0
    )
    if source_w_px + disclaimer_w_px + gap > final_w - 2 * side:
        raise ValueError(
            "Nguồn + disclaimer không vừa một dòng ở metadata_font_scale="
            f"{style['metadata_font_scale']:.2f}; không tự thu nhỏ dưới tỷ lệ user chốt."
        )
    probe = source_text or disclaimer or "Ag"
    probe_font = source_font if source_text else disclaimer_font
    text_bbox = measure.textbbox((0, 0), probe, font=probe_font)
    line_h = max(text_bbox[3] - text_bbox[1], metadata_font_px)
    v_pad = max(round(line_h * 0.45), 7)
    proposed_line_bottom = final_h - bottom
    proposed_text_y = proposed_line_bottom - line_h - text_bbox[1]
    proposed_backdrop_top = max(proposed_text_y - v_pad, 0)
    metadata_scan_bbox = (0, proposed_backdrop_top, final_w, final_h)
    metadata_scan = scan_text_collision(content_canvas, metadata_scan_bbox)
    metadata_extended = bool(metadata_scan["detected"])
    metadata_extension_px = 0
    output_h = final_h
    if metadata_extended:
        metadata_extension_px = max(
            final_h - proposed_backdrop_top,
            line_h + 2 * v_pad + bottom,
        )
        output_h = final_h + metadata_extension_px
    try:
        canvas = Image.new("RGBA", (final_w, output_h), (*colors["background"], 255))
    except (MemoryError, OSError) as exc:
        raise ValueError(
            "METADATA_GUARDRAIL_FAIL: phát hiện chữ trong band đáy nhưng không "
            f"nới được canvas thêm {metadata_extension_px}px"
        ) from exc
    canvas.alpha_composite(content_canvas, (0, 0))
    overlay = Image.new("RGBA", (final_w, output_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # TASK-017 (2026-08-07, quy định MỚI chủ dự án) — logo LUÔN phải có,
    # KHÔNG ĐƯỢC BỎ (thay ngược lại quyết định TASK-013 "va chạm cả 2 góc ->
    # bỏ qua logo", bị chủ dự án bác vì logo là thương hiệu). Thiếu file logo
    # hoặc không tìm được vị trí sạch chữ trong NỬA chứa ảnh minh hoạ đều
    # RAISE (KHÔNG âm thầm hoàn thành ảnh thiếu logo) — caller
    # (`ai_full.render_ai_full`) bắt lỗi này để sinh lại ảnh / NEEDS_HUMAN,
    # xem contract TASK-017 + `select_logo_corner`/`_measure_illustration_half`
    # docstring cho lý do đổi thuật toán chọn góc.
    resolved_logo_asset = None
    if logo_path is not None:
        resolved_logo_path = Path(logo_path)
    else:
        resolved_logo_asset = _resolve_active_logo_asset()
        resolved_logo_path = resolved_logo_asset["path"]
    if not resolved_logo_path.is_file():
        raise ValueError(
            "LOGO_GUARDRAIL_FAIL: không tìm thấy file logo "
            f"'{resolved_logo_path}' -- logo LUÔN phải có (quy định chủ dự "
            "án, TASK-017), không được xuất ảnh thiếu logo."
        )
    logo = Image.open(resolved_logo_path).convert("RGBA")
    # SỬA LỖI THẬT (2026-08-04) — neo theo BỀ RỘNG (logo_width_ratio, xem
    # docstring _resolve_overlay_style), bề cao suy theo tỷ lệ khung ảnh
    # gốc (ĐẢO chiều tính so với bản height-anchored cũ).
    logo_w, logo_h, logo_margin, logo_y = _full_canvas_logo_geometry(
        logo, final_w=final_w, final_h=final_h, style=style
    )
    if logo_margin + logo_w > final_w or logo_y + logo_h > final_h:
        raise ValueError("Logo full-canvas vượt biên ảnh; kiểm tra config infographic_overlay")
    half = _measure_illustration_half(
        content_canvas, final_w=final_w, final_h=final_h, background=colors["background"],
        top_fraction=style["logo_half_scan_top_fraction"],
        near_bg_tolerance=style["logo_half_scan_near_bg_tolerance"],
        near_bg_floor=style["logo_half_scan_near_bg_floor"],
        near_bg_ceiling=style["logo_half_scan_near_bg_ceiling"],
    )
    corner_result = select_logo_corner(
        content_canvas,
        logo_w=logo_w,
        logo_h=logo_h,
        logo_margin=logo_margin,
        logo_y=logo_y,
        final_w=final_w,
        final_h=final_h,
        corners=_corners_for_half(half["image_half"]),
        dark_pixel_floor=style["logo_text_dark_pixel_floor"],
        background=colors["background"],
        near_bg_tolerance=style["logo_half_scan_near_bg_tolerance"],
        corner_near_bg_floor=style["logo_corner_near_bg_floor"],
    )
    logo_scrim_applied = False
    if corner_result["chosen"] is None:
        raise ValueError(
            "LOGO_GUARDRAIL_FAIL: không có vị trí nào sạch chữ trong nửa "
            f"chứa ảnh minh hoạ ({half['image_half']}) để đặt logo -- KHÔNG "
            "được bỏ logo hay đè chữ (quy định chủ dự án, TASK-017); cần "
            "sinh lại ảnh."
        )
    chosen_candidate = next(
        c for c in corner_result["candidates"] if c["corner"] == corner_result["chosen"]
    )
    logo_x, logo_y = chosen_candidate["x"], chosen_candidate["y"]
    logo_position = corner_result["chosen"]
    tight_bbox = tuple(chosen_candidate["bbox"])
    if logo_path is not None:
        # Caller ép 1 file logo cụ thể (vd test) -- KHÔNG chuyển biến thể.
        variant_result = {
            "path": resolved_logo_path, "variant": "custom", "bg_dark_pixel_ratio": None,
            "navy_contrast_score": None, "white_contrast_score": None,
            "both_variants_low_contrast": False, "reason": "explicit_logo_path",
        }
    else:
        variant_result = _select_logo_variant(
            content_canvas, tight_bbox,
            navy_path=resolved_logo_asset["path"],
            white_path=resolved_logo_asset["white_gold_path"],
            low_contrast_floor=style["logo_low_contrast_floor"],
        )
        logo = Image.open(variant_result["path"]).convert("RGBA")
    logo = logo.resize((logo_w, logo_h), Image.LANCZOS)
    # SỬA LỖI THẬT (2026-08-04, Lead: "không recolor") — TRƯỚC ĐÂY theme sáng
    # ("bright"/"light") tự tô lại pixel gần trung tính (chroma thấp) của
    # logo sang màu chủ đạo theme. Bỏ hẳn — TASK-017 thay bằng chọn NGUYÊN
    # FILE biến thể navy-gold/white-gold có sẵn (xem `_select_logo_variant`),
    # không tô lại pixel nào.
    #
    # SỬA LỖI THẬT (2026-08-04, Lead: "tất cả ảnh Infographic đều có khung
    # chữ nhật xung quanh brand-kit") — không vẽ scrim/nền phía sau logo; logo
    # dán TRỰC TIẾP lên ảnh, không có gì phía sau ngoài chính ảnh AI. TASK-017
    # quy định 3 cho phép đè lên MỘT PHẦN ảnh minh hoạ (không phải chữ).
    overlay.alpha_composite(logo, (logo_x, logo_y))
    logo_bbox = [logo_x, logo_y, logo_x + logo_w, logo_y + logo_h]
    logo_in_bounds = True

    line_bottom = output_h - bottom
    text_y = line_bottom - line_h - text_bbox[1]
    backdrop_top = final_h if metadata_extended else max(text_y - v_pad, 0)
    draw.rectangle(
        (0, backdrop_top, final_w, output_h),
        fill=(*colors["background"], round(style["metadata_backdrop_opacity"])),
    )
    if source_text:
        draw.text((side, text_y), source_text, font=source_font, fill=(*colors["gold"], 255))
    if disclaimer:
        draw.text(
            (final_w - side - disclaimer_w_px, text_y),
            disclaimer,
            font=disclaimer_font,
            fill=(*colors["secondary"], 255),
        )

    rendered = Image.alpha_composite(canvas, overlay).convert("RGB")
    out = io.BytesIO()
    rendered.save(out, format="PNG")
    return out.getvalue(), {
        "overlay_mode": "full_canvas_deterministic",
        "theme": theme,
        "theme_id": theme_id,
        "source_wh": [source_w, source_h],
        "final_wh": [final_w, output_h],
        "content_wh": [final_w, final_h],
        "ratio_delta": round(ratio_delta, 6),
        "content_crop_px": 0,
        "matting_applied": False,
        "scale_x": round(final_w / source_w, 4),
        "scale_y": round(final_h / source_h, 4),
        "logo_position": logo_position,
        "logo_bbox": logo_bbox,
        "logo_in_bounds": logo_in_bounds,
        "logo_corner_candidates": corner_result["candidates"],
        "logo_all_corners_occupied": corner_result["all_occupied"],
        "logo_scrim_applied": logo_scrim_applied,
        "image_half": half["image_half"],
        "text_half": half["text_half"],
        "half_measurement": half,
        "logo_variant": variant_result["variant"],
        "logo_variant_reason": variant_result["reason"],
        "logo_bg_dark_pixel_ratio": variant_result["bg_dark_pixel_ratio"],
        "logo_navy_contrast_score": variant_result["navy_contrast_score"],
        "logo_white_contrast_score": variant_result["white_contrast_score"],
        "logo_both_variants_low_contrast": variant_result["both_variants_low_contrast"],
        "metadata_font_px": metadata_font_px,
        "image_body_font_px": body_font_px,
        "metadata_font_scale": style["metadata_font_scale"],
        "metadata_backdrop_top_px": backdrop_top,
        "metadata_text_scan": metadata_scan,
        "metadata_extended": metadata_extended,
        "metadata_extension_px": metadata_extension_px,
        "metadata_guardrail": "PASS_EXTENDED" if metadata_extended else "PASS_CLEAR",
        "source_text": source_text,
        "disclaimer_text": disclaimer,
        "metadata_single_line": True,
    }


# =====================================================================
# ĐIỂM VÀO CHÍNH
# =====================================================================

def stamp_brand(
    png_bytes: bytes,
    *,
    ratio: str,
    theme: str | None = None,
    wordmark: str = "FVA CAPITAL",
    source: str = "",
    disclaimer: str = "",
    font_path: str | None = None,
    logo_path: str | Path | None = None,
    settings=None,
) -> tuple[bytes, dict]:
    """Đóng dấu brand THEO KIẾN TRÚC KHUNG CỨNG ĐÁY (2026-07-23) + FIT-INSIDE
    matting/logo-trong-TOP_PAD (SỬA LỖI ĐẶC TẢ 2026-07-24 -- xem module
    docstring, phiên trước tự phát hiện lỗi ở "cover-fit + cắt cân giữa" của
    chính đặc tả mình, KHÔNG phải bug lập trình).

    KHÁC BIỆT CỐT LÕI với bản cover-fit cũ: ảnh AI KHÔNG BAO GIỜ bị cắt để
    lấp đầy khung -- nó luôn nằm TRỌN VẸN bên trong (fit-inside/contain,
    scale_factor <=1.0), phần dư (nếu có) lấp bằng màu band. TOP_PAD (dải
    cho logo) được trừ sẵn vào phép tính scale (Bước 2) -- va chạm chữ/nội
    dung, cắt nội dung, hay logo đè ảnh đều BẤT KHẢ THI VỀ CẤU TRÚC, không
    phải "đã canh cho khỏi đụng" (có thể sai khi dữ liệu đổi).

    Trả (PNG bytes ĐÃ đóng dấu, log dict) -- log PHẢI được ai_full.py ghi
    cạnh ảnh (JSON) để Lead kiểm không cần mở ảnh, CHẤM BẰNG SỐ (scale_factor/
    top_pad_px/side_pad_px) chứ KHÔNG dựa mắt -- mắt không bắt được lỗi crop
    nếu band vẫn trông sạch (xem STOP-REPORT phiên trước): {cropped_top_px,
    band_h, band_color, band_color_source, ai_size_requested, ai_size_reason,
    ratio_inner, ratio_ai, scale_factor, top_pad_px, side_pad_px, logo_in_pad,
    source_text, disclaimer_lines, final_wh}."""
    theme, theme_id, palette = load_theme_palette(theme)
    stamp_style = _resolve_stamp_style()
    colors = {
        "bg": _hex_to_rgb(palette["background.primary"]),
        "text": _hex_to_rgb(palette["text.primary"]),
        "muted": _hex_to_rgb(palette["text.secondary"]),
        "gold": _hex_to_rgb(palette["accent.gold"]),
    }

    im = Image.open(io.BytesIO(png_bytes)).convert("RGB")

    # --- Bước 1: edge sanitizer (lưới an toàn, KHÔNG thay cho sửa prompt) ---
    im, cropped_top_px = _edge_sanitize_top(im)
    ratio_ai = im.size[0] / im.size[1]

    # --- kích thước khung + logo (TRƯỚC matting -- Bước 2 cần logo_h+2*pad để
    # trừ vào TOP_PAD ngay trong phép tính scale, xem `_matte`) -------------
    final_w, final_h = _resolve_final_size(ratio, settings)
    band_min_px = _resolve_band_min_px(settings)
    nominal_band_h = max(round(final_h * 0.075), band_min_px)
    resolved_logo_path = Path(logo_path) if logo_path else _default_logo_path()
    logo_w, logo_h, pad = _logo_dimensions(resolved_logo_path, final_w=final_w, final_h=final_h)
    min_top_pad = logo_h + 2 * pad

    # --- Bước 2: matting fit-inside (final_h - band_h danh nghĩa) -----------
    fit = _matte(im, target_w=final_w, target_h=final_h - nominal_band_h, min_top_pad=min_top_pad)

    # --- Bước 3: màu band tự khớp -------------------------------------------
    navy_fallback = _resolve_navy_fallback(
        theme=theme,
        theme_background=colors["bg"],
        settings=settings,
    )
    fallback_source = "fallback_navy" if theme == "dark" else "fallback_theme_background"
    band_color, band_color_source = _band_color(
        fit["resized"],
        navy_fallback=navy_fallback,
        fallback_source=fallback_source,
    )

    # --- Bước 4: đo nội dung band (CÓ THỂ khiến band nới cao hơn danh nghĩa) -
    margin_x = max(int(final_w * 0.04), 12)
    source_short = _shorten_source(source)
    source_text = f"Nguồn: {source_short}" if source_short else ""
    probe_canvas = Image.new("RGB", (final_w, final_h))
    probe_draw = ImageDraw.Draw(probe_canvas)
    layout = _layout_band_text(
        probe_draw, source_text=source_text, disclaimer_text=disclaimer,
        band_w=final_w, nominal_band_h=nominal_band_h, margin_x=margin_x, font_path=font_path,
        text_scale=stamp_style["footer_text_scale"],
    )
    band_h = layout["band_h"]
    if band_h != nominal_band_h:
        # NỚI band -- re-matte với inner_h nhỏ hơn (final_h GIỮ NGUYÊN, xem A1
        # -- khung xuất bản cố định, phần hy sinh là diện tích ảnh AI, KHÔNG
        # BAO GIỜ là chữ bị cắt).
        fit = _matte(im, target_w=final_w, target_h=final_h - band_h, min_top_pad=min_top_pad)
        band_color, band_color_source = _band_color(
            fit["resized"],
            navy_fallback=navy_fallback,
            fallback_source=fallback_source,
        )

    # --- Dựng canvas: nền màu band PHỦ TOÀN BỘ (2c -- phần dư lấp màu band) -
    # rồi dán ảnh AI (đã fit-inside) đúng vị trí: đáy khớp band, ngang giữa --
    canvas = Image.new("RGB", (final_w, final_h), band_color)
    canvas.paste(fit["resized"], (fit["left"], fit["top_pad_px"]))
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

    # --- Bước 5: logo trong TOP_PAD (KHÔNG scrim -- nền phẳng, xem SỬA 2) ---
    logo_in_pad = _paste_logo(overlay, logo_path=resolved_logo_path, top_pad_px=fit["top_pad_px"],
                              pad=pad, logo_w=logo_w, logo_h=logo_h, final_w=final_w,
                              left_ratio=stamp_style["logo_left_ratio"],
                              vertical_bias=stamp_style["logo_vertical_bias"],
                              neutral_tint=colors["text"] if theme == "light" else None)

    stamped = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    out = io.BytesIO()
    stamped.save(out, format="PNG")

    ai_size, ai_size_reason = select_ai_size(ratio, settings=settings)

    log = {
        "theme": theme,
        "theme_id": theme_id,
        "cropped_top_px": cropped_top_px,
        "band_h": band_h,
        "band_color": "#%02x%02x%02x" % band_color,
        "band_color_source": band_color_source,
        "ai_size_requested": list(ai_size),
        "ai_size_reason": ai_size_reason,
        "ratio_inner": round(final_w / (final_h - nominal_band_h), 4),
        "ratio_ai": round(ratio_ai, 4),
        "scale_factor": round(fit["scale_factor"], 4),
        "top_pad_px": fit["top_pad_px"],
        "side_pad_px": fit["side_pad_px"],
        "logo_in_pad": logo_in_pad,
        "logo_left_ratio": stamp_style["logo_left_ratio"],
        "logo_vertical_bias": stamp_style["logo_vertical_bias"],
        "source_font_px": getattr(layout["src_font"], "size", None),
        "disclaimer_font_px": getattr(layout["dis_font"], "size", None),
        "source_text": source_text,
        "disclaimer_lines": layout["dis_lines"],
        "final_wh": [final_w, final_h],
    }
    return out.getvalue(), log
