# Launcher Layer (`scripts/launcher/`)

CLI 启动封装层：负责以与网络/代理层解耦的方式启动 `agy.exe`，并自动联动拉起和清理 `watchdog` 守护进程。

## 文件说明

| 文件 | 作用 |
| :--- | :--- |
| `agy.ps1` | 定义 `function agy` 与 `function agy-sidebar`：从 [`../../Config/`](../../Config/README.md) 读取默认路径，隐藏启动 `../watchdog/agy-watchdog.ps1 -WaitForNew`，按单窗口复用规则拉起 `../sidebar/launch-sidebar.ps1`，识别 `-r` / `--resume` 恢复会话并在退出时自动清理自有进程。 |
| `agy-stable.ps1` | PowerShell 脚本入口，dot-source `agy.ps1` 并透传 `@args`。 |
| `agy-stable.cmd` | CMD 入口，调用 `agy-stable.ps1` 并透传 `%*`。 |

## 推荐使用方式

在 PowerShell `$PROFILE` 中添加一行 dot-source（一次配置）：

```powershell
. "<REPO_PATH>\scripts\launcher\agy.ps1"
```

重载 `$PROFILE` 或新开终端后，在任意目录直接执行 `agy` 即可自动启动 `agy-watchdog.ps1` 与 `agy.exe`，退出时自动清理 watchdog，无需手动运行 `.ps1`。

若不希望修改 `$PROFILE`，也可临时通过 `agy-stable.ps1`（PowerShell）或 `agy-stable.cmd`（CMD）启动。

## 上下游关系

- **下游依赖**：`../watchdog/agy-watchdog.ps1`
- **网络解耦原则**：本层不管理任何代理端口、路由或 `HTTP_PROXY`/`GODEBUG`；网络环境由宿主机或用户的 shell profile 独立管理。
