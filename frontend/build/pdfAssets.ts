import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import { readFileSync, readdirSync } from 'node:fs'
import type { Plugin } from 'vite'

/** Serve and emit the same versioned PDF assets; document data never goes to a CDN. */
export function pdfAssets(): Plugin {
  const require = createRequire(import.meta.url)
  const packagePath = require.resolve('pdfjs-dist/package.json')
  const root = dirname(packagePath)
  const version = JSON.parse(readFileSync(packagePath, 'utf8')).version as string
  const prefix = `pdf-assets/${version}/`
  const files = new Map<string, string>()
  for (const folder of ['cmaps', 'standard_fonts', 'wasm', 'iccs']) {
    for (const entry of readdirSync(join(root, folder), { withFileTypes: true })) {
      if (entry.isFile())
        files.set(`${prefix}${folder}/${entry.name}`, join(root, folder, entry.name))
    }
  }
  let base = '/'
  return {
    name: 'aicheck-pdf-assets',
    configResolved(config) {
      base = config.base
    },
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const path = (request.url || '').split('?')[0]
        const relative = path.startsWith(base) ? path.slice(base.length) : ''
        const file = files.get(relative)
        if (!file || !['GET', 'HEAD'].includes(request.method || '')) return next()
        response.setHeader(
          'Content-Type',
          file.endsWith('.wasm') ? 'application/wasm' : 'application/octet-stream'
        )
        response.setHeader('Cache-Control', 'public, max-age=31536000, immutable')
        response.end(request.method === 'HEAD' ? undefined : readFileSync(file))
      })
    },
    generateBundle() {
      for (const [fileName, file] of files)
        this.emitFile({ type: 'asset', fileName, source: readFileSync(file) })
    }
  }
}
