import { readFile, readdir } from 'node:fs/promises'
import { extname, join, relative, resolve } from 'node:path'

const root = resolve(process.cwd(), 'src')
const extensions = new Set(['.ts', '.tsx', '.js', '.jsx', '.vue', '.css', '.scss', '.less'])
const checks = [
  {
    code: 'DEMO_IDENTIFIER_IN_PRODUCTION_SOURCE',
    pattern: /DEMO[-_ ]PROJECT|demo[-_ ]project|P[-_]\d{4}[-_]MOCK/gi,
    message: '生产业务源码不得包含演示项目标识。'
  },
  {
    code: 'FIXED_69_NODE_LIMIT',
    pattern: /(?:badge\s*:\s*['"]69\s*项|:max\s*=\s*['"]69['"]|\|\|\s*69\b)/g,
    message: '节点范围必须来自业务包或后端响应，不能固定为 69。'
  },
  {
    code: 'EXCESSIVE_FONT_WEIGHT',
    pattern: /(?:font-weight\s*:\s*(?:800|900)|fontWeight\s*:\s*(?:800|900))/g,
    message: '工业操作界面禁止使用 800/900 业务字重。'
  },
  {
    code: 'HARDCODED_DEMO_TENANT',
    pattern: /tenantId\s*:\s*['"]demo['"]/gi,
    message: '生产业务源码不得写死演示租户。'
  },
  {
    code: 'FAKE_COMPARE_MODEL_ALIAS',
    pattern: /['"]LLM-[A-Z]['"]/g,
    message: '模型选择必须使用运行时可解析的应用模型别名。'
  }
]

const aicheckUiChecks = [
  {
    code: 'AICHECK_HANDMADE_ELEMENT_MESSAGE',
    pattern: /class=["'][^"']*\bel-message\b[^"']*["']/g,
    message: 'AICheck 页面不得手工仿造 Element Message，请使用 ElMessage 或 ElNotification。'
  },
  {
    code: 'AICHECK_LEGACY_BASE_BUTTON',
    pattern: /<BaseButton\b/g,
    message: 'AICheck 页面不得继续引入旧 BaseButton，请使用 Element Plus 按钮。'
  },
  {
    code: 'AICHECK_PSEUDO_ACTION_TEXT',
    pattern: /<span\s+class=["']action-text["'][^>]*>/g,
    message: '无事件处理的 action-text 会形成伪交互；请接入真实动作或明确标记为不可用说明。'
  },
  {
    code: 'AICHECK_TOPBAR_HAMBURGER',
    pattern: /class=["']hamburger["']/g,
    message: 'AICheck 顶栏不得放置重复的导航收起按钮。'
  }
]

const sourceFiles = []
const walk = async (directory) => {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) await walk(path)
    else if (extensions.has(extname(entry.name))) sourceFiles.push(path)
  }
}

await walk(root)

const findings = []
for (const path of sourceFiles) {
  const content = await readFile(path, 'utf8')
  const relativePath = relative(process.cwd(), path)
  const activeChecks = relativePath.includes('views/AICheck/')
    ? [...checks, ...aicheckUiChecks]
    : checks
  for (const check of activeChecks) {
    check.pattern.lastIndex = 0
    for (const match of content.matchAll(check.pattern)) {
      const line = content.slice(0, match.index).split('\n').length
      findings.push({
        code: check.code,
        file: relativePath,
        line,
        message: check.message,
        excerpt: match[0]
      })
    }
  }
}

const loginSource = await readFile(resolve(root, 'views/Login/Login.vue'), 'utf8')
if (/RegisterForm|公开注册|立即注册/.test(loginSource)) {
  findings.push({
    code: 'PUBLIC_REGISTRATION_ENTRY',
    file: 'src/views/Login/Login.vue',
    line: 1,
    message: '生产登录页不得暴露公开注册入口。'
  })
}

const report = {
  schemaVersion: 'aicheck-operability-static-audit@1',
  generatedAt: new Date().toISOString(),
  scannedFiles: sourceFiles.length,
  passed: findings.length === 0,
  findings
}

console.log(JSON.stringify(report, null, 2))
if (findings.length) process.exitCode = 1
