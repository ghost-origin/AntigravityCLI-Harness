param(
    [string]$ConversationId = '',
    [string]$Reason = 'agent requested context compaction',
    [int]$CurrentTokens = 0,
    [string]$Command = '/compact',
    [string]$ResumePrompt = '',
    [int]$DelaySeconds = 2,
    [int]$EnterCount = 1,
    [int]$CharDelayMs = 0,
    [int]$CooldownSeconds = 120,
    [int]$WaitIdleTimeoutSeconds = 25,
    [int]$TargetProcessId = 0,
    [ValidateSet('auto', 'queue', 'direct')][string]$Mode = 'auto',
    [string]$RequestFile = '',
    [string]$LogDir = '',
    [string]$OutLog = '',
    [string]$StateFile = '',
    [switch]$AlreadyIdle,
    [switch]$Wait,
    [switch]$DryRun,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$scriptsRoot = Split-Path $PSScriptRoot -Parent
$repoRoot = Split-Path $scriptsRoot -Parent
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

if (-not $RequestFile) { $RequestFile = CfgVal 'compact' 'request_file' (Join-Path $repoRoot 'tmp\compact_request.json') }
if (-not $OutLog)      { $OutLog      = CfgVal 'compact' 'out_log' (Join-Path $repoRoot 'logs\auto_compact.log') }
if (-not $StateFile)   { $StateFile   = CfgVal 'compact' 'state_file' (Join-Path $repoRoot 'logs\auto_compact_state.json') }

$reqDir = Split-Path $RequestFile -Parent
if (-not (Test-Path $reqDir)) { New-Item -ItemType Directory -Path $reqDir -Force | Out-Null }

$reqId = 'cmp-' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '-' + (Get-Random -Minimum 1000 -Maximum 9999)
$brainDir = CfgVal 'antigravity' 'brain_dir' (Join-Path $env:USERPROFILE '.gemini\antigravity-cli\brain')
$transcriptPath = ''
if ($ConversationId) {
    $transcriptPath = Join-Path $brainDir ($ConversationId + '\.system_generated\logs\transcript.jsonl')
}

$effectiveLogDir = if ($LogDir) { $LogDir } else { CfgVal 'antigravity' 'cli_log_dir' (Join-Path $env:USERPROFILE '.gemini\antigravity-cli\log') }
$logFile = ''
$logOffset = -1
if (Test-Path $effectiveLogDir) {
    $latestLog = Get-ChildItem -Path $effectiveLogDir -Filter 'cli-*.log' -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($latestLog) {
        $logFile = $latestLog.FullName
        $logOffset = [int64]$latestLog.Length
    }
}

$payload = [ordered]@{
    request_id      = $reqId
    conversation_id = $ConversationId
    transcript_path = $transcriptPath
    log_file        = $logFile
    log_offset      = $logOffset
    command         = $Command
    resume_prompt   = $ResumePrompt
    reason          = $Reason
    current_tokens  = $CurrentTokens
    delay_seconds   = $DelaySeconds
    enter_count     = $EnterCount
    char_delay_ms   = $CharDelayMs
    created_at      = [DateTimeOffset]::UtcNow.ToString('o')
}
$payload | ConvertTo-Json -Depth 4 | Set-Content -Path $RequestFile -Encoding UTF8

# Detect whether agy-watchdog.ps1 is actively running
$watchdogPid = 0
$pidFile = CfgVal 'watchdog' 'pid_file' (Join-Path $repoRoot 'logs\watchdog.pid')
if (Test-Path $pidFile) {
    try {
        $pinfo = Get-Content -Path $pidFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($pinfo.pid) {
            $proc = Get-Process -Id ([int]$pinfo.pid) -ErrorAction SilentlyContinue
            if ($proc) { $watchdogPid = [int]$pinfo.pid }
        }
    } catch {}
}

$dispatch = $Mode
if ($Mode -eq 'auto') {
    if ($watchdogPid -gt 0 -and $TargetProcessId -le 0 -and -not $Wait) {
        $dispatch = 'queue'
    }
    else {
        $dispatch = 'direct'
    }
}

$workerPid = 0
if ($dispatch -eq 'direct') {
    $worker = Join-Path $PSScriptRoot 'auto-compact-worker.ps1'
    if (-not (Test-Path $worker)) {
        throw ('auto-compact-worker.ps1 not found at ' + $worker)
    }
    $argsList = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', $worker,
        '-RequestFile', $RequestFile,
        '-OutLog', $OutLog,
        '-StateFile', $StateFile,
        '-CooldownSeconds', $CooldownSeconds,
        '-WaitIdleTimeoutSeconds', $WaitIdleTimeoutSeconds
    )
    if ($LogDir)              { $argsList += @('-LogDir', $LogDir) }
    if ($TargetProcessId -gt 0) { $argsList += @('-TargetProcessId', $TargetProcessId) }
    if ($AlreadyIdle)         { $argsList += '-AlreadyIdle' }
    if ($DryRun)              { $argsList += '-DryRun' }
    if ($Force)               { $argsList += '-Force' }

    if ($Wait) {
        $wp = Start-Process -FilePath 'powershell.exe' -ArgumentList $argsList -WindowStyle Hidden -Wait -PassThru
        $workerPid = $wp.Id
    }
    else {
        $wp = Start-Process -FilePath 'powershell.exe' -ArgumentList $argsList -WindowStyle Hidden -PassThru
        $workerPid = $wp.Id
    }
}

$summary = [ordered]@{
    ok           = $true
    request_id   = $reqId
    dispatch     = $dispatch
    watchdog_pid = $watchdogPid
    worker_pid   = $workerPid
    request_file = $RequestFile
    command      = $Command
    dry_run      = [bool]$DryRun
}
$summary | ConvertTo-Json -Depth 3
