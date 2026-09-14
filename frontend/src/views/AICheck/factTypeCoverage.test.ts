/**
 * 事实类型守门：界面上每条事实的类型段都得有中文名。
 *
 * 2026-09-13 渲染级审计发现的第三个盲区。前两个是原因码和检查码，这个是**事实类型**：
 * r14/r15/r16-r18 的事实后端**根本不写 label**（见 `r15_facts.py` 的 `claimed_facts`），
 * 前端只能按 factId 的类型段（`r15-design_item-1` → `design_item`）查表。
 * 当时 22 个 snake_case 类型一个都没有，会把 `design_item`、`supervision_certificate`
 * 直接印到界面上——只是那些节点当时还没有可列的事实，所以没被看见。
 *
 * 和 `rawCodeCoverage` 一样从后端源码现抽，后端加一种记录而前端没词就红。
 */
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'

const EXTRACT = String.raw`
import re, pathlib, sys, json
kinds = set()
for root in [pathlib.Path(a) for a in sys.argv[1:]]:
    for p in root.rglob("*.py"):
        t = p.read_text(errors="ignore")
        # _extract_records(..., record_kind="quality_certificate")
        kinds |= set(re.findall(r'record_kind=["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']', t))
        # for fact_type, records, value_keys in (("design_item", items, ("a","b")), ...)
        kinds |= set(re.findall(r'\(\s*["\']([a-zA-Z][a-zA-Z0-9_-]*)["\']\s*,\s*[a-zA-Z_][a-zA-Z0-9_\[\]"\'\.]*\s*,\s*\(', t))
print(json.dumps(sorted(kinds)))
`

const kinds: string[] = JSON.parse(
  execFileSync(
    'python3',
    ['-c', EXTRACT, new URL('../../../../backend/libs', import.meta.url).pathname],
    { encoding: 'utf8' }
  )
)

/** 面板里的 FACT_TYPE_NAMES 是 <script setup> 里的字面量，直接从源码读键。 */
const panel = readFileSync(
  new URL('./components/WorkbenchAiReviewPanel.vue', import.meta.url).pathname,
  'utf8'
)
const block = panel.slice(
  panel.indexOf('const FACT_TYPE_NAMES'),
  panel.indexOf('const factDisplayLabel')
)
// 带连字符的键在源码里是带引号的（`'design-item': '设计元件'`），两种都要认
const named = new Set(
  [...block.matchAll(/^\s{2}'?([A-Za-z_][A-Za-z0-9_-]*)'?:/gm)].map((m) => m[1])
)

/**
 * 不是每个被抽出来的字符串都会当事实类型用（正则会扫到少量别的元组）。
 * 白名单只放**确认过不是事实类型**的，宁可多翻几个，也不放过真的。
 */
const NOT_FACT_TYPES = new Set([
  'evidence',
  'judgment',
  'conflicted',
  'fileName',
  'documentId',
  'documentNo',
  'certificateNo',
  'id',
  'value',
  'name',
  'code',
  'status',
  'result',
  'reason',
  'label',
  'source',
  'text',
  'title',
  'type',
  'key'
])

/** 和面板 factDisplayLabel 同一口径：先剥掉 `rNN-` 前缀再查表。 */
const lookupKey = (kind: string) => kind.replace(/^r\d+-/, '')

const missing = [
  ...new Set(kinds.map(lookupKey).filter((kind) => !NOT_FACT_TYPES.has(kind) && !named.has(kind)))
].sort()

assert.deepEqual(
  missing,
  [],
  `这些事实类型界面上会印原文，给它们加中文名（WorkbenchAiReviewPanel.FACT_TYPE_NAMES ` +
    `与 backend material_facts.FACT_TYPE_LABELS 两边都要加）：${missing.join('、')}`
)

console.log(`事实类型守门通过：后端抽出 ${kinds.length} 个，界面全部有中文名`)
