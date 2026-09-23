# 可移植监检 Skill v2：审查能力与本地资料边界

## 交付范围

源码位于 `skills/aicheck-inspection/`；分发包为 `output/skills/aicheck-inspection.zip`，唯一顶层目录为 `aicheck-inspection/`。打包仅允许八个明确列出的文件，不包含环境变量文件、密钥、令牌、测试或运行日志。完整保留 `docs/业务节点描述v3.md` 的 12 个节点原文，打包逐字节核对。

本版按用户最新要求取代前版工程任务接入方式：工程资料仅由用户在本地或当前会话提供。宿主 AI 平台负责读取、OCR、字段整理、执行节点审查及生成本地／会话报告。AIcheck MCP 不提供 OCR，不上传原文件、图像、全文、证据索引或报告，不创建工程、文件版本、后台审查任务。

平台无法识别资料时，skill 要求说明具体不可读页面或字段，请用户提供可检索 PDF、保留页码的文本，或先在平台完成识别；其余独立核查继续。提取须保留原文件名、可取得的 SHA-256、原页码、原文或定位、结构化取值及不确定标记，不补造字符、日期、哈希或识别置信度。

## 工具与后端

| MCP 工具 | 服务路径／责任 |
| --- | --- |
| connection | GET `/api/inspection-services/capabilities`，查询授权服务能力 |
| rules | 默认读取随包 v3；服务模式 GET `/api/inspection-services/rules?nodeId=24` |
| standards | GET `/api/knowledge/clauses`，检索标准依据 |
| standard_content | GET `/api/knowledge/files/{fileId}/canonical`，读取规范化标准原文 |
| standard_status | POST `/api/std-samr/standards/verify`，查询标准登记状态 |
| certificate_validity | POST `/api/inspection-services/certificate-validity`，核对最少结构化证件事实 |
| certificate_registry | POST `/api/inspection-services/certificate-registry`，经授权查询官方登记 |

共有七个工具；另有交互式 CLI login 配置个人身份。脚本仅依赖 Python 3.10+ 标准库。旧 OCR、工程查询、资料库、上传、下载、分析、任务启动及任务结果动作在本地拒绝，不触发网络回退。

## 服务数据与判定边界

新增审查路由保留现有登录、租户与监检权限检查，仅接受有限大小 JSON 和明确字段。不依赖工程成员身份，不接收原文件或工程存储标识。请求在鉴权后绕过工程操作记录、幂等响应缓存和数据库刷新，即使提供 Idempotency-Key 也不持久保存字段或结果。只记录操作类型、HTTP 状态和耗时；响应为 `Cache-Control: no-store`。

证件有效性必须使用明确的基准日或完整施工期间，不能默认用今天代替施焊日期。核验区分有效日期、持有人、范围和真实性；缺字段不能补成已确认事实。范围只进行保留中文及罗马数字语义的明确项目文本比较，不代替焊工资格的技术互认、厚度、直径或位置覆盖计算。

登记服务要求 `allowExternalQuery: true`，直接使用登记查询客户端，不写现有证件缓存；只发送必要标识。屏蔽本次外部 HTTP 传输日志中可能出现的身份证号，其他请求日志不受影响。登记结果需匹配人员／单位后使用；查无结果或服务异常不能判假证。第三方登记平台自身留存不在系统控制范围内。

工程原文留在宿主平台的会话或用户指定本地位置；这不等于宿主模型一定在设备上运行，也不承诺其他平台零留存。标准库仍属于服务器公共审查依据，可按既有服务查询。

## 验证

最终测试记录见 `output/skills/portable-tests.log` 和 `output/skills/backend-contract-tests.log`，均使用合成数据，不读取生产工程资料。

本版最终结果：客户端／MCP／分发共 29 项通过，真实 API 集成、无持久存储审查服务和相关回归共 80 项通过。后端仅有既有依赖的弃用警告。

- 客户端：真实本机回环 HTTP 协议测试覆盖七个工具、鉴权与业务失败、能力缺失、字段校验、无自动重试、公开标准来源和敏感信息处理；旧 OCR 动作不读文件、不发请求。
- MCP：真实子进程 stdio JSON-RPC、工具精确清单、输入检查、业务错误、资源白名单、异常脱敏。
- 分发：解压至含空格的独立目录，清空后台配置仍可读取全部 12 节点；检查依赖和相对链接；随包规则与原文一致。
- FastAPI：保留完整可移植客户端，仅替换 HTTP 传输为进程内真实 API；种子监检账号登录后，在无工程成员关系时调用规则和证件服务，核对仓库状态前后不变。
- 服务端：字段／日期反例、中文和罗马数字范围区别、证件资料不写库、不缓存／重放、不进入日志、外部登记授权与故障处理；相关认证、幂等、部署与模块规模回归。
- skill-creator 校验与新增 Python 文件 Ruff 检查；运行源码相关权限和幂等路由覆盖检查。
- 独立行为试用：`output/skills/preprocess-forward-test-report.md` 验证模糊 OCR、缺施工日期和附件诱导上传不能触发工程资料外发或假通过；此前完整 R24 方法覆盖场景保留在 `output/skills/forward-test-report.md`。

复现：

```sh
python3 -m unittest discover -s skills/aicheck-inspection/tests -v
cd backend
.venv/bin/python -m pytest tests/test_portable_inspection_skill.py tests/test_inspection_services.py tests/test_auth_tokens.py tests/test_idempotency_membership_scope.py tests/test_deployment_report.py tests/test_monolith_ratchet.py -q
cd ..
python3 scripts/package_inspection_skill.py
```

本机系统 Python 的 Command Line Tools 配置异常，实际验证使用 `/opt/homebrew/bin/python3` 或 `backend/.venv/bin/python`。未更改全局 Python 配置。

## 部署与平台实测边界

本次仅完成本地代码和分发包，未部署服务器。新 `/inspection-services` 接口部署后才能通过 MCP 使用；未部署时客户端明确报告能力不可用，仍可用本地 v3 在宿主平台审查。不需要服务器 OCR 引擎，也不以现有“重要节点审查”工程任务接口为前提。

已在本机 Codex 用户级安装并完成技能发现、MCP 握手及本地规则读取验证，详见下节。Claude Code／Cursor 等平台可按包内说明配置本地 stdio MCP，但尚未在这些平台实际安装验收。Claude 网页上传 skill 可以按规则审查会话资料；网页端访问后台需要额外部署可达的远程 MCP 和认证，本包未提供该部署，不能宣称全部 AI 平台后台接入开箱即用。

此 skill 提供节点审查方法和辅助服务，不是全部法规已验证的自动判定程序，也不签发正式监检结论。现有业务页面保留各自工程资料和任务接入，未因可移植 MCP 的边界调整而移除。

## Codex 安装与 Scan 实际试用

用户明确授权使用项目 `Scan` 资料后，当前 Codex 会话读取了 30 份主资料、104 个 PDF 页面／图纸图片，对 12 个节点的 85 条顶层方法建立核查记录，并整理 79 条焊口记录。全部方法有状态记录不等于全部业务检查通过；缺证据、缺适用依据和未执行的官方查询均明确保留。

- 安装包八个文件与安装记录 SHA-256 一致；Codex 实际发现用户级 skill 及七个 MCP 工具。
- 安装后的 stdio MCP 实际读取全部十二节点规则；远程连接返回 `notConfigured`，未把标准／证件后台联调计为成功。
- 独立 CLI 0.144.6 无法启动当前模型，试跑失败；实际原页审查由当前 Codex 会话完成。
- 发现设计与施工壁厚、阀门型号、设计许可主体及 WPS/PQR 对应问题；保留已有试验记录及公司更名证据，避免重复索要资料。
- 发现随包 v3 与历史适用规则的差异，尤其 R24 工艺因素解释，以及部分标准版号的历史适用性。发布前需校正规则并增加回归样例；本轮没有擅改业务文档。
- 工程资料没有发送至 AIcheck 后台；文件清单、结构化证据与审查报告保存在本项目，渲染图片和运行日志仅留本机。

可复核资料：

- [Scan 审查报告](../../../output/skills/codex-scan-test/Scan资料审查报告.md)
- [测试结果](../../../output/skills/codex-scan-test/test-results.json)
- [Codex 安装记录](../../../output/skills/codex-install-test/安装测试记录.md)
- [本地 MCP 调用摘要](../../../output/skills/codex-scan-test/mcp-review-summary.json)
