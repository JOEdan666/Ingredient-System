# 当前交接

更新：2026-09-28（Claude Code 云端会话，T03 进行中）。

## 当前状态

- `main` = `b620443`：启动包、T02、T01、T05 已按 #2 → #3 → #4 → #1 顺序合并。
- **T03 进行中**：分支 `agent/claude/T03-prototype`，基于 `main` `b620443`，owner `claude-cloud`，只有这个会话写入。草稿 PR [#6](https://github.com/JOEdan666/Ingredient-System/pull/6) 指向 `main`，未合并。
- tasks.json（本分支第一个提交）：T01、T02 → done（已合并，evidence 未改）；T05 → review（owner `claude-cloud`，evidence 为 D09 和 deployment.md）；T03 → in_progress。T05 合并后的最终 SHA 仍待 Codex 复审（见下方审查记录）。

## T03 进度（每一步提交后更新）

| 步骤 | 状态 |
| --- | --- |
| 1. tasks.json 状态、HANDOFF | 完成 |
| 2. Django 5.2 骨架、依赖锁文件 `prototype/uv.lock`（Python 3.13.12、Django 5.2.17、pytest 9.1.1、pytest-django 4.14.0） | 完成 |
| 3. 领域模块 `prototype/inventory/domain.py`（D07、I1–I11、operation_id 幂等、对账 `check_invariants`）+ 合成数据加载 | 完成 |
| 4. 四个页面（库存、收货、出库+订单处理、历史查询）+ 页面流程测试 | 完成 |
| 5. [prototype.md](prototype.md)、截图 `docs/screenshots/t03-*.png`（4 张，合成数据） | 完成 |
| 6. 草稿 PR [JOEdan666/Ingredient-System#6](https://github.com/JOEdan666/Ingredient-System/pull/6) 指向 main；内容提交 `0a5899d`，最终 SHA 以 PR 页面为准 | 完成 |

## 审查记录（仍有效的部分）

- T03：尚未审查。
- T05：Codex 审查 `e3974b0` 的 4 条已修正；复审 `426a47f` 的问题在 T02 `1d3b4f9` 和 T05 `c30e537` 修正。修正后的最终 SHA 待重新审查。
- T01：Codex 审查 `47d6b96` 确认的 3 条在 `22b1403` 修正；修正后未重新审查。

## 可运行检查（T03 分支）

- `python scripts/check_project.py`：基线和每次提交前都是 PASS（8 项任务、14 项验收定义）。只检查文档和任务格式。
- `cd prototype && uv run pytest`：36 passed（SQLite）。完整输出在 [prototype.md](prototype.md) 第 6 节。临时变异抽查（未提交）：两个变异分别让 4+3、3+1 条测试失败/出错，说明测试能分辨对错。
- `uv run python manage.py check`：无问题；`makemigrations --check`：无遗漏。
- **未运行验证**：PostgreSQL 与并发（A06）、Windows 上运行、除无头 Chromium 外的浏览器、登录权限（A14）、PDF/Excel 导入、打印。SQLite 上 `select_for_update()` 不生效，原型**不证明并发和锁**。
- acceptance.json 各项状态没有改（stage 为 database/end_to_end，SQLite 原型不满足）。

## 下一步（一项）

请业务方看四张截图，回答 Q03：员工口中的「库存」指实物、合格实物还是可用（[prototype.md](prototype.md) 第 8 节第 1 条）。

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

## 审查与修正（2026-09-28 夜，本机 Claude Code 接手本分支）

- **写入者交接**：云端会话建完 PR #6 后已结束；本机 Claude Code 接手 `agent/claude/T03-prototype` 做这一轮修正，云端会话不再写本分支。
- 审查来源：Claude 审查者定时任务（PR #6 评论，`CHANGES_REQUESTED @ 1fe6af5`）与 Codex（本机）。逐条核实后：
  - 已修：移位 / 改状态分两步锁来源和目标 → 改为一次按 id 顺序锁两行（避免 PostgreSQL 上 A→B / B→A 死锁）；改状态加锁后校验状态未变（保险，状态是余额行身份的一部分，本不会变）。
  - 已修：分配 / 取消页面未校验订单行属于 URL 中的订单 → 不属于即拒绝；表单里非数字的库存/分配编号 → 友好拒绝，不再 500。
  - 已修：T03 状态改为 review，补 evidence。
  - 不成立：「两个并发的待检→合格会重复加可售」——第二个请求在锁内重读可改数量为 0 会被拒绝（domain.py 的 insufficient_free 检查）。
- 新增 6 条回归测试；用修正前的代码跑这 6 条全部失败，修正后全部通过。本机 `pytest`：42 passed（SQLite，不证明并发）。
- **需要用户知道**：PR #5（本分支第一个提交：任务状态与 HANDOFF）在建立后 10 秒被合并进 main（合并人显示为用户账号）。按时间判断是云端会话所为，违反了「不要合并」。内容只含状态与交接文字，已保留，未回滚。
