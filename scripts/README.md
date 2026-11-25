# Scripts Layer Index (`scripts/`)

本目录按职责将 AntigravityCLI-Harness 的自动化脚本拆分为六个低耦合子层，遵循渐进式披露原则：顶层只列出各层职责边界，具体文件说明与调优参数分别下沉至各子目录的 `README.md`。

## 子层导航

| 子目录 | 职责 | 详细文档 |
| :--- | :--- | :--- |
| `launcher/` | CLI 启动封装层，提供 `agy` 与 `agy-sidebar` 命令入口并管理伴随进程生命周期。 | [launcher/README.md](launcher/README.md) |
| `hooks/` | Antigravity 原生 `PreInvocation` / `Stop` 钩子与只读上下文 token 度量。 | [hooks/README.md](hooks/README.md) |
| `watchdog/` | 宿主机侧非阻塞守护进程，轮询压缩信号并监听 `cli-*.log` 的 EOF 断流。 | [watchdog/README.md](watchdog/README.md) |
| `compact/` | `/compact` 请求入队、原子认领、硬冷却防重入与 `CHECKPOINT` 后自动续跑。 | [compact/README.md](compact/README.md) |
| `injector/` | Win32 底层控制台输入原语，不抢占焦点向运行中 `agy` 进程注入指令。 | [injector/README.md](injector/README.md) |
| `sidebar/` | 离线 KaTeX 公式、Mermaid 图表与贴图实时预览侧边栏，以及 DWM 统一窗口贴靠。 | [sidebar/README.md](sidebar/README.md) |

## 统一路径配置

全部脚本的默认路径均由根目录 [`Config/`](../Config/README.md) 统一管理，优先读取被忽略的本机配置 `Config/harness.config`，缺省回退至入库模板 `Config/harness.config.example`。
