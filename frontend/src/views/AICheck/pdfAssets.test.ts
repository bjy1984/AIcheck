import assert from 'node:assert/strict'
import { pdfAssets } from '../../../build/pdfAssets'

const plugin = pdfAssets()
const emitted: Array<{ fileName: string; source: Uint8Array }> = []
const generate = plugin.generateBundle as (this: {
  emitFile(asset: (typeof emitted)[number]): void
}) => void
generate.call({ emitFile: (asset) => emitted.push(asset) })
for (const folder of ['cmaps', 'standard_fonts', 'wasm', 'iccs'])
  assert.ok(
    emitted.some((asset) => asset.fileName.includes(`/${folder}/`) && asset.source.length > 0)
  )

const configure = plugin.configResolved as (config: { base: string }) => void
configure({ base: '/lab/' })
type Handler = (
  request: { url: string; method: string },
  response: { setHeader(key: string, value: string): void; end(body?: unknown): void },
  next: () => void
) => void
let handler: Handler | undefined
const setup = plugin.configureServer as (server: {
  middlewares: { use(value: Handler): void }
}) => void
setup({
  middlewares: {
    use: (value) => {
      handler = value
    }
  }
})
assert.ok(handler)
const asset = emitted.find((item) => item.fileName.endsWith('.bcmap'))!
let body: unknown
let missed = false
handler(
  { url: `/lab/${asset.fileName}`, method: 'GET' },
  {
    setHeader() {},
    end(value) {
      body = value
    }
  },
  () => {
    missed = true
  }
)
assert.equal(missed, false)
assert.deepEqual(body, asset.source, 'development and built CMap assets must be identical')
for (const url of [
  '/lab/pdf-assets/../../package.json',
  `/lab/${asset.fileName}/extra`,
  `/${asset.fileName}`
]) {
  missed = false
  handler(
    { url, method: 'GET' },
    {
      setHeader() {},
      end() {
        assert.fail('must not serve unknown paths')
      }
    },
    () => {
      missed = true
    }
  )
  assert.equal(missed, true)
}
