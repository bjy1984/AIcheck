import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./Workbench.vue', import.meta.url), 'utf-8')

assert.match(
  source,
  /import ProjectAnalysisControl from '.\/components\/ProjectAnalysisControl\.vue'/
)
assert.match(
  source,
  /<ProjectAnalysisControl[\s\S]*v-if="role === 'inspection' \|\| role === 'admin'"[\s\S]*:project-id="activeProjectId"/
)
const autoReviewPosition = source.indexOf('<AutoReviewControl')
const projectAnalysisPosition = source.indexOf('<ProjectAnalysisControl')
assert.ok(projectAnalysisPosition > autoReviewPosition, '一键分析按钮应位于自动审查按钮之后')
