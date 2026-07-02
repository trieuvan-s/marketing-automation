"""Chạy pipeline thu thập → chuẩn hóa → persist → nghiên cứu → hook (đến CỔNG 1).

Config-first: mọi thứ đọc từ config/settings.yaml. Adapter: crawl thật bằng
Crawl4aiCollector, lưu bằng FileDocumentStore. Tất định: normalize/relevance/hook
đều $0 token — LLM giữ ở MockLLM (KHÔNG gọi LLM thật, provider=mock).

Dừng TRƯỚC cổng duyệt 1: chỉ sản xuất brief + hook để người duyệt xem, chưa sinh
nội dung đắt. Kết quả lưu ra storage/output/ (JSON + Markdown, UTF-8).

Chạy:
    python scripts/run_pipeline.py
    python scripts/run_pipeline.py "chủ đề tùy chọn"

Yêu cầu crawl thật: pip install crawl4ai && crawl4ai-setup (xem requirements/pyproject).
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

# Cho phép chạy trực tiếp không cần cài package.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from twmkt.agents.base import MockLLM  # noqa: E402
from twmkt.agents.hook import HookAgent  # noqa: E402
from twmkt.agents.researcher import ResearcherAgent  # noqa: E402
from twmkt.config import load_settings  # noqa: E402
from twmkt.curation import normalize  # noqa: E402
from twmkt.curation.config import CurationConfig  # noqa: E402
from twmkt.factory import build_collector, build_sources, build_store  # noqa: E402
from twmkt.knowledge.rag import Retriever  # noqa: E402


def _safe_slug(text: str, n: int = 40) -> str:
    keep = [c if c.isalnum() else "-" for c in text.lower()]
    slug = "".join(keep).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:n] or "brief"


def run(topic: str | None = None, *, offline: bool = False) -> dict:
    settings = load_settings()

    # --- Nguồn + collector (config-first qua factory) ------------------------
    # offline=True -> MockCollector ($0 token, không mạng, không cần crawl4ai).
    # offline=False -> Crawl4aiCollector thật (limit theo config).
    sources = build_sources(settings)
    if not sources:
        raise SystemExit("Không có source enabled trong settings.yaml (mục sources).")
    collector = build_collector(settings, offline=offline)
    limit = int(settings.get("crawl.limit_per_source", 8))

    topic = topic or f"{sources[0].name}: điểm tin doanh nghiệp"

    raw_docs = []
    for s in sources:
        raw_docs.extend(collector.collect(s, limit=limit))

    # --- Chuẩn hóa + cổng relevance (tất định) -------------------------------
    curation = CurationConfig.from_settings(settings)
    clean = normalize(raw_docs, curation)

    # --- Persist vào FileDocumentStore (dedup across-run theo url) ------------
    store = build_store(settings)
    stored_new = store.upsert(clean)

    # --- Index RAG + brief + hook (MockLLM, $0 token) ------------------------
    retriever = Retriever.from_settings(settings)
    retriever.index(clean)
    llm = MockLLM()   # KHÔNG gọi LLM thật
    brief = ResearcherAgent(llm).run(topic, retriever)
    hook = HookAgent(llm).run(brief)

    # --- Lưu output (JSON + Markdown, UTF-8) ---------------------------------
    out_dir = Path(settings.get("storage.output_dir", "storage/output"))
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    stem = f"{ts}-{_safe_slug(topic)}"

    payload = {
        "topic": topic,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stats": {"crawled": len(raw_docs), "kept": len(clean), "stored_new": stored_new},
        "brief": asdict(brief),
        "hook": asdict(hook),
    }
    (out_dir / f"{stem}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (out_dir / f"{stem}.md").write_text(_to_markdown(payload), encoding="utf-8")

    _print_summary(payload, out_dir / f"{stem}.json")
    return payload


def _to_markdown(p: dict) -> str:
    b, h = p["brief"], p["hook"]
    lines = [
        f"# {p['topic']}",
        "",
        f"*Sinh lúc {p['generated_at']} — crawled {p['stats']['crawled']}, "
        f"kept {p['stats']['kept']}, stored(new) {p['stats']['stored_new']}*",
        "",
        "## Luận điểm (brief)",
        b.get("thesis", ""),
        "",
        f"**Mã liên quan:** {', '.join(b.get('tickers') or []) or 'N/A'}",
        "",
        "### Điểm chính",
        *[f"- {kp}" for kp in (b.get("key_points") or [])],
        "",
        "## Góc marketing (hook)",
        f"**Angle:** {h.get('angle', '')}",
        "",
        "### Tiêu đề ứng viên",
        *[f"- {hl}" for hl in (h.get("headlines") or [])],
        "",
        f"**Audience:** {h.get('audience', '')} · **Emotion:** {h.get('emotion', '')}",
        f"**CTA:** {h.get('cta', '')}",
        "",
        "## Nguồn",
        *[f"- {u}" for u in (b.get("sources") or [])],
        "",
    ]
    return "\n".join(lines)


def _print_summary(p: dict, json_path: Path) -> None:
    st, b, h = p["stats"], p["brief"], p["hook"]
    print("========== SUMMARY (đến cổng duyệt 1) ==========")
    print(f"Chủ đề     : {p['topic']}")
    print(f"crawled    : {st['crawled']}")
    print(f"kept       : {st['kept']} (sau dedup + relevance)")
    print(f"stored(new): {st['stored_new']} (FileDocumentStore)")
    print(f"tickers    : {', '.join(b.get('tickers') or []) or 'N/A'}")
    print(f"hook.angle : {h.get('angle', '')}")
    print("headlines  :")
    for hl in (h.get("headlines") or []):
        print(f"  - {hl}")
    print(f"\nĐã lưu     : {json_path}  (+ .md)")


def _parse_args(argv: list[str]):
    import argparse
    ap = argparse.ArgumentParser(
        description="Chạy pipeline đến cổng duyệt 1 (brief + hook). Provider=mock."
    )
    ap.add_argument("topic", nargs="?", default=None, help="Chủ đề (mặc định: theo source đầu).")
    ap.add_argument("--offline", action="store_true",
                    help="Dùng MockCollector ($0 token, không mạng, không cần crawl4ai).")
    return ap.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    run(args.topic, offline=args.offline)
