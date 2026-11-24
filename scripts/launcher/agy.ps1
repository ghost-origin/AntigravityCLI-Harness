$GeminiHarnessScripts = Split-Path $PSScriptRoot -Parent

function agy {
    $exe = if ($env:AGY_EXE) { $env:AGY_EXE } else {
        $cmd = Get-Command 'agy.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cmd) { $cmd.Source } else { '' }
    }
    if (-not $exe -or -not (Test-Path $exe)) {
        Write-Error 'agy.exe not found in PATH. Install Antigravity CLI or set $env:AGY_EXE.'
        return
    }

    $watchdog = $null
    $watchdogScript = Join-Path $GeminiHarnessScripts 'watchdog\agy-watchdog.ps1'
    if (Test-Path $watchdogScript) {
        $watchdogArgLine = '-NoProfile -ExecutionPolicy Bypass -File "' + $watchdogScript + '" -WaitForNew'
        $watchdog = Start-Process -FilePath 'powershell.exe' -ArgumentList $watchdogArgLine -WindowStyle Hidden -PassThru
    }

    try {
        & $exe @args
    }
    finally {
        if ($watchdog) {
            Stop-Process -Id $watchdog.Id -Force -ErrorAction SilentlyContinue
        }
    }
}
