"""A/B voice-lock — sinh CÙNG 1 bài article HAI lần (baseline vs voice-lock),
biến số DUY NHẤT là voice-lock, để người dùng chấm giọng văn. $0 (dùng LẠI
content_llm hiện có — KHÔNG thêm lệnh gọi API mới; nếu chưa có ANTHROPIC_API_KEY,
content_llm lùi mượt về khung tất định như mọi luồng khác trong repo).

Chạy:
    python scripts/ab_voice.py                       # tự lấy dòng Status=APPROVE đầu tiên trong CONTEXT
    python scripts/ab_voice.py --slug "co-may-tang-truong-moi-cua-hoa-phat"

Idempotent: ghi ĐÈ cùng 1 file <data_root>/ab/voice_ab_<slug>.md mỗi lần chạy lại
(không tích file rác). KHÔNG đụng power_on.py/CONTENT — chỉ đọc CONTEXT (APPROVE)
để lấy context/evidence, không ghi gì lên Sheet.
"""
from __future__ import annotations

import copy
import re
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
from twmkt.agents.voice import assemble_voice  # noqa: E402
from twmkt.config import Settings, data_path, load_settings  # noqa: E402
from twmkt.models import ContentDraft, ContentFormat, Source  # noqa: E402
from twmkt.sheets_board import SheetsBoard  # noqa: E402

from produce_from_sheet import _open_board, fetch_full_evidence  # noqa: E402


def _slug(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    s = re.sub(r"[\s_-]+", "-", s)
    return s[:60] or "bai-viet"


def pick_context(approved: list[dict], slug: str | None) -> dict | None:
    """`slug` khớp -> đúng dòng đó; rỗng -> dòng Status=APPROVE ĐẦU TIÊN. Hàm
    THUẦN (không mạng) — test được độc lập."""
    if not approved:
        return None
    if not slug:
        return approved[0]
    for a in approved:
        if _slug(a["context"]) == slug:
            return a
    return None


def _settings_with_voice(base: Settings, *, enabled: bool) -> Settings:
    """Bản sao Settings CHỈ khác `voice.enabled` — biến số DUY NHẤT giữa 2 lần
    sinh. Không đụng file settings.yaml thật."""
    data = copy.deepcopy(base.raw)
    data.setdefault("voice", {})["enabled"] = enabled
    return Settings(data)


def generate_article(brief: ProductionBrief, llm, *, voice_settings: Settings) -> ContentDraft:
    """Sinh 1 bài article — CÙNG hệ thống với AnalysisWriterAgent.run(), chỉ khác
    ở chỗ voice-lock lấy từ `voice_settings` truyền vào (thay vì luôn đọc
    settings.yaml thật) để A/B kiểm soát được biến bật/tắt."""
    agent = AnalysisWriterAgent(llm)
    voice = assemble_voice(None, settings=voice_settings)
    extra = f"\n\n---\n\nVOICE-LOCK (giọng văn bắt buộc):\n{voice}" if voice else ""
    data = try_json_object(agent._ask(build_analysis_prompt(brief), extra_system=extra))
    title, sapo, sections, disclaimer, sources = analysis_fields_from_data(data, brief)
    body = render_analysis(title, sapo, sections, disclaimer, sources, brief)
    return ContentDraft(fmt=ContentFormat.ARTICLE, title=title, body=body, brief_topic=brief.topic)


def _diff_notes(baseline: ContentDraft, voicelock: ContentDraft) -> list[str]:
    """5 dòng nhận xét THUẦN (không LLM) — so khác biệt QUAN SÁT ĐƯỢC, không suy
    diễn ý nghĩa. Dùng khi 2 bản GIỐNG HỆT (Mock/fallback) để báo rõ lý do."""
    if baseline.body == voicelock.body:
        return [
            "- Hai bản GIỐNG HỆT nhau — hiện KHÔNG có ANTHROPIC_API_KEY nên "
            "content_llm lùi mượt về khung tất định (không đọc system prompt).",
            "- Khung tất định (analysis_fields_from_data khi data=None) không phụ "
            "thuộc voice-lock -> A/B chỉ có ý nghĩa khi có LLM thật sinh văn xuôi.",
            "- Mở bài: giống nhau (cùng lấy brief.hook/brief.title).",
            "- Điểm chạm: giống nhau (cùng dựng từ evidence/background tất định).",
            "- Kết mở: giống nhau (cùng disclaimer/CTA tất định).",
        ]
    return [
        f"- Mở bài: {'khác' if baseline.body.splitlines()[:3] != voicelock.body.splitlines()[:3] else 'giống'} "
        "(so 3 dòng đầu).",
        f"- Độ dài: baseline {len(baseline.body)} ký tự vs voice-lock {len(voicelock.body)} ký tự.",
        f"- Tiêu đề: {'khác' if baseline.title != voicelock.title else 'giống'} "
        f"({baseline.title!r} vs {voicelock.title!r}).",
        "- Điểm chạm: xem phần thân — voice-lock kỳ vọng có ẩn dụ đời thường/câu hỏi "
        "thật (§1-§2 voice_examples.md), baseline thì không.",
        f"- Kết mở: {'khác' if baseline.body.splitlines()[-3:] != voicelock.body.splitlines()[-3:] else 'giống'} "
        "(so 3 dòng cuối).",
    ]


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
    item_slug = _slug(item["context"])

    llm = factory.build_content_llm(settings)   # $0 nếu thiếu key (lùi mượt, không thêm lệnh gọi mới)

    baseline = apply_guardrails(
        generate_article(brief, llm, voice_settings=_settings_with_voice(settings, enabled=False)),
        brief.evidence, brief.background)
    voicelock = apply_guardrails(
        generate_article(brief, llm, voice_settings=_settings_with_voice(settings, enabled=True)),
        brief.evidence, brief.background)

    out_dir = data_path("ab", settings=settings)
    out_path = out_dir / f"voice_ab_{item_slug}.md"

    notes = "\n".join(_diff_notes(baseline, voicelock))
    text = (
        f"# A/B voice-lock — {item['context']}\n\n"
        f"Nguồn: {item['source']}\n\n"
        "## BASELINE (chưa voice-lock)\n\n"
        f"{baseline.body}\n\n"
        "---\n\n"
        "## VOICE-LOCK\n\n"
        f"{voicelock.body}\n\n"
        "---\n\n"
        "## Khác gì (5 dòng)\n\n"
        f"{notes}\n"
    )
    out_path.write_text(text, encoding="utf-8")
    print(f"[ab-voice] Đã ghi: {out_path}")
    return out_path


def _parse_args(argv: list[str]):
    import argparse
    ap = argparse.ArgumentParser(description="A/B voice-lock đúng 1 bài (article).")
    ap.add_argument("--slug", default=None,
                    help="Slug (từ Context) để chọn đúng dòng APPROVE; bỏ trống -> lấy dòng đầu tiên.")
    return ap.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    run(slug=args.slug)
