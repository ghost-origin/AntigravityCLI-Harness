param(
    [int]$Port = 0,
    [double]$WidthRatio = 0,
    [string]$ConversationId = '',
    [string]$BrainDir = '',
    [string]$StateFile = '',
    [int]$ParentPid = 0,
    [string]$PythonExe = '',
    [Alias('NoResizeTerminal')]
    [switch]$NoDock,
    [switch]$NoClipboard,
    [switch]$NoBrowser,
    [switch]$Stop
)

$ErrorActionPreference = 'Stop'
$sidebarDir = $PSScriptRoot
$repoRoot = Split-Path (Split-Path $sidebarDir -Parent) -Parent

$cfgLoader = Join-Path $repoRoot 'Config\load-config.ps1'
$harnessCfg = @{}
if (Test-Path $cfgLoader) {
    . $cfgLoader
    $harnessCfg = Get-HarnessConfig -RepoRoot $repoRoot
}
function CfgVal([string]$sec, [string]$key, [string]$def) {
    if (Get-Command Get-HarnessConfigValue -ErrorAction SilentlyContinue) {
        return Get-HarnessConfigValue -Config $harnessCfg -Section $sec -Key $key -Default $def
    }
    return $def
}

if (-not $StateFile) {
    $StateFile = CfgVal 'sidebar' 'state_file' (Join-Path $repoRoot 'tmp\sidebar_state.json')
}
$dockRegDir = CfgVal 'sidebar' 'dock_registry_dir' (Join-Path $repoRoot 'tmp\sidebar_docks')

function Invoke-LocalPost([string]$Url, [string]$JsonBody = '{}') {
    $req = [System.Net.HttpWebRequest]::Create($Url)
    $req.Method = 'POST'
    $req.Timeout = 2500
    $req.Proxy = [System.Net.GlobalProxySelection]::GetEmptyWebProxy()
    $req.ContentType = 'application/json; charset=utf-8'
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($JsonBody)
    $req.ContentLength = $bytes.Length
    $stream = $req.GetRequestStream()
    $stream.Write($bytes, 0, $bytes.Length)
    $stream.Close()
    $resp = $req.GetResponse()
    $resp.Close()
}

function Test-LocalHealth([string]$BaseUrl) {
    try {
        $req = [System.Net.HttpWebRequest]::Create($BaseUrl.TrimEnd('/') + '/api/health')
        $req.Method = 'GET'
        $req.Timeout = 1200
        $req.Proxy = [System.Net.GlobalProxySelection]::GetEmptyWebProxy()
        $resp = $req.GetResponse()
        $ok = ($resp.StatusCode -eq 200)
        $resp.Close()
        return $ok
    } catch {
        return $false
    }
}

if ($Stop) {
    if (Test-Path $StateFile) {
        try {
            $st = Get-Content -Path $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($st.url) {
                try { Invoke-LocalPost ($st.url.TrimEnd('/') + '/api/shutdown') '{}' } catch {}
            }
            if ($st.pid) {
                Start-Sleep -Milliseconds 200
                Stop-Process -Id ([int]$st.pid) -Force -ErrorAction SilentlyContinue
            }
        } catch {}
        Remove-Item -Path $StateFile -Force -ErrorAction SilentlyContinue
    }
    exit 0
}

if ($WidthRatio -le 0) {
    $cfgRatioStr = CfgVal 'sidebar' 'width_ratio' '0.38'
    [double]$parsedCfg = 0.38
    if ([double]::TryParse($cfgRatioStr, [ref]$parsedCfg)) { $WidthRatio = $parsedCfg } else { $WidthRatio = 0.38 }
}
if ($env:AGY_SIDEBAR_WIDTH_RATIO) {
    [double]$parsedRatio = 0
    if ([double]::TryParse($env:AGY_SIDEBAR_WIDTH_RATIO, [ref]$parsedRatio)) {
        $WidthRatio = $parsedRatio
    }
}
if ($WidthRatio -lt 0.25) { $WidthRatio = 0.25 }
if ($WidthRatio -gt 0.55) { $WidthRatio = 0.55 }
if ($env:AGY_SIDEBAR_NO_DOCK -eq '1') { $NoDock = $true }

function Resolve-PythonBin {
    if ($PythonExe -and (Test-Path $PythonExe)) { return $PythonExe }
    if ($env:AGY_HARNESS_PYTHON -and (Test-Path $env:AGY_HARNESS_PYTHON)) { return $env:AGY_HARNESS_PYTHON }
    $cfgPy = CfgVal 'executables' 'python_exe' ''
    if ($cfgPy -and (Test-Path $cfgPy)) { return $cfgPy }
    foreach ($name in @('python', 'python3')) {
        $cmd = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cmd -and $cmd.Source -and ($cmd.Source -notmatch 'WindowsApps\\python')) {
            return $cmd.Source
        }
    }
    return ''
}

function Resolve-BrowserBin {
    if ($env:AGY_SIDEBAR_BROWSER -and (Test-Path $env:AGY_SIDEBAR_BROWSER)) {
        return $env:AGY_SIDEBAR_BROWSER
    }
    $cfgBr = CfgVal 'executables' 'browser_exe' ''
    if ($cfgBr -and (Test-Path $cfgBr)) { return $cfgBr }
    $candidates = @(
        "$env:ProgramFiles (x86)\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
        "$env:LocalAppData\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "$env:ProgramFiles (x86)\Google\Chrome\Application\chrome.exe"
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { return $c }
    }
    return ''
}

$pyBin = Resolve-PythonBin
if (-not $pyBin) {
    Write-Error 'Python 3 not found. Set executables.python_exe in Config\harness.config or $env:AGY_HARNESS_PYTHON.'
    exit 1
}

$vendorDir = CfgVal 'sidebar' 'vendor_dir' (Join-Path $sidebarDir 'vendor')
$katexCheck = Join-Path $vendorDir 'katex\katex.min.js'
if (-not (Test-Path $katexCheck)) {
    Write-Error "Missing vendor assets ($katexCheck). Run scripts\sidebar\fetch-vendor.ps1 first."
    exit 1
}

$winFindCode = @'
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public static class AgyWinFinder {
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr hWnd, StringBuilder sb, int n);

    public static HashSet<long> SnapshotChromeWindows() {
        var set = new HashSet<long>();
        EnumWindows((h, l) => {
            if (!IsWindowVisible(h)) return true;
            var cls = new StringBuilder(64);
            GetClassName(h, cls, 64);
            if (cls.ToString() == "Chrome_WidgetWin_1") {
                set.Add(h.ToInt64());
            }
            return true;
        }, IntPtr.Zero);
        return set;
    }

    public static long FindNewSidebarWindow(uint preferredPid, HashSet<long> before) {
        long found = 0;
        EnumWindows((h, l) => {
            if (!IsWindowVisible(h)) return true;
            var cls = new StringBuilder(64);
            GetClassName(h, cls, 64);
            if (cls.ToString() != "Chrome_WidgetWin_1") return true;
            RECT r;
            if (!GetWindowRect(h, out r) || (r.Right - r.Left) < 120 || (r.Bottom - r.Top) < 120) return true;
            uint pid = 0;
            GetWindowThreadProcessId(h, out pid);
            long id = h.ToInt64();
            if (pid == preferredPid || !before.Contains(id)) {
                found = id;
                return false;
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }
}
'@

if (-not ('AgyWinFinder' -as [type])) {
    Add-Type -TypeDefinition $winFindCode -ErrorAction SilentlyContinue
}

$termHwnd = [IntPtr]::Zero
$beforeChrome = $null
if ('AgyWinFinder' -as [type]) {
    try {
        $termHwnd = [AgyWinFinder]::GetForegroundWindow()
        $beforeChrome = [AgyWinFinder]::SnapshotChromeWindows()
    } catch {}
}

# Reuse existing sidebar if this Windows Terminal window already has one docked
if ((-not $NoDock) -and (-not $NoBrowser) -and ($termHwnd -ne [IntPtr]::Zero)) {
    $dockRegFile = Join-Path $dockRegDir ("dock_$($termHwnd.ToInt64()).json")
    if (Test-Path $dockRegFile) {
        try {
            $existing = Get-Content -Path $dockRegFile -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($existing -and $existing.url -and (Test-LocalHealth ([string]$existing.url))) {
                $selId = if ($ConversationId) { $ConversationId } else { 'auto' }
                try {
                    $selBody = (@{ conv_id = $selId } | ConvertTo-Json -Compress)
                    Invoke-LocalPost (([string]$existing.url).TrimEnd('/') + '/api/select') $selBody
                } catch {}
                Write-Output ('REUSED:' + [string]$existing.url)
                exit 0
            }
        } catch {}
        Remove-Item -Path $dockRegFile -Force -ErrorAction SilentlyContinue
    }
}

$stateDir = Split-Path $StateFile -Parent
if ($stateDir -and -not (Test-Path $stateDir)) {
    New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
}
Remove-Item -Path $StateFile -Force -ErrorAction SilentlyContinue

$serverScript = CfgVal 'sidebar' 'server_script' (Join-Path $sidebarDir 'sidebar_server.py')
$pyArgs = @(
    "`"$serverScript`"",
    '--port', $Port,
    '--state-file', "`"$StateFile`""
)
if ($ConversationId) { $pyArgs += @('--conversation-id', "`"$ConversationId`"") }
if ($BrainDir) { $pyArgs += @('--brain-dir', "`"$BrainDir`"") }
if ($ParentPid -gt 0) { $pyArgs += @('--parent-pid', $ParentPid) }
if ($NoClipboard) { $pyArgs += '--no-clipboard' }

Start-Process -FilePath $pyBin -ArgumentList ($pyArgs -join ' ') -WindowStyle Hidden | Out-Null

$stateObj = $null
for ($i = 0; $i -lt 40; $i++) {
    if (Test-Path $StateFile) {
        try {
            $stateObj = Get-Content -Path $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($stateObj -and $stateObj.url) { break }
        } catch {}
    }
    Start-Sleep -Milliseconds 100
}

if (-not $stateObj -or -not $stateObj.url) {
    Write-Error 'Failed to start sidebar_server.py.'
    exit 1
}

if (-not $NoBrowser) {
    $browser = Resolve-BrowserBin
    if (-not $browser) {
        Write-Warning ("No Edge/Chrome found. Open manually: " + $stateObj.url)
    } else {
        $profileDir = CfgVal 'sidebar' 'edge_profile_dir' (Join-Path $repoRoot 'tmp\edge-sidebar-profile')
        New-Item -ItemType Directory -Path $profileDir -Force | Out-Null
        $bArgs = @(
            "--app=$($stateObj.url)",
            "--user-data-dir=`"$profileDir`"",
            '--proxy-bypass-list="127.0.0.1;localhost"',
            '--no-first-run',
            '--no-default-browser-check',
            '--disable-session-crashed-bubble'
        )
        $edgeProc = Start-Process -FilePath $browser -ArgumentList ($bArgs -join ' ') -PassThru
        if ((-not $NoDock) -and ($termHwnd -ne [IntPtr]::Zero) -and ('AgyWinFinder' -as [type])) {
            $edgeHwnd = [long]0
            $epId = if ($edgeProc) { [uint32]$edgeProc.Id } else { [uint32]0 }
            for ($w = 0; $w -lt 30; $w++) {
                Start-Sleep -Milliseconds 100
                $edgeHwnd = [AgyWinFinder]::FindNewSidebarWindow($epId, $beforeChrome)
                if ($edgeHwnd -ne 0) { break }
            }
            if ($edgeHwnd -ne 0) {
                $payload = (@{
                    term_hwnd = $termHwnd.ToInt64()
                    edge_hwnd = $edgeHwnd
                    width_ratio = $WidthRatio
                } | ConvertTo-Json -Compress)
                try {
                    Invoke-LocalPost ($stateObj.url.TrimEnd('/') + '/api/dock') $payload
                } catch {}
            }
        }
    }
}

Write-Output $stateObj.url
