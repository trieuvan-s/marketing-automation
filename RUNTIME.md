# RUNTIME.md — môi trường chạy marketing-automation trên máy này (Windows/VPS)

> Sổ tay DỰNG LẠI MÁY. Không phải handoff nội dung/quyết định (xem
> `tasks/ACTIVE_TASK.md`, `PROJECT_HANDOFF_P5.md`) — chỉ ghi đúng những gì đã
> cài để repo chạy được. Cập nhật 2026-07-19, máy `D:\trung-temp\`.

## Vị trí thư mục (sibling, KHÔNG lồng nhau)

```
D:\trung-temp\
  marketing-automation\            <- repo này
  aigen\                           <- repo TypeScript (LƯU Ý: tên thư mục là "aigen",
                                      KHÔNG phải "aigen-pipeline")
  marketing-automation-database\   <- data_root (storage.data_root = "../marketing-automation-database")
```

## Tầng 1 — ĐÃ DỰNG (suite Python chạy được)

- **Python 3.13.14**, cài user-level tại
  `C:\Users\may99\AppData\Local\Programs\Python\Python313\`.
  - Cài bằng installer python.org (`python-3.13.14-amd64.exe`) với
    `/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1`.
  - **winget KHÔNG có trên máy này** — đừng theo hướng dẫn `winget install`.
  - `pyproject.toml` yêu cầu `requires-python = ">=3.10"` → 3.13.14 hợp lệ.
    (Không cần khớp CPython 3.11 của OmniVoice: venv 2 bên TÁCH BIỆT.)
- **venv riêng của repo**: `D:\trung-temp\marketing-automation\.venv\`
  (đã có trong `.gitignore`, TÁCH BIỆT hoàn toàn với venv OmniVoice của aigen).
  - Tạo: `<python313>\python.exe -m venv .venv`
  - Cài deps: `.venv\Scripts\python.exe -m pip install -r requirements.txt`
  - Cài package + pytest: `.venv\Scripts\python.exe -m pip install -e ".[dev]"`
    (bước này BẮT BUỘC để `import twmkt` chạy được dưới pytest, vì
    `[tool.setuptools.packages.find] where = ["src"]`).
  - Thêm khi cần chẩn đoán treo: `pip install pytest-timeout`.
- **Chạy suite**: `.venv\Scripts\python.exe -m pytest tests -q`
  → **400 passed in ~16s** (2026-07-19, máy này). Suite là MockLLM/$0, tất
  định, KHÔNG chạm mạng/Sheet — không cần credentials để chạy test.

## 3 bẫy Windows đã gặp thật (đọc trước khi dựng lại)

1. **App execution alias giả**: `python` trên PATH trỏ
   `...\WindowsApps\python.exe` (stub Microsoft Store), chạy ra thông báo
   "Python was not found but can be installed from the Microsoft Store".
   → Gọi bằng ĐƯỜNG DẪN ĐẦY ĐỦ, hoặc tắt alias ở
   Settings > Apps > Advanced app settings > App execution aliases.
2. **PATH không refresh trong session đang mở**: sau khi cài, terminal ĐANG
   mở vẫn dùng PATH cũ (kể cả `py` launcher cũng chưa thấy). Terminal MỚI thì
   có. → Trong phiên đang chạy, luôn dùng full path tới `.venv\Scripts\python.exe`.
3. **PowerShell `>` ghi file ở UTF-16**: `pytest ... > collect.txt` rồi
   `grep` bằng Git Bash sẽ KHÔNG khớp gì (file UTF-16, grep đọc byte).
   → Xử lý file đó bằng chính PowerShell (`Get-Content`), hoặc ghi bằng
   `Out-File -Encoding utf8`.

## Quyền chạy lệnh (Claude Code trên máy này) — QUAN TRỌNG

Máy đặt `permissions.defaultMode: "auto"` (ở `C:\Users\may99\.claude\settings.json`),
có classifier duyệt từng lệnh.

- **Dùng Bash tool để chạy Python, KHÔNG dùng PowerShell tool.** Allowlist đang
  mở cho `Bash(...python.exe ...)`; lệnh qua PowerShell tool bị hỏi/từ chối.
  Lệnh chạy được đã kiểm chứng:
  `D:/trung-temp/marketing-automation/.venv/Scripts/python.exe -m pytest tests -q`
- **Lệnh phải ĐƠN, không ghép**: không `;`, không `&&`, không `cd X; lệnh`,
  không biến tạm `$SP=...`, không `(Get-Content ...)` lồng trong lệnh. Lệnh
  ghép không khớp luật theo tiền tố → luôn bị hỏi.
- Agent KHÔNG tự sửa được file quyền (`.claude/settings*.json`) — classifier
  chặn, đúng thiết kế. Người vận hành tự sửa.

## Prerequisites ngoài package (đã kiểm 2026-07-19 — ĐỦ)

| Thứ | Đường dẫn cấu hình | Trạng thái |
|---|---|---|
| Service Account Google Sheet | `sheets.creds_path: "secrets/sa.json"` | CÓ |
| Biến bí mật | `secrets/.env` — `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | CÓ (đủ 2 biến settings.yaml tham chiếu) |
| data_root | `storage.data_root: "../marketing-automation-database"` | CÓ |

Không có `secrets/.env.example` trong repo — danh sách biến cần lấy từ
`grep '${' config/settings.yaml`. `ANTHROPIC_API_KEY` để trống là HỢP LỆ khi
`llm.mode="claude_code"` (dùng CLI `claude -p`, không cần key riêng).

## Tầng 2 — CHƯA DỰNG (cần cho chạy THẬT, không cần cho test)

- **ffmpeg/ffprobe**: ĐÃ CÓ trên máy này (8.1.2, trên PATH) — dùng bởi aigen.
- **OmniVoice server** (TTS local, `:8123`): chưa dựng. Máy này đủ phần cứng
  (khác PC-A cũ) — đây là việc còn lại trước khi render video thật.
- **Task Scheduler/NSSM** cho `system_power_on.py`: CHƯA đăng ký, đang chạy tay.
  `scripts/run_scheduler.py --print-os` in sẵn lệnh `schtasks` mẫu.
- **`storage.asset_server_enabled`**: đang `false`; bật `true` khi muốn
  `system_power_on.py` tự chạy asset server.
