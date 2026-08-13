import assert from 'node:assert/strict'
import { createMemoryHistory, createRouter } from 'vue-router'

import { didLoginNavigationComplete } from './loginNavigation'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/login', component: {} },
    { path: '/target', component: {} }
  ]
})

await router.push('/login')
router.beforeEach((to) => (to.path === '/target' ? false : true))

const failure = await router.push('/target')

assert.equal(didLoginNavigationComplete(failure, router.currentRoute.value.path), false)
assert.equal(router.currentRoute.value.path, '/login')
