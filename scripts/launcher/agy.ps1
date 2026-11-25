$GeminiHarnessScripts = Split-Path $PSScriptRoot -Parent
$GeminiHarnessRepo = Split-Path $GeminiHarnessScripts -Parent
$GeminiHarnessCfgLoader = Join-Path $GeminiHarnessRepo 'Config\load-config.ps1'
if (Test-Path $GeminiHarnessCfgLoader) {
    . $GeminiHarnessCfgLoader
}

function agy-sidebar {
    param(
        [string]$ConversationId = '',
        [double]$WidthRatio = 0,
        [Alias('NoResizeTerminal')]
        [switch]$NoDock,
        [switch]$NoClipboard,
        [switch]$Stop
    )
    $cfg = if (Get-Command Get-HarnessConfig -ErrorAction SilentlyContinue) { Get-HarnessConfig -RepoRoot $GeminiHarnessRepo } else { @{} }
    $launcher = if (Get-Command Get-HarnessConfigValue -ErrorAction SilentlyContinue) {
        Get-HarnessConfigValue -Config $cfg -Section 'sidebar' -Key 'launcher_script' -Default (Join-Path $GeminiHarnessScripts 'sidebar\launch-sidebar.ps1')
    } else {
        Join-Path $GeminiHarnessScripts 'sidebar\launch-sidebar.ps1'
    }
    if (-not (Test-Path $launcher)) {
        Write-Error "Sidebar launcher not found: $launcher"
        return
    }
    $pass = @{}
    if ($ConversationId) { $pass['ConversationId'] = $ConversationId }
    if ($WidthRatio -gt 0) { $pass['WidthRatio'] = $WidthRatio }
    if ($NoDock) { $pass['NoDock'] = $true }
    if ($NoClipboard) { $pass['NoClipboard'] = $true }
    if ($Stop) { $pass['Stop'] = $true }
    & $launcher @pass
}

function agy {
    $cfg = if (Get-Command Get-HarnessConfig -ErrorAction SilentlyContinue) { Get-HarnessConfig -RepoRoot $GeminiHarnessRepo } else { @{} }
    $cfgAgy = if (Get-Command Get-HarnessConfigValue -ErrorAction SilentlyContinue) { Get-HarnessConfigValue -Config $cfg -Section 'executables' -Key 'agy_exe' -Default '' } else { '' }
    $exe = if ($env:AGY_EXE) { $env:AGY_EXE } elseif ($cfgAgy -and (Test-Path $cfgAgy)) { $cfgAgy } else {
        $cmd = Get-Command 'agy.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cmd) { $cmd.Source } else { '' }
    }
    if (-not $exe -or -not (Test-Path $exe)) {
        Write-Error 'agy.exe not found in PATH. Install Antigravity CLI, set executables.agy_exe in Config\harness.config, or set $env:AGY_EXE.'
        return
    }

    $watchdog = $null
    $watchdogScript = if (Get-Command Get-HarnessConfigValue -ErrorAction SilentlyContinue) {
        Get-HarnessConfigValue -Config $cfg -Section 'watchdog' -Key 'script' -Default (Join-Path $GeminiHarnessScripts 'watchdog\agy-watchdog.ps1')
    } else {
        Join-Path $GeminiHarnessScripts 'watchdog\agy-watchdog.ps1'
    }
    if (Test-Path $watchdogScript) {
        $watchdogArgLine = '-NoProfile -ExecutionPolicy Bypass -File "' + $watchdogScript + '" -WaitForNew'
        $watchdog = Start-Process -FilePath 'powershell.exe' -ArgumentList $watchdogArgLine -WindowStyle Hidden -PassThru
    }

    $resumeConvId = ''
    for ($i = 0; $i -lt $args.Count; $i++) {
        $tok = [string]$args[$i]
        if (($tok -eq '-r' -or $tok -eq '--resume' -or $tok -eq '--conversation') -and ($i + 1 -lt $args.Count)) {
            $resumeConvId = [string]$args[$i + 1]
            break
        } elseif ($tok -match '^(--resume|--conversation|-r)=(.+)$') {
            $resumeConvId = $Matches[2]
            break
        }
    }
    if ($resumeConvId -and $resumeConvId.Length -ge 8) {
        try { $Host.UI.RawUI.WindowTitle = 'agy [' + $resumeConvId.Substring(0, 8) + ']' } catch {}
    }

    $sidebarOwned = $false
    $sidebarStateFile = ''
    $sidebarLauncher = if (Get-Command Get-HarnessConfigValue -ErrorAction SilentlyContinue) {
        Get-HarnessConfigValue -Config $cfg -Section 'sidebar' -Key 'launcher_script' -Default (Join-Path $GeminiHarnessScripts 'sidebar\launch-sidebar.ps1')
    } else {
        Join-Path $GeminiHarnessScripts 'sidebar\launch-sidebar.ps1'
    }
    $tmpDir = if (Get-Command Get-HarnessConfigValue -ErrorAction SilentlyContinue) {
        Get-HarnessConfigValue -Config $cfg -Section 'paths' -Key 'tmp_dir' -Default (Join-Path $GeminiHarnessRepo 'tmp')
    } else {
        Join-Path $GeminiHarnessRepo 'tmp'
    }
    if (($env:AGY_SIDEBAR -ne '0') -and (Test-Path $sidebarLauncher)) {
        $sidebarStateFile = Join-Path $tmpDir ("sidebar_state_$PID.json")
        try {
            $sbParams = @{ StateFile = $sidebarStateFile; ParentPid = $PID }
            if ($resumeConvId) { $sbParams['ConversationId'] = $resumeConvId }
            $sbOut = (& $sidebarLauncher @sbParams | Out-String).Trim()
            if ($sbOut -and (-not $sbOut.StartsWith('REUSED:'))) {
                $sidebarOwned = $true
            }
        } catch {
            $sidebarStateFile = ''
        }
    }

    try {
        & $exe @args
    }
    finally {
        if ($sidebarOwned -and $sidebarStateFile -and (Test-Path $sidebarLauncher)) {
            try {
                & $sidebarLauncher -Stop -StateFile $sidebarStateFile | Out-Null
            } catch {}
        }
        if ($watchdog) {
            Stop-Process -Id $watchdog.Id -Force -ErrorAction SilentlyContinue
        }
    }
}
