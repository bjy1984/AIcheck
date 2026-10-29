import { createApp, h } from 'vue'
import { createRouter, createWebHashHistory, RouterView } from 'vue-router'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import AdminOverview from '../../src/views/AICheck/AdminOverview.vue'
const router = createRouter({
  history: createWebHashHistory(),
  routes: [{ path: '/:pathMatch(.*)*', component: AdminOverview }]
})
createApp({ render: () => h(RouterView) })
  .use(router)
  .use(ElementPlus)
  .mount('#app')
