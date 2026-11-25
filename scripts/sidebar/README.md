# Sidebar Layer (`scripts/sidebar/`)

面向 Windows Terminal 与 `agy` 的低依赖公式、Mermaid 与图片实时预览侧边栏：复用 Windows 原生 Microsoft Edge 无边框应用模式、Python 3 标准库 SSE 微服以及离线内置静态前端资产，无需 Node.js、Electron 或第三方 Python 包。

## 核心文件

| 文件 | 作用 |
| :--- | :--- |
| `transcript_watcher.py` | 解析 `transcript_full.jsonl`、`annotations/*.pbtxt` 与 `conversation_metadata.json`，提取会话概括标题、工作目录、回复正文与 `USER_INPUT.media` 贴图，并经 Win32 `ctypes` 轻量监听剪贴板图片。 |
| `window_docker.py` | 启用 Per-Monitor V2 DPI 感知，基于 Win32 DWM 可见边框将 Windows Terminal 与 Edge 侧边窗融合为统一窗口，支持双向无漂移跟随、交界线保总宽拖拽、串流切分辨率自动重贴靠与标签页标题切换联动。 |
| `sidebar_server.py` | 纯 Python 标准库 HTTP 与 SSE 服务，提供 `/api/events`、`/api/snapshot`、`/api/media`、`/api/dock`、`/api/open-terminal` 与 `/api/shutdown` 接口。 |
| `launch-sidebar.ps1` | 启动本地微服与 Edge 应用窗并完成句柄贴靠，内置按终端窗口句柄的单实例复用保护。 |
| `fetch-vendor.ps1` | 幂等拉取或更新离线第三方前端库至 `vendor/`。 |

## 子目录导览

- [`web/`](web/README.md)：前端页面、深浅配色样式、Markdown 与 `$` / `$$` 公式解析、Mermaid 渲染与交互逻辑。
- [`vendor/`](vendor/README.md)：离线内置的 `KaTeX`、`copy-tex`、`marked` 与 `mermaid` 静态资源清单与更新方式。

## 使用与唤醒方式

- **随 `agy` 自动联动**：通过 [`../launcher/agy.ps1`](../launcher/agy.ps1) 启动 `agy` 时自动贴靠，退出时自动关闭。
- **终端命令手动唤醒**：在 PowerShell 中执行 `agy-sidebar` 或 `.\scripts\sidebar\launch-sidebar.ps1`。
- **对话内斜杠命令唤醒**：安装 [`../../skills/sidebar/SKILL.md`](../../skills/sidebar/SKILL.md) 后，可在 `agy` 中直接输入 `/sidebar`、`/sidebar restart` 或 `/sidebar stop`。
- **右键多标签页联动**：左键会话列表项切换当前侧边栏预览；右键会话项可通过 `wt.exe -w 0 new-tab` 在同一 Windows Terminal 新建标签页恢复该会话，点击不同标签页时侧边栏自动跟随切换。

## 配置项

所有路径与默认宽度比例集中由 [`../../Config/README.md`](../../Config/README.md) 中的 `[sidebar]`、`[antigravity]` 与 `[executables]` 管理，并支持环境变量 `AGY_SIDEBAR`、`AGY_SIDEBAR_WIDTH_RATIO`、`AGY_SIDEBAR_NO_DOCK` 与 `AGY_SIDEBAR_BROWSER` 覆盖。
