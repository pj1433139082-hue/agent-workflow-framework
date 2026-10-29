# 项目启动助手诊断

公开助手的前置失败使用结构化 `error.code` 和退出码 2，不回显原始参数或定位记录。按原因处理，不把所有失败都理解成需要重新提供框架目录。

## 助手前置错误（Helper Errors）

| 错误类别 | 下一步 | 不表示什么 |
| --- | --- | --- |
| `python_version` | 核对工具兼容声明，改用已核验的工具解释器；当前工具要求 Python ≥3.11 | 不要求业务项目升级 Python，也不证明框架目录缺失 |
| `helper_arguments_error` | 看助手 `--help` 并修正助手参数（注意 `--framework` 需置于 `--` 前） | 不表示框架目录不可用；转交 CLI 的参数由 CLI 判断 |
| `framework_location_error` | 核对本机定位记录或本地 checkout；必要时只补一次 `--framework` | 不下载框架，不覆盖业务项目，不泄漏定位正文 |
| `framework_invocation_error` | 核对已定位工具的可执行文件及访问条件；写入结果不明时先查同一任务状态 | 不宣称项目未创建，也不自动重放原操作 |

合法定位和帮助保持原有公开输出；助手使用参数列表转发，不经 shell。已运行 CLI 的输出、退出码和部分完成回执直接保留。收到 `completion` 表示事实已完成、索引不完整时，只按回执修复索引，不重复原写入。

## 助手参数的位置规则

助手自己的选项（`--framework`、`--locate`）必须写在 `--` **之前**：助手用 `argparse.REMAINDER` 接收 `command`，`--` 之后的一律原样转发给框架 CLI。位置写反时助手报 `helper_arguments_error` 并以退出码 2 结束，这不是框架目录缺失：

```text
正确：python <本技能目录>/scripts/start_project.py --framework <框架目录> -- <子命令> <参数…>
错误：python <本技能目录>/scripts/start_project.py -- <子命令> --framework <框架目录>
```

## 框架 CLI 的非助手错误（Workflow Errors）

下表是框架 CLI 执行阶段返回的 `WorkflowError`。同样以 `{"ok": false, "error": {"code", "message"}}` 和退出码 2 返回，命中时按类别对症处理，**切勿当成助手定位失败或框架目录不可用**：

| 错误代码 (`error.code`) | 含义与产生原因 | 下一步处置 |
| --- | --- | --- |
| `task_exists` | 目标任务目录（如 `tasks/kickoff/`）已存在 | **不要用同一 task-id 重跑 start/adopt**。想接着既有任务干 → 改用 `status` / `context` 续接，不写盘；想在同一工作区加一条新任务 → 传 `--task-id <新ID>`，但这会真建新的任务目录（已纳管项目上会新增 `AGENTS.framework.md`；既有 `.agent-workflow.local.json` 会被保留，零配置导航仍指向原任务），执行前先确认用户要的是后者。 |
| `workspace_exists` | 执行 `start` 时工作区目录已存在 | 若需纳管既有代码，改用 `adopt`；若是新项目，更换尚不存在的目标路径。框架不覆盖任何已有文件。 |
| `workspace_not_found` | 执行 `adopt` 或后续命令时目标目录不存在 | 检查工作区绝对路径是否拼写错误或盘符不符。 |
| `transition_blocked` | 推进阶段（`advance`）时前置检查未满足 | 运行 `context --check` 检查缺失事实或未通过门禁；编辑 `payload.json` 或 `plan.md` 后运行 `context --write` 重建索引再推进。 |
| `invalid_decision` | `decision` 提交的 ID 或选项不存在 | 运行 `status` 检查当前阶段待决项（`pending_decisions`）及合法选项值。 |
| `invalid_arguments` | 传递给框架 CLI 的参数不合法（如缺少必填参数） | 检查各子命令的参数契约，不要遗漏必填的 `--project-id`、`--task-id` 等参数。 |
| `private_workspace_required` | 试图将框架源码目录作为业务工作区 | 业务项目必须独立于框架源码 checkout 之外。 |
| `invalid_mode` | 交互档位不合法 | 档位仅支持 `assisted`、`full-auto`、`manual-review` 之一。 |
| `invalid_project_facts` | 已有 `project.json` 损坏或格式不符 | 检查工作区根目录 `project.json`，确保包含 `schema_version: "1.0"` 与 `project_id`。 |
| `project_identity_mismatch` | 工作区已有 `project.json`，其 `project_id` 与本次 `--project-id` 不同 | 一个工作区只对应一个项目身份。改用已有 ID 续接，或换一个工作区；该命令在写入前就停止，没有文件被改动，不要反复试错。 |

这些诊断不安装业务环境、不改系统默认解释器、PATH、代理或 VPN。工具自检或骨架创建成功也不等于业务环境已经配置或运行通过。
