# 真机 oracle 2 号：拉起 Axure，走 `Publish -> Generate HTML Files...`，把 .rp 发布成 HTML。
#
# 用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/axure_publish_html.ps1 -Path <rp> -Tag <tag>
#
# 产物：~\Documents\Axure\HTML\<Tag>\files\<page>\styles.css（解析好的控件样式，是
# "颜色 / 圆角 / 边框到底发出去没有"的唯一可信判据；离线"看起来对"不算数）。
#
# 行为与注意：
#   * 开头 / 结尾都 kill AxureRP8 进程（Axure 生成完会自己用 Chrome 打开预览页，那也会被关掉）。
#     **跑之前先存盘**：这台机器上未保存的 Axure 文档会被结束掉。
#   * 只认 UI Automation 的菜单项（`Publish` -> `Generate HTML Files...`），不模拟坐标点击。
#   * 打出 RESULT=OK / OUTPUT=<目录> 才算成功；别只看退出码。
#
# 本文件是 scripts/ 里的正式副本（%TEMP% 会被系统清掉，别把唯一的脚本放那里）。
param(
  [string]$AxureExe = "D:\Program File\Axure\Axure RP 8\AxureRP8.exe",
  [Parameter(Mandatory=$true)][string]$Path,
  [string]$Tag = "pub",
  [int]$TimeoutSec = 300,
  [int]$MinSec = 8
)
$ErrorActionPreference = "Continue"

# Close browser windows that Axure itself spawned after a publish (they are
# just the generated prototype open in Chrome, not anything the agent browses).
function Close-AxureBrowser {
  $procs = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'Documents\\Axure\\HTML' -and $_.CommandLine -notmatch '--type=' }
  foreach ($proc in $procs) { taskkill /PID $proc.ProcessId /T /F 2>&1 | Out-Null }
}
Close-AxureBrowser

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$work = Join-Path $env:TEMP "axpaint\run"
New-Item -ItemType Directory -Force -Path $work | Out-Null
$dest = Join-Path $work "$Tag.rp"
$out = Join-Path $env:USERPROFILE "Documents\Axure\HTML\$Tag"
Get-Process | Where-Object { $_.ProcessName -like "AxureRP8*" } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
if (Test-Path $out) { Remove-Item -LiteralPath $out -Recurse -Force -ErrorAction SilentlyContinue }
Copy-Item -LiteralPath $Path -Destination $dest -Force
$p = Start-Process -FilePath $AxureExe -ArgumentList "`"$dest`"" -PassThru
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $p.Id)
$ctCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::MenuItem)
$nameCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, "Publish")
$wsh = New-Object -ComObject WScript.Shell
$deadline = (Get-Date).AddSeconds($TimeoutSec)
$w = $null; $publish = $null
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 3
  $cand = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
  if (-not $cand -or $cand.Current.Name -notlike "*Axure RP 8*") { continue }
  $w = $cand
  $publish = $w.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $nameCond)
  if ($publish) { break }
}
if (-not $publish) { Write-Output "RESULT=NO_PUBLISH_MENU"; Get-Process -Id $p.Id -ErrorAction SilentlyContinue | Stop-Process -Force; exit 1 }
$gen = $null
for ($try = 1; $try -le 6 -and -not $gen; $try++) {
  $null = $wsh.AppActivate($p.Id)
  Start-Sleep -Milliseconds 700
  try { $publish.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern).Expand() } catch {}
  Start-Sleep -Milliseconds 1200
  $items = $publish.FindAll([System.Windows.Automation.TreeScope]::Descendants, $ctCond)
  foreach ($i in $items) { if ($i.Current.Name -eq "Generate HTML Files...") { $gen = $i } }
}
if (-not $gen) { Write-Output "RESULT=NO_MENU_ITEM"; Get-Process -Id $p.Id -ErrorAction SilentlyContinue | Stop-Process -Force; exit 1 }
$gen.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
$dlg = $null
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline -and -not $dlg) {
  Start-Sleep -Seconds 2
  $dlg = $w.FindFirst([System.Windows.Automation.TreeScope]::Descendants, (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Window)))
}
if (-not $dlg) { Write-Output "RESULT=NO_DIALOG"; Get-Process -Id $p.Id -ErrorAction SilentlyContinue | Stop-Process -Force; exit 1 }
$ok = $dlg.FindFirst([System.Windows.Automation.TreeScope]::Subtree, (New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, "okButton")))
$ok.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
$t0 = Get-Date
$deadline = (Get-Date).AddSeconds($TimeoutSec)
$stable = 0; $last = ""
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 3
  $elapsed = ((Get-Date) - $t0).TotalSeconds
  $files = Get-ChildItem $out -Recurse -File -ErrorAction SilentlyContinue
  $sig = "{0}:{1}" -f $files.Count, (($files | Measure-Object -Property Length -Sum).Sum)
  if ($elapsed -ge $MinSec -and $sig -eq $last -and $files.Count -gt 0) { $stable++ } else { $stable = 0 }
  $last = $sig
  if ($stable -ge 2) { break }
}
Close-AxureBrowser
$files = Get-ChildItem $out -Recurse -File -ErrorAction SilentlyContinue
Get-Process | Where-Object { $_.ProcessName -like "AxureRP8*" } | Stop-Process -Force -ErrorAction SilentlyContinue
Write-Output ("RESULT=OK files=" + $files.Count)
Write-Output "OUTPUT=$out"
