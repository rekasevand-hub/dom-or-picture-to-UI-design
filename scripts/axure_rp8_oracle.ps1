# 一次跑完两个探针：m3_native.rp（最小文档，scripts/axure_rp8_gen.py）
# 与 m9_ctl.rp（接线端到端，scripts/axure_rp8_wired.py，含圆 / 按钮 / 输入框）。
#
# 用法（会 kill AxureRP8 进程，先存盘退出）：
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/axure_rp8_oracle.ps1
#
# 看打印，别看退出码：每个探针会打出 RESULT=OK files=N / OUTPUT=<目录>，或某个 RESULT=NO_*。
param(
  [string]$Repo = (Split-Path -Parent $PSScriptRoot),
  [string]$Publish = (Join-Path $PSScriptRoot "axure_publish_html.ps1")
)
$ErrorActionPreference = "Continue"
$targets = @(
  @{ Path = (Join-Path $Repo "output\_axure_proto\m3_native.rp"); Tag = "m3native" },
  @{ Path = (Join-Path $Repo "output\_axure_proto\m9_ctl.rp");     Tag = "m9ctl" }
)
foreach ($t in $targets) {
  Write-Output ("=== {0}  ->  tag {1} ===" -f $t.Path, $t.Tag)
  if (-not (Test-Path $t.Path)) { Write-Output ("MISSING " + $t.Path); continue }
  & powershell -NoProfile -ExecutionPolicy Bypass -File $Publish -Path $t.Path -Tag $t.Tag
  Write-Output ""
}
Write-Output "=== done"