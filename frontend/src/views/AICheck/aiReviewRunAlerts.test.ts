import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const workbenchSource = readFileSync(new URL('./Workbench.vue', import.meta.url), 'utf8')
const alertsSource = readFileSync(
  new URL('./components/AiReviewRunAlerts.vue', import.meta.url),
  'utf8'
)

assert.match(
  workbenchSource,
  /import AiReviewRunAlerts from '.\/components\/AiReviewRunAlerts\.vue'/
)
assert.match(workbenchSource, /<AiReviewRunAlerts/)
assert.match(workbenchSource, /:evidence-budget="aiEvidenceBudget"/)
assert.match(workbenchSource, /:failure="aiRunFailure"/)
assert.match(workbenchSource, /:failure-kind-label="aiFailureKindLabel"/)
assert.match(workbenchSource, /@retry="handleAiRecheck"/)
assert.doesNotMatch(workbenchSource, /\.ai-truncation\s*\{/)
assert.doesNotMatch(workbenchSource, /\.ai-failure\s*\{/)

assert.match(alertsSource, /defineEmits<\{\s*retry: \[\]\s*\}>/)
assert.match(alertsSource, /v-if="evidenceBudget\?\.truncated"/)
assert.match(alertsSource, /v-if="failure"/)
assert.match(alertsSource, /emit\('retry'\)/)

console.log('AI review run alerts component contract passed')
