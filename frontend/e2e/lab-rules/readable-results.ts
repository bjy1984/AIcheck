import { createApp, h, ref } from 'vue'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import ReviewResultCard from '../../src/views/AIReviewB/components/ReviewResultCard.vue'
import ReviewReadableAnalysis from '../../src/views/AIReviewB/components/ReviewReadableAnalysis.vue'
import type { EvidenceLink } from '../../src/types/aicheck'
const evidence = { id: 'EV-1', documentId: 'DOC-1', documentVersionId: 'DV-1', pageNo: 2, quotedText: '批准人签字栏为空。' } as EvidenceLink
createApp({ setup() {
  const status = ref('insufficient_evidence')
  const count = ref(3)
  const opened = ref('')
  return () => h('main', { style: 'max-width:900px;margin:24px auto;padding:0 12px;font-family:system-ui;color:var(--el-text-color-primary)' }, [
    h(ReviewResultCard, { result: { reviewRunId: 'RUN-READABLE-1', projectAnalysisRunId: 'PA-1', reviewResult: status.value, findingDrafts: Array.from({ length: count.value }, (_, i) => ({
      id: `F-${i}`, title: ['批准人签字需要核对', '检测比例与委托单不一致', '首次使用的验证记录还未提供'][i] || `需要核对的事项 ${i + 1}`,
      severity: i === 0 ? 'high' : 'medium', suggestedAction: i === 1 ? 'request_correction' : 'human_confirm',
      description: '请确认提供的文件是否为已批准版本。\n\n' + '当前页未见批准人签字，需结合完整文件和批准记录核对。'.repeat(40),
      evidenceRefs: i === 0 ? [{ evidenceLinkId: 'EV-1', fileName: '无损检测工艺规程.pdf', pageNo: 2, quotedText: evidence.quotedText }, { evidenceLinkId: 'MISSING', fileName: '待核对文件.pdf', pageNo: 3, quotedText: '未能定位的引用仍保留。' }] : [],
      ruleRefs: [{ text: '示例规则：文件应按本单位质量体系要求批准。' }]
    })) }, evidenceLinks: [evidence], onOpenEvidence: value => { opened.value = `${value.documentVersionId}:${value.pageNo}` } }),
    h('output', { id: 'opened' }, opened.value),
    h(ReviewReadableAnalysis, { content: '原文全文保留。'.repeat(150), compact: true }),
    h(ReviewReadableAnalysis, { content: '这是普通问答的完整回答。'.repeat(80), compact: false }),
    h('div', { style: 'margin-top:24px' }, [h('select', { id: 'status', value: status.value, onChange: event => { status.value = (event.target as HTMLSelectElement).value } }, ['insufficient_evidence', 'supported', 'partially_supported', 'conflict', 'mismatch', 'new_status'].map(value => h('option', value))), h('button', { id: 'empty', onClick: () => { count.value = 0 } }, '无发现'), h('button', { id: 'many', onClick: () => { count.value = 12 } }, '12 项')])
  ])
}}).mount('#app')
