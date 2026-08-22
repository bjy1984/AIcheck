import { defineConfig, devices } from '@playwright/test'
import { fileURLToPath } from 'node:url'

const baseURL = process.env.AICHECK_BASE_URL || 'http://127.0.0.1:4000'
const targetHostname = new URL(baseURL).hostname.toLowerCase().replace(/^\[|\]$/g, '')
const isLocalTarget = ['localhost', '127.0.0.1', '::1', '0.0.0.0'].includes(targetHostname)
if (!isLocalTarget && process.env.AICHECK_E2E_ALLOW_EXTERNAL_NON_PRODUCTION !== 'true') {
  throw new Error(
    'External Playwright targets are disabled by default. Set AICHECK_E2E_ALLOW_EXTERNAL_NON_PRODUCTION=true only for a verified non-production target.'
  )
}
const shouldStartServer = !process.env.AICHECK_BASE_URL
const viteMode = process.env.AICHECK_VITE_MODE || 'base'
const useProductionPreview = process.env.AICHECK_E2E_PREVIEW === 'true'
const acceptanceArtifactDir = fileURLToPath(
  new URL('../audit-reports/e2e-remediation-acceptance/', import.meta.url)
)

export default defineConfig({
  testDir: './e2e',
  timeout: 45_000,
  expect: {
    timeout: 10_000
  },
  fullyParallel: false,
  workers: 1,
  outputDir: `${acceptanceArtifactDir}/playwright-artifacts`,
  reporter: [
    ['list'],
    ['json', { outputFile: `${acceptanceArtifactDir}/playwright-report.json` }],
    ['html', { outputFolder: `${acceptanceArtifactDir}/html-report`, open: 'never' }]
  ],
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
