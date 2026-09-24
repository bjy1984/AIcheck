/**
 * 前端源码不得含预设初始密码。
 *
 * 2026-09-24：登录页的密码框曾写死 value: 'anyuekeji.123' 预填——那是后端的预设初始
 * 密码与示范账号的共用密码，打包进 JS 后任何打开登录页的人都能看到，还替人填好了。
 * 管理后台新增用户时同样不得内嵌它（留空由后端代填）。测试与 mock 在 src 之外，不受此限。
 */
import assert from 'node:assert/strict'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

const root = new URL('../../', import.meta.url).pathname
const offenders: string[] = []
const walk = (dir: string) => {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) walk(path)
    else if (/\.(vue|ts|tsx|js|mjs)$/.test(name) && !/\.test\.(ts|mjs)$|__unit-/.test(name)) {
      if (readFileSync(path, 'utf8').includes('anyuekeji.123'))
        offenders.push(path.slice(root.length))
    }
  }
}
walk(root)
assert.deepEqual(offenders, [], `这些前端源码含预设初始密码：${offenders.join(', ')}`)
