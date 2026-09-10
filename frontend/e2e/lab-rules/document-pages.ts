import { createApp, h, ref } from 'vue'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import OcrDocumentPages from '../../src/views/AICheck/components/OcrDocumentPages.vue'
const rows = Array.from({ length: 9 }, (_, i) => ({ pageNo: i + 1, identified: i === 0,
  label: i === 0 ? '射线检测报告' : i === 2 ? '有多种资料标题，需要确认' : '还没确认这页是什么资料' }))
createApp({ setup() {
  const active = ref<number>()
  return () => h('main', { style: 'max-width: 640px; padding: 24px; font-family: sans-serif' }, [
    h('p', '原文件详情元件 · 合成资料验收'),
    h(OcrDocumentPages, { rows, activePage: active.value, onLocate: (page: number) => { active.value = page } }),
    h('output', active.value ? `定位到第 ${active.value} 页` : '尚未定位')
  ])
} }).mount('#app')
