# Auto-Compact Orchestration Layer (`scripts/compact/`)

自动压缩调度与执行层：负责压缩请求的生成、原子认领、防重入冷却、空闲态注入 `/compact`，以及 `CHECKPOINT` 落盘后的自动续跑。

## 文件说明

| 文件 | 作用 |
| :--- | :--- |
| `request-compact.ps1` | 压缩请求下发入口：预记录当前 `cli-*.log` 路径与字节偏移（`log_offset` 消除冷启动竞态），生成 `tmp/compact_request.json`；watchdog 在线时采用 `queue` 模式入队，否则采用 `direct` 模式直接拉起 worker。 |
| `auto-compact-worker.ps1` | 压缩执行器：通过 `Move-Item` 原子认领请求文件防止双触发，校验 `logs/auto_compact_state.json` 硬冷却（默认 120s），等待回合空闲（或 `-AlreadyIdle` 跳过）后调用底层注入器发送 `/compact`；若附带 `resume_prompt`，则轮询 `transcript.jsonl` 直到新 `CHECKPOINT` 出现后再自动注入续跑提示词。 |

## 上下游关系

- **上游调用方**：Agent `auto-compact` skill、`../watchdog/agy-watchdog.ps1`
- **下游调用方**：`../injector/send-console-input.ps1`（统一经 `-TextBase64` 传递文本）
