/**
 * 登录页不许有「点了没反应」。
 *
 * ## 线上实测（2026-08-16，多角色审计时撞上）
 *
 * 用 owner 登录：用户名和密码都填好、界面上没有任何红字提示，
 * 点「登录」两次 + 回车一次，`/api/auth/login` **一次都没发出去**，
 * 控制台也是干净的。而后端那边 owner 明明能登（code=0、拿到 token）。
 *
 * 原因是 signIn 里有三条静默 return——校验不过、拿不到表单实例、
 * 接口没返回，三条都是直接 `return`，不发请求也不提示。
 *
 * **登录页是整个系统的第一道门**，在这里「点了没反应」代价最大：
 * 用户没有任何线索可循，只能反复点，然后认定系统坏了。
 * 页面本来就有 errorMessage 提示框，只是那三条路径一个字都不往里写。
 *
 * ## 判据
 *
 * 每条提前退出都要先写 errorMessage 再 return。
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const sfc = readFileSync(
  fileURLToPath(new URL('./components/LoginForm.vue', import.meta.url)),
  'utf8'
)

const start = sfc.indexOf('const signIn = async')
assert.ok(start > 0, '找不到登录提交函数')
const fn = sfc.slice(start, sfc.indexOf('// 获取角色信息'))

// 逐条退出路径都要有话说
assert.ok(/正在登录，请稍候/.test(fn), '重复点击要说明正在处理，不能默默吞掉')
assert.ok(/登录表单未就绪/.test(fn), '拿不到表单实例要说清楚')
assert.ok(/请填写用户名和密码/.test(fn), '校验不过要说哪里不对')
assert.ok(/登录没有收到服务端响应/.test(fn), '接口没返回要提示，不能静默')

/* 不许再出现「静默失败的 return」。
 *
 * 判据要精确：**失败路径**的 return 前面必须写过提示；而正常流程的收尾
 * return（例如跳去改密码页之后那句）不该被算进来——它前面刚
 * `await push(...)` 并且失败时会 throw，用户已经被带走了。
 * 判据写宽了会逼人给正常路径也加一句假提示，那是把测试当对手糊弄。
 */
const lines = fn.split('\n')
lines.forEach((line, index) => {
  if (!/^\s*return\s*$/.test(line)) return
  const context = lines.slice(Math.max(0, index - 5), index).join('\n')
  // 正常收尾：前面刚做过跳转（push / navigated），不是失败退出
  if (/await push\(|navigated = /.test(context)) return
  assert.ok(
    /errorMessage\.value = /.test(context),
    `第 ${index + 1} 行是静默 return，用户会看到「点了没反应」：\n${context}`
  )
})
