# 当前交接

## 2026-09-29 Claude Code 本机：T04c PDF 送货单商品行

- Task/owner/branch：T04c，owner `claude-local`（Codex 本机会话额度用完后交接）；分支 `agent/claude/T04c-pdf-order-lines`，基准 `main` `0a5be88`（PR #11 已合并，T04b 同步标 `done`）。开工期间占住本机 Codex 定时任务的锁文件，避免同一任务被两边同时写。
- 改动：新增 `import-spike/import_spike/pdf_order.py` 与 17 条测试；按两份真实 PDF 的结构修正合成样本（旧样本多一行数量、序号 1 的位置不对）；契约见 [import-contract.md](import-contract.md) 第 10 节。
- 实测：`/private/tmp/ingredient-t04b-venv/bin/python -m pytest -q import-spike/tests` → 38 passed；`python3 scripts/check_project.py` → PASS；反例改坏配对/合计核对各自有测试失败。真实 PDF 只读核对只输出计数与错误类别。
- 未验收：Q04（整箱商品数量栏印 EA 的含义）、Q02 其它版式、过账（T06）。
- 下一动作：独立审查最终提交后推送分支并开 draft PR。

## 2026-09-29 Claude 定时例程：T04b 按审查意见修复

- Task/owner/branch：T04b，owner `claude-routine`；分支 `agent/codex/T04b-real-format-import`（继续沿用原分支，未新建）；基准提交 `e1dccf2`（PR #11 head，审查时一致）。
- 触发：PR #11 上「自动审查（Claude 审查者）@ e1dccf2」评论，`REVIEW_VERDICT: CHANGES_REQUESTED e1dccf23d609847f43f9ddb86eaf17d5b7de3ebb`，与本轮开始时分支 HEAD 完全一致；该 PR 内此类评论仅 1 条（≤2），按规则在原分支上修复。
- 缺陷与修复：`import-spike/import_spike/real_format.py:104` 的 `parse_stock_export` 把非 NG 仓行的 `condition` 写成字符串 `"SELLABLE"`，但 `docs/domain-model.md`（Condition 一行）与 `prototype/inventory/models.py:32-36` 的枚举只有 `PENDING_INSPECTION / AVAILABLE / HOLD / DAMAGED`；T06 按计划要用该枚举消费这批 `ImportLine`，命名不一致会导致正常库存行在过账时转换失败或被漏记。已把该分支的两处 `"SELLABLE"` 全部改为 `"AVAILABLE"`（赋值处与下方的 `location_missing` 判断条件）。已核对全仓库无其他 `SELLABLE` 引用。
- 测试：`import-spike/tests/test_real_format.py` 的 `test_stock_export_keeps_rows_and_parses_ng_and_slash_date` 新增断言 `lines[0].condition == "AVAILABLE"`，覆盖正常行应产出的枚举值（此前只断言过 HOLD 行，未断言正常行，这正是审查指出的漏测点）。
- 实际运行：
  ```
  $ cd import-spike && uv run --frozen pytest -q
  .....................
  21 passed in 0.61s

  $ python3 scripts/check_project.py
  PASS: 12 tasks, 14 acceptance definitions, synthetic fixture and local links

  $ git diff --check origin/main...HEAD
  (无输出)
  ```
- 未运行验证：真实文件核对未重新执行（本轮无真实文件访问权限，只跑合成 fixture）；两个解析器仍只预览、不过账，T06 消费端尚未实现，无法端到端验证 `AVAILABLE` 在下游的实际效果。
- 后续：Claude 对提交 `275d8e1` 的审查已在 PR #11 留下 `REVIEW_VERDICT: PASS`；本次同步 `main` 只解决交接文档冲突，解析器改动保持不变。

## 2026-09-29 Codex 本机 T04b 接手记录

- 基准：`main` 合并 PR #10 后为 `9fca774`；独立分支 `agent/codex/T04b-real-format-import`，owner `codex-local`，状态 `review`。旧交接正文保留为历史快照。
- 实现：库存导出和验货纸两个只预览的解析器；保留原始值、源行号与行级提示；修复 T04 已知的六类解析/顺序提交缺陷。真实验货纸末尾有汇总行，按结构排除，不当成商品。
- 验证：`cd import-spike && uv run --frozen pytest -q` → 21 passed；`python3 scripts/check_project.py` → PASS。用户已授权本机核对的真实文件只读运行：库存 478 行、验货纸 50 行，行级错误 0；仅记录这些汇总结果，未提交原件或客户值。
- 边界：验货纸的库存与实收列标题均为“件”，已是 EA；`Item UOM=CS` 仅表示商品箱规，不能把这两列再乘一次。显式 CS 数量的换算已实现并测试，但这一业务解释仍待 Q04 确认；数据库事务、并发、过账由 T06a/T06 承担。
- 下一动作：独立复审当前最终提交后再合并。PR #10 已合并；云端定时例程可能还读到旧 `main` 的 T04b=ready，在本分支推送并建 PR 前须防止双人同时写 T04b。

更新：2026-09-29（Codex 同步 main，T04b PR #11 收尾）。

## 当前状态

- 远端 `main` 已合并 T06a 的 [PR #12](https://github.com/JOEdan666/Ingredient-System/pull/12)；T04b 在独立分支 `agent/codex/T04b-real-format-import`，开放 draft [PR #11](https://github.com/JOEdan666/Ingredient-System/pull/11)，Claude 对其解析器最终改动 `275d8e1` 审查 PASS。T04c 依赖 T04b，仍未开工。
- `application/` 由 T06a 带入 main：领域模型、命令、迁移与合成数据回归用例连接 PostgreSQL，不含网页和生产部署。新增锁探针、缺锁反例、13 条 PostgreSQL 并发/失败检查及独立 CI 工作流；见 [test-commands.md](test-commands.md)。T06/T07/T08 仍因业务问题阻塞。库存规则只按 D07/D09 候选设计测试，不代表客户验收。

## 本轮实测与限制

- `python3 scripts/check_project.py`：`PASS: 12 tasks, 14 acceptance definitions, synthetic fixture and local links`。
- 本机 PostgreSQL 14.22 临时测试库：`application/` 的 `uv run --frozen pytest -ra` 为 **43 passed**；并发子集 **13 passed, 30 deselected**；计数脚本 `executed=13, expected>=13, failed=0`。这是本机数据库调试，不是目标 PostgreSQL 18 的测试结论。
- 目标 18.6 CI 首次未启动 job：GitHub 报 `(Line: 37, Col: 21): Unrecognized named-value: 'runner'`。删除 job 级 `UV_CACHE_DIR` 后，提交 `e2d3ef3` 的 [Actions run 36575919504](https://github.com/JOEdan666/Ingredient-System/actions/runs/36575919504) 和提交 `449d201` 的 [Actions run 36576125734](https://github.com/JOEdan666/Ingredient-System/actions/runs/36576125734) 均显示 `postgres-domain` 成功，全部测试及并发计数步骤均成功。此结果是合成数据技术测试，不是客户业务验收。Windows 安装/升级、真实客户数据、真实业务验收均未执行。
- 详细命令、版本、并发钩子与限制见 [test-commands.md](test-commands.md)。

## 下一步（一项）

复核 [draft PR #11](https://github.com/JOEdan666/Ingredient-System/pull/11) 同步 main 后的最终差异与 CI，再由有权集成者决定是否合并；合并后才能领取 T04c。不要在本例程合并 PR。

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
