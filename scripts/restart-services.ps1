<#
.SYNOPSIS
    重启 myPortal / networktopology 的 Windows 服务。

.DESCRIPTION
    服务以 **LocalSystem** 运行 —— 这意味着**普通用户 stop/start 会被拒**
    （`sc stop` 报 `Access is denied`，因为 OpenService 需要管理员权限）。

    所以每次改代码后要重启后端，都得提权。这个脚本把提权封装好，
    不用记命令。

    **会弹 UAC 确认框** —— 点「是」即可。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/restart-services.ps1
    powershell -ExecutionPolicy Bypass -File scripts/restart-services.ps1 -Service MyPortalBackend
    powershell -ExecutionPolicy Bypass -File scripts/restart-services.ps1 -Status
#>
[CmdletBinding()]
param(
    # 只重启指定服务（不指定则全部）
    [string]$Service,
    # 只看状态，不重启
    [switch]$Status
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$Known = @("MyPortalBackend", "MyPortalWeb", "MyPortalDemo", "NetworkTopology")

function Write-Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "    [OK] $m" -ForegroundColor Green }
function Write-Warn2($m){ Write-Host "    [!]  $m" -ForegroundColor Yellow }

# ── 只看状态 ────────────────────────────────────────────────────────────────
if ($Status) {
    Write-Step "服务状态"
    Get-Service -Name $Known -ErrorAction SilentlyContinue |
        Select-Object Name, Status, StartType |
        Format-Table -AutoSize | Out-String | Write-Host
    return
}

# ── 提权 ────────────────────────────────────────────────────────────────────
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "需要管理员权限才能停止服务（服务以 LocalSystem 运行）—— 正在请求提权…" -ForegroundColor Yellow
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = "powershell.exe"
        $psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" +
            $(if ($Service) { " -Service $Service" } else { "" })
        $psi.Verb = "runas"
        $psi.UseShellExecute = $true
        $proc = [System.Diagnostics.Process]::Start($psi)
        $proc.WaitForExit()
        exit $proc.ExitCode
    } catch {
        Write-Host ""
        Write-Host "提权被拒绝或失败。" -ForegroundColor Red
        Write-Host "请右键以管理员身份运行 PowerShell，再执行：" -ForegroundColor Yellow
        Write-Host "  & `"$PSCommandPath`"" -ForegroundColor White
        exit 1
    }
}

# ── 实际重启 ────────────────────────────────────────────────────────────────
$targets = if ($Service) { @($Service) } else { $Known }

foreach ($name in $targets) {
    $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
    if (-not $svc) {
        Write-Warn2 "$name 不存在，跳过"
        continue
    }

    Write-Step "重启 $name"

    # 先停 —— 超时了就直接杀（服务可能卡在停止中）
    $svc | Stop-Service -Force -ErrorAction SilentlyContinue
    $waited = 0
    while ($svc.Status -ne "Stopped" -and $waited -lt 15) {
        Start-Sleep -Seconds 1
        $svc.Refresh()
        $waited++
    }
    if ($svc.Status -ne "Stopped") {
        Write-Warn2 "停止超时（${waited}s），强制结束进程"
        # nssm 的子进程
        $nssm = Get-CimInstance Win32_Process -Filter "Name='nssm.exe'" -ErrorAction SilentlyContinue
        $svcPid = (Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
                   Where-Object { $_.OwningProcess -and $svc.Name } |
                   Select-Object -First 1 -ExpandProperty OwningProcess)
        if ($svcPid) {
            Stop-Process -Id $svcPid -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 2
    }

    Start-Service -Name $name
    Start-Sleep -Seconds 3
    $svc.Refresh()
    if ($svc.Status -eq "Running") {
        Write-Ok "$name 已重启"
    } else {
        Write-Warn2 "$name 状态: $($svc.Status)"
    }
}

Write-Host ""
Write-Step "重启完成"
Get-Service -Name $targets -ErrorAction SilentlyContinue |
    Select-Object Name, Status, StartType |
    Format-Table -AutoSize | Out-String | Write-Host
