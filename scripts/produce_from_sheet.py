"""GIAI ĐOẠN SẢN XUẤT (cổng 2): CONTEXT.Status=APPROVE -> sinh sản phẩm.

Luồng:
  CONTEXT (Status=APPROVE)  --đọc-->  full-fetch thân bài thật (tất định, $0)
    -->  Production (LLM ĐẮT: Sonnet, đã qua cổng 1)
    • AnalysisWriterAgent  (bài phân tích, LLM, schema JSON)
    • VideoScriptAgent     (kịch bản video, LLM, schema JSON)
    • InfographicSpecAgent (spec JSON, tất định $0 — số liệu trích thẳng evidence)
  --guardrail-->  compliance (disclaimer/claim cấm) + chặn bịa số (so evidence)
  --ghi-->  tab CONTENT (Context|Type|Status|Output) + storage/output/<ngày>/
  --> người duyệt xem & duyệt sản phẩm (cổng 2) --> Publish (giai đoạn sau).

Nguyên tắc: LLM đắt CHỈ chạy ở đây (sau cổng 1). Đã sinh rồi thì bỏ qua (dedup
(Context,Type) trong CONTENT) -> KHỎI tốn Sonnet lại. LÙI MƯỢT: thiếu SDK/khóa ->
Mock ($0), agent tự dựng khung tất định, KHÔNG crash. Văn phong agent nạp từ tab
PROMPTS (Name|Version|Enable) -> prompts/<Name>.<Version>.md; thiếu -> default code.

HAI CHẾ ĐỘ điền nội dung article/video (infographic luôn tất định, $0):
  1. Mặc định / --offline: gọi AnthropicLLM API (cần ANTHROPIC_API_KEY riêng) —
     để dành cho automation 100% không người trông (tương lai, xem CLAUDE.md).
  2. --draft / --ingest: KHÔNG cần API key riêng — nhờ Claude Code (phiên chat
     đang chạy, dùng gói Pro/Max/Team) viết nội dung. --draft chuẩn bị prompt
     (storage.drafts_dir), Claude đọc + viết JSON đúng schema cạnh đó, --ingest
     nạp lại qua ĐÚNG guardrail/CONTENT như chế độ 1 (không phân biệt "ai viết").
     Vì hệ thống đã có 2 cổng duyệt người-trong-vòng-lặp, đây là chế độ MẶC ĐỊNH
     dùng ở giai đoạn hiện tại (xem docs/production_agents_design.md).

Chạy:
    python scripts/produce_from_sheet.py --draft --limit 3    # chuẩn bị + Claude viết
    python scripts/produce_from_sheet.py --ingest              # nạp bài Claude đã viết
    python scripts/produce_from_sheet.py --limit 3              # gọi thẳng Anthropic API
    python scripts/produce_from_sheet.py --offline               # ép Mock ($0)
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

from twmkt import factory  # noqa: E402
from twmkt.agents.production import (  # noqa: E402
    AnalysisWriterAgent, InfographicSpecAgent, ProductionBrief, VideoScriptAgent,
    all_production_agents, analysis_fields_from_data, apply_guardrails,
    build_analysis_prompt, build_video_prompt, render_analysis, render_video,
    video_fields_from_data,
)
from twmkt.agents.prompts import resolve_prompts  # noqa: E402
from twmkt.agents.voice import load_voice_lock  # noqa: E402
from twmkt.config import load_settings  # noqa: E402
from twmkt.models import ContentDraft, ContentFormat, Source  # noqa: E402
from twmkt.sheets_board import SheetsBoard, content_row  # noqa: E402

_OUTPUT_PREVIEW = 1500   # số ký tự Output đưa lên Sheet (đủ xem; full lưu ra file)
_ALL_TYPES = ("infographic", "article", "video_script")   # 3 loại all_production_agents() sinh


def _is_fully_produced(context: str, seen: set[tuple[str, str]]) -> bool:
    """True nếu CẢ 3 loại (infographic/article/video_script) của `context` đã
    có trong CONTENT (`seen`) — tín hiệu để đặt Execute=DONE (idempotent)."""
    return all((context, t) in seen for t in _ALL_TYPES)


def _slug(text: str, n: int = 40) -> str:
    keep = "".join(c if c.isalnum() else "-" for c in (text or "").lower())
    while "--" in keep:
        keep = keep.replace("--", "-")
    return keep.strip("-")[:n] or "san-pham"


def _ext(fmt_value: str) -> str:
    return "json" if fmt_value == "infographic" else "md"


def match_source_by_domain(url: str, sources: list[Source]) -> Source | None:
    """CONTEXT không còn lưu tên Publisher (đã gọn hoá) -> khớp nguồn đăng ký
    (SOURCES) theo TÊN MIỀN của url bài, để full-fetch dùng đúng selector (mỗi
    domain 1 kiểu DOM). Không khớp -> None (fetch_one dùng default_spec chung)."""
    host = (urlparse(url).netloc or "").removeprefix("www.").lower()
    if not host:
        return None
    for s in sources:
        if (urlparse(s.url).netloc or "").removeprefix("www.").lower() == host:
            return s
    return None


def fetch_full_evidence(html_collector, sources: list[Source], url: str, fallback: str) -> str:
    """Full-fetch thân bài thật (tất định, $0) để LLM bám + chống bịa số. Lỗi/rỗng
    -> `fallback` (vd hook line), CẢNH BÁO rõ, KHÔNG crash."""
    if not url:
        return fallback
    src = match_source_by_domain(url, sources) or Source("_", url)
    try:
        raw = html_collector.fetch_one(src, url)
    except Exception as e:  # noqa: BLE001 - mạng có thể lỗi đủ kiểu, không được crash
        print(f"[CẢNH BÁO] full-fetch lỗi ({e!r}) -> dùng fallback (hook/title): {url}")
        return fallback
    if raw is None or not (raw.markdown or "").strip():
        print(f"[CẢNH BÁO] full-fetch rỗng -> dùng fallback (hook/title): {url}")
        return fallback
    return raw.markdown.strip()


def _open_board(settings, *, setup: bool = False) -> SheetsBoard:
    sheet_id = (os.environ.get("TWMKT_SHEET_ID") or settings.get("sheets.spreadsheet_id") or "").strip()
    creds = (os.environ.get("TWMKT_SHEETS_CREDS") or settings.get("sheets.creds_path") or "").strip()
    if not sheet_id or not creds:
        raise SystemExit("Thiếu sheets.spreadsheet_id/creds_path (settings.yaml hoặc ENV).")
    board = SheetsBoard(spreadsheet_id=sheet_id, creds_path=creds)
    # ensure_tabs() mặc định RẺ (chỉ tạo/format khi phát hiện tab thiếu/header sai);
    # setup=True (cờ --setup ở CLI) ép chạy đầy đủ (tạo tab/seed/format lại).
    board.ensure_tabs(force=setup)
    return board


def run_sync_only() -> dict:
    """Đồng bộ Execute NGAY, không đợi lịch (schedule/schedule_draft): Sheet
    KHÔNG có trigger đẩy sang Python -> đổi Status=APPROVE trên Sheet chỉ được
    Python NHÌN THẤY khi 1 script đọc lại (pull-based, xem sync_approve_execute_
    flags docstring). Dùng khi vừa duyệt tay và muốn Execute=RUN NGAY, không
    chờ lịch crawl (4h) hay --draft (30') tới lượt. KHÔNG full-fetch/gọi LLM."""
    settings = load_settings()
    board = _open_board(settings)
    n = board.sync_approve_execute_flags()
    print(f"[sync-only] Đồng bộ Execute=RUN cho {n} dòng Status=APPROVE (Execute vừa rỗng).")
    return {"synced": n}


def run(*, limit: int = 5, offline: bool = False, model: str | None = None,
        setup: bool = False) -> dict:
    settings = load_settings()
    board = _open_board(settings, setup=setup)

    # --- LLM ĐẮT cho Producers (Sonnet mặc định, --model opus nếu cần chất
    # lượng cao hơn). LÙI MƯỢT CÓ CẢNH BÁO: banner IN RÕ, không im lặng.
    # --offline luôn ép Mock (kể cả có key) để kiểm chứng $0.
    llm = factory.llm_status(settings)
    use_llm = (not offline) and llm.use_llm
    banner = ("LLM active: MOCK ($0 fallback) — lý do: --offline (ép mock)"
             if offline and llm.use_llm else llm.banner)
    print(banner)
    content_llm = factory.build_content_llm(settings, offline=not use_llm, model=model)
    engine = factory.model_engine_label(llm.content_model, use_llm=use_llm)
    board.log("INFO", banner, engine=engine)

    # Execute: dòng vừa APPROVE (Execute rỗng) -> tự đặt RUN; rồi CHỈ xử lý dòng
    # Status=APPROVE VÀ Execute=RUN (Execute=DONE -> đã sinh xong, bỏ qua —
    # idempotent, produce chạy lại KHÔNG sinh Content trùng).
    board.sync_approve_execute_flags()
    approved = [a for a in board.read_approved_context() if a["execute"] == "RUN"]
    if not approved:
        print("Không có dòng CONTEXT nào Status=APPROVE và Execute=RUN (chưa sản xuất). "
              "Duyệt ở tab CONTEXT trước.")
        return {"approved": 0, "produced": 0, "skipped": 0}
    approved = approved[:limit]

    # PROMPTS: đọc LIVE tab (Name|Version|Enable) -> resolve prompts/<name>.<v>.md;
    # thiếu tab/dòng/file -> giữ default nội bộ trong code (KHÔNG crash).
    default_prompts = {a.prompt_name: a.system for a in all_production_agents()}
    prompt_overrides = resolve_prompts(
        board.read_prompt_versions(), default_prompts,
        prompts_dir=settings.get("prompts.dir", "prompts"))

    # Full-fetch thân bài thật (tất định, $0) cho từng dòng APPROVE -> evidence
    # thật để LLM bám + chống bịa số (khớp nguồn đăng ký theo TÊN MIỀN).
    sources = board.read_sources() or factory.build_sources(settings)
    html_collector = factory.build_collector_for_source(Source("_", "_", fetch_type="html"), settings)

    seen = board.existing_content_keys()   # (Context, Type) đã sinh -> bỏ qua
    out_dir = Path(settings.get("storage.output_dir", "storage/output")) / _today()
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[list[str]] = []
    done_rows: list[int] = []   # số dòng CONTEXT (1-based) VỪA sản xuất xong -> Execute=DONE
    produced = skipped = flagged = 0
    for item in approved:
        evidence = fetch_full_evidence(html_collector, sources, item["source"], item["hook"])
        brief = ProductionBrief(
            title=item["context"], hook=item["hook"], tickers=item["tickers"],
            group=item["group"], topic=item["topic"], url=item["source"],
            evidence=evidence,
        )
        for agent in all_production_agents(content_llm, prompt_overrides=prompt_overrides):
            draft = apply_guardrails(agent.run(brief), brief.evidence, brief.background)
            type_ = draft.fmt.value
            if (item["context"], type_) in seen:
                skipped += 1
                continue
            status = "DONE" if draft.is_clean else "ERROR"
            note = "; ".join(draft.compliance_issues)
            if not use_llm and type_ != "infographic":
                note = (note + " | " if note else "") + "MOCK (chưa bật Sonnet)"
            # Lưu full ra file, đưa preview lên Sheet.
            fn = out_dir / f"{_slug(item['context'])}-{type_}.{_ext(type_)}"
            fn.write_text(draft.body, encoding="utf-8")
            preview = draft.body if len(draft.body) <= _OUTPUT_PREVIEW else \
                draft.body[:_OUTPUT_PREVIEW] + f"\n…(xem {fn.name})"
            rows.append(content_row(context=item["context"], type_=type_,
                                    status=status, output=preview, notes=note))
            seen.add((item["context"], type_))
            produced += 1
            flagged += 0 if draft.is_clean else 1
        done_rows.append(item["row"])   # xong CẢ 3 loại cho dòng này -> đánh dấu DONE

    written = board.append_content_rows(rows)
    board.mark_execute_done(done_rows)   # idempotent: chạy lại bỏ qua (execute=='RUN' lọc ở trên)
    if written:
        board.regroup_and_merge_content()   # merge dọc Timestamp+Context khi đủ 3 loại
    u = content_llm.usage.as_dict()
    board.log("INFO", f"TỔNG Production: approved {len(approved)} / sinh mới {produced} / "
                      f"bỏ qua {skipped} / dính compliance {flagged} / ghi CONTENT {written} / "
                      f"Execute=DONE {len(done_rows)} dòng",
              engine=engine)
    _summary(len(approved), produced, skipped, flagged, use_llm, u, out_dir)
    return {"approved": len(approved), "produced": produced, "skipped": skipped,
            "flagged": flagged, "llm": u, "use_llm": use_llm, "written": written}


def _today() -> str:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date().isoformat()
    except Exception:
        return datetime.now(timezone.utc).date().isoformat()


# =====================================================================
# --draft / --ingest: nhờ Claude Code (phiên chat) viết article/video thay vì
# gọi AnthropicLLM API — KHÔNG cần ANTHROPIC_API_KEY riêng. Cùng schema/guardrail/
# CONTENT với chế độ gọi API thẳng (run()) nên đổi sang API thật sau này không
# cần sửa gì ở đây.
# =====================================================================
_SCHEMA_HINT = {
    "article": 'title/sapo/sections[{heading,content}]/disclaimer/sources[]',
    "video": 'title/duration_sec/scenes[{t,voiceover,on_screen_text,visual_hint}]/cta/disclaimer',
}


def _prompt_md(slug: str, type_: str, user_prompt: str) -> str:
    system = AnalysisWriterAgent.system if type_ == "article" else VideoScriptAgent.system
    # Voice-lock: đường --draft KHÔNG đi qua Agent._ask() (không có LLMClient thật ở
    # đây — Claude Code tự đọc file .prompt.md này) nên phải nối riêng tại đây, chỉ
    # cho "article" theo đúng phạm vi hiện tại (xem agents/voice.py).
    if type_ == "article":
        voice = load_voice_lock("analysis")
        if voice:
            system += f"\n\n---\n\nVOICE-LOCK (giọng văn bắt buộc):\n{voice}"
    return (
        f"# YÊU CẦU VIẾT — {slug} ({type_})\n\n"
        f"## System (vai trò)\n{system}\n\n"
        f"## User (nội dung yêu cầu)\n{user_prompt}\n\n"
        f"## BƯỚC 1 — Research TRƯỚC KHI VIẾT (làm 1 lần/bài, dùng chung cho article+video)\n"
        f"Dùng WebSearch/WebFetch tìm bối cảnh/tiền lệ LIÊN QUAN đã công bố TRƯỚC bài này "
        f"(nguồn gốc vụ việc, các bên liên quan, phản ứng thị trường/giá cổ phiếu nếu có, "
        f"số liệu tài chính liên quan...) — để bài viết là bản TỔNG HỢP thật, giúp người "
        f"CHƯA đọc tin trước đó vẫn hiểu toàn cảnh, KHÔNG chỉ dịch lại 1 bài báo.\n"
        f"Ghi tóm tắt kết quả research (có SỐ LIỆU cụ thể, KHÔNG bịa) vào file "
        f"`{slug}.background.txt` (CÙNG THƯ MỤC, chỉ cần viết 1 lần cho cả article+video).\n\n"
        f"## BƯỚC 2 — Viết JSON đúng schema\n"
        f"Viết DUY NHẤT JSON đúng schema ({_SCHEMA_HINT[type_]}) — KHÔNG markdown, "
        f"KHÔNG lời dẫn — lưu vào file `{slug}.{type_}.json` (CÙNG THƯ MỤC file này). "
        f"BÁM SỐ LIỆU trong evidence (User ở trên) + trong {slug}.background.txt vừa viết — "
        f"KHÔNG dùng số liệu nào khác (guardrail sẽ chặn nếu bịa).\n\n"
        f"Sau khi viết xong hết các file cần (mọi *.article.json/*.video.json + "
        f"{slug}.background.txt), chạy: python scripts/produce_from_sheet.py --ingest\n"
    )


def draft_to_content_draft(type_: str, data: dict, brief: ProductionBrief) -> ContentDraft:
    """Chuyển JSON Claude Code đã viết (schema article/video) -> ContentDraft đã
    qua guardrail (evidence + brief.background gộp lại). Hàm THUẦN — DÙNG CHUNG
    bởi run_ingest() và test (không cần Sheets/mạng). `type_` = 'article' | 'video'."""
    if type_ == "article":
        title, sapo, sections, disclaimer, sources = analysis_fields_from_data(data, brief)
        body = render_analysis(title, sapo, sections, disclaimer, sources, brief)
        draft = ContentDraft(fmt=ContentFormat.ARTICLE, title=title, body=body, brief_topic=brief.topic)
    else:
        title, duration, scenes, cta, disclaimer = video_fields_from_data(data, brief)
        body = render_video(title, duration, scenes, cta, disclaimer, brief)
        draft = ContentDraft(fmt=ContentFormat.VIDEO_SCRIPT, title=title, body=body, brief_topic=brief.topic)
    return apply_guardrails(draft, brief.evidence, brief.background)


def run_draft(*, limit: int = 5, setup: bool = False) -> dict:
    """Full-fetch evidence + sinh infographic NGAY (tất định, $0); với article/
    video -> ghi *.brief.json + *.<type>.prompt.md vào storage.drafts_dir để
    Claude Code đọc và viết *.<type>.json cạnh đó (không gọi API riêng)."""
    settings = load_settings()
    board = _open_board(settings, setup=setup)

    # Execute: dòng vừa APPROVE (Execute rỗng) -> tự đặt RUN; CHỈ xử lý dòng
    # Status=APPROVE VÀ Execute=RUN (DONE -> đã sinh xong, bỏ qua — idempotent).
    board.sync_approve_execute_flags()
    approved = [a for a in board.read_approved_context() if a["execute"] == "RUN"]
    if not approved:
        print("Không có dòng CONTEXT nào Status=APPROVE và Execute=RUN (chưa sản xuất). "
              "Duyệt ở tab CONTEXT trước.")
        return {"approved": 0, "prepared": 0, "infographic_done": 0}
    approved = approved[:limit]

    sources = board.read_sources() or factory.build_sources(settings)
    html_collector = factory.build_collector_for_source(Source("_", "_", fetch_type="html"), settings)
    seen = board.existing_content_keys()
    out_dir = Path(settings.get("storage.output_dir", "storage/output")) / _today()
    out_dir.mkdir(parents=True, exist_ok=True)
    drafts_dir = Path(settings.get("storage.drafts_dir", "storage/production_drafts"))
    drafts_dir.mkdir(parents=True, exist_ok=True)

    rows: list[list[str]] = []
    done_rows: list[int] = []   # dòng CONTEXT (1-based) đã đủ CẢ 3 loại -> Execute=DONE
    prepared = infographic_done = 0
    for item in approved:
        context = item["context"]
        evidence = fetch_full_evidence(html_collector, sources, item["source"], item["hook"])
        brief = ProductionBrief(
            title=context, hook=item["hook"], tickers=item["tickers"],
            group=item["group"], topic=item["topic"], url=item["source"], evidence=evidence,
        )
        slug = _slug(context)

        # Infographic: tất định, $0 -> sinh NGAY, không cần Claude Code.
        if (context, "infographic") not in seen:
            draft = apply_guardrails(InfographicSpecAgent(None).run(brief), brief.evidence, brief.background)
            fn = out_dir / f"{slug}-infographic.json"
            fn.write_text(draft.body, encoding="utf-8")
            rows.append(content_row(context=context, type_="infographic",
                                    status="DONE" if draft.is_clean else "ERROR",
                                    output=draft.body[:_OUTPUT_PREVIEW],
                                    notes="; ".join(draft.compliance_issues)))
            seen.add((context, "infographic"))
            infographic_done += 1

        # Article/Video: chuẩn bị request cho Claude Code (bỏ qua nếu đã có
        # trong CONTENT, hoặc đã chuẩn bị/đã có câu trả lời đang chờ --ingest).
        need_brief = False
        for type_, ctype, prompt_fn in (
            ("article", "article", build_analysis_prompt),
            ("video", "video_script", build_video_prompt),
        ):
            if (context, ctype) in seen:
                continue
            if (drafts_dir / f"{slug}.{type_}.json").exists():
                continue   # đã có câu trả lời, chờ --ingest
            if (drafts_dir / f"{slug}.{type_}.prompt.md").exists():
                continue   # đã chuẩn bị, đang chờ Claude Code trả lời
            (drafts_dir / f"{slug}.{type_}.prompt.md").write_text(
                _prompt_md(slug, type_, prompt_fn(brief)), encoding="utf-8")
            need_brief = True
            prepared += 1
        brief_path = drafts_dir / f"{slug}.brief.json"
        if need_brief and not brief_path.exists():
            # execute_row: số dòng CONTEXT (1-based) — run_ingest() đọc lại để
            # biết ghi Execute=DONE cho ĐÚNG dòng nào khi article/video xong.
            brief_path.write_text(
                json.dumps({"context": context, "execute_row": item["row"], **asdict(brief)},
                          ensure_ascii=False, indent=2),
                encoding="utf-8")

        # Article/video có thể ĐÃ xong từ trước (seen) -> cùng infographic vừa
        # sinh, có thể đủ CẢ 3 loại ngay trong lượt --draft này -> đánh dấu DONE
        # luôn (không cần đợi --ingest).
        if _is_fully_produced(context, seen):
            done_rows.append(item["row"])

    written = board.append_content_rows(rows)
    board.mark_execute_done(done_rows)
    if written:
        board.regroup_and_merge_content()   # merge dọc Timestamp+Context khi đủ 3 loại
    print(f"[draft] infographic sinh ngay: {infographic_done} | "
          f"yêu cầu article/video chuẩn bị: {prepared} (xem {drafts_dir}) | "
          f"Execute=DONE {len(done_rows)} dòng")
    if prepared:
        print("Nhờ Claude Code đọc các file *.prompt.md ở trên, viết JSON đúng schema "
              "vào *.article.json/*.video.json cạnh đó, rồi chạy:\n"
              "    python scripts/produce_from_sheet.py --ingest")
    return {"approved": len(approved), "prepared": prepared,
            "infographic_done": infographic_done, "written": written}


def run_ingest(*, setup: bool = False) -> dict:
    """Nạp *.article.json/*.video.json (Claude Code đã viết) qua ĐÚNG schema
    fields/render/guardrail như chế độ gọi API -> ghi CONTENT + storage/output.
    Dọn file đã tiêu thụ; giữ lại *.prompt.md nào còn thiếu câu trả lời."""
    settings = load_settings()
    board = _open_board(settings, setup=setup)
    drafts_dir = Path(settings.get("storage.drafts_dir", "storage/production_drafts"))
    if not drafts_dir.exists() or not list(drafts_dir.glob("*.brief.json")):
        print(f"Không có bản nháp nào chờ ({drafts_dir}). Chạy --draft trước.")
        return {"ingested": 0, "skipped": 0, "pending": 0}

    seen = board.existing_content_keys()
    out_dir = Path(settings.get("storage.output_dir", "storage/output")) / _today()
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[list[str]] = []
    done_rows: list[int] = []   # dòng CONTEXT (1-based) đã đủ CẢ 3 loại -> Execute=DONE
    ingested = skipped = flagged = pending = 0
    for brief_path in sorted(drafts_dir.glob("*.brief.json")):
        slug = brief_path.name[: -len(".brief.json")]
        raw = json.loads(brief_path.read_text(encoding="utf-8"))
        context = raw.pop("context")
        # execute_row: bản nháp cũ (trước khi có Execute) không có khóa này ->
        # None -> KHÔNG đánh dấu DONE được (bản ghi cũ), vẫn ingest bình thường.
        execute_row = raw.pop("execute_row", None)
        brief = ProductionBrief(**raw)

        # Bối cảnh mở rộng (research) Claude Code viết ở BƯỚC 1 của _prompt_md —
        # KHÔNG bắt buộc; thiếu file -> brief.background giữ rỗng, guardrail vẫn
        # chạy bình thường (chỉ xét evidence).
        background_path = drafts_dir / f"{slug}.background.txt"
        if background_path.exists():
            brief.background = background_path.read_text(encoding="utf-8").strip()

        remaining = False
        for type_, ctype in (("article", "article"), ("video", "video_script")):
            answer_path = drafts_dir / f"{slug}.{type_}.json"
            prompt_path = drafts_dir / f"{slug}.{type_}.prompt.md"
            if not answer_path.exists():
                if prompt_path.exists():
                    remaining = True
                continue
            if (context, ctype) in seen:
                answer_path.unlink(missing_ok=True)
                prompt_path.unlink(missing_ok=True)
                skipped += 1
                continue
            data = json.loads(answer_path.read_text(encoding="utf-8"))
            draft = draft_to_content_draft(type_, data, brief)
            fn = out_dir / f"{slug}-{ctype}.md"
            fn.write_text(draft.body, encoding="utf-8")
            preview = draft.body if len(draft.body) <= _OUTPUT_PREVIEW else \
                draft.body[:_OUTPUT_PREVIEW] + f"\n…(xem {fn.name})"
            rows.append(content_row(context=context, type_=ctype,
                                    status="DONE" if draft.is_clean else "ERROR",
                                    output=preview, notes="; ".join(draft.compliance_issues)))
            seen.add((context, ctype))
            ingested += 1
            flagged += 0 if draft.is_clean else 1
            answer_path.unlink(missing_ok=True)
            prompt_path.unlink(missing_ok=True)

        if remaining:
            pending += 1
        else:
            brief_path.unlink(missing_ok=True)
            background_path.unlink(missing_ok=True)
            if execute_row is not None and _is_fully_produced(context, seen):
                done_rows.append(execute_row)

    written = board.append_content_rows(rows)
    board.mark_execute_done(done_rows)
    if written:
        board.regroup_and_merge_content()   # merge dọc Timestamp+Context khi đủ 3 loại
    print(f"[ingest] sản phẩm mới: {ingested} | bỏ qua (đã có): {skipped} | "
          f"dính compliance: {flagged} | còn chờ Claude viết: {pending} | ghi CONTENT {written} | "
          f"Execute=DONE {len(done_rows)} dòng")
    return {"ingested": ingested, "skipped": skipped, "flagged": flagged,
            "pending": pending, "written": written}


def _summary(approved, produced, skipped, flagged, use_llm, u, out_dir) -> None:
    print("\n========== PRODUCTION -> CONTENT (cổng 2) ==========")
    print(f"APPROVED đọc: {approved} | sản phẩm mới: {produced} | "
          f"bỏ qua (đã có): {skipped} | dính compliance: {flagged}")
    n = produced or 1
    if use_llm and u.get("calls"):
        print(f"LLM Producers (Sonnet thật): {u['calls']} lượt ({u.get('by_model', {})}) | "
              f"in {u['in_tokens']} / out {u['out_tokens']} tok | ~${u['cost_usd']:.4f} "
              f"(~${u['cost_usd'] / n:.4f}/sản phẩm)")
    else:
        print(f"LLM Producers: MOCK/$0 (không gọi API). "
              f"Ước tính nếu bật Sonnet: ~${u.get('cost_usd', 0):.4f}.")
    print(f"File đầy đủ: {out_dir}  |  Mở tab CONTENT để duyệt sản phẩm (cột Status).")


def _parse_args(argv: list[str]):
    import argparse
    ap = argparse.ArgumentParser(description="Sinh sản phẩm từ CONTEXT.Status=APPROVE (cổng 2).")
    ap.add_argument("--limit", type=int, default=5, help="Số bài APPROVE tối đa xử lý.")
    ap.add_argument("--offline", action="store_true", help="Ép MockLLM ($0, không gọi API).")
    ap.add_argument("--draft", action="store_true",
                    help="Chuẩn bị request cho Claude Code viết article/video (không gọi API).")
    ap.add_argument("--ingest", action="store_true",
                    help="Nạp *.article.json/*.video.json Claude Code đã viết -> CONTENT.")
    ap.add_argument("--model", choices=["sonnet", "opus"], default=None,
                    help="Chỉ áp dụng cho chế độ gọi API (không --draft/--ingest): "
                        "ghi đè llm.content_model — opus chất lượng cao hơn, đắt hơn.")
    ap.add_argument("--setup", action="store_true",
                    help="Ép chạy đầy đủ ensure_tabs (tạo/seed/format tab) dù header đã đúng "
                        "— mặc định BỎ QUA để giảm lượt gọi Sheets API (né quota 429).")
    ap.add_argument("--sync-only", action="store_true",
                    help="Chỉ đồng bộ Execute=RUN cho các dòng Status=APPROVE ($0, không "
                        "full-fetch/gọi LLM) — dùng khi vừa duyệt tay trên Sheet và muốn "
                        "Execute=RUN ngay, không chờ lịch crawl/--draft tới lượt.")
    return ap.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    if args.sync_only:
        run_sync_only()
    elif args.draft:
        run_draft(limit=args.limit, setup=args.setup)
    elif args.ingest:
        run_ingest(setup=args.setup)
    else:
        run(limit=args.limit, offline=args.offline, model=args.model, setup=args.setup)
