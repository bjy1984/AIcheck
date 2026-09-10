import { createApp, h, ref } from 'vue'
import 'element-plus/dist/index.css'
import WorkbenchAiReviewPanel from '../../src/views/AICheck/components/WorkbenchAiReviewPanel.vue'
import { buildWorkbenchAiPresentation } from '../../src/views/AICheck/workbenchReviewPresentation'
createApp({ setup() {
  const state = ref('empty')
  return () => {
    const presentation = { ...buildWorkbenchAiPresentation(null) }
    if (state.value !== 'empty') presentation.runId = 'R'
    if (state.value === 'running') { presentation.running = true; presentation.statusLabel = 'AI 正在分析' }
    if (state.value === 'failed') { presentation.errorMessage = '本次执行失败，请重试'; presentation.statusLabel = '执行失败' }
    if (state.value === 'complete') { presentation.deterministicResult = 'evidence_insufficient'; presentation.statusLabel = '执行完成' }
    return h('main', { style: 'max-width: 1000px; margin: 24px' }, [
      h('p', '原 AI 结果面板 · 合成状态测试'),
      ...['empty', 'running', 'failed', 'complete'].map(value => h('button', { onClick: () => { state.value = value } }, value)),
      h(WorkbenchAiReviewPanel, { presentation, history: [], canAct: true })
    ])
  }
} }).mount('#app')
