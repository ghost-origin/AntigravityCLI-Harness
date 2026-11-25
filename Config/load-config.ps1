function Get-HarnessConfig {
    param(
        [string]$RepoRoot = ''
    )

    if (-not $RepoRoot) {
        if ($env:GEMINI_HARNESS_ROOT) {
            $RepoRoot = $env:GEMINI_HARNESS_ROOT
        } else {
            $RepoRoot = Split-Path $PSScriptRoot -Parent
        }
    }
    $RepoRoot = $RepoRoot.TrimEnd('\', '/')
    $userHome = $env:USERPROFILE.TrimEnd('\', '/')

    $cfg = @{}
    $configDir = Join-Path $RepoRoot 'Config'
    foreach ($name in @('harness.config', 'harness.local.config')) {
        $fp = Join-Path $configDir $name
        if (-not (Test-Path $fp)) { continue }
        $section = 'default'
        foreach ($rawLine in (Get-Content -Path $fp -Encoding UTF8)) {
            $line = $rawLine.Trim()
            if (-not $line -or $line.StartsWith('#') -or $line.StartsWith(';')) { continue }
            if ($line -match '^\[([^\]]+)\]$') {
                $section = $Matches[1].Trim()
                if (-not $cfg.ContainsKey($section)) { $cfg[$section] = @{} }
                continue
            }
            $eq = $line.IndexOf('=')
            if ($eq -gt 0) {
                $k = $line.Substring(0, $eq).Trim()
                $v = $line.Substring($eq + 1).Trim()
                if ($v) {
                    $v = $v.Replace('${REPO_ROOT}', $RepoRoot).Replace('${USERPROFILE}', $userHome)
                    if ($v -match '[/\\]') {
                        $v = $v.Replace('/', '\')
                    }
                }
                if (-not $cfg.ContainsKey($section)) { $cfg[$section] = @{} }
                $cfg[$section][$k] = $v
            }
        }
    }
    return $cfg
}

function Get-HarnessConfigValue {
    param(
        [hashtable]$Config,
        [string]$Section,
        [string]$Key,
        [string]$Default = ''
    )
    if ($Config -and $Config.ContainsKey($Section) -and $Config[$Section].ContainsKey($Key)) {
        $val = [string]$Config[$Section][$Key]
        if ($val) { return $val }
    }
    return $Default
}
