# 技能配置模板与 tracker 选定验收

日期：2026-10-09。对应规格 #14、票据 #15、PR #17。仅记录本地框架工具、合成工作区与公开子进程结果，不代表业务环境、任意智能体实现或真实部署验收。31–39 历史记录未改写，其中 33 号“默认仍生成 14 个文件”是当时的历史事实，本次起默认必选文件为 16 个；当前操作方法见[验收清单](30-验收清单.md)。

## 环境与命令

从框架源码 checkout 根目录执行。本机工具解释器为 Windows Python 3.13.9，经 `--version` 与 doctor 核对。该版本不属于 39 号记录的 3.11.15 / 3.14.2，也不是 CI 矩阵成员；本轮未调用 uv 的 3.11 解释器或 WSL，矩阵结论以远端 CI 为准。不安装新解释器，不改默认 Python、PATH、代理或 VPN。

```bash
python --version                      # Python 3.13.9
python -m agent_workflow doctor
python -m unittest discover -s tests
python scripts/check_repository.py
python -m ruff check .
python -m mypy agent_workflow/cli.py agent_workflow/project_documents.py agent_workflow/project_start.py \
  tests/test_project_start.py tests/test_project_documents.py \
  tests/test_project_document_completion.py tests/test_cold_start_acceptance.py
git diff --check
```

doctor 返回 runtime_scope=framework_tools_only、business_runtime_constraint=null、business_runtime_checked=false。

## 从空目录实走

合成工作区基目录为本机 TEMP 下 `awf-acceptance-1791557902`，三个子目录 u（未选定）、g（github）、bad（非法值），项目 ID 均为 synthetic-*，任务 ID kickoff，全部使用默认档位。创建前三个目录都不存在。

| 实际命令 | 退出码与公开结果 | 读写差异 |
| --- | --- | --- |
| `start <u>` 默认预览 | 0，applied=false；project_files 11 项；issue_tracker={selected:null,file:null} | 目录未创建，零写入 |
| `start <u> --apply` | 0，applied=true；未选定 tracker | 16 个文件；`docs/agents/` 只有 triage-labels.md 与 domain.md，issue-tracker.md 不存在 |
| `start <g> --tracker github --apply` | 0，issue_tracker={selected:github,file:docs/agents/issue-tracker.md} | 17 个文件；该文件含 GitHub Issues 约定，不含 `.scratch/` 字样，两变体未混用 |
| `project-docs <u> --tracker local` 预览 | 0，applied=false；progress pending=[issue-tracker] | 零写入，文件仍不存在 |
| 同命令 `--apply` | 0，created=[issue-tracker] | 只新建缺失那一份 |
| 再跑 `--tracker github --apply` | 0，preserved=[issue-tracker] | 既有文件逐字节保留：local 标记 4 处、github 标记 0 处，未被改写成另一种变体 |
| `project-docs <u>`（两项都不给） | 2，error.code=invalid_arguments | 零写入 |
| `start <bad> --tracker jira --apply` | 2，invalid_arguments | 目录未创建 |

`--tracker` 未选定时的回执不谎报已选定；`project-docs` 回执的 issue_tracker 只描述本次请求选了什么，是否写入看 progress。

## 双轴审查与处置

Standards 与 Spec 两路独立审查（只读子智能体，各自不超过 400 字）共提出 12 项，处置如下：

| 发现 | 处置 |
| --- | --- |
| ADR 0004 写入本机真实仓库名，抵触 AGENTS.md“不收录真实业务资产” | 已改：删去全部仓库名，改为“五个既有仓库、已配置任务落点的四个里两种各占两个” |
| 规格要求“文件数变化写进新的验收记录”，PR 未含新记录 | 已改：本文件 |
| ADR 边界示例用现在时描述 `--with-docs claude`，而该取值属 #16 尚未实现 | 已改：标注为 #16 落地后的行为，并说明当前传入会被参数校验拒绝 |
| ADR“五个仓库…各占一半”只列出 4 个，计数不自洽 | 已改：明确第五个尚未配置 |
| start 回执有 `undecided`、project-docs 没有，且该字段可由 selected 推出 | 已改：删除 `undecided`，两个命令回执同为 {selected, file} |
| tracker 装配形状在 start 与 complete 两处重复 | 已改：抽出 `project_start.tracker_render`，两处调用 |
| 三份新模板与框架自身 `docs/agents/` 近逐字相似，可能漂移 | 未改，判断保留：两者受众不同（生成项目 / 框架本体），标签词汇按仓库约定本就是同一套五角色；漂移风险记在此处，后续如分化再抽公共来源 |
| 新错误码 `invalid_project_tracker` 经公开 CLI 不可达 | 未改：与既有 `select_documents` 同型，属 Python API 层防御；CLI 层由 argparse choices 拦成 invalid_arguments，两条路径都有测试 |
| `AGENTS.md.tmpl` 新增 docs/agents 说明段未经规格逐条授权 | 未改：必选文件新增后入口必须指明其存在，属票据第 1 条的必要衔接，无私人工具链内容 |
| complete() 对 project_start 取数增至多处，可能 Feature Envy | 部分改：抽出 tracker_render 后减少两处常量引用；剩余取数与既有 OPTIONAL_DOCUMENTS 用法同型 |

## 验证状态

| 状态 | 本次事实 |
| --- | --- |
| 通过 | 本机 3.13.9：doctor 退出 0；`unittest discover -s tests` 73 项通过、2 项条件跳过、190.571 秒；check_repository ok、files_checked 89、issues 空；Ruff All checks passed；`git diff --check` 无空白错误。远端 CI（PR #17）ubuntu/windows × 3.11/3.14 共 8 项检查全 SUCCESS，两次运行 37946038848 与 37946149784 |
| 失败 | mypy 对本轮涉及的 7 个文件报 5 处错误，全在 tests/test_project_documents.py 的 80、81、191、196 行。对 origin/main 版本单跑 mypy 得到同样 5 处、行号 77、77、78、188、193，与 39 号记录一致；本 PR 只在该文件上方新增 3 行导致行号平移。属既有问题，本轮未引入也未修复，因此不声称“全部类型检查通过” |
| 未执行 | 本机 3.11 / 3.14 与 Linux 解释器未运行；技能源变更后的本机分发未执行（`.skillshare/skills/project-start/` 已改，安装源与 Codex/Claude 入口仍是旧版）；受信任客户端 hook 实际触发未验证；#16（CLAUDE.md 指针化）未实施 |
| 不适用 | 真实项目迁移、既有项目覆盖、业务运行时配置、远端仓库创建与部署；均不在本票范围 |

合成工作区留在框架外的本机 TEMP，不上传其资料。框架业务包、SOP、pack_digest 语义、任务契约与 31–39 历史记录均未改。
