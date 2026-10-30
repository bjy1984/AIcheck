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

会话令牌只发给签发它的服务器；换地址要重新登录。读业务包需要 PyYAML（系统 python3 已有；没有就用 `backend/.venv/bin/python`）。

## 命令

| 命令 | 需登录 | 服务器接口 | 说明 |
|---|---|---|---|
| `login --web [--no-browser] [--timeout S]` | — | 浏览器打开 `/#/skill-authorize/…`；POST `/api/auth/skill/token` | 网页授权，助手可以自己运行：在本机 `127.0.0.1` 随机端口等回调，打开平台授权页（链接同时打到 stderr）；用户在浏览器里登录监检或管理员账号并点「授权」后，平台把一次性授权码（120 秒、只能用一次）回调到本机，skill 凭只有它知道的 PKCE 校验码（S256）换令牌，口令不经过 skill 和助手。保存令牌与角色（会话文件 `method: web`）。`webLoginDenied`：用户点了拒绝；`webLoginTimeout`：超时（默认 300 秒），返回里带 `authorizeUrl` |
| `login --username U [--tenant-id T]` | — | POST `/api/auth/login` | 口令登录，只能在用户终端运行（getpass）；网页授权用不了时的后备。保存令牌与角色 |
| `logout` | 是 | POST `/api/auth/logout` | 删除会话文件 |
| `connection` | 否 | GET `/api/readyz`、`/api/inspection-services/capabilities`、`/api/auth/me` | 连通性、服务能力、当前账号角色 |
| `rules --node N` | 否 | 无（本地业务包） | 规则原文、资料要求、原子检查（含服务器端绑定的工具名）、固定主条款 |
| `fetch --project P --node N [--out D] [--no-files]` | 是 | 见下 | 拉节点资料包。下载原件遇 502/503/504 隔 5 秒重试一次；仍没下载到的记进 `skippedFiles`（`downloadFailed: true`）并警告，报告必须在 `limitations` 写明（`report` 会核对）；中途令牌过期直接报 `loginRequired`，不建缺原件的包 |
| `local-init --node N --project-dir DIR [--files F…] [--project L] [--out D] [--workspace W] [--review-run R]` | 否 | 无 | 本地测试资料包。`--project-dir` 递归收入整个项目（跳过 `~$` 锁文件、隐藏文件、`__MACOSX`），`bundle.json` 的 `projectPath` 记原目录位置；`W`/`R` 可模拟服务器工作区和审查运行（可带 `{"data": …}` 外壳） |
| `skeleton --bundle D [--force]` | 否 | 无 | 生成 `audit.json` 骨架：每个原子检查（含 instruction、逐件项带 coverage 空位）和包里每份文件（reviewedFiles）都已列好，只需填空；已有 `audit.json` 时要 `--force` 才覆盖 |
| `ocr --bundle D [--files F…] [--force] [--timeout S] [--allow-egress]` | 是 | POST `/api/internal/ocr/mineru/tasks/upload`（原件字节；头 `Idempotency-Key`、`X-AICheck-Ocr-Metadata-B64`），GET `/api/internal/ocr/mineru/tasks/{jobId}`、`…/{jobId}/result` | 默认把包里全部没有文字层的原件（图片、扫描件、扫描页、转不出文字的 .doc，以及嵌了图片的 docx）上传到服务器识别：服务器用它自己配的 MinerU，MinerU 排队超时自动改用千问，本机不要任何 OCR 密钥（权限 `ai:recheck`，监检账号有）。上传名只用文件哈希；同一份原件同一个幂等键（`aicheck-node-audit-<哈希前 48 位>`），重跑、网关重试都拿回原任务。**服务器的幂等记录不过期，同一个键永远拿回第一次建的那个任务，失败的也一样**，所以重试要换键：任务失败、取消、完成却没有结果时，脚本在资料包 `ocr/attempts.json` 记一次重试，下次上传的键加 `-r1`、`-r2`…，服务器才建新任务；`--force` 重做已完成的文件也是这样。逐页文字存 `ocr/`（含完整证号的原文，0600，只给脚本回查）和 `text/<名>.ocr.txt`（已脱敏，可直接读）：文字块按阅读顺序排；表格按格展开、合并单元格值逐行重复，横跨多列的每行只写一次并标“（跨N列）”；公式写法转成原件写法（`$14\mathrm{mm}$`→`14mm`、`$\geqslant 300$`→`≥300`）；印章、签名记成 `[印章：…]`、`[签名：…]`；末尾附服务器抽取的字段（只作线索）。原件没变就 `cached` 不重做。返回 `done`（含 `provider`：mineru 或 qwen；`blankPages` 只算要靠 OCR 的页里没读出字的）、`cached`、`skipped`、`failed`（带服务器诊断码，只放真失败）、`progress`（“几份已有 OCR 文字/共几份”）。按服务器建议的间隔（至少 30 秒）查状态。`--timeout` 是整条命令的时长（上传加查状态，默认 300 秒、最多 420 秒）：每个请求的超时都按剩余时间截断，剩不到 20 秒不再开始新的上传，服务器重启时的退避也不越过期限；只有保证进展的第一份上传、第一次查状态最多给到 60 秒。到点就停，没上传的在 `notSubmitted`，没出完的在 `pending`（同一份文件只列一次；这次没来得及查的标 `state: submitted`，排在前面下次先查；换新任务重传的标 `retried`），再跑同一条命令接着来，不重传；每次至少传一份、查一份。任务失败、取消时当场换新键重传一次（返回 `retried`，不是失败；重试过仍失败的在 `failed` 里带 `autoRetried`）；这次来不及重传的（到点了、服务器不可用）记下重试次数、放进 `notSubmitted`／`notUploaded`，下次直接用新键传，不报失败。服务器诊断码是 HTTP_401、HTTP_403、MINERU_NOT_CONFIGURED 等的标 `kind: engineAuth`，只在**这次新建的任务**（服务器 `createdAt` 晚于本次命令开始）被拒时报：是服务器的 MinerU 令牌或配置问题，不是本机令牌，不当场重传；上次留下的失败任务（同一个键永远拿回它）照常换键重传。HTTP_429 标 `engineBusy`。`qualityWarnings` 按文件列出要靠 OCR 的页里读得不全的：没读出字、只读出几个字、识别跑飞（同一段字反复出现，或 40 字以上的同一行在一页里出现 5 次以上）、大幅面图纸；`text/<名>.ocr.txt` 的页头也标着。整份没有文字层、OCR 也一个字没读出的文件在 `nextStep` 里点名：`--force` 重做也一样，`reviewedFiles` 标 `skipped`。服务器偶尔把识别模型的英文说明（“The image provided is a QR code…”）当文字返回，整行换成 `[图块：识别模型没读出字（二维码、国徽、图案等）]`。整页读错了内容（管线号与本工程不符之类）认不出来。服务器暂时不可用（502/503/504、连不上，API 每约半小时重启一次，约一分钟）不会中止：上传时按 10、20、30 秒再试，仍不行就把这份和后面没传的放进 `notUploaded`（不是识别失败；键不变，稍后重跑拿回可能已建的任务，不重复建，也不记重试）；查状态、取结果时当作还在识别，在 `pending` 里标 `state: unreachable`，任务和进度都留着。`--files standard:rules/standards/<名>.pdf` 可 OCR 仓库里的标准原件。本地资料包第一次要 `--allow-egress`（先问用户；服务器会留存上传的原件）。查任务时服务器说任务不存在（`notFound`，任务被清理）：这一份记为失败，下次重跑换新键重新上传，不会每次卡在同一处；令牌过期（`loginRequired`）：命令中断，待办记着，重新授权后重跑接着等。OCR 记录带排版版本（`renderVersion`）：改排版之前存的记录照样能读（`text` 会提示 `ocrOutdated`），再跑一次 `ocr` 就从服务器上那个已完成的任务取结果按新排版重排（返回 `rerendered`），不重新上传、不重新识别；任务已不在就保留旧排版，要新排版加 `--force`。扫描页按原件文字层判：几乎没字，或字不多（200 字以内）而一张图占了大半页（扫描仪自带页眉页脚、垃圾文字层），或文字层是认错了的识别文字（满页罕用字），或 200 字以内的大幅面页（CAD 图纸的标注转成了线条），都要 OCR |
| `text --file F [--pages 4-6,9] [--bundle D \| --out O]` | 否 | 无（读 PDF 要 PyMuPDF） | 原件转文本存到资料包 `text/`，返回 `saved`；多页 PDF 每页前有 `--- 第 N 页 ---`，N 就是物理页。`--pages` 只转这几页（存 `<名>.p4-6_9.txt`，返回 `readPages`），不给就整份转；整份超过 20 页时带 `readHint`，提示按 `search` 命中页改用 `--pages`。跑过 `ocr` 的扫描件和扫描页给 OCR 文字（`status: ocr` 或 `ocrPages`，页头标“（OCR）”）；还没 OCR 的扫描页列在 `pagesWithoutText`，整份扫描件报 `noTextLayer`，先跑 `ocr`。包外文件（如仓库里的标准原件）必须加 `--bundle` 或 `--out`（文件或目录），否则报 `outputMissing`，不会写进仓库。文字层靠不住的页（认错的识别文字、扫描件自带的隐形识别文字、拆成一格一行的表格）：有这一页的 OCR 就只给 OCR 文字（算进 `ocrPages`），没有就照给文字层并在 `layerWarnings` 写明；仓库里的标准，有 OCR 的表格页也只给 OCR 文字（文字层常丢列，如 NB/T 47014-2023 表 6），工程资料的数字仍以文字层为准；嵌了图片的 docx 跑过 `ocr` 后，OCR 文字接在文字层后面，没跑时带 `embeddedImages`；文字层齐的工程资料页（如带文字层的施工图）有 OCR 时，OCR 多读出、文字层里没有的格（印章、签字栏人名、图片上的字）接在页末“以下是服务器 OCR 读出、文字层里没有的字”后面，页头标“（文字层＋OCR 补充）”、列在 `ocrSupplementPages`，`search` 也检索得到；和文字层比时去掉空白、标点，长格还和整份文字层比（服务器 OCR 会把后几页的字记到前一页），很多页都有的中英双语栏名只在第一页给；OCR 读得不全的页在 `ocrQuality`。GB 标准文字层里映射错的斜体字母（`犇`、`犛`、`犠`）自动换回 D、S、W。转出的文字里身份证号已脱敏 |
| `search --bundle D [--terms T…] [--only]`（`--terms` 是在默认词之外追加；加 `--only` 才只用你给的词） | 否 | 无（本地 PyMuPDF，用 `backend/.venv/bin/python` 跑） | 全包文字层和 OCR 文字检索（跑过 `ocr` 的扫描页一并检索，`filesWithHits` 的 `ocrPages` 标出来自 OCR 的页）：PDF 文字层、txt/csv、docx/xlsx 直接解析；.doc 先用内置 Word 97 解析（WPS 存的也能读），不行再走 textutil。默认词 = 本节点资料名称 + 工期/有效期/材质/人员等常见事实 + 按节点专业补的词（焊接、材料类节点带材质牌号、钢印、焊口等）。输出是摘要：`termHitFiles`（有命中的词各命中几份文件）、`zeroHitTerms`（有文字的文件里都没出现的词；包里还有没 OCR 的图片、扫描件或扫描页，或有 OCR 读得不全的页时带 `zeroHitNote`，提醒这些地方可能漏了，不能凭零命中说“没有”）、`filesWithHits`（每份文件的 `termPages` 按词列命中页，如 `焊口 p4-6、材质 p9`，每个词每份文件最多记 5 处，`--max-per-term` 可调；一条片段，`--sample N` 多看几条）、`idNumbersInText`（文字层和 OCR 文字里找得到的身份证号，已脱敏，及所在文件；这些可直接用脱敏号查 `cert-registry`）、无命中文件、`needsOcr`（还没 OCR 的图片、扫描件、读不了的 Office 文件）、`needsOcrPages`（文字 PDF 里夹的、还没 OCR 的扫描页）、`ocrQuality`（OCR 读得不全的页，按文件列）、`embeddedImages`（嵌了图片、还没 OCR 的 docx）。逐条命中和片段存 `search/<时间>.json`，路径在 `saved`，要看就读它，不用自己重定向输出。默认词还会按原子检查的 requiredFacts 补（如设计变更、出图专用章、施焊日期）。片段里的身份证号已脱敏 |
| `pages --file F (--pages 1-3,7 \| --sheet) [--dpi N] [--clip x0,y0,x1,y1] [--rotate 90\|180\|270] [--bundle D \| --out O] [--text-only]` | 否 | 无（本地 PyMuPDF，用 `backend/.venv/bin/python` 跑） | **审计时不用**：不自己看图，扫描件走 `ocr`，OCR 读不清的交人工确认。只给人工复核出页图：PDF 或图片渲染成 PNG（一次最多 20 页），`--sheet` 出缩略拼图，`--clip`/`--dpi` 放大局部、`--rotate` 转正横放的页。输出只进资料包：资料包里的文件默认存它的 `pages/`；包外文件（如仓库里的标准原件）必须加 `--bundle <资料包>` 或 `--out`，否则报 `outputMissing` |
| `pages --all-visual --bundle D [--dpi N]` | 否 | 无（PyMuPDF） | **审计时不用**；给人工复核出缩略拼图：最近一次 `search` 标出的全部还没 OCR 的文件（部分扫描的 PDF 只拼扫描页）；返回每个文件的 `sheets`、`formFieldPages`，打不开的（如 .doc）在 `skipped` |
| `cert-registry --kind person\|organization_license --identifier X` | 否 | POST `/api/inspection-services/certificate-registry` | 公示平台登记查询。人员：号码在 `search` 的 `idNumbersInText` 里，就传脱敏号加 `--bundle`（要加单引号，如 `--identifier '1101**********1237'`；不加引号 zsh 会把星号当通配符，报 `no matches found`），脚本从原件文字层找回完整号码再查；不在里面的（OCR 没读出，传脱敏号会报 `identifierNotFound`），先跑 `ocr` 再传脱敏号；OCR 也没读出就交人工，写进 `limitations`。完整号码先验出生日期和校验位，对不上报 `idChecksumFailed`、不去平台查，多半是读错了一位 |
| `cert-validity --json '{…}'` | 否 | POST `/api/inspection-services/certificate-validity` | 有效期/主体/范围字段核对 |
| `cnse-org-search --keyword 单位名` | 是（本地资料也要） | POST `/api/cnse/organizations/search` | 只有单位名、没有 TS 编号时用。没登录报 `loginRequired`：有 TS 号就改用 `cert-registry`，没有就写进 `limitations` |
| `standards --query Q` | 否 | GET `/api/inspection-services/standards` | 公共标准检索。命中里超过 300 字的文字只留开头并注明总字数，原文用 `standard-content` 读 |
| `standard-content --file-id KF-KB-… [--page-no N] [--section S]` | 否 | GET `/api/inspection-services/standards/{fileId}/canonical` | 标准规范化原文 |
| `standard-status --ref 标准号 [--date YYYY-MM-DD]` | 否 | POST `/api/inspection-services/standard-status` | 标准的有效状态。`verdict` 按今天算；给了 `--date` 再看 `onDate`：`status` 是那一天的状态（`in_force` 有效、`not_yet_effective` 未实施、`withdrawn` 已废止、`unknown` 没有实施日期），附 `effectiveFrom`、`withdrawnOn` |
| `node-standards --project P --node N` | 是 | GET `…/inspection/nodes/{N}/standards` | 节点固定依据条款（fetch 已包含） |
| `report --bundle D` | 否 | 无 | 校验 `audit.json`，生成 `audit.md`。服务器节点会把服务器结论（`serverResult`、`agreesWithServer`）写回 `audit.json`，这时输出 `auditJsonUpdated: true`，之后再改 `audit.json` 要先重新读一遍；本地资料不改写它。输出 `outcome`（节点整体：通过／不通过／暂不能判定通过）、`outcomeExplain`、`syncAvailable`，以及 `fullReport`：完整结果（节点结论、逐项的结论、理由、事实和出处、下一步、最需要先做的事、缺的资料、风险、总体意见、局限、已阅读文件），和 `audit.md` 一字不差，回复用户时直接用它，不要只给路径 |
| `render --bundle D [--out F]` | 是 | POST `/api/inspection-services/audit-result-image` | 先按 `report` 同样的规则校验 `audit.json`（不合格就拒绝，不发请求），再把**摘要**（节点结论、每项的结论、一句话理由、主要依据、最要先做的事、缺的资料、风险提示、总体意见；不含每项的事实全文；证号再脱敏一遍）发给服务器，服务器用 HTML 模板（PyMuPDF 排版，中文用自带字体）渲染成白底的 PNG，**一次返回所有页**：`{pageCount, pages:[{pageNo, imageBase64}]}`。一页存成资料包里的 `audit.png`；多页存成 `audit-1.png`、`audit-2.png`……（0600），每次先清掉上一次留下的 `audit*.png`，免得旧页混进新结果；`--out F` 指定路径时，多页在文件名后加页码（`F-1.png`…），不动目录里别的文件。返回 `images`（按页码排好的路径）、`pageCount`、`bytes`、`outcome`。版式：白底，每页顶部一条结论颜色的细线，页脚有免责说明和「第 n / N 页」。第 1 页是总览——节点名和大号结论块（绿＝通过、红＝不通过、琥珀＝暂不能判定）、按各结论占比着色的分段条和图例、最要先做的事、风险提示、缺的资料、总体意见；之后是逐项结论，每项一张卡片（左边一条结论色，检查号、名称、结论标签、理由、依据，与服务器结论不同的会标出），卡片整张排在一页里不拆开，第 2 页起有页眉。总览只占不到一半页面时逐项结论紧接着排，占了大半页就让逐项结论另起一页。最多 16 页，超过服务器回 400（内容过长）。要登录且账号有 `ai:recheck`（监检账号有）；服务器同时最多渲染两张，忙时回 429；渲染在子进程里，超时 45 秒。服务器没有这个接口（旧版后端）报 `renderNotDeployed`。服务器不存摘要也不存图 |
| `sync --bundle D [--confirm --preview-hash H]` | 是 | GET 节点 `evidence-chain`；确认后 POST `/api/review/findings` | 预览返回 `willCreate`、`skipped`、`previewHash` 及完整计划的 `savedTo`，只保存本地快照。用户确认该次具体内容后，用同一摘要确认；缺预览、摘要不符、报告或证据链改变均拒绝写入。预览里的 `earlierSyncs` 列出这个节点以前（别的资料包，或本包改报告之前）已经写到这台服务器上的 AI 发现（按发现号去重）：内容不同幂等键就不同，服务器不合并，再同步会多出一套草稿，要告诉用户。仅匹配同版本、同页且摘录或字段和值对应的唯一已确认有效证据，不借用同文件其他链接（摘录比对时忽略空白、表格竖线、“（跨N列）”和 `[印章：…]` 的外壳，身份证号两边都按脱敏后比；横跨格在服务器引文里逐格重复的，摘录对不上，靠字段和值那条路配）。只挂逐条对上的证据：至少一条事实对上才写这一项，对不上的事实列在 `willCreate` 的 `unmatchedFacts`，也写进发现说明请人工按出处核；一条都对不上的整项列入 skipped，本地报告保留。相同实际请求同幂等键，内容改变须重新批准；结果另存 sync/。只写草稿 AI 发现、待人工复核，不改节点状态或人工意见，且只能同步到取数时的服务器 |

查询类命令（`cert-registry`、`cert-validity`、`cnse-org-search`、`standards`、`standard-content`、`standard-status`）都可加 `--bundle <资料包>`：结果连同参数和时间存进 `tool-results/`（0600），返回的 `savedTo` 就是报告里 `tool:` 引用的出处。审计时一律带上。

Office 原件直接读不了：用 `node_audit text --file <原件>` 转成文本（.doc 内置 Word 97 解析，WPS 存的也能读；.docx/.xlsx 直接解析），返回的 `saved` 再读全文。转不出来（`noTextLayer`）就跑 `ocr`（服务器 OCR 收 .doc/.docx/.ppt），或请用户给 PDF。引用时 `source.file` 仍写 `files/` 下的原件，`text/…` 和行号写进 `locator`。

所有命令的输出、`search` 存档、`text` 转出的文字、`ocr` 的 `.ocr.txt`、`tool-results/` 存档里的身份证号都自动脱敏（前 4 位 + `**********` + 后 4 位）；完整号码只在原件和 `ocr/` 原文存档里（含 `ocr/server/` 下服务器 JSON 的原文；包根目录的 `workspace.json`、`evidence-chain.json`、`review-run.json` 已脱敏），`cert-registry` 用脱敏号回那里找。脱敏按宽口径：出生日期合法、首位 1–8 的 18 位号都遮，校验位不对（OCR 读错一位）的也遮；以 9 开头的全数字统一社会信用代码不遮。不要读 `ocr/` 下的文件。

## fetch 拉什么

| 文件 | 来源 | 内容 |
|---|---|---|
| `workspace.json` | GET `/api/projects/{P}/inspection/nodes/{N}/audit-workspace`（服务器把内容放在 `content` 下，存进包时已摊平，下面的键都在顶层；这份和下面四份 JSON 存进包根目录时已脱敏，原文在 `ocr/server/`，别读） | 资料要求、已提交挂载、文件与 OCR 就绪度、抽取字段（`ocr.extractedFields`）、证据就绪度与链接、审查运行列表、人工意见 |
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

`bundleMissing`（`--bundle` 指的不是资料包：路径写错或还没 fetch／local-init，命令没执行）、`loginRequired`（HTTP 401，或服务器在 HTTP 200 里返回业务码 401——两种都翻成这个码，`serverCode` 保留原数字；重新 `login --web` 授权）、`forbidden`（HTTP 403 或业务码 403：角色或节点范围不够）、`notFound`（HTTP 404 或业务码 40404）、`rateLimited`（看 `retryAfter`）、`unreachable`、`insecureTransport`（远程 HTTP 未放行）、`ttyRequired`（login 不在用户终端）、`pyyamlMissing`、`reportInvalid`（看 `errors`）、`identifierNotFound`（脱敏号在原件文字层里找不到）、`idChecksumFailed`（身份证号读错了一位）、`egressNotApproved`（本地资料包没得到上传同意：问用户，同意后加 `--allow-egress`）。服务器 OCR 任务失败时，`ocr` 的 `failed` 里写着服务器诊断码（如 `QWEN_OCR_FAILED`、`MINERU_PENDING_TIMEOUT`）：再跑一次同一条 `ocr`，它会换新任务重试（不用加 `--force`，已记下重试次数）；仍失败写进 `limitations`。生产版本较旧时 `standards` 等接口可能 404：记为能力不可用，不影响其他检查。

服务器一时不可用（部署、重启）会返回 `http502`/`http504`，公示平台暂不可查询会返回 `http503`：脚本已自动隔 5 秒重试一次。仍失败、或返回 `unreachable`、超时：先做不需要服务器的步骤（检索、OCR、读原件），隔 1–2 分钟再试一次；`connection` 开头报 502 也一样，不必停下。重试后仍失败按 audit-method 的“平台不可用”处理。
