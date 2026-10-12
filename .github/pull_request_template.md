## 变更描述 (Summary & Motivation)

<!-- 请简要说明此 PR 解决的问题、引入的新特性或技术方案。包含相关的背景动机与实现细节。 -->

## 关联 Issue (Related Issue)

<!-- 请使用 GitHub 关键字自动关联或关闭对应 Issue，例如： -->
- Closes #
- Fixes #

## 变更类型 (Type of Change)

- [ ] 🐛 **Bug fix** (修复框架调度错误、锁异常或逻辑缺陷)
- [ ] ✨ **New feature** (新增 CLI 命令、流程控制能力或项目启动特性)
- [ ] 🧩 **Workflow Pack** (新增或优化虚构演示业务包及阶段流转)
- [ ] 📝 **Documentation / ADR** (文档、上下文术语或系统架构决策更新)
- [ ] ♻️ **Refactoring** (代码重构与性能优化，不破坏公开契约)
- [ ] 🧪 **Tests** (新增或强化单元测试、恢复用例与状态验证)
- [ ] 🔧 **CI / Infrastructure** (工作流、依赖检查或发布脚本维护)

## 变更自查清单 (Checklist)

在提交此 Pull Request 之前，请确认已逐项完成本地自检：

- [ ] **Python 版本契约**：代码基于 Python 标准库实现，兼容 Python >= 3.11，无外部重型依赖。
- [ ] **全量单测通过**：本地执行 `python -m unittest discover -s tests -v` 100% 绿灯。
- [ ] **自检诊断通过**：本地执行 `python -m agent_workflow doctor` 返回 `{"ok": true}`。
- [ ] **门禁检查通过**：本地执行 `python scripts/check_repository.py` 返回 `{"ok": true, "issues": []}`。
- [ ] **🛡️ 零泄漏与安全红线**：
  - [ ] 确认**绝无**任何真实商业资产、私有企业系统拓扑或实际业务生产数据；
  - [ ] 确认**绝无**任何 API Token、敏感私钥、密码或内部私网 IP；
  - [ ] 所有测试数据与模板均为纯虚构合成内容；
  - [ ] 遵循单任务线性流转与只读 Hook 契约，无越权外部写入。
- [ ] **文档与契约同步**：若涉及 CLI 参数或业务包阶段变更，相应文档及 `CONTEXT.md` 已同步更新。
