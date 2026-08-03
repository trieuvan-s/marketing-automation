"""Hậu kiểm ảnh infographic bằng Pillow, không LLM và không OCR dịch vụ.

Detector ở đây cố ý hẹp:
- ``scan_text_collision`` tìm nhiều thành phần nét chữ tương phản, cùng hàng,
  trong bbox nhỏ do code sở hữu (logo/metadata).
- ``detect_ordinal_markers`` tìm ít nhất ba marker đơn, hẹp, cùng cỡ và thẳng
  cột. Đây là hình học của danh sách 1/2/3 hoặc ①②③; không cố đọc toàn ảnh.

Kết quả không được dùng để diễn giải nội dung. Nó chỉ quyết định overlay có an
toàn và ảnh có chứa dấu hiệu xếp hạng ngoài facts hay không.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from PIL import Image, ImageDraw, ImageFilter, ImageOps


@dataclass(frozen=True)
class Component:
    left: int
    top: int
    right: int
    bottom: int
    pixels: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2


def expand_bbox(
    bbox: Iterable[int],
    *,
    image_size: tuple[int, int],
    ratio: float = 0.20,
) -> tuple[int, int, int, int]:
    left, top, right, bottom = (int(v) for v in bbox)
    width = right - left
    height = bottom - top
    dx = round(width * ratio)
    dy = round(height * ratio)
    image_w, image_h = image_size
    return (
        max(left - dx, 0),
        max(top - dy, 0),
        min(right + dx, image_w),
        min(bottom + dy, image_h),
    )


def _components(mask: Image.Image, *, min_pixels: int = 4) -> list[Component]:
    """Connected components 8-neighbour trên ảnh ``L`` nhị phân."""
    width, height = mask.size
    pixels = mask.load()
    visited = bytearray(width * height)
    found: list[Component] = []
    for y in range(height):
        for x in range(width):
            index = y * width + x
            if visited[index] or pixels[x, y] == 0:
                continue
            stack = [(x, y)]
            visited[index] = 1
            left = right = x
            top = bottom = y
            count = 0
            while stack:
                px, py = stack.pop()
                count += 1
                left = min(left, px)
                right = max(right, px)
                top = min(top, py)
                bottom = max(bottom, py)
                for ny in range(max(py - 1, 0), min(py + 2, height)):
                    row = ny * width
                    for nx in range(max(px - 1, 0), min(px + 2, width)):
                        neighbour = row + nx
                        if not visited[neighbour] and pixels[nx, ny] != 0:
                            visited[neighbour] = 1
                            stack.append((nx, ny))
            if count >= min_pixels:
                found.append(Component(left, top, right + 1, bottom + 1, count))
    return found


def _contrast_mask(image: Image.Image) -> Image.Image:
    """Mask nét tối/sáng có tương phản mạnh so với nền cục bộ."""
    gray = image.convert("L")
    # Nét chữ tạo cạnh hai phía; MaxFilter nối các nét cùng ký tự nhưng không
    # nối cả dòng như phép dilation lớn.
    edges = gray.filter(ImageFilter.FIND_EDGES)
    mask = edges.point(lambda value: 255 if value >= 42 else 0).filter(
        ImageFilter.MaxFilter(3)
    )
    # FIND_EDGES đánh sáng đường viền crop; xoá nó để không nối mọi glyph chạm
    # mép thành một component giả khổng lồ.
    draw = ImageDraw.Draw(mask)
    draw.rectangle((0, 0, mask.width - 1, mask.height - 1), outline=0, width=3)
    return mask


def scan_text_collision(
    image: Image.Image,
    bbox: tuple[int, int, int, int],
    *,
    min_aligned: int = 3,
) -> dict:
    """Phát hiện cụm nét giống chữ trong bbox nhỏ.

    Yêu cầu ít nhất ba component có chiều cao gần nhau và cùng hàng. Ảnh/photo
    ngẫu nhiên thường có cạnh lớn hoặc phân bố rải; chữ tạo nhiều glyph lặp.
    """
    left, top, right, bottom = bbox
    region = image.crop((left, top, right, bottom))
    region_w, region_h = region.size
    if region_w < 8 or region_h < 8:
        return {"detected": False, "component_count": 0, "bbox": list(bbox)}
    gray = region.convert("L")
    dark_pixels = sum(count for value, count in enumerate(gray.histogram()) if value < 145)
    dark_pixel_ratio = dark_pixels / max(region_w * region_h, 1)
    components = [
        item
        for item in _components(_contrast_mask(region))
        if 3 <= item.height <= region_h
        and 2 <= item.width <= max(round(region_w * 0.70), 2)
        and item.pixels >= 6
    ]
    best_line = 0
    for anchor in components:
        aligned = [
            item
            for item in components
            if abs(item.center_y - anchor.center_y)
            <= max(anchor.height, item.height) * 0.45
            and 0.35 <= item.height / max(anchor.height, 1) <= 2.8
        ]
        best_line = max(best_line, len(aligned))
    detected = best_line >= min_aligned or dark_pixel_ratio >= 0.025
    return {
        "detected": detected,
        "component_count": len(components),
        "aligned_component_count": best_line,
        "dark_pixel_ratio": round(dark_pixel_ratio, 6),
        "bbox": list(bbox),
    }


def _gold_mask(image: Image.Image) -> Image.Image:
    rgb = image.convert("RGB")
    mask = Image.new("L", rgb.size, 0)
    src = rgb.load()
    dst = mask.load()
    for y in range(rgb.height):
        for x in range(rgb.width):
            red, green, blue = src[x, y]
            # Gold/amber của theme và biến thiên do model sinh ảnh.
            if red >= 130 and red >= green * 1.12 and green >= blue * 1.18:
                dst[x, y] = 255
    return mask.filter(ImageFilter.MaxFilter(3))


def detect_ordinal_markers(image: Image.Image) -> dict:
    """Tìm chuỗi marker thứ tự thẳng cột mà không đọc toàn bộ văn bản.

    Marker phải là token đơn (không phải chuỗi số liệu), cao 2–10% chiều rộng
    ảnh, và có ít nhất ba token cùng cột/cùng cỡ. Detector ưu tiên false
    negative hơn false positive; kết quả dương tính khiến renderer retry, rồi
    NEEDS_HUMAN chứ không tự sửa nội dung.
    """
    width, height = image.size
    gold_mask = _gold_mask(image)
    all_components = _components(gold_mask, min_pixels=12)
    raw_candidates = [
        item
        for item in all_components
        if max(round(width * 0.035), 18) <= item.height <= round(width * 0.11)
        and item.width >= item.height * 0.18
        and item.width <= item.height * 1.45
        and item.pixels >= item.height * 1.2
        and item.pixels / max(item.width * item.height, 1) >= 0.35
    ]
    rail_sequences: list[list[Component]] = []
    for outer in all_components:
        outer_fill = outer.pixels / max(outer.width * outer.height, 1)
        if max(outer.width, outer.height) < width * 0.20 or outer_fill >= 0.30:
            continue
        enclosed = [
            item
            for item in raw_candidates
            if outer.left <= item.left
            and outer.top <= item.top
            and outer.right >= item.right
            and outer.bottom >= item.bottom
        ]
        if len(enclosed) >= 3:
            x_spread = max(item.center_x for item in enclosed) - min(
                item.center_x for item in enclosed
            )
            y_spread = max(item.center_y for item in enclosed) - min(
                item.center_y for item in enclosed
            )
            if x_spread <= width * 0.035:
                ordered = sorted(enclosed, key=lambda item: item.center_y)
                spaced = [
                    item
                    for index, item in enumerate(ordered)
                    if index == 0
                    or item.center_y - ordered[index - 1].center_y >= height * 0.05
                ]
                if len(spaced) >= 3:
                    rail_sequences.append(spaced)
            elif y_spread <= height * 0.035:
                ordered = sorted(enclosed, key=lambda item: item.center_x)
                spaced = [
                    item
                    for index, item in enumerate(ordered)
                    if index == 0
                    or item.center_x - ordered[index - 1].center_x >= width * 0.05
                ]
                if len(spaced) >= 3:
                    rail_sequences.append(spaced)
    circle_number_sequences: list[list[Component]] = []
    numbered_circles: list[tuple[Component, list[Component]]] = []
    for outer in all_components:
        outer_fill = outer.pixels / max(outer.width * outer.height, 1)
        if not (
            width * 0.05 <= outer.width <= width * 0.15
            and 0.75 <= outer.width / max(outer.height, 1) <= 1.30
            and outer_fill < 0.30
        ):
            continue
        inner = [
            item
            for item in raw_candidates
            if outer.left <= item.left
            and outer.top <= item.top
            and outer.right >= item.right
            and outer.bottom >= item.bottom
        ]
        # "01/02/03" có ít nhất hai glyph số; icon minh hoạ thường là một
        # component phức tạp và không được coi là ordinal chỉ vì nằm trong vòng.
        if len(inner) >= 2:
            numbered_circles.append((outer, inner))
    for outer, _inner in numbered_circles:
        peers = [
            pair
            for pair in numbered_circles
            if 0.70 <= pair[0].width / max(outer.width, 1) <= 1.40
            and (
                abs(pair[0].center_x - outer.center_x) <= width * 0.035
                or abs(pair[0].center_y - outer.center_y) <= height * 0.035
            )
        ]
        if len(peers) >= 3:
            flattened = [
                item
                for _peer_outer, peer_inner in peers
                for item in peer_inner
            ]
            circle_number_sequences.append(flattened)
    linked_circle_sequences: list[list[Component]] = []
    linked_markers = [
        item
        for item in all_components
        if width * 0.05 <= item.width <= width * 0.15
        and 1.30 <= item.height / max(item.width, 1) <= 2.10
        and item.pixels / max(item.width * item.height, 1) < 0.25
    ]
    for anchor in linked_markers:
        peers = sorted(
            [
                item
                for item in linked_markers
                if abs(item.center_x - anchor.center_x) <= width * 0.035
                and 0.65 <= item.width / max(anchor.width, 1) <= 1.45
            ],
            key=lambda item: item.center_y,
        )
        if len(peers) >= 3:
            linked_circle_sequences.append(peers)
    # White digits inside small solid-gold badges. The gold component itself
    # is almost a filled circle, so the older outline-circle branch cannot see
    # it. Require an enclosed narrow light glyph and a repeated aligned series;
    # plain decorative gold dots therefore do not qualify.
    filled_badges: list[Component] = []
    for outer in all_components:
        outer_fill = outer.pixels / max(outer.width * outer.height, 1)
        if not (
            width * 0.018 <= outer.width <= width * 0.060
            and 0.75 <= outer.width / max(outer.height, 1) <= 1.30
            and outer_fill >= 0.58
        ):
            continue
        inverse = ImageOps.invert(
            gold_mask.crop((outer.left, outer.top, outer.right, outer.bottom))
        )
        normalized = gold_mask.crop(
            (outer.left, outer.top, outer.right, outer.bottom)
        ).resize((24, 24), Image.Resampling.NEAREST)
        gold_pixels = {
            index
            for index, value in enumerate(normalized.get_flattened_data())
            if value >= 128
        }
        ideal_disk = {
            y * 24 + x
            for y in range(24)
            for x in range(24)
            if (x - 11.5) ** 2 + (y - 11.5) ** 2 <= 11.5**2
        }
        disk_iou = len(gold_pixels & ideal_disk) / max(
            len(gold_pixels | ideal_disk), 1
        )
        if disk_iou < 0.82:
            continue
        holes = [
            item
            for item in _components(inverse, min_pixels=2)
            if item.left > 0
            and item.top > 0
            and item.right < outer.width
            and item.bottom < outer.height
        ]
        if any(
            item.height >= outer.height * 0.12
            and item.width <= item.height * 0.85
            for item in holes
        ):
            filled_badges.append(outer)
    filled_circle_sequences: list[list[Component]] = []

    def _badge_shape_similarity(first: Component, second: Component) -> float:
        samples: list[set[int]] = []
        for item in (first, second):
            normalized = gold_mask.crop(
                (item.left, item.top, item.right, item.bottom)
            ).resize((24, 24), Image.Resampling.NEAREST)
            samples.append(
                {
                    index
                    for index, value in enumerate(
                        normalized.get_flattened_data()
                    )
                    if value >= 128
                }
            )
        union = samples[0] | samples[1]
        return len(samples[0] & samples[1]) / max(len(union), 1)

    for anchor in filled_badges:
        vertical = sorted(
            [
                item
                for item in filled_badges
                if abs(item.center_x - anchor.center_x) <= width * 0.020
                and 0.70 <= item.width / max(anchor.width, 1) <= 1.40
                and _badge_shape_similarity(anchor, item) >= 0.72
            ],
            key=lambda item: item.center_y,
        )
        horizontal = sorted(
            [
                item
                for item in filled_badges
                if abs(item.center_y - anchor.center_y) <= height * 0.020
                and 0.70 <= item.height / max(anchor.height, 1) <= 1.40
                and _badge_shape_similarity(anchor, item) >= 0.72
            ],
            key=lambda item: item.center_x,
        )
        for peers, axis in ((vertical, "y"), (horizontal, "x")):
            spaced: list[Component] = []
            for item in peers:
                center = item.center_y if axis == "y" else item.center_x
                previous = (
                    spaced[-1].center_y
                    if spaced and axis == "y"
                    else spaced[-1].center_x
                    if spaced
                    else None
                )
                if previous is None or center - previous >= min(
                    item.width, item.height
                ) * 1.15:
                    spaced.append(item)
            if len(spaced) >= 3:
                filled_circle_sequences.append(spaced)
    horizontal_token_sequences: list[list[Component]] = []
    token_rows: list[Component] = []
    # Plain digit glyphs produced by the model are compact/dense. Repeated
    # outline icons (folder, document, clipboard) can share the same row and
    # size, but their sparse strokes must not be mistaken for 01/02/03.
    horizontal_candidates = [
        item
        for item in raw_candidates
        if item.pixels / max(item.width * item.height, 1) >= 0.55
    ]
    for anchor in horizontal_candidates:
        row = sorted(
            [
                item
                for item in horizontal_candidates
                if abs(item.center_y - anchor.center_y)
                <= max(item.height, anchor.height) * 0.30
                and 0.80 <= item.height / max(anchor.height, 1) <= 1.25
            ],
            key=lambda item: item.left,
        )
        groups: list[list[Component]] = []
        for item in row:
            if (
                groups
                and item.left - groups[-1][-1].right
                <= max(item.height, groups[-1][-1].height) * 0.45
            ):
                groups[-1].append(item)
            else:
                groups.append([item])
        for group in groups:
            # Horizontal plain markers are reliable only in the 01/02/03 form.
            # A single glyph repeated across metric cards is usually the first
            # digit of a financial value, not an ordinal.
            if len(group) != 2:
                continue
            left = min(item.left for item in group)
            top = min(item.top for item in group)
            right = max(item.right for item in group)
            bottom = max(item.bottom for item in group)
            token = Component(
                left,
                top,
                right,
                bottom,
                sum(item.pixels for item in group),
            )
            if token.width <= token.height * 1.50:
                token_rows.append(token)
    unique_tokens: dict[tuple[int, int, int, int], Component] = {
        (item.left, item.top, item.right, item.bottom): item for item in token_rows
    }
    token_list = list(unique_tokens.values())
    for anchor in token_list:
        peers = sorted(
            [
                item
                for item in token_list
                if abs(item.center_y - anchor.center_y) <= height * 0.025
                and 0.80 <= item.height / max(anchor.height, 1) <= 1.25
            ],
            key=lambda item: item.center_x,
        )
        deduped: list[Component] = []
        for item in peers:
            if not deduped or item.left - deduped[-1].right >= width * 0.05:
                deduped.append(item)
        if len(deduped) >= 3:
            horizontal_token_sequences.append(deduped)
    components = [
        item
        for item in raw_candidates
        # Plain vertical ordinal glyphs are narrow. Near-square marks are
        # pictograms; circled/linked markers are handled by the branches above.
        if item.width <= item.height * 0.80
        # Without OCR, only a leading-edge plain glyph is reliable evidence of
        # an item ordinal. Aligned digits deeper inside cards are metric values.
        if item.center_x <= width * 0.15
        if not any(
            outer is not item
            and outer.left <= item.left
            and outer.top <= item.top
            and outer.right >= item.right
            and outer.bottom >= item.bottom
            and outer.width * outer.height >= item.width * item.height * 1.45
            and outer.pixels / max(outer.width * outer.height, 1) < 0.30
            for outer in all_components
        )
    ]
    sequences: list[list[Component]] = []
    for anchor in components:
        aligned = sorted(
            (
                item
                for item in components
                if abs(item.center_x - anchor.center_x) <= width * 0.035
                and 0.50 <= item.height / max(anchor.height, 1) <= 1.85
            ),
            key=lambda item: item.center_y,
        )
        deduped: list[Component] = []
        for item in aligned:
            if not deduped or item.center_y - deduped[-1].center_y >= min(
                item.height, deduped[-1].height
            ) * 0.75:
                deduped.append(item)
        gaps = [
            deduped[index].center_y - deduped[index - 1].center_y
            for index in range(1, len(deduped))
        ]
        # A real ordinal list has a repeated visual cadence.  Sparse metric
        # digits/icons can accidentally align at the leading edge, but their
        # row gaps vary widely (the observed false positives varied 3.6–12x).
        regularly_spaced = (
            len(gaps) >= 2
            and min(gaps) > 0
            and max(gaps) <= min(gaps) * 2.25
            and max(gaps)
            <= max(item.height for item in deduped) * 4.5
        )
        if len(deduped) >= 3 and regularly_spaced:
            sequences.append(deduped)
    best = max(
        sequences
        + rail_sequences
        + circle_number_sequences
        + linked_circle_sequences
        + filled_circle_sequences
        + horizontal_token_sequences,
        key=len,
        default=[],
    )
    return {
        "detected": len(best) >= 3,
        "candidate_count": len(components),
        "sequence_length": len(best),
        "marker_bboxes": [
            [item.left, item.top, item.right, item.bottom] for item in best
        ],
        "method": (
            "deterministic_gold_ordinal_rail"
            if best in rail_sequences
            else "deterministic_gold_ordinal_circles"
            if best in circle_number_sequences
            else "deterministic_gold_ordinal_linked_circles"
            if best in linked_circle_sequences
            else "deterministic_gold_ordinal_filled_circles"
            if best in filled_circle_sequences
            else "deterministic_gold_ordinal_horizontal_tokens"
            if best in horizontal_token_sequences
            else "deterministic_gold_ordinal_geometry"
        ),
    }


def content_has_explicit_ranking(spec: dict) -> bool:
    """Chỉ trường thứ hạng tường minh mới cho phép ordinal marker."""
    rank_keys = {"rank", "ranking", "position", "ordinal", "xep_hang", "thu_hang"}

    def visit(value) -> bool:
        if isinstance(value, dict):
            if any(str(key).casefold() in rank_keys for key in value):
                return True
            return any(visit(item) for item in value.values())
        if isinstance(value, list):
            return any(visit(item) for item in value)
        return False

    return visit(spec.get("content_units", spec))
