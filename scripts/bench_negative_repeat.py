"""Phase 3.1b.1/3.1b.3 — Lặp lại Brief trên bài ĐỐI CHỨNG ÂM `cang_bien_gdp` N
lần độc lập/model, đo TẦN SUẤT salience-miss cụ thể (Hải Phòng — địa điểm tổ
chức hội thảo — bị gán salience="subject" thay vì "context"). KHÔNG ghi Sheet.

Chạy SONG SONG (ThreadPoolExecutor) — mỗi lượt là 1 tiến trình `claude -p`
độc lập, không chia sẻ state, an toàn chạy đồng thời — giảm wall-clock đáng kể
so với chạy tuần tự (Phase 3.1 gốc).

Chạy:
    python scripts/bench_negative_repeat.py --models sonnet,opus --trials 5
    python scripts/bench_negative_repeat.py --models sonnet,opus --trials 5 --system-override /path/to/new_prompt.txt
"""
from __future__ import annotations

import json
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

from twmkt.agents.brief import _system_prompt, build_brief_prompt, facts_from_llm_output  # noqa: E402
from twmkt.config import load_settings  # noqa: E402

from bench_brief import MODELS, call_claude_cli  # noqa: E402
from golden_evidence import evidence_text_for_golden, load_golden_entries  # noqa: E402

SLUG = "cang_bien_gdp"
# Tín hiệu context CỤ THỂ đã xác nhận là ca thật (Phase 3.1b) — địa điểm tổ
# chức hội thảo, KHÔNG phải chủ thể bài báo. Mở rộng danh sách nếu phát hiện
# ca mới, nhưng KHÔNG đoán chung chung — mỗi mục phải có bằng chứng thật.
KNOWN_CONTEXT_SIGNALS = ("hải phòng",)


def _nfc_cf(s: str) -> str:
    return unicodedata.normalize("NFC", s or "").strip().casefold()


@dataclass
class Trial:
    model: str
    trial_no: int
    subject_entities: list[str] = field(default_factory=list)
    context_entities: list[str] = field(default_factory=list)
    miss_entities: list[str] = field(default_factory=list)   # KNOWN_CONTEXT_SIGNALS bị gán subject
    n_facts: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    error: str = ""


def run_trial(model: str, trial_no: int, evidence: str, system: str, timeout_s: float) -> Trial:
    prompt = build_brief_prompt(evidence)
    call = call_claude_cli(system, prompt, model, timeout_s=timeout_s)
    if call.error or not call.result:
        return Trial(model=model, trial_no=trial_no, error=call.error or "rỗng",
                    cost_usd=call.cost_usd, duration_ms=call.duration_ms)
    result = facts_from_llm_output(call.result, evidence)
    subject, context, miss = [], [], []
    for f in result.facts:
        names = [f.value] if f.shape == "entity" else (f.entities if f.shape == "entity_list" else [])
        for name in names:
            if not name:
                continue
            if f.salience == "subject":
                subject.append(name)
                if _nfc_cf(name) in KNOWN_CONTEXT_SIGNALS or any(
                        sig in _nfc_cf(name) for sig in KNOWN_CONTEXT_SIGNALS):
                    miss.append(name)
            elif f.salience == "context":
                context.append(name)
    return Trial(model=model, trial_no=trial_no, subject_entities=subject, context_entities=context,
                miss_entities=miss, n_facts=len(result.facts), cost_usd=call.cost_usd,
                duration_ms=call.duration_ms)


def main(models: list[str], trials: int, *, system_override: str | None = None) -> list[Trial]:
    settings = load_settings()
    evidence = evidence_text_for_golden(SLUG, settings)
    if not evidence:
        raise SystemExit(f"Thiếu evidence cho '{SLUG}' — chạy scripts/golden_evidence.py trước.")
    system = (system_override if system_override is not None else
             _system_prompt(settings.get("guardrail.entity_types") or None,
                            settings.get("guardrail.entity_salience") or None))
    timeout_s = max(360.0, float(settings.get("llm.claude_code.timeout_s", 240)))

    jobs = [(m, t) for m in models for t in range(1, trials + 1)]
    results: list[Trial] = []
    print(f"Chạy song song {len(jobs)} lượt ({trials} lượt × {len(models)} model)...")
    with ThreadPoolExecutor(max_workers=min(6, len(jobs))) as pool:
        futures = {pool.submit(run_trial, m, t, evidence, system, timeout_s): (m, t) for m, t in jobs}
        for fut in as_completed(futures):
            m, t = futures[fut]
            r = fut.result()
            results.append(r)
            print(f"[{m} #{t}] xong: subject={r.subject_entities} miss={r.miss_entities} "
                 f"n_facts={r.n_facts} ${r.cost_usd:.4f} {r.duration_ms}ms {r.error}")
    results.sort(key=lambda r: (r.model, r.trial_no))
    return results


def write_report(results: list[Trial], out_path: Path, *, label: str) -> None:
    lines = [f"# Phase 3.1b — Lặp lại bài đối chứng âm `{SLUG}` ({label})", "",
            f"Chạy: {datetime.now().isoformat(timespec='seconds')} · 0 lượt ghi Sheet.", "",
            f"Tín hiệu context đã xác nhận (Phase 3.1b): {', '.join(KNOWN_CONTEXT_SIGNALS)} "
            "(địa điểm tổ chức hội thảo — CHỈ đúng khi bị gán salience=\"subject\").", ""]

    lines.append("## Tần suất salience-miss / 5 lượt")
    lines.append("")
    lines.append("| Model | Miss / N lượt | Tỷ lệ | Chi tiết từng lượt |")
    lines.append("|---|---|---|---|")
    for model in MODELS:
        rows = [r for r in results if r.model == model]
        if not rows:
            continue
        n_miss = sum(1 for r in rows if r.miss_entities)
        n_err = sum(1 for r in rows if r.error)
        detail = "; ".join(
            f"#{r.trial_no}:{'MISS(' + ','.join(r.miss_entities) + ')' if r.miss_entities else ('lỗi' if r.error else 'sạch')}"
            for r in rows)
        lines.append(f"| **{model}** | {n_miss}/{len(rows)} (lỗi: {n_err}) | "
                     f"{n_miss/len(rows)*100:.0f}% | {detail} |")

    lines.append("")
    lines.append("## Chi tiết")
    lines.append("")
    lines.append("| Model | Lượt | subject | context | miss | n_facts | Cost | Latency |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in results:
        status = f" ⚠️{r.error}" if r.error else ""
        lines.append(f"| {r.model} | #{r.trial_no} | {', '.join(r.subject_entities) or '—'} | "
                     f"{', '.join(r.context_entities) or '—'} | {', '.join(r.miss_entities) or '—'} | "
                     f"{r.n_facts} | ${r.cost_usd:.4f} | {r.duration_ms/1000:.1f}s{status} |")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    models = list(MODELS[1:])   # mặc định sonnet+opus (bỏ haiku — Phase 3.1b chỉ định 2 model này)
    trials = 5
    system_override_path = None
    label = "prompt GỐC"
    for i, arg in enumerate(sys.argv):
        if arg == "--models" and i + 1 < len(sys.argv):
            models = [m.strip() for m in sys.argv[i + 1].split(",")]
        if arg == "--trials" and i + 1 < len(sys.argv):
            trials = int(sys.argv[i + 1])
        if arg == "--system-override" and i + 1 < len(sys.argv):
            system_override_path = sys.argv[i + 1]
        if arg == "--label" and i + 1 < len(sys.argv):
            label = sys.argv[i + 1]

    system_override = None
    if system_override_path:
        system_override = Path(system_override_path).read_text(encoding="utf-8")
        label = "prompt MỚI (siết salience)"

    results = main(models, trials, system_override=system_override)

    out_dir = REPO_ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    suffix = "before" if system_override is None else "after"
    out_path = out_dir / f"ab_brief_negative_repeat_{suffix}_{datetime.now().strftime('%Y%m%d')}.md"
    write_report(results, out_path, label=label)
    print(f"\n== Báo cáo: {out_path} ==")

    raw_path = out_dir / f"ab_brief_negative_repeat_{suffix}_{datetime.now().strftime('%Y%m%d')}_raw.json"
    raw_path.write_text(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"== Raw data: {raw_path} ==")
