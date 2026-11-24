---
name: auto-compact
description: >-
  Autonomous context-window monitoring, EOF recovery, and automatic /compact execution via
  AntigravityCLI-Harness (<REPO_PATH>) and ~/.gemini/config/hooks.json. Use at milestones, when
  context reaches 300k–400k+ tokens, or immediately whenever stream EOF occurs (<150k
  breakdown-only; >=150k compact first then break down into smaller pieces with a brief .md plan).
---

# Auto-Compact（自主上下文治理、防遗忘钩子与 EOF 分级自愈）

> **Setup note**: Replace `<REPO_PATH>` with your local AntigravityCLI-Harness directory and `python` with your Python 3.8+ executable path before copying this folder to `~/.gemini/config/skills/auto-compact/`.

通过 **Antigravity 原生生命周期钩子（`~/.gemini/config/hooks.json`）+ `<REPO_PATH>` 后台注入器/Watchdog**，将“防遗忘度量”“EOF 分级恢复”与“空闲态自动注入 `/compact`”闭环化。

## 1. 精确度量（沙箱内可直接运行，零提权）

```powershell
python <REPO_PATH>\scripts\hooks\check-context.py --conversation-id <conversation_id>
```

（若刚完成某个大阶段，可附加 `--milestone` 参数。）

关键输出字段：
- `current_tokens`：最近一次 `PLANNER_RESPONSE` 的 `input_tokens + cache_read_tokens` 真实值；
- `eof_detected` / `eof_action`：是否检测到 `unexpected EOF` 及对应分支（`none` / `breakdown_only` / `compact_then_breakdown`）；
- `cooldown_remaining_seconds`：剩余冷却时间（默认 180 秒）；
- `watchdog_heartbeat_present`：`<REPO_PATH>\logs\watchdog.pid` 状态；
- `should_compact` 与 `recommended_action`。

## 2. 自主触发与 EOF 分级判定矩阵

| 场景 / 条件 | 判定动作 |
| :--- | :--- |
| `cooldown_remaining_seconds > 0` | **不触发压缩**（若因 EOF 触发且 `< 150k`，仍执行拆分规划） |
| 常规：`< 300,000` tokens | **不压缩**（`continue`，钩子完全静默） |
| 常规：`300,000 <= tokens < 400,000` | **可压缩**：`PreInvocation` 节流提醒；完成当前阶段里程碑、落盘检查点后执行压缩 |
| 常规：`>= 400,000` tokens | **强制压缩**：`PreInvocation` 强提醒；完成当前原子写入、更新检查点后立即压缩。若模型结束本轮仍遗忘，`Stop` hook 会自动拉回一次（`decision: "continue"`）要求先落盘并执行压缩 |
| **EOF 发生且 `< 150,000` tokens** | **不压缩，立刻拆分规划**：立即将剩余任务拆分为更小块（break down into smaller pieces），做一轮规划并落盘一份简要的 Markdown 规划文件（如 `scratch/BREAKDOWN_PLAN.md`），防止再次 EOF |
| **EOF 发生且 `>= 150,000` tokens** | **先压缩，再拆分规划**：Step 1 立即触发 `/compact`；Step 2 压缩完成后立刻执行与 `< 150k` 完全一致的任务拆分、规划并写入简要 `.md` 规划文件，再继续执行 |

## 3. 双层防遗忘自动化架构

1. **原生 Hook 层（`~/.gemini/config/hooks.json` → `scripts/hooks/auto-compact-hook.py`）**：
   - `PreInvocation`：在每次模型调用前静默检查 `transcript.jsonl` 与 `tmp/eof_signal.json`，按 300k/400k 与 EOF 分支精准注入 `systemMessage`，并跟踪压缩完成后的“EOF Step 2 拆分规划”提醒。
   - `Stop`：在回合结束时复核——若检测到在途 `tmp/compact_request.json`，原子盖章 `"dispatch_ready": true` 后直接放行（`decision: "allow"`），交给宿主机侧 `agy-watchdog.ps1` 在独立进程上下文中派发（避开 Antigravity hook 的 Windows Job Object 子进程回收）；若 `>= 400k` 仍未压缩且无在途请求，以 `decision: "continue"` 拉回模型一次落盘并压缩；若因 EOF 异常终止，`< 150k` 直接拉回执行拆分规划，`>= 150k` 写入 `dispatch_ready: true` 的 `compact_request.json` 先压缩再续跑拆分规划。
2. **Watchdog 宿主机轮询与日志层（`<REPO_PATH>\scripts\watchdog\agy-watchdog.ps1`）**：
   - 以 400ms 非阻塞 `FileStream` 循环同时承担两项职责：① 发现 `tmp/compact_request.json` 带有 `dispatch_ready == true` 时立即以 `-AlreadyIdle` 派发 `auto-compact-worker.ps1`（不依赖特定 `cli-*.log` 空闲日志文案）；② 监听 `cli-*.log` 中 CLI 内部重试期的瞬时 `unexpected EOF`：`< 150k` 写 `tmp/eof_signal.json` 交给 `PreInvocation` 立即触发拆分规划（终端失败时直接注入拆分提示词）；`>= 150k` 写带 `resume_prompt` 的 `tmp/compact_request.json`，回合空闲或终端失败时立刻先 `/compact` 再自动续跑拆分规划。

## 4. 手动/自主触发安全执行协议（四步不可颠倒）

1. **先落盘检查点**：确保所有文件已落盘并更新进度/规划文件（如 `scratch/STATE.md` 或 `scratch/BREAKDOWN_PLAN.md`）。
2. **选择下发通道**：
   - **优先通道 A（Watchdog 在线，零提权）**：若 `watchdog_heartbeat_present == true`，用 `write_file` 写入 `<REPO_PATH>\tmp\compact_request.json`（含 `request_id`、`conversation_id`、`command: "/compact"`、`resume_prompt`、`delay_seconds: 2`、`enter_count: 1`、`created_at`）。
   - **通道 B（独立触发脚本）**：若 watchdog 未运行，以异步后台方式（`run_command` 设 `WaitMsBeforeAsync: 500`）调用：
     ```powershell
     powershell.exe -NoProfile -ExecutionPolicy Bypass -File <REPO_PATH>\scripts\compact\request-compact.ps1 -ConversationId <conversation_id> -CurrentTokens <tokens> -Reason "<reason>" -Mode direct -Wait -DelaySeconds 2 -EnterCount 1
     ```
     （`agy.exe` 使用 `-EnterCount 1` 可一次提交 `/compact`；含空格或中文的 `-ResumePrompt` 底层统一经 `-TextBase64` 传递；测试时务必加 `-DryRun`。）
3. **立即结束本轮回复**：下发请求后**严禁再发起任何后续工具调用**，简明交代检查点与即将自动压缩，让 CLI 立刻回到空闲态以便注入器安全写入 `/compact`。
4. **优雅降级（Fallback）**：若自动通道不可用，直接列出已完成文件与剩余待办，提示用户手动输入 `/compact`。

## 5. 防循环与防死锁约束

- `Stop` hook 在检测到 `tmp/compact_request.json`（或 `.processing.*`）存在时直接放行（`decision: "allow"`），绝不阻塞正在等待 `/compact` 注入的正常回合结束。
- `Stop` hook 对同一 `checkpoint_count` 至多拉回一次，且注入侧保留 120 秒硬冷却（`logs/auto_compact_state.json`），杜绝死循环。
