# Lifecycle Hooks & Context Layer (`scripts/hooks/`)

原生生命周期钩子与上下文度量层：直接挂接 Antigravity 的 `~/.gemini/config/hooks.json`，不依赖控制台注入，**同时适用于 CLI、Antigravity Desktop 与 ACP 运行时**。

## 文件说明

| 文件 | 作用 |
| :--- | :--- |
| `check-context.py` | 只读解析 `transcript.jsonl` 与 `tmp/eof_signal.json`，精确统计当前 token（`input_tokens + cache_read_tokens`，遇 `CHECKPOINT` 重置）、冷却剩余秒数与 EOF 状态，以 JSON 输出决策建议。 |
| `auto-compact-hook.py` | `PreInvocation` / `Stop` 钩子入口：`<300k` 静默，`300k–400k` 节流提醒，`>=400k` 强提醒 + `Stop` 单次拉回；EOF 发生时按 `150k` 分界执行「仅拆分规划」或「先压缩再拆分规划」；检测到待执行的 `tmp/compact_request.json` 时原子盖章 `"dispatch_ready": true` 后放行（避免在 hook Job Object 内起子进程被回收）。 |

## 关键环境变量

- `AUTO_COMPACT_WARN_TOKENS`（默认 `300000`）
- `AUTO_COMPACT_TRIGGER_TOKENS`（默认 `400000`）
- `AUTO_COMPACT_EOF_TOKENS`（默认 `150000`）
- `AUTO_COMPACT_COOLDOWN_SECONDS`（默认 `180`）
- `GEMINI_HARNESS_ROOT`（默认自动推导为仓库根目录）

## 上下游关系

- **上游调用方**：Antigravity 原生 `hooks.json`；`../watchdog/agy-watchdog.ps1`（调用 `check-context.py`）
- **下游握手**：通过 `tmp/compact_request.json`（`dispatch_ready: true`）交由 `../watchdog/` 派发压缩。
