import { createApp, h } from 'vue'
import { createRouter, createWebHashHistory, RouterView } from 'vue-router'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import FdeConsole from '../../src/views/AICheck/FdeConsole.vue'
import FdeBlindReview from '../../src/views/AICheck/FdeBlindReview.vue'
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/fde/:page', component: FdeConsole },
    { path: '/fde-blind-review', component: FdeBlindReview },
    { path: '/:pathMatch(.*)*', redirect: '/fde/evaluation' }
  ]
})
const app = createApp({ render: () => h(RouterView) })
app.use(createPinia()).use(router).use(ElementPlus)
router.isReady().then(() => app.mount('#app'))
