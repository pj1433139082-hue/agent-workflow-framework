# 贡献指南 (Contributing Guide)

感谢你对 `agent-workflow-framework` 的关注与贡献！

本项目是一个领域无关的通用智能体协作与工作流调度底座，致力于提供任务定位、业务包分流、多档位交互决定、断点续接与本地证据索引等标准化协作能力。

在参与贡献前，请先阅读我们的 [行为准则 (CODE_OF_CONDUCT.md)](CODE_OF_CONDUCT.md) 与 [安全政策 (SECURITY.md)](SECURITY.md)。

---

## 1. 核心设计原则

在开发或提交代码前，请理解本项目的核心架构约束：

1. **纯标准库实现**：
   - 框架 CLI 和核心逻辑仅依赖 Python 3.11+ 标准库，不引入重型第三方包，保持极致轻量与高可移植性；
2. **两库物理隔离与虚构演示**：
   - 本仓库仅收录通用调度逻辑、技能、脚手架模板和虚构演示业务包（如 `ecommerce-catalog`、`document-delivery`）；
   - 真实业务项目、私有数据、真实测点与生产凭据绝不进入本仓库，保存在仓库外的独立项目工作区；
3. **公开 CLI 与只读 Hook 契约**：
   - 框架状态推进、决策记录与恢复通过公开 CLI 命令完成；
   - 辅助 Hook 保持只读状态，绝不越权向外部系统做不可逆写入。

---

## 2. 本地开发与环境验证

### 2.1 克隆仓库

```bash
git clone https://github.com/pj1433139082-hue/agent-workflow-framework.git
cd agent-workflow-framework
```

### 2.2 环境检查

确保当前 Python 解释器版本为 Python >= 3.11：

```bash
python --version
python -m agent_workflow doctor
python -m agent_workflow packs
```

---

## 3. 开发流程与规范

### 3.1 分支管理

- 从最新的 `main` 分支切出特性分支：
  - 功能特性：`feat/<feature-name>`
  - 缺陷修复：`fix/<bug-name>`
  - 文档改进：`docs/<topic-name>`
  - 重构优化：`refactor/<refactor-name>`

### 3.2 Commit 命名规范

提交信息请遵循 [Conventional Commits](https://www.conventionalcommits.org/) 规范：

- `feat`: 新增框架能力或业务包模板扩展
- `fix`: 修复调度、解析或并发状态异常
- `docs`: 文档、ADR 或术语修订
- `refactor`: 重构优化（不改变外部契约）
- `test`: 增加或更新单测与验收用例
- `chore`: 构建配置、CI 工作流或代码库日常维护

**示例**：
```text
feat(runner): 增强复杂长流程恢复与断点快照机制
fix(cli): 修复 Windows 环境下项目路径包含空格时的解析异常
docs(domain): 完善单上下文架构下术语与决策记录边界
```

---

## 4. 本地门禁检查（必须 100% 通过）

在提交 PR 或合并分支前，必须在本地完整运行并确认通过以下三项门禁：

1. **环境与业务包诊断**：
   ```bash
   python -m agent_workflow doctor
   ```
2. **全量单元测试与状态契约回归**：
   ```bash
   python -m unittest discover -s tests -v
   ```
3. **仓储资产与敏感信息扫描门禁**：
   ```bash
   python scripts/check_repository.py
   ```
   输出必须满足 `{"ok": true, "issues": []}`。

---

## 5. Pull Request 提交要求

- 创建 PR 时请基于提供的 [PR 模板](.github/pull_request_template.md) 填写变更说明与本地验收证据；
- 关联对应的 GitHub Issue（例如 `Fixes #14`）；
- 确保 CI 流水线（Windows / Linux 矩阵）全部绿色通过。
