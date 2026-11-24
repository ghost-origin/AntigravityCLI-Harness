# Console Input Injector Layer (`scripts/injector/`)

底层控制台输入注入层：封装 Windows Kernel32 控制台 API，实现**不抢占窗口焦点、不依赖剪贴板/模拟按键**的定向终端输入注入。

## 文件说明

| 文件 | 作用 |
| :--- | :--- |
| `send-console-input.ps1` | 调用 `FreeConsole` → `AttachConsole(pid)` → `CreateFileW("CONIN$")` → `WriteConsoleInputW` 向目标进程控制台写入 `KEY_EVENT_RECORD` 序列并附加回车；支持 `-TextBase64`（UTF-8 Base64）彻底规避 PowerShell 5.1 参数空格拆词与多语言字符转义问题，并将每次注入结果（`ok` / `stage` / `err`）追加记录到 `logs/send_console_input.log`。 |

## 常用参数

- `-ProcessId <int>`：目标控制台进程 PID（必填）
- `-TextBase64 <string>` / `-Text <string>`：待注入文本（含空格或中文时推荐使用 `-TextBase64`）
- `-EnterCount <int>`：尾部回车次数（默认 `1`，实测适配 `agy.exe` 单次回车提交）
- `-CharDelayMs <int>`：字符间延迟毫秒数（默认 `0` 批量写入）

## 上下游关系

- **上游调用方**：`../compact/auto-compact-worker.ps1`、`../watchdog/agy-watchdog.ps1`
- **无下游脚本依赖**：纯 Win32 P/Invoke 原语层，可独立测试和复用。
