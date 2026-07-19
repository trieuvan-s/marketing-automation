<#
.SYNOPSIS
    Cài api/main.py (uvicorn) thành Windows Service qua NSSM -- tự khởi động
    cùng máy, tự restart khi crash, log ra file (xem docs/VPS_MIGRATION_BACKLOG.md
    A1 -- thay scheduler 30' chạy tay hiện tại).

.DESCRIPTION
    RÁP SAU / CHƯA TEST THẬT: viết trên PC-A (không phải VPS), máy này KHÔNG
    cài NSSM để verify script chạy đúng -- kiểm tra lại đường dẫn nssm.exe,
    quyền Admin (NSSM cần chạy PowerShell as Administrator), và tên service
    trước khi chạy thật trên VPS. NSSM tải tại https://nssm.cc/download
    (KHÔNG có sẵn qua winget/choco chính thức, tải thủ công).

.EXAMPLE
    # Chạy với quyền Administrator, từ thư mục gốc repo hoặc bất kỳ đâu:
    .\api\install_service.ps1
#>
param(
    [string]$ServiceName = "MarketingAutomationWebhook",
    [string]$RepoRoot = (Resolve-Path "$PSScriptRoot\.."),
    [string]$NssmPath = "nssm.exe",  # giả định nssm.exe đã có trong PATH -- sửa thành đường dẫn đầy đủ nếu chưa
    [int]$Port = $(if ($env:WEBHOOK_PORT) { [int]$env:WEBHOOK_PORT } else { 8899 })
)

$ErrorActionPreference = "Stop"

$venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $pythonExe = $venvPython
} else {
    Write-Warning "Không thấy venv tại $venvPython -- dùng 'python' hệ thống. Xác nhận venv đã dựng đúng trên VPS trước khi cài service thật."
    $pythonExe = "python"
}

$uvicornArgs = "-m uvicorn api.main:app --host 0.0.0.0 --port $Port"
$logDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

Write-Host "Cài service '$ServiceName' -- python: $pythonExe -- port: $Port"

& $NssmPath install $ServiceName $pythonExe $uvicornArgs
& $NssmPath set $ServiceName AppDirectory $RepoRoot
& $NssmPath set $ServiceName AppStdout (Join-Path $logDir "webhook.out.log")
& $NssmPath set $ServiceName AppStderr (Join-Path $logDir "webhook.err.log")
& $NssmPath set $ServiceName AppRestartDelay 5000
& $NssmPath set $ServiceName Start SERVICE_AUTO_START

Write-Host ""
Write-Host "Đã cài xong (chưa start). Chạy tay:"
Write-Host "  nssm start $ServiceName"
Write-Host "Kiểm tra sống:"
Write-Host "  Invoke-RestMethod http://127.0.0.1:$Port/health"
Write-Host ""
Write-Host "LƯU Ý: biến môi trường WEBHOOK_TOKEN (bắt buộc) và WEBHOOK_PORT (tuỳ chọn)"
Write-Host "phải được set Ở CẤP HỆ THỐNG (System Environment Variables) trước khi start"
Write-Host "service -- NSSM KHÔNG tự đọc file .env, chỉ đọc ENV thật của process."
