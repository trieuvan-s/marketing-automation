"""GIAI ĐOẠN SẢN XUẤT (cổng 2): CONTEXT.Status=APPROVE -> sinh sản phẩm.

Luồng:
  CONTEXT (Status=APPROVE)  --đọc-->  full-fetch thân bài thật (tất định, $0)
    -->  Production (LLM ĐẮT: Sonnet, đã qua cổng 1)
    • ARTICLE (Phase 4.9 — Brief → route-once (đóng băng) → run_writer_with_retry,
      xem agents/brief.py + agents/route_once.py + agents/writer.py)
    • VideoScriptAgent     (kịch bản video, LLM, schema JSON — đường 3-agent cũ)
    • InfographicSpecAgent (Phase 4.11 — Composer: LLM Loại B/haiku nén facts[]
      + RouterDecision thành spec 8 trường, KHÔNG còn tất định/$0 thuần)
  --guardrail-->  compliance (disclaimer/claim cấm) + chặn bịa số (so evidence,
    Mục C: chấp nhận số làm tròn hợp lý khớp facts[].canonical_value)
  --ghi-->  tab CONTENT (Context|Type|Status|Output) + <data_root>/output/<ngày>/
    (data_root NGOÀI repo, xem Phase DATA-ROOT / config.data_path())
  --> người duyệt xem & duyệt sản phẩm (cổng 2) --> Publish (giai đoạn sau).

Nguyên tắc: LLM đắt CHỈ chạy ở đây (sau cổng 1). Đã sinh rồi thì bỏ qua (Lớp 5
Phase 2: dedup (TopicKey,Type) trong CONTENT, đọc TRỰC TIẾP cột TopicKey — TUYỆT
ĐỐI không tra theo Context/Source sống, xem sheets_board.content_topic_keys())
-> KHỎI tốn Sonnet lại. LÙI MƯỢT: thiếu SDK/khóa -> Mock ($0), agent tự dựng
khung tất định, KHÔNG crash. Văn phong agent nạp từ tab PROMPTS (Name|Version|
Enable) -> prompts/<Name>.<Version>.md; thiếu -> default code.

PHASE 4.9 — CẦU NỐI writer retry vào vòng thật (đóng gap Phase 4.5): trước phase
này, agents/writer.run_writer_with_retry() (retry/backoff/FAILED/NEEDS_HUMAN,
Phase 4.5) CHƯA từng được gọi bởi bất kỳ script sản xuất thật nào — chỉ được
kiểm bằng script tạm khi validate Phase 4.6/4.7/4.8. `run()` (chế độ gọi API
thật, KHÔNG phải --draft/--ingest) giờ dùng ĐÚNG pipeline này cho ARTICLE:
  1. run_brief() trích facts[] (Mục C: raw/canonical_value/approx).
  2. get_or_route() route-once — 1 chủ đề CHỈ route 1 lần, đóng băng (agents/
     route_once.RouterDecisionStore, storage theo router.decisions_path).
  3. run_writer_with_retry() -> WriterOutcome.DONE/FAILED/NEEDS_HUMAN, map vào
     cột CONTEXT.Execute (xem sheets_board.py, khối comment cạnh CONTEXT_HEADER):
       DONE         -> ghi CONTENT, Execute=DONE (nếu video+infographic cũng
                        xong — SheetsBoard.set_execute_values qua _is_fully_produced).
       FAILED       -> Execute=FAILED, KHÔNG ghi CONTENT (chưa có nội dung thật),
                        TỰ ĐỘNG tái chạy được lượt sau (không cần người reset).
       NEEDS_HUMAN  -> Execute=NEEDS_HUMAN, VẪN ghi CONTENT (Status=ERROR, để
                        người xem lý do reject), CHỜ người đổi Execute về RUN
                        (móc cho nút MANUAL của Phase 5, chưa có UI riêng).
Video/Infographic KHÔNG đổi — vẫn qua đường 3-agent Producer cũ (chưa có
RouterDecision, xem báo cáo Phase 4.7 §3: kiến trúc hiện tại chỉ ARTICLE tiêu
thụ router). --draft/--ingest (chế độ Claude Code tự viết) KHÔNG đổi ở phase
này — vẫn dùng voice-lock fallback tĩnh (assemble_voice(None)), ngoài phạm vi.

HAI CHẾ ĐỘ điền nội dung article/video (infographic luôn tất định, $0):
  1. Mặc định / --offline: gọi AnthropicLLM API (cần ANTHROPIC_API_KEY riêng) —
     để dành cho automation 100% không người trông (tương lai, xem CLAUDE.md).
  2. --draft / --ingest: KHÔNG cần API key riêng — nhờ Claude Code (phiên chat
     đang chạy, dùng gói Pro/Max/Team) viết nội dung. --draft chuẩn bị prompt
     vào storage.drafts_dir/<ngày>/ (theo NGÀY, như output — dễ nhận
     biết bản nháp mới/tồn đọng), Claude đọc + viết JSON đúng schema cạnh đó,
     --ingest quét TẤT CẢ thư mục ngày rồi nạp lại qua ĐÚNG guardrail/CONTENT
     như chế độ 1 (không phân biệt "ai viết", không phân biệt "ngày nào").
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
from twmkt.agents.base import MockLLM  # noqa: E402
from twmkt.agents.brief import BriefResult, run_brief  # noqa: E402
from twmkt.agents.production import (  # noqa: E402
    AnalysisWriterAgent, InfographicSpecAgent, ProductionBrief, VideoScriptAgent,
    all_production_agents, analysis_fields_from_data, apply_guardrails,
    build_analysis_prompt, build_video_prompt, render_analysis, render_video,
    video_fields_from_data,
)
from twmkt.agents.prompts import resolve_prompts  # noqa: E402
from twmkt.agents.route_once import RouterDecisionStore, get_or_route  # noqa: E402
from twmkt.agents.voice import assemble_voice  # noqa: E402
from twmkt.agents.writer import WriterOutcome, run_writer_with_retry  # noqa: E402
from twmkt.config import data_path, load_settings  # noqa: E402
from twmkt.curation.keys import assign_topic_key  # noqa: E402
from twmkt.models import ContentDraft, ContentFormat, Source  # noqa: E402
from twmkt.sheets_board import SheetsBoard, content_row, facts_to_json  # noqa: E402
from twmkt.utils.telegram_notifier import make_notifier  # noqa: E402

_OUTPUT_PREVIEW = 1500   # số ký tự Output đưa lên Sheet (đủ xem; full lưu ra file)
_ALL_TYPES = ("infographic", "article", "video")   # 3 loại all_production_agents() sinh (C7: "video" khớp Sheet)
_DEFAULT_ACTOR = "[user request]"


def _writer_notify_adapter(notifier):
    """Chuyển Notifier.notify(event, **ctx) (utils/telegram_notifier.py) sang
    đúng chữ ký notify(event, info: dict) mà agents.writer.run_writer_with_retry
    đã chừa từ Phase 4.5 — cầu nối 1 dòng, KHÔNG đổi 1 trong 2 interface gốc."""
    return lambda event, info: notifier.notify(event, **info)


def _is_fully_produced(topic_key: str, seen: set[tuple[str, str]]) -> bool:
    """True nếu CẢ 3 loại (infographic/article/video) của chủ đề (tra
    theo `topic_key` — Lớp 5 Phase 2, KHÔNG theo Context) đã có trong CONTENT
    (`seen`) — tín hiệu để đặt Execute=DONE (idempotent). Dùng cho run_draft()/
    run_ingest() (đường --draft/--ingest, KHÔNG đọc RouterDecision.output_
    channels — NGOÀI PHẠM VI Phase 4.13, xem run_draft)."""
    return all((topic_key, t) in seen for t in _ALL_TYPES)


# Phase 4.13 Mục A: output_channels dùng tên "video" (khớp RouterDecision),
# CONTENT Type cũng là "video" (C7 2026-07-20: khớp Sheet thật + đồng bộ với
# ContentFormat.VIDEO_SCRIPT.value đã đổi). Trước đây content-type là
# "video_script" nên map ở đây có tác dụng; nay 2 tên TRÙNG nhưng GIỮ map tường
# minh để nếu tách lại vocabulary về sau chỉ sửa 1 chỗ.
_CHANNEL_TO_TYPE = {"article": "article", "infographic": "infographic", "video": "video"}


def _is_fully_produced_channels(topic_key: str, seen: set[tuple[str, str]], channels: dict) -> bool:
    """True nếu MỌI tuyến channels[c]=True của chủ đề (tra theo `topic_key` —
    Lớp 5 Phase 2, KHÔNG theo Context) đã có trong CONTENT (`seen`) — tuyến
    channels[c]=False KHÔNG chặn DONE (chủ động không sinh, KHÔNG phải thiếu).
    Dùng cho run() (Phase 4.9+, có RouterDecision thật)."""
    return all((topic_key, _CHANNEL_TO_TYPE[c]) in seen for c, enabled in channels.items() if enabled)


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
        setup: bool = False, topic_keys: list[str] | None = None) -> dict:
    """Sản xuất cho các dòng CONTEXT Status=APPROVE + Execute∈{RUN,FAILED}.

    `topic_keys` (VIỆC 5.1 — điểm ráp webhook per-topic):
      - None (mặc định) -> HÀNH VI CŨ: quét TẤT CẢ dòng đủ điều kiện, cắt theo
        `limit`. Scheduler 30' (system_power_on) KHÔNG phải sửa — tương thích ngược.
      - list -> CHỈ xử lý các dòng có TopicKey nằm trong danh sách (dòng user bấm
        Execute qua webhook). `limit` BỊ BỎ QUA để không âm thầm cắt cụt danh sách.
    Trả dict tổng hợp {approved, produced, skipped}. `run()` là NƠI DUY NHẤT ghi
    cờ Execute (DONE/FAILED/NEEDS_HUMAN) lên Sheet — webhook chỉ đọc lại để trả
    trạng thái (xem api/, VIỆC 5.2-5.5), KHÔNG tự ghi Execute (tránh 2 nguồn
    trạng thái, VIỆC 5.2/5.3)."""
    settings = load_settings()
    board = _open_board(settings, setup=setup)
    notifier = make_notifier(settings)   # PHASE TELE — no-op êm nếu chưa cấu hình; KHỞI TẠO Ở TẦNG CAO NHẤT

    # --- LLM ĐẮT cho Producers video/infographic (đường 3-agent cũ, Sonnet mặc
    # định, --model opus nếu cần chất lượng cao hơn). LÙI MƯỢT CÓ CẢNH BÁO:
    # banner IN RÕ, không im lặng. --offline luôn ép Mock (kể cả có key) để
    # kiểm chứng $0.
    llm = factory.llm_status(settings)
    use_llm = (not offline) and llm.use_llm
    banner = ("LLM active: MOCK ($0 fallback) — lý do: --offline (ép mock)"
             if offline and llm.use_llm else llm.banner)
    print(banner)
    content_llm = factory.build_content_llm(settings, offline=not use_llm, model=model)
    engine = factory.model_engine_label(llm.content_model, use_llm=use_llm)
    board.log("INFO", banner, engine=engine)

    # --- LLM RIÊNG cho ARTICLE (Phase 4.9: Brief -> route-once -> Writer-with-
    # retry) — adapter make_llm/step_model, SONG SONG với content_llm/LLMRouter
    # ở trên (KHÔNG dùng chung). --offline ép MockLLM ($0) cho đường này luôn,
    # khớp tinh thần "kiểm chứng $0" của cờ.
    route_llm = MockLLM() if offline else factory.make_llm(settings)
    writer_llm = MockLLM() if offline else factory.build_writer_llm(settings)
    router_store = RouterDecisionStore(
        data_path(settings.get("router.decisions_path", "state/router_decisions.json"), settings=settings))

    # Execute: dòng vừa APPROVE (Execute rỗng) -> tự đặt RUN; rồi xử lý dòng
    # Status=APPROVE VÀ Execute ĐANG "RUN" (mới/đã reset tay) HOẶC "FAILED"
    # (Phase 4.9: lỗi TẠM THỜI của bài article — TỰ ĐỘNG tái chạy, không cần
    # người reset). Execute=DONE (xong hẳn) / NEEDS_HUMAN (chờ người) -> bỏ qua,
    # idempotent — produce chạy lại KHÔNG sinh Content trùng, KHÔNG đụng dòng
    # đang chờ người can thiệp.
    board.sync_approve_execute_flags()
    approved = [a for a in board.read_approved_context() if a["execute"] in ("RUN", "FAILED")]
    # VIỆC 5.1: webhook per-topic -> lọc ĐÚNG các dòng user bấm (khớp TopicKey
    # đã lưu ở cột CONTEXT). None = quét cả lô như cũ. Dòng chưa có TopicKey
    # (rỗng) KHÔNG khớp bất kỳ key nào -> tự loại, đúng ý (không target được).
    if topic_keys is not None:
        wanted = set(topic_keys)
        approved = [a for a in approved if a["topic_key"] in wanted]
    if not approved:
        print("Không có dòng CONTEXT nào Status=APPROVE và Execute=RUN/FAILED (chưa sản xuất "
              "hoặc đang chờ NEEDS_HUMAN). Duyệt ở tab CONTEXT trước.")
        return {"approved": 0, "produced": 0, "skipped": 0}
    # `limit` CHỈ áp đường quét-cả-lô. Khi lọc theo topic_keys, xử ĐỦ danh sách
    # (BỎ QUA limit — không để limit=5 cắt cụt danh sách user bấm, VIỆC 5.1).
    if topic_keys is None:
        approved = approved[:limit]

    # PROMPTS: đọc LIVE tab (Name|Version|Enable) -> resolve prompts/<name>.<v>.md;
    # thiếu tab/dòng/file -> giữ default nội bộ trong code (KHÔNG crash). LƯU Ý
    # (Phase 4.9): override "analysis" (article) KHÔNG còn áp dụng — đường
    # article mới dùng voice-lock động (agents/voice.assemble_voice theo
    # RouterDecision), KHÔNG qua prompt_overrides; override "video"/
    # "infographic" vẫn áp dụng như cũ.
    default_prompts = {a.prompt_name: a.system for a in all_production_agents()}
    prompt_overrides = resolve_prompts(
        board.read_prompt_versions(), default_prompts,
        prompts_dir=settings.get("prompts.dir", "prompts"))

    # Full-fetch thân bài thật (tất định, $0) cho từng dòng APPROVE -> evidence
    # thật để LLM bám + chống bịa số (khớp nguồn đăng ký theo TÊN MIỀN).
    sources = board.read_sources() or factory.build_sources(settings)
    html_collector = factory.build_collector_for_source(Source("_", "_", fetch_type="html"), settings)

    seen = board.existing_content_keys()   # Lớp 5 Phase 2: (TopicKey, Type) đã sinh -> bỏ qua
    # Context của các dòng CONTENT cũ có Type nhưng TopicKey RỖNG (chưa backfill/
    # rekey) — INVARIANT cấm auto-map các dòng này theo Context, xem nhánh
    # needs_human_rows bên dưới (Lead đã chốt: NEEDS_HUMAN + bỏ qua, không liều
    # sinh tiếp có thể đụng dữ liệu không định danh được).
    missing_key_contexts = set(board.existing_content_missing_keys())
    out_dir = data_path(settings.get("storage.output_dir", "output"), _today(), settings=settings)
    out_dir.mkdir(parents=True, exist_ok=True)
    approx_tol = float(settings.get("guardrail.approx_tolerance_pct", 5)) / 100

    rows: list[list[str]] = []
    done_rows: list[int] = []          # đủ CẢ 3 loại -> Execute=DONE
    failed_rows: list[int] = []        # Phase 4.9: article FAILED (lỗi tạm thời) -> Execute=FAILED
    needs_human_rows: list[int] = []   # Phase 4.9: article NEEDS_HUMAN (guardrail reject) -> chờ người
    topic_key_updates: dict[int, str] = {}   # Phase 1R.2: dòng CONTEXT vừa được GÁN khoá mới -> ghi lại NGAY
    produced = skipped = flagged = 0
    for item in approved:
        notifier.notify("start", topic=item["context"], row=item["row"], actor=_DEFAULT_ACTOR)

        # Lớp 5 Phase 2 — INVARIANT: match-or-insert TRA THEO TopicKey ĐÃ LƯU,
        # TUYỆT ĐỐI không tự đoán/auto-map theo Context. Nếu CONTENT đã có dòng
        # (Type bất kỳ) CÙNG Context này nhưng TopicKey RỖNG (dữ liệu cũ chưa
        # backfill/rekey — xem existing_content_missing_keys), KHÔNG THỂ biết
        # chắc dòng đó có trùng chủ đề với item hiện tại hay không theo khoá ->
        # dừng lại, đặt NEEDS_HUMAN, KHÔNG sản xuất (tránh liều sinh tạo bản
        # trùng "vô hình" với dòng cũ không định danh được).
        if item["context"] in missing_key_contexts:
            needs_human_rows.append(item["row"])
            reason = ("CONTENT đã có dòng cùng Context nhưng TopicKey rỗng (dữ liệu cũ "
                     "chưa backfill/rekey) -> không thể match-or-insert theo khoá an toàn. "
                     "Chạy scripts/backfill_topic_keys.py rồi đổi Execute về RUN.")
            notifier.notify("needs_human", topic=item["context"], row=item["row"], reason=reason)
            board.log("WARN", f"Lớp5 Phase2: '{item['context'][:60]}' CONTENT thiếu TopicKey -> NEEDS_HUMAN, bỏ qua.")
            continue

        evidence = fetch_full_evidence(html_collector, sources, item["source"], item["hook"])
        # Lớp 5 Phase 1R.2 — WRITE-ONCE: assign_topic_key() trả NGUYÊN khoá đã
        # có ở CONTEXT (item["topic_key"], có thể rỗng nếu dòng CHƯA từng gán)
        # — KHÔNG bao giờ tính lại 1 dòng ĐÃ có khoá, kể cả khi Source url đổi.
        # Dòng CHƯA có khoá -> tính từ Source url, hoặc gán SURROGATE uuid4 nếu
        # không có url hợp lệ (KHÔNG BAO GIỜ còn để lại ""). Khoá MỚI gán phải
        # ghi NGAY xuống CONTEXT (topic_key_updates, ghi 1 lượt cuối hàm) để
        # lần chạy SAU đọc lại ĐÚNG khoá này — write-once chỉ có hiệu lực khi
        # đã persist.
        existing_key = item.get("topic_key", "")
        topic_key = assign_topic_key(existing_key, url=item["source"])
        if topic_key != existing_key:
            topic_key_updates[item["row"]] = topic_key

        # --- ARTICLE (Phase 4.9): Brief -> route-once (đóng băng) -> Writer-
        # with-retry. Bỏ qua HOÀN TOÀN nếu đã có trong CONTENT (idempotent,
        # KHÔNG tốn thêm lượt Brief/Router/Writer cho bài đã DONE).
        write_article = (topic_key, "article") not in seen
        # Phase 4.12: run_brief() trả BriefResult (facts + no_numeric_content)
        # — phân biệt facts=[] RỖNG-HỢP-LỆ (Brief chạy trọn vẹn, xác nhận tin
        # thuần định tính) vs RỖNG-DO-HỎNG (LLM lỗi/timeout — cờ luôn False).
        brief_result = (run_brief(route_llm, evidence, model=factory.step_model(settings, "brief"),
                                  fail_loud=factory.is_fail_loud_step(settings, "brief"),
                                  settings=settings)
                       if write_article else BriefResult())
        brief = ProductionBrief(
            title=item["context"], hook=item["hook"], tickers=item["tickers"],
            group=item["group"], topic=item["topic"], url=item["source"],
            evidence=evidence, facts=brief_result.facts,
            no_numeric_content=brief_result.no_numeric_content,
        )
        # Production Factory Phase 1.3 — snapshot facts[] MÁY-SỞ-HỮU ghi vào MỌI
        # dòng CONTENT của chủ đề này (cột Facts, xem comment CONTENT_HEADER ở
        # sheets_board.py) — nguồn sự thật cho verify_spec() (guardrail lần 2,
        # media_factory/spec.py) chạy TRƯỚC KHI RENDER (Phase 1.3), TÁCH biệt
        # facts[] còn trong RAM ở tiến trình này (không đồng bộ giữa nhiều máy —
        # đúng bug Fix (a) đã sửa cho CONTEXT, không lặp lại cho Production
        # Factory qua data_root).
        facts_json = facts_to_json(brief.facts)

        # route-once (Mục A): gọi KHÔNG ĐIỀU KIỆN cho MỌI item (kể cả khi
        # article đã DONE từ trước) — cache-hit tức thời khi đã đóng băng
        # (KHÔNG tốn lượt LLM), cần thiết để VIDEO/INFOGRAPHIC (Phase 4.10)
        # cũng đọc ĐÚNG quyết định article của CÙNG chủ đề (nhất quán khung
        # multi-content, xem báo cáo Phase 4.7 §3).
        decision = get_or_route(
            route_llm, brief, store=router_store, key=_slug(item["context"]),
            model=factory.step_model(settings, "router"),
            fail_loud=factory.is_fail_loud_step(settings, "router"))
        # Phase 4.13 Mục A: tuyến nào ĐƯỢC sinh cho chủ đề này — quyết-định-từ-
        # đầu của router (đóng băng CÙNG decision), THAY nhánh "SKIPPED-vì-rỗng"
        # phản ứng-sau của Phase 4.12 (xem nhánh infographic bên dưới).
        channels = decision.output_channels

        article_outcome = None
        if not write_article:
            skipped += 1
        elif not channels.get("article", True):
            reason = (f"Router quyết định tuyến article không hợp tin này: "
                     f"{decision.channel_rationale.get('article') or '(router không cho lý do)'}")
            rows.append(content_row(context=item["context"], type_="article",
                                    status="SKIPPED", output="", notes=reason,
                                    topic_key=topic_key, facts=facts_json))
            seen.add((topic_key, "article"))
            skipped += 1
            notifier.notify("skipped", topic=item["context"], type="article", reason=reason)
        else:
            r = run_writer_with_retry(
                writer_llm, brief, decision, settings=settings,
                model=factory.step_model(settings, "writer"),
                notify=_writer_notify_adapter(notifier))
            article_outcome = r.outcome
            if r.outcome == WriterOutcome.DONE:
                fn = out_dir / f"{_slug(item['context'])}-article.md"
                fn.write_text(r.draft.body, encoding="utf-8")
                preview = r.draft.body if len(r.draft.body) <= _OUTPUT_PREVIEW else \
                    r.draft.body[:_OUTPUT_PREVIEW] + f"\n…(xem {fn.name})"
                rows.append(content_row(context=item["context"], type_="article",
                                        status="DONE", output=preview, notes="",
                                        topic_key=topic_key, facts=facts_json))
                seen.add((topic_key, "article"))
                produced += 1
                notifier.notify("draft_changed", topic=item["context"], type="article", status="DONE")
            elif r.outcome == WriterOutcome.NEEDS_HUMAN:
                # LLM ĐÃ trả lời nhưng guardrail reject -> VẪN ghi CONTENT (Status=
                # ERROR) để người xem lý do, nhưng KHÔNG seen.add (chưa coi là xong).
                note = "; ".join(r.draft.compliance_issues)
                fn = out_dir / f"{_slug(item['context'])}-article.md"
                fn.write_text(r.draft.body, encoding="utf-8")
                preview = r.draft.body if len(r.draft.body) <= _OUTPUT_PREVIEW else \
                    r.draft.body[:_OUTPUT_PREVIEW] + f"\n…(xem {fn.name})"
                rows.append(content_row(context=item["context"], type_="article",
                                        status="ERROR", output=preview, notes=note,
                                        topic_key=topic_key, facts=facts_json))
                flagged += 1
                notifier.notify("error", topic=item["context"], type="article", issues=note)
            else:   # FAILED — hết retry (lỗi hạ tầng gọi LLM), KHÔNG có draft -> KHÔNG ghi CONTENT rác
                flagged += 1
                notifier.notify("error", topic=item["context"], type="article", issues=r.reason)

        # --- VIDEO/INFOGRAPHIC: VIDEO tiêu thụ CÙNG RouterDecision đã đóng
        # băng (voice-lock động + §4 chuyển-thể, Phase 4.10, xem VideoScriptAgent
        # .run) — nhất quán khung với article của CÙNG chủ đề. INFOGRAPHIC
        # (Phase 4.11 — Composer) CŨNG tiêu thụ decision + facts[], nhưng dùng
        # LLM RIÊNG (route_llm, alias 'composer'/haiku — Loại B rẻ, KHÔNG dùng
        # content_llm/Sonnet như video/article) — swap .llm/.model NGAY TRƯỚC
        # khi gọi run(), giữ nguyên instance đã áp prompt_overrides ở trên.
        # facts[] rỗng -> spec KHÔNG bịa nhãn, đánh dấu NEEDS_HUMAN (Status=
        # ERROR ở CONTENT, xem đoạn append issue bên dưới) — KHÔNG đụng Execute
        # cấp DÒNG (đó vẫn do riêng article_outcome quyết định, phạm vi 4.9).
        for agent in all_production_agents(content_llm, prompt_overrides=prompt_overrides):
            if isinstance(agent, AnalysisWriterAgent):
                continue   # article đã xử lý ở nhánh route-once+retry trên

            # Phase 4.13 Mục A: router QUYẾT NGAY TỪ ĐẦU tuyến này không hợp
            # (channels[ch]=False, đóng băng cùng RouterDecision) -> SKIPPED
            # HỢP LỆ, KHÔNG gọi agent (khỏi tốn lượt LLM) — THAY nhánh phản
            # ứng-sau "facts rỗng -> skip" của Phase 4.12 làm cơ chế CHÍNH.
            ch = ("infographic" if isinstance(agent, InfographicSpecAgent)
                 else "video" if isinstance(agent, VideoScriptAgent) else None)
            if ch is not None and not channels.get(ch, True):
                type_key = _CHANNEL_TO_TYPE[ch]
                if (topic_key, type_key) in seen:
                    skipped += 1
                    continue
                reason = (f"Router quyết định tuyến {ch} không hợp tin này: "
                         f"{decision.channel_rationale.get(ch) or '(router không cho lý do)'}")
                rows.append(content_row(context=item["context"], type_=type_key,
                                        status="SKIPPED", output="", notes=reason,
                                        topic_key=topic_key, facts=facts_json))
                seen.add((topic_key, type_key))
                skipped += 1
                notifier.notify("skipped", topic=item["context"], type=ch, reason=reason)
                continue

            # Phase 4.12 (thu hẹp phạm vi ở 4.13 — chỉ còn xử lý CA BẤT ĐỒNG):
            # router chọn infographic:true (đã qua cổng ở trên) NHƯNG Brief xác
            # nhận no_numeric_content=True (facts=[] hợp lệ, tin thuần định
            # tính) -> router "tưởng" có số nhưng Brief đọc kỹ hơn thấy không
            # có -> vẫn SKIP (không có gì để trình bày), NHƯNG log WARN để
            # tinh chỉnh prompt router (mục 3, "để tinh chỉnh"). facts[] rỗng
            # mà KHÔNG có cờ (Brief hỏng thật) vẫn giữ nguyên đường NEEDS_HUMAN
            # cũ bên dưới (Mục B item 3, KHÔNG đổi).
            if isinstance(agent, InfographicSpecAgent) and not brief.facts and brief.no_numeric_content:
                if (topic_key, "infographic") in seen:
                    skipped += 1
                    continue
                print(f"[CẢNH BÁO] router/brief bất đồng: router chọn infographic:true "
                     f"nhưng Brief xác nhận no_numeric_content=true (không có số) cho "
                     f"'{item['context'][:60]}' -> vẫn SKIP, cần tinh chỉnh prompt router.")
                reason = ("Router chọn infographic:true nhưng Brief xác nhận không có số "
                         "liệu (no_numeric_content=true) -> bất đồng router/brief, tạm SKIP")
                rows.append(content_row(context=item["context"], type_="infographic",
                                        status="SKIPPED", output="", notes=reason,
                                        topic_key=topic_key, facts=facts_json))
                seen.add((topic_key, "infographic"))
                skipped += 1
                notifier.notify("skipped", topic=item["context"], type="infographic", reason=reason)
                continue

            if isinstance(agent, VideoScriptAgent):
                raw_draft = agent.run(brief, decision)
            elif isinstance(agent, InfographicSpecAgent):
                agent.llm = route_llm
                agent.model = factory.step_model(settings, "composer")
                raw_draft = agent.run(brief, decision)
            else:
                raw_draft = agent.run(brief)
            draft = apply_guardrails(raw_draft, brief.evidence, brief.background,
                                     brief.facts, approx_tolerance=approx_tol)
            if isinstance(agent, InfographicSpecAgent) and not brief.facts:
                # Tới được đây nghĩa là no_numeric_content=False -> facts rỗng
                # DO Brief HỎNG THẬT (timeout/lỗi/parse hỏng), KHÔNG phải tin
                # định tính (nhánh đó đã "continue" ở trên) -> vẫn NEEDS_HUMAN.
                draft.compliance_issues.append(
                    "facts[] rỗng (Brief chưa trích được số liệu) -> NEEDS_HUMAN, "
                    "không bịa nhãn 'Số liệu N'")
            type_ = draft.fmt.value
            if (topic_key, type_) in seen:
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
                                    status=status, output=preview, notes=note,
                                    topic_key=topic_key, facts=facts_json))
            seen.add((topic_key, type_))
            produced += 1
            if draft.is_clean:
                notifier.notify("draft_changed", topic=item["context"], type=type_, status=status)
            else:
                flagged += 1
                notifier.notify("error", topic=item["context"], type=type_, issues=note)

        # Execute (Phase 4.9): article FAILED/NEEDS_HUMAN quyết định dòng CHƯA
        # xong (dù video/infographic có xong hay không); article DONE (hoặc đã
        # DONE từ trước, write_article=False) -> xét đủ MỌI tuyến channels[c]=
        # True (Phase 4.13 — tuyến router chủ động tắt KHÔNG chặn DONE nữa).
        if article_outcome == WriterOutcome.FAILED:
            failed_rows.append(item["row"])
        elif article_outcome == WriterOutcome.NEEDS_HUMAN:
            needs_human_rows.append(item["row"])
        elif _is_fully_produced_channels(topic_key, seen, channels):
            done_rows.append(item["row"])

    written = board.append_content_rows(rows)
    # 1 lượt gọi Sheets API duy nhất cho MỌI thay đổi Execute (né 429, cùng
    # triết lý retry/backoff hiện có) — thay vì gọi mark_execute_done() +
    # set_execute_values() riêng.
    execute_updates: dict[int, str] = {r: "DONE" for r in done_rows}
    execute_updates.update({r: "FAILED" for r in failed_rows})
    execute_updates.update({r: "NEEDS_HUMAN" for r in needs_human_rows})
    board.set_execute_values(execute_updates)   # idempotent: chạy lại lọc theo execute ở trên
    # Phase 1R.2 — persist khoá MỚI gán (write-once chỉ có hiệu lực SAU khi ghi
    # xuống Sheet; lần chạy sau đọc lại đúng khoá này qua item["topic_key"]).
    board.set_topic_key_values(topic_key_updates)
    if written:
        board.regroup_and_band_content()   # to nen/vien xen ke theo nhom TopicKey (Sheet UI cleanup Phase 1)
        notifier.notify("gate2_done", written=written, approved=len(approved))
    u = content_llm.usage.as_dict()
    board.log("INFO", f"TỔNG Production: approved {len(approved)} / sinh mới {produced} / "
                      f"bỏ qua {skipped} / dính compliance {flagged} / ghi CONTENT {written} / "
                      f"Execute=DONE {len(done_rows)} / FAILED {len(failed_rows)} / "
                      f"NEEDS_HUMAN {len(needs_human_rows)} dòng",
              engine=engine)
    _summary(len(approved), produced, skipped, flagged, use_llm, u, out_dir)
    return {"approved": len(approved), "produced": produced, "skipped": skipped,
            "flagged": flagged, "llm": u, "use_llm": use_llm, "written": written,
            "failed": len(failed_rows), "needs_human": len(needs_human_rows)}


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
    # CONTENT.Output video (docs/CONTENT_OUTPUT_SCHEMA.md) — CTA nằm trong
    # payload của scene cuối (visual_kind="outro"), KHÔNG còn field "cta" rời.
    "video": 'schema_version/title/scenes[{role,visual_kind,payload,narration}]/source/disclaimer',
}


def _prompt_md(slug: str, type_: str, user_prompt: str) -> str:
    system = AnalysisWriterAgent.system if type_ == "article" else VideoScriptAgent.system
    # Voice-lock: đường --draft KHÔNG đi qua Agent._ask() (không có LLMClient thật ở
    # đây — Claude Code tự đọc file .prompt.md này) nên phải nối riêng tại đây, chỉ
    # cho "article" theo đúng phạm vi hiện tại (xem agents/voice.py).
    if type_ == "article":
        voice = assemble_voice(None)   # đường LEGACY --draft, chưa chạy StructureRouter -> fallback S1+H3+D
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


def draft_to_content_draft(type_: str, data: dict, brief: ProductionBrief, *,
                           approx_tolerance: float = 0.05) -> ContentDraft:
    """Chuyển JSON Claude Code đã viết (schema article/video) -> ContentDraft đã
    qua guardrail (evidence + brief.background gộp lại; brief.facts (Mục C) cho
    phép số làm tròn hợp lý khớp canonical). Hàm THUẦN — DÙNG CHUNG bởi
    run_ingest() và test (không cần Sheets/mạng). `type_` = 'article' | 'video'."""
    if type_ == "article":
        title, sapo, sections, disclaimer, sources = analysis_fields_from_data(data, brief)
        body = render_analysis(title, sapo, sections, disclaimer, sources, brief)
        draft = ContentDraft(fmt=ContentFormat.ARTICLE, title=title, body=body, brief_topic=brief.topic)
    else:
        title, scenes, disclaimer = video_fields_from_data(data, brief)
        body = render_video(title, scenes, disclaimer, brief)
        draft = ContentDraft(fmt=ContentFormat.VIDEO_SCRIPT, title=title, body=body, brief_topic=brief.topic)
    return apply_guardrails(draft, brief.evidence, brief.background, brief.facts,
                            approx_tolerance=approx_tolerance)


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
    seen = board.existing_content_keys()   # Lớp 5 Phase 2: (TopicKey, Type)
    # Xem run() cho giải thích đầy đủ INVARIANT — đường --draft KHÔNG có vocab
    # Execute=NEEDS_HUMAN (chỉ mark_execute_done/DONE) nên chỉ bỏ qua + cảnh
    # báo console (KHÔNG tự đoán/auto-map theo Context).
    missing_key_contexts = set(board.existing_content_missing_keys())
    out_dir = data_path(settings.get("storage.output_dir", "output"), _today(), settings=settings)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Theo NGÀY (như storage/output/<ngày>) — trước đây ghi phẳng vào drafts_dir,
    # không phân biệt được bản nháp mới/cũ khi tồn đọng (vd chưa --ingest kịp).
    # drafts_base = gốc KHÔNG có ngày (dò bản nháp CŨ còn tồn đọng ở NGÀY TRƯỚC,
    # tránh chuẩn bị trùng); drafts_dir = nơi GHI file MỚI hôm nay.
    drafts_base = data_path(settings.get("storage.drafts_dir", "state/production_drafts"), settings=settings)
    drafts_dir = data_path(settings.get("storage.drafts_dir", "state/production_drafts"), _today(), settings=settings)

    rows: list[list[str]] = []
    done_rows: list[int] = []   # dòng CONTEXT (1-based) đã đủ CẢ 3 loại -> Execute=DONE
    topic_key_updates: dict[int, str] = {}   # Phase 1R.2: ghi lại khoá MỚI gán
    prepared = infographic_done = 0
    for item in approved:
        context = item["context"]
        # Lớp 5 Phase 2 — INVARIANT (xem run() cho giải thích đầy đủ): CONTENT
        # đã có dòng cùng Context nhưng TopicKey rỗng (dữ liệu cũ chưa backfill)
        # -> KHÔNG THỂ match-or-insert theo khoá an toàn -> bỏ qua HOÀN TOÀN,
        # cảnh báo console, KHÔNG tự đoán/auto-map theo Context.
        if context in missing_key_contexts:
            print(f"[CẢNH BÁO] Lớp5 Phase2: '{context[:60]}' CONTENT thiếu TopicKey "
                 "(dữ liệu cũ chưa backfill/rekey) -> bỏ qua, chạy "
                 "scripts/backfill_topic_keys.py trước.")
            continue

        evidence = fetch_full_evidence(html_collector, sources, item["source"], item["hook"])
        brief = ProductionBrief(
            title=context, hook=item["hook"], tickers=item["tickers"],
            group=item["group"], topic=item["topic"], url=item["source"], evidence=evidence,
        )
        slug = _slug(context)
        # Phase 1R.2 — WRITE-ONCE (xem run() cho giải thích đầy đủ).
        existing_key = item.get("topic_key", "")
        topic_key = assign_topic_key(existing_key, url=item["source"])
        if topic_key != existing_key:
            topic_key_updates[item["row"]] = topic_key

        # Infographic: sinh NGAY (không cần Claude Code) — NGOÀI PHẠM VI Phase
        # 4.9/4.10/4.11: đường --draft KHÔNG chạy run_brief() nên brief.facts
        # luôn rỗng ở đây -> InfographicSpecAgent (Phase 4.11 Composer) trả
        # spec RỖNG có chủ ý (_empty_infographic_spec, KHÔNG bịa), không phải
        # bug — biết trước, chưa wire facts[]/route-once cho đường thủ công này.
        if (topic_key, "infographic") not in seen:
            approx_tol = float(settings.get("guardrail.approx_tolerance_pct", 5)) / 100
            draft = apply_guardrails(InfographicSpecAgent(None).run(brief), brief.evidence,
                                     brief.background, brief.facts, approx_tolerance=approx_tol)
            fn = out_dir / f"{slug}-infographic.json"
            fn.write_text(draft.body, encoding="utf-8")
            rows.append(content_row(context=context, type_="infographic",
                                    status="DONE" if draft.is_clean else "ERROR",
                                    output=draft.body[:_OUTPUT_PREVIEW],
                                    notes="; ".join(draft.compliance_issues),
                                    topic_key=topic_key,
                                    facts=facts_to_json(brief.facts)))   # rỗng ở đường --draft (chưa wire run_brief())
            seen.add((topic_key, "infographic"))
            infographic_done += 1

        # Article/Video: chuẩn bị request cho Claude Code (bỏ qua nếu đã có
        # trong CONTENT, hoặc đã chuẩn bị/đã có câu trả lời đang chờ --ingest).
        need_brief = False
        for type_, ctype, prompt_fn in (
            ("article", "article", build_analysis_prompt),
            ("video", "video", build_video_prompt),
        ):
            if (topic_key, ctype) in seen:
                continue
            # Dò TOÀN BỘ thư mục ngày (kể cả ngày trước, tồn đọng chưa --ingest)
            # -> tránh chuẩn bị TRÙNG prompt cho cùng 1 topic đang chờ dở.
            if list(drafts_base.glob(f"*/{slug}.{type_}.json")):
                continue   # đã có câu trả lời (ngày nào đó), chờ --ingest
            if list(drafts_base.glob(f"*/{slug}.{type_}.prompt.md")):
                continue   # đã chuẩn bị (ngày nào đó), đang chờ Claude Code trả lời
            (drafts_dir / f"{slug}.{type_}.prompt.md").write_text(
                _prompt_md(slug, type_, prompt_fn(brief)), encoding="utf-8")
            need_brief = True
            prepared += 1
        brief_path = drafts_dir / f"{slug}.brief.json"
        if need_brief and not list(drafts_base.glob(f"*/{slug}.brief.json")):
            # execute_row: số dòng CONTEXT (1-based) — run_ingest() đọc lại để
            # biết ghi Execute=DONE cho ĐÚNG dòng nào khi article/video xong.
            brief_path.write_text(
                json.dumps({"context": context, "execute_row": item["row"], **asdict(brief)},
                          ensure_ascii=False, indent=2),
                encoding="utf-8")

        # Article/video có thể ĐÃ xong từ trước (seen) -> cùng infographic vừa
        # sinh, có thể đủ CẢ 3 loại ngay trong lượt --draft này -> đánh dấu DONE
        # luôn (không cần đợi --ingest).
        if _is_fully_produced(topic_key, seen):
            done_rows.append(item["row"])

    written = board.append_content_rows(rows)
    board.mark_execute_done(done_rows)
    board.set_topic_key_values(topic_key_updates)   # Phase 1R.2: persist khoá MỚI gán
    if written:
        board.regroup_and_band_content()   # to nen/vien xen ke theo nhom TopicKey (Sheet UI cleanup Phase 1)
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
    # Quét TẤT CẢ thư mục ngày (storage.drafts_dir/<ngày>/) — bản nháp có thể
    # tồn đọng từ ngày TRƯỚC nếu --ingest chưa chạy kịp, KHÔNG chỉ hôm nay.
    drafts_dir = data_path(settings.get("storage.drafts_dir", "state/production_drafts"), settings=settings)
    brief_paths = sorted(drafts_dir.glob("*/*.brief.json"))
    if not drafts_dir.exists() or not brief_paths:
        print(f"Không có bản nháp nào chờ ({drafts_dir}/<ngày>/). Chạy --draft trước.")
        return {"ingested": 0, "skipped": 0, "pending": 0}

    seen = board.existing_content_keys()   # Lớp 5 Phase 2: (TopicKey, Type)
    missing_key_contexts = set(board.existing_content_missing_keys())   # xem run()
    out_dir = data_path(settings.get("storage.output_dir", "output"), _today(), settings=settings)
    out_dir.mkdir(parents=True, exist_ok=True)

    approx_tol = float(settings.get("guardrail.approx_tolerance_pct", 5)) / 100
    rows: list[list[str]] = []
    done_rows: list[int] = []   # dòng CONTEXT (1-based) đã đủ CẢ 3 loại -> Execute=DONE
    ingested = skipped = flagged = pending = 0
    for brief_path in brief_paths:
        day_dir = brief_path.parent   # NGÀY bản nháp được tạo (có thể khác hôm nay)
        slug = brief_path.name[: -len(".brief.json")]
        raw = json.loads(brief_path.read_text(encoding="utf-8"))
        context = raw.pop("context")
        # execute_row: bản nháp cũ (trước khi có Execute) không có khóa này ->
        # None -> KHÔNG đánh dấu DONE được (bản ghi cũ), vẫn ingest bình thường.
        execute_row = raw.pop("execute_row", None)
        brief = ProductionBrief(**raw)

        # Lớp 5 Phase 2 — INVARIANT (xem run() cho giải thích đầy đủ): CONTENT
        # đã có dòng cùng Context nhưng TopicKey rỗng -> KHÔNG THỂ match-or-
        # insert an toàn -> bỏ qua HOÀN TOÀN (giữ nguyên *.prompt.md/*.json chờ
        # người xử lý thủ công), cảnh báo console, KHÔNG tự đoán/auto-map.
        if context in missing_key_contexts:
            print(f"[CẢNH BÁO] Lớp5 Phase2: '{context[:60]}' CONTENT thiếu TopicKey "
                 "(dữ liệu cũ chưa backfill/rekey) -> bỏ qua ingest, chạy "
                 "scripts/backfill_topic_keys.py trước.")
            pending += 1
            continue

        # Bối cảnh mở rộng (research) Claude Code viết ở BƯỚC 1 của _prompt_md —
        # KHÔNG bắt buộc; thiếu file -> brief.background giữ rỗng, guardrail vẫn
        # chạy bình thường (chỉ xét evidence).
        background_path = day_dir / f"{slug}.background.txt"
        if background_path.exists():
            brief.background = background_path.read_text(encoding="utf-8").strip()
        # Phase 1R.2: run_ingest() KHÔNG đọc lại CONTEXT.TopicKey hiện có (đọc
        # từ file *.brief.json đã lưu, không phải dòng CONTEXT sống) — NGOÀI
        # PHẠM VI đồng bộ write-once đầy đủ ở đây (đường --draft/--ingest cũ,
        # đã ghi nhận ở các phase trước). assign_topic_key("", ...) đảm bảo
        # KHÔNG còn để lại "" (URL hợp lệ -> khoá tất định khớp CONTEXT nếu
        # CONTEXT cũng chưa có; không URL -> surrogate MỚI, có thể lệch
        # CONTEXT nếu CONTEXT đã có surrogate khác — chấp nhận được vì đường
        # này hiếm khi chạy cho chủ đề không-URL).
        topic_key = assign_topic_key("", url=brief.url)

        remaining = False
        for type_, ctype in (("article", "article"), ("video", "video")):
            answer_path = day_dir / f"{slug}.{type_}.json"
            prompt_path = day_dir / f"{slug}.{type_}.prompt.md"
            if not answer_path.exists():
                if prompt_path.exists():
                    remaining = True
                continue
            if (topic_key, ctype) in seen:
                answer_path.unlink(missing_ok=True)
                prompt_path.unlink(missing_ok=True)
                skipped += 1
                continue
            data = json.loads(answer_path.read_text(encoding="utf-8"))
            draft = draft_to_content_draft(type_, data, brief, approx_tolerance=approx_tol)
            fn = out_dir / f"{slug}-{ctype}.md"
            fn.write_text(draft.body, encoding="utf-8")
            preview = draft.body if len(draft.body) <= _OUTPUT_PREVIEW else \
                draft.body[:_OUTPUT_PREVIEW] + f"\n…(xem {fn.name})"
            rows.append(content_row(context=context, type_=ctype,
                                    status="DONE" if draft.is_clean else "ERROR",
                                    output=preview, notes="; ".join(draft.compliance_issues),
                                    topic_key=topic_key,
                                    facts=facts_to_json(brief.facts)))   # rỗng ở đường --ingest (chưa wire run_brief())
            seen.add((topic_key, ctype))
            ingested += 1
            flagged += 0 if draft.is_clean else 1
            answer_path.unlink(missing_ok=True)
            prompt_path.unlink(missing_ok=True)

        if remaining:
            pending += 1
        else:
            brief_path.unlink(missing_ok=True)
            background_path.unlink(missing_ok=True)
            if execute_row is not None and _is_fully_produced(topic_key, seen):
                done_rows.append(execute_row)

    written = board.append_content_rows(rows)
    board.mark_execute_done(done_rows)
    if written:
        board.regroup_and_band_content()   # to nen/vien xen ke theo nhom TopicKey (Sheet UI cleanup Phase 1)
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
