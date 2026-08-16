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

/* 导出 0 项不许报成功。
 *
 * 这条当初只在注释里记了现象（「0 项」），没当成问题修——**记录不等于修复**。
 * 2026-08-16 复测：建设方点归档包/证据包，两次都弹绿色的
 * 「导出任务已创建（0 项 · sha256:…）」，而项目 69 个节点、已通过 0 个。
 * 建设方拿着那串 sha256 会以为交工资料齐了——**空包和齐全的包，
 * 在提示上长得一模一样**。
 */
assert.ok(/const notifyExportResult = /.test(sfc), '导出结果要按项数分流，不能一律报成功')
assert.ok(
  /if \(!itemCount\) \{[\s\S]{0,200}ElMessage\.warning/.test(sfc),
  '0 项要走警告，不能走 success'
)
assert.ok(/不能作为交付依据/.test(sfc), '空包要说清楚它不能当交付依据')
assert.ok(/还没有节点通过审查/.test(sfc), '归档包为空要说明常见原因')
assert.ok(/还没有已确认的证据/.test(sfc), '证据包为空要说明常见原因')

// 两个入口都要走这套判断，不能只改一个
const archiveAt = sfc.indexOf('const handleDownloadArchivePackage')
const evidenceAt = sfc.indexOf('const handleDownloadEvidencePackage')
const archiveBlock = sfc.slice(archiveAt, evidenceAt)
const evidenceBlock = sfc.slice(evidenceAt, evidenceAt + 1400)
assert.ok(/notifyExportResult\(/.test(archiveBlock), '归档包没走统一判断')
assert.ok(/notifyExportResult\(/.test(evidenceBlock), '证据包没走统一判断')
assert.ok(!/ElMessage\.success\(\s*`归档包导出任务已创建/.test(sfc), '还残留着无条件报成功的旧写法')

console.log('Owner export button contract passed')
