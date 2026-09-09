import { createApp, h, ref } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import ReviewDocumentPicker from '../../src/views/AIReviewB/ReviewDocumentPicker.vue'
import type { ReviewDocumentSelection } from '../../src/api/aicheck/reviewDocuments'
createApp({ setup() {
  const selection = ref<ReviewDocumentSelection | null>(null)
  const node = ref(24)
  return () => h('main', [
    h(ReviewDocumentPicker, { projectId: 'P-2026-HDCP-001', nodeId: node.value, selection: selection.value,
      onChange: (value) => { selection.value = value } }),
    h('button', { onClick: () => { node.value++; selection.value = null } }, '切换测试节点'),
    h('pre', { 'data-testid': 'selection', style: 'white-space:pre-wrap;overflow-wrap:anywhere' }, JSON.stringify(selection.value))])
}}).use(ElementPlus).mount('#app')
