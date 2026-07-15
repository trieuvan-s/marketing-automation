"""Phase 3.2 — A/B WRITER: Sonnet · Opus. Cố định facts[] (Brief model tốt
nhất theo Phase 3.1b — Opus, prompt đã siết salience) + RouterDecision (route
1 lần, dùng CHUNG cho cả 2 nhánh) — BIẾN DUY NHẤT là model sinh bài phân
tích/video/infographic. KHÔNG ghi Sheet.

CODE đo: guardrail violations (compliance.check + unsupported_numbers) · độ
phủ 8-trường infographic · brand (FVA Capital + disclaimer NGUYÊN VĂN) ·
alias/viết tắt lọt vào voice_text (kiểm thêm, heuristic — xem ghi chú cuối
báo cáo). NGƯỜI đo: "có hồn" — xem file .md xuất ra, code KHÔNG chấm được.

Chạy:
    python scripts/bench_writer.py --slugs 4_cang_bien_dac_biet,cong_ty_lo_q2,vietnam_airlines_co_dong
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

from twmkt.agents.base import ClaudeCodeLLM  # noqa: E402
from twmkt.agents.brief import run_brief  # noqa: E402
from twmkt.agents.production import (  # noqa: E402
    InfographicSpecAgent, ProductionBrief, VideoScriptAgent, _default_cta,
    _default_disclaimer, apply_guardrails,
)
from twmkt.agents.route_once import RouterDecisionStore, get_or_route  # noqa: E402
from twmkt.agents.writer import run_writer_with_retry  # noqa: E402
from twmkt.config import load_settings  # noqa: E402

from golden_evidence import evidence_text_for_golden, load_golden_entries  # noqa: E402

BRIEF_MODEL = "opus"       # Phase 3.1b: best precision/shape/salience, prompt đã siết
ROUTER_MODEL = "haiku"     # khớp llm.step_models.router thật trong settings.yaml
WRITER_MODELS = ("sonnet", "opus")
_DISCLAIMER = _default_disclaimer()
_BRAND_TOKEN = "FVA Capital"

_VN_ABBREV_PAIRS = [
    ("khu công nghiệp", "KCN"), ("công ty cổ phần", "CTCP"),
    ("trách nhiệm hữu hạn", "TNHH"), ("ủy ban nhân dân", "UBND"),
    ("hội đồng quản trị", "HĐQT"),
]


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")


def _extract_voiceover_lines(video_body: str) -> str:
    """render_video(): mỗi cảnh in "[t] voiceover" (bracket bắt đầu bằng chữ
    số, vd "[0-3s]") — TÁCH khỏi dòng "[CTA] ..." (bracket chữ) và "On-screen:
    "/"Hình ảnh:" (thụt 2 khoảng trắng, không bracket) để chỉ lấy lời thoại
    THẬT sẽ được đọc lên (TTS), không lẫn chữ hiển thị trên màn hình."""
    lines = re.findall(r"^\[\d[^\]]*\]\s+(.+)$", video_body, re.MULTILINE)
    return "\n".join(lines)


def _check_voice_aliases(voice_text: str, tickers: list[str]) -> list[str]:
    """Heuristic — KHÔNG đầy đủ/NLP, chỉ bắt các mẫu viết tắt tiếng Việt phổ
    biến ĐÃ BIẾT (cùng tinh thần luật đã chốt: slots/on-screen được alias
    ngắn, voice_text phải đầy đủ để TTS đọc tự nhiên) + mã CK trần không kèm
    tên công ty."""
    issues = []
    low = _nfc(voice_text).lower()
    for full, abbr in _VN_ABBREV_PAIRS:
        if re.search(rf"\b{re.escape(abbr.lower())}\b", low) and full not in low:
            issues.append(f"'{abbr}' (viết tắt '{full}') xuất hiện trong voice_text, "
                         f"KHÔNG thấy dạng đầy đủ ở đâu trong lời thoại")
    for t in tickers:
        if t and re.search(rf"\b{re.escape(t)}\b", voice_text):
            issues.append(f"mã '{t}' xuất hiện trần trong voice_text (không kèm tên công ty)")
    return issues


_INFOGRAPHIC_FIELDS = ("title", "subtitle", "hero", "market", "highlights", "related", "priority", "source")


def _check_8_field_coverage(spec: dict) -> dict:
    out = {}
    for f in _INFOGRAPHIC_FIELDS:
        v = spec.get(f)
        if f == "priority":
            filled = bool(v) and any((v or {}).get(k) for k in ("primary", "secondary", "minor"))
        elif f == "related":
            filled = bool(v)   # rỗng CÓ THỂ hợp lệ (không có entity salience=subject) — báo riêng, không tự kết luận thiếu
        else:
            filled = bool(v)
        out[f] = filled
    return out


@dataclass
class WriterTrial:
    slug: str
    model: str
    article_outcome: str = ""
    article_violations: int = 0
    article_violation_detail: list[str] = field(default_factory=list)
    article_has_brand: bool = False
    article_disclaimer_exact: bool = False
    video_violations: int = 0
    video_violation_detail: list[str] = field(default_factory=list)
    video_disclaimer_exact: bool = False
    video_alias_issues: list[str] = field(default_factory=list)
    infographic_violations: int = 0
    infographic_violation_detail: list[str] = field(default_factory=list)
    infographic_field_coverage: dict = field(default_factory=dict)
    article_path: str = ""
    video_path: str = ""
    infographic_path: str = ""
    error: str = ""


def prepare_brief_and_decision(slug: str, settings) -> ProductionBrief:
    """Phase A — Brief (model tốt nhất, cố định) + route 1 lần -> đóng băng
    RouterDecision NGAY TRÊN brief (gắn `_decision` để Phase B tái dùng,
    KHÔNG route lại) — CHẠY SONG SONG qua các bài (độc lập hoàn toàn)."""
    entry_map = {e.slug: e for e in load_golden_entries()}
    entry = entry_map[slug]
    title = str(entry.raw.get("title") or entry.slug)
    evidence = evidence_text_for_golden(slug, settings)
    if not evidence:
        raise SystemExit(f"Thiếu evidence cho '{slug}' — chạy scripts/golden_evidence.py trước.")

    route_llm = ClaudeCodeLLM(timeout_s=360.0)
    brief_result = run_brief(route_llm, evidence, model=BRIEF_MODEL, settings=settings)
    tickers = sorted({f.value for f in brief_result.facts if f.shape == "entity" and f.entity_type == "ticker"})
    brief = ProductionBrief(title=title, hook=title, tickers=tickers, url=entry.url,
                            evidence=evidence, facts=brief_result.facts,
                            no_numeric_content=brief_result.no_numeric_content)

    decisions_path = Path(tempfile.mkdtemp()) / "router_decisions.json"
    router_store = RouterDecisionStore(decisions_path)
    decision = get_or_route(route_llm, brief, store=router_store, key=slug, model=ROUTER_MODEL)
    brief._decision = decision   # gắn tạm để Phase B đọc lại (không phải field chính thức)
    print(f"[{slug}] Brief+Router xong: {len(brief.facts)} facts, structure={decision.structure}")
    return brief


def run_writer_branch(slug: str, model: str, brief: ProductionBrief, decision, settings, out_dir: Path) -> WriterTrial:
    """Phase B — 1 NHÁNH (bài × model): article + video + infographic. CHẠY
    SONG SONG qua mọi nhánh (Brief/RouterDecision ĐÃ CỐ ĐỊNH từ Phase A, mỗi
    nhánh dùng LLM client RIÊNG — an toàn đồng thời, không share state)."""
    writer_llm = ClaudeCodeLLM(timeout_s=360.0)
    t = WriterTrial(slug=slug, model=model)
    try:
        wr = run_writer_with_retry(writer_llm, brief, decision, settings=settings, model=model)
        t.article_outcome = wr.outcome.value
        if wr.draft:
            t.article_violations = len(wr.draft.compliance_issues)
            t.article_violation_detail = list(wr.draft.compliance_issues)
            t.article_has_brand = _BRAND_TOKEN.lower() in wr.draft.body.lower()
            t.article_disclaimer_exact = _DISCLAIMER in wr.draft.body
            fn = out_dir / f"{slug}-{model}-article.md"
            fn.write_text(wr.draft.body, encoding="utf-8")
            t.article_path = str(fn)

        video_agent = VideoScriptAgent(writer_llm, model=model)
        video_draft = video_agent.run(brief, decision)
        video_draft = apply_guardrails(video_draft, brief.evidence, brief.background, brief.facts)
        t.video_violations = len(video_draft.compliance_issues)
        t.video_violation_detail = list(video_draft.compliance_issues)
        t.video_disclaimer_exact = _DISCLAIMER in video_draft.body
        voice_text = _extract_voiceover_lines(video_draft.body)
        t.video_alias_issues = _check_voice_aliases(voice_text, brief.tickers)
        fn = out_dir / f"{slug}-{model}-video.md"
        fn.write_text(video_draft.body, encoding="utf-8")
        t.video_path = str(fn)

        info_agent = InfographicSpecAgent(writer_llm, model=model)
        info_draft = info_agent.run(brief, decision)
        info_draft = apply_guardrails(info_draft, brief.evidence, brief.background, brief.facts)
        t.infographic_violations = len(info_draft.compliance_issues)
        t.infographic_violation_detail = list(info_draft.compliance_issues)
        try:
            spec = json.loads(info_draft.body)
            t.infographic_field_coverage = _check_8_field_coverage(spec)
        except json.JSONDecodeError:
            t.infographic_field_coverage = {}
            t.error = "infographic JSON không parse được"
        fn = out_dir / f"{slug}-{model}-infographic.json"
        fn.write_text(info_draft.body, encoding="utf-8")
        t.infographic_path = str(fn)
    except Exception as e:  # noqa: BLE001 - benchmark: ghi lỗi, KHÔNG crash cả batch
        t.error = f"{type(e).__name__}: {e}"
    print(f"[{slug}][{model}] article={t.article_outcome}({t.article_violations}) "
         f"video_viol={t.video_violations} info_viol={t.infographic_violations} "
         f"alias_issues={len(t.video_alias_issues)} err={t.error}")
    return t


def write_report(all_trials: list[WriterTrial], out_dir: Path, out_path: Path) -> None:
    lines = ["# Phase 3.2 — A/B Writer: Sonnet · Opus", "",
            f"Chạy: {datetime.now().isoformat(timespec='seconds')} · 0 lượt ghi Sheet · "
            f"facts[] cố định (Brief model={BRIEF_MODEL}, prompt đã siết salience Phase 3.1b) · "
            f"RouterDecision cố định (route 1 lần/bài, model={ROUTER_MODEL}) · "
            "BIẾN DUY NHẤT = model Writer/Composer.", ""]

    lines.append("## Bảng đo bằng CODE (guardrail/8-field/brand/alias)")
    lines.append("")
    lines.append("| Bài | Model | Article outcome | Article viol. | Video viol. | Infographic viol. | "
                 "8-field đủ | related rỗng? | Brand FVA | Disclaimer nguyên văn (article/video) | Alias issues |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for t in all_trials:
        cov = t.infographic_field_coverage
        n_filled = sum(1 for f in _INFOGRAPHIC_FIELDS if cov.get(f))
        related_empty = "rỗng" if cov and not cov.get("related") else ("có" if cov else "?")
        disc = f"{'✓' if t.article_disclaimer_exact else '✗'}/{'✓' if t.video_disclaimer_exact else '✗'}"
        status = f" ⚠️{t.error}" if t.error else ""
        lines.append(f"| {t.slug} | **{t.model}** | {t.article_outcome} | {t.article_violations} | "
                     f"{t.video_violations} | {t.infographic_violations} | {n_filled}/8 | {related_empty} | "
                     f"{'✓' if t.article_has_brand else '✗'} | {disc} | "
                     f"{len(t.video_alias_issues)}{status} |")

    lines.append("")
    lines.append("### Chi tiết vi phạm / alias (nếu có)")
    lines.append("")
    for t in all_trials:
        any_detail = t.article_violation_detail or t.video_violation_detail or t.infographic_violation_detail or t.video_alias_issues
        if not any_detail:
            continue
        lines.append(f"**{t.slug} / {t.model}**")
        for d in t.article_violation_detail:
            lines.append(f"- [article guardrail] {d}")
        for d in t.video_violation_detail:
            lines.append(f"- [video guardrail] {d}")
        for d in t.infographic_violation_detail:
            lines.append(f"- [infographic guardrail] {d}")
        for d in t.video_alias_issues:
            lines.append(f"- [alias voice_text] {d}")
        lines.append("")

    lines.append("## File để NGƯỜI đọc chấm \"có hồn\" (code KHÔNG chấm được phần này)")
    lines.append("")
    for t in all_trials:
        lines.append(f"- **{t.slug} / {t.model}**: [article]({Path(t.article_path).name}) · "
                     f"[video]({Path(t.video_path).name}) · [infographic]({Path(t.infographic_path).name})")

    lines.append("")
    lines.append("## Ghi chú")
    lines.append("- `related rỗng` không tự động là lỗi — HỢP LỆ nếu facts[] không có entity/entity_list "
                 "salience=\"subject\" nào (xem cột riêng để tự đối chiếu, không gộp vào \"8-field đủ\").")
    lines.append("- Alias/viết tắt trong voice_text: heuristic có chủ đích hẹp (danh sách viết tắt tiếng Việt "
                 "phổ biến đã biết + mã CK trần) — KHÔNG phải NLP tổng quát, có thể bỏ sót ca khác.")
    lines.append(f"- Disclaimer chuẩn đối chiếu: \"{_DISCLAIMER}\"")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    from concurrent.futures import ThreadPoolExecutor, as_completed

    slugs = ["4_cang_bien_dac_biet", "cong_ty_lo_q2", "vietnam_airlines_co_dong"]
    for i, arg in enumerate(sys.argv):
        if arg == "--slugs" and i + 1 < len(sys.argv):
            slugs = [s.strip() for s in sys.argv[i + 1].split(",")]

    settings = load_settings()
    out_dir = REPO_ROOT / "reports" / f"ab_writer_{datetime.now().strftime('%Y%m%d')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"== Phase A: Brief+Router song song cho {len(slugs)} bài ==")
    briefs: dict[str, ProductionBrief] = {}
    with ThreadPoolExecutor(max_workers=len(slugs)) as pool:
        futures = {pool.submit(prepare_brief_and_decision, s, settings): s for s in slugs}
        for fut in as_completed(futures):
            s = futures[fut]
            briefs[s] = fut.result()

    print(f"== Phase B: {len(slugs)}x{len(WRITER_MODELS)} nhánh Writer song song ==")
    all_trials: list[WriterTrial] = []
    jobs = [(s, m) for s in slugs for m in WRITER_MODELS]
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {pool.submit(run_writer_branch, s, m, briefs[s], briefs[s]._decision,
                               settings, out_dir): (s, m) for s, m in jobs}
        for fut in as_completed(futures):
            all_trials.append(fut.result())

    all_trials.sort(key=lambda t: (t.slug, t.model))
    out_path = REPO_ROOT / "reports" / f"ab_writer_{datetime.now().strftime('%Y%m%d')}.md"
    write_report(all_trials, out_dir, out_path)
    print(f"\n== Báo cáo: {out_path} ==")
    print(f"== File bài viết: {out_dir} ==")

    raw_path = REPO_ROOT / "reports" / f"ab_writer_{datetime.now().strftime('%Y%m%d')}_raw.json"
    raw_path.write_text(json.dumps([asdict(t) for t in all_trials], ensure_ascii=False, indent=2), encoding="utf-8")
