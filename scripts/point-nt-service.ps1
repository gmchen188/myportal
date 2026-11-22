<#
.SYNOPSIS
    把 NetworkTopology 服务指向新的构建产物目录。

.DESCRIPTION
    构建产物在 `.next-build`（用 NEXT_DIST_DIR 构建，避免与 dev server 抢 `.next`），
    所以服务的 AppDirectory 要跟着改。

    **会弹 UAC 确认框** —— 点「是」即可。

    为什么不用 `nssm set`：nssm 的参数里含空格时会被 cmd.exe 拆开，
    结果参数变空串、服务一起来就退出。配置直接写注册表没有这个问题
    （见 install-services.ps1 的说明）。
#>
[CmdletBinding()]
param(
    [string]$Service = "NetworkTopology",
    [string]$AppDirectory = "C:\Users\gmche\Work\networktopology\.next-build\standalone",
    # 只把构建产物摆到服务已经指向的目录里，不改注册表。
    # 这一步**不需要管理员**——服务的 AppDirectory 本来就是 .next\standalone。
    [switch]$CopyOnly
)
$ErrorActionPreference = "Stop"
# 控制台按 UTF-8 输出 —— 否则中文提示是乱码（PS 5.1 默认按 ANSI 解码）
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

if ($CopyOnly) {
    # ── 只摆产物：不需要管理员 ────────────────────────────────────────
    #
    # 为什么能绕开「目录删不掉」：服务的 cwd 锁住了 .next\standalone，
    # 目录本身删不掉（Device or resource busy），但**往里写不受影响**。
    # 所以把 .next-build\standalone 的内容复制进去即可。
    #
    # 路径为什么自洽：server.js 里的 distDirRoot 是 ".next-build"，
    # 相对 standalone 目录解析 → .next\standalone\.next-build，
    # 而 standalone 产物里本来就有这个子目录 —— 复制后正好对上。
    $target = "C:\Users\gmche\Work\networktopology\.next\standalone"
    Write-Host "把构建产物复制到 $target" -ForegroundColor Cyan
    if (-not (Test-Path (Join-Path $AppDirectory "server.js"))) {
        Write-Host "  [!] $AppDirectory 里没有 server.js" -ForegroundColor Red
        exit 1
    }
    & robocopy $AppDirectory $target /E /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -gt 7) {
        Write-Host "  [!] robocopy 失败（$LASTEXITCODE）" -ForegroundColor Red
        exit 1
    }
    Write-Host "  [OK] 产物已就位（server.js: $(Test-Path (Join-Path $target 'server.js')))" -ForegroundColor Green
    Write-Host "  重启服务让服务加载新产物 —— 这一步需要管理员：" -ForegroundColor Yellow
    Write-Host "    powershell -ExecutionPolicy Bypass -File scripts/restart-all.ps1" -ForegroundColor DarkGray
    exit 0
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "需要管理员权限 —— 正在请求提权…" -ForegroundColor Yellow
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = "powershell.exe"
        $psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Service $Service -AppDirectory `"$AppDirectory`""
        $psi.Verb = "runas"
        $psi.UseShellExecute = $true
        $proc = [System.Diagnostics.Process]::Start($psi)
        $proc.WaitForExit()
        exit $proc.ExitCode
    } catch {
        Write-Host "提权失败：$($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}

$key = "HKLM:\SYSTEM\CurrentControlSet\Services\$Service\Parameters"
$app = "C:\Program Files\nodejs\node.exe"

Write-Host "==> 写注册表" -ForegroundColor Cyan
Set-ItemProperty -Path $key -Name "Application" -Value $app -Type String
Set-ItemProperty -Path $key -Name "AppParameters" -Value "server.js" -Type String
Set-ItemProperty -Path $key -Name "AppDirectory" -Value $AppDirectory -Type String

Write-Host "==> 重启服务" -ForegroundColor Cyan
Stop-Service -Name $Service -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Start-Service -Name $Service
Start-Sleep -Seconds 6

$svc = Get-Service -Name $Service
Write-Host "    状态: $($svc.Status)" -ForegroundColor Green
Write-Host "    目录: $AppDirectory" -ForegroundColor Gray
