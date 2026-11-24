# AntigravityCLI-Harness

<p align="center">
  <strong>English</strong> | <a href="README.zh-CN.md">简体中文</a>
</p>

Unattended Windows harness for **Google Antigravity CLI (`agy`)**:

- **Lifecycle Hook Guard (`PreInvocation` / `Stop`)**: Objective token tracking from `transcript.jsonl` with configurable thresholds (default: `<300k` silent, `300k–400k` milestone advisory, `>=400k` mandatory reminder + one-time `Stop` pullback).
- **Tiered EOF Recovery**:
  - `tokens < 150k` on stream EOF: skip compaction and immediately direct the agent to break down the remaining task and write a concise Markdown plan file.
  - `tokens >= 150k` on stream EOF: compact first (`/compact`), then automatically trigger the same task breakdown & plan directive.
- **Zero-Privilege Watchdog & Console Injector**: `Stop` hook stamps `"dispatch_ready": true` on `tmp/compact_request.json` and lets the host-side non-blocking `agy-watchdog.ps1` dispatch `auto-compact-worker.ps1` via Win32 `CONIN$` (`send-console-input.ps1 -TextBase64`), supporting multi-word/Unicode auto-resume prompts after `CHECKPOINT` detection.
- **Unattended EOF Auto-Continue**: Watches `cli-*.log` for terminal retry exhaustion and resumes the running `agy` session without stealing window focus.

## Layout

| Layer | Files | Purpose |
| :--- | :--- | :--- |
| [`scripts/launcher/`](scripts/launcher/README.md) | `agy.ps1`, `agy-stable.ps1`, `agy-stable.cmd` | Network-agnostic launcher wrappers that start and clean up `agy-watchdog.ps1` alongside `agy.exe`. |
| [`scripts/hooks/`](scripts/hooks/README.md) | `check-context.py`, `auto-compact-hook.py` | Antigravity native `PreInvocation` / `Stop` hook handler and read-only `transcript.jsonl` context analyzer (works across CLI, Desktop, and ACP). |
| [`scripts/watchdog/`](scripts/watchdog/README.md) | `agy-watchdog.ps1` | Host-side non-blocking 400ms poller for `dispatch_ready` compact requests + `cli-*.log` EOF watcher & auto-continue trigger. |
| [`scripts/compact/`](scripts/compact/README.md) | `request-compact.ps1`, `auto-compact-worker.ps1` | Compact request producer, atomic claim, cooldown guard, idle wait, `/compact` injection, and post-`CHECKPOINT` auto-resume. |
| [`scripts/injector/`](scripts/injector/README.md) | `send-console-input.ps1` | Win32 `AttachConsole` / `CONIN$` / `WriteConsoleInputW` console input primitive (supports `-TextBase64`). |
| [`skills/auto-compact/`](skills/auto-compact/SKILL.md) | `SKILL.md` | Agent-side skill template defining the 300k/400k + 150k EOF decision matrix and the 4-step safe compaction handshake. |

## Quick Start (Windows)

### 1. Configure Antigravity Lifecycle Hooks

Add the hook entry to `~/.gemini/config/hooks.json` (replace `<REPO_PATH>` and `python` with your local paths):

```json
{
  "auto-compact-guard": {
    "enabled": true,
    "PreInvocation": [
      {
        "type": "command",
        "command": "python <REPO_PATH>/scripts/hooks/auto-compact-hook.py",
        "timeout": 10
      }
    ],
    "Stop": [
      {
        "type": "command",
        "command": "python <REPO_PATH>/scripts/hooks/auto-compact-hook.py",
        "timeout": 10
      }
    ]
  }
}
```

### 2. Install the `auto-compact` Skill

Copy the skill template into your Antigravity skills directory so the agent knows how to execute the safe `/compact` handshake when prompted by hooks:

```powershell
$skillDir = "$HOME\.gemini\config\skills\auto-compact"
New-Item -ItemType Directory -Path $skillDir -Force | Out-Null
Copy-Item ".\skills\auto-compact\SKILL.md" "$skillDir\SKILL.md" -Force
```

Then replace `<REPO_PATH>` (and `python` if needed) inside `~/.gemini/config/skills/auto-compact/SKILL.md` with your local paths.

### 3. Enable Seamless `agy` Command (Recommended)

Add a single line to your PowerShell `$PROFILE` so typing `agy` in any terminal automatically starts the entire harness (hooks + background watchdog) and cleans up the watchdog on exit—no need to invoke any `.ps1` script manually:

```powershell
# Append to your PowerShell profile (creates $PROFILE if it doesn't exist)
New-Item -ItemType File -Path $PROFILE -Force | Out-Null
Add-Content -Path $PROFILE -Value '. "<REPO_PATH>\scripts\launcher\agy.ps1"'

# Reload your profile once (or open a new terminal)
. $PROFILE
```

From then on, just run `agy` as usual in any directory:

```powershell
agy
```

> **Note:** If you already use a custom `agy` wrapper in `$PROFILE` (for example, to configure local proxy environment variables), keep your own wrapper and simply launch `<REPO_PATH>\scripts\watchdog\agy-watchdog.ps1 -WaitForNew` inside it before `& $exe @args`.
>
> **Alternative (one-off launch without editing `$PROFILE`):** run `.\scripts\launcher\agy-stable.ps1` (PowerShell) or `.\scripts\launcher\agy-stable.cmd` (CMD).

Optional environment variables:

- `AGY_EXE`: Explicit path to `agy.exe` (defaults to searching `PATH`).
- `AGY_HARNESS_PYTHON`: Explicit Python executable path for `agy-watchdog.ps1` (defaults to `python` on `PATH`).
- `AGY_CLI_AUTO_COMPACT_OVERRIDE`: Native Antigravity CLI (`1.5.15+`) hard auto-compact fallback (e.g., `750K`).
- `AUTO_COMPACT_WARN_TOKENS` / `AUTO_COMPACT_TRIGGER_TOKENS` / `AUTO_COMPACT_EOF_TOKENS` / `AUTO_COMPACT_COOLDOWN_SECONDS`: Override hook thresholds (defaults: `300000` / `400000` / `150000` / `180`).

## Requirements

- Windows PowerShell 5.1+
- Python 3.8+
- Google Antigravity CLI (`agy`)

## License

[MIT](LICENSE)
