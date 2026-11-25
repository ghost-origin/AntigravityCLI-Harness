# Sidebar Web Frontend (`scripts/sidebar/web/`)

侧边栏纯静态前端实现，由 `../sidebar_server.py` 经 `/` 与 `/static/` 路由直接提供服务，零构建步骤、完全离线运行。

## 文件说明

| 文件 | 作用 |
| :--- | :--- |
| `index.html` | 侧边栏页面骨架：顶部会话自定义下拉框、筛选与主题栏、剪贴板图片预览条、消息流容器、图片与 SVG 灯箱及右键上下文菜单。 |
| `styles.css` | 深浅双色主题变量与排版体系：高对比链接蓝、暖金加粗、淡紫斜体、薄荷绿行内代码胶囊，以及公式块与 Mermaid 悬浮工具条样式。 |
| `math_markdown.js` | Markdown 与数学预处理管线：先保护围栏与行内代码块，再按货币安全规则提取 `$` 与 `$$` 公式交由 KaTeX 渲染，同时改写本地图片路径并封装 `mermaid` 代码块。 |
| `app.js` | SSE 实时订阅控制器：管理会话下拉列表、左键切换与右键新标签页打开、单公式与整条 Markdown 复制、Mermaid 异步 SVG 渲染与主题重绘、灯箱放大及自动滚动锁定。 |

## 上游依赖

- 离线前端库：[`../vendor/README.md`](../vendor/README.md)
- 服务端接口与窗口贴靠：[`../README.md`](../README.md)
