"""A/B voice_examples.md v1 vs v2 — biến số DUY NHẤT là bản voice-lock nạp vào
system prompt (v1: chỉ §1+§2+§3 + Ví dụ A, KHÔNG có §2b; v2: có §2b + Ví dụ D).
Cùng 1 context + evidence (dùng lại đúng bài SSI 8 cổ phiếu ở vòng A/B trước).
$0 (dùng LẠI content_llm hiện có, không thêm lệnh gọi API mới). KHÔNG đổi kiến
trúc/power_on.py.

docs/voice_examples.md KHÔNG có bản v1 lưu riêng (file untracked, không có lịch
sử git) -> tái dựng ĐÚNG điều kiện v1 bằng cách đọc CÙNG file v2 hiện tại nhưng
BỎ §2b (menu hook/luật chuyển ý) và ép ví dụ A thay vì D — xem _voice_v1_equivalent().

Chạy:
    python scripts/ab_voice2.py                       # tự lấy dòng Status=APPROVE đầu tiên trong CONTEXT
    python scripts/ab_voice2.py --slug "co-may-tang-truong-moi-cua-hoa-phat"

Idempotent: ghi ĐÈ cùng 1 file storage/ab/voice_ab2_<slug>.md mỗi lần chạy lại.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

from twmkt import factory  # noqa: E402
from twmkt.agents._jsonparse import try_json_object  # noqa: E402
from twmkt.agents.production import (  # noqa: E402
    AnalysisWriterAgent, ProductionBrief, analysis_fields_from_data,
    apply_guardrails, build_analysis_prompt, render_analysis,
)
from twmkt.agents.voice import _extract_example, _split_top_sections, assemble_voice  # noqa: E402
from twmkt.config import Settings, load_settings  # noqa: E402
from twmkt.models import ContentDraft, ContentFormat, Source  # noqa: E402

from ab_voice import pick_context  # noqa: E402  (tái dùng — cùng cách chọn dòng CONTEXT/slug)
from produce_from_sheet import _open_board, fetch_full_evidence  # noqa: E402


def _voice_v1_equivalent(settings: Settings) -> str:
    """Tái dựng ĐÚNG điều kiện voice-lock v1 (trước khi có §2b + Ví dụ D): §1+§2+§3
    + Ví dụ A, KHÔNG có §2b — đọc CÙNG file examples_path hiện tại, chỉ khác tập
    mục lấy ra (không sửa/không đụng agents/voice.py — v1 chỉ tồn tại cho A/B này)."""
    path = Path(settings.get("voice.examples_path", "docs/voice_examples.md"))
    text = path.read_text(encoding="utf-8")
    sections = _split_top_sections(text)
    parts = [sections[n] for n in ("1", "2", "3") if n in sections]   # KHÔNG lấy "2b"
    example = _extract_example(sections.get("5", ""), "A")
    if example:
        parts.append(example)
    return "\n\n---\n\n".join(parts)


def generate_article(brief: ProductionBrief, llm, *, voice_text: str) -> ContentDraft:
    """Sinh 1 bài article — CÙNG hệ thống với AnalysisWriterAgent.run(), chỉ khác
    ở chỗ voice_text truyền thẳng vào (thay vì luôn đọc settings.yaml thật) để
    A/B kiểm soát được biến v1/v2."""
    agent = AnalysisWriterAgent(llm)
    extra = f"\n\n---\n\nVOICE-LOCK (giọng văn bắt buộc):\n{voice_text}" if voice_text else ""
    data = try_json_object(agent._ask(build_analysis_prompt(brief), extra_system=extra))
    title, sapo, sections, disclaimer, sources = analysis_fields_from_data(data, brief)
    body = render_analysis(title, sapo, sections, disclaimer, sources, brief)
    return ContentDraft(fmt=ContentFormat.ARTICLE, title=title, body=body, brief_topic=brief.topic)


def run(*, slug: str | None = None) -> Path:
    settings = load_settings()
    board = _open_board(settings)
    approved = board.read_approved_context()
    item = pick_context(approved, slug)
    if item is None:
        raise SystemExit(
            f"Không tìm thấy dòng CONTEXT Status=APPROVE khớp slug={slug!r} "
            "(hoặc CONTEXT chưa có dòng APPROVE nào)."
        )

    sources = board.read_sources() or factory.build_sources(settings)
    html_collector = factory.build_collector_for_source(Source("_", "_", fetch_type="html"), settings)
    evidence = fetch_full_evidence(html_collector, sources, item["source"], item["hook"])
    brief = ProductionBrief(
        title=item["context"], hook=item["hook"], tickers=item["tickers"],
        group=item["group"], topic=item["topic"], url=item["source"], evidence=evidence,
    )
    from ab_voice import _slug
    item_slug = _slug(item["context"])

    voice_v1 = _voice_v1_equivalent(settings)
    voice_v2 = assemble_voice(None, settings=settings)   # v2 THẬT — đúng đường sống (fallback S1+H3+D)

    llm = factory.build_content_llm(settings)   # $0 nếu thiếu key (lùi mượt, không thêm lệnh gọi mới)

    v1 = apply_guardrails(generate_article(brief, llm, voice_text=voice_v1), brief.evidence, brief.background)
    v2 = apply_guardrails(generate_article(brief, llm, voice_text=voice_v2), brief.evidence, brief.background)

    out_dir = REPO_ROOT / "storage" / "ab"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"voice_ab2_{item_slug}.md"

    text = (
        f"# A/B voice_examples.md v1 vs v2 — {item['context']}\n\n"
        f"Nguồn: {item['source']}\n\n"
        "## v1\n\n"
        f"{v1.body}\n\n"
        "---\n\n"
        "## v2\n\n"
        f"{v2.body}\n"
    )
    out_path.write_text(text, encoding="utf-8")
    print(f"[ab-voice2] Đã ghi: {out_path}")
    return out_path


def _parse_args(argv: list[str]):
    import argparse
    ap = argparse.ArgumentParser(description="A/B voice_examples.md v1 vs v2, đúng 1 bài (article).")
    ap.add_argument("--slug", default=None,
                    help="Slug (từ Context) để chọn đúng dòng APPROVE; bỏ trống -> lấy dòng đầu tiên.")
    return ap.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    run(slug=args.slug)
