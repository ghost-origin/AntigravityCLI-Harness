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
- **低依赖公式与图片实时侧边栏**：利用 Windows 自带 Edge 应用模式、Python 标准库与离线 `KaTeX` 静态资源，自动贴靠在 Windows Terminal 右侧实时渲染 `$` / `$$` 公式、支持源码级复制粘贴，并实时展示终端粘贴与剪贴板中的图片。

## 目录结构

| 层次目录 | 包含文件 | 核心职责 |
| :--- | :--- | :--- |
| [`Config/`](Config/README.md) | `harness.config.example`、`load-config.ps1`、`config_loader.py` | 配置中心层：提供可公开推送的标准配置模板，并将本机真实配置 `Config/harness.config` 纳入 `.gitignore` 隔离管理。 |
| [`scripts/launcher/`](scripts/launcher/README.md) | `agy.ps1`、`agy-stable.ps1`、`agy-stable.cmd` | 启动封装层：与网络/代理层解耦，负责随 `agy.exe` 启动并在退出时清理 `agy-watchdog.ps1` 与公式侧边栏。 |
| [`scripts/sidebar/`](scripts/sidebar/README.md) | `sidebar_server.py`、`transcript_watcher.py`、`window_docker.py`、`launch-sidebar.ps1`、`web/`、`vendor/` | 公式与图片侧边栏层：实时监听 `transcript_full.jsonl`、剪贴板图片与 Windows Terminal 标签页切换，在 Edge 统一贴靠侧边窗中离线渲染 KaTeX 公式、Mermaid 图表与本地图片。 |
| [`scripts/hooks/`](scripts/hooks/README.md) | `check-context.py`、`auto-compact-hook.py` | 生命周期钩子与度量层：`PreInvocation` / `Stop` 钩子与 `transcript.jsonl` 客观度量（CLI / Desktop / ACP 通用）。 |
| [`scripts/watchdog/`](scripts/watchdog/README.md) | `agy-watchdog.ps1` | 宿主机守护层：400ms 非阻塞轮询 `dispatch_ready` 压缩请求，并监听 `cli-*.log` 捕获瞬时 EOF 与触发自动续跑。 |
| [`scripts/compact/`](scripts/compact/README.md) | `request-compact.ps1`、`auto-compact-worker.ps1` | 压缩调度与执行层：请求入队/直发、原子认领、硬冷却防重入、等待空闲、`/compact` 注入及 `CHECKPOINT` 后自动续跑。 |
| [`scripts/injector/`](scripts/injector/README.md) | `send-console-input.ps1` | 底层控制台注入层：基于 Win32 `AttachConsole` / `CONIN$` / `WriteConsoleInputW` 的定向输入原语（支持 `-TextBase64`）。 |
| [`skills/auto-compact/`](skills/auto-compact/SKILL.md) | `SKILL.md` | Agent 侧 Skill 模板：定义 300k/400k 与 150k EOF 判定矩阵及四步安全压缩握手协议。 |
| [`skills/sidebar/`](skills/sidebar/SKILL.md) | `SKILL.md` | Agent 侧 `/sidebar` 斜杠命令模板：支持在 `agy` 对话中直接输入 `/sidebar`、`/sidebar restart` 或 `/sidebar stop` 唤醒或管理公式侧边栏。 |

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

### 2. 安装 `auto-compact` Skill

将仓库中的 Skill 模板复制到 Antigravity 的全局技能目录，让模型在钩子触发时能够按四步安全协议完成落盘与自动 `/compact`：

```powershell
$skillDir = "$HOME\.gemini\config\skills\auto-compact"
New-Item -ItemType Directory -Path $skillDir -Force | Out-Null
Copy-Item ".\skills\auto-compact\SKILL.md" "$skillDir\SKILL.md" -Force
```

复制后，将 `~/.gemini/config/skills/auto-compact/SKILL.md` 中的 `<REPO_PATH>`（以及按需替换 `python`）改为你的本机路径即可。

### 3. 接入 `agy` 命令（推荐，一次配置，后续直接输 `agy`）

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
- `AGY_SIDEBAR` / `AGY_SIDEBAR_WIDTH_RATIO` / `AGY_SIDEBAR_NO_RESIZE`：控制公式侧边栏开关（设为 `0` 禁用）、宽度比例（默认 `0.38`）及是否自动调整左侧终端尺寸。
- `AUTO_COMPACT_WARN_TOKENS` / `AUTO_COMPACT_TRIGGER_TOKENS` / `AUTO_COMPACT_EOF_TOKENS` / `AUTO_COMPACT_COOLDOWN_SECONDS`：覆盖钩子阈值与冷却时长（默认 `300000` / `400000` / `150000` / `180`）。

## 运行依赖

- Windows PowerShell 5.1+
- Python 3.8+
- Google Antigravity CLI（`agy`）

## 开源协议

[MIT](LICENSE)
