# Config Layer (`Config/`)

统一集中管理整个仓库的路径与运行时默认配置，避免各脚本重复硬编码路径，并将可公开推送的标准模板与本机真实配置彻底隔离。

## 文件说明

| 文件 | 是否入库 | 作用 |
| :--- | :--- | :--- |
| `harness.config.example` | 入库模板 | 标准配置模板，仅含 `${REPO_ROOT}` 与 `${USERPROFILE}` 通用占位符，不含任何本机路径或敏感信息，clone 后即开箱可用。 |
| `harness.config` | 已忽略 | 本机真实运行配置文件，已被 `.gitignore` 忽略，按需复制模板后填入本机 `agy_exe`、`python_exe` 等实际路径。 |
| `*.local.config` | 已忽略 | 可选额外本地覆盖文件，已被 `.gitignore` 忽略。 |
| `load-config.ps1` | 入库 | PowerShell 配置加载器，按模板到本机配置的顺序叠加加载。 |
| `config_loader.py` | 入库 | Python 标准库配置加载器，供 `hooks` 与 `sidebar` 服务端复用。 |

## 初始化本机配置

```powershell
Copy-Item .\Config\harness.config.example .\Config\harness.config
```

## 优先级规则

由高到低依次为：脚本显式命令行参数 > 环境变量 > `Config/harness.local.config` > `Config/harness.config` > `Config/harness.config.example`。
