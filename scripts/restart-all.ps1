<#
.SYNOPSIS
    重启 myPortal 与 networktopology 的服务，并让 networktopology 用新的构建产物。

.DESCRIPTION
    两件事一起做，**只弹一次 UAC**：

    1. **MyPortalWeb** —— `scripts/serve-static.mjs` 加了 `/networktopology`
       代理，不重启不生效（正式前端的「打开画布」按钮打不开画布）。
    2. **NetworkTopology** —— build 产物可能不在服务当前指向的目录。

    ## 为什么要合在一起

    每次提权都是一个 UAC 弹窗。弹两个 = 用户要点两次 = 容易误点「否」。

    ## 关于 networktopology 的构建产物

    构建时可以用 `NEXT_DIST_DIR=.next-build` 把产物放到 dev server 旁边
    （Windows 上 dev server 持有 `.next/standalone` 的句柄，
    `rm -rf .next` 会报 "Device or resource busy"）。

    这种情况下产物在 `.next-build/standalone`，而服务指向 `.next/standalone` ——
    **要么把服务指过去，要么用默认 distDir 重新 build**。
    本脚本用 `-NtDir` 参数选：

    - `-NtDir .next-build/standalone` → 改服务的 AppDirectory 指过去
    - 省略 → 用 `.next/standalone`（默认构建产物已经在那里）

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/restart-all.ps1
    powershell -ExecutionPolicy Bypass -File scripts/restart-all.ps1 -NtDir .next-build/standalone
#>
[CmdletBinding()]
param(
    [string]$NtDir = "",
    [switch]$Status
)
$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$Known = @("MyPortalBackend", "MyPortalWeb", "MyPortalDemo", "NetworkTopology")

function Write-Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "    [OK] $m" -ForegroundColor Green }

if ($Status) {
    Get-Service -Name $Known -ErrorAction SilentlyContinue |
        Select-Object Name, Status, StartType |
        Format-Table -AutoSize | Out-String | Write-Host
    return
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "需要管理员权限（服务以 LocalSystem 运行）—— 正在请求提权…" -ForegroundColor Yellow
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = "powershell.exe"
        $psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" +
            $(if ($NtDir) { " -NtDir `"$NtDir`"" } else { "" })
        $psi.Verb = "runas"
        $psi.UseShellExecute = $true
        $proc = [System.Diagnostics.Process]::Start($psi)
        $proc.WaitForExit()
        exit $proc.ExitCode
    } catch {
        Write-Host "提权被拒绝或失败：$($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}

# ── NetworkTopology：必要时改 AppDirectory ────────────────────────────────
if ($NtDir) {
    Write-Step "把 NetworkTopology 指向 $NtDir"
    $nt = "C:\Users\gmche\Work\networktopology"
    $abs = if ([System.IO.Path]::IsPathRooted($NtDir)) { $NtDir } else { Join-Path $nt $NtDir }
    if (-not (Test-Path (Join-Path $abs "server.js"))) {
        Write-Host "    [!] 那里没有 server.js —— 路径不对" -ForegroundColor Red
        exit 1
    }
    $key = "HKLM:\SYSTEM\CurrentControlSet\Services\NetworkTopology\Parameters"
    # 注册表直写：nssm set 的参数含空格时会被 cmd.exe 拆开
    Set-ItemProperty -Path $key -Name "Application" -Value "C:\Program Files\nodejs\node.exe" -Type String
    Set-ItemProperty -Path $key -Name "AppParameters" -Value "server.js" -Type String
    Set-ItemProperty -Path $key -Name "AppDirectory" -Value $abs -Type String
    Write-Ok "注册表已写：$abs"
}

# ── 重启 ─────────────────────────────────────────────────────────────────
# MyPortalBackend 也要在列里 —— **后台改了代码必须重启才生效**。
# （曾经只重启前端与画布，结果新端点 404，排查半天才发现是后端没重启。）
foreach ($name in @("MyPortalBackend", "MyPortalWeb", "NetworkTopology")) {
    Write-Step "重启 $name"
    try {
        Restart-Service -Name $name -Force -ErrorAction Stop
        Start-Sleep -Seconds 4
        $s = Get-Service -Name $name
        Write-Ok "$name → $($s.Status)"
    } catch {
        Write-Host "    [!] $name 重启失败：$($_.Exception.Message)" -ForegroundColor Yellow
    }
}

Write-Step "端口检查"
foreach ($port in @(9102, 5174, 6010)) {
    $up = Test-NetConnection -ComputerName 127.0.0.1 -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue
    Write-Host "    $port : $(if ($up) { '在用' } else { '不通' })" -ForegroundColor $(if ($up) { "Green" } else { "Yellow" })
}
