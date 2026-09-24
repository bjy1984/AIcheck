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
| certificate_registry | kind、identifier、allowExternalQuery=true | 查询政府登记平台；本系统不写证件缓存 |

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

`standards` 查询现有标准知识库。检索结果中的 total 受 top_k 检索窗口影响，不是标准库全量条数，也不证明检索穷尽。取得 knowledgeFileId 等真实文件标识后，通过 `standard_content` 核对原文；摘要不可作为数值和档位的唯一依据。

```json
{"fileId":"实际标准文件ID","pageNo":12}
```

标准版本核验：

```json
{"standardRef":"用户资料引用的标准号与版本","reviewDate":"2026-09-22"}
```

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

如用户已要求登记平台核验，只发送其授权的必要字段：

```json
{"kind":"organization_license","identifier":"实际许可证号","allowExternalQuery":true}
```

人员查询 kind 为 person，identifier 为平台所需的身份标识。allowExternalQuery 必须为 true，表示明确允许该次外部查询；不需要重复询问已授权的同一范围。本系统不缓存身份字段、查询结果或证件影像；政府平台有自身处理机制，不承诺第三方零留存。查不到、验证码失败或暂不可用不能推导伪证、证件无效或不符合。

## 接口映射与发布条件

| 动作 | HTTP 接口 |
| --- | --- |
| login | POST `/api/auth/login`；仅交互配置客户端身份 |
| connection / rules(server) | GET `/api/inspection-services/capabilities` / `/api/inspection-services/rules` |
| certificate_validity / certificate_registry | POST `/api/inspection-services/certificate-validity` / `…/certificate-registry` |
| standards / standard_content | GET `/api/knowledge/clauses` / `/api/knowledge/files/{fileId}/canonical` |
| standard_status | POST `/api/std-samr/standards/verify` |

后台地址和个人令牌按平台说明配置，不在 skill 中保存生产环境配置、模型密钥或 SSH 私钥。接口未部署时明确返回能力不可用，不能回落到工程资料服务。服务端新路径必须绕开请求／响应持久幂等缓存、工程操作记录与证件查询缓存；日志只保留必要的操作类型、状态和耗时等元数据。

新 `/inspection-services` 路径尚需部署验收。此 skill 不依赖服务器 OCR 引擎，也不依赖工程审查任务接口。系统既有页面可继续使用各自接口，不因此成为可移植 MCP 的工程资料来源。
