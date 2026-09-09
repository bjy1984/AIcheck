import { createApp, h, ref } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import ReviewWorkstationTools from '../../src/views/AIReviewB/ReviewWorkstationTools.vue'
import type { ReviewDocumentSelection } from '../../src/api/aicheck/reviewDocuments'
createApp({ setup() {
  const project = ref('PROJECT-A')
  const node = ref(35)
  const run = ref('RUN-A')
  const disabled = ref(false)
  const selection = ref<ReviewDocumentSelection | null>(null)
  return () => h('main', { style: 'max-width:960px;margin:24px auto;padding:0 16px;font-family:system-ui;color:var(--el-text-color-primary)' }, [
    h('h1', { style: 'font-size:25px' }, `${node.value}. 无损检测节点`),
    h('p', '节点工作台 · 资料与审查协作组件验收'),
    h(ReviewWorkstationTools, { projectId: project.value, nodeId: node.value, runId: run.value, documentsDisabled: disabled.value,
      selection: selection.value, onChange: value => { selection.value = value } }),
    h('div', { style: 'display:flex;gap:8px;flex-wrap:wrap;margin-top:24px' }, [
      h('button', { id: 'scope', onClick: () => { project.value = 'PROJECT-B'; node.value = 39; run.value = 'RUN-B'; selection.value = null } }, '切换工程 / 节点'),
      h('button', { id: 'busy', onClick: () => { disabled.value = !disabled.value } }, '切换资料权限'),
      h('button', { id: 'run', onClick: () => { run.value = run.value ? '' : 'RUN-B' } }, '切换任务状态')])])
}}).use(ElementPlus).mount('#app')
