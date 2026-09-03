# 启动 OmniParser 本地 HTTP 包装服务
# 用法：右键“使用 PowerShell 运行” 或在 PowerShell 中执行：
#   .\scripts\start_omniparser_server.ps1

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$OmniRoot = Join-Path $ProjectRoot "OmniParser\OmniParser-master"
$SomModel = Join-Path $OmniRoot "weights\icon_detect\model.pt"
$CaptionModel = Join-Path $OmniRoot "weights\icon_caption_florence"

# 检查权重是否存在
if (-not (Test-Path $SomModel)) {
    Write-Host "错误：未找到 YOLO 权重 $SomModel" -ForegroundColor Red
    Write-Host "请先下载 OmniParser 权重到 $OmniRoot\weights\" -ForegroundColor Yellow
    exit 1
}
if (-not (Test-Path $CaptionModel)) {
    Write-Host "错误：未找到 Caption 权重 $CaptionModel" -ForegroundColor Red
    Write-Host "请先下载 OmniParser 权重到 $OmniRoot\weights\" -ForegroundColor Yellow
    exit 1
}

# 切换到项目根目录
cd $ProjectRoot

# 启动参数
$ServerArgs = @(
    "-m", "src.app.services.omniparser.omniparser_server",
    "--omniparser-root", "$OmniRoot",
    "--som-model-path", "$SomModel",
    "--caption-model-path", "$CaptionModel",
    "--device", "cuda",
    "--box-threshold", "0.05",
    "--host", "127.0.0.1",
    "--port", "8000"
)

# 尝试用 conda run 启动（不需要先 activate）
$CondaEnv = "omni"
try {
    $condaInfo = conda info --envs 2>$null
    if ($LASTEXITCODE -eq 0 -and $condaInfo -match "^$CondaEnv\s+") {
        Write-Host "检测到 conda 环境 '$CondaEnv'，将用该环境启动服务" -ForegroundColor Green
        Write-Host "启动 OmniParser 服务..." -ForegroundColor Cyan
        Write-Host "地址: http://127.0.0.1:8000" -ForegroundColor Cyan
        conda run -n $CondaEnv --no-capture-output python @ServerArgs
    } else {
        throw "未找到环境"
    }
} catch {
    Write-Host "未能找到 conda 环境 '$CondaEnv'，将使用当前 Python 环境" -ForegroundColor Yellow
    Write-Host "如果依赖缺失，请先执行：" -ForegroundColor Yellow
    Write-Host "  conda create -n $CondaEnv python=3.12" -ForegroundColor Yellow
    Write-Host "  conda activate $CondaEnv" -ForegroundColor Yellow
    Write-Host "  pip install -r OmniParser\OmniParser-master\requirements.txt" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "启动 OmniParser 服务..." -ForegroundColor Cyan
    Write-Host "地址: http://127.0.0.1:8000" -ForegroundColor Cyan
    python @ServerArgs
}
