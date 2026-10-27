# 命令与服务器接口

在仓库根目录执行 `python3 skills/aicheck-node-audit/scripts/node_audit.py [--base-url URL] <命令> …`。`--base-url` 放在命令前；缺省用 `AICHECK_BASE_URL`，再缺省用登录时保存的地址。

## 环境变量

| 变量 | 作用 |
|---|---|
| `AICHECK_BASE_URL` | 服务器 origin，可带或不带 `/api` |
| `AICHECK_ALLOW_HTTP=1` | 允许远程明文 HTTP（本机 127.0.0.1/localhost 不需要） |
| `AICHECK_TOKEN` | 直接给令牌（优先于会话文件），一般不用 |
| `AICHECK_AUDIT_HOME` | 资料包根目录，默认 `~/.aicheck-node-audit` |
| `AICHECK_SESSION_FILE` | 会话文件，默认 `~/.config/aicheck-node-audit/session.json`（0600） |
| `AICHECK_REPO` / `AICHECK_BUSINESS_PACK` | 业务包位置，默认本仓库 `backend/business_packs/engineering_inspection_v1` |
| `AICHECK_OCR_CONFIG_FILE` | OCR 与视觉模型配置，默认 `~/.config/aicheck-node-audit/ocr.json`（0600，`ocr-setup` 写） |
| `AICHECK_MINERU_API_KEY` / `AICHECK_MINERU_BASE_URL` | MinerU 密钥与地址（默认 `https://mineru.net`），优先于配置文件 |
| `AICHECK_VLM_API_KEY` / `AICHECK_VLM_BASE_URL` / `AICHECK_VLM_MODEL` | 视觉模型密钥、OpenAI 兼容地址（默认阿里云百炼按量 `https://dashscope.aliyuncs.com/compatible-mode/v1`）、模型（默认 `qwen3-vl-plus`），优先于配置文件 |

会话令牌只发给签发它的服务器；换地址要重新登录。读业务包需要 PyYAML（系统 python3 已有；没有就用 `backend/.venv/bin/python`）。

## 命令

| 命令 | 需登录 | 服务器接口 | 说明 |
|---|---|---|---|
| `login --username U [--tenant-id T]` | — | POST `/api/auth/login` | 只能在用户终端运行（getpass）；保存令牌与角色 |
| `logout` | 是 | POST `/api/auth/logout` | 删除会话文件 |
| `connection` | 否 | GET `/api/readyz`、`/api/inspection-services/capabilities`、`/api/auth/me` | 连通性、服务能力、当前账号角色；`ocr.mineru`、`ocr.vlm` 只说有没有配密钥，不输出密钥 |
| `ocr-setup [--vlm-model M] [--vlm-base-url U] [--mineru-base-url U]` | — | 无 | 只能在用户终端运行（getpass）：输入 MinerU 密钥和视觉模型密钥（回车保持不变），存 `ocr.json`（0600） |
| `rules --node N` | 否 | 无（本地业务包） | 规则原文、资料要求、原子检查（含服务器端绑定的工具名）、固定主条款 |
| `fetch --project P --node N [--out D] [--no-files]` | 是 | 见下 | 拉节点资料包 |
| `local-init --node N --project-dir DIR [--files F…] [--project L] [--out D] [--workspace W] [--review-run R]` | 否 | 无 | 本地测试资料包。`--project-dir` 递归收入整个项目（跳过 `~$` 锁文件、隐藏文件、`__MACOSX`），`bundle.json` 的 `projectPath` 记原目录位置；`W`/`R` 可模拟服务器工作区和审查运行（可带 `{"data": …}` 外壳） |
| `skeleton --bundle D [--force]` | 否 | 无 | 生成 `audit.json` 骨架：每个原子检查（含 instruction、逐件项带 coverage 空位）和包里每份文件（reviewedFiles）都已列好，只需填空；已有 `audit.json` 时要 `--force` 才覆盖 |
| `ocr --bundle D [--files F…] [--force] [--timeout S] [--allow-egress]` | 否 | MinerU 云 `POST /api/v4/file-urls/batch`、签名地址 PUT、`GET /api/v4/extract-results/batch/{id}` | 默认把包里全部没有文字层的原件（图片、扫描件、扫描页、转不出文字的 .doc）交 MinerU（vlm 模型，开表格与公式识别），逐页文字存 `ocr/`（含完整证号的原文，0600，只给脚本回查）和 `text/<名>.ocr.txt`（已脱敏，可直接读）。上传名只用文件哈希。表格按格展开、合并单元格值逐行重复；公式写法转成原件写法（`$14\mathrm{mm}$`→`14mm`、`$\geqslant 300$`→`≥300`）；图片块记成 `[图片]`（里面的字要用 `vlm` 问）。原件没变就 `cached` 不重做。返回 `done`、`cached`、`skipped`、`failed`；默认等 240 秒，没出完的在 `pending`，再跑同一条命令接着等，不重传。`--files standard:rules/standards/<名>.pdf` 可 OCR 仓库里的标准原件。本地资料包第一次要 `--allow-egress`（先问用户） |
| `vlm --bundle D --file F [--page N] --question Q [--clip x0,y0,x1,y1] [--rotate 90\|180\|270] [--dpi N] [--allow-egress]` | 否 | 视觉模型 `POST {base}/chat/completions`（OpenAI 兼容） | 把一页（或 `--clip` 的一块，坐标是占整页的比例）渲染成 PNG 发给视觉模型，问一个具体问题；温度 0，系统提示要求看不清就说看不清、编号逐字照抄。返回 `answer`（身份证号已脱敏）、`caution`；回答原文存 `ocr/vlm/`，结果存 `tool-results/`（`savedTo`），报告引用 `tool:vlm`。默认 dpi 200，给了 `--clip` 默认 300。本地资料包第一次要 `--allow-egress` |
| `text --file F [--bundle D \| --out O]` | 否 | 无（读 PDF 要 PyMuPDF） | 原件转文本存到资料包 `text/`，返回 `saved`；多页 PDF 每页前有 `--- 第 N 页 ---`，N 就是物理页。跑过 `ocr` 的扫描件和扫描页给 OCR 文字（`status: ocr` 或 `ocrPages`，页头标“（OCR）”）；还没 OCR 的扫描页列在 `pagesWithoutText`，整份扫描件报 `noTextLayer`，先跑 `ocr`。包外文件（如仓库里的标准原件）必须加 `--bundle` 或 `--out`（文件或目录），否则报 `outputMissing`，不会写进仓库。转出的文字里身份证号已脱敏 |
| `search --bundle D [--terms T…] [--only]`（`--terms` 是在默认词之外追加；加 `--only` 才只用你给的词） | 否 | 无（本地 PyMuPDF，用 `backend/.venv/bin/python` 跑） | 全包文字层和 OCR 文字检索（跑过 `ocr` 的扫描页一并检索，`filesWithHits` 的 `ocrPages` 标出来自 OCR 的页）：PDF 文字层、txt/csv、docx/xlsx 直接解析；.doc 先用内置 Word 97 解析（WPS 存的也能读），不行再走 textutil。默认词 = 本节点资料名称 + 工期/有效期/材质/人员等常见事实 + 按节点专业补的词（焊接、材料类节点带材质牌号、钢印、焊口等）。输出是摘要：`termHitFiles`（有命中的词各命中几份文件）、`zeroHitTerms`（有文字的文件里都没出现的词；包里还有没 OCR 的图片、扫描件或扫描页时带 `zeroHitNote`，提醒这些文件没被检索到，不能凭零命中说“没有”）、`filesWithHits`（每份文件的 `termPages` 按词列命中页，如 `焊口 p4-6、材质 p9`，每个词每份文件最多记 5 处，`--max-per-term` 可调；一条片段，`--sample N` 多看几条）、`idNumbersInText`（文字层和 OCR 文字里找得到的身份证号，已脱敏，及所在文件；这些可直接用脱敏号查 `cert-registry`）、无命中文件、`needsOcr`（还没 OCR 的图片、扫描件、读不了的 Office 文件）、`needsOcrPages`（文字 PDF 里夹的、还没 OCR 的扫描页）。逐条命中和片段存 `search/<时间>.json`，路径在 `saved`，要看就读它，不用自己重定向输出。默认词还会按原子检查的 requiredFacts 补（如设计变更、出图专用章、施焊日期）。片段里的身份证号已脱敏 |
| `pages --file F (--pages 1-3,7 \| --sheet) [--dpi N] [--clip x0,y0,x1,y1] [--rotate 90\|180\|270] [--bundle D \| --out O] [--text-only]` | 否 | 无（本地 PyMuPDF，用 `backend/.venv/bin/python` 跑） | **审计时不用**（不自己看图：扫描件走 `ocr`，印章、手写走 `vlm`）；留给人工复核时出页图。PDF 或图片（png/jpg/tif 等，按单页处理）渲染成 PNG 并返回文字层；单页渲染一次最多 20 页（多的分几次），图片和单页 PDF 可省略 `--pages`。给了 `--bundle` 时 `F` 可写资料包里的相对路径（如 `files/13-焊工证.pdf`）。`--rotate` 把页图顺时针转 90/180/270 度，横放的表格、图纸转正后再读；配 `--clip` 时坐标按转正后的样子给。`textLayer=false` 是扫描页，只能看图。小字（证书代号、日期、被印章压住的字）：先整页看位置，再 `--clip x0,y0,x1,y1` 配 `--dpi 300–400` 放大；坐标是占整页宽高的比例，左上角 0,0、右下角 1,1，例如右下四分之一是 `--clip 0.5,0.5,1,1`，正中一块是 `--clip 0.25,0.25,0.75,0.75`；框偏了按整页图上的位置再调。原件本身分辨率低时放大也不会更清，写进 `limitations`。`--sheet` 出缩略拼图（每格一页、标页码、每张 30 格，省略 `--pages` 即全部页），用来过目扫描件、找某张表在哪页；缩略图看不清表格内容，取证要回单页。图纸上的电子章、签名多是 PDF 表单域：单页结果的 `formFields`、拼图结果的 `formFieldPages` 给出每页表单域个数，格子标题也会标出，这只说明页面上有章，不说明章真伪。输出只进资料包：文件在资料包里时默认存它的 `pages/`；渲染仓库里的标准原件等包外文件必须加 `--bundle <资料包>` 或 `--out`，否则报 `outputMissing`，不会写进仓库 |
| `pages --all-visual --bundle D [--dpi N]` | 否 | 无（PyMuPDF） | **审计时不用**；给人工复核出缩略拼图：最近一次 `search` 标出的全部还没 OCR 的文件（部分扫描的 PDF 只拼扫描页）；返回每个文件的 `sheets`、`formFieldPages`，打不开的（如 .doc）在 `skipped` |
| `cert-registry --kind person\|organization_license --identifier X` | 否 | POST `/api/inspection-services/certificate-registry` | 公示平台登记查询。人员：号码在 `search` 的 `idNumbersInText` 里，就传脱敏号加 `--bundle`（要加单引号，如 `--identifier '1101**********1237'`；不加引号 zsh 会把星号当通配符，报 `no matches found`），脚本从原件文字层找回完整号码再查；不在里面的（OCR 没读出，传脱敏号会报 `identifierNotFound`），先用 `vlm` 问那一页的身份证号，再传脱敏号（脚本也从视觉模型回答的原文里找）。完整号码先验出生日期和校验位，对不上报 `idChecksumFailed`、不去平台查，多半是读错了一位 |
| `cert-validity --json '{…}'` | 否 | POST `/api/inspection-services/certificate-validity` | 有效期/主体/范围字段核对 |
| `cnse-org-search --keyword 单位名` | 是（本地资料也要） | POST `/api/cnse/organizations/search` | 只有单位名、没有 TS 编号时用。没登录报 `loginRequired`：有 TS 号就改用 `cert-registry`，没有就写进 `limitations` |
| `standards --query Q` | 否 | GET `/api/inspection-services/standards` | 公共标准检索。命中里超过 300 字的文字只留开头并注明总字数，原文用 `standard-content` 读 |
| `standard-content --file-id KF-KB-… [--page-no N] [--section S]` | 否 | GET `/api/inspection-services/standards/{fileId}/canonical` | 标准规范化原文 |
| `standard-status --ref 标准号 [--date YYYY-MM-DD]` | 否 | POST `/api/inspection-services/standard-status` | 标准的有效状态。`verdict` 按今天算；给了 `--date` 再看 `onDate`：`status` 是那一天的状态（`in_force` 有效、`not_yet_effective` 未实施、`withdrawn` 已废止、`unknown` 没有实施日期），附 `effectiveFrom`、`withdrawnOn` |
| `node-standards --project P --node N` | 是 | GET `…/inspection/nodes/{N}/standards` | 节点固定依据条款（fetch 已包含） |
| `report --bundle D` | 否 | 无 | 校验 `audit.json`，生成 `audit.md`。服务器节点会把服务器结论（`serverResult`、`agreesWithServer`）写回 `audit.json`，这时输出 `auditJsonUpdated: true`，之后再改 `audit.json` 要先重新读一遍；本地资料不改写它。输出 `outcome`（节点整体：通过／不通过／暂不能判定通过）、`outcomeExplain`、`syncAvailable` |
| `sync --bundle D [--confirm --preview-hash H]` | 是 | GET 节点 `evidence-chain`；确认后 POST `/api/review/findings` | 预览返回 `willCreate`、`skipped`、`previewHash` 及完整计划的 `savedTo`，只保存本地快照。用户确认该次具体内容后，用同一摘要确认；缺预览、摘要不符、报告或证据链改变均拒绝写入。仅匹配同版本、同页且摘录或字段和值对应的唯一已确认有效证据，不借用同文件其他链接。只挂逐条对上的证据：至少一条事实对上才写这一项，对不上的事实列在 `willCreate` 的 `unmatchedFacts`，也写进发现说明请人工按出处核；一条都对不上的整项列入 skipped，本地报告保留。相同实际请求同幂等键，内容改变须重新批准；结果另存 sync/。只写草稿 AI 发现、待人工复核，不改节点状态或人工意见，且只能同步到取数时的服务器 |

查询类命令（`cert-registry`、`cert-validity`、`cnse-org-search`、`standards`、`standard-content`、`standard-status`）都可加 `--bundle <资料包>`：结果连同参数和时间存进 `tool-results/`（0600），返回的 `savedTo` 就是报告里 `tool:` 引用的出处。审计时一律带上。

Office 原件直接读不了：用 `node_audit text --file <原件>` 转成文本（.doc 内置 Word 97 解析，WPS 存的也能读；.docx/.xlsx 直接解析），返回的 `saved` 再读全文。转不出来（`noTextLayer`）就跑 `ocr`（MinerU 收 .doc/.docx/.ppt），或请用户给 PDF。引用时 `source.file` 仍写 `files/` 下的原件，`text/…` 和行号写进 `locator`。

所有命令的输出、`search` 存档、`text` 转出的文字、`ocr` 的 `.ocr.txt`、`vlm` 的回答、`tool-results/` 存档里的身份证号都自动脱敏（前 4 位 + `**********` + 后 4 位）；完整号码只在原件和 `ocr/` 原文存档里，`cert-registry` 用脱敏号回那里找。不要读 `ocr/` 下的文件。

## fetch 拉什么

| 文件 | 来源 | 内容 |
|---|---|---|
| `workspace.json` | GET `/api/projects/{P}/inspection/nodes/{N}/audit-workspace`（服务器把内容放在 `content` 下，存进包时已摊平，下面的键都在顶层） | 资料要求、已提交挂载、文件与 OCR 就绪度、抽取字段（`ocr.extractedFields`）、证据就绪度与链接、审查运行列表、人工意见 |
| `server-rule.json` | GET `…/rules/current-version` | 服务器当前给该节点的规则（用来查错位） |
| `standards.json` | GET `…/standards` | 固定依据条款 |
| `evidence-chain.json` | GET `…/evidence-chain` | 证据链 |
| `review-run.json` | GET `/api/review-runs/{id}` | 最近一次审查运行；`atomicCheckOutcomes[].result` 是服务器逐项结论 |
| `files/NN-文件名` | GET `/api/projects/{P}/documents/{docId}/original?disposition=attachment&versionId=…` | 挂载版本的原件，`bundle.json` 记 sha256 |
| `rules.json` | 本地业务包 | 同 `rules` 命令 |
| `bundle.json`、`digest.md` | 生成 | 清单、服务器结果、提示；先读 digest |

工作区只给已提交的挂载，施工方草稿不在里面。可选部分取不到时写进 `warnings`，主流程继续。

## 结果怎么读

- **cert-registry**：
  - 单位许可证（`organization_license`，TS 编号）：`records.found`；`records.record` 里 `zsbh` 证书号、`dwmc` 单位、`czzt` 证照状态、`zsxkxm`/`xkxm` 许可项目、`zsxkfw` 许可范围（常为空，空不等于没有范围）、`zsfzrq` 发证日、`zsyxq` 有效期至、`fzjg` 发证机关、`tyshxydm` 信用代码。
  - 人员（`person`，18 位身份证号或脱敏号）：输出和存档里的 `sfzh`、`zsbh` 等号码都已脱敏。`records.person`（姓名等）、`records.licenses[]`（`zslb` 类别、`zsbh` 证书号、`czxm`/`cyzl` 项目、`yxrqs`–`yxrqz` 有效期、`fzjg`、`limitRange`）、`records.licenseCount`、`records.licenseLookup.status`。`khdw` 是**考核机构**（焊工在哪里考的证），不是焊工的工作单位，与施工单位不同是常态，不要据此记风险；`pzrq` 是批准日期。`licenseLookup` 不是成功时只拿到了人员条目，没有证书全表，不能据此说“无证”。`validFlag` 对已到期记录仍可能是 1，现行与否按 `yxrqz` 与施焊/作业日期自己算。
  - `authenticityConclusion` 恒为 `manual_confirmation_required`。查不到、`REGISTRY_UNAVAILABLE`、403 都不是假证或无效证的证据。平台会限流：成功查到的号码不再重复查；失败（503、超时）的结果也会存档；503 脚本已自动重试一次，仍失败可隔几分钟再试。
- **cert-validity** 请求体：
  ```json
  {"certificates":[{"certificateNo":"…","holder":"…","validFrom":"2024-03-31","validUntil":"2027-03-31","scopes":["原文明确的许可项目"]}],
   "expectedHolder":"…","requiredScopes":["…"],"periodStart":"2026-03-01","periodEnd":"2026-09-20"}
  ```
  要确认一张证覆盖某个日期或期间，必须同时传该证的 `validFrom` 和 `validUntil`。缺任一端且没有明确不覆盖的日期事实时，日期维度为 `evidence_insufficient`；已知日期明确不覆盖时仍为 `failed`。原件缺字段就不要猜值补齐，在报告中写明缺失字段。
  必须给 `referenceDate` 或 `periodStart`+`periodEnd`；不知道施工期就不要拿今天冒充。范围只做完整字符串比较，GC1/GC2 包含关系、焊工代号覆盖它不算——`scopeMatch=failed` 不等于不覆盖。看 `checkedDimensions`/`uncheckedDimensions`。
  - 只收上面这些字段：顶层 `certificates`、`expectedHolder`、`requiredScopes`、`periodStart`、`periodEnd`、`referenceDate`，每张证 `certificateNo`、`holder`、`validFrom`、`validUntil`、`scopes`。多写字段（如 `reasoning`）会报 `invalidArguments` 并点名是哪个。
  - `certificateNo` 只是标签，服务器不拿它比对任何东西。焊工证的编号就是身份证号：填脱敏号。
  - `expectedHolder` 只在姓名来自另一份资料（施焊记录、焊工名册、合同人员表）时填；只有证书本身时不填，自己比自己的 `holderMatch=passed` 没有意义。
  - `requiredScopes` 只在证上项目与要求能逐字对上时填；焊工代号、GC 级别的覆盖按标准原文另算，不填。
  - 证上有效期只写到月：`validFrom` 取当月 1 日，`validUntil` 取当月最后一天，`reasoning` 写明。
- **standards**：查询词只放标准号和技术词，不放工程名称。用返回的 `standardContentArguments` 原样调 `standard-content`；`standardContentAvailable=false` 表示没有规范化原文。空结果不证明库里没有，更不证明标准废止。
- **standard-content** 的 `--section` 常定位不到附录条款（2026-10 实测 TSG Z6002-2010 附件 A 各节都是 `section_not_located`）。这时改读仓库：`rules/results/<标准文件名>.pdf.md` 是整份 OCR（无页码），`rules/standards/` 是原件（多为扫描件）：`ocr --bundle <资料包> --files standard:rules/standards/<文件名>.pdf` 取逐页文字，再 `text --file rules/standards/<文件名>.pdf --bundle <资料包>` 读，引用写物理页。2021 年第 41 号公告也不在服务器标准库里，同样走仓库。
- **standard-status**：`not_found`、`unsupported_family`（TSG 目前不支持）、`ambiguous` 都不是“无效”。

## 错误码

`loginRequired`（401，让用户重新 login）、`forbidden`（角色或节点范围不够）、`notFound`、`rateLimited`（看 `retryAfter`）、`unreachable`、`insecureTransport`（远程 HTTP 未放行）、`ttyRequired`（login 不在用户终端）、`pyyamlMissing`、`reportInvalid`（看 `errors`）、`identifierNotFound`（脱敏号在原件文字层里找不到）、`idChecksumFailed`（身份证号读错了一位）、`ocrNotConfigured` / `vlmNotConfigured`（没配密钥：请用户在自己终端跑 `ocr-setup`）、`egressNotApproved`（本地资料包没得到外发同意：问用户，同意后加 `--allow-egress`）、`mineruKeyInvalid` / `vlmKeyInvalid`（密钥被拒，重跑 `ocr-setup`）、`vlmNoPlan`（密钥有效但套餐或模型没买、过期，请用户续订）、`vlmModelNotFound`（模型名不对，`ocr-setup --vlm-model`）、`mineruRejected` / `mineruUploadFailed` / `mineruDownloadFailed` / `mineruBadResult`（MinerU 侧失败，隔几分钟重跑 `ocr`，仍失败把文件写进 `limitations`）。生产版本较旧时 `standards` 等接口可能 404：记为能力不可用，不影响其他检查。

服务器一时不可用（部署、重启）会返回 `http502`/`http504`，公示平台暂不可查询会返回 `http503`：脚本已自动隔 5 秒重试一次。仍失败、或返回 `unreachable`、超时：先做不需要服务器的步骤（检索、OCR、读原件），隔 1–2 分钟再试一次；`connection` 开头报 502 也一样，不必停下。重试后仍失败按 audit-method 的“平台不可用”处理。
