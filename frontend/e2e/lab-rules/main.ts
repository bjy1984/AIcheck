import { createApp, h } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import ProjectRuleEditor from '../../src/views/AIReviewB/ProjectRuleEditor.vue'
createApp({ render: () => h(ProjectRuleEditor, { projectId: 'P-2026-HDCP-001', nodeId: 24, reviewRunId: 'RR-BROWSER-TRIAL' }) }).use(ElementPlus).mount('#app')
