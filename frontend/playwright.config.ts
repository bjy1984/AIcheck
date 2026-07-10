import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.AICHECK_BASE_URL || 'http://127.0.0.1:4000'
const shouldStartServer = !process.env.AICHECK_BASE_URL
const viteMode = process.env.AICHECK_VITE_MODE || 'base'
const useProductionPreview = process.env.AICHECK_E2E_PREVIEW === 'true'

export default defineConfig({
  testDir: './e2e',
  timeout: 45_000,
  expect: {
    timeout: 10_000
  },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    reducedMotion: 'reduce'
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] }
    }
  ],
  ...(shouldStartServer
    ? {
        webServer: {
          command: useProductionPreview
            ? 'pnpm vite preview --mode pro --host 127.0.0.1 --port 4000'
            : `pnpm vite --mode ${viteMode} --host 127.0.0.1 --port 4000`,
          url: baseURL,
          reuseExistingServer: true,
          timeout: 120_000
        }
      }
    : {})
})
