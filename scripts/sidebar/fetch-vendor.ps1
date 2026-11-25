param(
    [string]$OutDir = '',
    [string]$KatexVersion = '0.16.21',
    [string]$MarkedVersion = '15.0.7',
    [string]$MermaidVersion = '11.4.1'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$cfgLoader = Join-Path $repoRoot 'Config\load-config.ps1'
if (-not $OutDir -and (Test-Path $cfgLoader)) {
    . $cfgLoader
    $hcfg = Get-HarnessConfig -RepoRoot $repoRoot
    $OutDir = Get-HarnessConfigValue -Config $hcfg -Section 'sidebar' -Key 'vendor_dir' -Default ''
}
if (-not $OutDir) {
    $OutDir = Join-Path $PSScriptRoot 'vendor'
}

$katexDir = Join-Path $OutDir 'katex'
$katexFontsDir = Join-Path $katexDir 'fonts'
$markedDir = Join-Path $OutDir 'marked'
$mermaidDir = Join-Path $OutDir 'mermaid'

New-Item -ItemType Directory -Path $katexFontsDir -Force | Out-Null
New-Item -ItemType Directory -Path $markedDir -Force | Out-Null
New-Item -ItemType Directory -Path $mermaidDir -Force | Out-Null

function Get-Asset([string]$Url, [string]$Dest) {
    if ((Test-Path $Dest) -and ((Get-Item $Dest).Length -gt 0)) {
        Write-Output "Cached: $Dest"
        return
    }
    Write-Output "Downloading: $Url -> $Dest"
    Invoke-WebRequest -Uri $Url -OutFile $Dest -UseBasicParsing
}

$katexBase = "https://cdn.jsdelivr.net/npm/katex@$KatexVersion/dist"
Get-Asset "$katexBase/katex.min.js" (Join-Path $katexDir 'katex.min.js')
Get-Asset "$katexBase/katex.min.css" (Join-Path $katexDir 'katex.min.css')
Get-Asset "$katexBase/contrib/copy-tex.min.js" (Join-Path $katexDir 'copy-tex.min.js')

$cssText = Get-Content -Path (Join-Path $katexDir 'katex.min.css') -Raw -Encoding UTF8
$fontMatches = [regex]::Matches($cssText, 'fonts/([A-Za-z0-9_\-]+\.woff2)')
$uniqueFonts = $fontMatches | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique

foreach ($font in $uniqueFonts) {
    Get-Asset "$katexBase/fonts/$font" (Join-Path $katexFontsDir $font)
}

$markedBase = "https://cdn.jsdelivr.net/npm/marked@$MarkedVersion"
Get-Asset "$markedBase/marked.min.js" (Join-Path $markedDir 'marked.min.js')

$mermaidBase = "https://cdn.jsdelivr.net/npm/mermaid@$MermaidVersion/dist"
Get-Asset "$mermaidBase/mermaid.min.js" (Join-Path $mermaidDir 'mermaid.min.js')

Write-Output "Vendor assets ready in $OutDir ($($uniqueFonts.Count) KaTeX woff2 fonts + marked + mermaid)"
