<#
.SYNOPSIS
    把 myPortal + networktopology 注册成 Windows 服务（开机自启、崩溃自动重启）。

.DESCRIPTION
    笔记本当服务器 —— 服务不能依赖开发会话。

    四个服务：

    | 服务名            | 端口 | 内容                                   |
    |-------------------|------|----------------------------------------|
    | MyPortalBackend   | 9102 | FastAPI 后台（真后台、真数据）          |
    | MyPortalWeb       | 5174 | 正式前端 production build + /api 代理  |
    | MyPortalDemo      | 6012 | demo 静态站                            |
    | NetworkTopology   | 6010 | 画布（Next standalone）+ /portal 同源入口 |

    ## 三条关键设计

    **1. 密钥不进服务参数。**
    nssm 的参数会出现在 `sc qc` 的输出里，任何本地用户都能看到。
    FortiSIEM 的 Client Secret、JWT_SECRET 都不该出现在那里。

    - 后台：从 `backend/.env` 读（app/__init__.py 用绝对路径加载，与 CWD 无关）
    - 画布：从 `.next/standalone/.env.local` 读

    **2. 正式前端用 production build，不用 vite dev。**
    vite dev 是开发服务器 —— watch 文件、重编译、开 HMR。做成开机自启
    服务，机器一开就占 CPU 编译，半夜有人改个文件还会重启。对「当服务器」
    这个场景是错的。build 产物是静态文件，直接发就行。

    **3. 配置走注册表直写，不用 `nssm set`。**
    `nssm set SVC AppParameters $args` 里值里的空格会被 cmd.exe 拆成多个
    参数 —— 结果 AppParameters 变空串、AppDirectory 变成 executable 所在
    目录，服务一起来就退出，而且日志文件都不生成。nssm 的配置本来就全在
    `HKLM:\SYSTEM\CurrentControlSet\Services\<Name>\Parameters`，直接写
    注册表就没有引号解析问题。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/install-services.ps1
    powershell -ExecutionPolicy Bypass -File scripts/install-services.ps1 -Uninstall
    powershell -ExecutionPolicy Bypass -File scripts/install-services.ps1 -WhatIfOnly
#>
[CmdletBinding()]
param(
    [switch]$Uninstall,
    [switch]$WhatIfOnly
)

# ── 自提升 ────────────────────────────────────────────────────────────────
# 写 `HKLM:\SYSTEM\CurrentControlSet\Services\*\Parameters` 需要管理员。
# 非管理员时直接跑，注册表写入会全部报「不允许所请求的注册表访问权」，
# 而且因为 nssm install 本身不要求管理员，服务会「装上了但起不来」——
# 表现为：SCM 里有服务，状态 Stopped，日志文件都不生成。
#
# 检测到不是管理员就弹 UAC 重新以管理员身份跑自己。
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "需要管理员权限 —— 正在请求提权…" -ForegroundColor Yellow
    try {
        $extra = ""
        if ($Uninstall) { $extra += " -Uninstall" }
        if ($WhatIfOnly) { $extra += " -WhatIfOnly" }
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = "powershell.exe"
        $psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"$extra"
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

# 出错就停 —— 但 nssm 那几行要单独放宽（见注册段）
$ErrorActionPreference = "Stop"

# 控制台按 UTF-8 输出 —— 否则中文全是乱码
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$OutputEncoding = [System.Text.Encoding]::UTF8

# -- 路径 ---------------------------------------------------------------
$MyPortal    = "C:\Users\gmche\Work\myPortal"
$NetTopo     = "C:\Users\gmche\Work\networktopology"
$Node        = "C:\Program Files\nodejs\node.exe"
$Python      = "$MyPortal\backend\.venv\Scripts\python.exe"
$Nssm        = "C:\Windows\System32\nssm.exe"
$LogDir      = "C:\ProgramData\myportal-logs"

$Services = @(
    @{
        Name = "MyPortalBackend"
        Display = "myPortal Backend (FastAPI)"
        Desc = "myPortal 后台：资产/拓扑/事件/监控/FortiSIEM 连接器。端口 9102。"
        Exe = $Python
        Args = "-m uvicorn app.main:app --host 127.0.0.1 --port 9102 --log-level info"
        Dir = "$MyPortal\backend"
        Env = @{}
    },
    @{
        Name = "MyPortalWeb"
        Display = "myPortal Web (production build)"
        Desc = "myPortal 正式前端（production build），并把 /api、/health 代理到后台 9102。端口 5174。"
        Exe = $Node
        Args = 'scripts\serve-static.mjs --root "' + $MyPortal + '\web\dist" --port 5174 --api http://127.0.0.1:9102'
        Dir = $NetTopo
        Env = @{}
    },
    @{
        Name = "MyPortalDemo"
        Display = "myPortal Demo (static)"
        Desc = "myPortal 演示静态站。端口 6012。"
        Exe = $Node
        Args = "scripts\serve-myportal.mjs 6012 $MyPortal\demo"
        Dir = $NetTopo
        Env = @{}
    },
    @{
        Name = "NetworkTopology"
        Display = "networktopology Canvas"
        Desc = "AI 网络拓扑画布（Next standalone），并提供同源 /portal 入口。端口 6010。"
        Exe = $Node
        Args = "server.js"
        Dir = "$NetTopo\.next\standalone"
        Env = @{
            PORT = "6010"
            HOSTNAME = "127.0.0.1"
            NODE_ENV = "production"
            NEXT_PUBLIC_BASE_PATH = "/networktopology"
            MYPORTAL_ORIGIN = "http://127.0.0.1:6012"
        }
    }
)

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "    [!]  $msg" -ForegroundColor Yellow }

# -- 卸载 ---------------------------------------------------------------
if ($Uninstall) {
    Write-Step "卸载服务"
    $ErrorActionPreference = "Continue"
    foreach ($s in $Services) {
        $existing = Get-Service -Name $s.Name -ErrorAction SilentlyContinue
        if ($existing) {
            & $Nssm stop $s.Name confirm 2>&1 | Out-Null
            & $Nssm remove $s.Name confirm 2>&1 | Out-Null
            Write-Ok "已移除 $($s.Name)"
        } else {
            Write-Warn2 "$($s.Name) 不存在，跳过"
        }
    }
    $ErrorActionPreference = "Stop"
    Write-Host ""
    Write-Host "日志目录保留在 $LogDir（如需清理请手动删除）。" -ForegroundColor DarkGray
    return
}

# -- 前置检查 -----------------------------------------------------------
Write-Step "前置检查"
foreach ($p in @($Nssm, $Node, $Python)) {
    if (-not (Test-Path $p)) {
        if ($p -like "*\.venv\*") {
            throw "缺少 $p —— 先建独立 venv（不要用工具链的 venv）：
    cd backend
    C:\Python314\python.exe -m venv .venv
    .venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
（服务以 LocalSystem 运行，没有 PYTHONPATH，依赖工具链的 venv 会报 No module named uvicorn）"
        }
        throw "缺少 $p"
    }
    Write-Ok "存在: $p"
}
foreach ($d in @("$MyPortal\backend", "$MyPortal\web\dist", "$MyPortal\demo",
                 "$NetTopo\.next\standalone", "$NetTopo\scripts")) {
    if (-not (Test-Path $d)) { throw "缺少目录 $d —— 先构建产物" }
    Write-Ok "存在: $d"
}
# 密钥文件必须在（服务启动时要读）
foreach ($f in @("$MyPortal\backend\.env", "$NetTopo\.next\standalone\.env.local")) {
    if (-not (Test-Path $f)) { throw "缺少密钥文件 $f" }
    Write-Ok "存在: $f"
}

if ($WhatIfOnly) {
    Write-Step "WhatIf —— 计划执行"
    foreach ($s in $Services) {
        Write-Host "  $($s.Name)  [$($s.Dir)]" -ForegroundColor White
        Write-Host "     $($s.Exe) $($s.Args)" -ForegroundColor DarkGray
    }
    return
}

# -- ACL：LocalSystem 要能读项目目录 ------------------------------------
# Windows 服务默认以 LocalSystem 运行，它对 C:\Users\<user>\ 没有读权限。
# 不授权的话服务启动就 Access Denied，日志里只有一行看不懂的错误。
#
# **只授权服务真正要读的那几个目录，不递归整个项目。**
#
# 试过 `icacls <项目根> /grant ... /T` —— 那会遍历 node_modules、.git、
# 几百 MB 的 .next，几万个文件，跑了 5 分钟还没结束，服务一个都没装上。
# 而且没必要：服务只读那几个具体目录。
Write-Step "授权 LocalSystem 读取项目目录"
foreach ($d in @(
    "$MyPortal\backend",
    "$MyPortal\web\dist",
    "$MyPortal\demo",
    "$NetTopo\scripts",
    "$NetTopo\.next\standalone"
)) {
    if (-not (Test-Path $d)) { continue }
    & icacls.exe $d /grant "NT AUTHORITY\SYSTEM:(OI)(CI)F" /T /Q /C | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "已授权: $d"
    } else {
        Write-Warn2 "授权失败（退出码 $LASTEXITCODE）: $d"
    }
}

# -- 日志目录 -----------------------------------------------------------
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
Write-Ok "日志目录: $LogDir"

# -- 注册服务 -----------------------------------------------------------
foreach ($s in $Services) {
    Write-Step "注册 $($s.Name)"

    # nssm 对「服务不存在」会往 stderr 写 "Can't open service!"，
    # 在 Stop 策略下 PowerShell 直接抛异常，脚本当场中断 ——
    # 明明只是要清一个不存在的服务，却把整个安装打断了。
    $ErrorActionPreference = "Continue"

    if (Get-Service -Name $s.Name -ErrorAction SilentlyContinue) {
        & $Nssm stop $s.Name confirm 2>&1 | Out-Null
        & $Nssm remove $s.Name confirm 2>&1 | Out-Null
        Write-Warn2 "已移除旧服务实例"
    }

    & $Nssm install $s.Name $s.Exe 2>&1 | Out-Null

    # -- 配置走注册表直写 -------------------------------------------
    $key = "HKLM:\SYSTEM\CurrentControlSet\Services\$($s.Name)\Parameters"

    # Application 必须是**裸路径，不能带引号**。
    #
    # 带引号 → nssm 把它当字面量 → CreateProcess() failed: 参数错误
    # （ERROR_INVALID_PARAMETER）。事件日志里就是这么写的：
    #   'Program "C:\Program Files\nodejs\node.exe" couldn't be launched.
    #    CreateProcess() failed: 参数错误。'
    # nssm 自己会处理路径里的空格。
    Set-ItemProperty -Path $key -Name "Application" -Value $s.Exe
    Set-ItemProperty -Path $key -Name "AppParameters" -Value $s.Args
    Set-ItemProperty -Path $key -Name "AppDirectory" -Value $s.Dir
    Set-ItemProperty -Path $key -Name "DisplayName" -Value $s.Display
    Set-ItemProperty -Path $key -Name "Description" -Value $s.Desc

    # 开机自启 + 崩溃自动重启
    Set-ItemProperty -Path $key -Name "Start" -Value "SERVICE_AUTO_START"
    Set-ItemProperty -Path $key -Name "AppExit" -Value "Default Restart"

    # **数值项必须是 REG_DWORD** —— Set-ItemProperty 写出来的是 REG_SZ，
    # nssm 会忽略并警告：
    #   'The registry value AppThrottle ... was not of type REG_DWORD.
    #    The default time of 1500 milliseconds will be used.'
    # 删掉再重建，才能指定类型。
    foreach ($dword in @(
        @{ Name = "AppRestartDelay"; Value = 5000 },
        @{ Name = "AppThrottle";      Value = 1500 }
    )) {
        Remove-ItemProperty -Path $key -Name $dword.Name -ErrorAction SilentlyContinue
        New-ItemProperty -Path $key -Name $dword.Name -Value $dword.Value -PropertyType DWord -Force | Out-Null
    }

    # 日志 + 轮转（10MB）
    Set-ItemProperty -Path $key -Name "AppStdout" -Value "$LogDir\$($s.Name).out.log"
    Set-ItemProperty -Path $key -Name "AppStderr" -Value "$LogDir\$($s.Name).err.log"
    foreach ($dword in @(
        @{ Name = "AppRotateFiles";  Value = 1 },
        @{ Name = "AppRotateBytes"; Value = 10485760 }
    )) {
        Remove-ItemProperty -Path $key -Name $dword.Name -ErrorAction SilentlyContinue
        New-ItemProperty -Path $key -Name $dword.Name -Value $dword.Value -PropertyType DWord -Force | Out-Null
    }

    # 环境变量（不含密钥 —— 密钥走 .env）
    #
    # **AppEnvironmentExtra 必须是 REG_MULTI_SZ** —— 每个变量一行。
    # 写成 REG_SZ 的话 nssm 不认，子进程拿不到，服务会静默用默认值
    # （实测：PORT=6010 没传进去，Next 用了默认的 3000）。
    if ($s.Env.Count -gt 0) {
        $envLines = @()
        foreach ($k in $s.Env.Keys) { $envLines += "$k=$($s.Env[$k])" }
        Remove-ItemProperty -Path $key -Name "AppEnvironmentExtra" -ErrorAction SilentlyContinue
        New-ItemProperty -Path $key -Name "AppEnvironmentExtra" -Value $envLines `
            -PropertyType MultiString -Force | Out-Null
        Write-Ok "环境变量: $($s.Env.Keys -join ', ')"
    }

    # 身份：LocalSystem。
    # **只传用户名不给密码会「静默错误」** —— 服务用错身份跑，
    # 立即退出 1066 而没有明显报错。这里显式写全。
    Set-ItemProperty -Path $key -Name "ObjectName" -Value "LocalSystem"

    & $Nssm start $s.Name 2>&1 | Out-Null
    $ErrorActionPreference = "Stop"

    Start-Sleep -Seconds 3
    $st = (Get-Service -Name $s.Name -ErrorAction SilentlyContinue).Status
    if ($st -eq "Running") {
        Write-Ok "$($s.Name) 已启动"
    } else {
        Write-Warn2 "$($s.Name) 状态: $st —— 看日志 $LogDir\$($s.Name).err.log"
    }
}

Write-Host ""
Write-Host "完成。查看状态：" -ForegroundColor Cyan
foreach ($s in $Services) {
    Write-Host "  sc query $($s.Name)" -ForegroundColor DarkGray
}
