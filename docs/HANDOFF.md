# 当前交接

更新：2026-09-27（Claude Code，T05 分支是当前最新的一层）。

## 分支与提交（叠放，由下到上）

| 层 | 分支 | 基于 | 内容 |
| --- | --- | --- | --- |
| 1 | `docs/warehouse-agent-foundation` | main `9243eed` | 导入启动包 v0.3（提交 `0388a9e`） |
| 2 | `agent/claude/T02-domain-model` | 第 1 层 | T02 领域模型（提交 `df4f155`，审查修正 `e592504`） |
| 3 | `agent/claude/T01-fit-gap` | 第 2 层 | T01 适配评估、建议、实测证据（最终 `22b1403`） |
| 4 | `agent/claude/T05-architecture` | 第 3 层 `22b1403` | T05 技术选型 ADR（D09）、部署与测试基线、本交接 |

叠放的原因：tasks.json 和本文件由几个任务共用，叠放可以避免合并冲突，T01 的建议也需要引用 T02。合并时请**从下往上**依次合并；下层合并后，GitHub 会把上层 PR 的目标分支自动改成 main。
前三层的 PR 由用户在网页上创建草稿；T05 的草稿 PR 由 Claude 通过 GitHub 工具创建，base 为第 3 层。审查者应核对每个 PR 的**最终 SHA**。

## 本次完成（T05，第 4 层）

- 分支 `agent/claude/T05-architecture`，基于 `22b1403`。内容提交 `be11393`；分支最终 SHA 以 PR 页面为准（本文件的 SHA 回填是最后一个提交，不能写自己的 SHA）。
- **D09**（[DECISIONS.md](DECISIONS.md)）：状态"候选，待业务确认路线"。比较了 Django 5.2 LTS、FastAPI + SQLAlchemy、TypeScript/Node 24 三个后端；候选选择 Python 3.13 + Django 5.2 LTS + psycopg 3 + PostgreSQL 18，READ COMMITTED + 显式行锁 + Operation 唯一键实现幂等；写了回退办法。
- **[deployment.md](deployment.md)**：局域网与云端两种形态（选择待 Q01）、断网时禁止写库存的具体行为、备份/恢复演练/升级/回退流程、支持责任占位、T06 测试基线（PostgreSQL 18.6 服务容器、并发测试写法与用例表、Windows runner 职责边界）。
- 官方资料查阅日期均为 2026-09-27，链接写在文中。postgresql.org、docs.github.com、djangoproject.com 在本环境被网络代理拦截，改为读取 GitHub 上的官方源文件；PostgreSQL 大版本 5 年支持政策**没能核对**，已标为未核查。
- **tasks.json 里 T05 仍是 `queued`**：它依赖的 T01、T02 还在 review，改成 in_progress 或 review 会让 `check_project.py` 失败。T01/T02 合并并标为 done 后，再把 T05 改为 review 并填 owner 和 evidence（`docs/DECISIONS.md#d09`、`docs/deployment.md`）。

## 之前完成（T01、T02）

- **T02** → review：[domain-model.md](domain-model.md)。只是设计，没有运行代码。
- **T01** → review：[fit-gap.md](fit-gap.md)。InvenTree 1.5.6 用合成数据实测；ERPNext 和 OpenBoxes 只核对了源码，未运行验证。建议第一版定制核心账务，路线尚未锁定。

## 审查记录

- 2026-09-27 Codex（codex-reviewer，只读）审查了 T01 的 `47d6b96`。确认成立 3 条：ERPNext/OpenBoxes 的"源码"结论没有写出处，且有几处说过了头；"接受缺口就改走 ERPNext"推理不成立。已补上指向具体版本源码文件的链接，把"支持"改成"有对应字段（行为未运行）"，并改写退路。
- Codex 还核实了 InvenTree 四条反例与源码一致，并指出"待检货可以被分配"只在接口层成立（网页表单默认过滤）。已在 T01、T02、RESEARCH 里写明。
- 修正后的最终 SHA 需要重新审查；上面这次审查只对 `47d6b96` 有效。
- T05 尚未审查。

## 可运行检查

- T05 分支：`python scripts/check_project.py` 开工前基线和提交前都是 PASS（8 项任务、14 项验收定义）；`git diff --check` 无输出。实际输出见 PR。这些只校验文档和任务格式。
- T05 **没有运行**：任何应用代码、PostgreSQL、GitHub Actions 服务容器工作流、并发测试、备份恢复、升级、Windows 安装。deployment.md 第 7 节的工作流骨架未运行验证。
- 更早的层：InvenTree 场景脚本见 T01 证据目录（23 条，16 通过、7 不通过）；并发、PDF、网页界面、Windows 都没有测。
- GitHub Actions：只有在 PR 创建后才会运行。

## 下一步（一项）

请业务方回答"路线"和 Q01（服务器放办公室还是云端、断网时是否必须能出货）。路线确认为定制后，D09 改为已采纳，T06 按 deployment.md 第 7 节建立 `application/` 和 PostgreSQL 并发测试工作流。

## 阻塞后续阶段的业务问题

1. **Q05**：客户导出的库存数，是实物数，还是已经扣掉未出货订单的数？导出时间点是什么时候？（阻塞真实数据切换）
2. **Q03**：员工说的"库存"指哪个数：实物、可用，还是两个都要看？一行订单能不能分几次发货？（阻塞正式启用前的验收）
3. **路线**：客户更看重"少维护、尽快能用"（会倾向 ERPNext），还是"账目规则完全按现在的做法"（倾向定制）？工作日出故障时，公司里谁负责？（阻塞 T05 锁定路线；D09 目前是候选）
4. **Q01 剩余部分**：服务器放办公室还是云端？断网时是否必须能继续出货，能否接受纸本应急单、恢复后补录？员工电脑的 Windows 版本？（阻塞部署形态和离线承诺，见 [deployment.md](deployment.md) 第 9 节）
5. **备份**：最多能接受丢失多长时间的录入？云端的话，数据存放地有无要求？（阻塞备份方案定稿）
6. **支持责任**：公司侧负责人、工作日技术支持、账号持有人、恢复演练负责人（阻塞试运行）

## 每次接手的最小记录

- Task / owner / branch / base SHA / PR head SHA
- 修改了什么以及对应需求或决策
- 实际运行的命令、结果和证据路径
- 尚未验证的部分、阻塞问题
- 下一项具体动作

后续把当前状态改为最新摘要，旧状态由 Git 历史保存。详细运行证据放在对应 PR 或合成测试报告中，避免无限增长。
