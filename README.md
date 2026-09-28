# Ingredient-System
For Hong Kong business usage

Windows 仓库管理项目。当前处于需求与工程准备阶段，尚无可运行应用。

## 从哪里开始

- [PROJECT.md](PROJECT.md)：已确认目标、范围、假设、阻塞项与交付条件。
- [AGENTS.md](AGENTS.md)：Codex 与其他编码代理共用的工程规则。
- [CLAUDE.md](CLAUDE.md)：Claude Code 入口，引用共用规则。
- [架构决策](docs/DECISIONS.md)：哪些已决定，哪些待业务答复。
- [研究与复用](docs/RESEARCH.md)：成熟项目、源码观察、历史问题与适用边界。
- [协作与接力](docs/COLLABORATION.md)：任务认领、独立分支、审查、停止条件和自动化启用步骤。
- [任务队列](docs/tasks.json)、[验收场景](docs/acceptance.json)、[交接记录](docs/HANDOFF.md)。

运行项目计划校验：`python scripts/check_project.py`。它只校验文档、任务依赖和验收记录格式，不证明库存软件正确。

## 当前下一步

先执行 T01 成熟系统适配评估和 T02 领域模型设计，再确定复用或定制路线。
Windows 安装程序是交付目标；已确认办公室 2–3 台电脑共用库存，采用集中服务的数据架构，局域网或云端位置待确认。接单即扣业务可用量、员工选货、期初先导入后盘点，详见 PROJECT.md 与 D07/D08。

当前 GitHub Actions 仅做项目计划检查。没有启用付费 AI 调用、持续自动派工、自动合并或生产发布。

## 数据边界

这是公开仓库。仅提交合成测试数据；客户订单、截图、联系人、地址、库存原表及数据库备份应存放在仓库外或被忽略的 `private-data/` 中。脱敏后的真实资料仍需检查后才可分享。
