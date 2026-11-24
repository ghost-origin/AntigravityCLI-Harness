# AntigravityCLI-Harness

Unattended Windows harness for **Google Antigravity CLI (`agy`)**:

- **Lifecycle Hook Guard (`PreInvocation` / `Stop`)**: Objective token tracking from `transcript.jsonl` with configurable thresholds (default: `<300k` silent, `300k–400k` milestone advisory, `>=400k` mandatory reminder + one-time `Stop` pullback).
- **Tiered EOF Recovery**:
  - `tokens < 150k` on stream EOF: skip compaction and immediately direct the agent to break down the remaining task and write a concise Markdown plan file.
  - `tokens >= 150k` on stream EOF: compact first (`/compact`), then automatically trigger the same task breakdown & plan directive.
- **Zero-Privilege Watchdog & Console Injector**: `Stop` hook stamps `"dispatch_ready": true` on `tmp/compact_request.json` and lets the host-side non-blocking `agy-watchdog.ps1` dispatch `auto-compact-worker.ps1` via Win32 `CONIN$` (`send-console-input.ps1 -TextBase64`), supporting multi-word/Unicode auto-resume prompts after `CHECKPOINT` detection.
- **Unattended EOF Auto-Continue**: Watches `cli-*.log` for terminal retry exhaustion and resumes the running `agy` session without stealing window focus.

## Layout

| File | Purpose |
| :--- | :--- |
| `scripts/check-context.py` | Read-only analyzer for `transcript.jsonl` and `tmp/eof_signal.json`; outputs exact token count, checkpoint count, cooldown, and action recommendation as JSON. |
| `scripts/auto-compact-hook.py` | Antigravity native `PreInvocation` / `Stop` hook handler for `~/.gemini/config/hooks.json`. |
| `scripts/agy-watchdog.ps1` | Non-blocking 400ms poller for `dispatch_ready` compact requests + `cli-*.log` EOF watcher & auto-continue trigger. |
| `scripts/request-compact.ps1` | Compact request producer (queues for watchdog or launches `auto-compact-worker.ps1` directly). |
| `scripts/auto-compact-worker.ps1` | Atomic request claim, cooldown guard, idle wait, `/compact` injection, and post-`CHECKPOINT` auto-resume. |
| `scripts/send-console-input.ps1` | Win32 `AttachConsole` / `CONIN$` / `WriteConsoleInputW` injector (supports `-TextBase64`). |
| `scripts/agy.ps1`, `scripts/agy-stable.ps1`, `scripts/agy-stable.cmd` | Launcher wrappers that start and clean up `agy-watchdog.ps1` alongside `agy.exe`. |

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
        "command": "python <REPO_PATH>/scripts/auto-compact-hook.py",
        "timeout": 10
      }
    ],
    "Stop": [
      {
        "type": "command",
        "command": "python <REPO_PATH>/scripts/auto-compact-hook.py",
        "timeout": 10
      }
    ]
  }
}
```

### 2. Launch `agy` with Watchdog

Dot-source `scripts/agy.ps1` in your PowerShell `$PROFILE`, or run directly:

```powershell
.\scripts\agy-stable.ps1
```

Optional environment variables:

- `AGY_EXE`: Explicit path to `agy.exe` (defaults to searching `PATH`).
- `AGY_PROXY_PORT`: Optional local proxy port (e.g., `7890`) to bind `HTTP_PROXY`/`HTTPS_PROXY` for the `agy` process only.
- `AGY_HARNESS_PYTHON`: Explicit Python executable path for `agy-watchdog.ps1` (defaults to `python` on `PATH`).
- `AGY_CLI_AUTO_COMPACT_OVERRIDE`: Native Antigravity CLI (`1.5.15+`) hard auto-compact fallback (e.g., `750K`).
- `AUTO_COMPACT_WARN_TOKENS` / `AUTO_COMPACT_TRIGGER_TOKENS` / `AUTO_COMPACT_EOF_TOKENS` / `AUTO_COMPACT_COOLDOWN_SECONDS`: Override hook thresholds (defaults: `300000` / `400000` / `150000` / `180`).

## Requirements

- Windows PowerShell 5.1+
- Python 3.8+
- Google Antigravity CLI (`agy`)

## License

[MIT](LICENSE)
