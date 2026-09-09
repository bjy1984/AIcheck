import { createApp, h, ref } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import WorkstationProjectTree from '../../src/views/AIReviewB/components/WorkstationProjectTree.vue'
import type { ProjectTreePayload } from '../../src/api/aicheck'

// Component acceptance only: synthetic projects, controlled HTTP responses, no model or mutations.
createApp({ setup() {
  const project = ref('A')
  const station = ref('')
  const status = ref('')
  const mounted = ref(true)
  return () => h('main', { style: 'width: 480px; padding: 24px' }, [
    h('h1', '原工位元件 · 工程切换验收'),
    h('p', '合成资料；此页面不发起审查或保存数据。'),
    ...['A', 'B'].map(id => h('button', { onClick: () => { project.value = id } }, `工程 ${id}`)),
    h('button', { onClick: () => { mounted.value = !mounted.value } }, '切换挂载'),
    h('output', { id: 'project' }, project.value),
    mounted.value ? h(WorkstationProjectTree, {
      groups: [{ groupName: `工程 ${project.value}`, nodes: [35, 36].map(nodeId => ({
        projectId: project.value, nodeId, name: `${project.value} 节点 ${nodeId}`,
        status: '待审查', inspectionType: 'B', fileCount: 0
      })) }] as ProjectTreePayload['groups'],
      enabled: true, activeNodeId: 35, idPrefix: 'race', modelValue: station.value,
      status: status.value, 'onUpdate:modelValue': value => { station.value = value },
      'onUpdate:status': value => { status.value = value }
    }) : null
  ])
}}).use(ElementPlus).mount('#app')
