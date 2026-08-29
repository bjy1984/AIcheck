/**
 * 标准规范库与项目文件必须共用同一套 OCR 结构化详情。
 *
 * 旧的标准库抽屉只显示元数据、切片和推理引用；后端已经抽出的表格、印章、
 * 正文结构完全不可见，而且“查看原文”用 window.open 直开受保护 API，会丢失
 * Bearer Token。复用 FileDetailDialog 后，原文通过带鉴权的 Blob 请求加载，结构化
 * 数据也与监检工作台保持一致。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const view = readFileSync(
  fileURLToPath(new URL('./KnowledgeOverview.vue', import.meta.url)),
  'utf8'
)
const dialog = readFileSync(
  fileURLToPath(new URL('./components/FileDetailDialog.vue', import.meta.url)),
  'utf8'
)

assert.match(
  view,
  /import FileDetailDialog from '\.\/components\/FileDetailDialog\.vue'/,
  '标准规范库必须直接复用 FileDetailDialog'
)
assert.match(
  view,
  /<FileDetailDialog[\s\S]*v-model="fileDrawerVisible"[\s\S]*:detail="fileDetail"/,
  '标准文件详情必须把真实详情数据交给公共组件'
)
assert.doesNotMatch(
  view,
  /window\.open\(target\.url/,
  '受保护的标准原文不能再用 window.open 直开，否则不会携带 Bearer Token'
)
assert.match(view, /getDocumentOriginalBlobApi\(url\)/, '标准原文下载必须通过带鉴权的 Blob API')
assert.match(
  view,
  /fileDrawerVisible\.value = false[\s\S]*ElMessage\.error/,
  '详情加载失败时必须关闭空弹窗并显示错误原因'
)
assert.match(
  dialog,
  /officePreviewSupported/,
  '公共详情组件必须区分有项目上下文和无项目上下文的 Office 预览'
)
assert.match(dialog, /标准库 Office 原文暂不支持在线预览/, '标准库 Office 文件不能显示空白预览区')
