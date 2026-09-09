import { createApp, h, ref } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import PipelineConflictDetails from '../../src/views/AIReviewB/PipelineConflictDetails.vue'
createApp({ setup() {
  const run = ref('RUN-A')
  return () => h('main', { style: 'max-width:700px;margin:16px auto' }, [
    h('button', { onClick: () => { run.value = run.value === 'RUN-A' ? 'RUN-B' : 'RUN-A' } }, '切换任务'),
    h(PipelineConflictDetails, { projectId: 'PROJECT', runId: run.value })])
}}).use(ElementPlus).mount('#app')
