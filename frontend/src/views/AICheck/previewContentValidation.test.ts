import assert from 'node:assert/strict'
import { previewContentError } from './components/previewContentValidation'
import { deferred, handler, ref } from './workflowTestHarness'

// Transport fixtures reproduce HTTP 200 responses interpreted as Blob by Axios.
const responseBlob = async (body: string, type: string) =>
  new Response(body, { status: 200, headers: { 'Content-Type': type } }).blob()
const fixtures = [
  { body: '', type: 'application/pdf', error: '空文件' },
  {
    body: '<!doctype html><html><body>Sign in</body></html>',
    type: 'application/pdf',
    error: '网页'
  },
  { body: '{"code":401,"message":"Unauthorized"}', type: 'application/json', error: '登录校验' },
  {
    body: '{"code":"NOT_FOUND","message":"原文不存在"}',
    type: 'application/octet-stream',
    error: 'NOT_FOUND'
  },
  { body: 'upstream unavailable', type: 'application/pdf', error: '不是可识别的 PDF' }
]
for (const fixture of fixtures) {
  const blob = await responseBlob(fixture.body, fixture.type)
  assert.ok((await previewContentError(blob, 'pdf')).includes(fixture.error))
}
const pdf = await responseBlob(
  '%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF',
  'application/pdf'
)
assert.equal(await previewContentError(pdf, 'pdf'), '')
assert.equal(await previewContentError(new Blob(['%PDF-1.7\n%%EOF']), 'pdf'), '')
assert.match(await previewContentError(undefined, 'pdf'), /没有返回/)

// Exercise the actual dialog handler: rejected bytes never enter the iframe URL.
const createState = (transport: (url: string) => Promise<unknown>) => ({
  previewLoadToken: 0,
  revokePreviewObjectUrl: () => {},
  previewOriginalError: ref(''),
  previewLoadingOriginal: ref(false),
  preview: ref({ url: '/api/original' }),
  previewRequiresBlob: ref(true),
  previewIsPdf: ref(true),
  previewObjectUrl: ref(''),
  previewContentError,
  getDocumentOriginalBlobApi: transport,
  getAicheckErrorMessage: () => '',
  URL: { createObjectURL: () => 'blob:validated-original' }
})
for (const fixture of fixtures) {
  const state = createState(async () => ({ data: await responseBlob(fixture.body, fixture.type) }))
  await handler('./components/FileDetailDialog.vue', 'loadPreviewOriginal', state)()
  assert.ok(state.previewOriginalError.value.includes(fixture.error))
  assert.equal(state.previewObjectUrl.value, '')
  assert.equal(state.previewLoadingOriginal.value, false)
}
const oldResponse = deferred()
let request = 0
const state = createState(async () => (++request === 1 ? oldResponse.promise : { data: pdf }))
const load = handler('./components/FileDetailDialog.vue', 'loadPreviewOriginal', state)
const oldLoad = load()
await load()
oldResponse.resolve({ data: await responseBlob('', 'application/pdf') })
await oldLoad
assert.equal(state.previewObjectUrl.value, 'blob:validated-original')
assert.equal(state.previewOriginalError.value, '')
assert.equal(state.previewLoadingOriginal.value, false)

console.log('Preview response validation and stale-error isolation passed')
