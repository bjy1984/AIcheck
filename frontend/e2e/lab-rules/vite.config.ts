import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'
export default defineConfig({
  root: fileURLToPath(new URL('../..', import.meta.url)),
  plugins: [vue()],
  define: { 'import.meta.env.VITE_AICHECK_WORKSTATIONS_ENABLED': '"true"' },
  resolve: { alias: [
    { find: /^@\/axios$/, replacement: fileURLToPath(new URL('./transport.ts', import.meta.url)) },
    { find: '@', replacement: fileURLToPath(new URL('../../src', import.meta.url)) }
  ] },
  server: { host: '127.0.0.1', port: 4393, strictPort: true, proxy: { '/api': 'http://127.0.0.1:4174' } }
})
