# 通用智能体协作框架

这是一个 Python 3.11+、仅依赖标准库的协作底座，提供任务定位、业务包分流、交互决定、续接和本地证据索引。目标项目的业务语言不受 Python 限制；框架不依赖 MLflow，也不连接真实业务系统。

首版带两个完全虚构的业务包：ecommerce-catalog（电商商品资料审核）和 document-delivery（通用文档交付）。它们用于说明流程机制，不代表已确认的真实业务规则。模板 payload 初始为空；空模板不构成业务事实。

新项目可通过 project-start 技能或公开 start 命令生成独立入口和 project-planning 启动任务，不需要先把项目套成某个演示业务包。

## 获取和更新

私有仓库：[agent-workflow-framework](https://github.com/pj1433139082-hue/agent-workflow-framework)。拥有该仓库访问权限的使用者可从 Windows PowerShell 获取：

    $repositoryUrl = 'https://github.com/pj1433139082-hue/agent-workflow-framework.git'
    git clone $repositoryUrl
    Set-Location .\agent-workflow-framework
    python -m agent_workflow doctor
    python -m agent_workflow packs

已克隆且跟踪主分支的工作副本只做快进更新：

    git switch main
    git pull --ff-only origin main

需使用 Python 3.11 或更新版本。Windows 可在 Python Launcher 已安装时用 py -3.11 替代 python。网络命令遵循使用者现有代理；需要代理时，把下面的示例地址换成自己的实际地址，仅对本次 Git 命令指定：

    $proxyUrl = 'http://127.0.0.1:6666'
    git -c "http.proxy=$proxyUrl" clone $repositoryUrl
    git -c "http.proxy=$proxyUrl" pull --ff-only origin main

代理示例是可选的本机配置，不要求其他使用者采用固定端口，也不会修改系统代理。

v0.1 从源码 checkout 根目录运行；README 中不承诺 PyPI 或 wheel 安装支持。

## 开始与接管

项目工作区放在本仓库外。创建任务、预览推进和恢复方式见[快速开始](docs/00-入口层/01-快速开始.md)；交互决定及 hook 限制见[交互与续接](docs/00-入口层/02-交互与续接.md)。

从空目录启动一个新项目，见[一键启动新项目](docs/00-入口层/03-一键启动新项目.md)。默认轻量骨架，环境、架构、进展、总结和结果口径按需选用，不要求启动时建齐空卡；已有项目接入和归档另行处理。

人工入口：`@AGENTS.md 阅读，接管这个任务：<业务包/工作区/任务ID>`

## 验收

从克隆仓库根目录运行：

    python -m unittest discover -s tests -v

此验收入口面向公开 CLI 和只读 hook。验收记录应提供本次运行结果和临时工作区证据；不要仅凭模板或 fake 测试资料宣称已验证真实业务。见 [验收清单](docs/30-触发层/30-验收清单.md)、[v0.1.0 本地验收记录](docs/30-触发层/31-v0.1.0验收记录.md)、[新项目启动技能本地验收](docs/30-触发层/32-新项目启动技能验收.md)、[项目模板复用验收](docs/30-触发层/33-项目模板复用与接入对齐验收.md)、[项目启动基线验收](docs/30-触发层/34-项目启动基线验收.md) 和 [任务同批核验验收](docs/30-触发层/35-任务同批核验验收.md)。

既有任务写入、索引共锁、故障回执及不重放恢复见[任务写入与恢复验收](docs/30-触发层/36-任务写入与恢复验收.md)。

## 文档入口

- [协作总览](docs/00-入口层/00-协作总览.md)：术语、边界和读取顺序
- [快速开始](docs/00-入口层/01-快速开始.md)：首次运行、创建任务和常用命令
- [交互与续接](docs/00-入口层/02-交互与续接.md)：任务档位、决定和恢复
- [一键启动新项目](docs/00-入口层/03-一键启动新项目.md)：新项目骨架、启动任务和边界
- [新增业务包](docs/10-流程层/10-新增业务包.md)：为新场景定义可替换流程
- [安全与事实源](docs/20-规则层/20-安全与事实源.md)：外部工作区、事实和派生状态

## 首版范围

首版不包含 ERP 或真实平台集成、动态执行插件、退款、支付或真实商品上架，也不收录真实业务资产或自动开放同事权限。
