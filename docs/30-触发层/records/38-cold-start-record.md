> SYNTHETIC 验收留存，不是业务事实或新状态源。仅将机器路径替换为占位：<CASE_ROOT> 是独立测试根，<PYTHON_311> 是实际 Windows 3.11 解释器；<INITIAL_HOST_WORKSPACE> 是无关的初始宿主目录。命令重放前替换占位，并按每条记录的工作目录执行。原问题、答复、命令参数和结果不改；早期待答段是历史时点，不是当前门禁。前后摘要来自原实测文件，不承诺换机后重建文件的摘要相同。

# SYNTHETIC 商品资料清单项目：冷启动记录

## 当前阶段

已按答复在指定测试根目录创建项目骨架；plan-acceptance 由 `synthetic-user` 接受；scope、plan、decision 检查通过，当前 CLI 阶段为 `ready`。只表示本地启动方案有效，不表示业务系统完成。environment 与 progress 两份辅助骨架已按需创建，保持未填的事实栏。

## 实际读取的入口与规则

1. `framework/AGENTS.md`：要求从协作总览进入，按 `workflow-router` 分流；新项目使用 `project-start` 和公开 `start` 命令；真实项目工作区需在框架仓库外；阶段只表示本地协作进度。
2. `framework/docs/00-入口层/00-协作总览.md`：商品资料审核对应 `ecommerce-catalog`；项目启动流程对应 `project-planning`；档位只是协作节奏；推荐入口顺序包含 doctor、packs 与仓库外工作区。
3. `framework/.skillshare/skills/workflow-router/SKILL.md`：新项目转入 project-start；使用公开 context/status/task-plan；assisted 连续处理已交办的本地工作；本轮结束报告阶段、已验证/未验证和安全下一步。
4. `framework/.skillshare/skills/project-start/SKILL.md`：使用 `start_project.py` 和公开 start；新目录需不存在；默认轻量启动，不要求七张项目卡；创建后从项目自己的 AGENTS.md 接续；先把已知 users、in_scope、out_of_scope、success_criteria 写入 payload，再编辑 plan；自定义 task-id 需用于后续命令。
5. `framework/docs/00-入口层/03-一键启动新项目.md`：`start` 默认预览，明确交办且范围齐全时可加 `--apply`；`--task-id` 可自定义；scope 事实放入 payload；`ready` 只代表启动方案已备齐，不代表业务系统完成。

## 实际命令与结果

以下读取均针对用户指定的只读框架副本，工作目录为 `<INITIAL_HOST_WORKSPACE>`，无框架文件写入。

```powershell
Get-Content -LiteralPath '<CASE_ROOT>\framework\AGENTS.md'
```

结果：读到上述框架入口、技能路由、真实业务范围与阶段语义规则。

```powershell
Get-Content -LiteralPath '<CASE_ROOT>\framework\docs\00-入口层\00-协作总览.md'
```

结果：确认 `ecommerce-catalog` 与 `project-planning` 两类流程边界；项目阶段不能解释为真实上架等外部状态。

```powershell
Get-Content -LiteralPath '<CASE_ROOT>\framework\.skillshare\skills\workflow-router\SKILL.md'
```

结果：确认新项目应交由 `project-start`，并按当前档位完成已交办本地工作。

```powershell
Get-Content -LiteralPath '<CASE_ROOT>\framework\.skillshare\skills\project-start\SKILL.md'
```

结果：确认新目录检查、轻量骨架、payload/plan 事实写入和续接流程。

```powershell
Get-Content -LiteralPath '<CASE_ROOT>\framework\docs\00-入口层\03-一键启动新项目.md'
```

结果：确认 start 预览和 `--apply` 行为、自定义 task-id 参数及 `ready` 含义。

```powershell
& '<PYTHON_311>' -m agent_workflow doctor; & '<PYTHON_311>' -m agent_workflow packs
```

结果：doctor 返回 `ok: true`、框架版本 `0.1.0`、Python `3.11.15`、根目录为指定的临时框架副本；packs 列出 `ecommerce-catalog`、`document-delivery`、`project-planning`；`external_integrations` 为空。

```powershell
& '<PYTHON_311>' '<CASE_ROOT>\framework\.skillshare\skills\project-start\scripts\start_project.py' --locate
```

结果：`ok: true`，唯一定位到框架目录 `<CASE_ROOT>\framework`。

```powershell
$rootPath = '<CASE_ROOT>'; $candidatePath = Join-Path $rootPath 'synthetic-product-catalog'; [pscustomobject]@{ root_exists = Test-Path -LiteralPath $rootPath; candidate_exists = Test-Path -LiteralPath $candidatePath; candidate = $candidatePath } | ConvertTo-Json -Compress
```

结果：测试根目录存在；推荐子目录 `...\synthetic-product-catalog` 当前不存在。

## 待集中回答

子目录由使用者决定。推荐 `<CASE_ROOT>\synthetic-product-catalog`；备选是在同一测试根目录下给出另一个子目录名。该选择未回答前不执行 start。

## 当前验证状态

- 已验证项目骨架回执、project-id `synthetic-product-catalog`、task-id `catalog-start-plan`、assisted 档位、payload 范围字段、四章方案结构、plan-acceptance 决定和 ready 阶段状态。
- 已读取新增的 environment/progress 两份文档，确认分别保留空环境清单与空事件表，没有填未知技术、运行事实或进度事实。
- context/status 当前显示 `stage: ready`、`evidence_valid: true`、`completed_locally: true`、`business_system_state: not_queried`。独立续接验收尚未执行；ready 只证明本地启动方案有效。
- 未创建额外项目卡、未查询或操作业务系统、未修改框架副本。

## 子目录答复后的实际执行

合成使用者选择了推荐子目录 `<CASE_ROOT>\synthetic-product-catalog`，并确认项目 ID `synthetic-product-catalog`、task-id `catalog-start-plan`。其余原始范围不变；沿用 `assisted`。

启动预览完整命令：

```powershell
& '<PYTHON_311>' '<CASE_ROOT>\framework\.skillshare\skills\project-start\scripts\start_project.py' --framework '<CASE_ROOT>\framework' -- start '<CASE_ROOT>\synthetic-product-catalog' --project-id synthetic-product-catalog --name 'SYNTHETIC 商品资料清单项目' --brief '整理虚构商品资料审核需求，供本地演示。' --task-id catalog-start-plan --mode assisted
```

结果：`ok: true`、`applied: false`、workflow `project-planning`；预览只列轻量项目骨架入口文件，说明 scope 为 `project planning only; no implementation or external operations`。

应用完整命令：

```powershell
& '<PYTHON_311>' '<CASE_ROOT>\framework\.skillshare\skills\project-start\scripts\start_project.py' --framework '<CASE_ROOT>\framework' -- start '<CASE_ROOT>\synthetic-product-catalog' --project-id synthetic-product-catalog --name 'SYNTHETIC 商品资料清单项目' --brief '整理虚构商品资料审核需求，供本地演示。' --task-id catalog-start-plan --mode assisted --apply
```

结果：`applied: true`，completion 为 `operation: completed`、`local_record: complete`、`repeat_operation: false`；生成项目入口与单个 `catalog-start-plan` 规划任务。

按 project-start 技能核对状态和上下文的完整命令：

```powershell
& '<PYTHON_311>' '<CASE_ROOT>\framework\.skillshare\skills\project-start\scripts\start_project.py' --framework '<CASE_ROOT>\framework' -- status '<CASE_ROOT>\synthetic-product-catalog' --task-id catalog-start-plan
& '<PYTHON_311>' '<CASE_ROOT>\framework\.skillshare\skills\project-start\scripts\start_project.py' --framework '<CASE_ROOT>\framework' -- context '<CASE_ROOT>\synthetic-product-catalog' --task-id catalog-start-plan
```

结果：新项目自己的 `AGENTS.md` 指向唯一任务和本机框架定位文件。初始 status/context 均为 `scope`，报告四项 `invalid_field`；按新项目入口只读检查 payload 后，将用户原话中的使用者、范围、排除项、成功标准分别填入 `users`、`in_scope`、`out_of_scope`、`success_criteria`。

项目资料和流程入口实际读取命令：

```powershell
Get-Content -LiteralPath '<CASE_ROOT>\synthetic-product-catalog\AGENTS.md'
Get-Content -LiteralPath '<CASE_ROOT>\synthetic-product-catalog\docs\00-入口层\00-项目总览.md'
Get-Content -LiteralPath '<CASE_ROOT>\synthetic-product-catalog\tasks\catalog-start-plan\payload.json'
Get-Content -LiteralPath '<CASE_ROOT>\synthetic-product-catalog\docs\20-规则层\20-项目规则.md'
Get-Content -LiteralPath '<CASE_ROOT>\framework\agent_workflow\packs\project-planning\SOP.md'
Get-Content -LiteralPath '<CASE_ROOT>\framework\docs\00-入口层\02-交互与续接.md'
```

结果：确认该任务采用通用 `project-planning` 工作流；项目规则不预填行业事实；本地 SOP 要求四个方案章节实写，并在接受前询问 `plan-acceptance`。

scope 完成后的 context 写入和状态检查完整命令：

```powershell
& '<PYTHON_311>' -m agent_workflow context '<CASE_ROOT>\synthetic-product-catalog' --task-id catalog-start-plan --write
& '<PYTHON_311>' -m agent_workflow status '<CASE_ROOT>\synthetic-product-catalog' --task-id catalog-start-plan
```

结果：`project-scope.passed: true`、`can_advance: true`、`evidence_valid: true`，stage 仍为 `scope`，可继续到 plan。

阶段推进先预览再应用：

```powershell
& '<PYTHON_311>' -m agent_workflow advance '<CASE_ROOT>\synthetic-product-catalog' --task-id catalog-start-plan
& '<PYTHON_311>' -m agent_workflow advance '<CASE_ROOT>\synthetic-product-catalog' --task-id catalog-start-plan --apply
```

结果：预览 `scope → plan` 且 `applied: false`；应用 `scope → plan` 且 completion 为 `operation: completed`、`local_record: complete`。

plan 阶段读取命令：

```powershell
Get-Content -LiteralPath '<CASE_ROOT>\synthetic-product-catalog\docs\10-流程层\10-项目启动SOP.md'
Get-Content -LiteralPath '<CASE_ROOT>\synthetic-product-catalog\tasks\catalog-start-plan\plan.md'
```

结果：确认需要将四章从占位模板写成正文，并说明尚未完成事项；不得把 ready 表述成系统实现完成。

方案更新后的 context 写入和状态核对完整命令：

```powershell
& '<PYTHON_311>' -m agent_workflow context '<CASE_ROOT>\synthetic-product-catalog' --task-id catalog-start-plan --write
& '<PYTHON_311>' -m agent_workflow status '<CASE_ROOT>\synthetic-product-catalog' --task-id catalog-start-plan
```

结果：`project-scope.passed: true`、`project-plan.passed: true`，四章结构证据通过；`plan-acceptance` 仍待使用者回答，`can_advance: false`，当前 stage 为 `plan`，`evidence_valid: false`。status 给出的决定原文为：“是否接受本次项目范围、启动方案和验收口径？接受只针对这份方案，不代表项目已实现或批准外部操作。” 推荐：若 payload 和 plan 符合需求，选 `accept`；若需改动，选 `revise` 并说明修改点。尚未写入决定。

## 方案接受与辅助骨架补建

合成使用者实际答复：主智能体逐字读取 `payload.json` 与四章 `plan.md`，确认符合原始范围；接受启动方案及其限定结论，`plan-acceptance=accept`，回答者 `synthetic-user`。接受仅限本地规划，不代表业务实现或外部操作。

本轮先读取按需项目文档规则：

```powershell
Get-Content -LiteralPath '<CASE_ROOT>\framework\.skillshare\skills\project-start\references\project-documents.md'
```

结果：确认已建项目补辅助文档须用公开 `project-docs` 先预览再应用；`environment` 仅记录实际核验，`progress` 是事件记录；应用只创建所选缺项，不改任务事实或索引。

应用接受决定的完整命令：

```powershell
& '<PYTHON_311>' -m agent_workflow decision '<CASE_ROOT>\synthetic-product-catalog' --task-id catalog-start-plan --decision-id plan-acceptance --answer accept --by synthetic-user --apply
```

结果：`ok: true`、decision-id `plan-acceptance`、answer `accept`、by `synthetic-user`、`applied: true`，completion 为 `operation: completed`、`local_record: complete`、`repeat_operation: false`。

接受后查询 status/context 的完整命令：

```powershell
& '<PYTHON_311>' -m agent_workflow status '<CASE_ROOT>\synthetic-product-catalog' --task-id catalog-start-plan
& '<PYTHON_311>' -m agent_workflow context '<CASE_ROOT>\synthetic-product-catalog' --task-id catalog-start-plan
```

结果：三项检查 `project-scope`、`project-plan`、`plan-acceptance` 均通过，pending_decisions 为空，`can_advance: true`、`evidence_valid: true`，当前 stage `plan`。

推进到 ready 先预览再应用的完整命令：

```powershell
& '<PYTHON_311>' -m agent_workflow advance '<CASE_ROOT>\synthetic-product-catalog' --task-id catalog-start-plan
& '<PYTHON_311>' -m agent_workflow advance '<CASE_ROOT>\synthetic-product-catalog' --task-id catalog-start-plan --apply
```

结果：预览 `plan → ready` 且 `applied: false`；应用 `plan → ready` 且 completion 为 `operation: completed`、`local_record: complete`、`repeat_operation: false`。

补建 environment 与 progress 的公开命令先预览：

```powershell
& '<PYTHON_311>' '<CASE_ROOT>\framework\.skillshare\skills\project-start\scripts\start_project.py' --framework '<CASE_ROOT>\framework' -- project-docs '<CASE_ROOT>\synthetic-product-catalog' --task-id catalog-start-plan --with-docs environment --with-docs progress
```

结果：`ok: true`、`applied: false`；仅显示 `docs/project/environment.md` 与 `docs/project/progress.md` 为 pending；scope 为 `optional documents only; task facts and index unchanged`。

按预览应用的完整命令：

```powershell
& '<PYTHON_311>' '<CASE_ROOT>\framework\.skillshare\skills\project-start\scripts\start_project.py' --framework '<CASE_ROOT>\framework' -- project-docs '<CASE_ROOT>\synthetic-product-catalog' --task-id catalog-start-plan --with-docs environment --with-docs progress --apply
```

结果：`ok: true`、`applied: true`、created 为 `environment` 与 `progress`，preserved/pending 均为空；返回说明任务事实与索引未改。

新增辅助文档和最终状态实际读取命令：

```powershell
Get-Content -LiteralPath '<CASE_ROOT>\synthetic-product-catalog\docs\project\environment.md'
Get-Content -LiteralPath '<CASE_ROOT>\synthetic-product-catalog\docs\project\progress.md'
& '<PYTHON_311>' -m agent_workflow status '<CASE_ROOT>\synthetic-product-catalog' --task-id catalog-start-plan
& '<PYTHON_311>' -m agent_workflow context '<CASE_ROOT>\synthetic-product-catalog' --task-id catalog-start-plan
```

结果：environment 仅有环境清单与安装/运行待填写说明，没有写入未知版本或技术事实；progress 仅有空事件表及记录规则，没有编造事件。最终 status/context 保持 `stage: ready`、`evidence_valid: true`、`completed_locally: true`、`business_system_state: not_queried`、`snapshot_matches: true`。辅助文档补建没有触碰 payload、plan、task 或 workflow index。
