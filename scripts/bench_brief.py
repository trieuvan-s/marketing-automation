"""Phase 3.1 — A/B BRIEF: Haiku · Sonnet · Opus trên golden set (6 bài, 5
DƯƠNG + 1 ĐỐI CHỨNG ÂM `cang_bien_gdp`). KHÔNG ghi Sheet lượt nào.

Gọi THẲNG `claude -p --output-format json` (không qua ClaudeCodeLLM.complete()
— hàm đó chỉ trích "result", bỏ qua "usage"/"total_cost_usd"/"duration_ms" mà
benchmark cần) nhưng TÁI DÙNG NGUYÊN parser thật của Brief
(agents.brief.facts_from_llm_output/build_brief_prompt/_system_prompt) — điểm
số phản ánh ĐÚNG hành vi production, không phải 1 bản mô phỏng riêng.

6 chỉ số/bài×model: recall · precision · shape coverage · salience accuracy ·
source_sentence hợp lệ (code verify, NFC) · chi phí thật + độ trễ.

Bài ĐỐI CHỨNG ÂM (`cang_bien_gdp`, KHÔNG có tên cảng nào — related=[] ĐÚNG)
CHỈ chấm PRECISION + cờ "bịa tên cảng" (đo kiềm chế được không) — KHÔNG hoà
vào điểm trung bình 5 bài dương (đo recall/precision/shape/salience).

Chạy:
    python scripts/bench_brief.py                    # cả 3 model, cả 6 bài
    python scripts/bench_brief.py --models haiku      # 1 model để thử nhanh
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

from twmkt.agents._jsonparse import try_json_object  # noqa: E402
from twmkt.agents._numeric import parse_magnitude_token  # noqa: E402
from twmkt.agents.brief import _system_prompt, build_brief_prompt, facts_from_llm_output  # noqa: E402
from twmkt.config import load_settings  # noqa: E402
from twmkt.models import FACT_SHAPES, Fact  # noqa: E402

from golden_evidence import load_golden_entries, evidence_text_for_golden  # noqa: E402

MODELS = ("haiku", "sonnet", "opus")
NEGATIVE_SLUG = "cang_bien_gdp"   # đối chứng ÂM — KHÔNG có tên cảng nào, related=[] ĐÚNG


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s or "").strip().casefold()


def _num(value: str, unit: str | None) -> float | None:
    try:
        return parse_magnitude_token(f"{value}{unit or ''}")
    except Exception:
        return None


# ---- gọi CLI thẳng (giữ nguyên usage/cost/duration mà ClaudeCodeLLM.complete() bỏ qua) ----
@dataclass
class RawCall:
    result: str
    in_tokens: int
    out_tokens: int
    cost_usd: float
    duration_ms: int
    error: str = ""


def call_claude_cli(system: str, prompt: str, model: str, *, timeout_s: float) -> RawCall:
    full_prompt = f"{system}\n\n{prompt}"
    cmd = ["claude", "-p", full_prompt, "--output-format", "json", "--model", model]
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              timeout=timeout_s, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return RawCall("", 0, 0, 0.0, int((time.perf_counter() - t0) * 1000), error="timeout")
    wall_ms = int((time.perf_counter() - t0) * 1000)
    if proc.returncode != 0:
        return RawCall("", 0, 0, 0.0, wall_ms, error=f"exit {proc.returncode}: {(proc.stderr or '')[:200]}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return RawCall("", 0, 0, 0.0, wall_ms, error=f"JSON không hợp lệ: {proc.stdout[:200]!r}")
    if data.get("is_error"):
        return RawCall("", 0, 0, 0.0, wall_ms, error=f"is_error: {str(data.get('result',''))[:200]}")
    usage = data.get("usage") or {}
    return RawCall(
        result=str(data.get("result", "")).strip(),
        in_tokens=int(usage.get("input_tokens", 0)),
        out_tokens=int(usage.get("output_tokens", 0)),
        cost_usd=float(data.get("total_cost_usd", 0.0)),
        duration_ms=int(data.get("duration_ms", wall_ms)),
    )


# ---- suy shape golden fact ----
# PHÁT HIỆN THẬT (khảo toàn bộ 113 fact, 6 file): field "kind" trong golden set
# BỊ DÙNG NHƯ SHAPE (giá trị đúng bằng models.FACT_SHAPES — scalar|range|delta|
# entity_list|entity), KHÔNG phải danh mục ngữ nghĩa FACT_KINDS (percent/money/
# count/...) như Fact.kind ở agents/brief.py. Ưu tiên đọc "kind" trực tiếp
# (100% khớp thực tế); fallback suy theo field CHỈ khi "kind" không phải 1
# trong 5 shape hợp lệ (an toàn nếu golden set sau này đổi quy ước).
def golden_shape(f: dict) -> str:
    kind = str(f.get("kind", "")).strip().lower()
    if kind in FACT_SHAPES:
        return kind
    if "value_low" in f and "value_high" in f:
        return "range"
    if "from_value" in f and "to_value" in f:
        return "delta"
    if "entities" in f:
        return "entity_list"
    if "entity_type" in f:
        return "entity"
    return "scalar"


# ---- atomic claim key: canonical số nếu parse được, fallback chuỗi NFC casefold ----
def _atomic_key(bucket: str, *parts) -> tuple:
    return (bucket,) + tuple(round(p, 6) if isinstance(p, float) else p for p in parts)


def _fuzzy_name_match(a: str, b: str) -> bool:
    """So khớp tên (entity/entity_list) SUBSTRING 2 CHIỀU sau NFC+casefold —
    chấp nhận paraphrase RÚT GỌN/MỞ RỘNG THẬT SỰ là substring (model bỏ chức
    danh dài "TS. ... (Ủy viên...)" -> chỉ còn tên, hoặc bỏ hậu tố "(SHS)"),
    KHÔNG chấp nhận tên khác hẳn nội dung — vẫn CODE, không suy diễn ngữ nghĩa."""
    a, b = _nfc(a), _nfc(b)
    if not a or not b:
        return False
    return a in b or b in a


# entity/entity_list dùng SET TÊN THÔ (NFC, chưa casefold) — so khớp fuzzy-
# substring ở nơi TÍNH recall/precision (_names_recall_precision), KHÔNG dùng
# set-intersection chính xác như 3 shape số (numeric formatting ổn định hơn,
# paraphrase tên riêng phổ biến hơn nhiều — xem ghi chú Phase 3.1).
def golden_atomic_claims(facts: list[dict]) -> dict[str, set]:
    """{shape_bucket: set(...)} — scalar/range/delta: tuple khoá CHÍNH XÁC
    (canonical số hoặc chuỗi NFC). entity/entity_list: set tên thô (NFC) —
    entity_list NỔ thành từng entity riêng (TÁCH bucket 'entity' đơn) để khớp
    granularity dù model gộp/tách khác golden."""
    buckets: dict[str, set] = {"scalar": set(), "range": set(), "delta": set(),
                               "entity": set(), "entity_list": set()}
    for g in facts:
        shape = golden_shape(g)
        unit = g.get("unit")
        if shape == "scalar":
            n = _num(str(g.get("value", "")), unit)
            key = _atomic_key("scalar", n) if n is not None else _atomic_key("scalar_s", _nfc(str(g.get("value", ""))))
            buckets["scalar"].add(key)
        elif shape == "range":
            lo, hi = _num(g["value_low"], unit), _num(g["value_high"], unit)
            key = (_atomic_key("range", lo, hi) if lo is not None and hi is not None
                  else _atomic_key("range_s", _nfc(g["value_low"]), _nfc(g["value_high"])))
            buckets["range"].add(key)
        elif shape == "delta":
            f_, t_ = _num(g["from_value"], unit), _num(g["to_value"], unit)
            key = (_atomic_key("delta", f_, t_) if f_ is not None and t_ is not None
                  else _atomic_key("delta_s", _nfc(g["from_value"]), _nfc(g["to_value"])))
            buckets["delta"].add(key)
        elif shape == "entity":
            buckets["entity"].add(_nfc(str(g.get("value", ""))))
        elif shape == "entity_list":
            for e in g.get("entities", []):
                buckets["entity_list"].add(_nfc(str(e)))
    return buckets


def model_atomic_claims(facts: list[Fact]) -> dict[str, set]:
    buckets: dict[str, set] = {"scalar": set(), "range": set(), "delta": set(),
                               "entity": set(), "entity_list": set()}
    for m in facts:
        if m.shape == "scalar":
            key = (_atomic_key("scalar", m.canonical_value) if m.canonical_value is not None
                  else _atomic_key("scalar_s", _nfc(m.value)))
            buckets["scalar"].add(key)
        elif m.shape == "range":
            key = (_atomic_key("range", m.canonical_low, m.canonical_high)
                  if m.canonical_low is not None and m.canonical_high is not None
                  else _atomic_key("range_s", _nfc(m.value_low or ""), _nfc(m.value_high or "")))
            buckets["range"].add(key)
        elif m.shape == "delta":
            key = (_atomic_key("delta", m.canonical_from, m.canonical_to)
                  if m.canonical_from is not None and m.canonical_to is not None
                  else _atomic_key("delta_s", _nfc(m.from_value or ""), _nfc(m.to_value or "")))
            buckets["delta"].add(key)
        elif m.shape == "entity":
            buckets["entity"].add(_nfc(m.value))
        elif m.shape == "entity_list":
            for e in m.entities:
                buckets["entity_list"].add(_nfc(e))
    return buckets


def _names_recall_precision(golden_names: set, model_names: set) -> tuple[int, int, int]:
    """(tp_recall, n_golden, tp_precision) cho 1 bucket tên (entity/entity_list)
    — so khớp fuzzy-substring 2 chiều, KHÔNG set-intersection chính xác."""
    tp_recall = sum(1 for g in golden_names if any(_fuzzy_name_match(g, m) for m in model_names))
    tp_precision = sum(1 for m in model_names if any(_fuzzy_name_match(g, m) for g in golden_names))
    return tp_recall, len(golden_names), tp_precision


def _bucket_hit(bucket: str, gset: set, mset: set) -> bool:
    if not gset:
        return False
    if bucket in ("entity", "entity_list"):
        return any(_fuzzy_name_match(g, m) for g in gset for m in mset)
    return bool(gset & mset)


def _salience_maps(golden_facts: list[dict], model_facts: list[Fact]):
    """entity-name(casefold) -> salience, CHỈ cho fact CÓ field salience (golden
    entity/entity_list cũ thiếu field này -> bỏ qua, không đoán)."""
    g_map: dict[str, str] = {}
    for g in golden_facts:
        shape = golden_shape(g)
        sal = g.get("salience")
        if not sal:
            continue
        if shape == "entity":
            g_map[_nfc(str(g.get("value", "")))] = sal
        elif shape == "entity_list":
            for e in g.get("entities", []):
                g_map[_nfc(str(e))] = sal
    m_map: dict[str, str] = {}
    for m in model_facts:
        if m.shape == "entity" and m.salience:
            m_map[_nfc(m.value)] = m.salience
        elif m.shape == "entity_list" and m.salience:
            for e in m.entities:
                m_map[_nfc(e)] = m.salience
    return g_map, m_map


@dataclass
class BaiModelResult:
    slug: str
    model: str
    is_negative: bool
    n_golden: int
    n_model_raw: int          # facts LLM ĐỀ XUẤT (trước verify — bắt hallucination attempt)
    n_model_verified: int     # facts CÒN SỐNG sau verify (facts_from_llm_output)
    n_rejected: int           # raw - verified (bị guardrail loại)
    recall: float | None
    precision: float | None
    shape_coverage: float | None
    shape_detail: dict
    salience_accuracy: float | None
    n_salience_judged: int
    source_sentence_valid_rate: float   # luôn 1.0 nếu n_model_verified>0 (verify-by-construction) — báo cáo để đối chứng
    bia_ten_cang: bool                  # CHỈ ý nghĩa với bài âm — model có claim tên cảng nào không
    bia_entities: list[str]
    in_tokens: int
    out_tokens: int
    cost_usd: float
    duration_ms: int
    error: str
    no_numeric_content: bool
    scan_note: str
    model_facts: list[dict] = field(default_factory=list)   # debug/audit — Fact.asdict() từng cái


# tên cảng "cấm" cho bài đối chứng âm — lấy TỪ CHÍNH golden set bài DƯƠNG
# 4_cang_bien_dac_biet (không hard-code tay, tránh bỏ sót/đánh máy sai).
def _port_name_universe() -> set[str]:
    path = REPO_ROOT / "tests" / "golden" / "4_cang_bien_dac_biet.json"
    if not path.exists():
        return set()
    d = json.loads(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for f in d.get("facts", []):
        if golden_shape(f) == "entity_list":
            names |= {_nfc(e) for e in f.get("entities", [])}
        elif golden_shape(f) == "entity" and str(f.get("entity_type", "")).lower() == "place":
            names.add(_nfc(str(f.get("value", ""))))
    return names


def run_one(slug: str, model: str, entry, evidence: str, settings, port_names: set[str]) -> BaiModelResult:
    system = _system_prompt(settings.get("guardrail.entity_types") or None,
                            settings.get("guardrail.entity_salience") or None)
    prompt = build_brief_prompt(evidence)
    # Benchmark: nới hơn timeout production (240s) — vài lượt Opus/bài dài đã
    # thấy xấp xỉ 230s ở Haiku, cần biên an toàn hơn để KHÔNG mất dữ liệu 1
    # lượt benchmark chỉ vì timeout sát nút (khác production, ưu tiên tốc độ).
    timeout_s = max(360.0, float(settings.get("llm.claude_code.timeout_s", 240)))
    call = call_claude_cli(system, prompt, model, timeout_s=timeout_s)

    is_negative = slug == NEGATIVE_SLUG
    golden_facts = entry.facts

    if call.error or not call.result:
        return BaiModelResult(
            slug=slug, model=model, is_negative=is_negative, n_golden=len(golden_facts),
            n_model_raw=0, n_model_verified=0, n_rejected=0,
            recall=None, precision=None, shape_coverage=None, shape_detail={},
            salience_accuracy=None, n_salience_judged=0, source_sentence_valid_rate=0.0,
            bia_ten_cang=False, bia_entities=[],
            in_tokens=call.in_tokens, out_tokens=call.out_tokens, cost_usd=call.cost_usd,
            duration_ms=call.duration_ms, error=call.error or "rỗng", no_numeric_content=False, scan_note="")

    raw_parsed = try_json_object(call.result)
    n_raw = len(raw_parsed.get("facts") or []) if raw_parsed else 0
    result = facts_from_llm_output(call.result, evidence)
    n_verified = len(result.facts)

    g_buckets = golden_atomic_claims(golden_facts)
    m_buckets = model_atomic_claims(result.facts)

    # scalar/range/delta: set-intersection CHÍNH XÁC (số ổn định, không cần
    # fuzzy). entity/entity_list: fuzzy-substring 2 chiều (_names_recall_
    # precision) — chấp nhận paraphrase rút gọn/mở rộng tên riêng, xem
    # _fuzzy_name_match. Cộng dồn TỪNG bucket vào tổng recall/precision chung.
    tp_recall_total = tp_precision_total = n_golden_total = n_model_total = 0
    for bucket in ("scalar", "range", "delta"):
        gset, mset = g_buckets[bucket], m_buckets[bucket]
        tp = len(gset & mset)
        tp_recall_total += tp
        tp_precision_total += tp
        n_golden_total += len(gset)
        n_model_total += len(mset)
    for bucket in ("entity", "entity_list"):
        gset, mset = g_buckets[bucket], m_buckets[bucket]
        tpr, ng, tpp = _names_recall_precision(gset, mset)
        tp_recall_total += tpr
        tp_precision_total += tpp
        n_golden_total += ng
        n_model_total += len(mset)

    recall = (tp_recall_total / n_golden_total) if n_golden_total else None
    precision = (tp_precision_total / n_model_total) if n_model_total else (1.0 if not n_golden_total else 0.0)

    shape_detail = {}
    covered = total_shapes = 0
    for bucket, gset in g_buckets.items():
        if not gset:
            continue
        total_shapes += 1
        hit = _bucket_hit(bucket, gset, m_buckets.get(bucket, set()))
        shape_detail[bucket] = {"golden_n": len(gset), "matched": bool(hit)}
        if hit:
            covered += 1
    shape_coverage = (covered / total_shapes) if total_shapes else None

    g_sal, m_sal = _salience_maps(golden_facts, result.facts)
    judged = agree = 0
    for name, gsal in g_sal.items():
        if name in m_sal:
            judged += 1
            if m_sal[name] == gsal:
                agree += 1
    salience_accuracy = (agree / judged) if judged else None

    # source_sentence hợp lệ — verify LẠI ĐỘC LẬP (NFC) mọi fact còn sống, đối
    # chứng cơ chế filter nội bộ của facts_from_llm_output (luôn phải =1.0 nếu
    # >0 fact, vì hàm đó KHÔNG BAO GIỜ giữ fact chưa verify được).
    ev_nfc = unicodedata.normalize("NFC", evidence)
    valid = sum(1 for f in result.facts if unicodedata.normalize("NFC", f.source or "") in ev_nfc)
    source_sentence_valid_rate = (valid / n_verified) if n_verified else 1.0

    bia_entities: list[str] = []
    if port_names:
        for m in result.facts:
            if m.shape == "entity" and _nfc(m.value) in port_names:
                bia_entities.append(m.value)
            elif m.shape == "entity_list":
                bia_entities += [e for e in m.entities if _nfc(e) in port_names]

    return BaiModelResult(
        slug=slug, model=model, is_negative=is_negative, n_golden=len(golden_facts),
        n_model_raw=n_raw, n_model_verified=n_verified, n_rejected=max(0, n_raw - n_verified),
        recall=recall, precision=precision, shape_coverage=shape_coverage, shape_detail=shape_detail,
        salience_accuracy=salience_accuracy, n_salience_judged=judged,
        source_sentence_valid_rate=source_sentence_valid_rate,
        bia_ten_cang=bool(bia_entities), bia_entities=bia_entities,
        in_tokens=call.in_tokens, out_tokens=call.out_tokens, cost_usd=call.cost_usd,
        duration_ms=call.duration_ms, error="", no_numeric_content=result.no_numeric_content,
        scan_note=result.scan_note, model_facts=[asdict(f) for f in result.facts])


CHECKPOINT_PATH = REPO_ROOT / "reports" / "ab_brief_checkpoint.json"


def load_checkpoint() -> list[dict]:
    if CHECKPOINT_PATH.exists():
        return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    return []


def save_checkpoint(rows: list[dict]) -> None:
    CHECKPOINT_PATH.parent.mkdir(exist_ok=True)
    CHECKPOINT_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def main(models: list[str], *, resume: bool = True) -> list[BaiModelResult]:
    """LƯU DẦN sau MỖI lượt (model×bài) vào CHECKPOINT_PATH — mỗi lượt gọi CLI
    thật mất 1.5-4 phút, 18 lượt CÓ THỂ vượt giới hạn 1 tiến trình đơn (10
    phút/lệnh) — resume=True (mặc định) BỎ QUA cặp (model,slug) ĐÃ có trong
    checkpoint từ lượt chạy trước (KHÔNG gọi lại LLM tốn thêm $), cho phép
    chạy nhiều lệnh riêng (vd --models haiku, rồi --models sonnet, ...) rồi
    gộp báo cáo cuối bằng --report-only."""
    settings = load_settings()
    entries = load_golden_entries()
    port_names = _port_name_universe()

    checkpoint = load_checkpoint() if resume else []
    done_keys = {(row["model"], row["slug"]) for row in checkpoint if not row.get("error")}
    results: list[BaiModelResult] = [BaiModelResult(**row) for row in checkpoint]

    for model in models:
        for e in entries:
            if (model, e.slug) in done_keys:
                print(f"[{model}] {e.slug} ... đã có ở checkpoint, bỏ qua.")
                continue
            evidence = evidence_text_for_golden(e.slug, settings)
            if not evidence:
                print(f"[LỖI] Thiếu evidence cho '{e.slug}' — chạy scripts/golden_evidence.py trước.")
                continue
            print(f"[{model}] {e.slug} ...", end=" ", flush=True)
            r = run_one(e.slug, model, e, evidence, settings, port_names)
            results.append(r)
            print(f"done (recall={r.recall} precision={r.precision} "
                 f"n_raw={r.n_model_raw} n_verified={r.n_model_verified} "
                 f"${r.cost_usd:.4f} {r.duration_ms}ms {r.error})")
            # checkpoint NGAY sau MỖI lượt — mất tiến trình giữa chừng vẫn giữ
            # được các lượt ĐÃ gọi (tốn $ thật, không được để mất trắng).
            save_checkpoint([asdict(x) for x in results])
    return results


def write_report(results: list[BaiModelResult], out_path: Path) -> None:
    lines = ["# A/B Brief — Haiku · Sonnet · Opus", "",
            f"Chạy: {datetime.now().isoformat(timespec='seconds')} · "
            f"0 lượt ghi Sheet · evidence từ corpus (topic_key, không _raw/).", ""]

    pos = [r for r in results if not r.is_negative]
    neg = [r for r in results if r.is_negative]

    lines.append("## 5 bài DƯƠNG — trung bình recall/precision/shape/salience theo model")
    lines.append("")
    lines.append("| Model | Recall | Precision | Shape coverage | Salience acc. | source_sentence hợp lệ | Rejected (bịa bị lọc) | Cost/lượt | Latency/lượt |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for model in MODELS:
        rows = [r for r in pos if r.model == model and not r.error]
        if not rows:
            lines.append(f"| {model} | — | — | — | — | — | — | — | — |")
            continue
        def avg(key):
            vals = [getattr(r, key) for r in rows if getattr(r, key) is not None]
            return sum(vals) / len(vals) if vals else None
        rec, prec, shp = avg("recall"), avg("precision"), avg("shape_coverage")
        sal_vals = [r.salience_accuracy for r in rows if r.salience_accuracy is not None]
        sal = sum(sal_vals) / len(sal_vals) if sal_vals else None
        ssv = sum(r.source_sentence_valid_rate for r in rows) / len(rows)
        rej = sum(r.n_rejected for r in rows) / len(rows)
        cost = sum(r.cost_usd for r in rows) / len(rows)
        dur = sum(r.duration_ms for r in rows) / len(rows)
        def fmt(x, pct=True):
            return "—" if x is None else (f"{x*100:.0f}%" if pct else f"{x:.2f}")
        lines.append(f"| **{model}** | {fmt(rec)} | {fmt(prec)} | {fmt(shp)} | {fmt(sal)} | "
                     f"{fmt(ssv)} | {rej:.1f} | ${cost:.4f} | {dur/1000:.1f}s |")

    lines.append("")
    lines.append("### Chi tiết từng bài dương")
    lines.append("")
    lines.append("| Bài | Model | Recall | Precision | Shape cov. | Salience | n_golden | n_raw→n_verified | Cost | Latency |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in pos:
        def fmt(x, pct=True):
            return "—" if x is None else (f"{x*100:.0f}%" if pct else f"{x:.2f}")
        status = f" ⚠️{r.error}" if r.error else ""
        lines.append(f"| {r.slug} | {r.model} | {fmt(r.recall)} | {fmt(r.precision)} | "
                     f"{fmt(r.shape_coverage)} | {fmt(r.salience_accuracy)} | {r.n_golden} | "
                     f"{r.n_model_raw}→{r.n_model_verified} | ${r.cost_usd:.4f} | {r.duration_ms/1000:.1f}s{status} |")

    lines.append("")
    lines.append("## 1 bài ĐỐI CHỨNG ÂM — `cang_bien_gdp` (KHÔNG có tên cảng nào, related=[] ĐÚNG)")
    lines.append("")
    lines.append("**CHỈ chấm precision + bịa-tên-cảng — KHÔNG hoà vào bảng trên.**")
    lines.append("")
    lines.append("| Model | Precision | Bịa tên cảng? | Tên bịa | n_golden | n_raw→n_verified | Cost | Latency |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in neg:
        def fmt(x, pct=True):
            return "—" if x is None else (f"{x*100:.0f}%" if pct else f"{x:.2f}")
        flag = "🚨 CÓ" if r.bia_ten_cang else "✅ Không"
        names = ", ".join(sorted(set(r.bia_entities))) or "—"
        lines.append(f"| **{r.model}** | {fmt(r.precision)} | {flag} | {names} | {r.n_golden} | "
                     f"{r.n_model_raw}→{r.n_model_verified} | ${r.cost_usd:.4f} | {r.duration_ms/1000:.1f}s |")

    lines.append("")
    lines.append("## Ghi chú")
    lines.append("- `n_raw→n_verified`: facts LLM đề xuất → facts còn sống sau guardrail code (verify NFC trong evidence). "
                 "Chênh lệch = bịa BỊ CHẶN (không lộ ra ngoài, nhưng cho biết model có xu hướng đề xuất ẩu không).")
    lines.append("- `source_sentence hợp lệ` = 1.0 theo thiết kế (facts_from_llm_output KHÔNG BAO GIỜ giữ fact chưa verify) — "
                 "báo cáo để đối chứng cơ chế lọc hoạt động đúng, KHÔNG phải điểm phân biệt model.")
    lines.append("- Tên cảng \"cấm\" cho đối chứng âm lấy TỪ CHÍNH golden set bài dương `4_cang_bien_dac_biet` "
                 "(entity_list/entity kind=place), không hard-code tay.")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    models = MODELS
    report_only = "--report-only" in sys.argv
    for i, arg in enumerate(sys.argv):
        if arg == "--models" and i + 1 < len(sys.argv):
            models = tuple(m.strip() for m in sys.argv[i + 1].split(","))

    if report_only:
        results = [BaiModelResult(**row) for row in load_checkpoint()]
        print(f"[report-only] {len(results)} kết quả trong checkpoint, KHÔNG gọi LLM.")
    else:
        results = main(list(models))

    out_dir = REPO_ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"ab_brief_{datetime.now().strftime('%Y%m%d')}.md"
    write_report(results, out_path)
    print(f"\n== Báo cáo: {out_path} ==")

    raw_path = out_dir / f"ab_brief_{datetime.now().strftime('%Y%m%d')}_raw.json"
    raw_path.write_text(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"== Raw data: {raw_path} ==")
