/**
 * 原因码翻译覆盖率守门：后端新增一个原因码而这里没词，测试就红。
 *
 * 2026-09-13 用户实测：界面上一直有 `consumable_certificate_or_design_requirement` 这类
 * 生码。全库扫出 295 个原因码，逐条列表跟不上，所以按词翻译＋后缀组框；这条测试
 * 从后端源码现抽代号，确保「一个都不剩」。
 */
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'

import { friendlyCheckReason } from './components/auditLabels'

const EXTRACT = String.raw`
import re, pathlib, json, sys
codes = set()
for p in pathlib.Path(sys.argv[1]).rglob("*.py"):
    t = p.read_text(errors="ignore")
    codes |= set(re.findall(r'"([a-z][a-z0-9_]*_missing)"', t))
    codes |= set(re.findall(r'"([a-z][a-z0-9_]*_not_(?:configured|verified|available|found|applicable|met|indexed))"', t))
    codes |= set(re.findall(r'_insufficient\(\s*"[^"]+",\s*"([a-z0-9_]+)"', t))
    codes |= set(re.findall(r'"reason":\s*"([a-z][a-z0-9_]+)"', t))
print(json.dumps(sorted(codes)))
`

const codes: string[] = JSON.parse(
  execFileSync(
    'python3',
    ['-c', EXTRACT, new URL('../../../../backend/libs', import.meta.url).pathname],
    {
      encoding: 'utf8'
    }
  )
)

assert.ok(codes.length > 200, `应当扫到几百个原因码，实际 ${codes.length} 个——抽取正则可能失效了`)

// 翻完的结果里不该再出现 snake_case 英文片段
const untranslated = codes.filter((code) => /[a-z]{3,}_[a-z]/.test(friendlyCheckReason(code)))
assert.deepEqual(
  untranslated,
  [],
  `这些原因码还没翻译，请在 auditLabels 的 REASON_WORDS / REASON_STEMS 里补：\n${untranslated.join('\n')}`
)

// 「未抽取」框架：必填栏要从别的文件抽取而尚未抽取时的原因码后缀
assert.ok(
  friendlyCheckReason('r68_plan_method_not_extracted').endsWith('尚未抽取，需人工核对'),
  friendlyCheckReason('r68_plan_method_not_extracted')
)
