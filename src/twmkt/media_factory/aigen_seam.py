"""Seam subprocess — gọi AIGEN pipeline THẬT (`npm run pipeline`) từ
marketing-automation, thu `video.mp4`, xử lý exit code/timeout/lỗi.

RANH GIỚI MÁY (xem tasks/ACTIVE_TASK.md "BỐI CẢNH MÁY"): máy PC-A (nơi module
này được VIẾT) KHÔNG BAO GIỜ thực thi lệnh này thật — không có OmniVoice/
ffmpeg/Chrome/CUDA. Test (`tests/test_pipeline.py`) MOCK `subprocess.run`
hoàn toàn — KHÔNG có test nào ở đây gọi `npm` thật. `run_aigen_pipeline(...,
dry_run=True)` là chế độ AN TOÀN dùng trên PC-A: chỉ LOG lệnh sẽ chạy, không
thực thi. Máy render thật (PC-B/VPS) mới gọi `dry_run=False`.

GIẢ ĐỊNH exit code (AIGEN `src/cli.ts` — đọc THẬT, không suy đoán, xem
`tasks/ACTIVE_TASK.md` Discovery Phase 0): `process.exit(2)` = thiếu argument
`script.json` (không nên xảy ra — seam LUÔN truyền path); `process.exit(1)` =
pipeline thất bại (thiếu ffmpeg/PATH, script.json không hợp lệ Zod, TTS lỗi,
timeout nội bộ...). Tài liệu AIGEN KHÔNG phân biệt rõ Ý NGHĨA giữa 2 mã lỗi
đủ để xử lý khác nhau một cách đáng tin cậy — module này coi CẢ HAI là FATAL
như nhau (không cố đoán thêm ý nghĩa từ mã số).

IDEMPOTENT PER-ASSET, KHÔNG CỜ --force TOÀN CỤC: nếu `video.mp4` (CÙNG thư
mục với `script.json` — xác nhận Discovery Phase 0: `outputDir =
dirname(scriptPath)`) ĐÃ TỒN TẠI trước khi gọi, BỎ QUA HOÀN TOÀN việc gọi
subprocess (trả `skipped_already_rendered=True`). Muốn render lại 1 asset cụ
thể: người vận hành tự xoá `video.mp4` đó rồi gọi lại — đúng nếp per-step
idempotent AIGEN đã có nội bộ (xoá 1 file cụ thể để ép render lại đúng bước
đó), áp dụng thêm ở biên NGOÀI của seam này để tránh gọi `npm run pipeline`
thừa khi đã có kết quả.

ĐƯỜNG DẪN REPO AIGEN QUA CONFIG, KHÔNG HARDCODE (sửa sau sự cố A5 — dry-run
từng in `cwd=E:\aigen-fva-capital\aigen`, repo ĐÃ CHẾT, xem
docs/VPS_MIGRATION_BACKLOG.md A5): `aigen_repo_path=None` (mặc định) ->
resolve qua `twmkt.config.aigen_repo_path()` (ENV `AIGEN_REPO_PATH` hoặc
`media_factory.aigen_repo_path` trong settings.yaml, mặc định sibling
"../aigen-pipeline" — CÙNG NẾP `data_root()`). Đổi máy (VPS) chỉ cần đổi 1
dòng config hoặc set ENV, KHÔNG sửa code. Path không tồn tại -> raise
`AigenRepoPathNotFoundError` nêu RÕ đường dẫn đã thử, không fail mù bằng lỗi
OS/subprocess khó hiểu. Truyền `aigen_repo_path` TƯỜNG MINH (như test làm)
vẫn được — bỏ qua bước resolve/validate config, giữ nguyên hành vi cũ.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from twmkt.config import aigen_repo_path as _resolve_aigen_repo_path


class AigenRepoPathNotFoundError(FileNotFoundError):
    """Path repo AIGEN (từ ENV AIGEN_REPO_PATH hoặc config
    media_factory.aigen_repo_path) không tồn tại trên đĩa — lỗi cấu hình phổ
    biến nhất khi đổi máy (VPS). Message nêu RÕ đường dẫn đã thử."""


@dataclass
class AigenPipelineResult:
    """Kết quả 1 lần gọi `run_aigen_pipeline()`. `ok=True` + `video_path=None`
    có thể xảy ra ở chế độ `dry_run` (chưa thực sự render gì)."""
    ok: bool
    video_path: Path | None
    skipped_already_rendered: bool
    exit_code: int | None
    stdout: str
    stderr: str
    error: str = ""


def run_aigen_pipeline(script_path: Path, *, aigen_repo_path: Path | None = None,
                       dry_run: bool = False, timeout_s: int = 1800) -> AigenPipelineResult:
    """Gọi `npm run pipeline -- <script_path>` với cwd=`aigen_repo_path`.

    `aigen_repo_path=None` (mặc định) -> resolve qua config (ENV
    AIGEN_REPO_PATH / settings.yaml media_factory.aigen_repo_path, xem
    docstring module) rồi kiểm tồn tại, raise `AigenRepoPathNotFoundError`
    nêu rõ đường dẫn nếu thiếu. Truyền tường minh -> dùng nguyên giá trị đó,
    KHÔNG qua bước resolve/validate config (test dùng nhánh này).

    Thứ tự kiểm tra: (1) `video.mp4` đã tồn tại? -> skip ngay, không đụng
    subprocess. (2) `dry_run=True`? -> chỉ log lệnh sẽ chạy, không thực thi.
    (3) Gọi thật, bắt timeout/exit code khác 0 (cả exit 1 và 2 đều FATAL —
    xem docstring module) đều fatal như nhau. (4) exit 0 nhưng KHÔNG thấy
    video.mp4 -> vẫn coi là lỗi (đừng tin exit code một mình)."""
    if aigen_repo_path is None:
        aigen_repo_path = _resolve_aigen_repo_path()
        if not aigen_repo_path.exists():
            raise AigenRepoPathNotFoundError(
                f"Không thấy repo AIGEN tại '{aigen_repo_path}' (từ ENV AIGEN_REPO_PATH "
                "hoặc settings.yaml media_factory.aigen_repo_path). Đổi máy (VPS)? Kiểm tra "
                "lại đường dẫn trong config/settings.yaml hoặc set biến môi trường "
                "AIGEN_REPO_PATH trỏ đúng nơi đã clone github.com/trieuvan-s/aigen-pipeline."
            )

    video_path = script_path.parent / "video.mp4"
    if video_path.exists():
        return AigenPipelineResult(ok=True, video_path=video_path,
                                   skipped_already_rendered=True, exit_code=None,
                                   stdout="", stderr="")

    # `produce:content` (KHÔNG phải `pipeline`) — SỬA 2026-07-28 sau khi chạy
    # thật. Hai lý do, cả hai đều làm bản cũ KHÔNG BAO GIỜ chạy nổi:
    #  1. `npm run pipeline` (cli.ts) nhận `TemplateScript` ĐÃ chuyển đổi, còn
    #     ta đưa vào `CONTENT.Output` -> Zod từ chối ngay. Bước chuyển đổi
    #     (`buildTemplateScriptFromContentOutput`) trước đây chỉ nằm trong
    #     `scripts/_e2e_real_build.ts` (script thử nghiệm, không phải cổng vào).
    #  2. `pipeline` KHÔNG tự bật OmniVoice TTS; `produce:content` thì có
    #     (dùng lại nếu healthy, không thì spawn warm --device cuda:0, chờ
    #     /health tối đa 180s) — nên KHÔNG cần khởi động TTS bằng tay nữa.
    # `script_path` giờ trỏ file `content-output.json`; aigen tự ghi
    # `script.json` + `video.mp4` CÙNG thư mục đó.
    # `shutil.which("npm")` — BẮT BUỘC trên Windows (bug thật 2026-07-29):
    # npm cài bằng shim `npm.cmd`, mà `subprocess.run(shell=False)` KHÔNG tự
    # thử phần mở rộng theo PATHEXT như shell -> bare "npm" luôn
    # FileNotFoundError dù npm có trong PATH và gõ tay chạy được. ĐÚNG bài học
    # đã giải quyết ở `agents/base.py::ClaudeCodeLLM.complete()` cho `claude`
    # — cùng lỗi, cùng cách sửa, chỉ khác chỗ chưa ai áp vào đây.
    npm = shutil.which("npm") or "npm"
    cmd = [npm, "run", "produce:content", "--", str(script_path)]

    if dry_run:
        return AigenPipelineResult(
            ok=True, video_path=None, skipped_already_rendered=False, exit_code=None,
            stdout=f"[DRY-RUN] sẽ chạy: {' '.join(cmd)} (cwd={aigen_repo_path})",
            stderr="",
        )

    try:
        proc = subprocess.run(cmd, cwd=str(aigen_repo_path), capture_output=True,
                              text=True, timeout=timeout_s)
    except FileNotFoundError:
        return AigenPipelineResult(
            ok=False, video_path=None, skipped_already_rendered=False, exit_code=None,
            stdout="", stderr="",
            error=f"Không chạy được '{cmd[0]}' (cwd={aigen_repo_path}). Cài Node/npm "
                 f"hoặc thêm vào PATH của TIẾN TRÌNH chạy worker — trên Windows npm là "
                 f"shim .cmd, tiến trình nền có thể có PATH khác terminal.",
        )
    except subprocess.TimeoutExpired as e:
        return AigenPipelineResult(
            ok=False, video_path=None, skipped_already_rendered=False, exit_code=None,
            stdout=(e.stdout or ""), stderr=(e.stderr or ""),
            error=f"timeout sau {timeout_s}s",
        )

    if proc.returncode != 0:
        return AigenPipelineResult(
            ok=False, video_path=None, skipped_already_rendered=False,
            exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr,
            error=f"AIGEN pipeline exit {proc.returncode} (exit 1 = pipeline lỗi, "
                 "exit 2 = thiếu argument — tài liệu không phân biệt đủ rõ để xử lý "
                 "khác nhau, coi cả hai FATAL như nhau)",
        )

    if not video_path.exists():
        return AigenPipelineResult(
            ok=False, video_path=None, skipped_already_rendered=False,
            exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr,
            error=f"exit 0 nhưng KHÔNG thấy video.mp4 tại {video_path}",
        )

    return AigenPipelineResult(
        ok=True, video_path=video_path, skipped_already_rendered=False,
        exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr,
    )
