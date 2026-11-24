param(
    [int]$Threshold = 9,
    [switch]$WaitForNew,
    [string]$Prompt = 'continue current work',
    [int]$MaxContinues = 10,
    [int]$CooldownSeconds = 30,
    [string]$LogDir = '',
    [string]$OutLog = '',
    [string]$CompactRequestFile = '',
    [string]$CompactStateFile = '',
    [string]$CompactOutLog = '',
    [string]$PidFile = '',
    [string]$EofSignalFile = '',
    [string]$PythonExe = '',
    [int]$EofCompactTokens = 150000,
    [int]$CompactCooldownSeconds = 120,
    [switch]$DryRun
)

$ErrorActionPreference = 'Continue'
$scriptsRoot = Split-Path $PSScriptRoot -Parent
$repoRoot = Split-Path $scriptsRoot -Parent

if (-not $LogDir) {
    $LogDir = Join-Path $env:USERPROFILE '.gemini\antigravity-cli\log'
}
if (-not $OutLog) {
    $OutLog = Join-Path $repoRoot 'logs\agy_watchdog.log'
}
if (-not $CompactRequestFile) {
    $CompactRequestFile = Join-Path $repoRoot 'tmp\compact_request.json'
}
if (-not $CompactStateFile) {
    $CompactStateFile = Join-Path $repoRoot 'logs\auto_compact_state.json'
}
if (-not $CompactOutLog) {
    $CompactOutLog = Join-Path $repoRoot 'logs\auto_compact.log'
}
if (-not $EofSignalFile) {
    $EofSignalFile = Join-Path $repoRoot 'tmp\eof_signal.json'
}
if (-not (Test-Path $LogDir)) {
    Write-Output ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' log dir not found: ' + $LogDir)
    exit 1
}

$eofBreakdownPrompt = 'EOF recovery: break down the remaining task into smaller pieces, run a brief planning pass, and write a concise Markdown plan file (e.g. scratch/BREAKDOWN_PLAN.md) before continuing.'
$eofCompactResumePrompt = 'EOF recovery: context has been compacted. Now break down the remaining task into smaller pieces, run a brief planning pass, and write a concise Markdown plan file (e.g. scratch/BREAKDOWN_PLAN.md) before continuing.'

function Resolve-PythonExe {
    if ($PythonExe -and (Test-Path $PythonExe)) { return $PythonExe }
    if ($env:AGY_HARNESS_PYTHON -and (Test-Path $env:AGY_HARNESS_PYTHON)) { return $env:AGY_HARNESS_PYTHON }
    foreach ($name in @('python', 'python3')) {
        $cmd = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cmd -and $cmd.Source -and ($cmd.Source -notmatch 'WindowsApps\\python')) {
            return $cmd.Source
        }
    }
    return ''
}

function Get-ContextSnapshot {
    $chk = Join-Path $scriptsRoot 'hooks\check-context.py'
    $pyBin = Resolve-PythonExe
    if (-not (Test-Path $chk) -or -not $pyBin) { return $null }
    try {
        $raw = & $pyBin $chk --harness-root $repoRoot --eof-compact-tokens $EofCompactTokens 2>$null
        if ($raw) { return ($raw | ConvertFrom-Json) }
    } catch {}
    return $null
}

function Dispatch-CompactWorker([switch]$IsAlreadyIdle) {
    $worker = Join-Path $scriptsRoot 'compact\auto-compact-worker.ps1'
    if (-not (Test-Path $worker)) {
        Write-WatchLog 'auto-compact-worker.ps1 not found'
        return
    }
    $wArgStr = '-NoProfile -ExecutionPolicy Bypass -File "' + $worker + '"' +
        ' -RequestFile "' + $CompactRequestFile + '"' +
        ' -LogDir "' + $LogDir + '"' +
        ' -OutLog "' + $CompactOutLog + '"' +
        ' -StateFile "' + $CompactStateFile + '"' +
        ' -CooldownSeconds ' + $CompactCooldownSeconds
    if ($IsAlreadyIdle) { $wArgStr += ' -AlreadyIdle' }
    if ($DryRun) { $wArgStr += ' -DryRun' }
    Start-Process -FilePath 'powershell.exe' -ArgumentList $wArgStr -WindowStyle Hidden | Out-Null
}

function Write-WatchLog([string]$message) {
    $line = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $message
    Write-Output $line
    $dir = Split-Path $OutLog -Parent
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    Add-Content -Path $OutLog -Value $line -Encoding UTF8
}

$latest = $null
if ($WaitForNew) {
    $start = Get-Date
    Write-WatchLog ('waiting for a new log after ' + $start.ToString('yyyy-MM-dd HH:mm:ss'))
    while (-not $latest) {
        $latest = Get-ChildItem $LogDir -Filter 'cli-*.log' -File |
            Where-Object { $_.CreationTime -ge $start } |
            Sort-Object CreationTime -Descending |
            Select-Object -First 1
        if (-not $latest) {
            Start-Sleep -Seconds 1
        }
    }
}
else {
    $latest = Get-ChildItem $LogDir -Filter 'cli-*.log' -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}

if (-not $latest) {
    Write-WatchLog 'no cli log found'
    exit 1
}

if (-not $PidFile) {
    $PidFile = Join-Path $repoRoot 'logs\watchdog.pid'
}
function Write-PidHeartbeat([string]$watchedLog) {
    $pdir = Split-Path $PidFile -Parent
    if (-not (Test-Path $pdir)) { New-Item -ItemType Directory -Path $pdir -Force | Out-Null }
    $info = [ordered]@{
        pid                  = $PID
        started_at           = [DateTimeOffset]::UtcNow.ToString('o')
        watched_log          = $watchedLog
        compact_request_file = $CompactRequestFile
    }
    $info | ConvertTo-Json | Set-Content -Path $PidFile -Encoding UTF8
}

Write-WatchLog ('watching ' + $latest.FullName)
Write-PidHeartbeat $latest.FullName

$currentAttempt = 0
foreach ($line in Get-Content $latest.FullName) {
    if ($line -match 'Run: attempt (\d+) failed') {
        $currentAttempt = [int]$Matches[1]
    }
}
Write-WatchLog ('current attempt: ' + $currentAttempt + '/' + $Threshold)

$continues = 0
$done = $false
$eofSeenThisTurn = $false
$eofTokensAtDetect = 0
$lastDispatchedReqId = ''

function Test-AndDispatchReadyCompact {
    if (-not (Test-Path $CompactRequestFile)) { return }
    try {
        $raw = Get-Content -Path $CompactRequestFile -Raw -Encoding UTF8 -ErrorAction Stop
        if (-not $raw) { return }
        $reqObj = $raw | ConvertFrom-Json
        if ($reqObj.dispatch_ready -eq $true) {
            $rid = if ($reqObj.request_id) { [string]$reqObj.request_id } else { 'ready' }
            if ($rid -ne $script:lastDispatchedReqId) {
                $script:lastDispatchedReqId = $rid
                Write-WatchLog ('dispatch_ready compact request detected (req=' + $rid + '); dispatching worker')
                Dispatch-CompactWorker -IsAlreadyIdle
            }
        }
    } catch {}
}

$logOffset = (Get-Item $latest.FullName).Length
$lineCarry = ''

try {
while ($true) {
    # 1. Check dispatch_ready compact_request.json stamped by Stop hook (independent of cli log format)
    Test-AndDispatchReadyCompact

    # 2. Non-blocking tail of cli-*.log
    $newLines = @()
    try {
        $curLen = (Get-Item $latest.FullName).Length
        if ($curLen -gt $logOffset) {
            $fs = [System.IO.File]::Open($latest.FullName, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
            try {
                $fs.Seek($logOffset, [System.IO.SeekOrigin]::Begin) | Out-Null
                $sr = New-Object System.IO.StreamReader($fs)
                $delta = $sr.ReadToEnd()
                $logOffset = $fs.Position
            }
            finally { $fs.Dispose() }
            if ($delta) {
                $combined = $lineCarry + $delta
                $parts = $combined -split "`r?`n"
                if ($combined.EndsWith("`n")) {
                    $lineCarry = ''
                    $newLines = $parts | Where-Object { $_ -ne '' }
                }
                else {
                    $lineCarry = $parts[$parts.Length - 1]
                    if ($parts.Length -gt 1) {
                        $newLines = $parts[0..($parts.Length - 2)] | Where-Object { $_ -ne '' }
                    }
                }
            }
        }
    } catch {}

    foreach ($line in $newLines) {
    $trigger = $false

    if ($line -match 'TASK_DONE') {
        $done = $true
        Write-WatchLog 'done marker seen'
    }

    if ($line -match 'HandleUserInput called with text: "([^"]*)"') {
        $uText = $Matches[1]
        if ($uText -eq '/compact') {
            Write-WatchLog 'compact command observed in cli log'
        }
        elseif ($uText -ne $Prompt) {
            Write-WatchLog 'manual user input; reset auto-continue counter'
            $continues = 0
            $done = $false
            $eofSeenThisTurn = $false
        }
    }

    # Detect genuine agent stream EOF (excluding play.googleapis.com/log and quota noise)
    if (($line -match 'stream reading error.*EOF|Run: attempt \d+ failed.*EOF') -and ($line -notmatch 'play\.googleapis\.com/log|quota')) {
        if (-not $eofSeenThisTurn) {
            $eofSeenThisTurn = $true
            $snap = Get-ContextSnapshot
            $tok = if ($snap -and $snap.ok) { [int]$snap.current_tokens } else { 0 }
            $cid = if ($snap -and $snap.ok) { [string]$snap.conversation_id } else { '' }
            $cd  = if ($snap -and $snap.ok) { [int]$snap.cooldown_remaining_seconds } else { 0 }
            $eofTokensAtDetect = $tok
            Write-WatchLog ('stream EOF detected; tokens=' + $tok + ' threshold=' + $EofCompactTokens + ' cooldown=' + $cd)

            $sigDir = Split-Path $EofSignalFile -Parent
            if (-not (Test-Path $sigDir)) { New-Item -ItemType Directory -Path $sigDir -Force | Out-Null }
            $sigObj = [ordered]@{
                signal_id       = 'eof-' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '-' + (Get-Random -Minimum 100 -Maximum 999)
                conversation_id = $cid
                current_tokens  = $tok
                action          = if ($tok -ge $EofCompactTokens) { 'compact_then_breakdown' } else { 'breakdown_only' }
                source          = 'watchdog'
                detected_at     = [DateTimeOffset]::UtcNow.ToString('o')
            }
            $sigObj | ConvertTo-Json | Set-Content -Path $EofSignalFile -Encoding UTF8

            if ($tok -ge $EofCompactTokens -and $cd -eq 0 -and -not (Test-Path $CompactRequestFile)) {
                $rDir = Split-Path $CompactRequestFile -Parent
                if (-not (Test-Path $rDir)) { New-Item -ItemType Directory -Path $rDir -Force | Out-Null }
                $reqPayload = [ordered]@{
                    request_id      = 'eofcmp-' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '-' + (Get-Random -Minimum 1000 -Maximum 9999)
                    conversation_id = $cid
                    command         = '/compact'
                    resume_prompt   = $eofCompactResumePrompt
                    reason          = ('watchdog stream EOF with tokens=' + $tok)
                    current_tokens  = $tok
                    delay_seconds   = 2
                    enter_count     = 1
                    char_delay_ms   = 0
                    created_at      = [DateTimeOffset]::UtcNow.ToString('o')
                }
                $reqPayload | ConvertTo-Json -Depth 4 | Set-Content -Path $CompactRequestFile -Encoding UTF8
                Write-WatchLog ('queued EOF compact+breakdown request: ' + $CompactRequestFile)
            }
        }
    }

    if ($line -match 'Stream completed for .*, clearing ResponsePending') {
        $eofSeenThisTurn = $false
        if (Test-Path $CompactRequestFile) {
            Write-WatchLog ('turn idle and compact request found; dispatching worker for ' + $CompactRequestFile)
            Dispatch-CompactWorker -IsAlreadyIdle
        }
    }

    if ($line -match 'Run: attempt (\d+) failed') {
        $currentAttempt = [int]$Matches[1]
        Write-WatchLog ('attempt ' + $currentAttempt + '/' + $Threshold)
        if ($currentAttempt -ge $Threshold) {
            $trigger = $true
        }
    }
    elseif ($line -match 'agent executor error|network issue connecting|Agent execution terminated|retry limit|too many retries|giving up') {
        Write-WatchLog ('terminal failure: ' + $line)
        $trigger = $true
    }

    if ($trigger -and -not $done) {
        if ($continues -ge $MaxContinues) {
            Write-WatchLog ('max auto-continues reached: ' + $continues)
        }
        elseif ($eofSeenThisTurn -and $eofTokensAtDetect -ge $EofCompactTokens -and (Test-Path $CompactRequestFile)) {
            Write-WatchLog ('terminal failure after EOF (>=150k); dispatching compact+breakdown worker instead of plain continue')
            Dispatch-CompactWorker -IsAlreadyIdle
            $continues = $continues + 1
            $eofSeenThisTurn = $false
            $currentAttempt = 0
            Start-Sleep -Seconds $CooldownSeconds
        }
        else {
            $promptToSend = if ($eofSeenThisTurn) { $eofBreakdownPrompt } else { $Prompt }
            $target = Get-Process agy -ErrorAction SilentlyContinue |
                Sort-Object StartTime -Descending |
                Select-Object -First 1
            if (-not $target) {
                Write-WatchLog 'no agy process found'
            }
            elseif ($DryRun) {
                Write-WatchLog ('dry-run: would send prompt to pid ' + $target.Id + ' text="' + $promptToSend + '"')
                $continues = $continues + 1
            }
            else {
                $helper = Join-Path $scriptsRoot 'injector\send-console-input.ps1'
                if (Test-Path $helper) {
                    $b64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($promptToSend))
                    $argLine = '-NoProfile -ExecutionPolicy Bypass -File "' + $helper + '" -ProcessId ' + $target.Id + ' -TextBase64 "' + $b64 + '"'
                    Start-Process -FilePath 'powershell.exe' -ArgumentList $argLine -WindowStyle Hidden -Wait
                    $continues = $continues + 1
                    Write-WatchLog ('sent prompt to pid ' + $target.Id + ' count=' + $continues + ' eof_mode=' + $eofSeenThisTurn)
                }
                else {
                    Write-WatchLog 'send-console-input.ps1 not found'
                }
            }

            $eofSeenThisTurn = $false
            $currentAttempt = 0
            Start-Sleep -Seconds $CooldownSeconds
        }
    }
    }

    Start-Sleep -Milliseconds 400
}
}
finally {
    if (Test-Path $PidFile) {
        try {
            $cur = Get-Content -Path $PidFile -Raw -Encoding UTF8 | ConvertFrom-Json
            if ([int]$cur.pid -eq $PID) { Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue }
        } catch {}
    }
}
