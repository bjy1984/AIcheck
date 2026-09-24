import { createApp, h, ref } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import { store } from '../../src/store'
import ImportantReview from '../../src/views/ImportantReview/ImportantReview.vue'
createApp({ setup() {
  const project = ref('P-IMPORTANT-TEST')
  const active = ref(true)
  return () => h('main', [h('header', [
    h('strong', '压力管道施工监督检验系统'),
    h('button', { onClick: () => { project.value = project.value === 'P-IMPORTANT-TEST' ? 'P-OTHER' : 'P-IMPORTANT-TEST' } }, '切换测试工程'),
    h('button', { onClick: () => { active.value = !active.value } }, '切换工作台视图'),
    h('strong', '重要节点审查')
  ]), h('div', { style: active.value ? '' : 'display:none' }, [h(ImportantReview, { projectId: project.value, active: active.value })])])
}}).use(store).use(ElementPlus).mount('#app')
