import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const adminOverviewSource = await readFile(
  new URL('../src/views/AICheck/AdminOverview.vue', import.meta.url),
  'utf8'
)

assert.doesNotMatch(
  adminOverviewSource,
  /subtitle: '管理项目清单、项目详情和立项向导'/,
  '项目管理页不应继续配置已移除的说明文字'
)
assert.match(
  adminOverviewSource,
  /<div v-if="adminPageSubtitle" class="page-subtitle">/,
  '空副标题不应渲染占位元素'
)

console.log('admin project subtitle regression check passed')
