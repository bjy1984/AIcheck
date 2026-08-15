/**
 * 预签名上传地址绝不能带 Authorization。
 *
 * S3/MinIO 一看到 Authorization 头就改用它来鉴权、不再认 URL 上的预签名参数，
 * 而我们的 JWT 不是合法的 AWS 签名——直接回 400 Bad Request。
 *
 * 2026-08-15 实操验证的对照：
 *   服务器侧 curl 同一个预签名 URL（不带该头） → HTTP 200
 *   浏览器 PUT（带该头）                        → 400 Bad Request
 *
 * 只有走自家 API 的那条本地上传通道才需要 JWT。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const sfc = readFileSync(fileURLToPath(new URL('./Workbench.vue', import.meta.url)), 'utf8')

assert.ok(sfc.includes('const isOwnApiUploadTarget'), '没有区分自家 API 与对象存储')

// 判据要同时认相对路径和同源绝对地址
const fn = sfc.slice(
  sfc.indexOf('const isOwnApiUploadTarget'),
  sfc.indexOf('const uploadFileToSignedUrl')
)
assert.ok(fn.includes("startsWith('/api/')"), '相对路径的本地上传通道要认出来')
assert.ok(fn.includes('window.location.origin'), '同源绝对地址也要认出来')

// Authorization 必须挂在条件里，不能无条件带
const upload = sfc.slice(sfc.indexOf('const uploadFileToSignedUrl'))
const body = upload.slice(0, upload.indexOf('const showSubmissionDialogError'))
assert.ok(
  /isOwnApiUploadTarget\(target\.url\)\s*\n?\s*\?\s*\{\s*\[userStore\.getTokenKey/.test(body),
  'Authorization 还是无条件带上了'
)

console.log('Upload auth header contract passed')
