# 通用智能体协作框架技能

本仓库将通用智能体协作技能作为项目源码进行版本化维护。Git 唯一可编辑源位于 `.skillshare/skills/`；`.agents/skills/` 是本机同步结果，不进入 Git 跟踪。

## 内置技能矩阵

框架提供两项核心互补技能：

1. **`project-start`（新项目启动与脚手架技能）**：
   - 源码路径：`.skillshare/skills/project-start/`
   - 核心职责：将用户的项目想法转化为框架外的独立项目工作区；通过内置定位脚本 `scripts/start_project.py` 安全调用公开 `agent_workflow start` 命令生成入口 `AGENTS.md`、分层文档骨架与初始规划任务；支持通过 `project-docs` 按需补建运行环境、架构等辅助文档；遵循用户原请求交办范围，实现从启动规划到后续业务实现的无缝衔接。
2. **`workflow-router`（任务定位与流程推进技能）**：
   - 源码路径：`.skillshare/skills/workflow-router/`
   - 核心职责：针对已有项目工作区，依据工作区路径与任务 ID 实施业务包分流；执行 `context`、`status` 查询当前阶段事实与待决业务决定；通过推荐驱动人机交互确认，安全推进生命周期状态机。

## 技能同步与免安装使用

### 方式 A：Skillshare 同步（推荐）

在仓库根目录执行：

```powershell
skillshare status --json
skillshare sync --json
```

同步目标固定为仓库内 `.agents/skills/`，符合 Codex / Claude 智能体环境的技能加载规范。

### 方式 B：免安装直接加载（零外部依赖）

未安装全局 Skillshare 工具时，智能体可直接读取源码目录中的对应规范卡片，不设安装门槛：

- 启动新项目：直接读取 `.skillshare/skills/project-start/SKILL.md`；
- 接管既有任务：直接读取 `.skillshare/skills/workflow-router/SKILL.md`。

## 统一使用入口

使用者无需记忆底层实现，可以直接使用标准自然语言入口：

- **从零启动新项目**：
  ```text
  @docs/00-入口层/03-一键启动新项目.md 阅读，开启一个新项目：<项目名称/目录/目标描述>
  ```
- **接管并推进既有任务**：
  ```text
  @docs/00-入口层 阅读，接管这个任务：<业务包/工作区绝对路径/任务ID>
  ```
