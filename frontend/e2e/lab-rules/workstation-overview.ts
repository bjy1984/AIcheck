import { createApp, h, ref, onBeforeUnmount } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import ReviewNodeOverview from '../../src/views/AIReviewB/components/ReviewNodeOverview.vue'
import ReviewWorkstationTools from '../../src/views/AIReviewB/ReviewWorkstationTools.vue'
import EvidenceLocatorDialog from '../../src/views/AICheck/components/EvidenceLocatorDialog.vue'
import { workstationNavigation } from '../../src/views/AIReviewB/workstationNavigation'
import type { ReviewBWorkspace } from '../../src/types/ai-review-b'
import type { EvidenceLink } from '../../src/types/aicheck'
import type { ReviewDocumentSelection } from '../../src/api/aicheck/reviewDocuments'
// This entry is a read-only prototype: component list requests use synthetic data;
// mutations cannot reach the API even when a local backend is running.
import transport from './transport'
const originalGet = transport.get
transport.get = config => config.responseType === 'blob' ? originalGet(config) : Promise.resolve({ code: 0, data: { items: [], total: 0, rules: [], atomicOptions: [] } })
transport.post = transport.patch = async () => { throw new Error('这是只读原型，不会保存数据。') }
const evidence = { id: 'EV-DEMO', projectId: 'PROJECT-A', documentId: 'DOC-DEMO', documentVersionId: 'DV-DEMO', fileName: '工艺规程.pdf', pageNo: 2, quotedText: '批准人签字栏需要核对。', objectType: 'documentVersion' } as EvidenceLink
const makeWorkspace = (): ReviewBWorkspace => ({ project: { id: 'PROJECT-A', etag: 'demo' }, node: { nodeId: 39 }, permissions: { canSubmitReviewOpinion: true, canManageEvidence: true }, activeReviewRun: { id: 'RUN-A', status: 'waiting_human_review', ruleVersion: '2026.09.lab.1', findingDrafts: [{ id: 'F1', title: '批准人签字需要核对', description: '当前引用中没有确认批准手续，请结合本单位质量体系和完整记录核对。', severity: 'high', evidenceRefs: [{ evidenceLinkId: evidence.id, fileName: evidence.fileName, pageNo: 2, quotedText: evidence.quotedText }] }, { id: 'F2', title: '文件编号已填写', checklistVerdict: '符合', groundingStatus: 'grounded', evidenceRefs: [{ evidenceLinkId: evidence.id }], description: '示例数据：编号字段已填写。' }] }, projectAnalysisResults: [], evidenceLinks: [evidence], evidenceReadiness: { supportingDocumentCount: 2, missingRequirements: [{ id: 'M1', name: '首次使用验证记录' }], blockingReasons: [] } } as unknown as ReviewBWorkspace)
createApp({ setup() {
  const wideNavigation = ref(window.innerWidth >= 768)
  const resizeNavigation = () => { wideNavigation.value = window.innerWidth >= 768 }
  window.addEventListener('resize', resizeNavigation)
  onBeforeUnmount(() => window.removeEventListener('resize', resizeNavigation))
  const node = ref(39)
  const previewVersion = ref('DV-DEMO')
  const inlinePreview = ref(true)
  const state = ref('normal'), station = ref('E'), pane = ref('overview'), selected = ref<ReviewDocumentSelection | null>(null), opened = ref(false)
  const toolsRef = ref<InstanceType<typeof ReviewWorkstationTools>>()
  const navigation = (section: string) => { if (['documents', 'rules', 'handoffs'].includes(section)) toolsRef.value?.focusTool(section as 'documents'); else pane.value = section }
  return () => {
    const workspace = state.value === 'empty' ? null : makeWorkspace()
    if (workspace && node.value !== 39) { workspace.node.nodeId = node.value; workspace.activeReviewRun = null; workspace.evidenceReadiness.missingRequirements = [] }
    if (workspace && state.value === 'readonly') workspace.permissions.canSubmitReviewOpinion = false
    return h('div', [h('header', { class: 'prototype-heading' }, [h('h1', 'AICheck · 先看待办，再看依据'), h('p', '可交互原型 · 合成资料；不保存人工结论，不发起模型任务'), h('div', { class: 'prototype-controls' }, ['normal', 'loading', 'error', 'empty', 'readonly', 'stale'].map((value, i) => h('button', { 'data-state': value, onClick: () => { state.value = value } }, ['正常', '载入中', '失败', '无资料', '只读', '资料已变更'][i])))]),
      h('div', { class: 'prototype-layout' }, [h('aside', [h('details', { open: wideNavigation.value, class: 'prototype-node-menu' }, [h('summary', '选择工位与节点'), h('label', { for: 'prototype-station' }, '按工位查看'), h('select', { id: 'prototype-station', value: station.value, onChange: event => { station.value = (event.target as HTMLSelectElement).value } }, workstationNavigation.map(item => h('option', { value: item.id }, `${item.id} · ${item.name}`))), h('nav', workstationNavigation.find(item => item.id === station.value)!.nodeIds.map(id => h('button', { onClick: () => { node.value = id; opened.value = false; selected.value = null; pane.value = 'overview' } }, `R${id} · ${id === 39 ? '工艺文件核对' : '节点入口'}`)))])]),
        h('main', [h('h2', node.value === 39 ? '39. 无损检测工艺文件' : `${node.value}. 节点资料与结果`), h(ReviewWorkstationTools, { ref: toolsRef, projectId: 'PROJECT-A', nodeId: node.value, runId: node.value === 39 ? 'RUN-A' : '', projectEtag: 'demo', selection: selected.value, documentsDisabled: state.value === 'readonly', onChange: value => { selected.value = value }, onEvidence: () => { opened.value = true } }), h(ReviewNodeOverview, { workspace, selection: selected.value, loading: state.value === 'loading', stale: state.value === 'stale', conflict: false, busy: false, canStart: state.value === 'normal', statusLabel: '等待人工确认', startLabel: '发起缺项预审', error: state.value === 'error' ? '这次加载失败，请重试；已有结果仍保留。' : '', onStart: () => { pane.value = 'start-preview' }, onNavigate: navigation, onEvidence: () => { opened.value = true } })]),
        h('aside', { class: 'prototype-context' }, [h('button', { id: 'preview-version', onClick: () => { previewVersion.value = 'DV-OTHER' } }, '切换引用版本（测试）'), h('button', { id: 'preview-mode', onClick: () => { inlinePreview.value = !inlinePreview.value } }, '切换原文显示方式（测试）'), opened.value ? h(EvidenceLocatorDialog, { inline: inlinePreview.value, modelValue: opened.value, projectId: 'PROJECT-A', evidence: { ...evidence, documentVersionId: previewVersion.value }, extractedFields: [], 'onUpdate:modelValue': value => { opened.value = value } }) : h('div', [h('h2', '原文与人工确认'), h('p', '点击问题中的引用，在这里查看原文。'), h('output', { id: 'prototype-navigation' }, ({ assistant: '已打开追问入口', human: '已打开人工确认入口', 'start-preview': '已选择发起审查；原型不会调用模型' } as Record<string, string>)[pane.value] || '请选择一条事项查看原文'), h('p', '人工结论使用现有工作台表单；本原型不写入数据。')])])])])
  }
}}).use(ElementPlus).mount('#app')
