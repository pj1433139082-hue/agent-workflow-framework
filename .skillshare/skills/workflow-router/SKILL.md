---
name: workflow-router
description: Route generic collaboration tasks to their selected business workflow, minimal documents, recorded mode and public CLI.
---

# 通用协作分流

先读 AGENTS.md 和 docs/00-入口层/00-协作总览.md。只有需要定位任务且不能唯一确定时，集中问一次工作区和任务 ID；不猜最近任务，不预加载全部业务包。

若需求是“按此框架开启全新项目”而非已有任务，转到同仓库 `../project-start/SKILL.md`，使用公开 start 生成项目入口和规划任务；不把未知业务强行选成虚构电商或文档演示。

执行 `python -m agent_workflow context <工作区> --task-id <ID>`、`status` 和 `task-plan`，读取返回的当前阶段资料。项目与任务事实在框架仓库外；不依赖聊天记忆，不把生成的 workflow-state.json 当事实源。

新任务只选一次 full-auto / assisted（默认推荐）/ manual-review。已明确选档或已有任务记录就恢复，不再弹选择。纯只读查询不选档。assisted 连续完成已交办的本地步骤，只集中询问新增业务决定；manual-review 每项实质写入前暂停；full-auto 不猜业务答案。弹窗可用时展示选项，同时提供可见文字，回复“按推荐”只覆盖已展示的推荐，不确认未来未知决定。

先自动检查事实；当前 required decision 未关闭时，在结束本轮前主动展示问题、推荐与备选。用户实际回答后才 `decision --apply`。所有档位均通过相同检查，`--apply` 不是重新要求用户批准每一条命令。

`advance` 只推进本地协作状态。此版本不实现真实业务写入、退款、支付、上架、模型发布或发消息。任务阶段和 hook 不是永久业务授权，任何将来的外部操作须有针对具体目标和内容的用户指令，不从选择全自动推断许可。

如果一次操作完成但生成索引或清理失败，按 completion 回执报告事实已完成、本地记录不完整；不重放 new/advance/decision/task-plan。只有索引需要重建时运行返回的同一目标 context 修复命令；锁或暂存路径提示检查时，先按安全规则核对，不自动删除未知内容。task_busy 不排队、不推断前次结果；无可靠回执的中断先读 status/context。

hook 只读且需客户端支持与信任；不可用时 AGENTS.md＋CLI 完整接管。Skillshare 不可用时直接读本文件，不增加安装或审批门禁。

每轮结束给出已验证/未验证、当前阶段和一个安全下一步；没有新业务选择就不加形式性确认。
