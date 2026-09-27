# 审查能力服务调用

工程资料只来自用户本地或当前会话。MCP 不读取服务器工程资料库，不创建工程、文档、版本、上传会话或审查任务。审查由当前 AI 平台按本 skill 完成，报告留在会话或用户指定的本地文件。

Python CLI 与 MCP 共用客户端，要求 Python 3.10+ 标准库。命令为 `python3 <skill目录>/scripts/aicheck_client.py <动作> --json '<JSON对象>'`；MCP 工具名为 `aicheck_<动作>`。工具返回 `ok` 与 `data` 或 `error`，必须检查成功标识；服务失败不是业务不符合。

## 工具范围

| 工具 | 输入／作用 | 数据边界 |
| --- | --- | --- |
| connection | 检查身份及服务能力 | 不读取工程或资料 |
| rules | nodeId 可选；默认本地 v3，source=server 读取服务规则 | 只读规则，不需要工程 ID |
| standards | query、page、pageSize | 查询系统标准知识库；关键词仅含标准和技术条件，避免工程名称等无关信息 |
| standard_content | fileId、pageNo／section 可选 | 读取标准规范化原文与来源 |
| standard_status | standardRef、reviewDate 可选 | 查询标准登记平台的版本和有效性信息 |
| certificate_validity | 证件事实、预期持有人／范围、作业日期或期间 | 无持久记录的确定性核验，不代表证件真实 |
| certificate_registry | kind、identifier（默认执行登记查询） | 查询政府登记平台；本系统不写证件缓存 |

以上工具没有 projectId、工程文件版本 ID、远程结果归档等参数。调用细节以实际 tools/list schema 为准。

## 本地资料预处理

OCR 和资料整理均由宿主 AI 平台完成，本客户端与审查服务没有 OCR 或工程文件上传接口。不应回退调用系统原有的文件上传、MinerU 或工程任务接口。

先固定用户选择的文件和涉及节点。能够读取文本层时直接读取；扫描件由平台完成 OCR，并保留原文件名、可取得的 SHA-256、原页码、原文摘录或位置、结构化字段及不确定标记。表格必须保留行列和单位，证件编号、日期、焊工资格代号等关键内容需对照原页核实；不能补造哈希、置信度或模糊字符。

当前平台不能识别或结果不完整时，明确未读取的页面与字段，请用户提供可检索 PDF、保留页码的文本，或先在平台完成识别。继续处理不受影响的核查项，不将识别失败判成工程缺资料或不符合。

报告、全文、图像和原文件留在当前平台会话或用户指定本地位置。只有核验必需的结构化字段可发给相应服务，例如证件日期与需要匹配的持有人；不得把整份 OCR 或报告塞入字段。当前 AI 平台自身对会话资料的处理规则由其平台决定。

## 规则与标准

离线规则：`rules {"nodeId":24}`。服务规则：`rules {"source":"server","nodeId":24}`，不指定工程。

规则文档只表达业务审查方法。标准查询示例：

```json
{"query":"焊工资格 厚度覆盖","page":1,"pageSize":20}
```

`standards` 查询现有标准知识库。检索结果中的 total 受 top_k 检索窗口影响，不是标准库全量条数，也不证明检索穷尽。只在 `standardContentAvailable=true` 时，将命中的 `standardContentArguments` 原样传给 `standard_content`（其中 `fileId` 是真实文件 ID）。`kbDocId` 是来源标识，`sourceRelativePath` 是路径，都不能代替 `fileId`。`standardContentAvailable=false` 表示尚无规范化原文，不能以登录或摘要替代原文核实。

`evidenceKind=business_rule`、`ruleFamily=legacy-business-rules` 是另一套业务规则，不能当作标准原文或混入 v3 节点规则；这类条目的 `ruleSequence` 不是 PDF 页码，不能据此引用原文页。`evidenceKind=reference_note` 为更新说明／临时参考记录，同样不是正式标准原文。摘要不可作为数值和档位的唯一依据。

```json
{"fileId":"实际标准文件ID","pageNo":12}
```

标准版本核验：

```json
{"standardRef":"用户资料引用的标准号与版本","reviewDate":"2026-09-22"}
```

`verdict` 按返回的 `reviewDate` 判定；`matched.status`、`standardReferences[].status` 是查询时登记平台状态，两者可能不同。历史日期缺少必要生效／废止证据时返回 `ambiguous`。`unsupported_family`（目前 TSG）表示适配器未覆盖，须另核对主管部门公告；`not_found` 表示本次未检出，两者都不代表标准无效。

reviewDate 应取真实适用时间，不用审查当天替代施工、签发或合同约定日期。登记平台与工程适用条款都需核实；服务查无结果、无规范化原文或请求失败均须保留不确定性。

## 证件有效性与登记核验

`certificate_validity` 按本地材料提取的明确事实比对：

```json
{
  "certificates":[{
    "certificateNo":"示例证件号",
    "holder":"示例持有人",
    "validFrom":"2024-03-31",
    "validUntil":"2027-03-31",
    "scopes":["原文明确的许可项目"]
  }],
  "expectedHolder":"示例持有人",
  "requiredScopes":["需要覆盖的许可项目"],
  "periodStart":"2026-09-01",
  "periodEnd":"2026-09-20"
}
```

必须提供明确的 referenceDate，或同时提供 periodStart 与 periodEnd。缺施工日期时不能默认采用今天；缺持有人或范围也不应补成默认值。返回的日期／文本范围比较不能替代焊工资格标准中的厚度、直径、位置等技术覆盖计算，更不能证明证件真实性。事实来自哪份本地文件、可取得的哈希和页码由调用平台在报告中保留。

证件缺 validFrom 或 validUntil 时，有效日期维度为证据不足；已知日期明确不覆盖时仍报告该失败事实。阅读 checkedDimensions、uncheckedDimensions 和逐证 dimensionResults：未提供预期持有人或范围意味着这些维度未请求核验，不能把日期通过扩展为全面通过。范围仅作完整项目字符串比较，保留中文和罗马数字差异，不计算技术互认。

证件审查默认执行登记平台核验，不另设确认步骤，只发送必要字段：

```json
{"kind":"organization_license","identifier":"实际许可证号"}
```

人员查询 kind 为 person，identifier 为平台所需的身份标识。无需提供 allowExternalQuery；缺省即执行查询，兼容旧调用的 true，显式 false 仍阻止发送。不要把此兼容开关解释成需要向用户索取授权。本系统不缓存身份字段、查询结果或证件影像；政府平台有自身处理机制，不承诺第三方零留存。查不到、验证码失败或暂不可用不能推导伪证、证件无效或不符合。

## 接口映射与发布条件

| 动作 | HTTP 接口 |
| --- | --- |
| login | POST `/api/auth/login`；仅保留兼容；当前审查无需登录 |
| connection / rules(server) | GET `/api/inspection-services/capabilities` / `/api/inspection-services/rules` |
| certificate_validity / certificate_registry | POST `/api/inspection-services/certificate-validity` / `…/certificate-registry` |
| standards / standard_content | GET `/api/inspection-services/standards` / `/api/inspection-services/standards/{fileId}/canonical` |
| standard_status | POST `/api/inspection-services/standard-status` |

只需按平台说明配置后台地址；审查服务无需令牌，不在 skill 中保存生产环境配置、模型密钥或 SSH 私钥。接口未部署时明确返回能力不可用，不能回落到工程资料服务。服务端新路径必须绕开请求／响应持久幂等缓存、工程操作记录与证件查询缓存；日志只保留必要的操作类型、状态和耗时等元数据。

`/inspection-services` 免登录开放审查能力；标准检索及原文仅提供无工程关联的公共标准，其他工程与知识管理接口仍须登录。远程部署需同步此版本后再验收。此 skill 不依赖服务器 OCR 引擎，也不依赖工程审查任务接口。系统既有页面可继续使用各自接口，不因此成为可移植 MCP 的工程资料来源。

## 版本与能力验收

本地与服务器规则用 `ruleVersion` 比较规则文档哈希。旧 `version` 字段的口径不同：本地仅规则文档，服务器包含 Skill 指令，不能直接比较；URL 脱敏不改变这些预先计算的哈希。

连接成功只表示接口可达。检查 `connection.standardContent.available`、`publicFileCount` 和 `canonicalRecordCount`，再实际完成一次检索→按 `standardContentArguments` 读取原文→检查正文与来源。规范化记录为零时应报告原文能力未就绪，不能把标准目录或规则摘要称为真实原文库。

证件 `scopeMatch=failed` 只表示归一后的完整字符串未匹配，不证明技术范围不覆盖；等级包含、项目互认须另按依据核查。证件字段核验不等于正式工程结论。

## 查询、定位与结果解释

- `standards`：查询中含标准编号时按文件身份限定编号和指定年份，不用另一份相近标准替代；纯文本查询须同时命中所有有效词组，单字及“标准/规范/查询”等通用词不能单独触发命中；此保守检索可能漏掉同义词，空结果不证明库中不存在。identityCheck.status 为 verified 表示文件名与独立编号/版本证据一致（不表示标准有效或条款适用），unverified 表示信息不足，conflict 表示身份冲突。编号检索排除 conflict；unverified/conflict 的 formalEvidenceEligible=false，须回看封面核对。文件名括号中的替代标准不是本文件身份。仍应核对 fileName、standardCode 和原文 identity；词面匹配不保证所引条款适用。
- `standard_status`：`ok=true` 只表示调用成功。`not_found` 是本次未检出，`unsupported_family` 是适配器不支持，`ambiguous` 是无法确定；均不得解释为标准无效。必要时另核主管部门公告。
- `standard_content`：fileId 须使用检索返回的 `KF-KB-*`。来源库 ID、文件名与路径返回 invalidArguments；standardFileUnavailable 表示文件不存在或未向公共接口开放（刻意不暴露受保护资料是否存在）；standardContentNotReady 表示公开文件存在但规范化正文尚未就绪。旧服务可能仍返回 standardEvidenceUnavailable，不能据此要求用户补登录令牌。
- `pageNo` 使用 PDF 物理页（1 起），超界返回 pageOutOfRange。`selection` 给出各类内容数量、pageCount、contentFound；有效空页标 empty_page，未定位条款标 section_not_located，不能等同为标准不存在该要求。
- `section` 同时读取 blocks、clauses、tables、equations 等类别；不要只读 blocks。新语料按 MinerU 原始序列与数字/附录条款标题建立 sectionPath，排除可识别的倍数、单位和目录条目，在附录/前言/参考文献边界切换或清空归属；`hierarchyBasis` 明示该归属仍需复核，不按字母清单或条款字母序猜测归属。
- 有 `sourceOrder` 时按原始序列阅读；`readingOrderBasis=unavailable` 时不把数组顺序当作原页顺序。`bbox=null`／layoutFallback=true 不能支持精确坐标定位，不能据此重建版面归属；缺布局不会通过排序伪造坐标。
- `certificate_validity.result` 为字段核查结果：passed 表示请求维度通过；failed 必须逐项解释（日期不覆盖或精确字符串未匹配）；evidence_insufficient 表示证据不足。GC1/GC2 等等级包含与技术互认没有被工具验证，scopeMatch=failed 不能写为工程不符合。businessConclusionProduced=false 表明工具未生成正式业务结论。
- 参数拒绝层不同：CLI 调用返回 invalidArguments，MCP schema 前置拒绝返回 JSON-RPC -32602；两者均未发起后台查询。缺参数、额外字段、日期格式错误与显式禁用外部查询是预期校验行为。

## 分册、合订本与本地全文补查

精确编号检索无结果不等于项目没有全文。先记录原查询，再用系列编号（例如 NB/T 47018-2017）及名称检索；在用户已授权的项目中，可查标准目录及其 OCR 产物。不得把扩大检索范围理解为允许读取未授权工程资料。MCP 没有原文时，允许直接读取已授权本地标准 PDF，不上传工程资料。

合订本须核对目标分册的封面、年份、目录、正文边界和具体表格原页；检索命中的父编号不自动证明分册身份。保留容器文件名、分册编号、PDF 物理页和印刷页区别。OCR、目录中的引用、参考文献或另一份标准不能代替目标标准全文。报告分别写“精确检索未命中”“仅找到引用”“本地全文已核实”或“在本次检索范围内未找到全文”。

本项目已核实的例子：`rules/standards/NBT 47018-2017 承压设备用焊接材料订货技术条件.pdf` 是合订本，含 NB/T 47018.3-2017；其 PDF 物理第30–36页含该分册正文及附录，相关 OCR 位于 `rules/results/` 的同名 `.pdf.md`。这些是项目相对路径，并未随 Skill 打包；其他平台应查询服务或用户提供的目录，不假定文件存在。

GB/T 39280 与 GB/T 8110 不能因同为焊丝标准而互相替代；未取得 GB/T 39280 全文时，保留这一依据缺口。取得 NB/T 47018.3 后可单独核查其有原文支持的指标，不把部分指标通过写成全部化学成分或产品全面符合。
