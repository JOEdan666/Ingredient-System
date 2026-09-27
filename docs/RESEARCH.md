# 研究与复用记录

核查日期：2026-09-27。事实、源码观察、问题报告与本项目建议分开记录。代码研究未等同于产品部署验证。

## 成熟软件比较

| 项目 | 已核查内容 | 对本项目的价值 | 适配代价和限制 |
| --- | --- | --- | --- |
| [InvenTree](https://github.com/inventree/InvenTree) | 下载源码，读取 LICENSE 和 stock/models.py | 库存项、位置、效期、拆分、移位、并发数量保护 | 需验证货主隔离、客户单据、板头纸及 Windows 交付，尚未部署运行 |
| [OpenBoxes](https://github.com/openboxes/openboxes) | 下载源码，读取 InventoryItem、TransactionEntry 和 LICENSE | 仓储批次与货位交易的分离 | 原项目面向医疗供应链，技术和部署维护需要评估，尚未部署运行 |
| [ERPNext](https://github.com/frappe/erpnext) | 官方库存账与纠错文档，仓库元数据 | 完整业务单据、库存流水和冲正模型，可评估配置复用 | 范围大于当前仓库需求，界面与流程适配需实证 |
| [Odoo Inventory](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/inventory/shipping_receiving/removal_strategies/fefo.html) | 官方 FEFO 文档搜索结果 | 效期与拣货策略的业务概念参考 | 正文抓取超时，尚未完成产品和具体版本核查，不据此锁定实现 |

已读取许可证：InvenTree MIT；OpenBoxes EPL-1.0；ERPNext 仓库标注 GPL-3.0。没有复制这些项目的源码进入本仓库。后续代码复用须按所选修订的实际许可保留通知并确认分发方式；不把“公开可看”当成无条件可复制。

## T01 结果（2026-09-27）

适配表和建议见 [fit-gap.md](fit-gap.md)。InvenTree 1.5.6 用合成数据实际运行了验收场景，证据在 [evidence/T01-inventree/](evidence/T01-inventree/README.md)；ERPNext v16.36.0 和 OpenBoxes v0.9.8-hotfix1 只核对了源码字段，未运行验证。
新增实测反例：InvenTree 1.5.6 中，待检库存可以被分配；重复提交会重复分配并超出订单行数量；取消订单会删除分配记录；发货历史不保存货位。这些反例对应 T02 的 I2、I4、I7 和 A01、A05、A10、A04，将作为本项目的负面测试。

## 源码观察

### R01 InvenTree 库存拆分与并发

修订：`d3c23f37ca28f3031abbd5c8437288f5a391bffc`。
[源码](https://github.com/inventree/InvenTree/blob/d3c23f37ca28f3031abbd5c8437288f5a391bffc/src/backend/InvenTree/stock/models.py)。

观察：StockItem 保存位置、批号、效期；move 对部分数量使用拆分路径；数量锁在事务中获取，并重新读取已提交数量。
本项目采用的思想：不能先在页面读取数量，再假设提交时仍然可用。多行出库需统一锁顺序/条件更新并处理冲突重试。具体实现必须与所选数据库一致。
映射：D03、T06、A02/A03/A06。不是把上游所有边界行为原样移植。

### R02 OpenBoxes 批次与交易

修订：`71454492fd8a8aeef88151b13c171d244c0dbf1a`。
[InventoryItem](https://github.com/openboxes/openboxes/blob/71454492fd8a8aeef88151b13c171d244c0dbf1a/grails-app/domain/org/pih/warehouse/inventory/InventoryItem.groovy)、[TransactionEntry](https://github.com/openboxes/openboxes/blob/71454492fd8a8aeef88151b13c171d244c0dbf1a/grails-app/domain/org/pih/warehouse/inventory/TransactionEntry.groovy)。

观察：批次对象关联商品、批号、效期；交易条目关联数量和库内位置。
本项目推导：商品、批次身份、位置余额和历史交易应能分别追溯。不要让改货位破坏旧订单，也不要把同效期的两次收货误认成同一来源。
映射：D04、T02、A03/A04/A09。

### R03 ERPNext 过账与冲正

[官方说明](https://docs.frappe.io/erpnext/immutable-ledger-in-erpnext)。
事实：取消已过账交易时保留原条目并记录相应反向条目，保留可追查的来源关系。
本项目建议：草稿可以编辑；过账后纠错保留原始记录和更正原因。未来若加入成本估值，补录历史交易需单独设计，不能用改时间掩盖错误。
映射：D03、A04/A10。

## 查到的历史故障与本项目测试

| 记录 | 原项目报告，不能当成当前版本仍存在的结论 | 本项目采取的预防措施 |
| --- | --- | --- |
| [OpenBoxes #1266](https://github.com/openboxes/openboxes/issues/1266)，closed | 升级版本启动时迁移校验和不匹配 | 已应用迁移不覆写；用上一版数据库副本升级；失败可恢复，A11 |
| [InvenTree #6066](https://github.com/inventree/InvenTree/issues/6066)，closed | 报告者怀疑写维护状态文件时中断，造成状态内容无效 | 假设作为故障测试线索：原子写入状态/元数据，模拟中断后重启，A11 |
| InvenTree R01 当前源码 | 并发调整需在锁内刷新数量 | 针对同一库存的两个并发出库测试，不能仅依赖普通事务包裹，A06 |

上述历史问题通过 GitHub API 读取，未在本地复现；网页渲染部分失败。结论只限于报告所述现象与我们的工程推导。

## AI 协作与交接

- [OpenAI AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)：使用仓库入口指令。PROJECT.md 需要由入口显式要求阅读。
- [Claude 项目记忆](https://code.claude.com/docs/en/memory)：CLAUDE.md 可用 @ 路径引用共用文件。本项目只保留一份共用规则。
- [Anthropic 长任务经验](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)：分步增量交付、清晰功能状态与交接、实际端到端验证；仅有压缩上下文不足以可靠完成长项目。
- [OpenAI OSS 维护实践](https://developers.openai.com/blog/skills-agents-sdk)：将仓库约定和可重复工作流结合。本文是流程先例，不是本项目效率收益保证。
- [Codex cloud](https://learn.chatgpt.com/docs/cloud)、[Claude cloud](https://code.claude.com/docs/en/claude-code-on-the-web)：连接仓库后可启动独立云任务；账号授权和当前可用能力未替用户配置。
- [Codex Action](https://learn.chatgpt.com/docs/github-action)、[Claude Action](https://code.claude.com/docs/en/github-actions)：认证、调用成本、可信触发者、超时和并发需要显式设置。Claude 文档说明默认 GITHUB_TOKEN 产生的提交可能不触发后续 CI。
- [Claude routines](https://code.claude.com/docs/en/routines)：可作为后续调度候选；本项目未启用，不能假设它已连接另一产品。

## X 与 YouTube 的检索边界

已搜索两类渠道。
[X 长任务讨论](https://x.com/systematicls/status/2038241033755168959)检索可见摘要，但正文抓取失败，不据此作已验证的技术结论。
[Odoo FEFO 视频线索](https://www.youtube.com/watch?v=cX0Q_G7b9Vo)可检索到标题，视频内容未完整读取；可作为后续操作演示参考，不宣称已经观看验证。
本方案的工程结论以官方文档、实际源码观察和有来源的故障记录为依据，不引用未经核实的社交平台效果宣传。

## 如何继续研究而不拖延交付

T01 输出一次有证据的适配比较；之后每遇到具体问题，查一个对应模块或故障，不持续下载整套仓库。
每条采纳经验都关联 Dxx 决策、Txx 任务或 Axx 验收。没有对应改变的链接不堆进日常代理上下文。
