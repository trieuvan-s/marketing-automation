"""Production Factory — render asset (PNG, AI ai_full) cho dòng CONTENT
infographic ĐÃ qua Gate 2 (Approve(gate 2)=APPROVE), ghi đường dẫn vào cột
AssetPath (neo TopicKey — kỷ luật Lớp 5) rồi mở Gate 3 (duyệt asset).

ĐẢO HƯỚNG (2026-07-21, QUYẾT ĐỊNH LEAD — xem docs/VPS_MIGRATION_BACKLOG.md):
renderer đổi từ SVG tất định (`render_infographic_svg`) sang AI-only
(`render/ai_full.py`, model gpt-image-2). GUARDRAIL-2 NHÁNH ẢNH (verify_spec
trên ProductionBlock/block_kind) ĐÃ XOÁ CÙNG LƯỢT theo đúng quyết định Lead —
KHÔNG còn bước đối chiếu output_data với facts[] NGAY TRƯỚC RENDER cho
infographic (khác trục video, vẫn giữ nguyên qua ProductionScene). Rủi ro
ĐÃ BIẾT: nếu người sửa tay output_data ở Gate 2 gõ nhầm số, AI (ai_full) sẽ vẽ
NGUYÊN VĂN số sai đó vào ảnh mà không có gì tự động bắt trước khi ghi
AssetPath — Gate 2 (duyệt người) + Gate 3 (duyệt asset) là 2 lớp chặn còn lại.

IDEMPOTENT: dòng đã có AssetPath (đã render) -> BỎ QUA HOÀN TOÀN, không render
lại/không ghi đè — kể cả nếu Gate3 CHƯA duyệt (chỉ người mới được đổi asset đã
có, bằng cách tự xoá AssetPath rồi chạy lại — KHÔNG có cờ --force ở đây, cố ý,
tránh xoá nhầm asset đã hoặc đang chờ duyệt Gate 3). ai_full tự cache theo
hash(spec+theme+ratio) — dòng render lại (sau khi tự xoá AssetPath) KHÔNG gọi
API lần nữa nếu input không đổi.

Chạy:
    python scripts/render_production_assets.py               # render tối đa 20 dòng
    python scripts/render_production_assets.py --limit 5
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))
# SỬA LỖI THẬT (2026-08-04, xem run_scheduler.py cùng lý do) -- ép cwd =
# REPO_ROOT NGAY ĐẦU để chạy đúng bất kể ai/gì khởi động tiến trình.
os.chdir(REPO_ROOT)

from twmkt._encoding import ensure_utf8_stdio  # noqa: E402

ensure_utf8_stdio()

from twmkt.asset_server import DEFAULT_PORT, asset_url  # noqa: E402
from twmkt.config import data_path, load_settings  # noqa: E402
from twmkt.agents.production import VALID_RATIOS  # noqa: E402
from twmkt.publishers.drive_store import GOOGLE_DOC_MIME, build_drive_store  # noqa: E402
from twmkt.render.ai_full import render_ai_full  # noqa: E402
from twmkt.sheets_board import SheetsBoard  # noqa: E402

from store import document_store as ds  # noqa: E402
from store import pipeline_store as ps  # noqa: E402


def _today() -> str:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date().isoformat()
    except Exception:
        return datetime.now(timezone.utc).date().isoformat()


def _slug(text: str, n: int = 40) -> str:
    keep = "".join(c if c.isalnum() else "-" for c in (text or "").lower())
    while "--" in keep:
        keep = keep.replace("--", "-")
    return keep.strip("-")[:n] or "san-pham"


def asset_hyperlink_formula(url: str) -> str:
    """Sheet UI cleanup Phase 6b/6c — bọc `url` (HTTP, xem twmkt.asset_server.
    asset_url) bằng HYPERLINK() để cột AssetPath (đã HIỂN THỊ từ Phase 6) là
    link NGƯỜI BẤM ĐƯỢC thay vì text đường dẫn thô.

    LỊCH SỬ (Phase 6b -> 6c): bản đầu dùng `file://` (Path.as_uri()) — test
    THẬT trên Sheet sống cho thấy KHÔNG hoạt động (Google Sheets chạy qua
    HTTPS, trình duyệt chặn điều hướng HTTPS -> file:// cục bộ). Đổi sang
    `http://127.0.0.1:PORT/...` (twmkt.asset_server, cần `scripts/
    serve_assets.py` chạy nền) — scheme http là web-an-toàn nên hoạt động
    bình thường trong Sheets.

    GIỚI HẠN ĐÃ BIẾT (chấp nhận, xem docs/HANDOFF.md): link CHỈ mở được trên
    MÁY đã render asset VÀ đang chạy `scripts/serve_assets.py` — không phải
    link chia sẻ được cho máy khác. Khi lên VPS: assets được serve qua web
    server/cloud storage THẬT (không phải localhost), chỉ cần đổi cách build
    `url` ở call site, KHÔNG cần sửa hàm này hay cấu trúc cột/Sheet."""
    return f'=HYPERLINK("{url}", "Mở file")'


def _append_notes(topic_key: str, content_type: str, note: str) -> int | None:
    """VIỆC A (Lead 02/08, agent-C phát hiện) — nối thêm 1 dòng vào
    content_output.notes TRONG STORE, KHÔNG ghi thẳng ô Sheet. Trước bản vá
    này, renderer gọi `board.set_content_cell(row, "Notes", ...)` ghi THẲNG
    lên Sheet — giá trị đó KHÔNG ingest ngược vào store, nên lượt
    render_content_to_sheet() kế tiếp (dựng lại TOÀN BỘ tab từ store, xem
    store/sync_service.py) XOÁ MẤT cảnh báo vừa ghi mà không ai biết.

    content_output là APPEND-ONLY (document_store.write_document — KHÔNG
    merge-on-write như content_status/gate_status), nên phải đọc bản MỚI
    NHẤT, nối Notes, ghi lại NGUYÊN VẸN mọi field khác (status/output/facts/
    timestamp/published_at) — chỉ ghi mỗi `note` mà không đọc trước sẽ XOÁ
    MẤT nội dung/status đã có. Trả version vừa ghi (dùng làm "lần render thứ
    N"), None nếu chưa có content_output để gắn vào (không nên xảy ra — dòng
    đã tới được renderer nghĩa là content_output PHẢI có sẵn từ Brief/Writer/
    Composer).

    A3: sync_service.render_content_to_sheet() đã tự đọc content_output.notes
    và hiển thị lên Sheet theo CƠ CHẾ CHUNG (content_row()) — KHÔNG thêm
    đường hiển thị riêng nào ở đây, hàm này CHỈ ghi store."""
    rec = ps.read_content_output(topic_key, content_type)
    if rec is None:
        print(f"[CẢNH BÁO] Không tìm thấy content_output({content_type}) để ghi Notes cho {topic_key!r} "
             "— bỏ qua (không nên xảy ra, dòng đã tới renderer).")
        return None
    existing = (rec.get("notes") or "").strip()
    payload = dict(rec)
    payload["notes"] = f"{existing}; {note}" if existing else note
    return ps.write_content_output(topic_key, content_type, payload)


def _ranking_guard_note(entries: list[tuple[str, list[dict]]], attempt: int) -> str:
    """VIỆC A2 — mã lý do RENDER_RANKING_GUARD kèm chi tiết: tỷ lệ nào bị cắt
    mật độ theo priority (ranking) của Composer, khối nào giữ/bỏ bao nhiêu,
    và đây là lần render thứ mấy cho content_output này (xem _append_notes).
    `entries` = [(ratio, truncated_list)] CHỈ gồm ratio THẬT SỰ có cắt (xem
    render.ai_full.apply_density_cap -- truncated rỗng nghĩa là không cắt gì)."""
    parts = []
    for ratio, truncated in entries:
        detail = "; ".join(
            f"{t['block']} giữ {t['kept']}/bỏ {t['dropped']} ({t['reason']}) {t['dropped_labels']}"
            for t in truncated
        )
        parts.append(f"tỷ lệ {ratio}: {detail}")
    return f"RENDER_RANKING_GUARD (lần render thứ {attempt}): " + " | ".join(parts)


def _open_board(settings) -> SheetsBoard:
    sheet_id = (os.environ.get("TWMKT_SHEET_ID") or settings.get("sheets.spreadsheet_id") or "").strip()
    creds = (os.environ.get("TWMKT_SHEETS_CREDS") or settings.get("sheets.creds_path") or "").strip()
    if not sheet_id or not creds:
        raise SystemExit("Thiếu sheets.spreadsheet_id/creds_path (settings.yaml hoặc ENV).")
    return SheetsBoard(spreadsheet_id=sheet_id, creds_path=creds)


# 2026-07-23 (nghiệm thu Phần A-B-C, yêu cầu Lead): render ĐỦ 3 tỷ lệ/bài,
# KHÔNG còn chỉ "4:5" như bản cũ -- AssetPath (1 cột duy nhất trên Sheet,
# KHÔNG đổi schema -- ranh giới file, sheets_board.py là vùng agent-A) vẫn
# trỏ tỷ lệ CHÍNH (_PRIMARY_RATIO); 2 tỷ lệ còn lại ghi đường dẫn vào Notes
# (cột đã có sẵn, KHÔNG phải thêm cột mới).
_RATIOS: tuple[str, ...] = VALID_RATIOS   # mọi tỷ lệ renderer dựng được
_PRIMARY_RATIO = "4:5"                    # dùng khi chưa biết Composer chọn gì


def ratios_for(output_data: dict, *, settings) -> tuple[str, ...]:
    """Tỷ lệ NÀO thực sự được render cho spec này.

    2026-07-28 (yêu cầu Lead): CHỈ SINH 1 ẢNH theo `render_hint.ratio` do
    Composer chọn theo lượng thông tin, thay vì vẽ cả 3 tỷ lệ cho CÙNG một nội
    dung. Mỗi ảnh là 1 lượt gọi gpt-image-2 mất tiền thật — bản cũ tiêu gấp 3
    lần cần thiết rồi vứt 2 ảnh không ai dùng (AssetPath chỉ trỏ được 1).

    Đường thoát khi cần đủ bộ (vd chiến dịch đăng nhiều nền tảng cùng lúc):
    `render.infographic.ratios: all` trong settings.yaml.

    render_hint thiếu/sai -> `_PRIMARY_RATIO`. KHÔNG raise: đây là lớp trình
    bày, hỏng tỷ lệ không đáng đánh rơi nội dung đã sinh xong."""
    if str(settings.get("render.infographic.ratios", "hint")).strip().lower() == "all":
        return _RATIOS
    hint = output_data.get("render_hint")
    ratio = str((hint or {}).get("ratio") or "").strip() if isinstance(hint, dict) else ""
    return (ratio,) if ratio in VALID_RATIOS else (_PRIMARY_RATIO,)


_TEXT_OUTPUTS = {
    # content_type -> (đuôi file, mime).
    "article": (".md", "text/markdown"),
    # VIỆC 1 (2026-08-03) — Long-Article dùng CHUNG định dạng .md/text/markdown
    # với article (KHÔNG có định dạng ra riêng, xem models.ContentFormat.
    # LONG_ARTICLE); thiếu dòng này thì Long-Article DONE nhưng KHÔNG BAO GIỜ
    # có AssetPath (run_text_assets() chỉ lặp qua các khoá trong dict này).
    "long_article": (".md", "text/markdown"),
    # SỬA LỖI THẬT (2026-08-03, Lead báo qua ca "Thế giới Di động") — "video"
    # TỪNG có mặt ở đây (upload KỊCH BẢN .json làm AssetPath khi aigen "CHƯA
    # nối vào luồng"). Nay aigen ĐÃ nối thật (run_videos()/render_video_one()
    # dựng .mp4 thật), nhưng "video" vẫn còn trong dict này khiến run_text_
    # assets() upload KỊCH BẢN JSON làm AssetPath BẤT CỨ KHI NÀO run_videos()
    # bỏ qua/lỗi ở lượt đó — Gate 2 trông như "đã xong" dù CHƯA có video thật.
    # Lead xác nhận: CHỈ video.mp4 thật lên Drive mới được coi là hoàn thành.
    # KHÔNG thêm lại "video" vào đây — muốn AssetPath cho video, PHẢI qua
    # run_videos()/render_video_one() (aigen), không có đường lùi mượt khác.
}

# VIỆC 2 (2026-08-03, Lead) — CHỈ Article/Long-Article convert sang Google
# Docs native (2.3: Infographic .png/Video .mp4/.json GIỮ NGUYÊN, không đụng).
_GOOGLE_DOC_CONVERT_TYPES = {"article", "long_article"}


def _content_hash(body: str) -> str:
    """VIỆC 2.4 — khoá idempotent: cùng TopicKey + cùng loại + cùng NỘI DUNG
    (hash) -> KHÔNG upload lại, dùng fileId đã lưu. Nội dung đổi (bài viết lại/
    sửa) -> hash khác -> upload lại (update() cùng file, không tạo bản thứ 2,
    xem DriveAssetStore.upload())."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def upload_text_outputs(drive, *, topic_key: str, topic: str, out_dir: Path) -> dict[str, str]:
    """Đẩy các đầu ra DẠNG VĂN BẢN (article/video-script) của 1 chủ đề lên Drive,
    vào CÙNG thư mục với ảnh (`<tên chủ đề>-<dd-mm-yyyy>/`).

    Nội dung lấy NGUYÊN VĂN TỪ STORE (yêu cầu Lead 2026-07-28: "nội dung cuối
    trên Drive phải đầy đủ như trong store, không bị cắt theo Sheet") — ô Sheet
    chỉ là preview 1500 ký tự, đẩy nó lên Drive là chép lại đúng bản cụt.

    CHỈ đẩy dòng có nội dung THẬT (status DONE/ERROR): SKIPPED không có gì để
    đẩy. Trả {content_type: view_link} cho những cái đã lên."""
    links: dict[str, str] = {}
    if drive is None:
        return links
    for ctype, (ext, mime) in _TEXT_OUTPUTS.items():
        rec = ps.read_content_output(topic_key, ctype)
        if rec is None:
            continue
        body = rec.get("output") or ""
        if not body.strip():
            continue   # SKIPPED / rỗng -> không có gì để đẩy
        fn = out_dir / f"{_slug(topic)}_{ctype}{ext}"
        fn.write_text(body, encoding="utf-8")
        try:
            target_mime = GOOGLE_DOC_MIME if ctype in _GOOGLE_DOC_CONVERT_TYPES else ""
            r = drive.upload(fn, topic=topic, topic_key=topic_key, mime_type=mime,
                             target_mime_type=target_mime)
            ps.write_content_status(topic_key, ctype, asset_drive_file_id=r["id"],
                                    asset_content_hash=_content_hash(body),
                                    asset_mime_type=target_mime or mime)
            links[ctype] = r["view_link"]
            print(f"[drive] {ctype} ({len(body)} ký tự, nguyên văn từ store) -> {r['view_link']}")
        except Exception as e:   # noqa: BLE001 -- cùng lý do lùi mượt như ảnh
            print(f"[CẢNH BÁO] Upload Drive {ctype} thất bại ({e!r}) — bỏ qua, không chặn lượt render.")
    return links


def render_one(item: dict, *, settings) -> tuple[dict[str, bytes | None], dict[str, str], dict[str, dict]]:
    """Xử 1 dòng CONTENT (từ SheetsBoard.read_content_for_render) -> (png
    bytes theo tỷ lệ, cảnh báo theo tỷ lệ, log JSON theo tỷ lệ -- xem
    ai_full.render_ai_full()). Hàm THUẦN về mặt Sheet (không tự ghi Sheet)
    nhưng CÓ gọi mạng thật (OpenAI Images API qua ai_full, cache-first) --
    khác quy ước "Hàm THUẦN" cũ của renderer SVG $0.

    ĐỌC JSON TỪ STORE (Lead xác nhận 2026-07-27), KHÔNG từ item["output"]
    (ô Sheet CONTENT.Output) -- ô đó chỉ là PREVIEW cắt 1500 ký tự cho người
    liếc (xem store/sync_service.py::_preview_output()), nội dung dài hơn
    ngưỡng sẽ bị cắt cụt JSON -> json.loads() vỡ (bug gốc gây NEEDS_HUMAN oan
    ở Bước 5.3). `item["topic_key"]` vẫn đọc từ Sheet (chỉ dùng làm KHOÁ tra
    store, không phải nội dung)."""
    topic_key = item.get("topic_key", "")
    full = ps.read_content_output(topic_key, "infographic") if topic_key else None
    if full is None:
        err = f"Không tìm thấy content_output trong store cho TopicKey={topic_key!r}"
        return {_PRIMARY_RATIO: None}, {_PRIMARY_RATIO: err}, {}
    try:
        output_data = json.loads(full.get("output", ""))
    except json.JSONDecodeError:
        err = "Output không phải JSON hợp lệ (đã bị sửa hỏng ở Gate 2?)"
        return {_PRIMARY_RATIO: None}, {_PRIMARY_RATIO: err}, {}

    ratios = ratios_for(output_data, settings=settings)
    results, logs = render_ai_full(output_data, ratios=ratios, settings=settings)
    png_map = {r: results[r][0] for r in ratios}
    warn_map = {r: results[r][1] for r in ratios}
    return png_map, warn_map, logs


def render_video_one(item: dict, *, settings, drive, out_dir: Path) -> str:
    """Tuyến VIDEO: CONTENT.Output -> aigen-pipeline -> video.mp4 -> Drive.
    Trả link AssetPath ("" nếu thất bại — caller ghi Notes rồi đi tiếp).

    2026-07-28: trước bản này KHÔNG CÓ CALLER THẬT nào gọi `aigen_seam` —
    tuyến video dừng ở kịch bản JSON, không ai dựng .mp4. Nay Gate 2 duyệt
    dòng video là chạy thẳng aigen.

    Ghi `content-output.json` vào `<aigen dataRoot>/<topic_key>/` — aigen suy
    outputDir = dirname(script) nên script.json + video.mp4 tự nằm đúng chỗ,
    KHÔNG lẫn dữ liệu 2 repo (kho chung, mỗi repo 1 thư mục con)."""
    from twmkt.media_factory.aigen_seam import run_aigen_pipeline

    topic_key = item.get("topic_key", "")
    rec = ps.read_content_output(topic_key, "video")
    if rec is None or not (rec.get("output") or "").strip():
        return ""

    job_dir = Path(settings.get("media_factory.aigen_data_root",
                                "../marketing-database/aigen-pipeline")) / topic_key
    job_dir.mkdir(parents=True, exist_ok=True)
    co_path = job_dir / "content-output.json"
    co_path.write_text(rec["output"], encoding="utf-8")

    timeout_s = int(settings.get("media_factory.video_timeout_s", 1800))
    print(f"[video] Goi aigen-pipeline cho {topic_key} (timeout {timeout_s}s; lan dau "
         f"co the mat toi 180s chi de nap model TTS len GPU)...")
    res = run_aigen_pipeline(co_path, timeout_s=timeout_s)
    if not res.ok or res.video_path is None:
        print(f"[video] THAT BAI: {res.error}")
        print((res.stderr or "")[-600:])
        return ""
    print(f"[video] OK -> {res.video_path}"
         + (" (da co san, bo qua render)" if res.skipped_already_rendered else ""))

    ps.write_content_status(topic_key, "video", asset_local_path=str(res.video_path))
    if drive is None:
        return ""
    try:
        r = drive.upload(res.video_path, topic=item["context"], topic_key=topic_key,
                         mime_type="video/mp4")
        ps.write_content_status(topic_key, "video", asset_url=r["view_link"])
        print(f"[drive] video.mp4 -> {r['view_link']}")
        return r["view_link"]
    except Exception as e:   # noqa: BLE001 -- cung ly do lui muot nhu anh
        print(f"[CANH BAO] Upload Drive video that bai ({e!r}) — file van o {res.video_path}.")
        return ""


def run_videos(*, settings, board, drive, out_dir: Path, limit: int = 5) -> dict:
    """Quet dong CONTENT type=video da qua Gate 2, chua co asset -> render."""
    done = failed = skipped = 0
    for item in board.read_content_for_render(type_="video"):
        if item["approve_gate2"] != "APPROVE":
            skipped += 1
            continue
        st = ps.read_content_status(item.get("topic_key", ""), "video")
        if (st.get("asset_url") or st.get("asset_local_path") or "").strip():
            skipped += 1
            continue   # IDEMPOTENT: hoi STORE, khong hoi o Sheet (xem nhanh anh)
        if render_video_one(item, settings=settings, drive=drive, out_dir=out_dir):
            done += 1
        else:
            failed += 1
        if done >= limit:
            break
    if done or failed:
        print(f"[video] Tong: render {done} | loi {failed} | bo qua {skipped}")
    return {"video_rendered": done, "video_failed": failed, "video_skipped": skipped}


def run_text_assets(*, settings, board, drive, out_dir: Path, limit: int = 20) -> dict:
    """Tuyến VĂN BẢN (article + kịch bản video): Gate 2 duyệt -> đẩy Drive ->
    ghi AssetPath.

    PHÁT HIỆN KHI CHẠY SYSTEM-TEST (2026-07-28): trước bản này việc upload văn
    bản chỉ nằm TRONG nhánh render ảnh, nên chủ đề CHỈ có article (người chọn
    Output Type=Article) duyệt Gate 2 xong thì job chạy, báo "render 0", rồi
    KHÔNG upload gì và KHÔNG có AssetPath. Đúng thứ Lead yêu cầu phải có mà
    lại hụt — vì cả luồng asset trước giờ ngầm định "asset = ảnh".

    Nội dung lấy NGUYÊN VĂN TỪ STORE (không phải ô Sheet 1500 ký tự)."""
    done = skipped = 0
    for ctype, (ext, mime) in _TEXT_OUTPUTS.items():
        for item in board.read_content_for_render(type_=ctype):
            if item["approve_gate2"] != "APPROVE":
                skipped += 1
                continue
            tk = item.get("topic_key", "")
            rec = ps.read_content_output(tk, ctype)
            body = (rec or {}).get("output") or ""
            if not body.strip():
                skipped += 1
                continue   # SKIPPED/rỗng -> không có gì để đẩy
            # VIỆC 2.4 (2026-08-03, Lead) — IDEMPOTENT theo TopicKey + loại +
            # content-hash: đã có asset_url VÀ hash KHÔNG đổi -> bỏ qua, dùng
            # fileId đã lưu. Nội dung đổi (viết lại/sửa) -> hash khác -> upload
            # lại (update() cùng file trong DriveAssetStore.upload(), KHÔNG
            # tạo bản thứ 2). Đọc STORE, không đọc ô Sheet (cùng nếp cũ).
            st = ps.read_content_status(tk, ctype)
            current_hash = _content_hash(body)
            if (st.get("asset_url") or "").strip() and st.get("asset_content_hash") == current_hash:
                skipped += 1
                continue
            fn = out_dir / f"{_slug(item['context'])}_{ctype}{ext}"
            fn.write_text(body, encoding="utf-8")
            ps.write_content_status(tk, ctype, asset_local_path=str(fn))
            if drive is None:
                continue
            try:
                target_mime = GOOGLE_DOC_MIME if ctype in _GOOGLE_DOC_CONVERT_TYPES else ""
                r = drive.upload(fn, topic=item["context"], topic_key=tk, mime_type=mime,
                                 target_mime_type=target_mime)
                ps.write_content_status(tk, ctype, asset_url=r["view_link"],
                                        asset_drive_file_id=r["id"], asset_content_hash=current_hash,
                                        asset_mime_type=target_mime or mime)
                print(f"[drive] {ctype} ({len(body)} ký tự, nguyên văn store) -> {r['view_link']}")
                done += 1
            except Exception as e:   # noqa: BLE001 -- lùi mượt như các nhánh khác
                print(f"[CẢNH BÁO] Upload Drive {ctype} thất bại ({e!r}).")
            if done >= limit:
                break
    if done:
        print(f"[text] Tổng: đẩy Drive {done} | bỏ qua {skipped}")
    return {"text_uploaded": done, "text_skipped": skipped}


def run(*, limit: int = 20) -> dict:
    settings = load_settings()
    board = _open_board(settings)

    drive = build_drive_store(settings)
    print(f"[drive] {'BẬT — link AssetPath lấy từ Drive' if drive else 'TẮT (drive.enabled=false) — dùng asset server cục bộ'}")

    candidates = board.read_content_for_render(type_="infographic")
    output_root = data_path(settings.get("storage.output_dir", "output"), settings=settings)
    out_dir = output_root / _today() / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    asset_port = int(settings.get("storage.asset_server_port", DEFAULT_PORT))

    rendered = skipped_not_approved = skipped_already_rendered = needs_human = 0
    for item in candidates:
        # IDEMPOTENT: đã render -> KHÔNG đụng lại (có thể đã/đang chờ Gate 3).
        # Hỏi STORE, không hỏi ô Sheet (2026-07-28): từ khi asset_url đi qua
        # store, ô Sheet chỉ là BẢN CHIẾU và có thể trễ 1 nhịp render — đọc nó
        # làm điều kiện chặn là quay lại đúng cái bẫy "2 nguồn sự thật" đã gây
        # ra loạt bug hôm nay. Bắt được thật: xoá asset_url trong store rồi
        # enqueue lại, job vẫn bị bỏ qua vì ô Sheet còn giữ link cũ.
        st = ps.read_content_status(item.get("topic_key", ""), "infographic")
        if (st.get("asset_url") or st.get("asset_local_path") or "").strip():
            skipped_already_rendered += 1
            continue
        # Dòng KHÔNG có nội dung để render (router SKIPPED, hoặc Output rỗng).
        # 2026-07-28 (System-Test): người duyệt Gate 2 trên dòng SKIPPED là
        # chuyện bình thường (đọc lý do rồi bấm cho xong), nhưng bản cũ đi
        # thẳng vào json.loads("") -> báo "Output không phải JSON hợp lệ (đã bị
        # sửa hỏng ở Gate 2?)" và đếm NEEDS_HUMAN. Chẩn đoán SAI HẲN nguyên
        # nhân: không ai sửa hỏng gì, chỉ là chưa từng có nội dung.
        rec = ps.read_content_output(item.get("topic_key", ""), "infographic")
        if rec is None or not (rec.get("output") or "").strip():
            print(f"[bỏ qua] '{item['context'][:60]}': tuyến infographic không có nội dung "
                 f"(status={(rec or {}).get('status', '?')}) — không có gì để render.")
            skipped_not_approved += 1
            continue
        if item["approve_gate2"] != "APPROVE":
            skipped_not_approved += 1
            continue   # chưa qua Gate 2 -> chưa tới lượt render

        png_map, warn_map, logs = render_one(item, settings=settings)
        # Tỷ lệ CHÍNH = tỷ lệ ĐẦU TIÊN thực sự được yêu cầu render, KHÔNG còn
        # là hằng "4:5" (2026-07-28: Composer chọn tỷ lệ, thường chỉ 1 — hằng
        # cũ sẽ KeyError khi Composer chọn 9:16).
        primary = next(iter(png_map), _PRIMARY_RATIO)
        if png_map.get(primary) is None:
            warning = warn_map.get(primary, "lỗi không rõ")
            _append_notes(item["topic_key"], "infographic",
                         f"NEEDS_HUMAN (render ai_full {primary}): {warning}")
            print(f"[NEEDS_HUMAN] '{item['context'][:60]}': {warning}")
            needs_human += 1
            continue

        slug = _slug(item["context"])
        written: dict[str, Path] = {}
        for ratio in png_map:
            png_bytes = png_map.get(ratio)
            if png_bytes is None:
                print(f"[CẢNH BÁO] '{item['context'][:60]}' tỷ lệ {ratio} thất bại: {warn_map.get(ratio)}")
                continue
            suffix = ratio.replace(":", "x")
            fn = out_dir / f"{slug}_{suffix}.png"
            fn.write_bytes(png_bytes)
            # A2 Bước 6 -- log JSON CẠNH ảnh (Lead kiểm không cần mở ảnh).
            log_fn = out_dir / f"{slug}_{suffix}.log.json"
            log_fn.write_text(json.dumps(logs.get(ratio, {}), ensure_ascii=False, indent=2), encoding="utf-8")
            written[ratio] = fn

        # VIỆC A2 — density cap (render/ai_full.apply_density_cap) cắt bớt
        # market/highlights/related theo priority (ranking) của Composer khi
        # vượt sức chứa layout của tỷ lệ. Trước bản vá này, sự kiện cắt CHỈ
        # log ra console/file .log.json CẠNH ảnh — KHÔNG có dấu vết nào trên
        # Sheet/store dù ảnh vẫn render "thành công" (silently drop items).
        # Ghi vào Notes (mã RENDER_RANKING_GUARD) để người duyệt Gate 3 biết
        # có mục bị bỏ mà không cần mở từng .log.json.
        ranking_entries = [(r, logs[r]["truncated"]) for r in png_map
                          if logs.get(r, {}).get("truncated")]
        if ranking_entries:
            attempt = len(ds.read_history(item["topic_key"], "content_output", "infographic")) + 1
            _append_notes(item["topic_key"], "infographic",
                         _ranking_guard_note(ranking_entries, attempt))

        primary_fn = written[primary]
        # Drive (2026-07-28) là nguồn link CHÍNH khi bật: link chia sẻ thật,
        # người duyệt Gate 3 mở được từ máy bất kỳ. Đẩy CẢ 3 tỷ lệ lên
        # <loại>/<dd-mm-yyyy>/<chủ đề>/, lấy link của tỷ lệ CHÍNH làm AssetPath.
        # LÙI MƯỢT: drive.enabled=false HOẶC lỗi mạng/quyền -> quay về link
        # asset server cục bộ như trước, KHÔNG chặn cả lượt render (ảnh đã có
        # trên đĩa rồi, mất link còn vớt lại được; ném lỗi ở đây thì công
        # render + tiền API mất trắng).
        url = asset_url(primary_fn, root=output_root, port=asset_port)
        if drive is not None:
            try:
                res = {}
                for ratio, fn in written.items():
                    r = drive.upload(fn, topic=item["context"],
                                     topic_key=item.get("topic_key", ""),
                                     mime_type="image/png")
                    # `primary` (tỷ lệ THẬT vừa render), KHÔNG phải hằng
                    # _PRIMARY_RATIO="4:5" — bug bắt được ở e2e 2026-07-28:
                    # Composer chọn 9:16 nên so với hằng 4:5 không bao giờ
                    # khớp, `res` rỗng, AssetPath âm thầm giữ link 127.0.0.1
                    # dù ảnh ĐÃ lên Drive thành công.
                    if ratio == primary:
                        res = r
                if res:
                    url = res["view_link"]
                    print(f"[drive] {len(written)} ảnh -> Drive, link chính: {url}")
                # Article + kịch bản video CÙNG thư mục chủ đề (2026-07-28):
                # trước đây Drive CHỈ có infographic, 2 đầu ra kia không lên
                # đâu cả dù store đã có sẵn nội dung đầy đủ.
                upload_text_outputs(drive, topic_key=item.get("topic_key", ""),
                                    topic=item["context"], out_dir=out_dir)
            except Exception as e:   # noqa: BLE001 -- xem lý do lùi mượt ở trên
                print(f"[CẢNH BÁO] Upload Drive thất bại ({e!r}) -> dùng link asset server cục bộ.")
        # P2 store-as-truth — GHI VÀO STORE TRƯỚC (2026-07-28, bug bắt được ở
        # lượt e2e thật): trước bản vá này hàm chỉ ghi THẲNG ô Sheet, mà từ khi
        # queue_worker gọi `render_content_to_sheet()` ngay sau mỗi job, lượt
        # render đó DỰNG LẠI TOÀN BỘ tab từ store -> AssetPath vừa ghi bị XOÁ
        # SẠCH vài giây sau. Ảnh render thành công nhưng người duyệt Gate 3
        # không có link nào để bấm. Trường `asset_url`/`asset_local_path` đã
        # tồn tại sẵn trong content_status và render_content_to_sheet ĐÃ đọc
        # chúng — chỉ thiếu đúng người GHI.
        ps.write_content_status(item["topic_key"], "infographic",
                                asset_url=url, asset_local_path=str(primary_fn))
        # VIỆC A (Lead 02/08) — KHÔNG còn ghi thẳng ô Sheet ở đây nữa (trước
        # đây có 1 lượt `board.set_content_cell(..., "AssetPath", ...)` "cho
        # phản hồi tức thì" — nhưng đây CHÍNH LÀ loại "bộ ghi trực tiếp lên
        # Sheet còn sót" agent-C phát hiện: giá trị không ingest ngược vào
        # store nên lượt sync kế tiếp có thể ghi đè bằng giá trị CŨ nếu 2
        # luồng lệch nhịp. store đã có asset_url/asset_local_path (dòng trên)
        # -- sync_service.render_content_to_sheet() tự đọc và hiển thị theo
        # cơ chế chung (A3), không cần đường tắt riêng.
        other = "; ".join(f"{r}: {p}" for r, p in written.items() if r != primary)
        if other:
            _append_notes(item["topic_key"], "infographic",
                         f"Tỷ lệ khác (chưa có cột riêng): {other}")
        print(f"[render] '{item['context'][:60]}' -> {len(written)}/{len(png_map)} tỷ lệ ({primary}), "
             f"primary={primary_fn} ({url})")
        rendered += 1
        if rendered >= limit:
            break

    print(f"\nTổng: render {rendered} | bỏ qua (đã render) {skipped_already_rendered} | "
         f"bỏ qua (chưa qua Gate 2) {skipped_not_approved} | NEEDS_HUMAN {needs_human}")

    # Tuyến VIDEO chạy SAU tuyến ảnh trong CÙNG lượt job (2026-07-28) — 1 job
    # `render_assets` lo cả 2, không tách job riêng: cùng 1 cổng duyệt Gate 2,
    # tách ra chỉ thêm trạng thái phải đồng bộ.
    vid = run_videos(settings=settings, board=board, drive=drive, out_dir=out_dir)
    txt = run_text_assets(settings=settings, board=board, drive=drive, out_dir=out_dir)
    return {"rendered": rendered, "skipped_already_rendered": skipped_already_rendered,
           "skipped_not_approved": skipped_not_approved, "needs_human": needs_human, **vid, **txt}


def _parse_args(argv: list[str]):
    import argparse
    ap = argparse.ArgumentParser(
        description="Render asset (SVG) cho CONTENT infographic đã qua Gate 2 (Production Factory Phase 1.3).")
    ap.add_argument("--limit", type=int, default=20, help="Số asset tối đa render mỗi lượt.")
    return ap.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    run(limit=args.limit)
