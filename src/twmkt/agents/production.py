"""Giai đoạn SẢN XUẤT (cổng 2) — chạy SAU khi người duyệt đặt CONTEXT.Status=APPROVE.

Đây là nơi DUY NHẤT bật LLM ĐẮT (Sonnet, content_model): vì đã qua cổng duyệt 1
nên không đốt token cho chủ đề bị loại. Mỗi định dạng = 1 agent chuyên biệt, output
JSON theo SCHEMA cố định (xem docs/production_agents_design.md):
  • AnalysisWriterAgent  — bài phân tích (LLM). Schema: title/sapo/sections/disclaimer/sources.
  • VideoScriptAgent     — kịch bản video ~60s (LLM). Schema: CONTENT.Output video
    (schema_version/title/scenes[{role,visual_kind,payload,narration}]/source/
    disclaimer/content_units — xem docs/CONTENT_OUTPUT_SCHEMA.md, hợp đồng CHÉO REPO).
  • InfographicSpecAgent — spec JSON (TẤT ĐỊNH, $0 — theo CLAUDE.md: infographic ở
    Tầng 0/free). Số liệu đọc THẲNG từ ProductionBrief.content_units[] (Phase 4.10 — trước
    đó trích thô bằng regex trên evidence, không qua LLM nên không thể bịa).

HAI CÁCH điền JSON cho Analysis/Video (cùng schema, cùng guardrail, khác "ai viết"):
  1. AnthropicLLM API (llm.provider=anthropic, cần ANTHROPIC_API_KEY riêng) — để
     dành cho khi cần automation 100% không người trông (xem factory.build_content_llm).
  2. Claude Code (phiên chat đang chạy, dùng gói Pro/Max/Team sẵn có, KHÔNG cần
     API key riêng) — build_analysis_prompt/build_video_prompt tách sẵn để Claude
     Code đọc rồi tự viết JSON, qua scripts/produce_from_sheet.py --draft/--ingest.
     Vì hệ thống đã có 2 cổng duyệt người-trong-vòng-lặp, bước sinh nội dung KHÔNG
     cần chạy tự động hoàn toàn ở giai đoạn hiện tại — dùng cách 2 là mặc định.

LÙI MƯỢT: LLM trả rỗng/không parse được JSON -> dựng schema TẤT ĐỊNH từ dữ kiện
đã duyệt (KHÔNG crash, vẫn ra sản phẩm nháp đúng cấu trúc).

SIGNATURE + BỐI CẢNH MỞ RỘNG: bài viết PHẢI có góc nhìn/nhận định riêng của
thương hiệu (tên đọc từ config/brand.yaml, KHÔNG hard-code — xem _BRAND_NAME),
không tường thuật lại 1 bài báo, và xâu chuỗi thêm bối cảnh/tiền
lệ liên quan đã research (brief.background) để người CHƯA đọc tin trước đó vẫn
hiểu toàn cảnh. `evidence` = thân bài gốc (full-fetch, $0, tất định); `background`
= tóm tắt nghiên cứu bổ sung — do Claude Code tự tìm (WebSearch) khi viết qua
--draft/--ingest, hoặc để trống nếu gọi thẳng AnthropicLLM (chưa có web search).

GUARDRAIL (chạy SAU khi sinh, TRƯỚC khi ghi CONTENT, xem apply_guardrails()):
  - compliance.check (đã có): disclaimer bắt buộc + chặn claim cấm.
  - MỚI: mọi con số tài chính (%, tỷ, triệu, usd, đồng...) xuất hiện trong body
    PHẢI có trong `evidence` HOẶC `background` — chống bịa số. Vi phạm -> ERROR.
  - Trích nguồn báo: gắn "Nguồn: <domain>" TẤT ĐỊNH khi render (không phụ thuộc
    LLM có nhớ ghi hay không).

PHASE 4.8 MỤC C — SỐ CANONICAL: số trong body KHÔNG khớp NGUYÊN VĂN evidence
(vd Writer viết "gần 600 tỷ" trong khi evidence chỉ có "585 tỷ đồng") KHÔNG còn
tự động bị flag — nếu `content_units` (agents/brief.py) có 1 fact.canonical_value lệch
≤ dung sai (0% mặc định, nới ≤ guardrail.approx_tolerance_pct% CHỈ KHI số
trong body đi kèm từ xấp xỉ ngay trước nó) thì coi là HỢP LỆ. Đây vẫn là PHÉP
TÍNH SỐ HỌC TẤT ĐỊNH (agents/_numeric.py) — KHÔNG gọi LLM để phán. `content_units`
rỗng/không truyền (đa số call site hiện tại CHƯA wire agents/brief.run_brief())
-> cơ chế này no-op hoàn toàn, lùi về hành vi CŨ (chỉ so khớp evidence trực
tiếp) — KHÔNG đổi hành vi các đường sản xuất hiện có.

Cơ chế PROMPTS (đổi văn phong không cần sửa code): xem agents/prompts.py +
sheets_board.SheetsBoard.read_prompt_versions. Gọi all_production_agents(llm,
prompt_overrides=...) để áp bản prompt đã kích hoạt trên tab PROMPTS.

PHASE 4.13 MỤC B — KỶ LUẬT SỐ Ở NGUỒN SINH (sửa CHẤT LƯỢNG, KHÔNG nới guardrail):
backtest Phase 4.12-B phát hiện writer/composer tự CHẾ số sai (vd cộng "89.000
tỷ" + "125.000 tỷ" thành "200.000 tỷ" không có thật trong evidence; rớt "000"
biến "357.000 tỷ đồng" thành "357 tỷ" — sai 1.000 lần) — cả 2 case đều bị
guardrail-canonical (Mục C, apply_guardrails/unsupported_numbers) CHẶN ĐÚNG,
nhưng gây NEEDS_HUMAN OAN (writer/composer THỪA SỨC viết đúng ngay từ đầu nếu
được nhắc kỷ luật). `_NUMBER_DISCIPLINE` (hằng số dùng CHUNG, tránh trôi giữa 2
agent) nối vào CUỐI `AnalysisWriterAgent.system` và `_INFOGRAPHIC_COMPOSER_SYSTEM`
— guardrail-canonical GIỮ NGUYÊN làm lưới chặn CUỐI (không nới lỏng), đây chỉ
là sửa NGUỒN để giảm tỷ lệ bị lưới chặn oan.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from ._jsonparse import try_json_object
from ._numeric import has_approx_word, parse_magnitude_token
from ..config import data_path, load_brand, load_settings
from ..guardrails import compliance
from ..media_factory.numbers import find_spelled_number_phrases
from ..media_factory.spec import DEFERRED_VISUAL_KINDS, VISUAL_KINDS
from ..models import ContentDraft, ContentFormat, ContentUnit
from .base import Agent, LLMClient
from .voice import assemble_voice

_FALLBACK_DISCLAIMER = "Nội dung mang tính thông tin, không phải khuyến nghị đầu tư."

# CONTENT.Output (video) — hợp đồng CHÉO REPO có version, xem
# docs/CONTENT_OUTPUT_SCHEMA.md (NGUỒN SỰ THẬT DUY NHẤT cho shape JSON dưới
# đây). Đổi shape PHẢI bump version này + đồng bộ tài liệu ở CẢ HAI repo.
_CONTENT_OUTPUT_SCHEMA_VERSION = 1

# 9 visual_kind IN-SCOPE (10 canonical trừ "avatar" DEFERRED — chờ HeyGen, xem
# media_factory/spec.py) — MỘT NGUỒN cho cả prompt LLM lẫn validate parse ở
# đây, KHÔNG tự chép lại danh sách rời rạc (tránh trôi giữa 2 nơi).
_IN_SCOPE_VISUAL_KINDS = VISUAL_KINDS - DEFERRED_VISUAL_KINDS
_VIDEO_SCENE_ROLES = ("hook", "body", "outro")


def _default_cta(brand: dict | None = None) -> str:
    """CTA mặc định — Content Factory Phase D (vá rò brand cũ): tên thương
    hiệu đọc từ config/brand.yaml (MỘT NGUỒN, qua config.load_brand()), TUYỆT
    ĐỐI KHÔNG hard-code TÊN BRAND NÀO (cũ hay mới) ở đây — đổi brand chỉ sửa
    brand.yaml, KHÔNG sửa prompt/code. Sự cố THẬT đã gặp: CTA mang brand CŨ
    (đã đổi tên từ lâu) vẫn rò ra sản phẩm video THẬT vì hằng số hard-code ở
    đây không theo kịp lúc chốt brand mới (Phase 1.2 chỉ vá renderer, CHƯA
    quét hết prompt) — xem test_no_old_brand_name_anywhere_in_product_code."""
    b = brand if brand is not None else load_brand()
    name = str(b.get("name") or "").strip()
    return f"Theo dõi {name} để cập nhật phân tích." if name else "Theo dõi để cập nhật phân tích."


def _default_disclaimer(brand: dict | None = None) -> str:
    """Disclaimer mặc định — đọc `footer.disclaimer` từ config/brand.yaml (MỘT
    NGUỒN, cùng brand kit dùng bởi render/infographic.py). _FALLBACK_DISCLAIMER
    CHỈ dùng khi CẢ brand.yaml lẫn key này đều thiếu (môi trường test/lỗi đọc
    file) — không hard-code brand nào, chỉ là câu miễn trừ trách nhiệm chung."""
    b = brand if brand is not None else load_brand()
    footer = b.get("footer") or {}
    return str(footer.get("disclaimer") or "").strip() or _FALLBACK_DISCLAIMER


def _verbatim_disclaimer(candidate: str) -> str:
    """E' (2026-07-24, theo chỉ đạo Lead) — đối chiếu NGUYÊN VĂN `candidate`
    (LLM viết, hoặc đã là default) với bản chuẩn `_default_disclaimer()`
    (config/brand.yaml: footer.disclaimer). Lệch dù 1 ký tự -> GHI ĐÈ bằng bản
    chuẩn TẠI CHỖ (KHÔNG nối thêm bản thứ 2) + CẢNH BÁO rõ (in cả 2 chuỗi, để
    truy vết bản LLM viết là gì). Lý do bắt buộc: disclaimer là dòng miễn trừ
    trách nhiệm PHÁP LÝ (nội dung chứng khoán công bố công khai) — prompt yêu
    cầu LLM viết "đúng nguyên văn" nhưng KHÔNG có gì ép được LLM tuân thủ;
    guardrail cũ (guardrails/compliance.py) chỉ kiểm CÓ MẶT disclaimer, KHÔNG
    kiểm ĐÚNG CHỮ -> bản LLM tự diễn giải (không rỗng) từng lọt xuống production
    mà không ai biết. Khớp NGUYÊN VĂN (kể cả rỗng -> default) là NO-OP, không
    cảnh báo."""
    canonical = _default_disclaimer()
    if candidate.strip() == canonical.strip():
        return canonical
    print(f"[CẢNH BÁO] Disclaimer LLM viết khác bản chuẩn -> GHI ĐÈ (không nối thêm). "
         f"LLM viết: {candidate!r} | Bản chuẩn: {canonical!r}")
    return canonical


# ACTIVE_TASK — Tích hợp CONTENT_WRITER_RULES: đọc prompts/content_writer_
# rules.md TẠI THỜI ĐIỂM GỌI (không cache import-time, CÙNG NẾP với agents/
# voice.assemble_voice đọc docs/voice_examples.md mỗi lần gọi) — sửa rule
# trong file .md KHÔNG cần sửa code. Trích ĐÚNG các mục §-số nguyên thuộc
# nhóm (a) PROMPT (Phase 1 phân loại: §2 nguyên tắc viết cốt lõi dùng chung +
# §3 Article + §4 Video + §5 Infographic) — GHÉP NGUYÊN VĂN, KHÔNG diễn giải
# lại/tóm tắt (file rules là NGUỒN CHUẨN). §1 (quyết định model)/§6-§9
# (checklist/reject-conditions/meta) KHÔNG nhúng ở đây — đó là input cho
# validator (guardrails/) và bước tự-review, không phải nội dung DẠY VĂN.
# Cắt mục theo heading ĐÁNH SỐ CẤP 1. Chấp nhận `# N. ` LẪN `## N. ` vì 2 file
# rule dùng 2 quy ước khác nhau (content_writer_rules.md dùng `#`,
# longform_content_writing_rules.md dùng `##`) — KHÔNG nới thì file longform
# khớp 0 mục và loader trả "" ÂM THẦM (rule không bao giờ được áp, không ai biết).
# `\. ` (dấu chấm + KHOẢNG TRẮNG) giữ nguyên nên mục con `## 2.1.`/`### 2.1.`
# VẪN KHÔNG khớp — xem test_content_writer_rules_section_re_*.
_CONTENT_WRITER_RULES_SECTION_RE = re.compile(r"(?m)^#{1,2} (\d+)\. ")


def _load_content_writer_rules(*, sections: tuple[str, ...], settings=None) -> str:
    """Đọc + trích các mục `sections` (số §, vd ("2","3") cho Article) từ
    `prompts/content_rules_v1.0.md` (đã đổi tên từ `CONTENT_WRITER_RULES.md`
    qua `git mv`, xem Phase A quy ước tên file — đường dẫn qua config, KHÔNG
    hard-code — `writer.content_rules_path`). File thiếu/đọc lỗi -> "" (LÙI
    MƯỢT, agent vẫn chạy bằng persona/schema gốc, KHÔNG crash) + 1 dòng cảnh
    báo console. Hàm THUẦN ngoại trừ đọc đĩa — test được bằng cách trỏ
    `settings` tới file tạm, không cần LLM thật."""
    settings = settings or load_settings()
    path = Path(settings.get("writer.content_rules_path", "prompts/content_rules_v1.0.md"))
    if not path.exists():
        print(f"[CẢNH BÁO] không thấy {path} -> bỏ qua CONTENT_WRITER_RULES (rỗng).")
        return ""
    return _load_content_writer_rules_from_text(path.read_text(encoding="utf-8"), sections)


# BƯỚC 1 (rules v2.1, 2026-07-22) — v2.1 là RULES MẶC ĐỊNH cho Composer TRƯỚC
# Phase A, áp MỌI loại content_type. A (content_rules_v1.0.md, rule cũ) và C
# (c_unified_longform_rules.md, hợp nhất longform — kết quả thí nghiệm A/B/C)
# GIỮ làm DỰ PHÒNG, chọn qua `writer.rules_profile` ("v21" mặc định | "A" |
# "C") — KHÔNG XOÁ. Hàm này KHÔNG đụng `_load_content_writer_rules` ở trên
# (giữ nguyên — ~10 test gọi trực tiếp, phụ thuộc đọc THẲNG content_rules_v1.
# 0.md qua `writer.content_rules_path`) — chỉ ĐỊNH TUYẾN profile rồi gọi lại
# hàm cũ HOẶC logic trích riêng cho v2.1 (numbering khác hẳn, xem dưới).
#
# PHASE A (rules loader v3+, 2026-07-3x, gói Lead) — toàn bộ nhánh v21/A/C
# dưới đây giờ là NHÁNH "legacy_sections" (`writer.rules_load_mode`), GIỮ
# NGUYÊN 100% hành vi cũ khi mode này được chọn (mặc định khi KHÔNG set
# rules_load_mode — tương thích ngược tuyệt đối, không phá pipeline đang
# chạy). Nhánh MỚI "full" (nạp nguyên văn v3+, xem `_load_rules_full`) đứng
# TRƯỚC, tách bạch hoàn toàn — không tái dùng biến/hàm của nhánh cũ để tránh
# lẫn 2 hình dạng dữ liệu.
_LEGACY_SECTIONS_BY_TYPE = {"article": ("2", "3"), "video": ("2", "4"), "infographic": ("2", "5"),
                           # VIỆC 1 -- lưới an toàn nếu rules_load_mode lùi về
                           # legacy_sections: long_article dùng CHUNG mục với
                           # article (KHÔNG có mục riêng ở rules cũ, hàm _load_
                           # composer_rules() nạp thêm supplement CHỈ ở nhánh
                           # "full" — nhánh này KHÔNG PHẢI đường sản xuất).
                           "long_article": ("2", "3")}

# v2.1 core dùng CHUNG mọi loại: §1 mục tiêu, §2 thứ tự ưu tiên, §3 ranh giới
# bắt buộc, §4 cấu trúc vừa đủ, §5 không gian sáng tạo, §6 chất lượng lập luận/
# văn phong. KHÔNG gồm §7 (theo loại — trích RIÊNG dưới), §8 (validation —
# tài liệu cho VALIDATOR, không phải Composer), §9/§10 (checklist/nguyên tắc
# cuối, giống §6-9 content_rules_v1.0.md CŨ cũng không nhúng — input cho
# guardrail/self-review, không phải "dạy văn").
_V21_CORE_SECTIONS = ("1", "2", "3", "4", "5", "6")
_V21_PRODUCT_SUBSECTION = {"article": "7.1", "video": "7.2", "infographic": "7.3",
                          "long_article": "7.1"}   # VIỆC 1 -- cùng lưới an toàn, xem _LEGACY_SECTIONS_BY_TYPE
_V21_SUBSECTION_RE_CACHE: dict[str, re.Pattern] = {}


def _v21_subsection_re(num: str) -> re.Pattern:
    if num not in _V21_SUBSECTION_RE_CACHE:
        _V21_SUBSECTION_RE_CACHE[num] = re.compile(
            r"(?m)^### " + re.escape(num) + r"\. .*?(?=\n### \d|\n## \d|\Z)", re.S)
    return _V21_SUBSECTION_RE_CACHE[num]


# PHASE A1/A2 — nhánh "full" (rules v3+, KHÔNG cắt mục). File v3.4/v3.0/v2.1
# KHÔNG còn thiết kế theo "trích §N riêng cho content_type" như v2.1 cũ —
# phạm vi áp dụng đã tự ghi ngay trong file (xem đầu content-rules-daily-v3.4.
# md: "Phạm vi: Article · Infographic · Video"). A2 CẤM hard-code tên file/số
# mục -- default dưới đây CHỈ là fallback khi config không set, giống mọi
# hằng số _DEFAULT_* khác trong repo (config LUÔN thắng).
_DEFAULT_RULES_FULL_PATH = "prompts/content-rules-daily-v3.4.md"

# VIỆC 1 (2026-08-03, Lead) — content_type="long_article" nạp THÊM file này
# SAU file nền (_DEFAULT_RULES_FULL_PATH/content_rules_path) -- "bổ sung,
# không thay thế" (xem header content-rules-deep-v3.0.md: "Nạp độc lập... nạp
# thêm"). Fallback khi config không set `writer.content_rules_supplement_path`,
# cùng quy ước A2 với _DEFAULT_RULES_FULL_PATH ở trên.
_DEFAULT_RULES_SUPPLEMENT_PATH = "prompts/content-rules-deep-v3.0.md"


def _load_rules_full(path: Path) -> str:
    """A1 — nạp NGUYÊN VĂN, KHÔNG cắt mục nào. Chỉ rstrip khoảng trắng thừa
    cuối file, không đụng nội dung (khác hẳn `_load_content_writer_rules_
    from_text` ở nhánh legacy_sections, vốn CẮT theo số §)."""
    return path.read_text(encoding="utf-8").rstrip()


def _sha256_text(text: str) -> str:
    """A4 — SHA-256 của NỘI DUNG rules đã nạp (không phải đường dẫn) -- đổi 1
    ký tự trong file là đổi hash, truy vết được bài nào dùng ĐÚNG bản nào kể
    cả khi tên file không đổi."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _append_rules_run_state(*, content_type: str, path: Path, sha256: str, mode: str, settings=None) -> None:
    """A4 — ghi 1 dòng JSONL truy vết "bài nào dùng bản rules nào" (đường dẫn
    + SHA-256 NỘI DUNG tại thời điểm nạp + mode + content_type + mốc giờ).
    Ghi dưới `state/` (CÙNG NẾP `state/router_decisions.json`,
    `state/production_drafts` đã có trong storage.*_dir) — KHÔNG đụng store/
    (vùng agent hạ tầng Sheet/queue, ranh giới nhiệm vụ này). Lỗi ghi (đĩa
    đầy, quyền...) KHÔNG được làm hỏng cả lượt sản xuất -- nuốt, chỉ cảnh báo
    console, cùng triết lý LÙI MƯỢT của cả module này."""
    try:
        log_path = data_path("state", "rules_run_log.jsonl", settings=settings)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "content_type": content_type,
            "path": str(path),
            "sha256": sha256,
            "mode": mode,
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"[CẢNH BÁO] không ghi được state/rules_run_log.jsonl (A4): {e}")


def _load_composer_rules(content_type: str, *, settings=None) -> str:
    """Điểm ĐỊNH TUYẾN DUY NHẤT rules cho 3 Composer (Analysis/Video/Infographic).

    PHASE A (2026-07-3x) — `writer.rules_load_mode` là công tắc TƯỜNG MINH,
    KHÔNG suy đoán từ heading file (A2 — bỏ hẳn kiểu nhận diện "# PHẦN..."):
      "full"            -> nạp NGUYÊN VĂN `writer.content_rules_path`
                           (mặc định `_DEFAULT_RULES_FULL_PATH`), không cắt
                           mục nào (A1). ĐÂY LÀ MẶC ĐỊNH SẢN XUẤT MỚI (xem
                           config/settings.yaml — Lead chọn v3.4 sau khi P0
                           xong, LEAD_DECISION_INPUT_STRICTNESS.md §9.1).
      "legacy_sections" (mặc định CODE khi KHÔNG set rules_load_mode, tương
                         thích ngược tuyệt đối) -> HỆT hành vi trước Phase A:
                         override `content_rules_path` (nếu set) LUÔN THẮNG,
                         qua `_load_content_writer_rules` cắt §N theo
                         `_LEGACY_SECTIONS_BY_TYPE`; không thì định tuyến
                         `writer.rules_profile` (v21 mặc định | A | C).

    Cả 2 nhánh đều ghi SHA-256 + đường dẫn vào `state/rules_run_log.jsonl`
    (A4) mỗi lần nạp THÀNH CÔNG (rỗng/lỗi thì không ghi — không có gì để
    truy vết). File thiếu/lỗi -> "" (LÙI MƯỢT, agent vẫn chạy bằng persona/
    schema gốc, KHÔNG crash)."""
    settings = settings or load_settings()
    mode = str(settings.get("writer.rules_load_mode", "legacy_sections")).strip() or "legacy_sections"

    if mode == "full":
        path = Path(settings.get("writer.content_rules_path", _DEFAULT_RULES_FULL_PATH))
        if not path.exists():
            print(f"[CẢNH BÁO] không thấy {path} (rules_load_mode=full) -> bỏ qua rules (rỗng).")
            return ""
        text = _load_rules_full(path)
        if content_type == "long_article":
            # VIỆC 1 -- nạp nền TRƯỚC (đã xong ở trên), bổ sung SAU, NỐI NGUYÊN
            # VĂN cả 2 (không cắt mục nào) — "nạp KÈM, không thay thế" (header
            # content-rules-deep-v3.0.md). Thiếu file bổ sung -> LÙI MƯỢT, vẫn
            # trả nền (KHÔNG rỗng cả 2 vì thiếu 1 file phụ).
            supp_path = Path(settings.get("writer.content_rules_supplement_path",
                                          _DEFAULT_RULES_SUPPLEMENT_PATH))
            if supp_path.exists():
                supp_text = _load_rules_full(supp_path)
                if supp_text:
                    text = text + "\n\n---\n\n" + supp_text if text else supp_text
            else:
                print(f"[CẢNH BÁO] không thấy {supp_path} (long_article bổ sung) -> chỉ dùng nền.")
        if text:
            _append_rules_run_state(content_type=content_type, path=path,
                                    sha256=_sha256_text(text), mode=mode, settings=settings)
        return text

    # mode == "legacy_sections" — GIỮ NGUYÊN 100% hành vi trước Phase A.
    if str(settings.get("writer.content_rules_path", "")).strip():
        override_path = Path(settings.get("writer.content_rules_path", ""))
        text = _load_content_writer_rules(sections=_LEGACY_SECTIONS_BY_TYPE[content_type], settings=settings)
        if text:
            _append_rules_run_state(content_type=content_type, path=override_path,
                                    sha256=_sha256_text(text), mode=f"{mode}:override", settings=settings)
        return text

    profile = str(settings.get("writer.rules_profile", "v21")).strip() or "v21"
    if profile == "C" and content_type != "article":
        profile = "A"   # C không có mục video/infographic -> lùi về A

    if profile == "A":
        path = Path(settings.get("writer.content_rules_path", "prompts/content_rules_v1.0.md"))
        text = _load_content_writer_rules(sections=_LEGACY_SECTIONS_BY_TYPE[content_type], settings=settings)
        if text:
            _append_rules_run_state(content_type=content_type, path=path,
                                    sha256=_sha256_text(text), mode=f"{mode}:A", settings=settings)
        return text

    if profile == "C":
        path = Path(settings.get("writer.rules_c_path", "prompts/c_unified_longform_rules.md"))
        if not path.exists():
            print(f"[CẢNH BÁO] không thấy {path} -> bỏ qua rules profile C (rỗng).")
            return ""
        text = path.read_text(encoding="utf-8").strip()   # C không tách content_type -> dùng NGUYÊN VĂN
        if text:
            _append_rules_run_state(content_type=content_type, path=path,
                                    sha256=_sha256_text(text), mode=f"{mode}:C", settings=settings)
        return text

    # v21 (mặc định) — trích core (§1-6) + đúng sub-section §7.N theo content_type.
    path = Path(settings.get("writer.rules_v21_path", "prompts/content-rules-v2.1.md"))
    if not path.exists():
        print(f"[CẢNH BÁO] không thấy {path} -> bỏ qua rules v2.1 (rỗng).")
        return ""
    text = path.read_text(encoding="utf-8")
    core = _load_content_writer_rules_from_text(text, _V21_CORE_SECTIONS)
    sub_num = _V21_PRODUCT_SUBSECTION[content_type]
    m = _v21_subsection_re(sub_num).search(text)
    # rstrip dấu "---" (hr phân cách trước mục kế) lẫn vào cuối do lookahead chỉ
    # dừng Ở HEADING kế, không loại dòng hr đứng giữa.
    product = re.sub(r"\n+---\s*\Z", "", m.group(0).rstrip()) if m else ""
    result = "\n\n".join(b for b in (core, product) if b)
    if result:
        _append_rules_run_state(content_type=content_type, path=path,
                                sha256=_sha256_text(text), mode=f"{mode}:v21", settings=settings)
    return result


def _load_content_writer_rules_from_text(text: str, sections: tuple[str, ...]) -> str:
    """Lõi trích-mục DÙNG CHUNG (tách khỏi `_load_content_writer_rules` để tái
    dùng trên văn bản đã đọc sẵn — v2.1 cần đọc 1 LẦN rồi trích 2 lượt: core +
    sub-section, đọc đĩa 2 lần là lãng phí không cần thiết)."""
    matches = list(_CONTENT_WRITER_RULES_SECTION_RE.finditer(text))
    blocks: list[str] = []
    for i, m in enumerate(matches):
        if m.group(1) not in sections:
            continue
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks.append(text[start:end].rstrip())
    return "\n\n".join(blocks)


_JSON_ONLY = "\n\nCHỈ trả JSON đúng schema, KHÔNG markdown, KHÔNG lời dẫn."

# PERSONA của AnalysisWriterAgent/VideoScriptAgent (system prompt, xem 2 class
# bên dưới) đọc tên brand 1 LẦN lúc import module — CÙNG NẾP với mọi `system`
# khác trong file này (hằng số string tĩnh, đối chiếu 1-1 với prompts/*.v1.md
# qua test_prompts_*_file_matches_code_default_no_drift, xem tests/test_
# pipeline.py) — KHÔNG đổi sang property/method động (sẽ vỡ đối chiếu chuỗi
# tĩnh đó). Đổi brand.yaml rồi restart tiến trình là đủ, khớp cách load_settings()
# cũng chỉ đọc 1 lần mỗi lượt chạy script.
_BRAND_NAME = str(load_brand().get("name") or "").strip() or "đội ngũ phân tích"

# Phase 4.13 Mục B — dùng CHUNG cho AnalysisWriterAgent + InfographicSpecAgent
# (composer), tránh trôi giữa 2 nơi. Xem docstring module đầu file.
_NUMBER_DISCIPLINE = (
    "\nKỶ LUẬT SỐ (BẮT BUỘC, Phase 4.13 — giảm NEEDS_HUMAN oan do tự chế số):\n"
    "- MỌI số bạn viết PHẢI Y NGUYÊN VĂN như trong content_units[].raw (hoặc evidence "
    "nếu không có content_units) — KHÔNG tự CỘNG/GỘP nhiều số RIÊNG LẺ thành 1 số MỚI "
    "(vd evidence có '89.000 tỷ đồng' và '125.000 tỷ đồng' ở 2 câu KHÁC NHAU -> "
    "CẤM tự cộng ra '214.000 tỷ đồng' hay bất kỳ số tổng nào KHÔNG có sẵn "
    "nguyên văn trong content_units[]/evidence).\n"
    "- KHÔNG tự đổi/rớt ĐƠN VỊ hay BẬC SỐ (vd evidence viết '357.000 tỷ đồng' -> "
    "PHẢI giữ đúng '357.000 tỷ đồng' hoặc '357 nghìn tỷ đồng' — TUYỆT ĐỐI KHÔNG "
    "viết thành '357 tỷ' vì đã làm mất 3 chữ số 0, sai lệch 1.000 LẦN).\n"
    "- QUY ƯỚC SỐ TIẾNG VIỆT (đọc SAI 2 dấu này là nguồn lỗi lệch bậc số phổ "
    "biến nhất — LUÔN đếm lại số chữ số trước khi viết): dấu CHẤM (.) = phân "
    "cách HÀNG NGHÌN của PHẦN NGUYÊN (vd '357.000' = ba trăm năm mươi bảy "
    "NGHÌN); dấu PHẨY (,) = phân cách PHẦN THẬP PHÂN sau hàng đơn vị (vd "
    "'8,18%' = tám phẩy mười tám phần trăm, KHÔNG phải 818%).\n"
    "- Muốn dùng SỐ TỔNG (vd tổng nhiều khoản) -> CHỈ dùng nếu con số tổng đó "
    "ĐÃ có sẵn NGUYÊN VĂN trong content_units[]/evidence (ai đó đã tính sẵn và công bố) "
    "— KHÔNG tự làm phép cộng/trừ/nhân/chia rồi trình bày như số THẬT của nguồn."
)

# Dữ kiện gây chú ý dạng số (dùng cho cả anti-hallucination guardrail lẫn trích
# stat cho infographic): số tiền/%/kỷ lục.
_MAGNITUDE_RE = re.compile(
    r"\d[\d.,]*\s*(?:%|tỷ đồng|nghìn tỷ|tỷ|triệu|usd|đồng)", re.IGNORECASE)

# TASK-027 (Guardrail HAI TẦNG) — Tầng 1: bù ca THẬT gặp trên evidence full-
# fetch (vd vietnambiz.vn, xem docs/hypotheses/2026-08-12-guardrail-hai-tang.md):
# HTML->markdown đôi khi chèn khoảng trắng LẠC giữa từng ký tự số ("7 , 7 7 tỷ
# cổ phiếu" thay vì "7,77 tỷ cổ phiếu", "41 ,7 triệu" thay vì "41,7 triệu") —
# _MAGNITUDE_RE (\d[\d.,]*, KHÔNG cho khoảng trắng giữa các ký tự) bỏ lọt hoàn
# toàn, khiến Composer viết ĐÚNG số "7,77 tỷ" bị báo ĐỘNG GIẢ "bịa số". Regex
# này NỚI để bắt được cụm đó — CHỈ dùng quét evidence/background (KHÔNG áp cho
# body, Composer luôn viết số liền mạch) và CHỈ khớp khi cụm digit/dấu-tách
# liền NHAU (không xen chữ) NGAY SAU LÀ đơn vị — an toàn với enumeration kiểu
# "Phân khu 2, 4 và 9, cùng 350 tỷ đồng" (chữ "và"/"cùng" xen giữa chặn match,
# xem test_unsupported_numbers_spaced_digit_*).
_SPACED_MAGNITUDE_RE = re.compile(
    r"\d(?:[ \t]*[.,]?[ \t]*\d)*[ \t]*(?:%|tỷ đồng|nghìn tỷ|tỷ|triệu|usd|đồng)",
    re.IGNORECASE)


@dataclass
class ProductionBrief:
    """Đầu vào sản xuất — dựng từ 1 dòng CONTEXT đã APPROVE (+ full-fetch bài)."""
    title: str                                   # CONTEXT.Context (tiêu đề bài)
    hook: str = ""                               # CONTEXT.Hook (tiêu đề gợi ý)
    tickers: list[str] = field(default_factory=list)
    group: str = ""                              # CONTEXT.Group
    topic: str = ""                              # CONTEXT.Topic
    url: str = ""                                # CONTEXT.Source (bài chính)
    evidence: str = ""                           # thân bài (full-fetch) để LLM bám + chống bịa số
    background: str = ""                         # bối cảnh/tiền lệ research THÊM (Claude Code tự tìm)
    content_units: list[ContentUnit] = field(default_factory=list)  # số liệu đã gắn nhãn (agents/brief.py, Phase 2)
    no_numeric_content: bool = False   # Phase 4.12: Brief xác nhận CHẮC CHẮN tin không có số (content_units=[] hợp lệ, khác content_units=[] do Brief hỏng — xem agents/brief.BriefResult)


def _tickers_line(brief: ProductionBrief) -> str:
    return ", ".join(brief.tickers) or "N/A"


def _soft_truncate(text: str, limit: int) -> str:
    """Cắt `text` về TỐI ĐA `limit` ký tự nhưng KHÔNG cắt GIỮA 1 từ (Phase
    4.11, item 6 — sửa lỗi cắt cụt giữa chữ ở các đường LÙI MƯỢT article/video,
    vd cũ 'brief.evidence[:200]' có thể đứt ngang 1 từ). Lùi về khoảng trắng
    GẦN NHẤT trước `limit`; không có khoảng trắng nào (1 từ dài hơn limit) ->
    cắt cứng như cũ (không còn lựa chọn nào tốt hơn). text ngắn hơn limit ->
    giữ NGUYÊN, không thêm "…". Hàm THUẦN — test được không cần Brief thật."""
    text = text or ""
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit)
    return text[:cut if cut > 0 else limit].rstrip() + "…"


def domain_of(url: str) -> str:
    """Tên miền để trích nguồn TẤT ĐỊNH (vd 'cafef.vn'). URL rỗng/hỏng -> ''."""
    try:
        return (urlparse(url).netloc or "").removeprefix("www.")
    except Exception:
        return ""


def _normalize_number(token: str) -> str:
    """Chuẩn hoá SO SÁNH 1 token số (Phase 4.6, sửa false-positive phát hiện
    khi validate): bỏ hết dấu '.'/',' trong token — token do _MAGNITUDE_RE bắt
    CHỈ chứa số + đơn vị (không có câu chữ khác lẫn vào) nên an toàn để bỏ dấu
    phân cách, bất kể kiểu viết: evidence gốc hay để dấu CHẤM thập phân kiểu
    quốc tế ("12.61%" — dữ liệu bảng/HOSE), trong khi Writer viết đúng chuẩn
    tiếng Việt bằng dấu PHẨY ("12,61%") — không chuẩn hoá thì 2 chuỗi này
    KHÁC NHAU dù CÙNG 1 con số, gây báo sai 'bịa số'.

    TASK-027 (Tầng 1): CŨNG bỏ khoảng trắng (thêm '\\s' vào lớp ký tự bỏ) —
    "thống nhất dấu thập phân" CHỈ đủ nếu 2 vế không lệch nhau ở khoảng trắng
    NỘI BỘ cụm số; ca thật evidence chèn khoảng trắng lạc giữa ký tự số (xem
    _SPACED_MAGNITUDE_RE) cần bước này để so khớp ra bằng nhau."""
    return re.sub(r"[.,\s]", "", token.lower().strip())


_DEFAULT_APPROX_TOLERANCE = 0.05   # Mục C: nới ≤5% CHỈ KHI số TRONG BÀI đi kèm từ xấp xỉ
_APPROX_LOOKBACK = 12               # số ký tự nhìn NGƯỢC trước token để tìm từ xấp xỉ


def _matches_canonical_fact(tok: str, body: str, start: int, content_units: list[ContentUnit],
                            tolerance: float) -> bool:
    """Mục C (Phase 4.8; mở rộng Content Factory Phase 1 — range/delta): số
    TRONG BÀI (`tok`, tại vị trí `start`) HỢP LỆ nếu khớp BẤT KỲ trường
    canonical_* nào có mặt trên 1 fact: canonical_value (shape=scalar) lệch ≤
    `tolerance`; NẰM TRONG [canonical_low, canonical_high] (shape=range, biên
    nới thêm theo `tolerance` CHỈ khi có từ xấp xỉ — số NẰM SẴN trong range
    khớp dù không có từ xấp xỉ, đúng bản chất range, khớp media_factory/
    spec._fact_matches cho NHẤT QUÁN 2 lượt guardrail); khớp canonical_from
    HOẶC canonical_to (shape=delta). `tolerance` = 0 (khớp chính xác) CHỈ nới
    lên khi `tok` trong bài đi kèm từ xấp xỉ ngay trước nó — xem apply_
    guardrails/unsupported_numbers. shape=entity/entity_list KHÔNG có
    canonical_* số nào -> tự động bỏ qua ở đây (guardrail TÊN chưa có ở lượt
    1, xem media_factory/spec._check_plain_list_item_entity cho lượt 2). So
    khớp SỐ HỌC tất định (agents/_numeric.py) — guardrail luôn là CODE, KHÔNG
    bao giờ để AI phán 1 số là an toàn."""
    val = parse_magnitude_token(tok)
    if val is None:
        return False
    effective_tolerance = tolerance if has_approx_word(body[max(0, start - _APPROX_LOOKBACK):start]) else 0.0
    for f in content_units:
        if f.canonical_value is not None and f.canonical_value != 0:
            if abs(val - f.canonical_value) / abs(f.canonical_value) <= effective_tolerance:
                return True
        if f.canonical_low is not None and f.canonical_high is not None:
            lo, hi = sorted((f.canonical_low, f.canonical_high))
            slack = (hi - lo) * effective_tolerance
            if lo - slack <= val <= hi + slack:
                return True
        if f.canonical_from is not None and f.canonical_from != 0:
            if abs(val - f.canonical_from) / abs(f.canonical_from) <= effective_tolerance:
                return True
        if f.canonical_to is not None and f.canonical_to != 0:
            if abs(val - f.canonical_to) / abs(f.canonical_to) <= effective_tolerance:
                return True
    return False


def unsupported_numbers(body: str, source_text: str, content_units: list[ContentUnit] | None = None, *,
                        approx_tolerance: float = _DEFAULT_APPROX_TOLERANCE) -> list[str]:
    """Số liệu tài chính (%, tỷ, triệu...) xuất hiện trong `body` nhưng KHÔNG có
    trong `source_text` (evidence + background gộp lại) VÀ không khớp canonical
    nào trong `content_units` -> nghi bịa số. Hàm THUẦN, dùng bởi apply_guardrails().
    Thứ tự kiểm (dừng ở bước đầu tiên khớp):
      1. So khớp CHÍNH XÁC trong evidence.
      2. Sau khi chuẩn hoá dấu thập phân (_normalize_number, Phase 4.6 fix 1) —
         chấp nhận Writer đổi "12.61%" (evidence) thành "12,61%" (chuẩn tiếng
         Việt) mà KHÔNG coi là bịa số, miễn CHỮ SỐ giống hệt.
      3. Mục C (Phase 4.8): khớp SỐ HỌC với 1 fact.canonical_value trong dung
         sai (0% mặc định; ≤ approx_tolerance nếu số trong bài đi kèm từ xấp
         xỉ) — `content_units` rỗng/None -> bước này no-op, hành vi y hệt trước Mục C.
      4. TASK-027 (Tầng 1): CŨNG khớp token bắt được qua _SPACED_MAGNITUDE_RE
         (evidence bị chèn khoảng trắng lạc giữa ký tự số, xem docstring regex
         đó) — dùng CHUNG _normalize_number nên tự động gộp bước 2."""
    low = source_text.lower()
    evidence_norm = {_normalize_number(m.group(0)) for m in _MAGNITUDE_RE.finditer(source_text)}
    evidence_norm |= {_normalize_number(m.group(0)) for m in _SPACED_MAGNITUDE_RE.finditer(source_text)}
    content_units = content_units or []
    bad, seen = [], set()
    for m in _MAGNITUDE_RE.finditer(body):
        tok = m.group(0)
        key = tok.lower().strip()
        if key in low or key in seen:
            continue
        if _normalize_number(tok) in evidence_norm:
            continue   # khớp sau khi chuẩn hoá dấu thập phân -> KHÔNG nghi bịa
        if content_units and _matches_canonical_fact(tok, body, m.start(), content_units, approx_tolerance):
            continue   # khớp canonical (đúng số hoặc làm tròn hợp lý) -> KHÔNG nghi bịa
        seen.add(key)
        bad.append(tok)
    return bad


def _fact_source_tokens(source_sentence: str) -> set[str]:
    """TASK-027 (Tầng 2) — set số CHUẨN HOÁ trích từ `source_sentence` (CÂU
    NGUYÊN VĂN của 1 ContentUnit, field `source` — xem models.ContentUnit).
    Gộp CẢ _MAGNITUDE_RE lẫn _SPACED_MAGNITUDE_RE (cùng lý do Tầng 1 — câu
    nguồn cũng trích từ evidence full-fetch, có thể dính cùng lỗi chèn khoảng
    trắng)."""
    tokens = {_normalize_number(m.group(0)) for m in _MAGNITUDE_RE.finditer(source_sentence)}
    tokens |= {_normalize_number(m.group(0)) for m in _SPACED_MAGNITUDE_RE.finditer(source_sentence)}
    return tokens


def _anchor_fact_count(tok: str, start: int, body: str, content_units: list[ContentUnit],
                       tolerance: float) -> int:
    """TASK-027 (Tầng 2) — đếm SỐ content_units mà `tok` (số TRONG BODY, tại vị
    trí `start`) neo được: literal (chuẩn hoá) trong CÂU NGUỒN của CHÍNH fact đó
    (`f.source`, xem _fact_source_tokens) HOẶC khớp canonical số học CỦA RIÊNG
    fact đó (tái dùng _matches_canonical_fact — NHƯNG xét TỪNG fact 1 LÚC, khác
    _matches_canonical_fact gọi trực tiếp ở unsupported_numbers xét CẢ danh sách
    cùng lúc). Xét riêng từng fact để phân biệt "neo ĐÚNG 1 câu" khỏi "khớp số
    học trùng hợp ở NHIỀU fact khác nhau" — xem unanchored_numbers/vi_sao_hai_tang
    trong TASK-027 contract."""
    return sum(
        1 for f in content_units
        if _normalize_number(tok) in _fact_source_tokens(f.source)
        or _matches_canonical_fact(tok, body, start, [f], tolerance)
    )


def unanchored_numbers(body: str, content_units: list[ContentUnit] | None = None, *,
                       approx_tolerance: float = _DEFAULT_APPROX_TOLERANCE) -> list[str]:
    """TẦNG 2 (TASK-027) — CẢNH BÁO, KHÔNG chặn. Số liệu trong `body` KHÔNG neo
    được về ĐÚNG MỘT CÂU nguồn qua content_units[].source: 0 câu = không fact
    nào trích ra số này (dù có mặt đâu đó trong toàn văn bài gốc — lỗ hổng Tầng
    1 sau khi nới sang toàn văn, xem module docstring "vi_sao_hai_tang" +
    docs/hypotheses/2026-08-12-guardrail-hai-tang.md); >1 câu KHÁC NHAU = mơ
    hồ, không rõ số đang neo vào dữ kiện nào. Hàm THUẦN, dùng bởi apply_
    guardrails() — kết quả trả về đây TUYỆT ĐỐI KHÔNG được gộp vào
    compliance_issues/draft.is_clean (cam kết TASK-027: 'KHÔNG để tầng 2 chặn').
    `content_units` rỗng/None -> [] (không có fact nào để neo, không có cơ sở
    để cảnh báo — tránh ngập cảnh báo vô nghĩa khi Brief chưa/không trích
    được content_units)."""
    content_units = content_units or []
    if not content_units:
        return []
    warn, seen = [], set()
    for m in _MAGNITUDE_RE.finditer(body):
        tok = m.group(0)
        key = tok.lower().strip()
        if key in seen:
            continue
        if _anchor_fact_count(tok, m.start(), body, content_units, approx_tolerance) != 1:
            seen.add(key)
            warn.append(tok)
    return warn


def apply_guardrails(draft: ContentDraft, evidence: str, background: str = "",
                     content_units: list[ContentUnit] | None = None, *,
                     approx_tolerance: float = _DEFAULT_APPROX_TOLERANCE, title: str = "") -> ContentDraft:
    """Chạy compliance.check (disclaimer/claim cấm) + chặn bịa số (evidence +
    background gộp lại — background = bối cảnh Claude Code research thêm khi
    viết; `content_units` (agents/brief.py, tuỳ chọn) cho phép số làm tròn hợp lý khớp
    canonical, xem unsupported_numbers). Gắn draft.compliance_issues
    (Status=ERROR nếu vi phạm). Trả lại draft.

    TASK-027 (Guardrail HAI TẦNG):
      Tầng 1 (CHẶN, không đổi cơ chế — chỉ nới vế `source_text`): `title` (tuỳ
      chọn, mặc định "" — 100% tương thích ngược cho call site CHƯA truyền,
      xem scope allowed_paths TASK-027 không gồm writer.py/scripts/) nối vào
      ĐẦU `source_text` cùng evidence/background, hiện thực "TOÀN VĂN bài gốc
      = tiêu đề + thân bài" đúng thiết kế chốt.
      Tầng 2 (CẢNH BÁO, KHÔNG chặn): gắn draft.numeric_anchor_warnings — ATTRIBUTE
      ĐỘNG, KHÔNG PHẢI field khai báo trong ContentDraft (models.py NGOÀI
      scope.allowed_paths của TASK-027, xem contract) — để KHÔNG đổi
      draft.is_clean/Status ERROR ở scripts/produce_from_sheet.py (cũng ngoài
      scope, forbidden_paths). Wiring THẬT vào cột Notes trên Sheet (không đổi
      Status) là việc của 1 task SAU, chạm scripts/ (hiện bị cấm ở đây) — xem
      sheets_board.append_anchor_warnings() cho phần dịch/format đã chuẩn bị sẵn."""
    issues = compliance.check(draft)
    source_text = f"{title}\n{evidence}\n{background}".strip()
    if source_text:   # infographic trích số THẲNG từ evidence -> luôn rỗng, bỏ qua vô ích
        issues += [f"Số liệu không thấy trong evidence/background: {t}" for t in
                   unsupported_numbers(draft.body, source_text, content_units, approx_tolerance=approx_tolerance)]
    draft.compliance_issues = issues
    draft.numeric_anchor_warnings = unanchored_numbers(draft.body, content_units,
                                                        approx_tolerance=approx_tolerance)
    return draft


class AnalysisWriterAgent(Agent):
    role = "AnalysisWriter"
    prompt_name = "analysis"          # khớp tab PROMPTS.Name + prompts/analysis.<v>.md
    system = (
        f"PERSONA: Bạn là cây bút phân tích trưởng của {_BRAND_NAME} — giọng SẮC,\n"
        "có QUAN ĐIỂM riêng (trung lập về khuyến nghị mua/bán, nhưng KHÔNG lấp\n"
        "lửng khi gọi tên vấn đề). Bạn KHÔNG tường thuật lại 1 bài báo — bạn TỔNG\n"
        "HỢP, xâu chuỗi sự kiện hiện tại với bối cảnh/tiền lệ liên quan để người\n"
        "CHƯA đọc tin trước đó vẫn hiểu toàn cảnh. Đây là điểm khác biệt (signature)\n"
        "so với mặt bằng tin tức thông thường.\n"
        "QUY TẮC BẮT BUỘC:\n"
        "- Mở bài bằng NHẬN ĐỊNH sắc nhất của bạn về ý nghĩa sự kiện — KHÔNG mở\n"
        "  bằng cách tóm tắt tin như báo chí.\n"
        "- Nếu có mục 'Bối cảnh mở rộng (research)' trong dữ kiện: PHẢI dùng để\n"
        "  dựng 1 phần riêng trong bài, xâu chuỗi tiền lệ/diễn biến trước đó —\n"
        "  không chỉ dựa vào 1 bài báo gốc.\n"
        "- MỖI phần phải có NHẬN ĐỊNH của người viết (ý nghĩa/rủi ro/so sánh),\n"
        "  không chỉ liệt kê dữ kiện.\n"
        "- BÁM SỐ LIỆU trong evidence/bối cảnh được cung cấp — KHÔNG bịa số.\n"
        "- KHÔNG khuyến nghị mua/bán.\n"
        f'- "disclaimer": PHẢI dùng ĐÚNG NGUYÊN VĂN "{_default_disclaimer()}" (KHÔNG viết '
        "lại/diễn giải/thêm bớt chữ nào — đây là câu miễn trừ trách nhiệm CHUẨN, đã duyệt).\n"
        + _NUMBER_DISCIPLINE +
        '\nTrả về DUY NHẤT JSON: {"title": str, "sapo": str, '
        '"sections": [{"heading": str, "content": str}], '
        '"disclaimer": str, "sources": [str]}.'
    )

    def run(self, brief: ProductionBrief) -> ContentDraft:
        # decision=None -> fallback an toàn S1+H3+D (chưa chạy StructureRouter ở
        # đường LEGACY này — xem agents/writer.py cho đường MỚI có router thật).
        voice = assemble_voice(None)
        extra = f"\n\n---\n\nVOICE-LOCK (giọng văn bắt buộc):\n{voice}" if voice else ""
        rules = _load_composer_rules("article", settings=self.rules_settings)
        if rules:
            extra += f"\n\n---\n\nCONTENT_WRITER_RULES (bắt buộc, nguồn chuẩn):\n{rules}"
        data = try_json_object(self._ask(build_analysis_prompt(brief), extra_system=extra))
        try:
            title, sapo, sections, disclaimer, sources = analysis_fields_from_data(data, brief)
        except EmptySectionsError as e:
            # Đường LEGACY (không qua run_writer_with_retry) -- KHÔNG tự dựng
            # bài thay Composer (xem EmptySectionsError), trả draft rỗng kèm lý
            # do trong compliance_issues để caller thấy NEEDS_HUMAN (is_clean=False).
            return ContentDraft(fmt=ContentFormat.ARTICLE, title=brief.title, body="",
                                brief_topic=brief.topic, compliance_issues=[str(e)])
        body = render_analysis(title, sapo, sections, disclaimer, sources, brief)
        return ContentDraft(fmt=ContentFormat.ARTICLE, title=title, body=body,
                            brief_topic=brief.topic)


def _background_block(brief: ProductionBrief) -> str:
    return f"\nBối cảnh mở rộng (research): {brief.background[:1500]}" if brief.background else ""


def build_analysis_prompt(brief: ProductionBrief) -> str:
    """Prompt (user turn) cho AnalysisWriterAgent — tách riêng để CÓ THỂ dùng mà
    KHÔNG gọi AnthropicLLM: xem scripts/produce_from_sheet.py --draft (nhờ Claude
    Code viết trực tiếp thay vì gọi API riêng — xem docs/production_agents_design.md)."""
    return (
        f"Tiêu đề: {brief.title}\nGóc marketing: {brief.hook}\n"
        f"Mã: {_tickers_line(brief)}\nNguồn: {brief.url}\n"
        f"Dữ kiện (evidence): {brief.evidence[:1500]}" + _background_block(brief) + _JSON_ONLY
    )


class EmptySectionsError(ValueError):
    """Lead 02/08 (Nhóm B, cùng loại bug với subtitle/related nhưng NẶNG NHẤT:
    bịa CẢ BÀI thay vì 1 trường) — Composer (Writer) trả JSON HỢP LỆ nhưng
    sections RỖNG (tường minh "sections": [] HOẶC thiếu hẳn key), KHÁC HẲN
    data=None/lỗi hạ tầng (case đó vẫn LÙI MƯỢT, xem test_production_agent_
    graceful_empty_llm — KHÔNG đụng).

    Trước đây: coi sections rỗng = "Composer fail cần cứu", tự dựng lại 100%
    bài từ brief.evidence/brief.background — chính cơ chế "bịa cả bài từ
    trang rỗng" đã ghi trong báo cáo content_units. Với content_units mới,
    tới được đây nghĩa là Brief đã xác nhận có chất liệu neo nguồn + Router đã
    bật tuyến article (has_anchored_units) — sections rỗng lúc này là tín hiệu
    Composer THỰC SỰ không viết được gì, CÓ Ý NGHĨA, không phải input rỗng cần
    cứu -> PHẢI NEEDS_HUMAN, KHÔNG tự viết đè (agents/writer.py:
    run_writer_with_retry bắt riêng exception này, KHÁC LLMCallError)."""


def analysis_fields_from_data(data: dict | None, brief: ProductionBrief):
    if data:
        title = str(data.get("title") or brief.hook or brief.title).strip()
        sapo = str(data.get("sapo", "")).strip()
        sections = [
            {"heading": str(s.get("heading", "")).strip(), "content": str(s.get("content", "")).strip()}
            for s in (data.get("sections") or []) if isinstance(s, dict)
        ]
        disclaimer = _verbatim_disclaimer(str(data.get("disclaimer") or _default_disclaimer()).strip())
        sources = [str(u).strip() for u in (data.get("sources") or []) if str(u).strip()]
        if sections:
            return title, sapo, sections, disclaimer, sources
        raise EmptySectionsError(
            "Composer trả sections rỗng (JSON hợp lệ, không có thân bài) — "
            "content_units đã verified + Router đã bật tuyến article, cần "
            "người xem lại, không phải lỗi hạ tầng.")
    # LÙI MƯỢT: CHỈ còn cho data=None/rỗng HOÀN TOÀN (Composer/LLM lỗi hạ tầng
    # thật, KHÔNG parse được JSON gì cả). "data hợp lệ nhưng sections rỗng"
    # KHÔNG còn rơi xuống đây (raise EmptySectionsError ở trên thay vì fall
    # through) — LUÔN giữ tiêu đề gốc trong Bối cảnh (dù có hook/evidence riêng) -> truy vết được.
    # _soft_truncate (Phase 4.11, item 6): cắt về giới hạn nhưng KHÔNG cắt GIỮA
    # 1 từ (lùi về khoảng trắng gần nhất) — trước đây cắt cứng [:N] có thể đứt
    # ngang chữ.
    title = brief.hook or brief.title
    sapo = _soft_truncate(brief.evidence, 200) or brief.title
    boi_canh = f"{brief.title}. {_soft_truncate(brief.evidence, 600)}" if brief.evidence else brief.title
    sections = [{"heading": "Bối cảnh", "content": boi_canh}]
    if brief.background:
        sections.append({"heading": "Bối cảnh mở rộng", "content": _soft_truncate(brief.background, 600)})
    sections.append({"heading": "Hàm ý với nhà đầu tư",
                     "content": f"Mã liên quan: {_tickers_line(brief)}."})
    return title, sapo, sections, _default_disclaimer(), ([brief.url] if brief.url else [])


def render_analysis(title, sapo, sections, disclaimer, sources, brief: ProductionBrief) -> str:
    body = [f"# {title}", "", sapo, ""]
    for s in sections:
        if s["heading"] or s["content"]:
            body += [f"## {s['heading']}", s["content"], ""]
    body.append(f"Mã liên quan: {_tickers_line(brief)}")
    dom = domain_of(brief.url)
    if dom:
        body.append(f"Nguồn: {dom}")            # TẤT ĐỊNH — không phụ thuộc LLM có nhớ ghi
    for u in sources:
        if u and u != brief.url:
            body.append(f"Xem thêm: {u}")
    body += ["", _default_cta(), "", f"_{disclaimer}_"]
    return "\n".join(body)


# PHASE 4.10: hướng dẫn CHUYỂN THỂ VIDEO riêng (docs/voice_examples.md §4) —
# assemble_voice() (agents/voice.py) CHỈ lắp §1/§2/§2b/§2c/§3/§5 (phổ quát +
# theo router), KHÔNG có §4 (đặc thù theo FORMAT: bài dài/social/video/
# infographic) — nối THÊM ở đây, cục bộ cho VideoScriptAgent, KHÔNG sửa
# voice.py (giữ voice.py dùng CHUNG cho article, không lẫn hướng dẫn riêng
# format khác).
_VIDEO_TTS_GUIDANCE = (
    "\n\n---\n\nCHUYỂN THỂ VIDEO (§4 voice_examples.md): hook 5-8 giây đầu = câu "
    "Mở-nghịch-lý đọc lên được; giữ câu NGẮN để TTS mượt và phụ đề không tràn "
    "dòng; mỗi 'beat' một ý; kết mở bằng câu hỏi. Tránh câu lồng nhiều mệnh đề."
)


class VideoScriptAgent(Agent):
    role = "VideoScripter"
    prompt_name = "video"
    system = (
        f"PERSONA: Bạn viết kịch bản video ngắn (~45-60s) cho kênh {_BRAND_NAME} —\n"
        "giọng SẮC, có góc nhìn riêng, KHÔNG đọc lại tin như phát thanh viên. Xâu\n"
        "chuỗi sự kiện với bối cảnh/tiền lệ liên quan (nếu có 'Bối cảnh mở rộng')\n"
        "để người xem CHƯA theo dõi tin trước đó vẫn hiểu toàn cảnh — đây là điểm\n"
        "khác biệt (signature) so với clip tóm tắt tin thông thường.\n"
        "Bố cục: HOOK (0-3s, dùng hook đã có, dẫn bằng NHẬN ĐỊNH chứ không phải\n"
        "tóm tắt) -> 3 beat nội dung (mỗi beat 1 ý + số liệu từ evidence/bối cảnh,\n"
        "PHẢI có góc nhìn/so sánh, không chỉ thuật lại) -> CTA. Mỗi cảnh: lời thoại\n"
        "(voiceover) tự nhiên, chữ trên hình (on-screen text) ngắn, gợi ý hình ảnh.\n"
        f'Kết bằng disclaimer: PHẢI dùng ĐÚNG NGUYÊN VĂN "{_default_disclaimer()}" '
        "(KHÔNG viết lại/diễn giải/thêm bớt chữ nào — đây là câu miễn trừ trách nhiệm "
        "CHUẨN, đã duyệt). KHÔNG bịa số, KHÔNG hô hào mua.\n"
        'Trả về DUY NHẤT JSON: {"schema_version": 1, "title": str, "scenes": '
        '[{"role": "hook"|"body"|"outro", "visual_kind": "title"|"stat"|"statement"|'
        '"list"|"comparison"|"quote"|"ticker"|"news"|"outro", "payload": object, '
        '"narration": str}], "source": str, "disclaimer": str}. scenes[0].role="hook", '
        'scene cuối role="outro" (payload outro gồm CTA, KHÔNG có field "cta" rời cấp top). '
        'payload theo visual_kind: title:{"headline":str,"subheadline":str?}; '
        'stat:{"label":str,"value":str,"note":str?}; statement:{"hero":str,"desc":str}; '
        'list:{"title":str,"items":[{"title":str,"desc":str,"tag":str?}]}; '
        'comparison:{"left":{"label":str,"bullets":[str],"stat":str?},'
        '"right":{"label":str,"bullets":[str],"stat":str?}}; '
        'quote:{"quote":str,"attribution":str?}; '
        'ticker:{"items":[{"symbol":str,"value":str}]}; '
        'news:{"headline":str,"source":str}; '
        'outro:{"brand_name":str,"tagline":str?,"cta":str}.'
        # V1 (2026-07-19) — HỢP ĐỒNG ĐỊNH DẠNG. Phải GIỐNG HỆT khối cùng tên ở
        # `prompts/video.v1.md` (file .md là bản NẠP THẬT khi có; chuỗi này là
        # fallback khi thiếu file — lệch nhau = 2 hành vi khác nhau tuỳ máy).
        # Lý do tồn tại: Opus từng tự viết "năm hai nghìn không trăm hai mươi
        # lăm" vào narration, vi phạm `docs/CONTENT_OUTPUT_SCHEMA.md` (narration
        # giữ nguyên số) — prompt cũ KHÔNG có dòng nào nói về định dạng số.
        "\n\n---\n\n"
        "ĐỊNH DẠNG ĐẦU RA — VĂN VIẾT THƯỜNG (quy tắc CỨNG, đọc kỹ TRƯỚC KHI viết)\n\n"
        "CONTENT.Output là VĂN BẢN ĐỌC BẰNG MẮT (người biên tập duyệt, hệ thống khác\n"
        "đọc lại) — KHÔNG phải bản ghi âm. Viết mọi con số, mã, ký hiệu, tên riêng Y\n"
        "HỆT cách viết trong một bài báo tài chính bình thường.\n\n"
        "TUYỆT ĐỐI KHÔNG viết số thành chữ. TUYỆT ĐỐI KHÔNG phiên âm mã/viết tắt.\n"
        "Lý do: một tầng TỰ ĐỘNG phía sau (KHÔNG phải bạn) chuyển số→chữ và mã→phiên\n"
        "âm để sinh giọng đọc TTS. Bạn làm thay = nội dung bị xử lý HAI LẦN = sai.\n"
        "Việc của bạn là giữ nguyên dạng viết.\n\n"
        "Áp dụng cho CẢ `narration` LẪN mọi field chữ trong `payload`.\n\n"
        "| Loại | VIẾT THẾ NÀY | KHÔNG BAO GIỜ viết |\n"
        "|---|---|---|\n"
        "| Năm | 2025 · thời kỳ 2021-2030 · tầm nhìn 2050 | hai nghìn không trăm hai mươi lăm |\n"
        "| Ngày | 14/7 · ngày 14/7/2026 | ngày mười bốn tháng Bảy |\n"
        "| Quý | Q2/2026 · quý 2/2026 | quý hai năm hai nghìn hai mươi sáu |\n"
        "| Tỷ lệ | 4,98% · giảm 4,98% · 1-1,4%/năm | bốn phẩy chín tám phần trăm |\n"
        "| Tiền | 9,34 tỷ đồng · 66.800 đồng · 1.396 triệu tấn | chín phẩy ba bốn tỷ đồng |\n"
        "| Số đếm | 3 khu công nghiệp · 15 cảng biển loại I | ba khu công nghiệp |\n"
        "| Mã chứng khoán | HVN · FPT · VNM · HPG | hát vê en · ép pê tê |\n"
        "| Viết tắt, chỉ số | VN-Index · GDP · CPI · LNG · Teu | vê en in-đéc · giê đê pê |\n"
        "| Tên riêng | Vietnam Airlines · Hòa Phát · Hòn Khoai | (giữ nguyên, không dịch) |\n\n"
        "GIỮ NGUYÊN VĂN dạng số như trong evidence: dấu phẩy là THẬP PHÂN (4,98), dấu\n"
        "chấm là PHÂN CÁCH NGHÌN (66.800). KHÔNG đổi 66.800 thành 66800 hay 66,800.\n\n"
        "NGOẠI LỆ DUY NHẤT — số dùng như TỪ NGỮ THÔNG THƯỜNG, không mang dữ liệu:\n"
        '"một trong những", "hai mặt của vấn đề", "vài phiên gần đây", "hàng loạt" —\n'
        "viết chữ bình thường. Bảng trên áp cho MỌI số MANG GIÁ TRỊ: lượng, tiền, tỷ\n"
        "lệ, ngày/tháng/quý/năm, thứ hạng, mã số.\n\n"
        "GHI ĐÈ §4.5 CONTENT_WRITER_RULES: luật \"voice-over cấm dùng mã chứng khoán/\n"
        "viết tắt\" KHÔNG áp cho `narration` của schema JSON này. `narration` là VĂN\n"
        "VIẾT, không phải lời đọc — giữ nguyên mã (HVN, VN-Index). Tầng voice phía sau\n"
        "lo phần đọc.\n\n"
        "TỰ KIỂM TRƯỚC KHI TRẢ JSON: quét lại từng `narration` và từng field `payload`\n"
        "— nếu thấy BẤT KỲ con số MANG DỮ LIỆU nào đang viết bằng chữ (không/một/hai/\n"
        "ba/mười/mươi/trăm/nghìn/triệu/tỷ/phẩy), sửa về dạng chữ số rồi mới trả kết quả."
    )

    def run(self, brief: ProductionBrief, decision=None) -> ContentDraft:
        """PHASE 4.10: `decision` = RouterDecision (agents/structure_router,
        đã ĐÓNG BĂNG qua agents/route_once — CÙNG quyết định article của chủ đề
        này dùng, xem scripts/produce_from_sheet.run) hoặc None (fallback
        S1+H3+D, giống AnalysisWriterAgent đường legacy). Voice-lock ĐỘNG +
        §4 chuyển-thể video nối vào system qua _ask(extra_system=...), CÙNG cơ
        chế AnalysisWriterAgent.run() (đường legacy) đã dùng — KHÔNG tự chế
        đường mới."""
        voice = assemble_voice(decision)
        extra = (f"\n\n---\n\nVOICE-LOCK (giọng văn bắt buộc):\n{voice}" if voice else "")
        extra += _VIDEO_TTS_GUIDANCE
        rules = _load_composer_rules("video", settings=self.rules_settings)
        if rules:
            extra += f"\n\n---\n\nCONTENT_WRITER_RULES (bắt buộc, nguồn chuẩn):\n{rules}"
        data = try_json_object(self._ask(build_video_prompt(brief), extra_system=extra))
        title, scenes, disclaimer = video_fields_from_data(data, brief)
        body = render_video(title, scenes, disclaimer, brief)
        return ContentDraft(fmt=ContentFormat.VIDEO_SCRIPT, title=title, body=body,
                            brief_topic=brief.topic)


def build_video_prompt(brief: ProductionBrief) -> str:
    """Prompt (user turn) cho VideoScriptAgent — tách riêng, cùng lý do với
    build_analysis_prompt (dùng cho luồng --draft/--ingest không gọi API)."""
    return (
        f"Tiêu đề: {brief.title}\nGóc/hook: {brief.hook}\n"
        f"Mã: {_tickers_line(brief)}\nDữ kiện (evidence): {brief.evidence[:1000]}"
        + _background_block(brief) + _JSON_ONLY
    )


def _normalize_video_scene(sc: dict, *, role_default: str) -> dict:
    """1 phần tử scenes[] LLM trả -> {role, visual_kind, payload, narration} đã
    validate NHẸ (role/visual_kind lạ -> default an toàn; `payload` không phải
    LLM cũng KHÔNG trust là dict). Validate CHI TIẾT hơn theo từng visual_kind
    (payload đúng field) là việc của scene-builder/guardrail-2 phía
    aigen-pipeline (xem docs/ARCHITECTURE_MODULES.md) — ở đây chỉ đảm bảo
    SHAPE ngoài đúng để JSON hợp lệ, không đụng nội dung LLM viết."""
    role = str(sc.get("role", "")).strip().lower()
    if role not in _VIDEO_SCENE_ROLES:
        role = role_default
    visual_kind = str(sc.get("visual_kind", "")).strip().lower()
    if visual_kind not in _IN_SCOPE_VISUAL_KINDS:
        visual_kind = "statement"
    payload = sc.get("payload") if isinstance(sc.get("payload"), dict) else {}
    narration = str(sc.get("narration", "")).strip()
    return {"role": role, "visual_kind": visual_kind, "payload": payload, "narration": narration}


def _ensure_outro_scene(sc: dict, brief: ProductionBrief) -> dict:
    """Ép cảnh CUỐI đúng bất biến schema (scenes[last].role == visual_kind ==
    "outro", xem docs/CONTENT_OUTPUT_SCHEMA.md) + payload có "brand_name"/"cta"
    (brand-driven, KHÔNG hard-code — _default_cta()/_BRAND_NAME) khi LLM/đường
    lùi mượt bỏ sót. aigen-pipeline scene-builder DỰA VÀO bất biến này, không
    tự lùi mượt được phía đó — PHẢI đảm bảo TẠI ĐÂY."""
    payload = dict(sc.get("payload") or {})
    if not str(payload.get("brand_name") or "").strip():
        payload["brand_name"] = _BRAND_NAME
    if not str(payload.get("cta") or "").strip():
        payload["cta"] = _default_cta()
    narration = str(sc.get("narration") or "").strip() or payload["cta"]
    return {"role": "outro", "visual_kind": "outro", "payload": payload, "narration": narration}


class SpelledNumberContractError(ValueError):
    """CONTENT.Output vi phạm hợp đồng "narration giữ số dạng CHỮ SỐ" — Composer
    viết số bằng chữ (VIỆC 0.3). CỨNG NGAY (luật chống-bịa), KHÔNG self-review
    mềm: bắt ở ĐẦU NGUỒN thay vì để tầng voice/guardrail-2 phía aigen đoán mò."""


def _assert_scenes_narration_use_digits(scenes: list[dict]) -> None:
    """VALIDATOR TẤT ĐỊNH (VIỆC 0.3): quét `narration` mọi cảnh, phát hiện SỐ
    VIẾT BẰNG CHỮ tiếng Việt (vd "hai nghìn không trăm hai mươi lăm", "mười ba
    phẩy tám tỷ", "năm phần trăm") -> raise SpelledNumberContractError nêu RÕ
    cảnh nào + chuỗi nào. KHÔNG dựa vào việc Opus nghe lời prompt. Chỉ áp cho
    narration do LLM sinh (đường Composer), KHÔNG áp cho fallback tất định (đi
    qua evidence nguồn có thể chứa số-chữ tự nhiên — xem video_fields_from_data)."""
    problems: list[str] = []
    for i, sc in enumerate(scenes):
        for phrase in find_spelled_number_phrases(str(sc.get("narration", ""))):
            problems.append(f'scene[{i}].narration: "{phrase}"')
    if problems:
        raise SpelledNumberContractError(
            "narration chứa SỐ VIẾT BẰNG CHỮ (hợp đồng CONTENT.Output: giữ dạng "
            "CHỮ SỐ, tầng voice tất định phía sau lo phần đọc) — "
            + "; ".join(problems))


_VIDEO_SCENE_FLOOR = 3   # KHỚP aigen scene-builder (scenes[] must have 3-12 elements)


class InsufficientScenesError(ValueError):
    """BƯỚC 3 (rules v2.1, 2026-07-22) — Composer (LLM thật, KHÔNG phải fallback
    tất định) chỉ dựng được ÍT HƠN sàn scene renderer đòi (aigen scene-builder:
    3-12, cần hook+ít nhất 1 body+outro để dựng video có nghĩa). Sàn này là
    RÀNG BUỘC RENDERER (video 1-2 cảnh không dựng được), KHÁC BẢN CHẤT với field
    tuỳ chọn thiếu (§8.2) — GIỮ NGUYÊN, không nới.

    NHƯNG tuyệt đối KHÔNG được ép Composer BỊA cảnh cho đủ số (§3.1: "không suy
    đoán để lấp... đủ số cảnh"; §8.3.4: "giảm mật độ hoặc bỏ block thay vì yêu
    cầu Composer bịa thêm") — độn cảnh rỗng/lặp ý sẽ tạo video vô nghĩa, tệ hơn
    hẳn việc KHÔNG có video. Thay vào đó: THROW sớm, TẠI Content Factory (Python)
    — không để nguồn nghèo âm thầm trôi thành CONTENT.Output x lỗi kỹ thuật khó
    hiểu (`scenes[] must have 3-12 elements`) tận phía aigen, có thể nhiều ngày
    sau qua webhook. `produce_from_sheet.run()` bắt lỗi này RIÊNG (không chung
    với SpelledNumberContractError), ghi NEEDS_HUMAN kèm đề xuất chuyển loại
    nội dung (infographic/article) — nguồn nghèo scene KHÔNG có nghĩa nguồn
    nghèo SỐ LIỆU, infographic/article vẫn có thể sản xuất được bình thường."""


def video_fields_from_data(data: dict | None, brief: ProductionBrief):
    """JSON LLM (hoặc None/rỗng) -> (title, scenes, disclaimer) khớp
    ContentOutputVideo (docs/CONTENT_OUTPUT_SCHEMA.md) — `schema_version`/
    `source`/`content_units` KHÔNG lấy từ đây (tất định, gắn ở render_video()), cùng
    nếp InfographicSpecAgent (source luôn domain_of(brief.url), KHÔNG tin LLM
    tự bịa domain). `cta` (dạng cũ) KHÔNG còn ở đây — nằm trong
    payload của scene cuối (visual_kind="outro"), xem _ensure_outro_scene."""
    if data:
        title = str(data.get("title") or brief.hook or brief.title).strip()
        raw_scenes = [sc for sc in (data.get("scenes") or []) if isinstance(sc, dict)]
        n = len(raw_scenes)
        scenes = [
            _normalize_video_scene(sc, role_default=("hook" if i == 0 else "outro" if i == n - 1 else "body"))
            for i, sc in enumerate(raw_scenes)
        ]
        disclaimer = str(data.get("disclaimer") or _default_disclaimer()).strip()
        if not scenes:
            # Lead 02/08 (Nhóm B, cùng sửa với sections=[] article): Composer
            # trả JSON HỢP LỆ nhưng scenes RỖNG (tường minh "scenes": [] HOẶC
            # thiếu hẳn key) -- KHÁC data=None/lỗi hạ tầng (case đó vẫn LÙI
            # MƯỢT bên dưới, xem test_production_agent_graceful_empty_llm).
            # Tới được đây, content_units đã verified + Router đã bật tuyến
            # video -- scenes rỗng là Composer THỰC SỰ không viết được gì, tín
            # hiệu CÓ Ý NGHĨA, KHÔNG còn coi là "cần cứu" để tự dựng 4 cảnh mặc
            # định (chính cơ chế "bịa cả video từ JSON rỗng" đã ghi trong báo
            # cáo content_units) -- ném qua LƯỚI InsufficientScenesError CÓ SẴN
            # (produce_from_sheet.run() đã bắt riêng -> NEEDS_HUMAN + Notes).
            raise InsufficientScenesError(
                "Composer trả scenes rỗng (0 cảnh, cần tối thiểu "
                f"{_VIDEO_SCENE_FLOOR} để video có hook+thân+outro) — KHÔNG tự "
                "dựng 4 cảnh mặc định thay Composer. content_units đã verified + "
                "Router đã bật tuyến video, cần người xem lại, không phải lỗi "
                "hạ tầng.")
        scenes[0]["role"] = "hook"
        scenes[-1] = _ensure_outro_scene(scenes[-1], brief)
        # VIỆC 0.3 — CONTRACT CHECK tất định trên OUTPUT COMPOSER (chỉ đường
        # LLM này, KHÔNG áp fallback bên dưới): số bằng chữ -> THROW ngay.
        _assert_scenes_narration_use_digits(scenes)
        # BƯỚC 3 (rules v2.1) — sàn scene RENDERER, xem InsufficientScenesError.
        # Đặt SAU digit-check có chủ đích: lỗi ĐỊNH DẠNG (voice_text hỏng) là
        # vấn đề TOÀN VẸN dữ liệu, ưu tiên lộ ra trước lỗi SỐ LƯỢNG (khả thi
        # video) — cũng giữ nguyên hành vi test_video_narration_contract_
        # rejects_spelled_out_numbers (2 scene, cố ý test riêng digit-check).
        if len(scenes) < _VIDEO_SCENE_FLOOR:
            raise InsufficientScenesError(
                f"Nguồn chỉ đủ dựng {len(scenes)} cảnh (cần tối thiểu "
                f"{_VIDEO_SCENE_FLOOR} để video có hook+thân+outro) — KHÔNG bịa "
                f"cảnh đệm cho đủ số. Đề xuất chuyển loại nội dung sang "
                f"infographic/article cho chủ đề này (nguồn nghèo SCENE video, "
                f"KHÔNG có nghĩa nghèo SỐ LIỆU — 2 loại kia dùng chung content_units[]).")
        return title, scenes, disclaimer
    # LÙI MƯỢT: CHỈ còn cho data=None/rỗng HOÀN TOÀN (Composer/LLM lỗi hạ tầng
    # thật, KHÔNG parse được JSON gì cả — xem test_production_agent_graceful_
    # empty_llm). "data hợp lệ nhưng scenes rỗng" KHÔNG còn rơi xuống đây từ
    # Lead 02/08 (đã raise InsufficientScenesError ở nhánh `if data:` trên).
    # Kịch bản tất định 4 cảnh (>= 1 "hook" + 1 "outro") từ dữ kiện đã duyệt
    # (KHÔNG cần Opus) — GIỮ nguyên nội dung/thứ tự ý tưởng đường cũ (hook ->
    # tiêu đề -> bối cảnh (nếu có) -> mã liên quan -> CTA), chỉ đổi VỎ ĐỰNG
    # sang scene có kiểu.
    title = brief.hook or brief.title
    scenes = [
        {"role": "hook", "visual_kind": "statement",
         "payload": {"hero": brief.hook or brief.title, "desc": brief.title},
         "narration": brief.hook or brief.title},
        {"role": "body", "visual_kind": "statement",
         "payload": {"hero": brief.title, "desc": _soft_truncate(brief.evidence, 200)},
         "narration": brief.title},
    ]
    if brief.background:
        scenes.append({"role": "body", "visual_kind": "statement",
                       "payload": {"hero": "Bối cảnh mở rộng", "desc": _soft_truncate(brief.background, 200)},
                       "narration": _soft_truncate(brief.background, 200)})
    scenes.append({"role": "body", "visual_kind": "stat",
                   "payload": {"label": "Mã liên quan", "value": _tickers_line(brief)},
                   "narration": f"Hàm ý cho nhà đầu tư với {_tickers_line(brief)}."})
    scenes.append(_ensure_outro_scene({}, brief))
    return title, scenes, _default_disclaimer()


def render_video(title, scenes, disclaimer, brief: ProductionBrief) -> str:
    """Serialize ContentOutputVideo (schema_version=1, xem docs/CONTENT_OUTPUT_
    SCHEMA.md) -> JSON string = `ContentDraft.body` mới (thay hẳn văn xuôi có
    đánh dấu cũ `[t] voiceover / On-screen: / Hình ảnh: / [CTA] / Nguồn:`).
    `source` TẤT ĐỊNH từ domain_of(brief.url) (giống dòng "Nguồn:" cũ, KHÔNG
    tin LLM tự bịa domain — cùng nếp InfographicSpecAgent.infographic_spec_
    from_data). Khoá `"facts"` (JSON) pass-through NGUYÊN VĂN brief.
    content_units (đã verify sẵn ở Brief/agents.brief.py, KHÔNG LLM sinh lại)
    — nguồn cho guardrail-2 phía aigen-pipeline. TÊN KHOÁ JSON giữ NGUYÊN
    "facts" (KHÔNG đổi thành "content_units") — hợp đồng chéo repo với aigen/
    production-spec/guardrail/verify-spec.ts, đổi 1 bên là gãy luật đồng bộ 2
    repo (xem docs/ARCHITECTURE_MODULES.md, comment tại điểm dựng dict dưới)."""
    output = {
        "schema_version": _CONTENT_OUTPUT_SCHEMA_VERSION,
        "title": title,
        "scenes": scenes,
        "source": domain_of(brief.url),
        "disclaimer": disclaimer,
        "facts": [asdict(f) for f in brief.content_units],   # Tên khoá trên dây giữ "facts" cho tương thích
        # aigen/production-spec/guardrail/verify-spec.ts. Đổi cùng lượt 2 repo khi
        # agent-B có quota. Nội bộ dùng content_units.
    }
    return json.dumps(output, ensure_ascii=False, indent=2)


# PHASE 4.10: kind ưu tiên "đáng lên hình nhất" khi chọn stat emphasis=true —
# ưu tiên số có SỨC NẶNG (tiền/%/tăng-giảm) hơn đếm/xếp hạng/ngày tháng, khớp
# trực giác "con số đập vào mắt trước" của 1 tấm infographic. Vẫn dùng ở Phase
# 4.11 để chọn 1 fact lên `hero` trong đường LÙI MƯỢT (composer LLM lỗi/rỗng).
_INFOGRAPHIC_EMPHASIS_KINDS = ("percent", "growth", "money")


def _pick_emphasis_index(content_units: list[ContentUnit]) -> int:
    """ContentUnit ĐẦU TIÊN thuộc nhóm kind đáng lên hình nhất (percent/growth/money)
    -> emphasis=true; không có fact nào thuộc nhóm đó -> mặc định fact đầu
    tiên (giữ hành vi cũ i==0). Hàm THUẦN — test được không cần Brief thật."""
    for i, f in enumerate(content_units):
        if f.kind in _INFOGRAPHIC_EMPHASIS_KINDS:
            return i
    return 0


# PHASE 4.11 — INFOGRAPHIC COMPOSER: Phase 4.10 đọc content_units[] nhưng DUMP thẳng
# (value = nguyên câu evidence, label dài, takeaway cắt cụt 160 ký tự, subhead
# lặp headline khi hook rỗng). Đây là việc CÔ ĐỌNG — cần LLM (Loại B/haiku,
# KHÔNG còn $0 thuần T0 như trước), không phải chuỗi Python. Input = content_units[] +
# RouterDecision (khung bài, để composer biết nên nhấn số nào); output = spec
# JSON 8 TRƯỜNG ổn định (title/subtitle/hero/market/highlights/related/
# priority/source) + 1 khối render_hint TÁCH RIÊNG (gợi ý style mềm, KHÔNG
# thuộc "8 trường data"). disclaimer KHÔNG còn nằm trong spec (thuộc RENDER,
# xem CLAUDE.md nguyên tắc tách data/trình bày) — render/infographic.py (Phase
# 5, chưa làm) sẽ tự gắn khi vẽ.
_INFOGRAPHIC_COMPOSER_SYSTEM = (
    "Bạn là Infographic Composer — nén content_units[] (đã trích sẵn, có nhãn NGHĨA + "
    "số nguyên văn) + khung bài (StructureRouter) thành spec JSON 8 TRƯỜNG cho "
    "1 tấm infographic. Đây là việc CÔ ĐỌNG (viết lại NGẮN hơn), KHÔNG phải "
    "liệt kê nguyên văn content_units.\n"
    "YÊU CẦU CÔ ĐỌNG:\n"
    "- value NÉN: bỏ chủ ngữ/động từ thừa trong câu, nhưng GIỮ NGUYÊN VĂN cả "
    "SỐ và ĐƠN VỊ như trong fact gốc (BẮT BUỘC, để còn đối chiếu được với dữ "
    "kiện gốc) — CHỈ được cắt bớt CHỮ THỪA (chủ ngữ/động từ), TUYỆT ĐỐI KHÔNG "
    "tự quy đổi bậc số/đơn vị (vd '357.000 tỷ đồng' PHẢI giữ nguyên '357.000 "
    "tỷ đồng', KHÔNG tự viết lại thành '357 tỷ' hay '357 nghìn tỷ' — mọi phép "
    "quy đổi bậc số đều có rủi ro rớt số, xem KỶ LUẬT SỐ bên dưới). Vd an toàn "
    "(chỉ cắt chữ, không đụng số): 'GDP 6 tháng đầu năm tăng 8,18%' -> "
    "'GDP +8,18%'.\n"
    "- hero: 2-3 mã/số NỔI NHẤT (đáng lên hình đầu tiên, ưu tiên %/tăng-giảm/tiền).\n"
    "- market: các số còn lại (cũng phải NÉN như hero).\n"
    "- highlights: 1-3 câu góc-nhìn NGẮN (KHÔNG phải 1 đoạn takeaway dài, "
    "KHÔNG cắt cụt giữa câu — mỗi câu phải TRỌN VẸN).\n"
    "- related: TÊN thực thể thật liên quan trực tiếp (địa danh/dự án/công ty/"
    "mã CK/chính sách) — LẤY TỪ content_units[] có [entity]/[entity_list] (xem nhãn "
    "[shape:salience] đầu mỗi dòng fact), GHÉP tên NGUYÊN VĂN. TUYỆT ĐỐI KHÔNG "
    "tự bịa thêm tên nào KHÔNG có trong content_units[] — dòng nào trong 'related' "
    "không khớp content_units[] SẼ BỊ GUARDRAIL LẦN 2 CHẶN (xem media_factory/spec.py). "
    "CHỈ LẤY entity/entity_list có salience=\"subject\" — TUYỆT ĐỐI KHÔNG lấy "
    "salience=\"context\" (Content Factory Phase 2b — lỗi THẬT đã gặp: related "
    "bị lấp bởi tên hội thảo/hiệp hội/viện nghiên cứu thay vì tên cảng/dự án "
    "thật). content_units[] không có entity/entity_list salience=subject nào -> để "
    "related rỗng [], KHÔNG lùi về mã CK/tên context khi không chắc chắn.\n"
    "- RỖNG TƯỜNG MINH (Lead 02/08): nếu THẬT SỰ không có subtitle/related phù "
    "hợp, hãy trả rỗng tường minh (subtitle: \"\", related: []) — hệ thống GIỮ "
    "NGUYÊN rỗng, KHÔNG tự điền lại. TUYỆT ĐỐI KHÔNG bịa 1 câu/tên nào chỉ để "
    "'cho đủ trường'.\n"
    "- priority: {\"primary\": [...nhãn/tên quan trọng nhất...], \"secondary\": "
    "[...], \"minor\": [...]} — \"primary\" CHỈ được chứa nhãn (label) đã dùng "
    "ở hero/market VÀ/HOẶC tên thực thể salience=\"subject\" đã đưa vào "
    "related (KHÔNG bao giờ salience=\"context\") — \"secondary\"/\"minor\" có "
    "thể chứa nhãn context (hội thảo/hiệp hội...) nếu cần, dựa trên mức độ "
    "phục vụ luận điểm chính (khung bài đã cho). MỌI mục trong \"primary\" LẤY "
    "TỪ hero/market PHẢI LẶP LẠI NGUYÊN VĂN chuỗi label đã dùng ở đó — TUYỆT "
    "ĐỐI KHÔNG viết tắt/diễn giải lại (vd đã dùng label \"Khu công nghiệp\" ở "
    "market thì priority.primary PHẢI ghi lại đúng \"Khu công nghiệp\", KHÔNG "
    "được rút gọn thành \"KCN\") — guardrail lần 2 so khớp CHUỖI, viết tắt sẽ "
    "bị chặn NHẦM dù không phải bịa.\n"
    "- title KHÁC subtitle: title = tiêu đề GỌN; subtitle = 1 CÂU GÓC NHÌN "
    "(KHÔNG được lặp lại y hệt title).\n"
    "- render_hint (TÁCH RIÊNG khỏi 8 trường data): "
    "{\"theme\": \"dark|light\", \"palette\": tên bảng màu ngắn, \"ratio\": "
    "\"9:16|4:5|1:1\"}.\n"
    "  theme/palette là gợi ý MỀM. `ratio` thì KHÔNG — nó quyết định ảnh THẬT "
    "được sinh ra, và hệ thống CHỈ sinh ĐÚNG 1 ảnh theo tỷ lệ bạn chọn (không "
    "sinh cả 3 để đỡ lãng phí). Chọn theo LƯỢNG THÔNG TIN bạn vừa viết ra:\n"
    "    · \"9:16\" — DÀI, nhiều mục: tổng (hero+market) từ 7 mục trở lên, "
    "hoặc highlights dài. Khung dọc Story/Reels/TikTok.\n"
    "    · \"4:5\"  — TRUNG BÌNH: tổng 4-6 mục. Khung feed Facebook/Instagram.\n"
    "    · \"1:1\"  — NGẮN, 1-3 con số nổi bật, ít chữ. Khung vuông.\n"
    "  Đếm số mục THẬT trong hero/market/highlights rồi mới chọn — nhồi 10 mục "
    "vào khung 1:1 sẽ ra ảnh chữ nhỏ không đọc nổi.\n"
    "- TUYỆT ĐỐI KHÔNG bịa số ngoài content_units[] được cung cấp — MỌI số trong spec "
    "PHẢI xuất phát từ 1 fact đã cho.\n"
    + _NUMBER_DISCIPLINE +
    '\nTrả về DUY NHẤT JSON: {"title": str, "subtitle": str, '
    '"hero": [{"label": str, "value": str}], "market": [{"label": str, "value": str}], '
    '"highlights": [str], "related": [str], '
    '"priority": {"primary": [str], "secondary": [str], "minor": [str]}, '
    '"source": str, "render_hint": {"theme": str, "palette": str, "ratio": str}}. '
    "KHÔNG markdown, KHÔNG lời dẫn."
)

# Tập ĐÓNG tỷ lệ ảnh infographic — phải KHỚP đúng những gì renderer dựng được
# (render/ai_full.py + scripts/render_production_assets.py). Sửa ở ĐÂY thì sửa
# LUÔN cả 2 chỗ đó, có test khoá (test_valid_ratios_match_renderer_support).
VALID_RATIOS: tuple[str, ...] = ("9:16", "4:5", "1:1")
_DEFAULT_RENDER_HINT = {"theme": "dark", "palette": "navy-gold", "ratio": "4:5"}


def _content_unit_display_value(f: ContentUnit) -> str:
    """Số/tên hiển thị của 1 fact cho Composer đọc — Content Factory Phase 2:
    khác nhau THEO SHAPE (models.FACT_SHAPES), KHÔNG còn chỉ scalar. `raw`
    (nguyên văn evidence) ưu tiên cho scalar; range/delta ghép 2 đầu; entity_
    list liệt kê ĐỦ mọi thành viên (Composer PHẢI thấy hết để điền 'related'
    — thiếu 1 tên là mất nguyên liệu, xem _INFOGRAPHIC_COMPOSER_SYSTEM); entity
    là 1 tên đơn."""
    if f.shape == "range":
        return f"{f.value_low} - {f.value_high}{f.unit or ''}"
    if f.shape == "delta":
        return f"{f.from_value} → {f.to_value}"
    if f.shape == "entity_list":
        return ", ".join(f.entities)
    if f.shape == "entity":
        return f.value
    return f.raw or f"{f.value}{f.unit or ''}"   # shape == "scalar" (mặc định, dữ liệu cũ)


def _content_unit_tag(f: ContentUnit) -> str:
    """Nhãn đầu dòng fact cho Composer đọc — [shape] (scalar/range/delta), hoặc
    [shape:salience] cho entity/entity_list (Content Factory Phase 2b — Composer
    PHẢI thấy salience ngay trên dòng để lọc related/priority.primary, không
    phải suy đoán)."""
    if f.shape in ("entity", "entity_list"):
        return f"{f.shape}:{f.salience or 'context'}"   # salience rỗng (dữ liệu cũ) -> hiển thị NHƯ context, AN TOÀN hơn
    return f.shape


def build_infographic_composer_prompt(brief: ProductionBrief, decision=None) -> str:
    """Prompt (user turn) cho Infographic Composer — content_units[] (KHÔNG phải
    evidence thô) là NGUYÊN LIỆU chính, kèm khung bài (RouterDecision đã đóng
    băng, agents/route_once.py) để composer biết nhấn số nào theo đúng luận
    điểm article/video của CÙNG chủ đề đang dùng (nhất quán multi-content).
    Content Factory Phase 2: mỗi dòng gắn nhãn [shape] (KHÔNG phải [kind] như
    cũ) — Composer cần biết HÌNH DẠNG fact để biết cách dùng (vd entity_list
    -> nguồn cho 'related', KHÔNG phải 1 con số cho hero/market). Phase 2b:
    entity/entity_list thêm ":salience" ([entity_list:subject] vs
    [entity_list:context]) — Composer lọc related/priority.primary CHỈ theo
    subject, xem _INFOGRAPHIC_COMPOSER_SYSTEM."""
    facts_lines = "\n".join(
        f"- [{_content_unit_tag(f)}] {f.label}: {_content_unit_display_value(f)}" for f in brief.content_units
    )
    structure = str(getattr(decision, "structure", None) or "S1").strip().upper()
    parts = [
        f"Tiêu đề: {brief.title}", f"Hook: {brief.hook}", f"Mã: {_tickers_line(brief)}",
        f"Khung bài đã chọn (StructureRouter): {structure}",
        f"Facts đã trích (agents/brief.py):\n{facts_lines}",
        _JSON_ONLY,
    ]
    return "\n".join(parts)


def _parse_stat_list(raw) -> list[dict]:
    """[{label,value}] từ JSON composer — bỏ item thiếu label/value (an toàn,
    không tin mù LLM trả đủ trường)."""
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()
        value = str(item.get("value", "")).strip()
        if label and value:
            out.append({"label": label, "value": value})
    return out


def _parse_priority(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {tier: [str(x).strip() for x in (raw.get(tier) or []) if str(x).strip()]
            for tier in ("primary", "secondary", "minor")}


def _parse_render_hint(raw) -> dict:
    """Chuẩn hoá render_hint. `ratio` đi qua TẬP ĐÓNG (VALID_RATIOS) — khác
    theme/palette vốn là gợi ý style tự do.

    2026-07-28: `ratio` giờ QUYẾT ĐỊNH ảnh nào được sinh (chỉ 1 ảnh thay vì cả
    3 — xem scripts/render_production_assets.py), nên giá trị lạ không còn vô
    hại như thời nó chỉ là gợi ý style. LỖI ĐÃ CÓ THẬT trong prompt: mời
    Composer chọn "16:9" trong khi renderer chỉ có 9:16/4:5/1:1 — Composer trả
    đúng như được mời thì renderer lại không có tỷ lệ đó. Giá trị ngoài tập ->
    LÙI VỀ mặc định (không raise): đây là lớp trình bày, hỏng tỷ lệ không đáng
    đánh rơi cả nội dung đã sinh."""
    raw = raw if isinstance(raw, dict) else {}
    out = {k: str(raw.get(k) or v).strip() for k, v in _DEFAULT_RENDER_HINT.items()}
    if out["ratio"] not in VALID_RATIOS:
        out["ratio"] = _DEFAULT_RENDER_HINT["ratio"]
    return out


def _stat_from_content_unit(f: ContentUnit) -> dict:
    return {"label": f.label, "value": _content_unit_display_value(f)}


def _entity_names_from_content_units(content_units: list[ContentUnit]) -> list[str]:
    """Content Factory Phase 2 (+ 2b — salience) — mọi TÊN thật CHỦ THỂ
    (salience="subject", KHÔNG phải "context"/phông nền — hội thảo/hiệp hội/
    người phát biểu; xem models.ContentUnit.salience) đã verify sẵn ở Brief (agents/
    brief.py, KHÔNG bịa) — nguồn DUY NHẤT cho 'related' ở đường lùi mượt (KHÔNG
    LLM, xem _empty_infographic_spec/_fallback_infographic_spec). CỐ Ý loại
    salience="" (dữ liệu CŨ trước Phase 2b, chưa phân loại) — KHÔNG đủ chắc
    chắn để lên hình 'related' cho luồng MỚI, dù verify_spec vẫn coi salience
    rỗng là khớp hợp lệ khi ĐỐI CHIẾU (tương thích ngược đọc, không tương
    thích ngược CHỌN). Giữ thứ tự xuất hiện, khử trùng."""
    seen: set[str] = set()
    out: list[str] = []
    for f in content_units:
        if f.salience != "subject":
            continue
        names = f.entities if f.shape == "entity_list" else ([f.value] if f.shape == "entity" and f.value else [])
        for n in names:
            if n and n not in seen:
                seen.add(n)
                out.append(n)
    return out


def _empty_infographic_spec(brief: ProductionBrief) -> dict:
    """content_units[] RỖNG (Brief lỗi/timeout) -> spec RỖNG CÓ CHỦ Ý — KHÔNG bịa (giữ
    nguyên triết lý Phase 4.10; caller (scripts/produce_from_sheet.run) đánh
    dấu NEEDS_HUMAN cho dòng này). content_units[] rỗng -> _entity_names_from_content_units
    cũng rỗng -> related lùi về brief.tickers (mã CK từ CONTEXT, KHÔNG phải
    bịa — vẫn là dữ liệu THẬT, chỉ là nguồn khác)."""
    return {
        "title": brief.hook or brief.title, "subtitle": "",
        "hero": [], "market": [], "highlights": [],
        "related": _entity_names_from_content_units(brief.content_units) or list(brief.tickers),
        "priority": {"primary": [], "secondary": [], "minor": []},
        "source": domain_of(brief.url), "render_hint": dict(_DEFAULT_RENDER_HINT),
    }


def _fallback_infographic_spec(brief: ProductionBrief) -> dict:
    """LÙI MƯỢT: composer LLM lỗi/JSON rỗng -> dựng spec TẤT ĐỊNH trực tiếp từ
    content_units[] (KHÔNG nén được chữ vì không có LLM ở bước lùi mượt — value dài
    hơn bản composer thật, nhưng vẫn ĐÚNG số/KHÔNG bịa, và vẫn đủ 8 trường +
    title != subtitle). ContentUnit ưu tiên (_pick_emphasis_index) lên `hero`; còn
    lại (tối đa 5 fact) vào `market`. `related` (Content Factory Phase 2) lấy
    từ MỌI fact entity/entity_list (không chỉ 5 fact đầu — related không giới
    hạn như hero/market), lùi về brief.tickers nếu Brief không trích được tên nào."""
    content_units = brief.content_units[:5]
    idx = _pick_emphasis_index(content_units)
    hero = [_stat_from_content_unit(f) for i, f in enumerate(content_units) if i == idx]
    market = [_stat_from_content_unit(f) for i, f in enumerate(content_units) if i != idx]
    title = brief.hook or brief.title
    subtitle = content_units[idx].label if content_units and content_units[idx].label != title else ""
    related = _entity_names_from_content_units(brief.content_units) or list(brief.tickers)
    return {
        "title": title, "subtitle": subtitle, "hero": hero, "market": market,
        "highlights": [f"{f.label}: {_content_unit_display_value(f)}" for f in content_units[:2]],
        "related": related,
        "priority": {"primary": [s["label"] for s in hero],
                     "secondary": [s["label"] for s in market], "minor": []},
        "source": domain_of(brief.url), "render_hint": dict(_DEFAULT_RENDER_HINT),
    }


def infographic_spec_from_data(data: dict | None, brief: ProductionBrief) -> dict:
    """JSON composer -> spec 8 trường + render_hint đã validate. Hàm THUẦN —
    test được không cần LLM thật, dùng chung bởi InfographicSpecAgent.run()."""
    if data:
        hero = _parse_stat_list(data.get("hero"))
        market = _parse_stat_list(data.get("market"))
        if hero or market:
            title = str(data.get("title") or brief.hook or brief.title).strip()
            subtitle_raw = data.get("subtitle")
            if subtitle_raw is None:
                # Key VẮNG MẶT/None -> Composer "quên điền", CODE tự chọn subtitle
                # khác title (không tin mù LLM, cùng triết lý driver_count).
                subtitle = brief.title if brief.title != title else ""
            else:
                subtitle = str(subtitle_raw).strip()
                if subtitle == title:
                    # RÀNG BUỘC CỨNG: title != subtitle luôn — composer lỡ LẶP
                    # (không phải để rỗng) thì CODE tự sửa.
                    subtitle = brief.title if brief.title != title else ""
                # subtitle == "" (Composer TRẢ RỖNG có chủ đích, khác title) ->
                # GIỮ NGUYÊN, KHÔNG tự điền brief.title (Lead 02/08 — "code đang
                # BỊA dữ liệu vào ảnh" khi coi "" giống "quên điền").
            highlights = [str(h).strip() for h in (data.get("highlights") or []) if str(h).strip()]
            related_raw = data.get("related")
            if related_raw is None:
                related = [str(t).strip() for t in
                          (_entity_names_from_content_units(brief.content_units) or brief.tickers)
                          if str(t).strip()]
            else:
                # Key có mặt (kể cả [] có chủ đích) -> TÔN TRỌNG nguyên văn,
                # KHÔNG lùi về nguồn khác (Lead 02/08, cùng lý do subtitle).
                related = [str(t).strip() for t in related_raw if str(t).strip()]
            return {
                "title": title, "subtitle": subtitle, "hero": hero, "market": market,
                "highlights": highlights, "related": related,
                "priority": _parse_priority(data.get("priority")),
                "source": domain_of(brief.url),
                "render_hint": _parse_render_hint(data.get("render_hint")),
            }
    return _fallback_infographic_spec(brief)


class InfographicSpecAgent(Agent):
    """PHASE 4.11: KHÔNG còn TẤT ĐỊNH/$0 thuần — giờ là 1 bước LLM Loại B/rẻ
    (caller gán `self.model`/`self.llm` = alias 'composer'/haiku, xem
    scripts/produce_from_sheet.run) để CÔ ĐỌNG content_units[]+RouterDecision thành
    spec 8 trường (xem _INFOGRAPHIC_COMPOSER_SYSTEM). Đổi từ Phase 4.10 (đọc
    thẳng content_units[] nhưng DUMP nguyên văn — value cả câu, takeaway cắt cụt 160
    ký tự, subhead lặp headline khi hook rỗng).

    AN TOÀN SỐ: composer chỉ được CÔ ĐỌNG CHỮ, KHÔNG được đổi giá trị — guard
    chống bịa vẫn là content_units[]-verify (agents/brief.py) TRƯỚC + guardrail-số-
    canonical (Mục C, agents/production.apply_guardrails/unsupported_numbers)
    CHẠY LẠI SAU trên `draft.body` (spec JSON đầy đủ) như đã wire từ Phase 4.9
    — KHÔNG cần code MỚI ở đây, chỉ cần composer dùng ĐÚNG từ đơn vị mà
    agents/_numeric.parse_magnitude_token nhận diện được (%, tỷ, tỷ đồng,
    nghìn tỷ, triệu, usd, đồng) để số nén vẫn map được về canonical.

    content_units[] RỖNG -> _empty_infographic_spec (KHÔNG gọi LLM, KHÔNG bịa)."""
    role = "InfographicComposer"
    prompt_name = "infographic"
    system = _INFOGRAPHIC_COMPOSER_SYSTEM
    uses_llm = True

    def run(self, brief: ProductionBrief, decision=None) -> ContentDraft:
        if not brief.content_units:
            spec = _empty_infographic_spec(brief)
        else:
            rules = _load_composer_rules("infographic", settings=self.rules_settings)
            extra = (f"\n\n---\n\nCONTENT_WRITER_RULES (bắt buộc, nguồn chuẩn):\n{rules}"
                    if rules else "")
            data = try_json_object(self._ask(build_infographic_composer_prompt(brief, decision),
                                             extra_system=extra))
            spec = infographic_spec_from_data(data, brief)
        return ContentDraft(fmt=ContentFormat.INFOGRAPHIC,
                            title=f"[Infographic] {brief.title}",
                            body=json.dumps(spec, ensure_ascii=False, indent=2),
                            brief_topic=brief.topic)


_PRODUCTION_AGENT_CLASSES = (AnalysisWriterAgent, VideoScriptAgent, InfographicSpecAgent)


def all_production_agents(llm: LLMClient | None = None,
                          prompt_overrides: dict[str, str] | None = None) -> list[Agent]:
    """3 agent sản xuất: 2 dùng LLM (Sonnet) + 1 tất định. `prompt_overrides` =
    {prompt_name: system_text} đã resolve từ tab PROMPTS (agents.prompts.resolve_prompts)
    — override đúng agent theo `agent.prompt_name`, không đổi ai không có bản mới."""
    agents = [cls(llm) for cls in _PRODUCTION_AGENT_CLASSES]
    if prompt_overrides:
        for a in agents:
            text = prompt_overrides.get(getattr(a, "prompt_name", ""))
            if text:
                a.system = text
    return agents
