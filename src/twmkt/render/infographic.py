"""Render spec InfographicSpecAgent (JSON) -> ảnh SVG thật — $0, TẤT ĐỊNH.

KHÔNG dùng LLM, KHÔNG phụ thuộc ngoài (không cần Pillow/cairo): SVG là văn bản
XML thuần, mở trực tiếp bằng trình duyệt hoặc export PNG bằng công cụ thiết kế
khi cần đăng MXH. Brand kit (màu/font/kích thước) đọc từ config/settings.yaml
(mục `render.infographic`) qua `brand_kit_from_settings()` — đổi màu không sửa
code (adapter/config-first như CLAUDE.md yêu cầu).

Bố cục cố định (template đơn), từ trên xuống:
  wordmark + tickers -> headline -> subhead -> thẻ số liệu (tối đa 5, thẻ đầu
  emphasis) -> takeaway -> footer (disclaimer + nguồn).
Bọc chữ (word-wrap) bằng ước lượng ký tự/dòng theo font-size — KHÔNG đo font
thật (không có engine đo chữ trong stdlib) nên với tiêu đề rất dài, dòng có thể
lệch nhẹ; đủ dùng cho MVP xem trước, chưa phải render pixel-perfect.
"""
from __future__ import annotations

import html
import textwrap

_DEFAULT_BRAND = {
    "width": 1080,
    "height": 1350,
    "bg": "#0B1B2B",
    "surface": "#132A3E",
    "primary": "#E7C873",
    "text": "#F5F5F0",
    "text_muted": "#9FB3C8",
    "font_family": "Arial, 'Segoe UI', sans-serif",
}


def brand_kit_from_settings(settings) -> dict:
    """Đọc `render.infographic.*`, thiếu key nào dùng mặc định tương ứng."""
    g = lambda k, d: settings.get(f"render.infographic.{k}", d)
    return {
        "width": int(g("width", _DEFAULT_BRAND["width"])),
        "height": int(g("height", _DEFAULT_BRAND["height"])),
        "bg": g("bg", _DEFAULT_BRAND["bg"]),
        "surface": g("surface", _DEFAULT_BRAND["surface"]),
        "primary": g("primary", _DEFAULT_BRAND["primary"]),
        "text": g("text", _DEFAULT_BRAND["text"]),
        "text_muted": g("text_muted", _DEFAULT_BRAND["text_muted"]),
        "font_family": g("font_family", _DEFAULT_BRAND["font_family"]),
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


def render_infographic_svg(spec: dict, brand: dict | None = None) -> str:
    """`spec` = dict đúng schema InfographicSpecAgent.run() (xem agents/production.py):
    headline, subhead, tickers, stats[{label,value,emphasis}], takeaway, footer.
    Trả về chuỗi SVG hoàn chỉnh (chuẩn XML, có khai báo header)."""
    b = {**_DEFAULT_BRAND, **(brand or {})}
    w, h = b["width"], b["height"]
    pad = int(w * 0.07)
    cw = w - 2 * pad   # content width

    tickers = spec.get("tickers") or []
    ticker_txt = " · ".join(str(t) for t in tickers)

    headline_lines = _wrap(spec.get("headline", ""), max_chars=18)[:4]
    subhead_lines = _wrap(spec.get("subhead", ""), max_chars=42)[:2]
    takeaway_lines = _wrap(spec.get("takeaway", ""), max_chars=48)[:5]

    stats = (spec.get("stats") or [])[:5]
    footer = spec.get("footer") or {}
    disclaimer_lines = _wrap(footer.get("disclaimer", ""), max_chars=70)[:3]
    source = footer.get("source", "")

    parts: list[str] = []
    parts.append(
        f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        f'xmlns="http://www.w3.org/2000/svg" font-family="{_esc(b["font_family"])}">'
    )
    parts.append(f'<rect x="0" y="0" width="{w}" height="{h}" fill="{b["bg"]}"/>')

    # --- wordmark + ticker pill --------------------------------------------
    y = pad + 10
    parts.append(f'<text x="{pad}" y="{y}" font-size="26" font-weight="700" '
                 f'letter-spacing="2" fill="{b["primary"]}">TURTLE WEALTH VN</text>')
    if ticker_txt:
        pill_w = 24 + 16 * len(ticker_txt)
        px = w - pad - pill_w
        parts.append(f'<rect x="{px}" y="{y - 30}" width="{pill_w}" height="42" rx="21" '
                     f'fill="{b["surface"]}" stroke="{b["primary"]}"/>')
        parts.append(f'<text x="{px + pill_w / 2}" y="{y - 3}" text-anchor="middle" '
                     f'font-size="20" font-weight="700" fill="{b["text"]}">{_esc(ticker_txt)}</text>')

    # --- headline ------------------------------------------------------------
    y += 90
    parts.append(f'<text x="{pad}" y="{y}" font-size="64" font-weight="800" '
                 f'fill="{b["text"]}">{_tspans(headline_lines, x=pad, dy_first=0, line_height=72)}</text>')
    y += 72 * len(headline_lines)

    # --- subhead ---------------------------------------------------------
    y += 34
    parts.append(f'<text x="{pad}" y="{y}" font-size="30" fill="{b["text_muted"]}">'
                 f'{_tspans(subhead_lines, x=pad, dy_first=0, line_height=38)}</text>')
    y += 38 * len(subhead_lines) + 30

    # --- thẻ số liệu (grid tối đa 3 cột) ------------------------------------
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
            parts.append(f'<text x="{cx + card_w / 2:.0f}" y="{cy + 88:.0f}" text-anchor="middle" '
                         f'font-size="44" font-weight="800" fill="{value_color}">'
                         f'{_esc(st.get("value", ""))}</text>')
            parts.append(f'<text x="{cx + card_w / 2:.0f}" y="{cy + 128:.0f}" text-anchor="middle" '
                         f'font-size="20" fill="{label_color}">{_esc(st.get("label", ""))}</text>')
        rows = -(-len(stats) // cols)
        y += rows * (card_h + gap) + 20
    else:
        y += 20

    # --- takeaway ----------------------------------------------------------
    y += 44
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
