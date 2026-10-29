import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'
export default defineConfig({
  root: fileURLToPath(new URL('../..', import.meta.url)),
  plugins: [vue()],
  cacheDir: 'node_modules/.vite-admin-usability',
  optimizeDeps: { entries: ['e2e/admin-usability/index.html'] },
  css: {
    preprocessorOptions: {
      less: {
        additionalData: '@import "./src/styles/variables.module.less";',
        javascriptEnabled: true
      }
    }
  },
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
  server: { host: '127.0.0.1', port: 4491, strictPort: true }
})
