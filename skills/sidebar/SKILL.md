---
name: sidebar
description: >-
  Launch, focus, restart, or stop the Antigravity CLI LaTeX, Mermaid, and image preview
  sidebar (<REPO_PATH>/scripts/sidebar/) directly from agy via /sidebar. Use whenever the
  user invokes /sidebar or asks to open, refresh, dock, or close the formula preview sidebar.
---

# Sidebar（`/sidebar` 快捷唤醒公式与图片侧边栏）

> **Setup note**: Replace `<REPO_PATH>` with your local AntigravityCLI-Harness path before copying this folder to `~/.gemini/config/skills/sidebar/`.

本 Skill 将仓库中的 `scripts/sidebar/` 侧边栏能力注册为 Antigravity CLI 原生斜杠命令 `/sidebar`，支持在任意对话中随时唤醒、重启或关闭右侧公式、Mermaid 与图片预览栏。

## 1. 支持的触发指令

- `/sidebar` 或 `/sidebar open`：唤醒并贴靠侧边栏到当前 Windows Terminal 右侧，自动切换到当前会话。若该终端已存在共享侧边栏，则直接复用并切换会话，不重复弹窗。
- `/sidebar restart`：先优雅关闭当前终端绑定的旧侧边栏，再以最新配置重新拉起。
- `/sidebar stop`：优雅关闭当前侧边栏与后台本地服务。

## 2. 执行步骤

### A. 打开或复用侧边栏（默认 `/sidebar`）

使用 `run_command` 并设置 `BypassSandbox: true` 与 `IsDaemon: true` 运行以下命令，其中 `<conversation_id>` 替换为当前会话 ID，以确保侧边栏在回复结束后继续常驻直到用户手动关闭：

```powershell
$stateFile = '<REPO_PATH>\tmp\sidebar_state_slash.json'
$out = & '<REPO_PATH>\scripts\sidebar\launch-sidebar.ps1' -ConversationId '<conversation_id>' -StateFile $stateFile
Write-Output $out
if (($out -notlike 'REUSED:*') -and (Test-Path $stateFile)) {
    $st = Get-Content $stateFile -Raw | ConvertFrom-Json
    if ($st.pid) { Wait-Process -Id ([int]$st.pid) -ErrorAction SilentlyContinue }
}
```

- 若输出以 `REUSED:` 开头，说明当前终端已有共享侧边栏且已自动切换到本会话，守护命令会立刻正常结束。
- 若输出为 `http://127.0.0.1:<port>`，说明已拉起新侧边栏，并会在用户关闭侧边栏窗口时自动退出守护进程。

### B. 重启侧边栏（`/sidebar restart`）

先执行关闭，再按步骤 A 重新拉起：

```powershell
Get-ChildItem '<REPO_PATH>\tmp\sidebar_docks' -Filter 'dock_*.json' -ErrorAction SilentlyContinue | ForEach-Object {
    try {
        $d = Get-Content $_.FullName -Raw | ConvertFrom-Json
        if ($d.url) {
            $req = [System.Net.HttpWebRequest]::Create($d.url.TrimEnd('/') + '/api/shutdown')
            $req.Method = 'POST'; $req.Timeout = 1500; $req.Proxy = [System.Net.GlobalProxySelection]::GetEmptyWebProxy(); $req.ContentLength = 0
            $r = $req.GetResponse(); $r.Close()
        }
    } catch {}
    Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
}
```

### C. 关闭侧边栏（`/sidebar stop`）

调用 `run_command`（`BypassSandbox: true`）执行：

```powershell
& '<REPO_PATH>\scripts\sidebar\launch-sidebar.ps1' -Stop -StateFile '<REPO_PATH>\tmp\sidebar_state_slash.json'
```

## 3. 进一步细节

- 配置路径与默认宽度比例由 `<REPO_PATH>\Config\harness.config`（模板为 `harness.config.example`）统一管理。
- 架构与模块说明见 `<REPO_PATH>\scripts\sidebar\README.md`。
