import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname } from 'node:path'

// Execute the actual component handlers with deferred transports. This exercises
// response ordering rather than checking that a guard string exists in the source.
const require = createRequire(import.meta.url)
const esbuild = require(
  require.resolve('esbuild', {
    paths: [dirname(require.resolve('vite/package.json'))]
  })
)
const ts = require('typescript')
export const handler = (path: string, name: string, context: Record<string, unknown>) => {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8')
  const script = source.includes('<script')
    ? source.split(/<script[^>]*>/)[1].split('</script>')[0]
    : source
  const ast = ts.createSourceFile(path, script, ts.ScriptTarget.Latest, true)
  let declaration: any
  const visit = (node: any) => {
    if (ts.isVariableDeclaration(node) && node.name.getText(ast) === name) declaration = node
    ts.forEachChild(node, visit)
  }
  visit(ast)
  assert.ok(declaration, name)
  const code = esbuild.transformSync(`const ${declaration.getText(ast)}`, { loader: 'ts' }).code
  return new Function(...Object.keys(context), `${code}; return ${name}`)(...Object.values(context))
}
export const ref = <T>(value: T) => ({ value })
export const deferred = () => {
  let resolve!: (value: any) => void
  const promise = new Promise<any>((done) => {
    resolve = done
  })
  return { promise, resolve }
}
export const noop = () => {}
export const asyncNoop = async () => {}
