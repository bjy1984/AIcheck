/**
 * 建设方不该有一个名不副实、且与「归档包」重复的导出入口。
 *
 * 实操（2026-08-15，以 owner 登录）：点顶栏「导出状态摘要」，
 * 提示是「归档包导出任务已创建（0 项）」，请求打到 /archive/package。
 *
 * 查下来：这个按钮绑的就是 handleDownloadArchivePackage，
 * 而建设方的归档区里本来就有「归档包」按钮——两个入口做同一件事，
 * 其中一个还挂着错名字。前后端都没有「状态摘要导出」这个能力，
 * 这个名字从来只是个误会。
 *
 * 与其留一个骗人的入口，不如去掉；真要做状态摘要，那是另一个功能。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const sfc = readFileSync(fileURLToPath(new URL('./Workbench.vue', import.meta.url)), 'utf8')

// 按钮已移除
assert.ok(!/>\s*导出状态摘要\s*</.test(sfc), '「导出状态摘要」这个错名字还在')

// 归档包本身的能力要保留——去掉的是重复入口，不是功能
assert.ok(sfc.includes('handleDownloadArchivePackage'), '归档包导出被误删了')

console.log('Owner export button contract passed')
