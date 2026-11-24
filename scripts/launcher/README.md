# Launcher Layer (`scripts/launcher/`)

CLI 启动封装层：负责以与网络/代理层解耦的方式启动 `agy.exe`，并自动联动拉起和清理 `watchdog` 守护进程。

## 文件说明

| 文件 | 作用 |
| :--- | :--- |
| `agy.ps1` | 定义 `function agy`：查找 `agy.exe`（优先 `$env:AGY_EXE`，否则从 `PATH` 解析），隐藏启动 `../watchdog/agy-watchdog.ps1 -WaitForNew`，透传参数运行 `agy.exe`，并在 CLI 退出时自动终止对应的 watchdog 进程。 |
| `agy-stable.ps1` | PowerShell 脚本入口，dot-source `agy.ps1` 并透传 `@args`。 |
| `agy-stable.cmd` | CMD 入口，调用 `agy-stable.ps1` 并透传 `%*`。 |

## 上下游关系

- **下游依赖**：`../watchdog/agy-watchdog.ps1`
- **网络解耦原则**：本层不管理任何代理端口、路由或 `HTTP_PROXY`/`GODEBUG`；网络环境由宿主机或用户的 shell profile 独立管理。
