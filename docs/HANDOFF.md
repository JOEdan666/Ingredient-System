# 当前交接

## 2026-10-01 Claude Code 本机：T11 错误记录（堆叠在 T10 上）

- 分支 `agent/claude/T11-error-log`（基于 T10 分支 `99ddf39`；合并顺序：T06c 标 done → T10 → 本分支）。用户批了验收单（4 条）后开工，并说明接下来 4 小时不用问他。
- 做了什么：新增 `ErrorLog` 表（迁移 0005）、`inventory/errors.py` 中间件、`/errors/` 页与导航入口、`error500.html`。员工看到编号；记录里没有业务数据（不存异常原文、不存查询参数）。
- 技术决定（未问用户）：只记到中间件的异常，业务拒绝和 404 不记；保留最新 1000 条；编号 `E-` + 8 位十六进制；记录写入失败不挡友好页；出错位置取项目代码里最靠里的一层。
- 自己发现并改掉：提示原写「你刚才的操作没有保存」——提交成功后渲染才出错时这句为假，会诱导重复提交；改为「可能没有完成，也可能已经完成，先核对再重试」。
- 实测见 `docs/tasks.json` T11 evidence：131 passed；两个反例失败后恢复；真跑故意出错的演示服务并截图。
- 这 4 小时内只在本机做和提交，**没有推送、没有创建/合并 PR、没有删除任何东西**。
- 下一动作：见下方审查回应。

### 审查叫停回应（Codex gpt-5.6-luna 审 `7a49fb2` → COULD_NOT_VERIFY，无代码/界面缺陷）

- 审查者实跑：prototype 131 passed、import-spike 44 passed、项目检查 PASS、`git diff --check` 通过；注入真实 500 看到中文提示与编号、`/errors/` 可按编号片段查找、404/库存不足/数量错误不入记录、日志写入失败仍显示友好页、插入 1001 条后保留 1000；库存指纹前后一致；另按「首次使用」走了文件导入与已批准真实文件（只看汇总）。完整报告 `/private/tmp/ingredient-acceptance-report-20261001-020758-51056.txt`。
- 唯一理由：Windows 中文文件名/Excel 打开效果（T10 遗留，本机无法产出）。T11 本身不涉及 Windows。**同 T10 回应：接受为未验证，不伪造证据，归 T07；不再重复复审。** 没有可修缺陷，未改代码。
- 下一动作：推送并开 draft PR（PR 里写明此结论）。推送等用户醒来同意。合并顺序：T06c 标 done → T10 → T11。

## 2026-10-01 Claude Code 本机：T10 数据导出 Excel（只读）

- 分支 `agent/claude/T10-data-export`（基于 main `0d65c6b`，并合并了 `agent/claude/T06c-mark-done` 的「T06c 标 done」提交，因项目检查要求依赖任务已 done）。用户批了验收单（4 条）后开工。
- 做了什么：库存页、出库页、历史页各一个「导出 Excel」。库存按页面筛选条件导出（批次货位明细 + 商品汇总 + 说明页）；库存流水、订单各一份。全部 GET、只读；新增 `prototype/inventory/exports.py` 与 `tests/test_exports.py`。
- 技术决定（未问用户）：用已有的 openpyxl；所有文本按文本写（openpyxl 会把 = 开头当公式，导入文件里的商品名可能以任何字符开头）；「可用」口径在说明页标明是 D07 候选、待 Q03；按钮放页面标题右侧（放筛选栏里会把「筛选库存」挤成竖条，已发现并改掉）。
- 实测见 `docs/tasks.json` T10 evidence：pytest 124 passed；反例（删掉按文本写）测试失败；本机合成库真下载三个文件逐格核对；三页截图已看。
- 未验证：Windows 上的文件名/Excel 打开效果（T07）；真实客户数据；大数据量耗时。

### 审查叫停回应（Codex gpt-5.6-luna 审 `49f6f99` → COULD_NOT_VERIFY，无代码/界面缺陷）

- **2026-10-03 新复审 finding（`99ddf39` → CHANGES_REQUESTED）接受并修**：「按货位筛选时明细已筛选，但商品汇总仍是全量」。这会让员工把别的货位数量误算进当前导出。现在商品汇总只合计筛选后的明细；货位/批次/效期/状态筛选下，占用只计算这些明细里已经分配未发的数量，因为未选货位的商品级占用无法归到某个货位。补 B-01 只剩 1 个货主、C-01 明细与汇总都为空的回归测试，并在工作簿说明页写明口径。修后须重跑 Excel 内容核对与独立验收，PASS 前不解除叫停。
- 修复后自检：T10 定向 `9 passed`，prototype 全量 `125 passed`，import-spike `44 passed`，`scripts/check_project.py` PASS，`git diff --check` 无输出。定向测试实际打开导出的 `.xlsx`，确认 B-01 的明细与汇总都只有货主 B（实物/可售/占用/可用 = 5/5/0/5），C-01 两张表都只有表头、没有数据行。下一动作：提交并重跑 `scripts/run_acceptance_review.sh`。

- 审查者实跑：prototype 124 passed、import-spike 44 passed、项目检查 PASS、`git diff --check` 通过；用 drive.mjs 真点了三页导出按钮，三个下载均 200 且带中文文件名；库存指纹前后一致（`balances=4 on_hand=37 allocated=0 movements=4 orders=0 notices=0 hash=df76440d0909d046`）。完整报告 `/private/tmp/ingredient-acceptance-report-20261001-010305-46754.txt`。
- 唯一理由：Windows 上的中文文件名/Excel 打开效果、真实客户数据导出、大数据量耗时没有证据。**接受为「未验证」，不伪造证据**：Windows 归 T07（被 Q01 阻塞），这台 Mac 无法产出；T10 任务书已写明只覆盖 A12 中「重复导出不影响库存」和 Excel 内容中文正常。真实客户数据：本轮只导出合成库，导出表里没有也不会提交真实数据。
- 没有可修的缺陷，所以没有改代码。与 T04f 同一类环境性阻塞（见 T04f 回应），**不再重复复审**，交用户决定是否接受「Windows 部分留在 T07」后合并。
- 下一动作：推送并开 draft PR（PR 里写明此结论）。推送等用户醒来同意。不要把 T10 的结论说成 A12 整体或 Windows 已通过。

## 2026-10-01 Claude Code 本机：T06c 整张订单一次发货

- 分支 `agent/claude/T06c-ship-whole-order`（基于 main `46186e4`，#19 合并后才开，避免冲突）。
- 用户对验收单调用 who-decides：照搬已批做法、无新业务规则的功能不再发验收单（已写进 work-rhythm 第 0 条）。domain.ship 本就支持整单一次发货，本次主要是页面与逐项校验。
- 用户已看截图并说「行」（2026-10-01）。本机实测：pytest 116 passed；3 行订单展开后把第 3 行改成 1 件 → 红字「这次少发 3，留下次」→ 提交「发货完成：3 项，共 6 件」→ 实物 A-01 6→1、B-01 8→7、已分配剩 3。

### 审查叫停回应（Codex gpt-5.6-luna 审 `395430e` → CHANGES_REQUESTED，唯一 1 条中）

- 「改过的行没有移到折叠区外」——**有异议，附证据**。审查者截图 04 里折叠区始终关着，说明它是用脚本直接改了折叠区内的隐藏输入框；真人要改数量必须先点开折叠区，点开后该行当场标红（我方截图 `ship-3-partial-edit.png`）。任务书写的是「改过的项标出『这次少发 N，留下次』」，没有写「移出折叠区」。提交后若有一项不对，服务端会把该行放到折叠区外并写明原因（`test_bad_row_...` 覆盖）。
- 但留一个小隐患交用户决定：改完数量后再把折叠区合上，红字会被藏起来，提交时只有底部一个按钮。可选做法是改数量后自动把摘要改成「N 项已改数量」并标红。**本轮不改代码**（没有新业务规则，改了要重新过闸门）。
- 其余审查结果：4 个自动检查全过（pytest 116 / import-spike 44 / 项目检查 / diff --check），words-versus-behavior 表 6/7 通过，库存发货前后对得上。完整报告 `/private/tmp/ingredient-acceptance-report-20261001-002514-40201.txt`。
- 下一动作：draft PR 已按「无论过没过都开」规则开出，PR 里写明此结论；由用户决定是否要做上面那个小改动，或接受现状后合并。

## 2026-09-30 Claude Code 本机：T06b 整张订单一次选货位

- 分支 `agent/claude/T06b-allocate-whole-order`（基于 main `16752fd`）。用户先批验收单再开发。
- 技术决定：只有「订单指定效期 + 只有一处同效期库存 + 够用」才先填，别的都留给员工（项目规则：员工选批次，不 FEFO）；没配够的行不阻止保存（库存不够时可先存其他行），只有填错/多填/超过可分配才整张拒绝；各行发货/取消卡片默认收起。
## 2026-09-30 Claude Code 本机：T03c 库存页文件夹（用户指出折叠应在库存页）

- 分支 `agent/claude/T03c-inventory-folders`（基于 main `16752fd`）。上一个验收单把「折叠」放错了页面（做在了收货页）；用户截图指出库存页 250+ 商品太长、明细挤在最右一列。原因：我只看过库存页收起状态的第一屏。本次检查包括全部展开与明细打开状态、右侧溢出。
- 技术决定：品牌从商品名开头取；≤2 种商品的品牌并入「其他」（避免只有 1 个商品的文件夹）；只改显示，不涉及库存写入，按 work-rhythm 不送 Codex 审。
- 等待：用户看截图（第 5 步）。

## 2026-09-30 Claude Code 本机：T05b 整张预告一次确认实收（按 work-rhythm 新节奏）

- 分支 `agent/claude/T05b-receive-whole-notice`（基于 main `7073a3b`）。用户先批了验收单（第 2 版，加了折叠），再开发。
- 技术决定（未问用户）：「统一货位」放在表头，否则 50 行都显示「未选货位」而无法折叠；默认货位/状态沿用原页面（收货区、待检），不改业务规则；已收过的单保留逐行「补收」，不减少原有能力。
- 实测见 `docs/tasks.json` T05b evidence。等待：用户看截图（第 5 步）。

## 2026-09-30 晚 Claude Code 本机：审查工具的第二轮加固（Codex gpt-5.6-luna 审）

- 触发：AGENTS.md 第 3 条规则——新工具上线后让另一个模型看一遍。Codex 报 8 条，逐条对照代码确认后全部接受并修。
- `scripts/print_page_check.py`：等 Chrome 退出或 PDF 大小稳定再读（不再见到文件就读）；缺参数、页数非法、Chrome 不在、PDF 损坏都给清楚的一行 FAIL 且退出码 2（页数不符仍是 1）；临时目录一律删除；杀进程不再因已退出而抛错。
- `scripts/run_acceptance_review.sh`：工作区有未提交改动时拒绝运行（审查副本只含已提交内容，否则「通过」会盖在没审过的改动上）；同一分支同时只允许一个审查（目录锁），每次运行文件名带进程号；`trap` 在克隆前安装；真实文件名单缺失时不再静默跳过脱敏，闸门里不放报告正文。
- 顺带发现并修了同类的旧隐患：多处「$变量 + 中文标点」在 bash 里会被当成变量名的一部分，提示文字会变空白（本轮新增的一条更是让脚本报错退出，靠单独复现缺失名单的情形才发现）。全脚本已扫描，无残留。
- 验证：假审查者在临时 HOME 里逐项测——正常 PASS 且锁释放、脏工作区拒绝、并发第二个被拒、名单缺失、错版本记为 SHA_MISMATCH 且警告里有版本号、已有锁的提示带路径；print_page_check 7 种输入的退出码。应用代码未改，不重跑应用审查。

## 2026-09-30 Claude Code 本机：T03b 员工名单（堆叠在 T04f 上）

- Task/owner/branch：T03b，owner `claude-local`；分支 `agent/claude/T03b-staff-list`，基于 T04f 分支 `b7eff8f`（两边都新增迁移，故堆叠，本分支迁移为 0004）。合并顺序：先 T04f（PR #15）再本分支。
- 起因：操作人下拉是写死的「员工甲（合成）」，导致历史记录没有真名。真实姓名只有用户有，所以做成用户自己在页面录入的名单，**不进仓库**。
- 改动：`Staff` 表；`inventory/staff.py`（校验与增删）；所有提交在服务端 `check_actor`；`/staff/` 页与导航；名单为空时提示「操作人现在用的是演示名字」。
- 边界：这不是登录/权限（第一版目标第 7 项）——任何人仍可在下拉里选别人的名字，只是名字必须是名单里的在岗员工。
- 下一动作：跑 `scripts/run_acceptance_review.sh`；无论结论都推送开 draft PR。

## 2026-09-30 Claude Code 本机：T04f 板头纸生成

- Task/owner/branch：T04f，owner `claude-local`；分支 `agent/claude/T04f-pallet-sheet`（基于 `main` `9149af3`，PR #14 已合并）。
- 判断：PROJECT.md 第一版目标第 6 项写明板头纸是「保留数据、模板预览/导出」，桌面 Word 是**员工现在手打的标签样本**，不是要导入的单据；所以做成从订单生成，而不是导入解析。
- 改动：`PalletSheet` 表（迁移 0003，存填写时的快照）；`inventory/pallet_sheets.py`；订单页「打印板头纸」→ 填写页 → 打印页（按样本版式每板一页，浏览器打印/存 PDF）；订单页列出历次板头纸可重印。不读写任何库存表。
- 实测：见 `docs/tasks.json` T04f evidence（73 passed、反例、真实数据演示库上点击生成并导出 PDF 2 页、库存指纹不变）。
- 待问清单（不阻塞）：板头纸是否要印商品/箱数明细；专用标签纸尺寸（现按 A4）。

### 审查叫停回应（Codex gpt-5.6-luna 审 `270f120` → COULD_NOT_VERIFY，无代码/界面缺陷）

- 唯一理由「Windows target validation unavailable」——**有异议，附证据**：Windows 安装、中文文件名与打印属于 T07（`docs/tasks.json` T07 `blocked_by: Q01`，交付物写明「专用打印机适配暂缓，不要求打印验收阻塞试用」）；PROJECT.md 第一版目标第 6 项「专用打印集成以后确认」。T04f 只对 A12 中「重复导出不影响库存」负责，审查者已实测库存指纹不变。任务仍挂 A12（项目检查要求每个任务有验收编号），但交付物里写明 T04f 只覆盖 A12 的库存一句，Windows 部分归 T07。
- **第 2 轮复审（`b7eff8f`）**：仍为 COULD_NOT_VERIFY、仍无代码/界面缺陷；理由是「无 Windows 证据」和「实际打印/存 PDF 未演练」。后者接受并补：新增 `scripts/print_page_check.py`（无头 Chrome 导出 PDF，报页数和每页末行；`… 2` 通过，`… 3` 失败退出 1，本机实测），并加入审查者的「打印页」关卡。前者仍是异议：Windows 归 T07，无法在这台 Mac 上产生证据。按 AGENTS.md「同一问题两次修不掉就停」，**不再第 3 次复审**，交用户决定是否接受「Windows 部分留在 T07」。
- **定时开发者按叫停指令复审（`4cb3a21`）**：独立审查再次为 `COULD_NOT_VERIFY`，唯一原因仍是这台 Mac 无法提供 A12 的 Windows 证据；没有发现可复现代码或界面缺陷。本轮已补齐并由审查者亲自验证此前缺失的 PDF 证据：Chrome 导出 2 页成功，页末分别为「共2板 (1/2)」「共2板 (2/2)」；`shot.sh` 成功且截图已目视检查；库存指纹生成、重印前后均为 `balances=4 on_hand=37 allocated=0 movements=4 orders=1 notices=0 hash=df76440d0909d046`。接受「A12 整体仍未验收」这一结论，但不通过删除或放宽 Windows 验收来换 PASS；Windows 中文文件名、内容和实际打印继续由受 Q01 阻塞的 T07 处理。完整报告：`/private/tmp/ingredient-acceptance-report-20260930-143349.txt`。同一环境阻塞已重复，按 AGENTS.md 停止继续修补并交接。
- **本轮审查叫停回应（Codex gpt-5.6-luna 审 `3307c21` → CHANGES_REQUESTED）**：接受「多张长订单号被 `[:200]` 静默截断」；这会让板头纸漏印部分订单号。修复为合并文本超过 200 字时整单拒绝并提示减少订单，不保存残缺快照；新增 6 张长订单、合计 255 字的回归测试，要求错误码 `order_numbers_too_long`、提示可见且数据库不生成板头纸。Windows 中文文件名、内容与实际打印仍接受为 A12 未验证项，继续留给 T07，不伪造本机证据。
- **修复后独立验收（`c1c4c64`）**：`ACCEPTANCE_VERDICT: PASS`。审查者实跑 prototype `74 passed`、import-spike `44 passed`、项目检查 PASS、PDF 2 页、首次用户生成与重印、长订单号超限明确拒绝、截图目视检查和库存指纹不变；完整报告 `/private/tmp/ingredient-acceptance-report-20260930-151602.txt`。PASS 只覆盖 T04f 当前范围，Windows 中文文件名和实体打印仍未验证，归 T07。
- 附带：第 2 轮 `shot.sh` 曾没跑完；`4cb3a21` 复审已成功运行并完成目视检查，此项已关闭。
- 下一动作：保持 T04f 为 `review` 和 PR #15 为 draft，由用户决定是否合并已通过的 T04f 范围；待具备 Windows 目标环境并明确 Q01 后，再由 T07 补中文文件名、内容和实体打印证据。不要把 T04f PASS 说成 A12 全部或 Windows 打印已通过。

## 2026-09-30 Claude Code 本机：T04e 文件真正可导入 + 独立验收闸门

- Task/owner/branch：T04e，owner `claude-local`；分支 `agent/claude/T04e-import-posting`（从 `agent/codex/T03-ui-rework` 的 `f289917` 接着做，独立 worktree `~/work/Ingredient-System-import`）。
- 起因：用户实测「连导入 Excel 和 PDF 都不可以」。独立验收审查者（Codex 无额度，自动换 Claude 执行）对 `17e2160` 判 **CHANGES_REQUESTED**，报告见本机 `~/agent-archive/review-gate/Ingredient-System/agent__codex__T03-ui-rework.md`。

### 审查叫停回应（逐条）

1. 高「页面叫导入却只能预览」——**接受并修**。新增确认入账：`inventory/import_posting.py` 在一个事务里经领域命令入账（库存表→`post_opening` 期初；验货纸→`create_notice` 收货预告；PDF→`accept_order` 接单占用），任一行失败全部撤销。导航仍叫「文件导入」，现在名副其实。
2. 中「货主、外部单号随便填也通过，页面不说明」——**接受并修**。货主改为从已有货主选择，或明确新建（页面说明「这批货属于哪家客户」，确认页标出「新货主，入账时创建」）；外部单号收进「一般不用填」，不填时自动取 PDF 的 INV No.、验货纸文件名里的 SO 号、库存表文件名。文件类型不再让人选，按文件内容自动识别。
3. 中低「汇总直接显示英文错误代码」——**接受并修**。汇总按中文问题分组，每类都写「怎么办」；整箱单位问题直接在页面逐行选择件/箱并留名。
4. 低「PDF 单号不显示、填的单号被悄悄丢掉」——**接受并修**。确认页显示读出的单号；PDF 以单据上的单号为准，输入框说明了这一点。
5. 低「390px 宽度右侧被截」——**接受，部分修**：上传区与表格在窄屏改为单列/可换行；目标是 Windows 台式机，未做完整手机适配。
6. 流程「T04d 不在任务清单」——**接受并修**：本轮登记为 T04e（`docs/tasks.json`）。

### 审查叫停回应（第 2 轮：Codex 审 `e0b901e` → CHANGES_REQUESTED）

1. 高「期初切换边界未建立就允许入账」——**接受并修**。库存表确认时必须填「从客户系统导出的时间」并选择「数字是仓库实物数 / 已扣未出货订单」；选「已扣」直接拒绝（会重复扣减）；时间晚于现在拒绝。两者记在导入记录和每条期初流水的来源单据上。PDF 单据日期不晚于导出日时，必须由操作人勾选「导出时这张单还没发货/没扣」才能接单，并记下确认人。Q05 的业务答案仍未知，这里只是把边界由人明确说出并留痕，不替客户猜。
2. 高「先传 PDF、再建商品，原预览不解除」——**接受并修**。「商品不在系统里」改为每次打开核对页和入账时按当前数据重新检查，不再固定在上传那一刻；提示改为「导入库存表后回到这一页即可，不用重新上传」。实测：先传 PDF（9 行被拦）→ 导入库存表 → 回到 PDF 页自动变 9 行通过。
3. 中「订单失去原文件行号」——**接受并修**。订单行新增原件位置（PDF 用纸面上的「序号」），订单来源写「导入#N 文件名 sha256 前 12 位」；订单页和历史查询页都显示。
4. 中「单位确认可留下空操作人」——**接受并修**：缺操作人直接拒绝。
5. 中「重复文件汇总显示可入账」——**接受并修**：汇总改为「行检查通过 / 行需要处理 / 整份状态」，整份状态与下方结论一致；「最近导入」列表同样显示「不能入账」。
6. 低「提交了指向本机的 .venv 链接」——**接受并修**：移出版本库，`.gitignore` 忽略 `.venv`。

另：审查者 token 消耗过大（上一轮约 790 万输入 token、68 次调用）。已给审查指令加硬预算：约 25 次调用、输出只看尾部、截图最多 6 张单屏、复审只看上次闸门之后的改动、库存证明用 `scripts/stock_fingerprint.py`；推理强度 high→medium；Claude 兜底改用 Sonnet。

### 本轮改动

- 导入：`ImportBatch` 表（迁移 0002）保存读出的行供人核对，原文件不保留；同一文件、或同一货主第二份库存表，在点确认前就提示「拒绝」，入账时再查一次。
- 候选映射规则（**未经客户确认**，已记入下方待问）：库存表=期初且每货主一次；验货纸「实收」栏为空，按收货预告处理，不加库存；NG 仓行按冻结入账，货位记为 `NG:<仓库名>`；PDF 按接单占用，指定效期写为订单行指定效期。
- 验收闸门：`scripts/run_acceptance_review.sh` 先用 Codex 跑 `acceptance-reviewer`，Codex 没给出结论（额度、报错、超时）就用同一份指令换 Claude Code；结论写到 `~/agent-archive/review-gate/`，非 PASS 时 `.claude/hooks/review-gate.sh` 每次会话/每次发言都把叫停内容塞给 Claude，AGENTS.md 第 5 条要求两边先逐条回应。审查者新增「新手首次使用」和「页面说法对照实际行为」两道关，UI 操作必须用 `~/ai-hub/shared-skills/see-it-run/drive.mjs` 真实点击，curl 不再算数。
- 实测：见 `docs/tasks.json` T04e evidence（55 + 44 passed、反例、真实文件从空库走完）。

### 待问清单（不阻塞本轮，暂按候选规则）

- Q05：客户库存导出数是否已扣未出货订单（影响期初）。
- Q04：整箱商品数量栏印 EA 的含义（现在由员工逐行选择）。
- 验货纸：是入库前的到货清单（现按收货预告），还是出库前的验货单？
- 操作人下拉仍是合成员工名，正式试用前需换成真实员工。

### 下一动作

跑 `scripts/run_acceptance_review.sh` 审最终提交；PASS 前不算完成。


## 2026-09-29 Codex 本机：真实文件预览界面

- Task/owner/branch：T03/T04b/T04c 的本机预览衔接，owner `codex-local`；分支 `agent/codex/T03-ui-rework` 已合并远端 `main` `7ed4296`，未推送。
- 改动：导航新增“文件导入”，支持库存表 Excel、验货纸 Excel、PDF 订单；复用 `import-spike/` 已审查解析器，上传文件只写临时文件并在解析后删除。页面显示汇总，真实行明细默认折叠；本功能只预览、不调用库存领域命令。
- 真实文件只读界面验证：库存表识别 478 行，478 行可继续确认、0 行阻塞；一份 PDF 识别 4 行，1 行可继续确认、3 行因 `unit_needs_confirmation` 阻塞，整份显示“暂不能入账”。截图只保存在 `/private/tmp/ingredient-import-proof/`，未进入仓库。
- 自动验证：`prototype/.venv/bin/python -m pytest -q` → 45 passed；`import-spike` 同一锁定环境 → 44 passed；`python3 scripts/check_project.py` → PASS。页面测试确认预览不会增加 `StockBalance`。
- 边界：尚未实现“人工确认后正式过账”，板头纸 `.docx` 仍无解析器；真实数据不会写入本机 SQLite。下一动作是独立复审当前最终提交，再决定是否推送和开 PR。

## 2026-09-29 Codex 本机：T03 界面复盘（独立本地分支）

- 用户指出此前预览观感差，并提醒桌面有真实文件。分支 `agent/codex/T03-ui-rework` 从 `main` 建独立 worktree，不触碰 Claude 正在写的 T04c 分支。
- 调整 T03 四页的导航、标题、筛选和表格样式；只改模板，没有修改库存命令或数量规则。
- 本机用 Django 5.2.17 和合成夹具启动在 `127.0.0.1:8766`，通过浏览器逐页查看库存、收货、出库、历史查询；`prototype` 的 pytest 为 42 passed，`scripts/check_project.py` 为 PASS。
- 桌面客户文件已定位；T04b 曾对真实库存表与验货纸做只读格式核对。**T03 网页仍只接合成数据，不能上传、预览或确认真实 Excel/PDF，也不能据此声称真实业务流程可用。** 下一步应以真实文件结构为依据，设计私有环境中的“解析预览 → 人工确认 → 过账”界面与验收，不把客户数据提交到公开仓库。

## 2026-09-29 Claude Code 本机：T04c PDF 送货单商品行

- Task/owner/branch：T04c，owner `claude-local`（Codex 本机会话额度用完后交接）；分支 `agent/claude/T04c-pdf-order-lines`，基准 `main` `0a5be88`（PR #11 已合并，T04b 同步标 `done`）。开工期间占住本机 Codex 定时任务的锁文件，避免同一任务被两边同时写。
- 改动：新增 `import-spike/import_spike/pdf_order.py` 与 17 条测试；按两份真实 PDF 的结构修正合成样本（旧样本多一行数量、序号 1 的位置不对）；契约见 [import-contract.md](import-contract.md) 第 10 节。
- 实测：`/private/tmp/ingredient-t04b-venv/bin/python -m pytest -q import-spike/tests` → 44 passed；`python3 scripts/check_project.py` → PASS；反例改坏配对/合计核对各自有测试失败。真实 PDF 只读核对只输出计数与错误类别。
- 未验收：Q04（整箱商品数量栏印 EA 的含义）、Q02 其它版式、过账（T06）。
- 审查：Codex 审 `745f912` 提出 3 条缺陷，均复现并修复（见 tasks.json T04c 证据）；修复提交尚未再审。
- 下一动作：推送分支并开 draft PR，由独立审查者复核最终提交。

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
