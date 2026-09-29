# 测试命令

更新：2026-09-29（T06a）。记录本地与 CI 实际运行的命令，不是客户业务验收（见 docs/acceptance.json）。

## 范围

三个 Python 子项目各自带 `pyproject.toml` + `uv.lock`：

- `prototype/`：T03 四屏流程原型（Django 5.2，模拟持久化，不证明并发/锁）。
- `import-spike/`：T04 固定格式导入解析 spike（不过账，不连数据库）。
- `application/`：T06a Django 5.2.17 + psycopg 3 + PostgreSQL 的领域命令和数据库测试；只含领域层，无部署或界面。

Q03 展示口径与 Q04 单位/NG 规则仍属候选，不能据此声称客户验收通过。

## 本地运行

依赖 [uv](https://docs.astral.sh/uv/)（本次用 `uv 0.8.17` 验证，CI 固定 `0.12.20`；两者都能解析各目录的 `uv.lock`）。`--frozen` 表示严格按锁文件安装，不重新解析依赖。

```bash
cd prototype && uv run --frozen pytest -ra
cd import-spike && uv run --frozen pytest -ra
# 先启动 PostgreSQL，创建 ingredient_test 数据库，赋予测试用户 CREATEDB 权限。
# 用 PGHOST、PGPORT、PGUSER、PGPASSWORD、PGDATABASE 指向这台测试库。
cd application && uv run --frozen pytest -ra
cd application && uv run --frozen pytest -m concurrency --junitxml=concurrency.xml -ra
cd application && uv run --frozen python check_concurrency_junit.py concurrency.xml
```

实际运行（2026-09-29，Linux 云容器，Python 3.13.12）：

```
$ cd prototype && uv run --frozen pytest -ra
============================== 42 passed in 2.14s ==============================

$ cd import-spike && uv run --frozen pytest -ra
============================== 14 passed in 0.33s ==============================
```

## CI

`.github/workflows/pytest.yml`（T09 新增，独立于 `.github/workflows/project-checks.yml`，不改动后者行为）：

- 触发：`pull_request`、`push` 到 `main`、手动 `workflow_dispatch`。
- 两个 job，均在 `ubuntu-24.04` 上：`prototype`、`import-spike`，各自 `actions/checkout` 后用 `astral-sh/setup-uv` 安装固定版本 uv，再 `uv run --frozen pytest -ra`。
- Actions 均按 commit SHA 固定版本（`actions/checkout@11d5960a...` = v4，`astral-sh/setup-uv@c771a70e...` = v9.0.0，均于 2026-09-29 用 `git ls-remote --tags` 核对解析）。
- 收集到 0 条测试时失败：pytest 在未收集到任何测试时以退出码 5 结束（非 0），CI 步骤按 shell 惯例视为失败，两个 job 都不需要额外判断逻辑。已验证：本地对着一个空目录跑 `uv run --frozen pytest -ra /tmp/empty_test_dir`，输出 `no tests ran`，退出码 5（2026-09-29，import-spike 环境）。**未运行验证**的是同一断言在真正的 GitHub Actions 环境里的表现（本地验证的是 pytest 本身的返回码语义，不是 Actions runner）。
- `postgres:` 服务容器留给 T06a（本文件届时补充连接串、迁移和并发测试命令）。

CI 是否真的通过：本次改动未在 GitHub Actions 上实际运行（**未运行验证**，PR 提交后由 Actions 自动跑，结果见 PR 的 checks 标签）。本地 `uv run --frozen pytest` 的结果如上，用来确认锁文件和测试本身在改动前是绿的。

## T06a PostgreSQL 领域层

`.github/workflows/db-tests.yml` 在本任务分支 push、PR 和 main push 时独立起 `postgres:18.6` 服务容器，先跑全部测试，再单独跑标记为 `concurrency` 的 13 条测试并读取 JUnit 结果；少于 13 条或有失败时退出非零。CI 设置 `REQUIRE_PG18=1`，数据库版本测试必须读到 18.x。镜像版本依据 [PostgreSQL 官方 18.6 发布记录](https://www.postgresql.org/about/news/postgresql-186-1711-1615-1519-1424-and-19-beta-3-released-3365/)，2026-09-29 查阅。

本机调试使用临时 PostgreSQL **14.22**（不是目标版本）、Python 3.13.5、uv 0.12.20、Django 5.2.17。测试库位于 `/private/tmp/ingredient-pg14`，连接端口 55432；测试数据全是合成值。实测：

```
$ cd application && uv run --frozen pytest -ra
43 passed in 4.61s
$ cd application && uv run --frozen pytest -m concurrency --junitxml=/private/tmp/ingredient-concurrency.xml -ra
13 passed, 30 deselected in 2.00s
$ cd application && uv run --frozen python check_concurrency_junit.py /private/tmp/ingredient-concurrency.xml
concurrency: executed=13, expected>=13, failed=0
```

未分配订单竞态参数重复 3 次；其余并发用例各运行一次。钩子停住事务 A 后，测试确认 B 到达加锁点，查 `pg_stat_activity.wait_event_type='Lock'`，再放行 A；未加 `FOR UPDATE` 的专用反例用例能检测到 B 在 A 提交前读到旧量。版本 18 的实际结果以分支 GitHub Actions 记录为准；本机 14 的通过不能替代它。
