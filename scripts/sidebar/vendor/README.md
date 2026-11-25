# Sidebar Offline Vendor Assets (`scripts/sidebar/vendor/`)

存放侧边栏离线运行所需的第三方开源前端静态资源，由 `../sidebar_server.py` 通过 `/vendor/` 路由直接下发，运行时不依赖外网 CDN 或 Node.js 构建工具。

## 目录结构

| 子目录 | 组件与版本 | 用途 |
| :--- | :--- | :--- |
| `katex/` | KaTeX `0.16.21`（含 `copy-tex` 扩展与 `fonts/*.woff2` 字体） | 本地毫秒级渲染 `$` 与 `$$` 数学公式，并支持划选复制还原原始 LaTeX。 |
| `marked/` | marked `15.0.7` | GFM Markdown 解析。 |
| `mermaid/` | Mermaid `11.4.1` | 离线渲染 `mermaid` 代码块为可缩放矢量图。 |

## 更新或重新拉取

如需重新下载或升级版本，运行上级目录的幂等拉取脚本：

```powershell
.\scripts\sidebar\fetch-vendor.ps1
```

详细服务端与前端集成说明见 [`../README.md`](../README.md)。
