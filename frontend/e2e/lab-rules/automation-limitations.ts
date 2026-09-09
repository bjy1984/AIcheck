import { createApp, h } from 'vue'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import ReviewAutomationLimitations from '../../src/views/AIReviewB/components/ReviewAutomationLimitations.vue'
createApp({ render: () => h('main', { style: 'max-width: 760px; padding: 24px; font-family: sans-serif' }, [
  h('p', '原结果元件验收 · 合成数据'),
  h(ReviewAutomationLimitations, { items: ['technical_parameters', 'design_requirements', 'report_results'].map(code => ({ atomicCheckId: 'AC-R40-01', code })) })
]) }).mount('#app')
