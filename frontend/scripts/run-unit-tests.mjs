// 前端单元测试 runner。
//
// 仓库里的 *.test.ts 是用 node:assert 写的独立脚本，但 package.json 里既没有
// vitest 依赖也没有测试脚本——它们从未被执行过（P0 审计发现）。装 vitest 会牵动
// pnpm 版本闸（engines.pnpm >=11.7.0，本机 corepack 是 11.0.0），所以用 vite
// 自带的 esbuild 把每个测试打包成可执行 JS 再跑，零新增依赖。
//
// 产物写到测试文件同目录（部分测试用 import.meta.url 读相邻文件，如
// inspectionSubmittedDocuments.test.ts 读 Workbench.vue），跑完即删。
import { spawnSync } from 'node:child_process'
import { readdirSync, rmSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')

// esbuild 从 vite 的依赖树里解析（JS API，不是原生二进制），避免依赖顶层安装
const vitePackage = require.resolve('vite/package.json', { paths: [frontendRoot] })
const esbuild = require(require.resolve('esbuild', { paths: [dirname(vitePackage)] }))

const testFiles = []
const walk = (dir) => {
  for (const name of readdirSync(dir)) {
    if (name === 'node_modules' || name.startsWith('.')) continue
    const full = join(dir, name)
    if (statSync(full).isDirectory()) walk(full)
    else if (name.endsWith('.test.ts')) testFiles.push(full)
  }
}
walk(join(frontendRoot, 'src'))
testFiles.sort()

if (testFiles.length === 0) {
  console.error('未发现任何 *.test.ts —— runner 配置可能坏了，按失败处理。')
  process.exit(1)
}

let failed = 0
for (const file of testFiles) {
  const outfile = file.replace(/\.test\.ts$/, `.__unit-${process.pid}.mjs`)
  const label = file.slice(frontendRoot.length + 1)
  try {
    esbuild.buildSync({
      entryPoints: [file],
      bundle: true,
      platform: 'node',
      format: 'esm',
      outfile,
      logLevel: 'error'
    })
    const run = spawnSync(process.execPath, [outfile], { stdio: ['ignore', 'pipe', 'pipe'], encoding: 'utf-8' })
    if (run.status === 0) {
      console.log(`  通过  ${label}`)
    } else {
      failed += 1
      console.error(`  失败  ${label}`)
      const detail = `${run.stdout || ''}${run.stderr || ''}`.trim()
      if (detail) console.error(detail.split('\n').map((line) => `        ${line}`).join('\n'))
    }
  } finally {
    rmSync(outfile, { force: true })
  }
}

console.log(`\n前端单测：${testFiles.length - failed} 通过 / ${failed} 失败（共 ${testFiles.length} 个文件）`)
process.exit(failed === 0 ? 0 : 1)
