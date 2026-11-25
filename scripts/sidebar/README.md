# Sidebar Layer (`scripts/sidebar/`)

面向 Windows Terminal 与 `agy` 的低依赖公式与图片实时侧边栏：复用 Windows 原生 Microsoft Edge 无边框应用模式、Python 3 标准库本地微服以及离线内置的开源 `KaTeX`、`copy-tex` 与 `marked.js`，无需 Node.js、Electron 或第三方 Python 包。

## 文件说明

| 文件 | 作用 |
| :--- | :--- |
| `transcript_watcher.py` | 扫描并解析 `~/.gemini/antigravity-cli/brain/*/transcript_full.jsonl`，提取对话正文与 `USER_INPUT.media` 贴图路径，并通过 Win32 `ctypes` 轻量监控剪贴板图片变化。 |
| `window_docker.py` | 基于 Win32 DWM 可见边框将 Windows Terminal 与 Edge 侧边栏融合为统一窗口：保留终端原始大小无缝贴合右侧，支持双向拖动跟随、拖拉交界线维持总宽度不变以及最小化与置顶层级联动。 |
| `sidebar_server.py` | 纯 Python 标准库本地 HTTP 与 SSE 服务，负责推送实时会话更新、代理本地图片 `/api/media`、管理窗口贴靠 `/api/dock`、输出剪贴板预览图并响应优雅关闭信号。 |
| `launch-sidebar.ps1` | 启动本地微服与 Edge 应用窗，并将终端与侧边窗句柄交给 `/api/dock` 自动贴靠，支持 `-Stop` 优雅关闭。 |
| `fetch-vendor.ps1` | 幂等下载或更新离线 `KaTeX`、字体、`marked.js` 与 `mermaid.min.js` 至 `vendor/`。 |
| `web/` | 侧边栏前端页面，负责保护代码块与货币符号、解析 `$` / `$$` 公式与 `mermaid` 图表、提供单公式与整段 Markdown 复制以及图片与图表灯箱放大。 |

## 使用方式

### 1. 随 `agy` 自动启动

配置好 [agy.ps1](../launcher/agy.ps1) 后，在 Windows Terminal 中直接运行 `agy` 即会自动在右侧打开侧边栏，并在退出 `agy` 时优雅关闭。

如需临时关闭自动拉起侧边栏，可设置环境变量：

```powershell
$env:AGY_SIDEBAR = '0'
```

### 2. 手动独立启动或重新打开

在任意 PowerShell 窗口中运行：

```powershell
agy-sidebar
```

或直接调用脚本：

```powershell
.\scripts\sidebar\launch-sidebar.ps1
```

## 可选环境变量

- `AGY_SIDEBAR`：设为 `0` 时禁用 `agy` 自动启动侧边栏，默认开启。
- `AGY_SIDEBAR_WIDTH_RATIO`：侧边栏占当前显示器工作区宽度的比例，默认 `0.38`，范围 `0.25` 至 `0.55`。
- `AGY_SIDEBAR_NO_RESIZE`：设为 `1` 时不自动调整左侧 Windows Terminal 窗口尺寸。
- `AGY_SIDEBAR_BROWSER`：显式指定浏览器可执行文件路径，默认优先使用系统自带 `msedge.exe`。
