/**
 * 界面生码守门：检查码、发现类型、资料类型代号。
 *
 * 2026-09-13 用户实测：界面上到处是 `consumable_certificate_or_design_requirement`、
 * `all_codes_decoded`、`welder_certificate` 这类原始代号。这条测试从后端源码现抽，
 * 后端新增一个代号而前端没词，就红。
 */
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'

import {
  friendlyCheckCode,
  friendlyEvidenceIssue,
  friendlyFieldLabel,
  friendlyMaterialType,
  friendlyRuleCode,
  friendlyTechTerm
} from './components/auditLabels'
import { findingTypeLabel } from './workbenchReviewPresentation'

const EXTRACT = String.raw`
import re, pathlib, json, sys
out = {"checks": set(), "findingTypes": set(), "materialTypes": set(), "ruleKeys": set()}
for root in [pathlib.Path(a) for a in sys.argv[1:]]:
    for p in root.rglob("*.py"):
        t = p.read_text(errors="ignore")
        out["checks"] |= set(re.findall(r'check\(\s*"([a-zA-Z0-9_]+)"', t))
        out["findingTypes"] |= set(re.findall(r'"findingType":\s*"([a-zA-Z0-9_]+)"', t))
        out["materialTypes"] |= set(re.findall(r'materialTypeCode["\s:=]+"([a-z0-9_]+)"', t))
    for p in root.rglob("*.yaml"):
        t = p.read_text(errors="ignore")
        out["materialTypes"] |= set(re.findall(r'materialTypeCode:\s*([a-z0-9_]+)', t))
        out["ruleKeys"] |= set(re.findall(r'ruleKey:\s*"?([a-z0-9][a-z0-9-]{4,})', t))
print(json.dumps({k: sorted(v) for k, v in out.items()}))
`
const data = JSON.parse(
  execFileSync(
    'python3',
    [
      '-c',
      EXTRACT,
      new URL('../../../../backend/libs', import.meta.url).pathname,
      new URL('../../../../backend/business_packs', import.meta.url).pathname
    ],
    {
      encoding: 'utf8'
    }
  )
)
// 连字符也算生码：`welder-qualification` 就是被只认下划线的正则漏掉的（2026-09-13）。
const rawish = (text: string) => /[a-z]{3,}[_-][a-z]/.test(text)

assert.ok(
  data.checks.length > 30,
  `应当扫到几十个检查码，实际 ${data.checks.length} 个——抽取正则可能失效了`
)
assert.deepEqual(
  data.checks.filter((code: string) => rawish(friendlyCheckCode(code))),
  [],
  '这些逐条检查码还没翻译，请补 auditLabels.checkCodeLabels'
)
assert.deepEqual(
  data.findingTypes.filter((code: string) => rawish(findingTypeLabel(code))),
  [],
  '这些发现类型还没翻译，请补 workbenchReviewPresentation.FINDING_TYPE_LABELS'
)
assert.deepEqual(
  data.materialTypes.filter((code: string) => rawish(friendlyMaterialType(code))),
  [],
  '这些资料类型代号还没翻译，请补 auditLabels.materialTypeLabels'
)
assert.ok(data.ruleKeys.length > 50, `应当扫到几十个规则键，实际 ${data.ruleKeys.length} 个`)
assert.deepEqual(
  data.ruleKeys.filter((code: string) => rawish(friendlyRuleCode(code))),
  [],
  '这些规则键还没翻译，请补 auditLabels.ruleCodeLabels'
)
void friendlyEvidenceIssue
void friendlyFieldLabel
void friendlyTechTerm
