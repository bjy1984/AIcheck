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
  for (const check of checks) {
    check.pattern.lastIndex = 0
    for (const match of content.matchAll(check.pattern)) {
      const line = content.slice(0, match.index).split('\n').length
      findings.push({
        code: check.code,
        file: relative(process.cwd(), path),
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
