# T04 固定格式库存与验货导入验证

任务：T04 · 作者：Claude Code（定时开发例程，owner `claude-routine`）· 日期：2026-09-29 · 基准：`main` `5be897f`
验收关联：A05 A07 A08 · 决策关联：D04 D05 · 设计依据：[domain-model.md](domain-model.md) 第 1、7、8 节

> **范围边界**：本任务是一个 spike（`import-spike/`），只证明"解析固定模板 → 行级校验 → 预览 →
> 重复/修订单识别"这条链路的规则，用合成数据和真实运行的 pytest 验证。它**不**连接
> `prototype/` 的 Django 领域层，也不写任何 `StockMovement`。把预览确认后的批次真正过账
> （`domain-model.md` 第 5 节的 `PostImport` 命令、Operation 幂等、同一数据库事务）是 **T06**
> 的工作，T06 开工时应复用这里验证过的解析/校验/去重规则，而不是重新发明。

| 标记 | 含义 |
| --- | --- |
| **[事实]** | PROJECT.md / AGENTS.md / DECISIONS.md 已确认的规则 |
| **[候选]** | 本 spike 的工程做法，可改，需在 T06 复核 |
| **[待确认]** | 需要业务答复 |
| **[已验证]** | 本次用 pytest 在合成 `.xlsx` 文件上实际跑过 |
| **[未运行验证]** | 没有运行过（本 spike 完全不涉及） |

## 1. 结论

- **[已验证]** `import-spike/import_spike/importer.py` 实现了固定模板解析、行级错误/警告、
  批次预览（纯函数，不产生任何副作用）、以及"完全重复文件"与"同单号但内容不同（修订单）"
  两种情况的区分。`cd import-spike && uv run pytest -v`：**14 passed**（见第 6 节完整输出）。
- **[已验证]（反例）** 手工做过两次临时变异（未提交）：注释掉"编码存成数字"检查后，
  `test_code_stored_as_number_is_blocked_not_silently_cast` 失败；还原后 14 条全部通过。
  说明测试真的在检查这条规则，不是摆设。
- **[未运行验证]** 真实客户的 PDF 订单解析、真实 Excel 到货表样式、生产数据库、T06 的
  `PostImport` 集成、权限。
- **更正（2026-09-29，审查后）**：A05 在 `docs/acceptance.json` 里是 `stage: database`、`status: not_run`，
  本 spike 只用内存/JSON 台账，**没有验证** A05 要求的数据库事务、响应丢失后重试、并发提交。
  下文所有「幂等」「不会多长一条」只指单进程顺序调用的内存台账。
- **已知缺陷（2026-09-29 Codex 审查 `1815591`，本机核实）**，本 spike 不再修补，改由 T04b 按真实格式重做时必须避开：
  1. `commit_batch` 不按最新台账重新判重：两次都基于旧 `preview()` 的结果提交，会入账两次。
  2. 数量单元格为 `TRUE/FALSE` 时被当成 1/0（`bool` 是 `int` 的子类）。
  3. 备注里的负数或 `实际数量=7` 这类写法匹配不到，备注覆盖冲突被静默忽略。
  4. 已确认的单位换算（如 CS→EA ×24）只做了"认不认识"的检查，没有真正换算成基本单位，也不检查结果是否为整数。
  5. Excel 的 `datetime` 效期原样传出，不是纯日期。
  6. 同一文件里混有不同单据版本时，批次版本静默取第一行。
  7. 本节原文把 A05 写成已验证（已在上面更正）。
- **[待确认]** Q02（PDF 订单版式与自动识别必需程度）、Q04（单位、NG 货、未知效期、跨批规则）
  仍未回答；本 spike 对这些一律采用"拦截，人工处理"的候选规则（见第 4、5 节）。

## 2. 固定模板契约

第一版只支持**一种**到货/验货 Excel 模板（`TEMPLATE_VERSION = "receiving-v1"`），工作表名
`到货`（找不到就用第一个工作表）。表头必须逐字匹配下表左列，顺序不限、允许多余列（多余列
被忽略而不是报错，方便客户模板里夹杂人看的辅助列）：

| 表头（中文） | 内部字段 | 必填 | 说明 |
| --- | --- | --- | --- |
| 货主 | owner | 是 | 见 D04；本 spike 假定整份文件同一货主，混货主直接拒绝整批 |
| 外部单号 | external_doc_no | 是 | 用于重复/修订单识别（D05） |
| 单据版本 | doc_version | 否 | 客户自己标注的版本号，仅记录，不参与判定；判定只看文件字节和外部单号 |
| 商品编码 | code | 是 | **必须是文本单元格**；数字类型单元格判定为"前导零可能已丢失"，整行拦下（D04） |
| 商品名称 | name | 是 | 原样保留 |
| 数量 | quantity | 是 | 必须是数字，且 ≥ 0；负数拦下，不clamp 成 0（AGENTS.md） |
| 单位 | unit | 是 | 必须是该商品已确认的换算版本，或本身就是基本单位 `EA`；否则拦下（D04、AGENTS.md 不自动转换未知单位） |
| 效期 | expiry_raw | 否 | 见第 4 节；空白 = 未知，不当作批号、不编造日期（D04） |
| 外部批号 | external_lot | 否 | 缺失时记为未知，不用效期顶替（D04） |
| 备注 | remark | 否 | 若写着"实际数量 N"且与正文数量不一致，整行拦下，不自动采用备注值（D05） |

## 3. 重复与修订单识别（A05）

判定只依赖两样东西，不看文件名、不看"单据版本"这种客户自己填的字段：

1. **文件指纹** = 整个文件字节的 SHA-256（`import_spike.importer.file_fingerprint`）。
2. **业务身份** = (货主, 外部单号)。

| 情况 | 分类 | 行为 |
| --- | --- | --- |
| 指纹和台账里某条完全一致 | `exact_duplicate` | 不可过账；`commit_batch` 拒绝，返回原批次的指纹供人工核对 |
| 指纹不同，但 (货主, 外部单号) 已存在 | `revision` | 不可过账，**不自动覆盖**原批次；需要人工决定用哪一份，或作为一次独立的纠正/冲正走 T06 的 `Reverse/Adjust` |
| 都不匹配 | `new` | 若所有行都可过账（见第 4 节），批次本身可过账 |

**[已验证，仅内存台账、顺序调用]** `preview()` 是纯函数：多次对同一台账调用，不会修改台账，也不会因为"看过一次"
就把分类从 `new` 变成别的（`test_preview_has_no_side_effects_and_is_repeatable`）。只有显式
调用 `commit_batch()` 才会在返回的新列表里追加一条记录；重复调用或对不可过账的批次调用都会
被拒绝，不会让台账"多长一条"（`test_exact_duplicate_upload_is_detected_and_not_postable`、
`test_commit_rejects_non_postable_batch_and_does_not_grow_ledger`）。

台账本身在本 spike 里是合成 JSON（`fixtures/synthetic/import-ledger.json`），不是数据库；
T06 里这张台账应该就是真实的 `ImportBatch` 表，用文件指纹和 (owner, external_doc_no) 建索引。

## 4. 日期规则（A07）

只有 ISO 格式（`YYYY-MM-DD`）或 Excel 原生日期单元格算"明确"（`expiry_status = "known"`）。

| 输入 | 处理 | status |
| --- | --- | --- |
| 空白 | `expiry_date = None`，**允许过账**（未知不是错误，只是不编造） | `unknown` |
| `YYYY-MM-DD` | 按值解析 | `known` |
| `A/B/年`，A、B 都 ≤ 12 且不相等 | 无法判断谁是日谁是月，**不猜**，`expiry_date = None`，拦下 | `ambiguous` |
| `A/B/年`，A 或 B > 12 | 能唯一确定日/月，算出 `expiry_date`，但**仍然拦下**要求人工确认（模板要求 ISO，这种格式本身就不该出现） | `ambiguous` |
| 其他无法识别的字符串 | `expiry_date = None`，拦下 | `ambiguous` |

**[已验证]**：`test_missing_expiry_is_recorded_as_unknown_not_invented`（空白可过账）、
`test_genuinely_ambiguous_date_is_not_guessed`（`03/04/2026` 两段都 ≤12，`expiry_date is None`）、
`test_non_iso_but_determinable_date_is_flagged_with_a_guess`（`25/12/2026` 算出 2026-12-25，
但仍标记需要确认、不可直接过账）。

## 5. 单位、编码、备注覆盖（A07 A08）

- **单位**：`fixtures/synthetic/unit-conversions.json` 里 `base_units` 列出免换算的基本单位
  （目前只有 `EA`），`confirmed` 列出逐条确认过的 (owner, code, unit, factor_to_base)。不在
  这两处的单位一律拦下过账，不猜换算系数（`test_unconfirmed_unit_blocks_posting`、
  `test_confirmed_unit_conversion_allows_posting`）。
- **编码**：单元格必须是文本类型（openpyxl `data_type == "s"`）。存成数字类型的编码（例如
  `00456` 被 Excel 自动转成 `456`）直接拦下、**不猜测补零**，因为补多少个零是猜的
  （`test_code_stored_as_number_is_blocked_not_silently_cast`）。
- **备注覆盖正文**：D05 明确提到"备注里实际数量覆盖正文"必须有行级提示和人工确认。本 spike
  用正则 `实际数量[:：]?\s*(\d+(\.\d+)?)` 识别这种备注；数值和正文数量不一致时拦下整行，
  **保留正文数量**，不自动采用备注值（`test_remark_quantity_override_is_not_auto_applied`）。
- **文件内重复行**：同一文件里 (货主, 编码, 外部批号, 效期原文, 数量) 完全相同的多行，
  **不静默合并**成一行，只打一个"看起来重复，可能是合法多行"的警告（不拦），两行各自可过账
  （`test_duplicate_looking_rows_are_kept_separate_not_merged`），对应 AGENTS.md
  "绝不静默合并疑似重复的来源行"。

## 6. 实际运行的命令与输出

平台：Linux 云容器，Python 3.13.12，2026-09-29。

```
$ cd import-spike && uv sync
Resolved 9 packages in 192ms
Installed 7 packages in 17ms
 + et-xmlfile==2.0.0
 + iniconfig==2.3.0
 + openpyxl==3.1.5
 + packaging==26.3
 + pluggy==1.6.0
 + pygments==2.21.0
 + pytest==9.1.1

$ uv run python ../fixtures/synthetic/import-samples/generate_samples.py
wrote receiving_normal.xlsx, receiving_revision.xlsx, receiving_unit_confirmed.xlsx, receiving_bad_rows.xlsx

$ uv run pytest -v
tests/test_importer.py::test_new_batch_is_postable_and_classified_new PASSED
tests/test_importer.py::test_preview_has_no_side_effects_and_is_repeatable PASSED
tests/test_importer.py::test_exact_duplicate_upload_is_detected_and_not_postable PASSED
tests/test_importer.py::test_revision_is_flagged_not_silently_superseded PASSED
tests/test_importer.py::test_commit_rejects_non_postable_batch_and_does_not_grow_ledger PASSED
tests/test_importer.py::test_leading_zero_code_is_preserved_as_text PASSED
tests/test_importer.py::test_code_stored_as_number_is_blocked_not_silently_cast PASSED
tests/test_importer.py::test_unconfirmed_unit_blocks_posting PASSED
tests/test_importer.py::test_confirmed_unit_conversion_allows_posting PASSED
tests/test_importer.py::test_missing_expiry_is_recorded_as_unknown_not_invented PASSED
tests/test_importer.py::test_genuinely_ambiguous_date_is_not_guessed PASSED
tests/test_importer.py::test_non_iso_but_determinable_date_is_flagged_with_a_guess PASSED
tests/test_importer.py::test_duplicate_looking_rows_are_kept_separate_not_merged PASSED
tests/test_importer.py::test_remark_quantity_override_is_not_auto_applied PASSED
14 passed in 0.15s

$ python3 scripts/check_project.py   # 仓库根目录
PASS: 8 tasks, 14 acceptance definitions, synthetic fixture and local links
Application, database, installer and printing tests have NOT been run by this check.
```

**未运行或无法验证**：PDF 订单解析（Q02，客户订单是 PDF 不是 Excel，本任务范围是到货/验货
Excel 表，PDF 解析留待另行评估）；真实客户文件；生产数据库；把预览确认结果接进 T06 的
`PostImport` 事务；权限（A14）；箱规/多级单位换算的完整矩阵（只做了单条确认换算的正例）。

## 7. 仍待确认的假设

| 假设 | 当前处理 | 阻塞什么 |
| --- | --- | --- |
| Q02 PDF 订单版式、是否需要自动识别 | 本任务不覆盖 PDF，只做 Excel 到货表 | 订单导入功能范围 |
| Q04 单位、NG 货、未知效期、跨批合并规则 | 未知单位/含糊日期一律拦截、人工处理；不做库存状态相关判断 | 这些情况的实账处理 |
| 真实客户模板是否与本契约的表头/列序一致 | 假设与 PROJECT.md 描述的到货/验货 Excel 一致，未用真实样本核对 | 真实文件对接（仅限获准私有环境） |
| 备注覆盖正文的识别方式是否够用 | 只识别"实际数量 N"这一种措辞 | 真实备注措辞多样时的识别率 |

## 8. 影响与交接

- 涉及迁移、单位、日期、库存规则、权限或部署：**否**。本任务不产生任何持久化数据，
  `fixtures/synthetic/import-ledger.json` 只是合成台账，不代表任何真实导入历史。
- T06 开工时应当：把 `import_spike/importer.py` 的解析/校验/去重函数迁移或适配进 Django 领域层，
  ledger 换成真实数据库表，`commit_batch` 换成真正调用 `domain.py` 的 `PostImport`（在同一数据库
  事务里，见 `domain-model.md` 第 5 节），并补充 PostgreSQL 并发测试（A06 范围之外，A05/A08
  在真实数据库上的重复提交测试仍需补）。

## 9. T04b 真实结构解析（本地验证，未过账）

- `real_format.py` 分别读取库存导出表和验货纸，返回带源行号、原始单元格、规范字段和行级错误的 `ImportLine`。库存表不合并同编码多行；货主与快照单号由调用方明确传入；` NG` 仓暂记为 `HOLD` 候选；空仓位只允许在该候选状态下通过。斜杠效期解析为纯 `date`。
- 验货纸跳过标题、双层表头与仅有汇总字段的末行；保留空的实收/多收/少收为 `None`。该表的“存倉數量 (件)”与“收貨數量 件”已经标成件，不能因 `Item UOM=CS` 再乘箱规；显式标成 CS 的数量可用 `convert_to_ea` 按 `Piece Per Case` 换算。此区分仍需业务方确认后才能用于实际过账。
- T04 旧解析器同时修正预览后台账变化的重复判定、布尔数量、备注负数及等号写法、已确认单位换算整数校验、`datetime` 转纯日期、混合单据版本拦截。它仍然只是内存台账，不代表 A05 数据库验收通过。
- 本机运行：`/private/tmp/ingredient-t04b-venv/bin/python -m pytest -q import-spike/tests` → 21 passed；`python3 scripts/check_project.py` → PASS。获准读取的两份本地真实 Excel 仅输出行数与错误类别：库存 478 行、验货纸 50 行，均无行级错误；没有在仓库或日志打印客户值。真实文件验证了这两个已观察版式，不证明其它版本或业务口径。

## 10. T04c PDF 送货/装箱单商品行（本地验证，未过账）

- **[已验证，合成样本]** `import_spike/pdf_order.py` 的 `parse_pdf_order_text(text, owner=...)` 读 pypdf 提取出的文字，按序号重排后输出 `ImportLine`：编码（文本）、规格、商品单位、描述（跨行拼接）、旧编码、数量、数量栏单位、净重、指定效期（`1-Jul-27` → 纯 `date`，两位年份按 20YY）。页头只取 INV No.、日期、Cust#；地址、联系人不解析、不保存。货主由调用方传入。模块不依赖 pypdf，调用方负责提取文字。
- **配对规则 [候选，已用真实文件核对]**：pypdf 从页底往上吐字，数量栏是单独一串。按提取顺序把第 k 个数量行配给第 k 个商品行。两份真实 PDF 上，此规则让可换算的净重全部对上；「取紧挨在上方的数量行」的配法对不上。
- **拿不准就整单拦下，不猜**：数量行与商品行条数不同（`line_count_mismatch`）、商品行不是倒序（`order_unrecognized`）、序号不是 1..n（`seq_gap`）、各行合计 ≠ 单据合计或缺合计行（`totals_mismatch` / `totals_missing`）、像商品行但规格或单位不是已观察的写法（`item_line_unrecognized`，描述里出现 EA 也不会被当成单位）、缺单号或日期；整单被拦时每一行都同时标 `document_blocked`。行级拦截：描述跨了不止一行（`description_unclear`，页码行不会被拼进描述）、效期无法确认、`(Old` 写法无法解析、规格是 kg 时净重 ≠ 数量×规格（`net_weight_mismatch`）、商品单位和数量栏单位不同（`unit_needs_confirmation`）。
- **[待确认 Q04]** 真实文件里整箱商品（`CS`，如 `12 x 5.5 oz.`）的数量栏印的是 `EA`，是罐数还是箱数不能从单据判断，因此这类行不给基本单位数量，只能人工确认。**[待确认 Q02]** 只观察了一种版式。
- 本机运行：`/private/tmp/ingredient-t04b-venv/bin/python -m pytest -q import-spike/tests` → 44 passed。只读核对两份真实 PDF（经用户此前授权，仅输出计数与错误类别）：9 行和 4 行全部识别，无批次错误；件装的 9 行全部可过账预览，整箱的 3 行按上条规则拦下。
