# 试跑 Codex（或别的助手）

状态：只做了准备，还没跑过 Codex。下面的前置项里标“没验证”的，要在第一次试跑前先确认。

这个目录是开发资产，不放进 skill 目录：里面有评测流程，执行者不该读到。

## 先确认三件事，缺一不可

1. **资料出境。** 执行者会把证书、合同的整页图片读给模型看。命令输出里的身份证号已脱敏，页图上的号码看得见。换成 Codex，这些测试资料就发给了另一家模型服务商。这一步要用户自己决定。
2. **能不能看图。** skill 里扫描件、证照、质证书都要靠看页图。先开一个空会话，让它打开一张本地 PNG 并说出内容；不行，这个 skill 对它就没有意义（没验证）。提示词里已写：看不了图就停，只回复“无法看图”。
3. **沙箱。** 执行者要连服务器（明文 HTTP）、用 `backend/.venv` 里的 PyMuPDF、往试跑目录写资料包。`codex exec` 有 `-s workspace-write`、`-C <工作区>`、`--add-dir <额外可写目录>`；网络默认是否关闭、怎么放开，以本机 Codex 文档为准（没验证）。不要为了省事用 `--dangerously-bypass-approvals-and-sandbox`。读权限通常不受 workspace-write 限制，所以不隔离的话它读得到标准答案目录。

另外两处试跑前请你扫一眼：`~/.codex/AGENTS.md` 会被每个会话载入；`~/.codex/aicheck-jev-eval` 是旧评测结果目录，属于“别的审计结果”，可以先挪走。我没看过它们的内容。

## 步骤

把下面的 `<…>` 换成你的值。命令在仓库根目录执行。

**1. 准备（隐藏标准答案，复制项目，记下仓库里已有的文件）**

```bash
mkdir -p /tmp/codex-trial-tmp
python3 skills/aicheck-node-audit-dev/eval/isolate.py prepare --tag r11-codex --project "<项目目录>" --watch /tmp/codex-trial-tmp
```

返回里有 `projectDir`、`runsDir`、`transcriptsDir`、`env`。`prepare` 之后审计目录会改名成 `.aicheck-node-audit.hold`，到 `finish` 才还原；中间不要用别的会话去用审计目录。

**2. 每个节点：一个全新会话，一条命令**

```bash
python3 skills/aicheck-node-audit-dev/eval/isolate.py prompt --tag r11-codex --node 24 \
  --project-dir "<projectDir>" --base-url "<服务器地址>" --raw \
| TMPDIR=/tmp/codex-trial-tmp codex exec -C "$(pwd)" -s workspace-write --add-dir "<runHome>" \
    --json -o "<transcriptsDir>/node-24-last.txt" - > "<transcriptsDir>/node-24.jsonl"
```

要指定模型加 `-m <模型>`。`--json` 的输出是过程记录，放在 `transcriptsDir`（隐藏目录里，执行者够不着）。

**3. 每个节点跑完，立刻检查并清场，再开下一个**

```bash
python3 skills/aicheck-node-audit-dev/eval/isolate.py scan --tag r11-codex "<transcriptsDir>/node-24.jsonl"
python3 skills/aicheck-node-audit-dev/eval/isolate.py stash --tag r11-codex --move-stray
```

- `scan` 看三项：`peeks`（碰过答案目录、旧结果、记忆、评估文档、别的试跑目录没有）、`directPdfReads`（自己写脚本读 PDF）、`fullIdNumberLines`（工具输出里出现完整身份证号）。命中只说明字符串出现过，要看上下文。
- `stash` 把这个节点的资料包移出执行者够得着的地方，下一个节点看不到；执行者在仓库或 `/tmp/codex-trial-tmp` 里新留下的文件会列出来（`newInRepo`、`newInWatched`）。加 `--move-stray` 只把 `--watch` 目录里的移进归档；仓库里新冒出的要看过 `newInRepo`、确认是执行者留下的，再用 `--move-repo <路径…>` 点名移走（仓库里常有别的会话在写，2026-10-28 一次误移过别的会话 138 个文件）。以前吃过亏：上一个节点的脚本里带着结论，下一个节点读到了。

**4. 全部跑完：还原并打分**

```bash
python3 skills/aicheck-node-audit-dev/eval/isolate.py finish --tag r11-codex --move-stray
python3 skills/aicheck-node-audit-dev/eval/score.py --gold ~/.aicheck-node-audit/eval/gold/holdout/tank-node-24.json \
  --bundle ~/.aicheck-node-audit/eval/runs/r11-codex/runs/<资料包目录>
```

`finish` 会检查归档里有没有完整身份证号、删掉执行者那份项目副本、把审计目录改回原名。资料包目录名是 `codex-<项目目录名>-node-<节点号>`。

出了岔子先看状态；没还原的话手工改回：

```bash
python3 skills/aicheck-node-audit-dev/eval/isolate.py status
mv ~/.aicheck-node-audit.hold ~/.aicheck-node-audit
```

## 跑哪些节点、怎么算

- 保留节点 02、03、25、38 各 1 次（标准答案已确认）。节点 16 的口径是从它的结果里学来的，不再当干净样本。
- 达标：每个节点 ≥85% 且没有严重问题（误判符合、误判不符合、完整身份证号、校验不过）。
- 同时记 token 和用时，`report` 校验有没有一次过。

## 比较时要小心

- skill 在 Sonnet/Haiku 最后一轮复跑（第十轮）之后又改了：条件句规则、503 自动重试、检索零命中提示、几张标准页码表，还有这次的中性措辞。这些改动都没用子代理验证过。Codex 的分数和之前 Claude 的分数不能直接比，要比就在同样的节点上用 Sonnet 再跑一次。
- 没验证的还有：`codex exec --json` 的记录里是否包含工具输出全文（不含的话，`scan` 查完整身份证号会漏，以 `finish` 对资料包的检查为准）；提示词对 Codex 要不要再调。
