# 安装与连接审查服务

本 skill 的名称是 `aicheck-inspection`。同一份规则和资料审查流程可用于 Claude Code、Cursor 以及支持 Agent Skills 的其他平台。工程资料由用户在本地或当前会话提供，读取、OCR、字段整理和审查由宿主 AI 完成，报告保存在本地或会话中。MCP 按需提供标准依据、规则和证件核验能力，不提供工程资料库、OCR 或后台审查任务。

导入 skill 不会自动登录后台，也不会自动配置 MCP。以下命令中的路径、地址均为示例，请替换为本机实际值；不要把生产 `.env`、SSH 私钥、口令或 token 放进 skill 文件夹或分发 ZIP。

## 1. 安装 skill

解压后应得到完整的 `aicheck-inspection` 文件夹，内含 `SKILL.md`、`references/` 和 `scripts/`。复制整个文件夹，保留相对目录结构。

### Claude Code

项目内安装到 `.claude/skills/aicheck-inspection/`；个人全局安装到 `~/.claude/skills/aicheck-inspection/`。下面是 macOS/Linux 的全局安装示例，变量和路径均带引号，支持路径含空格：

```sh
skill_source="/absolute/path/to/aicheck-inspection"
mkdir -p "$HOME/.claude/skills"
cp -R "$skill_source" "$HOME/.claude/skills/aicheck-inspection"
```

首次安装时执行以上复制；若目标已存在，先核对备份与版本，避免复制成重复嵌套的文件夹。项目级安装时，将目标父目录改为当前工程的 `.claude/skills`。在 Claude Code 中输入 `/aicheck-inspection`，或使用后面的自然语言示例。首次新建 skills 根目录后若未发现 skill，重启会话。[Claude Code 官方安装说明](https://code.claude.com/docs/en/skills)

### Cursor

项目内安装到 `.cursor/skills/aicheck-inspection/`；个人全局安装到 `~/.cursor/skills/aicheck-inspection/`：

```sh
skill_source="/absolute/path/to/aicheck-inspection"
mkdir -p "$HOME/.cursor/skills"
cp -R "$skill_source" "$HOME/.cursor/skills/aicheck-inspection"
```

Cursor 自动发现这些目录中的 `SKILL.md`，也支持 `.agents/skills/` 和兼容的 Claude skills 目录。一个安装位置即可，无需复制多份。个人本地目录不等于云端可用；云端会话需按 Cursor 的技能同步或项目仓库机制配置。本包采用目录复制方式安装。[Cursor 官方 Skills 说明](https://cursor.com/docs/skills)

Windows 可用文件管理器复制相同目录结构。执行下文脚本时使用本机 Python 的实际路径；JSON 中的 Windows 路径应写成 `C:\\...` 或使用 `/`。

### Claude 网页与 Desktop 的 Skills

将 `aicheck-inspection` 文件夹压成 ZIP，结构应为：

```text
aicheck-inspection.zip
└── aicheck-inspection/
    ├── SKILL.md
    ├── references/
    └── scripts/
```

不要把 `SKILL.md` 裸放在 ZIP 根目录，也不要再套一层发布目录。在 Claude 的 Customize → Skills → Create skill → Upload a skill 中上传并启用，随后提供待审查资料。组织管理员可能限制自建 skills；相关能力需在账户中启用。[Claude 上传入口](https://support.claude.com/en/articles/12512180-use-skills-in-claude)、[ZIP 结构要求](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills)

**本包仅提供本地 stdio MCP，不提供已部署的远程 MCP connector。** Claude 网页可使用上传的规则和资料进行审查，但不能因上传 ZIP 就访问本地桥接器或 AIcheck 后台。Claude Desktop 聊天可另配置本地 MCP；Cowork 与网页不能照搬 Desktop 本地 MCP 配置。需要网页后台能力时，应另外部署可由 Anthropic 云端访问的远程 MCP，配置认证后再连接。用户电脑上的 localhost、VPN 或 SSH 隧道不代表 Anthropic 云端可达。[Claude 官方网络与客户端限制](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)

## 2. 首次连接 AIcheck 审查服务

本地桥接脚本要求 Python 3.10 或更高版本，只使用 Python 标准库，无需复制或安装 AIcheck 后端工程。优先使用已有的 HTTPS 后台地址。若服务器仅可通过 SSH 访问，可使用用户已授权的 SSH 隧道，将服务转到本机 loopback，再使用 `http://127.0.0.1:<port>`；不在 skill 中保存 SSH 私钥。

在本机终端设置以下变量。`AICHECK_BASE_URL` 可以是服务 origin，也可以以 `/api` 结尾，由客户端统一处理；不要附加具体业务接口路径。token 文件应位于 skill 和仓库之外，使用绝对路径：

```sh
export AICHECK_BASE_URL="https://aicheck.example.com"
export AICHECK_TOKEN_FILE="$HOME/.config/aicheck/inspection-token.json"

python3 "/absolute/path/to/aicheck-inspection/scripts/aicheck_client.py" connection --json '{}'
python3 "/absolute/path/to/aicheck-inspection/scripts/aicheck_client.py" login
```

`connection` 用于连接诊断；尚未登录时出现需要认证的提示，应先完成登录再检查。`login` 会交互询问用户名，并用隐藏输入读取密码；登录凭据写入 `AICHECK_TOKEN_FILE`，不要将用户名和口令直接拼入命令。登录后可再运行 `connection` 检查。

服务地址必须由部署信息或用户提供，不猜测生产地址。已有受限服务 token 时也可设置 `AICHECK_TOKEN`，此时不要再提供另一份不一致的 token 文件。不要把 token 贴进聊天、示例 JSON、截图、日志或版本库；MCP 配置推荐仅引用 token 文件路径。身份过期或被撤销时重新登录，不能换用管理员凭据绕过权限。服务连接无需后台工程 ID，登录只用于授权使用审查能力。

## 3. 让 AI 平台使用 MCP 工具

MCP 运行脚本为 `scripts/mcp_server.py`，采用 stdio。Python 命令与脚本路径都应使用本机绝对路径；不要假设 AI 平台进程继承了终端中的环境变量。下面把后台地址和 token 文件路径显式传给子进程，且不嵌入实际 token。

### Claude Code 配置

将下面的 `aicheck-inspection` 条目**合并到**项目根目录 `.mcp.json` 的 `mcpServers` 对象。保留已有服务器和其他配置，不整文件覆盖：

```json
{
  "mcpServers": {
    "aicheck-inspection": {
      "type": "stdio",
      "command": "/absolute/path/to/python3",
      "args": ["/absolute/path/to/aicheck-inspection/scripts/mcp_server.py"],
      "env": {
        "AICHECK_BASE_URL": "https://aicheck.example.com",
        "AICHECK_TOKEN_FILE": "/absolute/path/to/private/inspection-token.json"
      }
    }
  }
}
```

在 Claude Code 用 `/mcp` 检查服务器状态，按平台提示启用项目 MCP。需要全局安装时，可使用官方 `claude mcp add --scope user --transport stdio ...` 入口；不要把项目 JSON 直接写入 `~/.claude.json` 并覆盖其他设置。[Claude Code 官方 MCP 配置](https://code.claude.com/docs/en/mcp)

### Cursor 配置

将以下条目合并到项目 `.cursor/mcp.json`，或全局 `~/.cursor/mcp.json` 的 `mcpServers` 对象，同样保留已有条目：

```json
{
  "mcpServers": {
    "aicheck-inspection": {
      "type": "stdio",
      "command": "/absolute/path/to/python3",
      "args": ["/absolute/path/to/aicheck-inspection/scripts/mcp_server.py"],
      "env": {
        "AICHECK_BASE_URL": "https://aicheck.example.com",
        "AICHECK_TOKEN_FILE": "/absolute/path/to/private/inspection-token.json"
      }
    }
  }
}
```

在 Cursor 的 MCP 设置中检查连接与工具列表。每个绝对路径是一个 JSON 字符串，不要在字符串内部再包 shell 引号；`args` 数组会正确保留路径中的空格。[Cursor 官方 MCP 配置](https://cursor.com/docs/mcp)

### Claude Desktop 本地 MCP

Claude Desktop 聊天可通过其开发者设置配置本地 MCP；在现有 `claude_desktop_config.json` 的 `mcpServers` 中合并同名条目，使用上述 `command`、`args`、`env`，省略 `type`。路径以应用设置显示的配置文件为准，随后检查连接状态。本包是 Python stdio 服务与 skill，不是 `.mcpb` 桌面扩展，不能将 skill ZIP 放入“Install Extension”冒充扩展。若后续需要桌面一键安装，可另制作 `.mcpb` 并验证依赖与配置。[Claude Desktop 官方本地 MCP 说明](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop)

## 4. 调用示例与验收

离线资料审查无需后台：

> 使用 aicheck-inspection，根据随包的业务节点描述 v3，审查我提供的焊工资格证、焊口台账和焊接记录。先列明资料范围与适用节点，再逐项给出证据、缺项和待人工核验事项。

连接审查服务后：

> 使用 aicheck-inspection 审查我提供的本地资料。先在当前平台完成必要的 OCR，保留文件名、可获取的内容哈希、原页码、原文定位、结构化字段和不确定标记，再按 v3 逐项核查。需要时通过 MCP 查询规则、标准和证件有效性；仅发送必要查询字段，不把原文件或 OCR 正文上传后台，报告保存在本地。

平台应能发现以下 7 个工具，以实际返回的 schema 为准：

| 工具 | 用途 | 对外传输内容 |
| --- | --- | --- |
| `aicheck_connection` | 认证和能力诊断 | 服务连接信息 |
| `aicheck_rules` | 查询单节点规则及版本 | 节点编号；随包规则可离线读取 |
| `aicheck_standards` | 查询标准依据 | 标准关键词 |
| `aicheck_standard_content` | 读取标准原文 | 标准或条款标识 |
| `aicheck_standard_status` | 查询标准状态 | 标准号（含版本）和审查日期 |
| `aicheck_certificate_validity` | 按已提供的事实检查有效期、范围等 | 必要证件字段及施工基准信息；不等于官方真实性核验 |
| `aicheck_certificate_registry` | 独立的官方通道核验 | 用户已授权外发的最小身份字段 |

先用 `connection` 检查新服务接口及具体能力，再用一个规则查询和一次标准查询验证响应。进程启动成功或工具列出成功都不能单独证明后端能力可用。宿主平台能否读取和识别用户资料须单独验证；证件外部查询需另有真实的授权与可用通道，不能用本地日期计算冒充验收。

可让平台执行下面这组调用作为连接验收；以下仅为工具参数示例：

```text
aicheck_connection({})
aicheck_rules({"nodeId": 24, "source": "local"})
aicheck_rules({"nodeId": 24, "source": "server"})
aicheck_standards({"query": "工业管道焊接", "page": 1, "pageSize": 10})
```

MCP 不接受 `filePath`、文件字节或完整 OCR 文本。用户资料需由当前 AI 平台直接读取；扫描页先使用该平台的 OCR／视觉识别能力，按 [审查输出与判定](review-contract.md) 保留来源与不确定标记。若平台没有相应能力、无法访问附件或识别不足，应请用户提供可检索 PDF／文字，或先在平台完成识别。skill 可在本地整理字段，再把必要核验字段交给 MCP；无需上传资料或启用远程整理工具。调用参数详见 [服务调用流程](backend-workflow.md)。

`certificate_registry` 与 `certificate_validity` 分开使用：前者仅在已授权必要身份信息发往指定官方平台时设置 `allowExternalQuery: true`；后者依据用户提供事实计算，须明确 `referenceDate` 或完整的 `periodStart` 与 `periodEnd`，不证明证件真伪。日期应来自工程实际施工时间，缺失时不能用今天代替。系统不缓存本次查询输入或结果；该约束不代表政府核验平台或宿主 AI 平台零留存。

## 5. 服务器版本与失败处理

部署中的后台可能尚未提供新的无持久存储审查服务。出现接口不存在、能力未启用或版本不匹配时，应根据连接诊断和真实响应说明缺失能力，不把空结果写成业务不存在，也不把本地分析包装成服务调用成功。

始终使用用户提供的本地资料，结合随包 v3 继续可完成的核查。明确报告资料哈希、规则来源、缺失证据和未运行的系统能力。系统规则与随包规则存在差异时展示差异来源，不静默混用。新服务不可用时，不调用旧工程资料、上传、OCR 或审查任务接口补救。宿主平台不能识别资料时，受影响的核查项应停留在输入预处理环节并请求可读资料，其余独立核查继续；不能把未识别内容当成已确认事实。

401/403 表示需要恢复有效身份或权限；不得绕过权限。超时、无法识别、无法查看原文与“证据不足”应分别记录；工具失败不能推断业务符合或不符合。审查服务部署、宿主平台资料识别及 MCP 连接需要分别验证，不能因为本地 skill 可读就宣称服务器新接口或远程 MCP 已上线。

## 官方参考

- [Claude Code：Skills](https://code.claude.com/docs/en/skills)
- [Claude Code：MCP](https://code.claude.com/docs/en/mcp)
- [Claude：使用 Skills](https://support.claude.com/en/articles/12512180-use-skills-in-claude)
- [Claude：创建与打包自定义 Skills](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills)
- [Claude：远程 MCP 与网络要求](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)
- [Claude Desktop：本地 MCP 与扩展](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop)
- [Cursor：Skills](https://cursor.com/docs/skills)
- [Cursor：MCP](https://cursor.com/docs/mcp)

以上平台安装方式依据 2026-09-22 核对的官方文档；界面名称与组织策略可能随后调整。
