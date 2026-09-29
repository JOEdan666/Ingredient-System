# 当前交接

更新：2026-09-29（Claude Code 定时开发例程，T04 进行中）。

## 当前状态

- `main` = `5be897f`：启动包、T02、T01、T05、T03 已按 #2 → #3 → #4 → #1 → #5 → #6 顺序合并。
- tasks.json：T01、T02、T03、T05 → done（T03/T05 的 PR 均已合并，evidence 里补了合并记录）；
  T06/T07/T08 仍 `blocked`（各自的 Q03/Q04/Q01/Q05 未回答）。
- **T04 进行中**：分支 `agent/claude/T04-import-spike`，基于 `main` `5be897f`，owner `claude-routine`，
  只有本次例程会话写入。deliverable 是 `import-spike/`（固定模板解析 + 行级校验 + 预览 +
  重复/修订单识别的 spike，纯 Python，不接 `prototype/` 的 Django 层）、
  `fixtures/synthetic/`（新增 `import-samples/*.xlsx`、`unit-conversions.json`、
  `import-ledger.json`，均标 `synthetic: true`）、`docs/import-contract.md`。

## T04 进度（每一步提交后更新）

| 步骤 | 状态 |
| --- | --- |
| 1. tasks.json 状态（T03/T05→done 补合并证据，T04→in_progress）、HANDOFF | 完成 |
| 2. `import-spike/`：uv 项目骨架 + 依赖锁文件（Python 3.13.12、openpyxl 3.1.5、pytest 9.1.1） | 完成 |
| 3. `import_spike/importer.py`：解析、行级校验（编码/单位/日期/备注覆盖/文件内疑似重复行）、纯函数 `preview()`、`classify_batch()`、`commit_batch()` | 完成 |
| 4. 合成 `.xlsx` 样本（`fixtures/synthetic/import-samples/generate_samples.py` 生成）+ 单位换算配置 + 合成台账 | 完成 |
| 5. `import-spike/tests/test_importer.py`：14 条 pytest，覆盖 A05/A07/A08 | 完成 |
| 6. `docs/import-contract.md` | 完成 |
| 7. 状态改 review、补 evidence、开 draft PR | 待做（本轮最后一步） |

## 可运行检查（T04 分支）

- `python scripts/check_project.py`（仓库根目录）：PASS（8 项任务、14 项验收定义）。只检查文档和任务格式。
- `cd import-spike && uv sync && uv run python ../fixtures/synthetic/import-samples/generate_samples.py && uv run pytest -v`：**14 passed**。完整输出见 [import-contract.md](import-contract.md) 第 6 节。
- 临时变异抽查（未提交）：注释掉"编码存成数字"检查后 1 条测试失败（`test_code_stored_as_number_is_blocked_not_silently_cast`），还原后 14 条全部通过，说明测试能分辨对错。
- **未运行验证**：真实客户文件、PDF 订单解析（Q02，本任务只做到货/验货 Excel）、生产数据库、
  与 T06 `PostImport` 的集成、权限。这些都标在 import-contract.md 里，没有谎称已验证。

## 下一步（一项）

跑完 T04 的交付检查（`git diff --check`、`check_project.py`、pytest）后，把 T04 状态改为
`review`、补 evidence，推送并开 draft PR。

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

- T01（PR #4）、T02（PR #3）、T05（PR #1）、T03（PR #6）均已合并进 `main`；各自的审查往返、
  修正提交和最终 SHA 见对应 PR 页面，不在此重复。
- **供参考**：T03 分支曾出现 PR #5、PR #6 在建立后很快被合并（合并人显示为用户账号，具体是否
  为人工操作还是某次会话所为已无法在本轮确认）。两次合并的内容都只是既定的状态/文档变更，
  未发现被篡改的证据，未做回滚。按本轮指令，例程本身在任何情况下都不合并 PR。
