# 当前交接

更新：2026-09-29（Codex 定时开发，T06a）。

## 当前状态

- 远端 `main` 基准 `9fca774`，T09 已通过 PR #10 合并；T04b 在独立分支 `agent/codex/T04b-real-format-import`，开放 draft PR #11。T04c 依赖 T04b，仍未开工。
- 本轮只接 T06a；分支 `agent/codex/T06a-postgres-domain`，基准 `9fca774`。`application/` 移植 T03 的领域模型、命令、迁移与合成数据回归用例，连接 PostgreSQL，不含网页和生产部署。新增锁探针、缺锁反例、13 条 PostgreSQL 并发/失败检查及独立 CI 工作流；见 [test-commands.md](test-commands.md)。
- T06a 当前为 `review`。GitHub 连接器创建 draft PR 返回 403（integration 无权限），浏览器入口超时；分支 push 会直接触发 PostgreSQL 18 CI。Claude 审查工具返回 extra usage 已用尽，尚无独立审查。T06/T07/T08 仍因业务问题阻塞。所有库存规则只按 D07/D09 候选设计测试，不代表客户验收。

## 本轮实测与限制

- `python3 scripts/check_project.py`：`PASS: 12 tasks, 14 acceptance definitions, synthetic fixture and local links`。
- 本机 PostgreSQL 14.22 临时测试库：`application/` 的 `uv run --frozen pytest -ra` 为 **43 passed**；并发子集 **13 passed, 30 deselected**；计数脚本 `executed=13, expected>=13, failed=0`。这是本机数据库调试，不是目标 PostgreSQL 18 的测试结论。
- 目标 18.6 由 `.github/workflows/db-tests.yml` 在任务分支 push 上运行；实际结果待检查。Windows 安装/升级、真实客户数据、真实业务验收均未执行。
- 详细命令、版本、并发钩子与限制见 [test-commands.md](test-commands.md)。

## 下一步（一项）

检查 T06a 分支的 PostgreSQL 18 CI；若失败，修复并重跑。取得 GitHub PR 写权限后创建 draft PR，再独立审查最终 commit SHA，保留 draft 等人工集成。不要在本例程合并 PR。

## 阻塞后续阶段的业务问题

1. **Q05**：客户导出的库存数，是实物数，还是已经扣掉未出货订单的数？导出时间点是什么时候？（阻塞真实数据切换）
2. **Q03**：员工说的"库存"指哪个数：实物、可用，还是两个都要看？一行订单能不能分几次发货？（阻塞正式启用前的验收）T03 原型已可演示，界面问题清单见 [prototype.md](prototype.md) 第 8 节（按货位显示口径、缺货接单、接单与选货位是否分两步、取消原因、实收差异、不合格货处理、已分配货能否移位、界面语言）。
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

## 历史记录（已合并任务的审查细节见 Git 历史与对应 PR）

- T01（PR #4）、T02（PR #3）、T05（PR #1）、T03（PR #6）、T04（PR #7）均已合并进 `main`；各自的
  审查往返、修正提交和最终 SHA 见对应 PR 页面，不在此重复。
- **供参考**：T03 分支曾出现 PR #5、PR #6 在建立后很快被合并（合并人显示为用户账号，具体是否
  为人工操作还是某次会话所为已无法在本轮确认）。两次合并的内容都只是既定的状态/文档变更，
  未发现被篡改的证据，未做回滚。按本轮指令，例程本身在任何情况下都不合并 PR。

## 2026-09-29 下午：按真实格式推进（本机 Claude Code，分支 agent/claude/plan-real-formats）

- 用户提供了真实文件（库存导出表、验货纸、2 份 PDF 送货单、板头纸），**放在仓库外，从不提交**。只在本机读取结构。
- 发现：T04 spike 是按虚构模板写的，与真实格式不一致（见 fixtures/synthetic/real-format/README.md）。
- 新增 `fixtures/synthetic/real-format/`：照真实结构生成的合成样本（表头与真实文件逐格比对一致，值全部编造）。
- T04 已合并但未经审查；Codex 事后审出 6 条代码缺陷 + 1 条文档说过头，已写入 docs/import-contract.md「已知缺陷」，由 T04b 重做时避开。
- 新任务（按顺序）：T09 合并前跑 pytest → T04b 真实格式库存表/验货纸 → T04c PDF 商品行 → T06a PostgreSQL 与并发测试。都不依赖业务答复。
- 仍需业务答复：Q03（库存口径）、Q05（导出数是否已扣未出货订单）——建议用户带原型和真实文件问表叔。
