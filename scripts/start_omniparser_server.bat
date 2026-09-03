@echo off
chcp 65001 >nul
setlocal

set "PROJECT_ROOT=%~dp0.."
cd /d "%PROJECT_ROOT%"

set "OMNI_ROOT=%PROJECT_ROOT%\OmniParser\OmniParser-master"
set "SOM_MODEL=%OMNI_ROOT%\weights\icon_detect\model.pt"
set "CAPTION_MODEL=%OMNI_ROOT%\weights\icon_caption_florence"

if not exist "%SOM_MODEL%" (
    echo 错误：未找到 YOLO 权重 %SOM_MODEL%
    echo 请先下载 OmniParser 权重到 %OMNI_ROOT%\weights\
    exit /b 1
)

if not exist "%CAPTION_MODEL%" (
    echo 错误：未找到 Caption 权重 %CAPTION_MODEL%
    echo 请先下载 OmniParser 权重到 %OMNI_ROOT%\weights\
    exit /b 1
)

set "CONDA_ENV=omni"
set "SERVER_ARGS=-m src.app.services.omniparser.omniparser_server --omniparser-root "%OMNI_ROOT%" --som-model-path "%SOM_MODEL%" --caption-model-path "%CAPTION_MODEL%" --device cuda --box-threshold 0.05 --host 127.0.0.1 --port 8000"

conda info --envs 2>nul | findstr /B "%CONDA_ENV% " >nul
if %errorlevel% == 0 (
    echo 检测到 conda 环境 '%CONDA_ENV%'，将用该环境启动服务
    echo 启动 OmniParser 服务...
    echo 地址: http://127.0.0.1:8000
    conda run -n %CONDA_ENV% --no-capture-output python %SERVER_ARGS%
) else (
    echo 未能找到 conda 环境 '%CONDA_ENV%'，将使用当前 Python 环境
    echo 如果依赖缺失，请先执行：
    echo   conda create -n %CONDA_ENV% python=3.12
    echo   conda activate %CONDA_ENV%
    echo   pip install -r OmniParser\OmniParser-master\requirements.txt
    echo.
    echo 启动 OmniParser 服务...
    echo 地址: http://127.0.0.1:8000
    python %SERVER_ARGS%
)
