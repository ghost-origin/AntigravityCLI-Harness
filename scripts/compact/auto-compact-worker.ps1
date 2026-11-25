param(
    [string]$RequestFile = '',
    [string]$LogDir = '',
    [string]$OutLog = '',
    [string]$StateFile = '',
    [int]$CooldownSeconds = 120,
    [int]$WaitIdleTimeoutSeconds = 25,
    [int]$ResumeWaitTimeoutSeconds = 90,
    [int]$TargetProcessId = 0,
    [switch]$AlreadyIdle,
    [switch]$DryRun,
    [switch]$Force
)

$ErrorActionPreference = 'Continue'
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
if (-not $LogDir)      { $LogDir      = CfgVal 'antigravity' 'cli_log_dir' (Join-Path $env:USERPROFILE '.gemini\antigravity-cli\log') }
if (-not $OutLog)      { $OutLog      = CfgVal 'compact' 'out_log' (Join-Path $repoRoot 'logs\auto_compact.log') }
if (-not $StateFile)   { $StateFile   = CfgVal 'compact' 'state_file' (Join-Path $repoRoot 'logs\auto_compact_state.json') }

function Write-CompactLog([string]$msg) {
    $line = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $msg
    $dir = Split-Path $OutLog -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    Add-Content -Path $OutLog -Value $line -Encoding UTF8
    Write-Output $line
}

function Get-CheckpointCount([string]$transcriptPath) {
    if (-not $transcriptPath -or -not (Test-Path $transcriptPath)) { return 0 }
    try {
        $matches = Select-String -Path $transcriptPath -Pattern '"type"\s*:\s*"CHECKPOINT"' -ErrorAction SilentlyContinue
        if ($matches) { return @($matches).Count }
    } catch {}
    return 0
}

if (-not (Test-Path $RequestFile)) {
    Write-CompactLog ('no pending request file: ' + $RequestFile)
    exit 0
}

# Atomically claim request file so watchdog and worker never double-fire
$claimFile = $RequestFile + '.processing.' + $PID
try {
    Move-Item -Path $RequestFile -Destination $claimFile -Force -ErrorAction Stop
}
catch {
    Write-CompactLog ('request already claimed by another worker: ' + $_.Exception.Message)
    exit 0
}

$req = $null
try {
    $raw = Get-Content -Path $claimFile -Raw -Encoding UTF8
    $req = $raw | ConvertFrom-Json
}
catch {
    Write-CompactLog ('invalid request json: ' + $_.Exception.Message)
    Remove-Item -Path $claimFile -Force -ErrorAction SilentlyContinue
    exit 1
}
Remove-Item -Path $claimFile -Force -ErrorAction SilentlyContinue

$reqId      = if ($req.request_id)      { [string]$req.request_id }      else { 'req-' + (Get-Date -Format 'yyyyMMdd_HHmmss') }
$convId     = if ($req.conversation_id) { [string]$req.conversation_id } else { '' }
$cmdText    = if ($req.command)         { [string]$req.command }         else { '/compact' }
$resumeText = if ($req.resume_prompt)   { [string]$req.resume_prompt }   else { '' }
$delaySec   = if ($null -ne $req.delay_seconds) { [int]$req.delay_seconds } else { 2 }
$enterCount = if ($null -ne $req.enter_count)   { [int]$req.enter_count }   else { 1 }
$charDelay  = if ($null -ne $req.char_delay_ms) { [int]$req.char_delay_ms } else { 0 }
$transcript = if ($req.transcript_path) { [string]$req.transcript_path } else { '' }
$brainDir = CfgVal 'antigravity' 'brain_dir' (Join-Path $env:USERPROFILE '.gemini\antigravity-cli\brain')
if (-not $transcript -and $convId) {
    $transcript = Join-Path $brainDir ($convId + '\.system_generated\logs\transcript.jsonl')
}

# Cooldown check
if (-not $Force -and (Test-Path $StateFile)) {
    try {
        $st = Get-Content -Path $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($st.last_compact_at) {
            $lastDt = [DateTimeOffset]::Parse([string]$st.last_compact_at)
            $elapsed = ([DateTimeOffset]::UtcNow - $lastDt.ToUniversalTime()).TotalSeconds
            if ($elapsed -lt $CooldownSeconds) {
                $rem = [int][Math]::Ceiling($CooldownSeconds - $elapsed)
                Write-CompactLog ('skipped req=' + $reqId + ' reason=cooldown remaining=' + $rem + 's')
                exit 0
            }
        }
    } catch {}
}

# Wait until CLI turn finishes (ResponsePending cleared), unless already idle or custom target PID
if (-not $AlreadyIdle -and $TargetProcessId -le 0 -and (Test-Path $LogDir)) {
    $latestLog = $null
    if ($req.log_file -and (Test-Path ([string]$req.log_file))) {
        $latestLog = Get-Item ([string]$req.log_file) -ErrorAction SilentlyContinue
    }
    if (-not $latestLog) {
        $latestLog = Get-ChildItem -Path $LogDir -Filter 'cli-*.log' -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
    }
    if ($latestLog) {
        $curItemLen = (Get-Item $latestLog.FullName).Length
        if ($null -ne $req.log_offset -and [int64]$req.log_offset -ge 0 -and [int64]$req.log_offset -le $curItemLen) {
            $baselineLen = [int64]$req.log_offset
        }
        else {
            $baselineLen = $curItemLen
        }
        $deadline = (Get-Date).AddSeconds($WaitIdleTimeoutSeconds)
        $pattern = if ($convId) { 'Stream completed for ' + [regex]::Escape($convId) + ', clearing ResponsePending' } else { 'Stream completed for .*, clearing ResponsePending' }
        $idleSeen = $false
        while ((Get-Date) -lt $deadline) {
            try {
                $curLen = (Get-Item $latestLog.FullName).Length
                if ($curLen -gt $baselineLen) {
                    $fs = [System.IO.File]::Open($latestLog.FullName, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
                    try {
                        $fs.Seek($baselineLen, [System.IO.SeekOrigin]::Begin) | Out-Null
                        $sr = New-Object System.IO.StreamReader($fs)
                        $delta = $sr.ReadToEnd()
                        $baselineLen = $fs.Position
                    }
                    finally { $fs.Dispose() }
                    if ($delta -match $pattern) {
                        $idleSeen = $true
                        Write-CompactLog ('idle detected in ' + $latestLog.Name + ' for req=' + $reqId)
                        break
                    }
                }
            } catch {}
            Start-Sleep -Milliseconds 400
        }
        if (-not $idleSeen) {
            Write-CompactLog ('idle wait timed out after ' + $WaitIdleTimeoutSeconds + 's; proceeding req=' + $reqId)
        }
    }
}

if ($delaySec -gt 0) { Start-Sleep -Seconds $delaySec }

# Resolve target process
$pidToUse = $TargetProcessId
if ($pidToUse -le 0) {
    $target = Get-Process agy -ErrorAction SilentlyContinue | Sort-Object StartTime -Descending | Select-Object -First 1
    if (-not $target) {
        Write-CompactLog ('aborted req=' + $reqId + ' reason=no_agy_process')
        exit 1
    }
    $pidToUse = $target.Id
}

$beforeCp = Get-CheckpointCount $transcript

function Invoke-ConsoleInjector([int]$targetPid, [string]$textValue, [int]$enters, [int]$cDelay) {
    $injector = CfgVal 'compact' 'injector_script' (Join-Path $scriptsRoot 'injector\send-console-input.ps1')
    if (-not (Test-Path $injector)) {
        return $null
    }
    $b64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($textValue))
    $argStr = '-NoProfile -ExecutionPolicy Bypass -File "' + $injector + '" -ProcessId ' + $targetPid +
        ' -TextBase64 "' + $b64 + '" -EnterCount ' + $enters + ' -CharDelayMs ' + $cDelay
    return (Start-Process -FilePath 'powershell.exe' -ArgumentList $argStr -WindowStyle Hidden -Wait -PassThru)
}

if ($DryRun) {
    Write-CompactLog ('dry-run: would inject cmd="' + $cmdText + '" enters=' + $enterCount + ' pid=' + $pidToUse + ' req=' + $reqId + ' resume="' + $resumeText + '"')
}
else {
    $p = Invoke-ConsoleInjector -targetPid $pidToUse -textValue $cmdText -enters $enterCount -cDelay $charDelay
    if (-not $p) {
        Write-CompactLog ('aborted req=' + $reqId + ' reason=injector_not_found')
        exit 1
    }
    Write-CompactLog ('injected cmd="' + $cmdText + '" enters=' + $enterCount + ' pid=' + $pidToUse + ' exit=' + $p.ExitCode + ' req=' + $reqId)
}

# Persist state (avoid polluting default state during DryRun unless custom StateFile was provided)
$defaultState = CfgVal 'compact' 'state_file' (Join-Path $repoRoot 'logs\auto_compact_state.json')
if (-not $DryRun -or ($StateFile -ne $defaultState)) {
    $stDir = Split-Path $StateFile -Parent
    if (-not (Test-Path $stDir)) { New-Item -ItemType Directory -Path $stDir -Force | Out-Null }
    $stObj = @{
        last_compact_at = [DateTimeOffset]::UtcNow.ToString('o')
        last_request_id = $reqId
        last_pid        = $pidToUse
        last_command    = $cmdText
        dry_run         = [bool]$DryRun
    }
    $stObj | ConvertTo-Json | Set-Content -Path $StateFile -Encoding UTF8
}

# Optional auto-resume after CHECKPOINT appears in transcript.jsonl
if ($resumeText -and -not $DryRun) {
    $deadline = (Get-Date).AddSeconds($ResumeWaitTimeoutSeconds)
    $cpDone = $false
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 1500
        if ((Get-CheckpointCount $transcript) -gt $beforeCp) {
            $cpDone = $true
            break
        }
    }
    if ($cpDone) {
        Start-Sleep -Seconds 2
        $rp = Invoke-ConsoleInjector -targetPid $pidToUse -textValue $resumeText -enters 1 -cDelay 0
        $rExit = if ($rp) { $rp.ExitCode } else { -1 }
        Write-CompactLog ('auto-resumed prompt="' + $resumeText + '" pid=' + $pidToUse + ' exit=' + $rExit + ' req=' + $reqId)
    }
    else {
        Write-CompactLog ('auto-resume skipped: CHECKPOINT not observed within ' + $ResumeWaitTimeoutSeconds + 's req=' + $reqId)
    }
}
