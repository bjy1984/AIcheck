import { createApp, h, ref } from 'vue'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import ReviewApprovalChecks from '../../src/views/AIReviewB/components/ReviewApprovalChecks.vue'
import type { EvidenceLink } from '../../src/types/aicheck'
const evidence = { id: 'E1', documentVersionId: 'V1', pageNo: 3, quotedText: '采用早于批复' } as EvidenceLink
createApp({ setup() {
  const opened = ref('尚未定位')
  return () => h('main', { style: 'max-width: 850px; padding: 24px; font-family: sans-serif' }, [
    h('p', '原节点结果元件 · 合成资料验收'),
    h(ReviewApprovalChecks, { items: [
      { code: 'r11_signature_编制', result: 'passed' },
      { code: 'r11_owner_approval_before_use', result: 'failed', usageId: 'U1', approvedAt: '2026-09-03', startedAt: '2026-09-02', evidenceRefs: [evidence, { evidenceLinkId: 'E1', documentVersionId: 'OTHER', pageNo: 3 }, {}] },
      { code: 'r11_usage_inventory', result: 'evidence_insufficient', evidenceRefs: [{ documentVersionId: 'UNKNOWN', pageNo: 9 }] }
    ], evidenceLinks: [evidence], onEvidence: (link: EvidenceLink) => { opened.value = `定位 ${link.documentVersionId} 第 ${link.pageNo} 页` } }),
    h('output', opened.value)
  ])
} }).mount('#app')
