import io

from PIL import Image, ImageDraw

from twmkt.config import Settings
from twmkt.render import ai_full as af
from twmkt.render import brand_stamp as bs
from twmkt.render import postflight as pf


def _png_bytes(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _small_settings(size: int = 400) -> Settings:
    return Settings(
        {
            "infographic": {
                "ai_full": {
                    "final_size": {"1:1": [size, size]},
                    "generation_size": {"1:1": [size, size]},
                }
            }
        }
    )


def test_text_collision_detects_text_but_not_blank_region():
    image = Image.new("RGB", (500, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.text((30, 80), "DU LIEU CUOI", font=bs._find_font(34, bold=True), fill="#09285B")
    assert pf.scan_text_collision(image, (0, 60, 500, 150))["detected"] is True
    assert pf.scan_text_collision(image, (0, 0, 500, 55))["detected"] is False


def test_ordinal_detector_finds_three_leading_gold_numbers():
    image = Image.new("RGB", (600, 800), "white")
    draw = ImageDraw.Draw(image)
    font = bs._find_font(64, bold=True)
    for index, y in enumerate((100, 280, 460), start=1):
        draw.text((40, y), str(index), font=font, fill="#C58A18")
        draw.text((130, y), f"NOI DUNG {index}", font=bs._find_font(28), fill="#09285B")
    result = pf.detect_ordinal_markers(image)
    assert result["detected"] is True
    assert result["sequence_length"] >= 3


def test_ordinal_detector_does_not_treat_stacked_outline_icons_as_ranking():
    image = Image.new("RGB", (600, 800), "white")
    draw = ImageDraw.Draw(image)
    for y in (100, 280, 460):
        draw.ellipse((35, y, 105, y + 70), outline="#C58A18", width=4)
        draw.line((55, y + 38, 68, y + 52, 90, y + 20), fill="#C58A18", width=5)
    assert pf.detect_ordinal_markers(image)["detected"] is False


def test_ordinal_detector_finds_circled_numbers_on_connected_timeline_rail():
    image = Image.new("RGB", (600, 800), "white")
    draw = ImageDraw.Draw(image)
    font = bs._find_font(42, bold=True)
    draw.line((125, 90, 125, 610), fill="#C58A18", width=3)
    for index, y in enumerate((110, 280, 450), start=1):
        draw.ellipse((35, y, 115, y + 80), outline="#C58A18", width=3)
        draw.line((115, y + 40, 125, y + 40), fill="#C58A18", width=3)
        draw.text((60, y + 13), str(index), font=font, fill="#C58A18")
    result = pf.detect_ordinal_markers(image)
    assert result["detected"] is True
    assert result["method"] == "deterministic_gold_ordinal_rail"


def test_ordinal_detector_does_not_split_digits_inside_one_number_on_rail():
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (250, 120, 570, 240),
        radius=12,
        outline="#C58A18",
        width=4,
    )
    draw.text(
        (330, 145),
        "1.378",
        font=bs._find_font(58, bold=True),
        fill="#C58A18",
    )
    assert pf.detect_ordinal_markers(image)["detected"] is False


def test_ordinal_detector_finds_horizontal_circled_two_digit_steps():
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    font = bs._find_font(42, bold=True)
    for index, x in enumerate((100, 300, 500), start=1):
        draw.ellipse((x, 125, x + 80, 205), outline="#C58A18", width=3)
        draw.text((x + 12, 138), f"0{index}", font=font, fill="#C58A18")
    result = pf.detect_ordinal_markers(image)
    assert result["detected"] is True
    assert result["method"] == "deterministic_gold_ordinal_circles"


def test_ordinal_detector_finds_vertical_linked_circle_markers():
    image = Image.new("RGB", (600, 800), "white")
    draw = ImageDraw.Draw(image)
    for y in (100, 300, 500):
        draw.ellipse((45, y, 125, y + 80), outline="#C58A18", width=3)
        draw.line((85, y + 80, 85, y + 125), fill="#C58A18", width=3)
    result = pf.detect_ordinal_markers(image)
    assert result["detected"] is True
    assert result["method"] == "deterministic_gold_ordinal_linked_circles"


def test_ordinal_detector_finds_white_numbers_in_filled_gold_badges():
    image = Image.new("RGB", (600, 800), "white")
    draw = ImageDraw.Draw(image)
    font = bs._find_font(16, bold=True)
    for index, y in enumerate((100, 180, 260, 340), start=1):
        draw.ellipse((45, y, 75, y + 30), fill="#C58A18")
        draw.text(
            (56, y + 6),
            str(index),
            font=font,
            fill="white",
            stroke_width=1,
            stroke_fill="white",
        )
    result = pf.detect_ordinal_markers(image)
    assert result["detected"] is True
    assert result["method"] == "deterministic_gold_ordinal_filled_circles"


def test_ordinal_detector_ignores_plain_filled_gold_dots():
    image = Image.new("RGB", (600, 800), "white")
    draw = ImageDraw.Draw(image)
    for y in (100, 180, 260, 340):
        draw.ellipse((45, y, 75, y + 30), fill="#C58A18")
    assert pf.detect_ordinal_markers(image)["detected"] is False


def test_ordinal_detector_finds_plain_horizontal_two_digit_steps():
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    font = bs._find_font(52, bold=True)
    for index, x in enumerate((80, 300, 520), start=1):
        draw.text((x, 150), f"0{index}", font=font, fill="#C58A18")
    result = pf.detect_ordinal_markers(image)
    assert result["detected"] is True
    assert result["method"] == "deterministic_gold_ordinal_horizontal_tokens"


def test_ordinal_detector_does_not_treat_horizontal_metric_prefixes_as_steps():
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    font = bs._find_font(52, bold=True)
    for value, x in zip(("1.511", "1.378", "57"), (80, 300, 520)):
        draw.text((x, 150), value, font=font, fill="#C58A18")
    assert pf.detect_ordinal_markers(image)["detected"] is False


def test_ordinal_detector_does_not_treat_horizontal_outline_icons_as_steps():
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    for x in (80, 300, 520):
        draw.rounded_rectangle(
            (x, 140, x + 64, 202),
            radius=10,
            outline="#C58A18",
            width=6,
        )
        draw.rectangle(
            (x + 16, 158, x + 48, 188),
            outline="#C58A18",
            width=5,
        )
    assert pf.detect_ordinal_markers(image)["detected"] is False


def test_ordinal_detector_does_not_treat_vertical_filled_icons_as_ranking():
    image = Image.new("RGB", (600, 800), "white")
    draw = ImageDraw.Draw(image)
    for y in (100, 300, 500):
        draw.rounded_rectangle(
            (38, y, 112, y + 74),
            radius=16,
            fill="#C58A18",
        )
        draw.rectangle((58, y + 18, 92, y + 56), fill="white")
    assert pf.detect_ordinal_markers(image)["detected"] is False


def test_ordinal_detector_does_not_treat_aligned_metric_digits_as_ranking():
    image = Image.new("RGB", (800, 800), "white")
    draw = ImageDraw.Draw(image)
    font = bs._find_font(64, bold=True)
    for value, y in zip(("9.670", "1.106", "804"), (100, 300, 500)):
        draw.text((190, y), value, font=font, fill="#C58A18")
    assert pf.detect_ordinal_markers(image)["detected"] is False


def test_ordinal_detector_ignores_irregular_leading_metric_fragments():
    image = Image.new("RGB", (1152, 2048), "white")
    draw = ImageDraw.Draw(image)
    font = bs._find_font(54, bold=True)
    for value, x, y in (
        ("9", 121, 816),
        ("1", 141, 1186),
        ("8", 102, 1290),
        ("2", 103, 1402),
    ):
        draw.text((x, y), value, font=font, fill="#C58A18")
    assert pf.detect_ordinal_markers(image)["detected"] is False


def test_content_has_explicit_ranking_only_for_rank_fields():
    assert pf.content_has_explicit_ranking(
        {"content_units": [{"type": "entity", "rank": 1}]}
    )
    assert not pf.content_has_explicit_ranking(
        {"content_units": [{"type": "timeline", "order": 1}]}
    )


def test_metadata_collision_extends_canvas_instead_of_covering_text():
    image = Image.new("RGB", (400, 400), "white")
    ImageDraw.Draw(image).text(
        (20, 360),
        "DU LIEU CUOI",
        font=bs._find_font(28, bold=True),
        fill="#09285B",
    )
    stamped, log = bs.overlay_brand_full_canvas(
        _png_bytes(image),
        ratio="1:1",
        theme="bright",
        source="Test",
        disclaimer="Thong tin tham khao.",
        logo_path="missing-logo.png",
        settings=_small_settings(),
    )
    assert log["metadata_guardrail"] == "PASS_EXTENDED"
    assert log["metadata_extended"] is True
    assert log["final_wh"][1] > log["content_wh"][1]
    assert Image.open(io.BytesIO(stamped)).height == log["final_wh"][1]


def test_logo_moves_to_top_left_when_right_bbox_contains_text(tmp_path):
    image = Image.new("RGB", (400, 400), "white")
    ImageDraw.Draw(image).text(
        (315, 20), "ABC", font=bs._find_font(34, bold=True), fill="#09285B"
    )
    logo = Image.new("RGBA", (80, 40), (10, 40, 90, 255))
    logo_path = tmp_path / "logo.png"
    logo.save(logo_path)
    _, log = bs.overlay_brand_full_canvas(
        _png_bytes(image),
        ratio="1:1",
        theme="bright",
        logo_path=logo_path,
        settings=_small_settings(1080),
    )
    right_candidate = next(c for c in log["logo_corner_candidates"] if c["corner"] == "top_right")
    assert right_candidate["detected"] is True
    assert log["logo_position"] == "top_left"
    assert log["logo_bbox"][0] < 400 / 2


def test_qualitative_process_prompt_keeps_photo_anchor():
    spec = {
        "title": "Quy trinh",
        "content_units": [
            {"type": "process", "text": "Buoc A"},
            {"type": "timeline", "text": "Buoc B"},
        ],
    }
    prompt = af.build_ai_full_prompt(spec, theme="bright", ratio="4:5")
    assert "process/timeline" in prompt
    assert "Ảnh chụp vẫn là neo thị giác" in prompt
    assert "sơ đồ bước chỉ là lớp thông tin" in prompt


def test_ranking_guardrail_retries_once_then_exports(monkeypatch, tmp_path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.new("RGB", (400, 400), "white").save(first)
    Image.new("RGB", (400, 400), "white").save(second)

    def fake_generate(*args, postflight_instruction="", **kwargs):
        return (second if postflight_instruction else first), ""

    scans = iter(
        [
            {"detected": True, "marker_bboxes": [[1, 1, 2, 2]]},
            {"detected": False, "marker_bboxes": []},
        ]
    )
    monkeypatch.setattr(af, "get_or_generate_raw_image", fake_generate)
    monkeypatch.setattr(pf, "detect_ordinal_markers", lambda image: next(scans))
    results, logs = af.render_ai_full(
        {"title": "Test", "source": "Test"},
        theme="bright",
        ratios=("1:1",),
        settings=_small_settings(1080),
    )
    assert results["1:1"][0] is not None
    assert logs["1:1"]["ranking_attempts"] == 2
    assert logs["1:1"]["postflight_status"] == "PASS"


def test_ranking_guardrail_needs_human_after_second_failure(monkeypatch, tmp_path):
    raw = tmp_path / "raw.png"
    Image.new("RGB", (400, 400), "white").save(raw)
    monkeypatch.setattr(
        af, "get_or_generate_raw_image", lambda *args, **kwargs: (raw, "")
    )
    monkeypatch.setattr(
        pf,
        "detect_ordinal_markers",
        lambda image: {"detected": True, "marker_bboxes": [[1, 1, 2, 2]]},
    )
    results, logs = af.render_ai_full(
        {"title": "Test", "source": "Test"},
        theme="bright",
        ratios=("1:1",),
        settings=_small_settings(1080),
    )
    assert results["1:1"][0] is None
    assert "NEEDS_HUMAN" in results["1:1"][1]
    assert logs["1:1"]["ranking_attempts"] == 2
