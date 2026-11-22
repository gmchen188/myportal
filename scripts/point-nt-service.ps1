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
    [string]$AppDirectory = "C:\Users\gmche\Work\networktopology\.next-build\standalone"
)
$ErrorActionPreference = "Stop"

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
