$GeminiHarnessScripts = $PSScriptRoot

function agy {
    $exe = if ($env:AGY_EXE) { $env:AGY_EXE } else {
        $cmd = Get-Command 'agy.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cmd) { $cmd.Source } else { '' }
    }
    if (-not $exe -or -not (Test-Path $exe)) {
        Write-Error 'agy.exe not found in PATH. Install Antigravity CLI or set $env:AGY_EXE.'
        return
    }

    $proxyPort = 0
    if ($env:AGY_PROXY_PORT -and ($env:AGY_PROXY_PORT -match '^\d+$')) {
        $proxyPort = [int]$env:AGY_PROXY_PORT
    }

    if ($proxyPort -gt 0) {
        $client = New-Object System.Net.Sockets.TcpClient
        try {
            $client.Connect('127.0.0.1', $proxyPort)
            $listening = $true
        }
        catch {
            $listening = $false
        }
        finally {
            $client.Dispose()
        }
        if (-not $listening) {
            Write-Warning ('Local proxy port ' + $proxyPort + ' is not listening; agy may fail until your proxy starts.')
        }
    }

    $watchdog = $null
    $watchdogScript = Join-Path $GeminiHarnessScripts 'agy-watchdog.ps1'
    if (Test-Path $watchdogScript) {
        $watchdogArgLine = '-NoProfile -ExecutionPolicy Bypass -File "' + $watchdogScript + '" -WaitForNew'
        $watchdog = Start-Process -FilePath 'powershell.exe' -ArgumentList $watchdogArgLine -WindowStyle Hidden -PassThru
    }

    $oldHttps = $env:HTTPS_PROXY
    $oldHttp = $env:HTTP_PROXY
    $oldNo = $env:NO_PROXY
    $oldGodebug = $env:GODEBUG
    if ($proxyPort -gt 0) {
        $env:HTTPS_PROXY = 'http://127.0.0.1:' + $proxyPort
        $env:HTTP_PROXY = 'http://127.0.0.1:' + $proxyPort
        $env:NO_PROXY = '127.0.0.1,localhost'
    }
    if (-not $env:AGY_KEEP_HTTP2) {
        $env:GODEBUG = 'http2client=0'
    }
    try {
        & $exe @args
    }
    finally {
        $env:HTTPS_PROXY = $oldHttps
        $env:HTTP_PROXY = $oldHttp
        $env:NO_PROXY = $oldNo
        $env:GODEBUG = $oldGodebug
        if ($watchdog) {
            Stop-Process -Id $watchdog.Id -Force -ErrorAction SilentlyContinue
        }
    }
}
