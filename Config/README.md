# Config Layer (`Config/`)

统一集中管理整个仓库的路径与运行时默认配置，避免各脚本重复硬编码路径。

## 文件说明

| 文件 | 作用 |
| :--- | :--- |
| `harness.config` | 主配置文件，采用标准 INI 分段格式，通过 `${REPO_ROOT}` 与 `${USERPROFILE}` 占位符保持跨机器可移植。 |
| `harness.local.config` | 可选本机覆盖文件，已被 `.gitignore` 忽略，用于存放本机私有路径（例如自定义 `agy_exe` 或 `python_exe`）。 |
| `load-config.ps1` | PowerShell 配置加载器，供 `launcher`、`watchdog`、`compact` 与 `sidebar` 脚本复用。 |
| `config_loader.py` | Python 标准库配置加载器，供 `hooks` 与 `sidebar` 服务端复用。 |

## 优先级规则

由高到低依次为：脚本显式命令行参数 > 环境变量 > `Config/harness.local.config` > `Config/harness.config`。
