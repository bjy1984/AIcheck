import assert from 'node:assert/strict'

import { normalizeMineruMarkdownForDisplay } from './mineruMarkdownDisplay'

const evidence = {
  id: 'EV-001',
  documentVersionId: 'DV-001',
  pageNo: 3,
  bbox: [10, 20, 300, 180],
  quotedText: `# 特种设备生产许可证
<table><tr><td>许可项目</td><td>许可子项目</td></tr><tr><td>压力管道设计</td><td>工业管道(GC1)</td></tr></table>
![](images/license.jpg)
<script>alert('xss')</script>`
}
const anchorBefore = JSON.stringify({
  id: evidence.id,
  documentVersionId: evidence.documentVersionId,
  pageNo: evidence.pageNo,
  bbox: evidence.bbox
})

const displayed = normalizeMineruMarkdownForDisplay(evidence.quotedText)

assert.match(displayed, /^# 特种设备生产许可证/m)
assert.match(displayed, /\| 许可项目 \| 许可子项目 \|/)
assert.match(displayed, /\| --- \| --- \|/)
assert.match(displayed, /\| 压力管道设计 \| 工业管道\(GC1\) \|/)
assert.ok(!displayed.includes('<table>'), 'MinerU HTML表格标签不应原样显示')
assert.ok(!displayed.includes('<script>'), '不可信HTML不得进入展示结果')
assert.ok(!displayed.includes('images/license.jpg'), '不可访问的MinerU相对图片路径不应显示')
assert.match(displayed, /OCR图片片段请查看左侧原文预览/)
assert.equal(
  JSON.stringify({
    id: evidence.id,
    documentVersionId: evidence.documentVersionId,
    pageNo: evidence.pageNo,
    bbox: evidence.bbox
  }),
  anchorBefore,
  '显示转换不得修改证据ID、版本、页码或bbox'
)
