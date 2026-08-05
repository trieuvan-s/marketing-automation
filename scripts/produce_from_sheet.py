"""GIAI ĐOẠN SẢN XUẤT (cổng 2): CONTEXT.Status=APPROVE -> sinh sản phẩm.

Luồng:
  CONTEXT (Status=APPROVE)  --đọc-->  full-fetch thân bài thật (tất định, $0)
    -->  Production (LLM ĐẮT: Sonnet, đã qua cổng 1)
    • ARTICLE (Phase 4.9 — Brief → route-once (đóng băng) → run_writer_with_retry,
      xem agents/brief.py + agents/route_once.py + agents/writer.py)
    • VideoScriptAgent     (kịch bản video, LLM, schema JSON — đường 3-agent cũ)
    • InfographicSpecAgent (Phase 4.11 — Composer: LLM Loại B/haiku nén content_units[]
      + RouterDecision thành spec 8 trường, KHÔNG còn tất định/$0 thuần)
  --guardrail-->  compliance (disclaimer/claim cấm) + chặn bịa số (so evidence,
    Mục C: chấp nhận số làm tròn hợp lý khớp content_units[].canonical_value)
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
  1. run_brief() trích content_units[] (Mục C: raw/canonical_value/approx).
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
sys.path.insert(0, str(REPO_ROOT))
# SỬA LỖI THẬT (2026-08-04, xem run_scheduler.py cùng lý do) -- ép cwd =
# REPO_ROOT NGAY ĐẦU để chạy đúng bất kể ai/gì khởi động tiến trình.
os.chdir(REPO_ROOT)

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

from twmkt import factory  # noqa: E402
from twmkt.agents.base import MockLLM  # noqa: E402
from twmkt.agents.brief import BriefResult, run_brief  # noqa: E402
from twmkt.agents.production import (  # noqa: E402
    AnalysisWriterAgent, InfographicSpecAgent, InsufficientScenesError, ProductionBrief,
    VideoScriptAgent, all_production_agents, analysis_fields_from_data, apply_guardrails,
    build_analysis_prompt, build_video_prompt, render_analysis, render_video,
    video_fields_from_data,
)
from twmkt.agents.prompts import resolve_prompts  # noqa: E402
from twmkt.agents.route_once import RouterDecisionStore, get_or_route  # noqa: E402
from twmkt.agents.voice import assemble_voice  # noqa: E402
from twmkt.agents.writer import WriterOutcome, run_writer_with_retry  # noqa: E402
from twmkt.config import data_path, load_settings  # noqa: E402
from twmkt.models import ContentDraft, ContentFormat, Source  # noqa: E402
from twmkt.sheets_board import SheetsBoard, content_row, facts_to_json  # noqa: E402
from twmkt.utils.telegram_notifier import make_notifier  # noqa: E402

from store import pipeline_store as ps  # noqa: E402
from twmkt.sheets_board import _now_ddmmyyyy  # noqa: E402

# store phải giữ NGUYÊN VĂN (Lead xác nhận 2026-07-27, sau khi bug
# render_production_assets.py lộ ra store cũng chỉ nhận bản cắt) -- KHÔNG còn
# hằng số/preview ở tầng ghi store. Truncate hiển thị (nếu cần) giờ CHỈ còn ở
# điểm đẩy sang Sheet, xem store/sync_service.py::render_content_to_sheet().
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

# P2 store-as-truth Bước 4 — Output Type (sheets_board.OUTPUT_TYPE_VALUES) là
# ĐẦU VÀO giới hạn Content Factory, ĐỘC LẬP với quyết định router (2 lớp gate
# riêng: router quyết "tuyến này CÓ HỢP tin không" theo nội dung; Output Type
# quyết "người CÓ MUỐN sinh tuyến này không" theo lựa chọn Sheet — CẢ HAI phải
# đồng ý mới sinh, xem run() chỗ áp vào `channels`).
#
# VIỆC 1 (2026-08-03, Lead) — Long-Article NỐI vào đây, dùng CHUNG kênh router
# "article" (Router KHÔNG có khái niệm "long_article" riêng — nó chỉ đánh giá
# 3 hình dạng nội dung article/infographic/video, xem agents/structure_router.
# _CHANNELS; Long-Article là CÙNG hình dạng "article", chỉ khác bộ rules +
# độ dài kỳ vọng, xem agents/writer.build_writer_system). Map này vì vậy là map
# GATE-KÊNH (Output Type -> kênh router nào được phép), KHÔNG PHẢI map nhãn ->
# content_type ghi ra store — content_type THẬT ghi ra ("article" hay
# "long_article") được quyết riêng ở nhánh ghi article trong run(), xem
# `_wants_long_article()`.
_OUTPUT_TYPE_TO_CONTENT_TYPE = {"Article": "article", "Long-Article": "article",
                                "Infographic": "infographic", "Video": "video"}


def _allowed_output_types(output_type: list[str]) -> set[str] | None:
    """None = KHÔNG áp giới hạn thêm (output_type rỗng hoặc chứa "AUTO") --
    giữ NGUYÊN hành vi router-only từ trước Bước 4. Set cụ thể = CHỈ các
    KÊNH ROUTER này được sinh, bất kể router có đồng ý hay không (xem docstring
    _OUTPUT_TYPE_TO_CONTENT_TYPE — trả về TÊN KÊNH "article"/"infographic"/
    "video", KHÔNG phải content_type ghi ra store)."""
    if not output_type or "AUTO" in output_type:
        return None
    return {_OUTPUT_TYPE_TO_CONTENT_TYPE[t] for t in output_type if t in _OUTPUT_TYPE_TO_CONTENT_TYPE}


def _wants_long_article(output_type: list[str]) -> bool:
    """VIỆC 1 — True nếu người chọn "Long-Article" tường minh cho chủ đề này.
    Quyết định content_type ghi ra ("article" vs "long_article") + rules nạp
    (build_writer_system) — KHÔNG ảnh hưởng cổng router (đã gate ở
    _allowed_output_types, cùng kênh "article" cho cả 2 nhãn). Chọn ĐỒNG THỜI
    cả "Article" lẫn "Long-Article" (đa chọn trên Sheet) -> Long-Article THẮNG
    (bài dài đã bao hàm nội dung bài thường; tránh 2 nhánh tranh nhau ghi cùng
    1 kênh router mà sinh 2 bản khác nhau)."""
    return "Long-Article" in (output_type or [])


# BƯỚC 4.3 (Router, quyết định Lead 31/07) — CHUẨN HOÁ mã SKIP ghi vào Notes:
# SOURCE_BROKEN | DUPLICATE | BOILERPLATE | NO_USABLE_CONTENT | FORMAT_MISMATCH.
# 5 mã này mô tả NGUYÊN NHÂN NỘI DUNG (content-driven) — KHÁC "Output Type
# không chọn" (đó là NGƯỜI chủ động loại, không phải nội dung có vấn đề, giữ
# nguyên câu riêng, không gán mã). SOURCE_BROKEN dùng cho nhánh NEEDS_HUMAN
# "Brief hỏng thật" (facts[] rỗng do lỗi hạ tầng — xem nhánh isinstance(agent,
# InfographicSpecAgent) and not brief.content_units bên dưới, KHÔNG phải nhánh
# này). DUPLICATE hiện KHÔNG có Notes riêng (chủ đề đã DONE trước đó -> không
# ghi dòng nào cả, xem write_article/_is_fully_produced_channels — im lặng
# CÓ CHỦ Ý, không phải thiếu sót, không cần gán mã cho thứ không ghi ra).
# BOILERPLATE dùng CHUNG cơ chế phát hiện với NO_USABLE_CONTENT (content_units
# rỗng + no_numeric_content=False sau khi Brief chạy trọn vẹn) — CHƯA có bộ
# phát hiện MẪU boilerplate riêng (vd nhận diện văn bản kiểu menu/điều hướng)
# nên 2 mã này hiện là 1 -- không tách giả tạo khi chưa có tín hiệu phân biệt
# thật, xem _NO_USABLE_CONTENT_REASON.
_NO_USABLE_CONTENT_REASON = (
    "NO_USABLE_CONTENT: Brief đọc được nguồn nhưng KHÔNG tìm thấy nội dung thực "
    "chất nào (không phải lỗi hạ tầng, không phải tin thuần định tính đã xác "
    "nhận) — nghi nguồn boilerplate/trang điều hướng/placeholder (BOILERPLATE "
    "dùng chung mã này — chưa có bộ nhận diện mẫu riêng). SKIP cả 3 tuyến, "
    "KHÔNG cần người can thiệp (xem agents/brief.BriefResult.brief_status)."
)

def _infographic_not_worthy_reason(counts: dict) -> str:
    """BƯỚC A (Router, gỡ nốt cứng nhắc Infographic) — A2: "ghi lý do quyết
    định vào Notes: dùng nhánh nào, đếm được bao nhiêu unit theo type nào,
    để sau này chỉnh ngưỡng bằng số, không bằng cảm nhận". Nêu ĐỦ 4 số đếm
    dùng bởi agents/brief.BriefResult.infographic_worthy, không chỉ nói
    chung chung "không đủ dữ liệu"."""
    return (
        "FORMAT_MISMATCH: content_units KHÔNG đạt ngưỡng dựng Infographic có "
        "ý nghĩa (đánh giá bằng CODE, thay ý kiến Router) — đếm được: "
        f"{counts['numeric']} numeric (ngưỡng ≥2 cho Data Infographic), "
        f"{counts['process_timeline']} process/timeline (ngưỡng ≥3 cho sơ đồ "
        f"bước/dòng thời gian), {counts['relation_state']} relation/state_change "
        f"(ngưỡng ≥3 cho sơ đồ quan hệ/trước-sau), {counts['total']} content_unit "
        "tổng cộng (ngưỡng ≥4 bất kỳ type). KHÔNG PHẢI lỗi nội dung/Brief — "
        "Article/Video vẫn sinh bình thường (xem BriefResult.infographic_worthy)."
    )


def _channel_skip_reason(ch: str, decision, output_type_excluded: set[str], *,
                         no_usable_content: bool = False,
                         infographic_not_worthy_counts: dict | None = None) -> str:
    """Notes giải thích ĐÚNG nguyên nhân SKIPPED — phân biệt router (nội dung
    không hợp tuyến, mã FORMAT_MISMATCH), Output Type (người không chọn tuyến,
    dù router có thể đã đồng ý — KHÔNG gán mã, đây không phải vấn đề nội
    dung), NO_USABLE_CONTENT (Brief xác nhận nguồn KHÔNG có nội dung thực
    chất), và `infographic_not_worthy_counts` (Bước A, đánh giá THUẦN CODE cho
    riêng tuyến infographic — TÁCH RIÊNG khỏi nhánh router/channel_rationale
    dù CÙNG mã FORMAT_MISMATCH, vì đây là cổng CODE-QUYẾT-ĐỊNH, không phải ý
    kiến chủ quan của Router LLM nữa) — ưu tiên kiểm THEO THỨ TỰ no_usable_
    content > infographic_not_worthy_counts (Bước A) > Output Type > router,
    vì mỗi nhánh sau chỉ còn ý nghĩa khi nhánh trước KHÔNG áp dụng — gộp làm 1
    thông điệp sẽ đánh lừa người đọc Notes khi tra vì sao thiếu 1 loại."""
    if no_usable_content:
        return _NO_USABLE_CONTENT_REASON
    if infographic_not_worthy_counts is not None:
        return _infographic_not_worthy_reason(infographic_not_worthy_counts)
    if ch in output_type_excluded:
        return f"Output Type không chọn tuyến {ch} cho chủ đề này (người giới hạn qua cột Output Type)."
    return (f"FORMAT_MISMATCH: Router quyết định tuyến {ch} không hợp tin này: "
           f"{decision.channel_rationale.get(ch) or '(router không cho lý do)'}")


def _is_fully_produced_channels(topic_key: str, seen: set[tuple[str, str]], channels: dict) -> bool:
    """True nếu MỌI tuyến channels[c]=True của chủ đề (tra theo `topic_key` —
    Lớp 5 Phase 2, KHÔNG theo Context) đã có trong CONTENT (`seen`) — tuyến
    channels[c]=False KHÔNG chặn DONE (chủ động không sinh, KHÔNG phải thiếu).
    Dùng cho run() (Phase 4.9+, có RouterDecision thật).

    VIỆC 1 (2026-08-03) — kênh "article" coi là xong nếu `seen` có content_type
    "article" HOẶC "long_article" (Long-Article dùng CHUNG kênh router
    "article", xem _wants_long_article() — channels dict KHÔNG BAO GIỜ có khoá
    "long_article", chỉ 3 kênh router thật)."""
    for c, enabled in channels.items():
        if not enabled:
            continue
        type_key = _CHANNEL_TO_TYPE[c]
        if (topic_key, type_key) in seen:
            continue
        if c == "article" and (topic_key, "long_article") in seen:
            continue
        return False
    return True


def _write_content(topic_key: str, type_: str, *, status: str, output: str, notes: str, content_units_json: str) -> None:
    """P2 store-as-truth: ghi 1 sản phẩm MỚI (chưa từng có trong `seen` — caller
    đảm bảo) vào store -- 2 layer riêng: `content_output` (nội dung sinh ra,
    coi như bất biến) + `content_status` khởi tạo gate2=PENDING/gate3 để trống
    (INVARIANT gate3 không do máy ghi -- xem docstring content_row() cũ,
    write_content_status() merge-on-write nên không truyền gate3 = giữ trống)."""
    ps.write_content_output(topic_key, type_, {
        "status": status, "output": output, "notes": notes, "facts": content_units_json,  # khoá "facts" giữ nguyên cho store/sync_service.py (off-limits, đọc .get("facts"))
        # HAI MỐC THỜI GIAN, lưu TÁCH BẠCH (2026-07-29, quyết định Lead) —
        # DB phải đủ để khôi phục 100% Sheet UI, nên không được để mất mốc nào:
        #   `timestamp`    = NGÀY XỬ LÝ (sản xuất nội dung này). Là thứ hiển
        #                    thị ở cột Timestamp tab CONTENT.
        #   `published_at` = NGÀY ĐĂNG BÀI GỐC, kế thừa từ raw. Trùng
        #                    `timestamp` khi crawl và xử lý cùng ngày; KHÁC khi
        #                    người duyệt sản xuất vào ngày sau.
        # Thiếu `timestamp` thì content_row() lấy now() mỗi lượt render ->
        # Timestamp mọi dòng nhảy sang hôm nay (bug thật 2026-07-29).
        "timestamp": _now_ddmmyyyy(),
        "published_at": (ps.read_raw(topic_key) or {}).get("timestamp", ""),
    })
    ps.write_content_status(topic_key, type_, gate2="PENDING")


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
    """Sản xuất cho các topic Gate1=APPROVE + Execute∈{RUN,FAILED} — P2
    store-as-truth (nhánh feature/store-as-truth): đọc/ghi STORE
    (store/pipeline_store.py), KHÔNG còn đọc/ghi tab CONTEXT/CONTENT trên
    Sheet trực tiếp. `board` ở đây CHỈ còn dùng cho 3 việc Sheet-native theo
    quyết định Bước 1 (log/PROMPTS/SOURCES — do người quản lý trực tiếp trên
    Sheet, không phải trạng thái nội dung cần store làm nguồn sự thật). Sheet
    thấy được kết quả của run() qua store/sync_service.py (Bước 3, chưa xây ở
    phase này) — KHÔNG qua đường này.

    `topic_keys` (VIỆC 5.1 — điểm ráp webhook per-topic):
      - None (mặc định) -> HÀNH VI CŨ: quét TẤT CẢ topic đủ điều kiện, cắt theo
        `limit`. Scheduler 30' (system_power_on) KHÔNG phải sửa — tương thích ngược.
      - list -> CHỈ xử lý các topic có TopicKey nằm trong danh sách (user bấm
        Execute qua webhook). `limit` BỊ BỎ QUA để không âm thầm cắt cụt danh sách.
    Trả dict tổng hợp {approved, produced, skipped}. `run()` là NƠI DUY NHẤT ghi
    cờ Execute (DONE/FAILED/NEEDS_HUMAN) vào STORE — webhook chỉ đọc lại để trả
    trạng thái (xem api/, VIỆC 5.2-5.5), KHÔNG tự ghi Execute (tránh 2 nguồn
    trạng thái, VIỆC 5.2/5.3)."""
    settings = load_settings()
    # LAZY-LOAD (2026-07-24, theo chỉ đạo Lead): board CHỈ còn cần cho
    # read_sources()/read_prompt_versions() (2 việc Sheet-native còn lại) —
    # KHÔNG khởi tạo NGAY ở đây nữa. Trước đây _open_board() gọi sớm hơn
    # NHIỀU so với chỗ nó thật sự dùng -> pipeline đòi Sheet credential cho 1
    # việc mãi về sau mới cần, dù toàn bộ dữ liệu (approved/content/execute)
    # đã đọc/ghi qua store rồi. Lazy-load đưa phụ thuộc về ĐÚNG vị trí nó tồn
    # tại — SAI kiến trúc trước đây, độc lập chuyện có test hay không.
    # get_board() KHÔNG bắt exception của _open_board() (SystemExit khi thiếu
    # sheets.spreadsheet_id/creds_path) — để lỗi NỔ RÕ đúng chỗ, KHÔNG nuốt,
    # KHÔNG fallback rỗng im lặng (nuốt lỗi ở đây sẽ khiến pipeline sinh 0 sản
    # phẩm mà không ai biết vì sao — tệ hơn crash).
    _board_holder: list[SheetsBoard] = []
    def get_board() -> SheetsBoard:
        if not _board_holder:
            _board_holder.append(_open_board(settings, setup=setup))
        return _board_holder[0]

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
    ps.write_log("INFO", banner, engine=engine)

    # --- LLM RIÊNG cho ARTICLE (Phase 4.9: Brief -> route-once -> Writer-with-
    # retry) — adapter make_llm/step_model, SONG SONG với content_llm/LLMRouter
    # ở trên (KHÔNG dùng chung). --offline ép MockLLM ($0) cho đường này luôn,
    # khớp tinh thần "kiểm chứng $0" của cờ.
    route_llm = MockLLM() if offline else factory.make_llm(settings)
    writer_llm = MockLLM() if offline else factory.build_writer_llm(settings)
    router_store = RouterDecisionStore(
        data_path(settings.get("router.decisions_path", "state/router_decisions.json"), settings=settings))

    # P2 store-as-truth: gate1/execute đọc TRỰC TIẾP từ store (gate_status
    # layer) — KHÔNG còn gọi board.sync_approve_execute_flags() (bridge
    # Gate1->Execute="RUN" lần đầu giờ là việc của sync service, chiều
    # Sheet->store, Bước 3 — chưa xây ở phase này). Execute=DONE (xong hẳn) /
    # NEEDS_HUMAN (chờ người) -> ps.list_approved_topics() đã tự lọc bỏ,
    # idempotent — produce chạy lại KHÔNG sinh Content trùng, KHÔNG đụng topic
    # đang chờ người can thiệp.
    approved = ps.list_approved_topics()
    # VIỆC 5.1: webhook per-topic -> lọc ĐÚNG các topic user bấm (khớp TopicKey
    # đã lưu ở store). None = quét cả lô như cũ.
    if topic_keys is not None:
        wanted = set(topic_keys)
        approved = [a for a in approved if a["topic_key"] in wanted]
    if not approved:
        print("Không có topic nào Gate1=APPROVE và Execute=RUN/FAILED (chưa sản xuất "
              "hoặc đang chờ NEEDS_HUMAN). Duyệt Gate1 trước (qua Sheet, sync service nạp vào store).")
        return {"approved": 0, "produced": 0, "skipped": 0}
    # `limit` CHỈ áp đường quét-cả-lô. Khi lọc theo topic_keys, xử ĐỦ danh sách
    # (BỎ QUA limit — không để limit=5 cắt cụt danh sách user bấm, VIỆC 5.1).
    if topic_keys is None:
        approved = approved[:limit]

    # PROMPTS: Sheet-native theo quyết định Bước 1 (người quản lý trực tiếp
    # trên Sheet, không phải trạng thái nội dung) — đọc LIVE tab (Name|
    # Version|Enable) -> resolve prompts/<name>.<v>.md; thiếu tab/dòng/file ->
    # giữ default nội bộ trong code (KHÔNG crash). LƯU Ý (Phase 4.9): override
    # "analysis" (article) KHÔNG còn áp dụng — đường article mới dùng
    # voice-lock động (agents/voice.assemble_voice theo RouterDecision), KHÔNG
    # qua prompt_overrides; override "video"/"infographic" vẫn áp dụng như cũ.
    default_prompts = {a.prompt_name: a.system for a in all_production_agents()}
    prompt_overrides = resolve_prompts(
        get_board().read_prompt_versions(), default_prompts,
        prompts_dir=settings.get("prompts.dir", "prompts"))

    # Full-fetch thân bài thật (tất định, $0) cho từng topic APPROVE -> evidence
    # thật để LLM bám + chống bịa số (khớp nguồn đăng ký theo TÊN MIỀN). SOURCES
    # Sheet-native theo quyết định Bước 1 (danh sách nguồn do người quản lý).
    sources = get_board().read_sources() or factory.build_sources(settings)
    html_collector = factory.build_collector_for_source(Source("_", "_", fetch_type="html"), settings)

    seen = ps.existing_content_keys()   # Lớp 5 Phase 2: (TopicKey, Type) đã sinh -> bỏ qua
    out_dir = data_path(settings.get("storage.output_dir", "output"), _today(), settings=settings)
    out_dir.mkdir(parents=True, exist_ok=True)
    approx_tol = float(settings.get("guardrail.approx_tolerance_pct", 5)) / 100

    done_topics: list[str] = []          # đủ CẢ 3 loại -> Execute=DONE
    failed_topics: list[str] = []        # Phase 4.9: article FAILED (lỗi tạm thời) -> Execute=FAILED
    needs_human_topics: list[str] = []   # Phase 4.9: article NEEDS_HUMAN (guardrail reject) -> chờ người
    written = produced = skipped = flagged = 0
    for item in approved:
        topic_key = item["topic_key"]
        notifier.notify("start", topic=item["context"], topic_key=topic_key, actor=_DEFAULT_ACTOR)

        evidence = fetch_full_evidence(html_collector, sources, item["source"], item["hook"])
        # P2 store-as-truth: topic_key ĐÃ có sẵn (khoá của raw layer, gán 1 lần
        # khi raw được ghi — xem store/pipeline_store.py::write_raw). KHÔNG còn
        # cảnh "topic chưa có khoá" (Sheet-era assign_topic_key()/topic_key_
        # updates cũ) vì store BẮT BUỘC topic_key ở MỌI write — không tồn tại
        # bản ghi nào thiếu khoá để phải match-or-insert theo Context (INVARIANT
        # Lớp 5 Phase 2 cũ, xem existing_content_missing_keys ở sheets_board.py,
        # nay MOOT trong store).

        # --- ARTICLE (Phase 4.9): Brief -> route-once (đóng băng) -> Writer-
        # with-retry. Bỏ qua HOÀN TOÀN nếu đã có trong CONTENT (idempotent,
        # KHÔNG tốn thêm lượt Brief/Router/Writer cho bài đã DONE).
        # VIỆC 1 (2026-08-03) — content_type ghi ra phụ thuộc Output Type
        # ("Long-Article" -> "long_article", còn lại -> "article", xem
        # _wants_long_article()); dedup theo ĐÚNG content_type sẽ dùng, không
        # phải hằng "article" -- nếu không, đổi Output Type Article<->Long-
        # Article sẽ không bao giờ re-trigger (seen chỉ có key cũ) HOẶC ngược
        # lại chạy lại vô ích (seen có "article", request lại "long_article").
        article_content_type = "long_article" if _wants_long_article(item.get("output_type") or []) else "article"
        write_article = (topic_key, article_content_type) not in seen
        # Phase 4.12: run_brief() trả BriefResult (content_units + no_numeric_content)
        # — phân biệt content_units=[] RỖNG-HỢP-LỆ (Brief chạy trọn vẹn, xác nhận tin
        # thuần định tính) vs RỖNG-DO-HỎNG (LLM lỗi/timeout — cờ luôn False).
        # Phase C (2026-07-3x): BriefResult giờ CÒN có `brief_status` (OK|
        # NO_USABLE_CONTENT|FAILED, xem agents/brief.py) — dùng ngay dưới đây
        # để chặn nguồn boilerplate/rỗng tuếch TRƯỚC khi tới Writer/Composer
        # (biến `no_usable_content`, sau khi tính `channels`). `.content_units` vẫn đọc
        # được qua property tương thích ngược (HẠN CỨNG 2026-08-10).
        brief_result = (run_brief(route_llm, evidence, model=factory.step_model(settings, "brief"),
                                  fail_loud=factory.is_fail_loud_step(settings, "brief"),
                                  settings=settings)
                       if write_article else BriefResult())
        brief = ProductionBrief(
            title=item["context"], hook=item["hook"], tickers=item["tickers"],
            group=item["group"], topic=item["topic"], url=item["source"],
            evidence=evidence, content_units=brief_result.content_units,
            no_numeric_content=brief_result.no_numeric_content,
        )
        # Production Factory Phase 1.3 — snapshot content_units[] MÁY-SỞ-HỮU ghi vào MỌI
        # dòng CONTENT của chủ đề này (cột Facts, xem comment CONTENT_HEADER ở
        # sheets_board.py) — nguồn sự thật cho verify_spec() (guardrail lần 2,
        # media_factory/spec.py) chạy TRƯỚC KHI RENDER (Phase 1.3), TÁCH biệt
        # content_units[] còn trong RAM ở tiến trình này (không đồng bộ giữa nhiều máy —
        # đúng bug Fix (a) đã sửa cho CONTEXT, không lặp lại cho Production
        # Factory qua data_root).
        content_units_json = facts_to_json(brief.content_units)

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
        channels = dict(decision.output_channels)
        # Phase C — brief_status=NO_USABLE_CONTENT (Brief chạy TRỌN VẸN, đọc
        # được nguồn nhưng KHÔNG tìm thấy nội dung thực chất nào -- không phải
        # lỗi hạ tầng [FAILED], không phải tin thuần định tính đã XÁC NHẬN
        # [no_numeric_content=True, OK] -- nghi boilerplate/trang điều hướng/
        # placeholder, xem agents/brief.BriefResult docstring) -> ÉP CẢ 3
        # TUYẾN false NGAY Ở ĐÂY, TRƯỚC khi Writer/Composer có cơ hội chạy.
        # TRƯỚC Phase C: content_units=[]+no_numeric_content=False (chữ ký boilerplate)
        # không phân biệt được với "Brief hỏng thật" hay "router/brief bất
        # đồng" -> Article vẫn được Writer viết BỊA từ trang rỗng, Execute=
        # DONE -- xác nhận THẬT qua tests/test_pipeline.py::test_regression_
        # row11_boilerplate_source_currently_produces_fabricated_article_
        # known_gap (Phase B, SẼ chuyển PASS sau thay đổi này).
        # BƯỚC 4.3 (Router, quyết định Lead 31/07, SỬA lại quyết định Phase C
        # ban đầu) — ÉP CẢ 3 TUYẾN vào no_usable_content_channels VÔ ĐIỀU KIỆN
        # khi brief_status=NO_USABLE_CONTENT, KỂ CẢ tuyến Router đã tự tắt kèm
        # rationale riêng (khác Phase C bản đầu: từng CHỈ đè tuyến Router để
        # mặc định true, giữ nguyên rationale Router cho tuyến router đã tắt
        # sẵn). LÝ DO ĐỔI: Bước 4.3 chuẩn hoá 5 mã SKIP — NO_USABLE_CONTENT là
        # sự thật NỀN TẢNG (không có gì để làm việc), PHẢI thắng mọi ý kiến chủ
        # quan của Router về TỪNG tuyến riêng lẻ, để Notes nhất quán thay vì
        # tuỳ tiện theo tuyến nào Router tình cờ tự tắt trước. Xem test_run_
        # article_skipped_when_router_decides_channel_false_upfront (đã cập
        # nhật kỳ vọng theo thay đổi này).
        no_usable_content_channels: set[str] = set()
        if write_article and brief_result.brief_status == "NO_USABLE_CONTENT":
            no_usable_content_channels = {"article", "video", "infographic"}
            for ch in no_usable_content_channels:
                channels[ch] = False

        # BƯỚC A (Router, quyết định Lead 31/07 — GỠ NỐT CỨNG NHẮC INFOGRAPHIC,
        # THAY HẲN Bước 4.4 bản đầu "has_numeric_units=False -> luôn tắt"):
        # quy tắc CŨ tự nó vẫn cứng nhắc — giả định Infographic CHỈ vẽ được
        # bảng số liệu, trong khi gpt-image-2 (render/ai_full.py, KHÔNG đụng ở
        # đây) vẽ được sơ đồ quy trình/dòng thời gian/quan hệ từ content_unit
        # ĐỊNH TÍNH, không cần khuôn dữ liệu riêng (xem agents/brief.BriefResult.
        # infographic_worthy). channels["infographic"] GIỜ do CODE quyết định
        # HOÀN TOÀN ở chế độ AUTO (cả 2 chiều True/False) — THAY THẾ ý kiến
        # riêng của Router (LLM) cho tuyến này, KHÔNG chỉ ghi đè 1 chiều như
        # article (has_anchored_units). Output Type chọn TƯỜNG MINH Infographic
        # vẫn BỎ QUA property này hoàn toàn (xem deterministic_off_channels +
        # BƯỚC 4.5 bên dưới — infographic_worthiness_channels KHÔNG nằm trong
        # đó, khác no_usable_content_channels là sự thật tuyệt đối không viết
        # được gì).
        infographic_worthiness_channels: set[str] = set()
        if (write_article and brief_result.brief_status == "OK"
                and "infographic" not in no_usable_content_channels):
            channels["infographic"] = brief_result.infographic_worthy
            infographic_worthiness_channels.add("infographic")

        # BƯỚC 4.1/4.2 (Router) — "article=true khi brief_status=OK VÀ có ≥1
        # content_unit NEO ĐƯỢC vào nguồn (has_anchored_units — xem agents/
        # brief.BriefResult), BẤT KỂ type; KHÔNG BAO GIỜ đặt article=false vì
        # thiếu số/nguồn ngắn": Router (LLM) VẪN được quyền tự phán qua prompt
        # (_SYSTEM structure_router.py), NHƯNG khi Brief đã xác nhận có chất
        # liệu neo nguồn thật, CODE ÉP article=True — Router MẤT quyền phủ
        # quyết article trong trường hợp này (khác hẳn trước đây, Router có
        # thể tắt article vì "tin quá vụn" dù Brief đã trích được content_unit
        # thật, xem test_run_article_skipped_when_router_decides_channel_
        # false_upfront -- ca đó brief_status=NO_USABLE_CONTENT nên KHÔNG bị
        # ép ở đây, giữ nguyên hành vi cũ, không phá test).
        if (write_article and brief_result.brief_status == "OK"
                and brief_result.has_anchored_units
                and not channels.get("article", True)):
            channels["article"] = True

        # Bước 4 (2026-07-28, Output Type AND với quyết định router) — xem
        # docstring _allowed_output_types/_channel_skip_reason: output_type
        # rỗng/AUTO -> KHÔNG đổi channels (hành vi router-only như trước).
        allowed_types = _allowed_output_types(item.get("output_type") or [])
        output_type_excluded: set[str] = set()
        if allowed_types is not None:
            # KHÔNG lọc theo `enabled` (bug bắt được ở e2e 2026-07-28): bản cũ
            # chỉ đánh dấu tuyến mà ROUTER đã bật. Tuyến router TỰ TẮT rơi ra
            # ngoài -> đi tiếp vào nhánh "router skip" và VẪN ghi 1 dòng
            # SKIPPED. Kết quả: cùng Output Type="Article", infographic không
            # có dòng còn video lại có — cùng ý định của người, 2 kết cục khác
            # nhau chỉ vì tầng nào loại trước. Người đã nói KHÔNG cần tuyến đó
            # thì KHÔNG dòng nào cả, bất kể ai loại.
            for ch in list(channels):
                if ch not in allowed_types:
                    output_type_excluded.add(ch)
                    channels[ch] = False
            # BƯỚC 4.5 (Router, quyết định Lead 31/07) — "người chọn TƯỜNG
            # MINH một loại -> Router MẤT quyền phủ quyết": tuyến người CHỌN
            # (trong allowed_types) mà Router TỰ Ý tắt (channel_rationale
            # riêng, vd "tin quá vụn"/"không đủ dữ liệu trình bày hình") ->
            # BỎ QUA ý kiến Router, ép bật lại. CHỈ áp cho quyết định RIÊNG
            # CỦA ROUTER — KHÔNG ghi đè 2 cổng TẤT ĐỊNH ở trên (no_usable_
            # content/format_mismatch): đó là SỰ THẬT về hình dạng nội dung
            # (không có gì để viết/không có số để trình bày), ép bật sẽ ép
            # Composer BỊA hoặc sinh spec rỗng — khác hẳn Router chỉ đang nêu
            # Ý KIẾN chủ quan có thể sai. `infographic_worthiness_channels`
            # (Bước A) KHÔNG nằm trong deterministic_off_channels — đây CŨNG
            # là 1 dạng "ý kiến đánh giá" (chỉ khác là CODE đánh giá thay vì
            # LLM), Output Type chọn tường minh PHẢI ghi đè được, đúng yêu
            # cầu "Router mất quyền phủ quyết" áp cho MỌI định dạng, không
            # riêng Article.
            deterministic_off_channels = no_usable_content_channels
            for ch in allowed_types:
                if ch not in deterministic_off_channels and not channels.get(ch, True):
                    channels[ch] = True

        article_outcome = None
        if not write_article:
            skipped += 1
        elif "article" in output_type_excluded:
            # 2026-07-28 (quyết định Lead): tuyến người KHÔNG CHỌN ở Output Type
            # -> KHÔNG ghi dòng nào cả. Trước đây ghi 1 dòng SKIPPED, khiến tab
            # CONTENT lúc nào cũng 3 dòng cho mỗi chủ đề dù người chỉ muốn 1 —
            # 2 dòng kia là nhiễu thuần tuý, người đã tự nói là không cần.
            # KHÁC HẲN skip do ROUTER (nhánh dưới): ở đó người CÓ yêu cầu tuyến
            # này, nên vẫn cần 1 dòng giải thích vì sao hệ thống từ chối.
            skipped += 1
        elif not channels.get("article", True):
            reason = _channel_skip_reason("article", decision, output_type_excluded,
                                          no_usable_content="article" in no_usable_content_channels)
            _write_content(topic_key, article_content_type, status="SKIPPED", output="", notes=reason, content_units_json=content_units_json)
            written += 1
            seen.add((topic_key, article_content_type))
            skipped += 1
            notifier.notify("skipped", topic=item["context"], type=article_content_type, reason=reason)
        else:
            r = run_writer_with_retry(
                writer_llm, brief, decision, settings=settings,
                model=factory.step_model(settings, "writer"),
                notify=_writer_notify_adapter(notifier),
                content_type=article_content_type)
            article_outcome = r.outcome
            if r.outcome == WriterOutcome.DONE:
                fn = out_dir / f"{_slug(item['context'])}-{article_content_type}.md"
                fn.write_text(r.draft.body, encoding="utf-8")
                _write_content(topic_key, article_content_type, status="DONE", output=r.draft.body, notes="", content_units_json=content_units_json)
                written += 1
                seen.add((topic_key, article_content_type))
                produced += 1
                notifier.notify("draft_changed", topic=item["context"], type=article_content_type, status="DONE")
            elif r.outcome == WriterOutcome.NEEDS_HUMAN:
                # LLM ĐÃ trả lời nhưng guardrail reject -> VẪN ghi CONTENT (Status=
                # ERROR) để người xem lý do, nhưng KHÔNG seen.add (chưa coi là xong).
                note = "; ".join(r.draft.compliance_issues)
                fn = out_dir / f"{_slug(item['context'])}-{article_content_type}.md"
                fn.write_text(r.draft.body, encoding="utf-8")
                _write_content(topic_key, article_content_type, status="ERROR", output=r.draft.body, notes=note, content_units_json=content_units_json)
                written += 1
                flagged += 1
                notifier.notify("error", topic=item["context"], type=article_content_type, issues=note)
            else:   # FAILED — hết retry (lỗi hạ tầng gọi LLM), KHÔNG có draft -> KHÔNG ghi CONTENT rác
                flagged += 1
                notifier.notify("error", topic=item["context"], type=article_content_type, issues=r.reason)

        # --- VIDEO/INFOGRAPHIC: VIDEO tiêu thụ CÙNG RouterDecision đã đóng
        # băng (voice-lock động + §4 chuyển-thể, Phase 4.10, xem VideoScriptAgent
        # .run) — nhất quán khung với article của CÙNG chủ đề. INFOGRAPHIC
        # (Phase 4.11 — Composer) CŨNG tiêu thụ decision + content_units[], nhưng dùng
        # LLM RIÊNG (route_llm, alias 'composer'/haiku — Loại B rẻ, KHÔNG dùng
        # content_llm/Sonnet như video/article) — swap .llm/.model NGAY TRƯỚC
        # khi gọi run(), giữ nguyên instance đã áp prompt_overrides ở trên.
        # content_units[] rỗng -> spec KHÔNG bịa nhãn, đánh dấu NEEDS_HUMAN (Status=
        # ERROR ở CONTENT, xem đoạn append issue bên dưới) — KHÔNG đụng Execute
        # cấp DÒNG (đó vẫn do riêng article_outcome quyết định, phạm vi 4.9).
        for agent in all_production_agents(content_llm, prompt_overrides=prompt_overrides):
            if isinstance(agent, AnalysisWriterAgent):
                continue   # article đã xử lý ở nhánh route-once+retry trên

            # Phase 4.13 Mục A: router QUYẾT NGAY TỪ ĐẦU tuyến này không hợp
            # (channels[ch]=False, đóng băng cùng RouterDecision) -> SKIPPED
            # HỢP LỆ, KHÔNG gọi agent (khỏi tốn lượt LLM) — THAY nhánh phản
            # ứng-sau "content_units rỗng -> skip" của Phase 4.12 làm cơ chế CHÍNH.
            ch = ("infographic" if isinstance(agent, InfographicSpecAgent)
                 else "video" if isinstance(agent, VideoScriptAgent) else None)
            if ch is not None and ch in output_type_excluded:
                # Người không chọn tuyến này ở Output Type -> KHÔNG ghi dòng
                # nào (xem nhánh article ở trên cho lý do đầy đủ).
                skipped += 1
                continue
            if ch is not None and not channels.get(ch, True):
                type_key = _CHANNEL_TO_TYPE[ch]
                if (topic_key, type_key) in seen:
                    skipped += 1
                    continue
                reason = _channel_skip_reason(
                    ch, decision, output_type_excluded,
                    no_usable_content=ch in no_usable_content_channels,
                    infographic_not_worthy_counts=(
                        brief_result.infographic_type_counts()
                        if ch in infographic_worthiness_channels else None),
                )
                _write_content(topic_key, type_key, status="SKIPPED", output="", notes=reason, content_units_json=content_units_json)
                written += 1
                seen.add((topic_key, type_key))
                skipped += 1
                notifier.notify("skipped", topic=item["context"], type=ch, reason=reason)
                continue

            # Phase 4.12 (thu hẹp phạm vi ở 4.13 — chỉ còn xử lý CA BẤT ĐỒNG)
            # từng có 1 nhánh riêng ở đây bắt "router chọn infographic:true
            # nhưng Brief xác nhận no_numeric_content=true". Bước 4.4 (bản đầu,
            # rồi Bước A thay tiếp) ĐÃ THAY THẾ HOÀN TOÀN: cổng infographic_
            # worthiness_channels ở trên (tính TRƯỚC vòng lặp này, từ brief_
            # result.infographic_worthy) bắt ĐÚNG case này SỚM HƠN (channels
            # ["infographic"] đã được CODE quyết định dứt điểm ngay từ đầu,
            # cả 2 chiều) -- nhánh cũ do đó KHÔNG BAO GIỜ còn chạy tới được,
            # đã XOÁ để không giữ code chết dùng chung 1 ý nghĩa nhưng 2 cơ
            # chế/2 mã lý do khác nhau.

            if isinstance(agent, VideoScriptAgent):
                # BƯỚC 3 (rules v2.1) — nguồn không đủ SCENE cho video (sàn
                # renderer, xem InsufficientScenesError) là tình huống RIÊNG với
                # lỗi hạ tầng: bắt ĐÚNG loại này, ghi NEEDS_HUMAN kèm đề xuất
                # chuyển loại, KHÔNG để crash cả lượt run() (các dòng khác vẫn
                # phải xử tiếp). Không bắt Exception chung — lỗi khác (hỏng
                # thật) vẫn phải nổ để không âm thầm nuốt lỗi lạ.
                try:
                    raw_draft = agent.run(brief, decision)
                except InsufficientScenesError as e:
                    if (topic_key, "video") in seen:
                        skipped += 1
                        continue
                    _write_content(topic_key, "video", status="NEEDS_HUMAN", output="", notes=str(e), content_units_json=content_units_json)
                    written += 1
                    seen.add((topic_key, "video"))
                    flagged += 1
                    notifier.notify("needs_human", topic=item["context"], type="video", reason=str(e))
                    continue
            elif isinstance(agent, InfographicSpecAgent):
                agent.llm = route_llm
                agent.model = factory.step_model(settings, "composer")
                raw_draft = agent.run(brief, decision)
            else:
                raw_draft = agent.run(brief)
            draft = apply_guardrails(raw_draft, brief.evidence, brief.background,
                                     brief.content_units, approx_tolerance=approx_tol)
            if isinstance(agent, InfographicSpecAgent) and not brief.content_units:
                # Tới được đây nghĩa là no_numeric_content=False -> content_units rỗng
                # DO Brief HỎNG THẬT (timeout/lỗi/parse hỏng), KHÔNG phải tin
                # định tính (nhánh đó đã "continue" ở trên) -> vẫn NEEDS_HUMAN.
                draft.compliance_issues.append(
                    "SOURCE_BROKEN: content_units[] rỗng (Brief chưa trích được số liệu, "
                    "brief_status=FAILED — lỗi hạ tầng thật) -> NEEDS_HUMAN, "
                    "không bịa nhãn 'Số liệu N'")
            type_ = draft.fmt.value
            if (topic_key, type_) in seen:
                skipped += 1
                continue
            status = "DONE" if draft.is_clean else "ERROR"
            note = "; ".join(draft.compliance_issues)
            if not use_llm and type_ != "infographic":
                note = (note + " | " if note else "") + "MOCK (chưa bật Sonnet)"
            # Lưu full ra file (tham chiếu cục bộ, tiện đọc tay); store CŨNG giữ
            # NGUYÊN VĂN draft.body (Lead xác nhận 2026-07-27 -- store là nguồn
            # sự thật, KHÔNG được chỉ có bản cắt như Sheet preview).
            fn = out_dir / f"{_slug(item['context'])}-{type_}.{_ext(type_)}"
            fn.write_text(draft.body, encoding="utf-8")
            _write_content(topic_key, type_, status=status, output=draft.body, notes=note, content_units_json=content_units_json)
            written += 1
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
            failed_topics.append(topic_key)
        elif article_outcome == WriterOutcome.NEEDS_HUMAN:
            needs_human_topics.append(topic_key)
        elif _is_fully_produced_channels(topic_key, seen, channels):
            done_topics.append(topic_key)

    # P2 store-as-truth: mỗi thay đổi Execute ghi 1 version mới vào gate_status
    # (merge-on-write — không đụng gate1/output_type đã có, xem
    # store/pipeline_store.py::write_gate_status). KHÔNG còn board.append_
    # content_rows()/set_execute_values()/set_topic_key_values() (đã ghi trực
    # tiếp per-item ở trên qua _write_content(); topic_key write-once MOOT
    # trong store — xem comment đầu vòng lặp). regroup_and_band_content()
    # (băng màu/viền Sheet UI) chuyển thành việc của sync service khi render
    # store->Sheet (Bước 3) — KHÔNG còn ở đây (thuần render, không phải ghi dữ
    # liệu).
    for tk in done_topics:
        ps.mark_execute(tk, "DONE")
    for tk in failed_topics:
        ps.mark_execute(tk, "FAILED")
    for tk in needs_human_topics:
        ps.mark_execute(tk, "NEEDS_HUMAN")
    if written:
        notifier.notify("gate2_done", written=written, approved=len(approved))
    u = content_llm.usage.as_dict()
    ps.write_log("INFO", f"TỔNG Production: approved {len(approved)} / sinh mới {produced} / "
                        f"bỏ qua {skipped} / dính compliance {flagged} / ghi CONTENT {written} / "
                        f"Execute=DONE {len(done_topics)} / FAILED {len(failed_topics)} / "
                        f"NEEDS_HUMAN {len(needs_human_topics)} topic",
                engine=engine)
    _summary(len(approved), produced, skipped, flagged, use_llm, u, out_dir)
    return {"approved": len(approved), "produced": produced, "skipped": skipped,
            "flagged": flagged, "llm": u, "use_llm": use_llm, "written": written,
            "failed": len(failed_topics), "needs_human": len(needs_human_topics)}


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
    qua guardrail (evidence + brief.background gộp lại; brief.content_units (Mục C) cho
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
    return apply_guardrails(draft, brief.evidence, brief.background, brief.content_units,
                            approx_tolerance=approx_tolerance)


def run_draft(*, limit: int = 5, setup: bool = False) -> dict:
    """Full-fetch evidence + sinh infographic NGAY (tất định, $0); với article/
    video -> ghi *.brief.json + *.<type>.prompt.md vào storage.drafts_dir để
    Claude Code đọc và viết *.<type>.json cạnh đó (không gọi API riêng). P2
    store-as-truth: đọc/ghi STORE cho dữ liệu nội dung, `board` CHỈ còn dùng
    cho SOURCES (Sheet-native, xem docstring run()). LAZY-LOAD (xem docstring
    run()): board KHÔNG khởi tạo ở đây, chỉ lúc get_board().read_sources()
    thật sự gọi."""
    settings = load_settings()
    _board_holder: list[SheetsBoard] = []
    def get_board() -> SheetsBoard:
        if not _board_holder:
            _board_holder.append(_open_board(settings, setup=setup))
        return _board_holder[0]

    # P2 store-as-truth: gate1/execute đọc TRỰC TIẾP từ store -- KHÔNG còn
    # board.sync_approve_execute_flags() (bridge Gate1->Execute="RUN" lần đầu
    # là việc sync service, Bước 3, xem docstring run()). --draft KHÔNG có
    # vocab Execute=NEEDS_HUMAN/FAILED (chỉ mark_execute_done/DONE) nên lọc
    # riêng "RUN" (không gộp "FAILED" như run()).
    approved = [a for a in ps.list_approved_topics() if a["execute"] == "RUN"]
    if not approved:
        print("Không có topic nào Gate1=APPROVE và Execute=RUN (chưa sản xuất). "
              "Duyệt Gate1 trước (qua Sheet, sync service nạp vào store).")
        return {"approved": 0, "prepared": 0, "infographic_done": 0}
    approved = approved[:limit]

    sources = get_board().read_sources() or factory.build_sources(settings)
    html_collector = factory.build_collector_for_source(Source("_", "_", fetch_type="html"), settings)
    seen = ps.existing_content_keys()   # Lớp 5 Phase 2: (TopicKey, Type)
    out_dir = data_path(settings.get("storage.output_dir", "output"), _today(), settings=settings)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Theo NGÀY (như storage/output/<ngày>) — trước đây ghi phẳng vào drafts_dir,
    # không phân biệt được bản nháp mới/cũ khi tồn đọng (vd chưa --ingest kịp).
    # drafts_base = gốc KHÔNG có ngày (dò bản nháp CŨ còn tồn đọng ở NGÀY TRƯỚC,
    # tránh chuẩn bị trùng); drafts_dir = nơi GHI file MỚI hôm nay.
    drafts_base = data_path(settings.get("storage.drafts_dir", "state/production_drafts"), settings=settings)
    drafts_dir = data_path(settings.get("storage.drafts_dir", "state/production_drafts"), _today(), settings=settings)

    done_topics: list[str] = []   # topic đã đủ CẢ 3 loại -> Execute=DONE
    written = prepared = infographic_done = 0
    for item in approved:
        context = item["context"]
        topic_key = item["topic_key"]   # store BẮT BUỘC topic_key ở mọi write -> luôn có sẵn (xem run())

        evidence = fetch_full_evidence(html_collector, sources, item["source"], item["hook"])
        brief = ProductionBrief(
            title=context, hook=item["hook"], tickers=item["tickers"],
            group=item["group"], topic=item["topic"], url=item["source"], evidence=evidence,
        )
        slug = _slug(context)

        # Infographic: sinh NGAY (không cần Claude Code) — NGOÀI PHẠM VI Phase
        # 4.9/4.10/4.11: đường --draft KHÔNG chạy run_brief() nên brief.content_units
        # luôn rỗng ở đây -> InfographicSpecAgent (Phase 4.11 Composer) trả
        # spec RỖNG có chủ ý (_empty_infographic_spec, KHÔNG bịa), không phải
        # bug — biết trước, chưa wire content_units[]/route-once cho đường thủ công này.
        if (topic_key, "infographic") not in seen:
            approx_tol = float(settings.get("guardrail.approx_tolerance_pct", 5)) / 100
            draft = apply_guardrails(InfographicSpecAgent(None).run(brief), brief.evidence,
                                     brief.background, brief.content_units, approx_tolerance=approx_tol)
            fn = out_dir / f"{slug}-infographic.json"
            fn.write_text(draft.body, encoding="utf-8")
            _write_content(topic_key, "infographic",
                          status="DONE" if draft.is_clean else "ERROR",
                          output=draft.body,
                          notes="; ".join(draft.compliance_issues),
                          content_units_json=facts_to_json(brief.content_units))   # rỗng ở đường --draft (chưa wire run_brief())
            written += 1
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
            # P2 store-as-truth: topic_key (KHÔNG còn "execute_row" -- khái
            # niệm Sheet row-index -- run_ingest() giờ đọc lại + ghi Execute
            # THẲNG theo topic_key này qua ps.mark_execute_done()).
            brief_path.write_text(
                json.dumps({"context": context, "topic_key": topic_key, **asdict(brief)},
                          ensure_ascii=False, indent=2),
                encoding="utf-8")

        # Article/video có thể ĐÃ xong từ trước (seen) -> cùng infographic vừa
        # sinh, có thể đủ CẢ 3 loại ngay trong lượt --draft này -> đánh dấu DONE
        # luôn (không cần đợi --ingest).
        if _is_fully_produced(topic_key, seen):
            done_topics.append(topic_key)

    for tk in done_topics:
        ps.mark_execute_done(tk)
    print(f"[draft] infographic sinh ngay: {infographic_done} | "
          f"yêu cầu article/video chuẩn bị: {prepared} (xem {drafts_dir}) | "
          f"Execute=DONE {len(done_topics)} topic")
    if prepared:
        print("Nhờ Claude Code đọc các file *.prompt.md ở trên, viết JSON đúng schema "
              "vào *.article.json/*.video.json cạnh đó, rồi chạy:\n"
              "    python scripts/produce_from_sheet.py --ingest")
    return {"approved": len(approved), "prepared": prepared,
            "infographic_done": infographic_done, "written": written}


def run_ingest() -> dict:
    """Nạp *.article.json/*.video.json (Claude Code đã viết) qua ĐÚNG schema
    fields/render/guardrail như chế độ gọi API -> ghi CONTENT + storage/output.
    Dọn file đã tiêu thụ; giữ lại *.prompt.md nào còn thiếu câu trả lời. P2
    store-as-truth: đọc/ghi STORE, KHÔNG đụng Sheet (KHÔNG còn `board`/
    `_open_board()` -- hàm này không còn thao tác Sheet nào, xem docstring
    run(). `setup` (cờ --setup) bỏ mất Ý NGHĨA ở đây vì không còn ensure_tabs()
    nào để chạy -- xem __main__ bên dưới)."""
    settings = load_settings()
    # Quét TẤT CẢ thư mục ngày (storage.drafts_dir/<ngày>/) — bản nháp có thể
    # tồn đọng từ ngày TRƯỚC nếu --ingest chưa chạy kịp, KHÔNG chỉ hôm nay.
    drafts_dir = data_path(settings.get("storage.drafts_dir", "state/production_drafts"), settings=settings)
    brief_paths = sorted(drafts_dir.glob("*/*.brief.json"))
    if not drafts_dir.exists() or not brief_paths:
        print(f"Không có bản nháp nào chờ ({drafts_dir}/<ngày>/). Chạy --draft trước.")
        return {"ingested": 0, "skipped": 0, "pending": 0}

    seen = ps.existing_content_keys()   # Lớp 5 Phase 2: (TopicKey, Type)
    out_dir = data_path(settings.get("storage.output_dir", "output"), _today(), settings=settings)
    out_dir.mkdir(parents=True, exist_ok=True)

    approx_tol = float(settings.get("guardrail.approx_tolerance_pct", 5)) / 100
    done_topics: list[str] = []   # topic đã đủ CẢ 3 loại -> Execute=DONE
    written = ingested = skipped = flagged = pending = 0
    for brief_path in brief_paths:
        day_dir = brief_path.parent   # NGÀY bản nháp được tạo (có thể khác hôm nay)
        slug = brief_path.name[: -len(".brief.json")]
        raw = json.loads(brief_path.read_text(encoding="utf-8"))
        context = raw.pop("context")
        # P2 store-as-truth: topic_key ghi SẴN trong *.brief.json bởi
        # run_draft() (đọc thẳng từ store, xem run_draft()) -- KHÔNG còn
        # "execute_row" (Sheet row-index) hay assign_topic_key("", url=...)
        # đoán lại (không tin cậy bằng đọc thẳng khoá đã có). Bản nháp CŨ
        # (trước P2, không có field này) -> KeyError sớm, RÕ RÀNG hơn âm thầm
        # đoán sai khoá -- dữ liệu cũ không còn ý nghĩa (BỐI CẢNH task).
        topic_key = raw.pop("topic_key")
        brief = ProductionBrief(**raw)

        # Bối cảnh mở rộng (research) Claude Code viết ở BƯỚC 1 của _prompt_md —
        # KHÔNG bắt buộc; thiếu file -> brief.background giữ rỗng, guardrail vẫn
        # chạy bình thường (chỉ xét evidence).
        background_path = day_dir / f"{slug}.background.txt"
        if background_path.exists():
            brief.background = background_path.read_text(encoding="utf-8").strip()

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
            _write_content(topic_key, ctype, status="DONE" if draft.is_clean else "ERROR",
                          output=draft.body, notes="; ".join(draft.compliance_issues),
                          content_units_json=facts_to_json(brief.content_units))   # rỗng ở đường --ingest (chưa wire run_brief())
            written += 1
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
            if _is_fully_produced(topic_key, seen):
                done_topics.append(topic_key)

    for tk in done_topics:
        ps.mark_execute_done(tk)
    print(f"[ingest] sản phẩm mới: {ingested} | bỏ qua (đã có): {skipped} | "
          f"dính compliance: {flagged} | còn chờ Claude viết: {pending} | ghi CONTENT {written} | "
          f"Execute=DONE {len(done_topics)} topic")
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
        run_ingest()
    else:
        run(limit=args.limit, offline=args.offline, model=args.model, setup=args.setup)
