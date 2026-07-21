"""Render spec InfographicSpecAgent (JSON) -> ảnh SVG thật — TẤT ĐỊNH, lớp
CODE (chữ/số/layout) $0 luôn luôn; lớp AI (nền) TUỲ CHỌN qua `render_mode`
(xem HYBRID bên dưới) — KHÔNG dùng LLM cho bất kỳ chữ/số/layout nào (mãi mãi
đúng nguyên tắc PRODUCTION FACTORY PHASE 1.2 gốc), CHỈ ảnh nền minh hoạ mới
qua AI, và CHỈ khi `render_mode="hybrid"`.

PRODUCTION FACTORY PHASE 1.2 (quyết định #4 — giữ SVG, KHÔNG chuyển Playwright/
HTML): brand kit (màu/font/wordmark/footer) đọc từ `config/brand.yaml` (MỘT
NGUỒN, qua `config.load_brand()`) — dùng CHUNG cho renderer này VÀ template
video (CSS, Phase 2) sau này, vì infographic/video KHÔNG chung LAYOUT nhưng
chung TOKEN thương hiệu. KÍCH THƯỚC (width/height, layout thuần) vẫn đọc từ
`render.infographic.*` trong config/settings.yaml — settings.yaml CÓ THỂ ghi
đè từng token brand riêng lẻ nếu 1 lượt render cụ thể cần khác đi tạm thời
(brand.yaml là mặc định, không bắt buộc). `brand_kit_from_settings()` gộp cả
2 nguồn — đổi màu/logo/wordmark chỉ sửa config/brand.yaml, KHÔNG sửa code.

HYBRID (chốt 2026-07-19, xem docs/VPS_MIGRATION_BACKLOG.md C8) — 2 lượt test
renderer HTML/SVG thuần (kể cả bản 2 có lưới nền/đánh số mục/đường nối)
KHÔNG cải thiện đáng kể cảm nhận thị giác (khô cứng, thiếu hồn). Quyết định:
thêm lớp AI (`ai_background.py`) sinh ẢNH NỀN minh hoạ, GIỮ NGUYÊN mọi chữ/
số/layout/bản đồ/icon ở CODE tất định — AI KHÔNG BAO GIỜ được phép sinh chữ,
số, bản đồ Việt Nam (đòi chính xác địa lý + Hoàng Sa/Trường Sa — asset SVG
tĩnh, không AI), hay icon thay thế bộ SVG tĩnh sẵn có. Tính TẤT ĐỊNH của
renderer (2 lần chạy cùng input -> ảnh giống hệt) được GIỮ qua CACHE
(`ai_background.get_or_generate_background()`), KHÔNG qua bản thân API (API
generative không tất định) — cache HIT không gọi API, đảm bảo re-render
không đổi.

`render_mode` (config `render.infographic.render_mode`, mặc định "hybrid"):
  "hybrid"    -> gọi `ai_background` lấy nền (cache-first); lỗi/thiếu key/
                 timeout -> tự fallback "pure_html" NGAY, ghi cảnh báo rõ,
                 KHÔNG crash, KHÔNG render ảnh vỡ (xem `render_infographic()`).
  "pure_html" -> bỏ qua HOÀN TOÀN lớp AI — không gọi API, không cần key. Giữ
                 làm đường lui/so sánh, và làm chế độ mặc định khi thiếu
                 OPENAI_API_KEY trên môi trường (vd CI/test).

Bố cục cố định (template đơn), từ trên xuống:
  wordmark + related (mã) -> title -> subtitle -> thẻ số liệu (hero+market gộp,
  tối đa 5, thẻ hero được nhấn) -> highlights -> footer (disclaimer + nguồn).
Chiều cao canvas GIỜ CO GIÃN nhẹ theo lượng nội dung (B6, 2026-07-19) — xem
`_measure_content_height()`: nội dung NGẮN không còn để trống mảng lớn giữa
takeaway và footer như bản cũ (footer neo cứng đáy canvas cố định) — khoảng
trống THỪA được phân bổ lại thành giãn cách giữa các khối (đều, có chủ đích),
KHÔNG co nhỏ hẳn canvas (giữ tỉ lệ 4:5 nhất quán cho MXH).

PHASE 4.11: schema spec đổi từ headline/subhead/tickers/stats/takeaway/footer
(Phase 4.10, InfographicSpecAgent trích thẳng facts[]) sang 8 TRƯỜNG composer
(title/subtitle/hero/market/highlights/related/priority/source) + render_hint
riêng — disclaimer KHÔNG còn trong spec (thuộc RENDER, xem agents/production.py
docstring InfographicSpecAgent) nên module này tự giữ hằng số disclaimer
riêng, KHÔNG phụ thuộc ngược vào agents/production (giữ decoupled).
`render_hint` (theme/palette/ratio) hiện là gợi ý MỀM, CHƯA áp dụng vào layout
(vẫn dùng brand_kit cố định) — để ngỏ cho việc tinh chỉnh sau, không thuộc yêu
cầu Phase 4.11.

Bọc chữ (word-wrap) bằng ước lượng ký tự/dòng theo font-size — KHÔNG đo font
thật (không có engine đo chữ trong stdlib) nên với tiêu đề rất dài, dòng có thể
lệch nhẹ; đủ dùng cho MVP xem trước, chưa phải render pixel-perfect.
"""
from __future__ import annotations

import base64
import html
import logging
import textwrap
from pathlib import Path

logger = logging.getLogger("twmkt.render.infographic")

# Lùi mượt CUỐI CÙNG nếu CẢ settings.yaml LẪN config/brand.yaml đều thiếu key
# (vd môi trường test dựng Settings({}) trần, hoặc brand.yaml bị xoá nhầm) —
# KHÔNG còn brand cũ (đã chốt brand mới, xem config/brand.yaml +
# PROJECT_HANDOFF_P5.md §1); giữ palette navy/gold hiện có (gần đúng logo
# thật, xem config/brand.yaml ghi chú màu ước).
_DEFAULT_BRAND = {
    "width": 1080,
    "height": 1350,
    "bg": "#0B1B2B",
    "surface": "#132A3E",
    "primary": "#E7C873",
    "text": "#F5F5F0",
    "text_muted": "#9FB3C8",
    "font_family": "Arial, 'Segoe UI', sans-serif",
    "wordmark": "FVA CAPITAL",
}

# Phase 4.11: disclaimer KHÔNG còn trong spec (data/style tách bạch) -> render
# tự gắn. Phase 1.2: ưu tiên đọc config/brand.yaml (footer.disclaimer) qua
# brand_kit_from_settings(); hằng số này CHỈ còn là lùi-mượt-cuối-cùng khi
# brand.yaml thiếu/lỗi (KHÔNG import ngược agents/production, giữ render độc
# lập — trùng nội dung agents/production._FALLBACK_DISCLAIMER có chủ đích, xem
# Content Factory Phase D — disclaimer rút gọn).
_RENDER_DISCLAIMER = "Nội dung mang tính thông tin, không phải khuyến nghị đầu tư."

# B6 — chiều cao TỐI THIỂU giữa 2 khối liền kề khi phân bổ khoảng trống thừa
# (tránh giãn quá tay nếu nội dung SIÊU ngắn, trông vẫn phải như 1 trang liền
# mạch chứ không phải các khối rời rạc trôi nổi).
_MAX_EXTRA_GAP_PER_SLOT = 90


def brand_kit_from_settings(settings) -> dict:
    """Gộp brand kit từ 2 nguồn (Phase 1.2, quyết định #4): MÀU/FONT/WORDMARK/
    FOOTER từ `config/brand.yaml` (MỘT NGUỒN, qua `config.load_brand()`) —
    KÍCH THƯỚC (width/height, layout thuần) từ `render.infographic.*` trong
    settings.yaml. settings.yaml CÓ THỂ ghi đè từng token brand riêng lẻ (vd
    `render.infographic.primary`) nếu 1 lượt render cụ thể cần khác brand.yaml
    tạm thời — brand.yaml là mặc định, không bắt buộc. Thiếu CẢ 2 nguồn cho 1
    key -> lùi về `_DEFAULT_BRAND`."""
    from ..config import load_brand

    brand = load_brand()
    colors = brand.get("colors", {}) if isinstance(brand.get("colors"), dict) else {}
    footer = brand.get("footer", {}) if isinstance(brand.get("footer"), dict) else {}
    g = lambda k, d: settings.get(f"render.infographic.{k}", d)
    return {
        "width": int(g("width", _DEFAULT_BRAND["width"])),
        "height": int(g("height", _DEFAULT_BRAND["height"])),
        "bg": g("bg", colors.get("bg", _DEFAULT_BRAND["bg"])),
        "surface": g("surface", colors.get("surface", _DEFAULT_BRAND["surface"])),
        "primary": g("primary", colors.get("primary", _DEFAULT_BRAND["primary"])),
        "text": g("text", colors.get("text", _DEFAULT_BRAND["text"])),
        "text_muted": g("text_muted", colors.get("text_muted", _DEFAULT_BRAND["text_muted"])),
        "font_family": g("font_family", brand.get("font_family", _DEFAULT_BRAND["font_family"])),
        "wordmark": g("wordmark", brand.get("wordmark", _DEFAULT_BRAND["wordmark"])),
        "disclaimer": g("disclaimer", footer.get("disclaimer", _RENDER_DISCLAIMER)),
    }


def _esc(s: str) -> str:
    return html.escape(str(s or ""), quote=False)


def _wrap(text: str, max_chars: int) -> list[str]:
    return textwrap.wrap(str(text or ""), width=max(max_chars, 8)) or [""]


def _tspans(lines: list[str], *, x: int, dy_first: int, line_height: int) -> str:
    out = []
    for i, line in enumerate(lines):
        dy = dy_first if i == 0 else line_height
        out.append(f'<tspan x="{x}" dy="{dy}">{_esc(line)}</tspan>')
    return "".join(out)


def _prepare_content(spec: dict, w: int) -> dict:
    """Bóc dữ liệu spec + đo trước (word-wrap) — TÁCH khỏi phần emit SVG để
    B6 (co giãn layout) đo được TỔNG chiều cao nội dung TRƯỚC khi quyết định
    khoảng-trống-thừa phân bổ ra sao, không phải đoán/thử-sai."""
    related = spec.get("related") or []
    ticker_txt = " · ".join(str(t) for t in related)

    headline_lines = _wrap(spec.get("title", ""), max_chars=18)[:4]
    subhead_lines = _wrap(spec.get("subtitle", ""), max_chars=42)[:2]
    takeaway_lines = [line for h in (spec.get("highlights") or [])
                      for line in _wrap(str(h), max_chars=48)][:5]

    hero = [{**s, "emphasis": True} for s in (spec.get("hero") or [])]
    market = [{**s, "emphasis": False} for s in (spec.get("market") or [])]
    stats = (hero + market)[:5]

    return {
        "ticker_txt": ticker_txt,
        "headline_lines": headline_lines,
        "subhead_lines": subhead_lines,
        "takeaway_lines": takeaway_lines,
        "stats": stats,
    }


def _measure_content_height(content: dict, *, cw: int, pad: int, disclaimer_lines: int) -> int:
    """Tổng chiều cao "tự nhiên" (không giãn cách thêm) từ đỉnh wordmark tới
    hết khối takeaway — dùng để tính khoảng-trống-thừa (B6) khi so với chiều
    cao canvas cấu hình. THUẦN, không I/O, không phụ thuộc SVG string."""
    y = 10 + 90  # wordmark + khoảng trước headline
    y += 72 * len(content["headline_lines"])
    y += 34 + 38 * len(content["subhead_lines"]) + 30
    stats = content["stats"]
    if stats:
        cols = min(len(stats), 3)
        rows = -(-len(stats) // cols)
        y += rows * (160 + 20) + 20
    else:
        y += 20
    y += 44 + 44 * max(len(content["takeaway_lines"]), 1)
    return y


def _background_image_layers(background_image_data_uri: str | None, *, w: int, h: int) -> list[str]:
    """B2 — 2 lớp ảnh nền, chèn NGAY SAU rect nền cơ bản (trước MỌI text/thẻ
    số liệu) để z-order tự nhiên đảm bảo "TUYỆT ĐỐI KHÔNG đè lên vùng số
    liệu" — thẻ/chữ vẽ SAU trong DOM order sẽ tự nằm TRÊN ảnh nền, không cần
    logic clip riêng cho từng vùng.

    Lớp 1: toàn trang, mờ (opacity thấp) — "không khí" chung.
    Lớp 2: dải header (top ~42% canvas), đậm hơn, fade mượt về 0 ở đáy dải
    (linearGradient mask) — v vùng ảnh header rõ nét hơn, không cắt cụt đột
    ngột khi giao với vùng nội dung."""
    if not background_image_data_uri:
        return []
    header_h = int(h * 0.42)
    return [
        '<defs>'
        '<linearGradient id="bgHeaderFade" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0%" stop-color="white" stop-opacity="1"/>'
        '<stop offset="70%" stop-color="white" stop-opacity="0.6"/>'
        '<stop offset="100%" stop-color="white" stop-opacity="0"/>'
        '</linearGradient>'
        f'<mask id="bgHeaderMask"><rect x="0" y="0" width="{w}" height="{header_h}" '
        'fill="url(#bgHeaderFade)"/></mask>'
        '</defs>',
        f'<image href="{background_image_data_uri}" x="0" y="0" width="{w}" height="{h}" '
        'preserveAspectRatio="xMidYMid slice" opacity="0.18"/>',
        f'<image href="{background_image_data_uri}" x="0" y="0" width="{w}" height="{h}" '
        'preserveAspectRatio="xMidYMid slice" opacity="0.62" mask="url(#bgHeaderMask)"/>',
    ]


def render_infographic_svg(
    spec: dict,
    brand: dict | None = None,
    *,
    background_image_data_uri: str | None = None,
) -> str:
    """`spec` = dict đúng schema Composer (Phase 4.11, xem agents/production.py
    InfographicSpecAgent/infographic_spec_from_data): title, subtitle, hero[],
    market[] ({label,value} mỗi item), highlights[], related[], priority,
    source. `render_hint` (nếu có) hiện CHƯA áp dụng vào layout (gợi ý mềm,
    xem docstring module). `background_image_data_uri` (Hybrid, B2) — data URI
    "data:image/png;base64,..." từ `ai_background.get_or_generate_background()`
    hoặc `None` (pure_html/fallback, xem `render_infographic()`). Trả về chuỗi
    SVG hoàn chỉnh (chuẩn XML, có khai báo header). HÀM THUẦN, TẤT ĐỊNH: cùng
    tham số -> cùng chuỗi SVG -> cùng ảnh xuất, mọi lúc."""
    b = {**_DEFAULT_BRAND, **(brand or {})}
    w, h = b["width"], b["height"]
    pad = int(w * 0.07)
    cw = w - 2 * pad   # content width

    content = _prepare_content(spec, w)
    ticker_txt = content["ticker_txt"]
    headline_lines = content["headline_lines"]
    subhead_lines = content["subhead_lines"]
    takeaway_lines = content["takeaway_lines"]
    stats = content["stats"]
    disclaimer_lines = _wrap(b.get("disclaimer", _RENDER_DISCLAIMER), max_chars=70)[:3]
    source = spec.get("source", "")

    # --- B6: co giãn layout theo lượng nội dung ------------------------------
    natural_h = _measure_content_height(content, cw=cw, pad=pad, disclaimer_lines=len(disclaimer_lines))
    footer_block_h = 30 + 18 * (len(disclaimer_lines) - 1) + 60
    available = h - pad - footer_block_h - (pad + natural_h)
    # 4 khe giãn cách (sau wordmark/headline, sau subhead, sau stats, trước
    # takeaway) chia đều slack thừa, mỗi khe tối đa _MAX_EXTRA_GAP_PER_SLOT —
    # nội dung CÀNG ngắn thì khoảng cách CÀNG rộng (có chủ đích, không phải 1
    # cục trống ở cuối như bản cũ), nội dung dài (slack <= 0) -> extra_gap=0,
    # hành vi giống hệt bản cũ (không co lại nhỏ hơn, tránh chữ chồng nhau).
    extra_gap = max(0, min(_MAX_EXTRA_GAP_PER_SLOT, available / 4)) if available > 0 else 0

    parts: list[str] = []
    parts.append(
        f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        f'xmlns="http://www.w3.org/2000/svg" font-family="{_esc(b["font_family"])}">'
    )
    parts.append(f'<rect x="0" y="0" width="{w}" height="{h}" fill="{b["bg"]}"/>')
    parts.extend(_background_image_layers(background_image_data_uri, w=w, h=h))

    # --- wordmark + ticker pill --------------------------------------------
    y = pad + 10
    parts.append(f'<text x="{pad}" y="{y}" font-size="26" font-weight="700" '
                 f'letter-spacing="2" fill="{b["primary"]}">{_esc(b.get("wordmark", "FVA CAPITAL"))}</text>')
    if ticker_txt:
        # Giới hạn bề rộng pill để KHÔNG BAO GIỜ tràn ra ngoài canvas (bug phát
        # hiện qua dữ liệu thật: related[] nhiều mục -> ticker dài -> pill_w cũ
        # không giới hạn từng vượt cả chiều rộng canvas). Cắt bớt + "…" khi quá
        # dài, KHÔNG đổi cỡ chữ/định dạng khác.
        max_pill_w = w - 2 * pad - 220
        max_chars_ticker = max(10, int((max_pill_w - 24) / 16))
        if len(ticker_txt) > max_chars_ticker:
            ticker_txt = ticker_txt[: max_chars_ticker - 1].rstrip(" ·") + "…"
        pill_w = 24 + 16 * len(ticker_txt)
        px = w - pad - pill_w
        parts.append(f'<rect x="{px}" y="{y - 30}" width="{pill_w}" height="42" rx="21" '
                     f'fill="{b["surface"]}" stroke="{b["primary"]}"/>')
        parts.append(f'<text x="{px + pill_w / 2}" y="{y - 3}" text-anchor="middle" '
                     f'font-size="20" font-weight="700" fill="{b["text"]}">{_esc(ticker_txt)}</text>')

    # --- headline ------------------------------------------------------------
    y += 90 + extra_gap
    parts.append(f'<text x="{pad}" y="{y}" font-size="64" font-weight="800" '
                 f'fill="{b["text"]}">{_tspans(headline_lines, x=pad, dy_first=0, line_height=72)}</text>')
    y += 72 * len(headline_lines)

    # --- subhead ---------------------------------------------------------
    y += 34 + extra_gap
    parts.append(f'<text x="{pad}" y="{y}" font-size="30" fill="{b["text_muted"]}">'
                 f'{_tspans(subhead_lines, x=pad, dy_first=0, line_height=38)}</text>')
    y += 38 * len(subhead_lines) + 30

    # --- thẻ số liệu (grid tối đa 3 cột) ------------------------------------
    y += extra_gap
    if stats:
        cols = min(len(stats), 3)
        gap = 20
        card_w = (cw - gap * (cols - 1)) / cols
        card_h = 160
        for i, st in enumerate(stats):
            col, row = i % cols, i // cols
            cx = pad + col * (card_w + gap)
            cy = y + row * (card_h + gap)
            emphasis = bool(st.get("emphasis"))
            fill = b["primary"] if emphasis else b["surface"]
            value_color = b["bg"] if emphasis else b["primary"]
            label_color = b["bg"] if emphasis else b["text_muted"]
            parts.append(f'<rect x="{cx:.0f}" y="{cy:.0f}" width="{card_w:.0f}" height="{card_h}" '
                         f'rx="16" fill="{fill}"/>')
            # Giá trị DÀI (bug phát hiện qua dữ liệu thật: khoảng số liệu kiểu
            # "48,6-57,4 triệu TEU" tràn khỏi thẻ ở cỡ chữ 44 cố định) -> giảm
            # cỡ chữ + gói 2 dòng thay vì tràn/chồng lên thẻ kế bên.
            value_text = str(st.get("value", ""))
            vx = cx + card_w / 2
            if len(value_text) > 10:
                v_lines = _wrap(value_text, max_chars=14)[:2]
                v_span = _tspans(v_lines, x=vx, dy_first=0, line_height=30)
                v_y = cy + 62
                v_font = 26
            else:
                v_span = _tspans([value_text], x=vx, dy_first=0, line_height=0)
                v_y = cy + 88
                v_font = 44
            parts.append(f'<text x="{vx:.0f}" y="{v_y:.0f}" text-anchor="middle" '
                         f'font-size="{v_font}" font-weight="800" fill="{value_color}">{v_span}</text>')
            parts.append(f'<text x="{cx + card_w / 2:.0f}" y="{cy + 128:.0f}" text-anchor="middle" '
                         f'font-size="20" fill="{label_color}">{_esc(st.get("label", ""))}</text>')
        rows = -(-len(stats) // cols)
        y += rows * (card_h + gap) + 20
    else:
        y += 20

    # --- takeaway ----------------------------------------------------------
    y += 44 + extra_gap
    parts.append(f'<text x="{pad}" y="{y}" font-size="34" fill="{b["text"]}">'
                 f'{_tspans(takeaway_lines, x=pad, dy_first=0, line_height=44)}</text>')

    # --- footer (đáy canvas, cố định) ----------------------------------------
    fy = h - pad - 18 * (len(disclaimer_lines) - 1) - 60
    parts.append(f'<line x1="{pad}" y1="{fy - 30}" x2="{w - pad}" y2="{fy - 30}" '
                 f'stroke="{b["text_muted"]}" stroke-opacity="0.4"/>')
    parts.append(f'<text x="{pad}" y="{fy}" font-size="18" fill="{b["text_muted"]}">'
                 f'{_tspans(disclaimer_lines, x=pad, dy_first=0, line_height=24)}</text>')
    if source:
        parts.append(f'<text x="{w - pad}" y="{h - pad}" text-anchor="end" font-size="20" '
                     f'font-weight="700" fill="{b["primary"]}">Nguồn: {_esc(source)}</text>')

    parts.append("</svg>")
    return "".join(parts)


def render_infographic(
    spec: dict,
    *,
    brand: dict | None = None,
    settings=None,
    topic: str | None = None,
    regenerate: bool = False,
    assets_dir: str | Path | None = None,
) -> tuple[str, str]:
    """Điểm vào NÊN DÙNG (thay vì gọi thẳng `render_infographic_svg()`) — đọc
    `render.infographic.render_mode` (config, mặc định "hybrid"), tự quyết
    định có gọi lớp AI hay không, LUÔN LUÔN trả về SVG hợp lệ (không bao giờ
    "ảnh vỡ", đúng B5). Trả `(svg_string, warning)` — `warning` rỗng nếu mọi
    thứ suôn sẻ (kể cả pure_html chủ động, không phải lỗi), khác rỗng khi
    hybrid rơi về pure_html do lỗi/thiếu key/timeout.

    `topic` = CHỦ ĐỀ CHÍNH (vd `spec["title"]`) — bắt buộc nếu muốn hybrid
    thật (không có topic -> coi như pure_html, không đoán chủ đề từ đâu khác).

    `assets_dir=None` (mặc định) -> `ai_background.get_or_generate_background()`
    tự resolve qua `data_path()` (NGOÀI repo, dưới `storage.data_root`) —
    KHÔNG cache ảnh AI trong repo. Truyền tường minh để override (test dùng
    `tmp_path`).
    """
    render_mode = "hybrid"
    if settings is not None:
        render_mode = settings.get("render.infographic.render_mode", "hybrid")

    b = brand if brand is not None else _DEFAULT_BRAND
    warning = ""
    background_data_uri = None

    if render_mode == "hybrid" and topic:
        from .ai_background import get_or_generate_background

        png_path, ai_warning = get_or_generate_background(
            topic, assets_dir=assets_dir, regenerate=regenerate, settings=settings
        )
        if png_path is not None:
            png_bytes = Path(png_path).read_bytes()
            background_data_uri = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
        else:
            warning = ai_warning or "hybrid mode nhưng không sinh được nền (không rõ lý do) -- fallback pure_html."
            logger.warning(warning)
    elif render_mode == "hybrid" and not topic:
        warning = "hybrid mode nhưng thiếu 'topic' -- không đoán chủ đề, fallback pure_html."
        logger.warning(warning)

    svg = render_infographic_svg(spec, b, background_image_data_uri=background_data_uri)
    return svg, warning
