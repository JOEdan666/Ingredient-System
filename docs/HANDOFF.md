# 当前交接

更新：2026-09-29（Claude Code 定时开发例程，T09 已推到 review，等待人工/审查者合并）。

## 当前状态

- `main` = `0064a62`：启动包、T02、T01、T05、T03、T04、状态同步、plan-real-formats 已按
  #2 → #3 → #4 → #1 → #5 → #6 → #7 → #8 → #9 顺序合并。
- tasks.json：T01–T05 → done；T06/T07/T08 仍 `blocked`（Q03/Q04/Q01/Q05 未回答）；
  T09 本轮改为 `review`（见下）；T04b `ready`、T04c `queued`、T06a `ready` 待后续例程按顺序开工。
- 本轮例程（分支 `agent/claude/T09-ci-pytest`，基准 `main`=`0064a62`）：
  - 第 0 步：`git branch -r --no-merged origin/main` 一开始因 fetch 时序短暂显示
    `agent/claude/status-sync-2026-09-29` 未合并，重新 fetch 后确认该分支其实已通过
    PR #8 合并进 main（`git merge-base --is-ancestor` 验证），不是遗留分支，按空分支处理进入第 1 步。
  - 第 1 步：未发现 `review` 状态任务需要补记合并状态；按 tasks.json 顺序挑到 T09
    （合并前自动测试：GitHub Actions 跑 prototype 与 import-spike 的 pytest），
    depends_on T03/T04 均已 done，blocked_by 为空。
  - 第 2/3 步：新增 `.github/workflows/pytest.yml`（不改 `project-checks.yml`）：两个
    `ubuntu-24.04` job（`prototype`、`import-spike`），`actions/checkout` + `astral-sh/setup-uv`
    均按 commit SHA 固定（用 `git ls-remote --tags` 于 2026-09-29 解析：
    `actions/checkout` = v4 = `11d5960a326750d5838078e36cf38b85af677262`；
    `astral-sh/setup-uv` = v9.0.0 = `c771a70e6277c0a99b617c7a806ffedaca235ff9`，
    uv 版本固定 `0.12.20`，来自 PyPI `uv` 包 2026-09-29 的 latest），
    各自 `uv run --frozen pytest -ra`。新增 `docs/test-commands.md` 记录本地/CI 命令与实际输出。
  - 第 4 步：`python scripts/check_project.py` PASS；`git diff --check origin/main...HEAD` 无输出；
    `prototype/` 与 `import-spike/` 的 `uv run --frozen pytest -ra` 均全部通过（见下）；
    T09 标记 `review`，evidence 见 tasks.json。

## 可运行检查（本轮实际运行，2026-09-29，Linux 云容器）

```
$ python scripts/check_project.py
PASS: 12 tasks, 14 acceptance definitions, synthetic fixture and local links

$ git diff --check origin/main...HEAD
(无输出)

$ cd prototype && uv run --frozen pytest -ra
============================== 42 passed in 2.11s ==============================

$ cd import-spike && uv run --frozen pytest -ra
============================== 14 passed in 0.16s ==============================

$ cd import-spike && uv run --frozen pytest -ra /tmp/empty_test_dir   # 验证 0 条测试时的退出码
collected 0 items / no tests ran / exit code 5
```

未运行验证：新工作流在真实 GitHub Actions 上的执行结果（含 `astral-sh/setup-uv` 实际下载、
uv 0.12.20 在 Actions runner 上的行为）——本地只验证了 pytest 本身的退出码语义，不是 Actions 环境；
PR 提交后由 Actions 的 checks 标签给出真实结果。

## 下一步（一项）

T09 的 draft PR 等待审查（Claude 审查者或人工）；本例程不合并任何 PR。下一次例程接手时：
先重复第 0 步检查 `agent/claude/T09-ci-pytest` 对应的 open PR 是否有
`REVIEW_VERDICT: CHANGES_REQUESTED` 需要按意见修改，或已合并需要在第 1 步把 T09 记为 `done`；
若已处理完 T09，再按 tasks.json 顺序挑下一个：T04b（真实格式库存表/验货纸导入）或 T06a
（PostgreSQL 领域层与并发测试），二者当前都满足开工条件（depends_on 已 done、blocked_by 为空）。
T06/T07/T08 仍需业务方回答 PROJECT.md「关键未决项」表中的 Q01/Q03/Q04/Q05 之一才能解除阻塞。

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
