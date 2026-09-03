# 使用 OmniParser 作为后端运行外层 UI 还原 Agent
# 用法：.\scripts\run_agent_with_omniparser.ps1 --image uploads/test01.png --tool svg

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
cd $ProjectRoot

# 解析传入参数
$RemainingArgs = $args

# 先检查 OmniParser 服务是否可用
try {
    $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -Method GET -TimeoutSec 3
    Write-Host "OmniParser 服务已就绪: $($resp.status)" -ForegroundColor Green
} catch {
    Write-Host "⚠️ 无法连接到 OmniParser 服务 http://127.0.0.1:8000" -ForegroundColor Yellow
    Write-Host "   请先运行 .\scripts\start_omniparser_server.ps1" -ForegroundColor Yellow
    exit 1
}

# 设置环境变量并运行 Agent
$env:OMNIPARSER_ENABLED = "true"
$env:OMNIPARSER_URL = "http://127.0.0.1:8000"
$env:OMNIPARSER_FALLBACK = "true"

$CondaEnv = "omni"
try {
    $condaInfo = conda info --envs 2>$null
    if ($LASTEXITCODE -eq 0 -and $condaInfo -match "^$CondaEnv\s+") {
        Write-Host "使用 conda 环境: $CondaEnv" -ForegroundColor Green
        conda run -n $CondaEnv --no-capture-output python -m src.main @RemainingArgs
    } else {
        throw "未找到环境"
    }
} catch {
    Write-Host "未能找到 conda 环境 '$CondaEnv'，使用当前 Python 环境" -ForegroundColor Yellow
    python -m src.main @RemainingArgs
}
