# CLI 配置与数据目录

## 实施范围与顺序

1. 增加统一运行上下文，确定配置、密钥、SQLite 和运行产物的路径与优先级。
2. 增加 `config init/show/reset`、`paths`，取消隐式搜索当前目录的 `.env`。
3. CLI、交互向导与 MCP 共用目录；每次运行独立产物目录，保存运行索引与可导出的报告附件。
4. 增加明确的清理和卸载命令；保护外部目录与符号链接目标。
5. 用隔离目录做配置、异常路径和浏览器回归，并从项目外验证正式 wheel。

当前项目目录中的数据库、`.auth.key`、报告和生成测试均为开发数据，**不扫描、不迁移、不自动删除**。

## 默认目录

Linux 和 macOS 均使用 `~/.config/webaudit/`：

```text
~/.config/webaudit/
├── .webaudit-home                 # 本工具创建的管理标识
├── config.toml                   # 服务商、模型、接口和默认步数
├── credentials/
│   ├── .auth.key                 # 网站登录凭据加密密钥，使用时才创建
│   ├── keyring.json              # 使用系统凭据库的标识，不包含密钥
│   └── api_keys.json             # 仅显式选择文件存储时存在
├── data/
│   ├── webaudit.sqlite           # 会话、运行索引、网站凭据、浏览器认证状态
│   ├── baselines/                # 开启视觉回归时创建
│   └── runs/<session-id>/<run-id>/
│       ├── report.md
│       ├── screenshots/
│       ├── generated-tests/<category>/
│       └── test-execution-*.md    # 开启生成测试执行时产生
├── logs/                         # 预留，当前诊断输出到 stderr
└── cache/                        # 预留；不包含安装工具或 Playwright 的缓存
```

安装包时不创建这些目录。`--help`、`--version`、`paths`、`config show` 只读；`config init` 创建配置和必要的凭据，不创建数据库。实际运行或访问历史会话时才创建数据库；报告、截图和测试按使用情况创建。

目录权限为 0700；配置、密钥和数据库为 0600。系统凭据库优先，用户也可以使用环境变量。系统凭据库不可用时明确报错，不自动降级到明文文件。

## 初始化与配置

```bash
webaudit config init
webaudit config show --sources
webaudit paths
```

初始化依次询问服务商、接口地址、模型和 API key（隐藏输入）。默认写入系统凭据库；留空密钥保留已有凭据或使用环境变量。无系统凭据库时可明确选择：

```bash
webaudit config init --secret-storage file
```

文件方式会显示明文存储提示。`config.toml` 不保存 API key。密钥按 home 目录隔离，卸载只清理对应凭据。仅使用环境变量时也可以无需初始化直接运行；自动优先选择 OpenAI，再选择 Gemini。多个服务商同时配置时建议显式选择服务商。

```bash
export OPENAI_API_KEY='your-key'
webaudit config init --non-interactive --provider openai --model gpt-4o-mini
```

非交互初始化不持久化环境中的密钥。更新已有配置使用 `--force`。OpenAI 兼容的本地服务允许在提供接口地址时不设置密钥。

配置优先级为命令参数 > 环境变量 > TOML > 默认值。支持 `WEBAUDIT_PROVIDER`、`WEBAUDIT_MODEL`、`WEBAUDIT_MAX_STEPS`、`WEBAUDIT_MAX_FAILURES`。OpenAI 支持 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`；兼容旧变量 `OPEN_AI_API_KEY`、`OPEN_AI_API_URL`、`OPEN_AI_MODEL`，新名称优先。两种密钥同时设置且不同会告警，但不显示值。Gemini 使用 `GOOGLE_AI_STUDIO_API_KEY`、`GEMINI_MODEL`。

不再自动读取项目或当前工作目录的 `.env`。开发时显式加载：

```bash
uv run webaudit --env-file .env run https://example.com --max-steps 10 --json
```

已有环境变量优先于 `.env`。配置来源可以用 `config show --sources` 查看，密钥内容不会显示。

## 自定义目录

全局选项放在子命令之前：

```bash
webaudit --home /path/to/webaudit config init
webaudit --home /path/to/webaudit run https://example.com
webaudit --data-dir /path/to/data run https://example.com
webaudit --config /path/to/config.toml config show
```

- `--home` / `WEBAUDIT_HOME`：改变整个根目录，方便隔离开发、测试及不同配置。
- `--data-dir` / `WEBAUDIT_DATA_DIR`：只改变 SQLite、运行产物及视觉基线的目录；配置和密钥仍在 home。
- TOML 中 `[storage] data_dir`：指定数据目录，相对路径以配置文件所在目录为基准。

数据目录优先级为 `--data-dir` > `WEBAUDIT_DATA_DIR` > `[storage] data_dir` > `<home>/data`。命令参数和环境变量的相对路径按当前工作目录解释。

## 报告与生成测试

每次运行获得独立 `runId`，即使恢复同一个 session，也保留之前的报告。JSON 结果包含 `runId`、`artifactDir`、`reportPath`（绝对路径）。截图引用使用相对路径；报告打包时会复制需要的历史截图。

```bash
webaudit run https://example.com --max-steps 10 --output-dir ./exports --json
webaudit report --list
webaudit report <session-id>
webaudit report <session-id> --run-id <run-id> --output-dir ./exports
webaudit test
webaudit test /path/to/generated-tests
```

导出到 `<output-dir>/<session-id>/<run-id>/`，复制报告及所有附件，原始产物保留。指定历史运行时读取历史报告；文件丢失会报错，不用当前会话状态替代历史内容。

`webaudit test` 默认遍历数据目录下全部运行的 `*_spec.py`，指定路径可只测试某次运行。MCP 使用同一套 home/data 规则；直接启动 `python -m src.mcp.index` 时通过环境变量设置目录，不加载隐式 `.env`。

## 清理与卸载

```bash
webaudit clean --runs --session-id <id> --dry-run
webaudit clean --runs --before 2026-10-01 --yes
webaudit clean --cache --logs --yes
webaudit clean --credentials --yes
webaudit config reset --yes
webaudit uninstall
```

`clean` 默认展示范围并要求确认，`--dry-run` 只预览。日期按 UTC，依据产物文件修改时间。清理运行产物同步删除运行索引、清除已失效附件引用，保留可恢复的探索状态。清理凭据删除对应系统 API key、凭据文件、数据库中的网站凭据和浏览器认证状态；环境变量不受影响。重置配置仅删除当前配置文件，保留数据和凭据。

`uninstall` 按用户约定直接删除当前 home 目录及其中所有内容，并清除该 home 对应的系统凭据。根目录外的自定义数据、配置和导出副本保留，并显示保留路径。不存在目录时无操作；没有管理标识、home 根本身是符号链接或指定系统根目录/用户目录/当前目录时拒绝删除。目录内部的符号链接只删除链接，不递归删除目标。

此命令清理 WebAudit 配置与数据，不移除安装包。程序卸载使用原安装工具，例如：

```bash
uv tool uninstall web-audit-agent
```
