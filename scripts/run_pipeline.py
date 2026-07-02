"""Chạy pipeline thu thập → chuẩn hóa → persist → nghiên cứu → hook (đến CỔNG 1).

Config-first: mọi thứ đọc từ config/settings.yaml. Adapter: crawl THẬT bằng
HttpFirstCollector (httpx + BeautifulSoup, $0 token, mặc định crawl.engine=http),
lưu bằng FileDocumentStore. Tất định: normalize/relevance/hook đều $0 token —
LLM giữ ở MockLLM (KHÔNG gọi LLM thật, provider=mock).

Dừng TRƯỚC cổng duyệt 1: chỉ sản xuất brief + hook để người duyệt xem, chưa sinh
nội dung đắt. Kết quả lưu ra storage/output/ (JSON + Markdown, UTF-8).

Chạy:
    python scripts/run_pipeline.py                 # crawl thật (engine theo config)
    python scripts/run_pipeline.py "chủ đề tùy chọn"
    python scripts/run_pipeline.py --offline       # MockCollector, không mạng

Crawl thật mặc định KHÔNG cần crawl4ai/Playwright (chỉ httpx + beautifulsoup4).
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

# Cho phép chạy trực tiếp không cần cài package.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

from twmkt.agents.hook import HookAgent  # noqa: E402
from twmkt.agents.researcher import ResearcherAgent  # noqa: E402
from twmkt.config import load_settings  # noqa: E402
from twmkt.curation import normalize  # noqa: E402
from twmkt.curation.config import CurationConfig  # noqa: E402
from twmkt.factory import (  # noqa: E402
    build_collector, build_research_llm, build_sources, build_store,
)
from twmkt.knowledge.rag import Retriever  # noqa: E402


def _safe_slug(text: str, n: int = 40) -> str:
    keep = [c if c.isalnum() else "-" for c in text.lower()]
    slug = "".join(keep).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:n] or "brief"


def _source_stats(name: str, url: str, crawled_docs: list, kept_docs: list) -> dict:
    """Thống kê 1 nguồn (tất định, $0): crawled/kept/loại + mã trích được.

    `kept_docs` = CleanDocument đã qua dedup + whitelist mã + lọc liên quan cho
    nguồn này (gom theo tên nguồn). 'rejected' = crawled - kept (gồm trùng + không
    liên quan). Không tính stored_new ở đây (thuộc về I/O — cộng ở nơi gọi)."""
    return {
        "name": name,
        "url": url,
        "crawled": len(crawled_docs),
        "kept": len(kept_docs),
        "rejected": len(crawled_docs) - len(kept_docs),
        "tickers": sorted({t for d in kept_docs for t in d.tickers}),
    }


def run(topic: str | None = None, *, offline: bool = False, limit: int | None = None,
        mock_llm: bool = False) -> dict:
    settings = load_settings()

    # LLM giả cho brief/hook khi offline HOẶC --mock-llm (crawl thật nhưng $0 token).
    use_mock_llm = offline or mock_llm

    # Preflight: cần khóa API TRƯỚC khi crawl (khỏi tốn công crawl rồi mới bail).
    provider = (settings.get("llm.provider", "mock") or "mock").lower()
    if not use_mock_llm and provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "Chưa đặt ANTHROPIC_API_KEY (llm.provider=anthropic). Đặt biến môi "
            "trường rồi chạy lại, dùng --mock-llm (crawl thật, $0) hoặc --offline."
        )

    # --- Nguồn + collector (config-first qua factory) ------------------------
    # offline=True -> MockCollector ($0 token, không mạng).
    # offline=False -> engine thật theo crawl.engine (mặc định http = httpx+bs4).
    sources = build_sources(settings)
    if not sources:
        raise SystemExit("Không có source enabled trong settings.yaml (mục sources).")
    collector = build_collector(settings, offline=offline)
    # --limit ưu tiên (nếm thử limit nhỏ 3-5 để tiết kiệm token), nếu không lấy config.
    limit = int(limit if limit is not None else settings.get("crawl.limit_per_source", 8))

    topic = topic or f"{sources[0].name}: điểm tin doanh nghiệp"

    # Crawl từng nguồn, giữ nhóm raw theo tên nguồn để báo cáo per-source.
    raw_by_source: dict[str, list] = {}
    for s in sources:
        print(f"[crawl] {s.name} ({s.url}) — limit {limit}...")
        raw_by_source[s.name] = collector.collect(s, limit=limit)
    raw_docs = [d for docs in raw_by_source.values() for d in docs]

    # --- Chuẩn hóa + cổng relevance (tất định) -------------------------------
    curation = CurationConfig.from_settings(settings)
    clean = normalize(raw_docs, curation)   # dedup + whitelist mã + lọc liên quan (global)

    # --- Persist vào FileDocumentStore + thống kê per-source -----------------
    # clean.source giữ nguyên tên nguồn -> gom theo nguồn để đếm kept/loại/mã.
    clean_by_source: dict[str, list] = {}
    for d in clean:
        clean_by_source.setdefault(d.source, []).append(d)

    store = build_store(settings)
    per_source: list[dict] = []
    stored_new = 0
    for s in sources:
        kept_docs = clean_by_source.get(s.name, [])
        stat = _source_stats(s.name, s.url, raw_by_source.get(s.name, []), kept_docs)
        stat["stored_new"] = store.upsert(kept_docs)   # persist theo nguồn (dedup across-run)
        stored_new += stat["stored_new"]
        per_source.append(stat)
    all_tickers = sorted({t for d in clean for t in d.tickers})

    # --- Index RAG + brief + hook -------------------------------------------
    # CHỈ Researcher + Hook gọi LLM (tầng rẻ Haiku qua LLMRouter để đo token).
    # Mọi bước khác tất định $0. Dùng CHUNG 1 router để usage cộng dồn.
    retriever = Retriever.from_settings(settings)
    retriever.index(clean)
    llm = build_research_llm(settings, offline=use_mock_llm)   # LLMRouter(Haiku|Mock)
    brief = ResearcherAgent(llm).run(topic, retriever)
    hook = HookAgent(llm).run(brief)
    usage = llm.usage.as_dict()
    kept = len(clean)
    usage["provider"] = "mock" if use_mock_llm else provider
    usage["cost_per_article_usd"] = round(usage["cost_usd"] / kept, 6) if kept else 0.0

    # --- Lưu output (JSON + Markdown, UTF-8) ---------------------------------
    out_dir = Path(settings.get("storage.output_dir", "storage/output"))
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    stem = f"{ts}-{_safe_slug(topic)}"

    payload = {
        "topic": topic,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stats": {
            "crawled": len(raw_docs), "kept": len(clean), "stored_new": stored_new,
            "tickers": all_tickers, "n_tickers": len(all_tickers),
        },
        "per_source": per_source,    # crawled/kept/loại/stored/mã theo từng nguồn
        "llm_usage": usage,          # token + ước tính chi phí (LLMRouter)
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
    b, h, u = p["brief"], p["hook"], p["llm_usage"]
    ps = p.get("per_source", [])
    lines = [
        f"# {p['topic']}",
        "",
        f"*Sinh lúc {p['generated_at']} — crawled {p['stats']['crawled']}, "
        f"kept {p['stats']['kept']}, stored(new) {p['stats']['stored_new']}, "
        f"{p['stats'].get('n_tickers', 0)} mã*",
        "",
        "## Thu thập theo nguồn",
        "| Nguồn | Crawled | Kept | Loại | Stored(new) | Mã |",
        "| --- | --: | --: | --: | --: | --- |",
        *[f"| {s['name']} | {s['crawled']} | {s['kept']} | {s['rejected']} | "
          f"{s['stored_new']} | {', '.join(s['tickers']) or '—'} |" for s in ps],
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
        "## Token & chi phí (chỉ Researcher + Hook)",
        f"- provider: {u.get('provider')} · calls: {u.get('calls')} "
        f"(cache hits {u.get('cache_hits')})",
        f"- tokens (ước tính): in {u.get('in_tokens')} / out {u.get('out_tokens')}",
        f"- chi phí: ~${u.get('cost_usd'):.6f} tổng · "
        f"~${u.get('cost_per_article_usd'):.6f}/bài giữ lại",
        "",
        "## Nguồn",
        *[f"- {src}" for src in (b.get("sources") or [])],
        "",
    ]
    return "\n".join(lines)


def _print_summary(p: dict, json_path: Path) -> None:
    st, b, h, u = p["stats"], p["brief"], p["hook"], p["llm_usage"]
    print("========== SUMMARY (đến cổng duyệt 1) ==========")
    print(f"Chủ đề     : {p['topic']}")
    print("---------- Theo từng nguồn ----------")
    for s in p.get("per_source", []):
        print(f"• {s['name']}")
        print(f"    crawled {s['crawled']} | kept {s['kept']} | loại {s['rejected']} "
              f"| stored(new) {s['stored_new']} | mã: {', '.join(s['tickers']) or '—'}")
    print("---------- Tổng ----------")
    print(f"crawled    : {st['crawled']}")
    print(f"kept       : {st['kept']} (sau dedup + relevance)")
    print(f"stored(new): {st['stored_new']} (FileDocumentStore)")
    print(f"số mã trích : {st['n_tickers']} — {', '.join(st.get('tickers') or []) or 'N/A'}")
    print(f"luận điểm  : {b.get('thesis', '')}")
    print(f"hook.angle : {h.get('angle', '')}")
    print("headlines  :")
    for hl in (h.get("headlines") or []):
        print(f"  - {hl}")
    print("---------- LLM (chỉ Researcher + Hook) ----------")
    print(f"provider   : {u.get('provider')} | model: {list(u.get('by_model') or {}) or ['mock']}")
    print(f"calls      : {u.get('calls')} (cache hits {u.get('cache_hits')})")
    print(f"tokens     : in {u.get('in_tokens')} / out {u.get('out_tokens')} (ước tính)")
    print(f"chi phí     : ~${u.get('cost_usd'):.6f} tổng | "
          f"~${u.get('cost_per_article_usd'):.6f}/bài giữ lại")
    print(f"\nĐã lưu     : {json_path}  (+ .md)")


def _parse_args(argv: list[str]):
    import argparse
    ap = argparse.ArgumentParser(
        description="Chạy pipeline đến cổng duyệt 1 (brief + hook). LLM thật chỉ ở "
                    "Researcher + Hook (tầng rẻ Haiku) theo llm.provider trong config."
    )
    ap.add_argument("topic", nargs="?", default=None, help="Chủ đề (mặc định: theo source đầu).")
    ap.add_argument("--offline", action="store_true",
                    help="Dùng MockCollector + MockLLM ($0 token, không mạng, không cần khóa API).")
    ap.add_argument("--mock-llm", dest="mock_llm", action="store_true",
                    help="Crawl THẬT nhưng dùng MockLLM cho brief/hook ($0 token, không cần khóa API).")
    ap.add_argument("--limit", type=int, default=None,
                    help="Số bài tối đa/nguồn (ghi đè crawl.limit_per_source).")
    return ap.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    run(args.topic, offline=args.offline, limit=args.limit, mock_llm=args.mock_llm)
