import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import jsx from '@vitejs/plugin-vue-jsx'
import { fileURLToPath } from 'node:url'
export default defineConfig({
  root: fileURLToPath(new URL('../..', import.meta.url)),
  plugins: [vue(), jsx()],
  optimizeDeps: { entries: ['e2e/uiux-priority/index.html'] },
  define: { 'import.meta.env.VITE_AICHECK_WORKSTATIONS_ENABLED': '"true"' },
  resolve: {
    alias: [
      {
        find: /^@\/axios$/,
        replacement: fileURLToPath(new URL('./transport.ts', import.meta.url))
      },
      {
        find: /^@\/store\/modules\/user$/,
        replacement: fileURLToPath(new URL('./user.ts', import.meta.url))
      },
      { find: '@', replacement: fileURLToPath(new URL('../../src', import.meta.url)) }
    ]
  },
  css: {
    preprocessorOptions: {
      less: {
        additionalData: '@import "./src/styles/variables.module.less";',
        javascriptEnabled: true
      }
    }
  },
  server: { host: '127.0.0.1', port: 4395, strictPort: true }
})
