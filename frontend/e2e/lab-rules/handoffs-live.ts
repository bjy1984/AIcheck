import { createApp, h, ref } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import ReviewHandoffPanel from '../../src/views/AIReviewB/ReviewHandoffPanel.vue'
import EvidenceLocatorDialog from '../../src/views/AICheck/components/EvidenceLocatorDialog.vue'
import type { EvidenceLink } from '../../src/types/aicheck'
createApp({ setup() {
  const evidence = ref<EvidenceLink>()
  const visible = ref(false)
  return () => h('main', { style: 'max-width:900px;margin:16px auto' }, [
    h(ReviewHandoffPanel, { projectId: 'P-2026-HDCP-001', runId: 'RR-LAB-HANDOFF-TARGET',
      onEvidence: (value: EvidenceLink) => { evidence.value = value; visible.value = true } }),
    h(EvidenceLocatorDialog, { projectId: 'P-2026-HDCP-001', evidence: evidence.value,
      modelValue: visible.value, 'onUpdate:modelValue': value => { visible.value = value }, extractedFields: [] })
  ])
}}).use(ElementPlus).mount('#app')
