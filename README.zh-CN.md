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

| 层次目录 | 包含文件 | 核心职责 |
| :--- | :--- | :--- |
| [`scripts/launcher/`](scripts/launcher/README.md) | `agy.ps1`、`agy-stable.ps1`、`agy-stable.cmd` | 启动封装层：与网络/代理层解耦，负责随 `agy.exe` 启动并在退出时清理 `agy-watchdog.ps1`。 |
| [`scripts/hooks/`](scripts/hooks/README.md) | `check-context.py`、`auto-compact-hook.py` | 生命周期钩子与度量层：`PreInvocation` / `Stop` 钩子与 `transcript.jsonl` 客观度量（CLI / Desktop / ACP 通用）。 |
| [`scripts/watchdog/`](scripts/watchdog/README.md) | `agy-watchdog.ps1` | 宿主机守护层：400ms 非阻塞轮询 `dispatch_ready` 压缩请求，并监听 `cli-*.log` 捕获瞬时 EOF 与触发自动续跑。 |
| [`scripts/compact/`](scripts/compact/README.md) | `request-compact.ps1`、`auto-compact-worker.ps1` | 压缩调度与执行层：请求入队/直发、原子认领、硬冷却防重入、等待空闲、`/compact` 注入及 `CHECKPOINT` 后自动续跑。 |
| [`scripts/injector/`](scripts/injector/README.md) | `send-console-input.ps1` | 底层控制台注入层：基于 Win32 `AttachConsole` / `CONIN$` / `WriteConsoleInputW` 的定向输入原语（支持 `-TextBase64`）。 |

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

### 2. 接入 `agy` 命令（推荐，一次配置，后续直接输 `agy`）

在你的 PowerShell `$PROFILE` 中加入一行 dot-source，以后在任意终端目录直接输入 `agy`，就会自动拉起整套系统（原生钩子 + 后台 Watchdog），并在退出 `agy` 时自动清理后台进程，日常无需手动运行任何 `.ps1` 脚本：

```powershell
# 写入当前 PowerShell 的 $PROFILE（如文件不存在会自动创建）
New-Item -ItemType File -Path $PROFILE -Force | Out-Null
Add-Content -Path $PROFILE -Value '. "<REPO_PATH>\scripts\launcher\agy.ps1"'

# 立即生效（或新开一个终端窗口）
. $PROFILE
```

配置完成后，日常直接像平时一样输入 `agy` 即可：

```powershell
agy
```

> **说明**：如果你自己的 `$PROFILE` 里已经定义了自定义 `agy` 函数（例如用于管理本地网络/代理环境变量），保留你的函数即可，只需在调用 `& $exe @args` 前隐藏拉起 `<REPO_PATH>\scripts\watchdog\agy-watchdog.ps1 -WaitForNew`，并在 `finally` 中停止它。
>
> **备选（不修改 `$PROFILE` 时的临时启动方式）**：直接运行 `.\scripts\launcher\agy-stable.ps1`（PowerShell）或 `.\scripts\launcher\agy-stable.cmd`（CMD）。

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
