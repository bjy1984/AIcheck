import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./Workbench.vue', import.meta.url), 'utf8')

assert.match(source, /import AutoReviewControl from '.\/components\/AutoReviewControl\.vue'/)
assert.match(
  source,
  /<AutoReviewControl[\s\S]*v-if="role === 'inspection'"[\s\S]*:project-id="activeProjectId"/
)
const segmentedEnd = source.indexOf('</div>', source.indexOf('class="view-segmented"'))
const autoReviewPosition = source.indexOf('<AutoReviewControl')
const registrationPosition = source.indexOf('handleOpenProjectRegistration', autoReviewPosition)
assert.ok(autoReviewPosition > segmentedEnd, '自动审查按钮应位于视图切换控件之后')
assert.ok(registrationPosition > autoReviewPosition, '自动审查按钮应位于注册入口之前')
