# Watchdog Layer (`scripts/watchdog/`)

宿主机守护进程层：作为独立于 Antigravity hook Job Object 之外的常驻进程，负责**非阻塞轮询压缩握手信号**与**日志侧 EOF 断流监控/自动续跑**。

## 文件说明

| 文件 | 作用 |
| :--- | :--- |
| `agy-watchdog.ps1` | 400ms 非阻塞 `FileStream` 轮询循环：① 发现 `tmp/compact_request.json` 含 `dispatch_ready == true` 时，不依赖 CLI 空闲日志文案立即以 `-AlreadyIdle` 派发压缩 worker；② 持续跟踪最新 `cli-*.log`，过滤 `play.googleapis.com/log` 与 `quota` 噪音后捕获真实流式 EOF，按 `150k` 阈值写入 `tmp/eof_signal.json` 或入队 `/compact`，并在重试耗尽时自动续跑。 |

## 核心状态与文件

- 心跳文件：`logs/watchdog.pid`（退出时自动清理）
- 运行日志：`logs/agy_watchdog.log`
- Python 解释器解析：优先 `-PythonExe` → `$env:AGY_HARNESS_PYTHON` → `PATH` 中的 `python` / `python3`

## 上下游关系

- **上游启动方**：`../launcher/agy.ps1`（或手动后台启动）
- **下游调用方**：`../hooks/check-context.py`、`../compact/auto-compact-worker.ps1`、`../injector/send-console-input.ps1`
