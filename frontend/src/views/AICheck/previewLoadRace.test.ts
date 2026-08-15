/**
 * 连着看两份资料时，原文预览不能停在「加载中」不动。
 *
 * 线上实测（2026-08-16，施工方文件详情）：
 *   接口 200、字节 678 KB、objectURL 也建得出来，界面就是不显示，
 *   停在「原文预览加载中」——不转圈、不报错、也没有内容。
 *
 * 成因是两次取字节重叠：loadPreviewOriginal 开头会 revoke 掉已有地址，
 * 而先发的那次后返回，就把后发的那次覆盖或清空。
 *
 * **既不成功也不失败的状态比失败更难查**：它看起来像还没加载完，
 * 人会一直等下去，不会去点重试、也不会来报错。
 *
 * 另一条：后端未登录时回的是 HTTP 200 + {"code":401}，responseType=blob
 * 会把这段 JSON 原样包成 Blob；塞进 iframe 就是一片空白。类型对不上要直说。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const sfc = readFileSync(
  fileURLToPath(new URL('./components/FileDetailDialog.vue', import.meta.url)),
  'utf8'
)

const start = sfc.indexOf('let previewLoadToken')
assert.ok(start > 0, '原文预览没有做代次保护，快速切换文件会停在加载中')

const fn = sfc.slice(start, sfc.indexOf('const handlePreviewImageError'))

// 代次要在最前面取，且在 await 之后逐个校验
const take = fn.indexOf('const token = ++previewLoadToken')
assert.ok(take > 0, '进函数就要占一个代次')
const awaitAt = fn.indexOf('await getDocumentOriginalBlobApi')
assert.ok(take < awaitAt, '代次要在发请求前取')
assert.ok(
  fn.indexOf('if (token !== previewLoadToken) return', awaitAt) > awaitAt,
  '请求返回后要先比代次，过期的结果必须丢弃'
)

// catch 里同样要比——旧请求的失败不该盖掉新请求的进行中状态
const catchAt = fn.indexOf('} catch (error) {')
assert.ok(
  fn.indexOf('if (token !== previewLoadToken) return', catchAt) > catchAt,
  '过期请求的异常不该写进当前状态'
)

// finally 里只有当前代次才允许收起 loading
assert.ok(
  /if \(token === previewLoadToken\) previewLoadingOriginal\.value = false/.test(fn),
  '过期请求不该把当前的加载状态收起来'
)

// 错误文案不能为空字符串——空字符串会让告警框不渲染，界面又回到「什么都没有」
assert.ok(
  /getAicheckErrorMessage\(error, ''\) \|\|/.test(fn),
  '错误文案要兜底，否则空文案会让告警框不显示'
)

// 200 + code 401 伪装成 Blob 的情况要识别出来
assert.ok(/instanceof Blob/.test(fn), '要校验拿回来的确实是 Blob')
assert.ok(/includes\('json'\)/.test(fn), 'JSON 伪装成原文时要给出可读的提示')
