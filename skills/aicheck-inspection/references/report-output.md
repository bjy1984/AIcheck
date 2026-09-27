# 本地报告生成约定

默认交付 `report.html`、`report.md`、`report.json`。HTML 是主阅读版，Markdown 便于平台阅读，JSON 是唯一结果来源；不把完整工程资料传给生成服务。生成脚本仅使用 Python 标准库，无网络调用、无第三方依赖。

## 工作顺序

1. 运行 `python3 scripts/report.py init review.json --nodes R04 R09 R24`，使用用户实际选择的节点。该命令按随包 v3 生成全部方法的未执行清单；不是完成审查。不要漏掉“输出”方法。
2. 阅读 `report.schema.json` 和 `report.example.json`，逐项填入真实记录。示例是虚构数据，不能当作工程事实。项目名和 scopeNote 写明本次范围；不要在 scopeNote 另写一套总数或通过结论。
3. 运行 `python3 scripts/report.py validate review.json`。非零退出表示有结构或一致性错误；按真实证据修正，不为通过校验虚构日期、定位、服务成功或判定条件。
4. 运行 `python3 scripts/report.py render review.json --output report-output`。失败不会输出新的报告；成功生成三种文件，正文与汇总来自同一 JSON。复核 HTML 窄屏、折叠、筛选、证据跳转和打印。
5. 向用户提供主报告链接及主要待处理事项。不得将“程序校验通过”写成专业结论、原件真实性已核实或工程符合。

平台无法运行 Python 时，仍按摘要→节点总览→问题详情→处理清单→附录的结构输出 Markdown，醒目标注“未经过程序校验”，保留 JSON；不能声称生成了未实际生成的 HTML/PDF。

## 数据填写

- ID 在报告内唯一。资料只登记实际文件，同内容副本合并引用，不把目录条目再登记成附件，不填空占位文件。资料编号用 D，证据用 E，核查用 C，问题用 I，服务用 S 前缀。文件数和节点数由脚本计算。
- 所选节点的每条方法至少有一条 check；不同焊工、管线、炉批可有多条。`kind` 使用 comparison（事实比较）、period（有效期覆盖）、official（官方登记）、scope（范围覆盖）。只要判断时间覆盖就必须用 period；日期不完整保留 null，不把年份猜成某月某日。年份已知可写 actual，不得伪造精确日期。
- `execution` 与 `result` 分开。只有 completed、basisVerified=true、conditionsMet=true 且证据可定位、依赖服务成功时，才允许 passed/failed/not_applicable。basisVerified 表示适用标准原文和版本已核实，不是“随包 v3 写了这句话”。条件未满足写明 conditionNote，结果采用 insufficient/manual/warning/pending。
- 有效期覆盖 period 记录 validFrom、validUntil、eventStart、eventEnd 和日期证据。发证日期不一定等于有效起始日期；制造日期不能从质证书编号猜出；换证连续性需有依据。官方核验通过应关联 status=success 的服务记录；成功查询不自动证明范围或日期覆盖。
- evidence 的 page 是原件物理页；非分页文档可为 null，但 locator 须给章节、表格、行和能回读的定位。提取文本行号必须同时指向所交付的提取文件和原件映射；否则 locationVerified=false。哈希取不到写 null 与 hashReason。
- 每个未通过/未完成核查均关联一个 issue。跨节点共性问题用一个 issue 关联多个 checkIds，避免重复统计。区分 recognize（文件已有，待识别）、supply（确实缺资料）、retry（查询失败待重试）、basis（能力/标准/规则待核实）、rectify（已有明确整改事项）。issue 写可执行 action 与可验收 completion。
- 服务记录填写来源、实际调用时间与结果摘要，不填完整身份证号、请求载荷、账号或令牌。未调用写 not_run，不将预期调用记为成功。

## 当前已知能力与规则边界

- R13 方法4所需的制造单位＋产品类别型式试验查询，当前 MCP certificate_registry 未提供；其 kind 只有 person 和 organization_license。应记录 unsupported/能力未覆盖，不能以单位许可证查询冒充型式试验核验，也不能要求重复授权来解决缺能力。
- R24 工艺因素已更正为 10 有背面保护气、11 无背面保护气。须分别核查 11→10 与 10→11 的方向及适用材料例外；不能把代号不同直接写成不覆盖，不能把 WPS 未记载写成实际无保护气。旧报告若使用反向解释，须重新核查受影响的方法3/5及处理事项，记录修订说明后更新规则哈希，不能只替换哈希使旧结论通过校验。
- 校验不能识别所有自然语言矛盾，也不能证明原件、OCR、标准适用性或工具返回真实。不得通过错标 kind、basisVerified 或 conditionsMet 绕过检查。正式出具前仍需监检人员复核。
