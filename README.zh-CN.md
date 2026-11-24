# AntigravityCLI-Harness

<p align="center">
  <a href="README.md">English</a> | <strong>简体中文</strong>
</p>

面向 **Google Antigravity CLI（`agy`）** 的 Windows 无人值守治理与自愈 Harness（与网络/代理层完全解耦）：

- **原生生命周期钩子守卫（`PreInvocation` / `Stop`）**：直接读取 `transcript.jsonl` 精确度量上下文 token，支持可配置阈值（默认：`<300k` 静默，`300k–400k` 里程碑提醒，`>=400k` 强制提醒 + `Stop` 钩子单次拉回落盘并压缩）。
- **EOF 分级自愈**：
  - 流式 EOF 发生且 `tokens < 150k`：不压缩，立刻要求模型将剩余任务拆分为更小块（break down into smaller pieces），做一轮规划并落盘简要的 Markdown 规划文件。
  - 流式 EOF 发生且 `tokens >= 150k`：先自动执行 `/compact` 压缩上下文，压缩完成后再自动触发相同的任务拆分与规划流程。
- **零提权 Watchdog 与控制台注入**：`Stop` 钩子向 `tmp/compact_request.json` 原子写入 `"dispatch_ready": true`，由宿主机侧非阻塞 `agy-watchdog.ps1` 派发 `auto-compact-worker.ps1`，经 Win32 `CONIN$`（`send-console-input.ps1 -TextBase64`）安全注入 `/compact`，并在检测到新 `CHECKPOINT` 后自动注入支持多词与中文的续跑提示词。
- **断流无人值守自动续跑**：监听 `cli-*.log` 中的重试耗尽与终态错误，在不抢占窗口焦点的情况下向运行中的 `agy` 控制台自动续跑。

## 目录结构

| 文件 | 说明 |
| :--- | :--- |
| `scripts/check-context.py` | 只读分析 `transcript.jsonl` 与 `tmp/eof_signal.json`，以 JSON 输出精确 token 数、checkpoint 次数、冷却状态与建议动作。 |
| `scripts/auto-compact-hook.py` | 供 Antigravity 全局 `~/.gemini/config/hooks.json` 调用的 `PreInvocation` / `Stop` 钩子脚本。 |
| `scripts/agy-watchdog.ps1` | 400ms 非阻塞轮询 `dispatch_ready` 压缩请求，同时监听 `cli-*.log` 捕获瞬时 EOF 并触发自动续跑。 |
| `scripts/request-compact.ps1` | 压缩请求下发入口（watchdog 在线时入队，否则直接拉起 `auto-compact-worker.ps1`）。 |
| `scripts/auto-compact-worker.ps1` | 原子认领请求、硬冷却防重入、等待回合空闲、注入 `/compact` 及 `CHECKPOINT` 后自动续跑。 |
| `scripts/send-console-input.ps1` | 基于 Win32 `AttachConsole` / `CONIN$` / `WriteConsoleInputW` 的控制台注入器（支持 `-TextBase64`）。 |
| `scripts/agy.ps1`、`scripts/agy-stable.ps1`、`scripts/agy-stable.cmd` | `agy` 启动包装脚本，负责随 `agy.exe` 启动并在退出时清理 `agy-watchdog.ps1`。 |

## 快速开始（Windows）

### 1. 配置 Antigravity 原生生命周期钩子

在 `~/.gemini/config/hooks.json` 中添加如下配置（将 `<REPO_PATH>` 和 `python` 替换为你的本地路径）：

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

### 2. 携带 Watchdog 启动 `agy`

在 PowerShell `$PROFILE` 中 dot-source `scripts/agy.ps1`，或直接运行：

```powershell
.\scripts\agy-stable.ps1
```

可选环境变量：

- `AGY_EXE`：显式指定 `agy.exe` 路径（默认从 `PATH` 自动查找）。
- `AGY_HARNESS_PYTHON`：显式指定 `agy-watchdog.ps1` 使用的 Python 可执行文件路径（默认从 `PATH` 查找 `python`）。
- `AGY_CLI_AUTO_COMPACT_OVERRIDE`：Antigravity CLI（`1.5.15+`）原生内核级自动压缩硬兜底阈值（例如 `750K`）。
- `AUTO_COMPACT_WARN_TOKENS` / `AUTO_COMPACT_TRIGGER_TOKENS` / `AUTO_COMPACT_EOF_TOKENS` / `AUTO_COMPACT_COOLDOWN_SECONDS`：覆盖钩子阈值与冷却时长（默认 `300000` / `400000` / `150000` / `180`）。

## 运行依赖

- Windows PowerShell 5.1+
- Python 3.8+
- Google Antigravity CLI（`agy`）

## 开源协议

[MIT](LICENSE)
