import { createApp, h, ref } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import FileDetailDialog from '../../src/views/AICheck/components/FileDetailDialog.vue'
import type { DocumentDetailPayload } from '../../src/api/aicheck'
const detail = {
  document: { id: 'D-RT', projectId: 'P-TEST', fileName: '金辉焊接工艺评定20.pdf', currentVersionId: 'V-RT' },
  currentVersion: { id: 'V-RT', documentId: 'D-RT', versionNo: 1 },
  versions: [], bindings: [], extractedFields: [], evidenceLinks: [],
  preview: { url: '/fixtures/real-rt.pdf', previewType: 'pdf', readonly: true },
  download: { url: '/fixtures/real-rt.pdf' },
  ocrStructured: { available: true, documentVersionId: 'V-RT', layoutBlocks: [], tables: [], seals: [], pageCount: 16, truncated: false,
    pageClassifications: [{ pageNo: 9, status: 'identified', documentKind: 'welding_record' },
      { pageNo: 10, status: 'identified', documentKind: 'rt_report' }, { pageNo: 11, status: 'identified', documentKind: 'rt_report' }] }
} as unknown as DocumentDetailPayload
createApp({ setup() {
  const current = ref(detail)
  return () => h('div', [h('button', { id: 'stale', style: 'position:fixed;z-index:99999;top:0', onClick: () => {
    current.value = { ...detail, ocrStructured: { ...detail.ocrStructured!, documentVersionId: 'OLD' } }
  } }, '注入旧版分类（测试）'), h(FileDetailDialog, { modelValue: true, loading: false, detail: current.value })])
} }).use(ElementPlus).mount('#app')
