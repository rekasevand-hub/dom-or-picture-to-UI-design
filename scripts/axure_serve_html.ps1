# 把 Axure 8 发布的 HTML 目录用本地 HTTP 服务跑起来，再打开页面。
#
# 为什么必须有这一步：Axure 8 的产物在 `file://` 下会被它自己的守卫页拦住
# （`index.html` 第 92 行：Firefox >= 68 且 file:// -> 跳 `resources/chrome/firefox.html`，
# 文案就是 "Firefox does not permit locally stored files to be viewed"）。
# 任何静态 HTTP 服务都能绕过去 —— Axure 自己的 `Preview` 就是这么做的。
#
# 用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/axure_serve_html.ps1 -Dir <发布目录>
#   ... -Dir <目录> -Port 8766 -Page "index.html#p=home" -NoOpen
#
# 说明：进程是后台隐藏窗口，退出前用 -Stop 或 taskkill 收掉；Ctrl+C 不会自动带走它。
param(
  [Parameter(Mandatory=$true)][string]$Dir,
  [int]$Port = 8765,
  [string]$Page = "index.html",
  [string]$PythonExe = "C:\Users\lzq\.conda\envs\omni\python.exe",
  [switch]$NoOpen,
  [switch]$Stop
)
$ErrorActionPreference = "Continue"
$resolved = (Resolve-Path -LiteralPath $Dir).Path

if ($Stop) {
  Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "http\.server\s+$Port\b" } |
    ForEach-Object { taskkill /PID $_.ProcessId /T /F 2>&1 | Out-Null }
  Write-Output "STOPPED port=$Port"
  exit 0
}

if (-not (Test-Path -LiteralPath (Join-Path $resolved "index.html"))) {
  Write-Output "RESULT=NO_INDEX dir=$resolved"; exit 1
}

$alive = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -match "http\.server\s+$Port\b" }
if (-not $alive) {
  Start-Process -FilePath $PythonExe -WindowStyle Hidden -ArgumentList @(
    "-m", "http.server", "$Port", "--bind", "127.0.0.1", "--directory", $resolved
  ) | Out-Null
}

$url = "http://127.0.0.1:$Port/$Page"
$code = $null
for ($i = 0; $i -lt 20 -and -not $code; $i++) {
  Start-Sleep -Milliseconds 500
  try { $code = (Invoke-WebRequest -Uri "http://127.0.0.1:$Port/index.html" -UseBasicParsing -TimeoutSec 5).StatusCode } catch { $code = $null }
}
if (-not $code) { Write-Output "RESULT=SERVER_DOWN port=$Port"; exit 1 }

Write-Output "RESULT=OK http=$code"
Write-Output "URL=$url"
Write-Output "DIR=$resolved"
if (-not $NoOpen) { Start-Process $url | Out-Null }