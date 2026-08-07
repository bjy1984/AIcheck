#!/usr/bin/env node
/**
 * Preflight for `pnpm run dev:live`.
 * Vite live mode only starts the frontend; FastAPI must already listen on :8000.
 */

const backendPort = process.env.AICHECK_DEV_BACKEND_PORT || '8000'
const healthUrl =
  process.env.AICHECK_DEV_BACKEND_HEALTHZ ||
  `http://127.0.0.1:${backendPort}/api/healthz`
const skip = ['1', 'true', 'yes'].includes(
  String(process.env.AICHECK_DEV_SKIP_BACKEND_CHECK || '').toLowerCase()
)

if (skip) {
  console.warn(`[ensure-backend-ready] skipped (${healthUrl})`)
  process.exit(0)
}

try {
  const response = await fetch(healthUrl, { signal: AbortSignal.timeout(3000) })
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }
  console.log(`[ensure-backend-ready] ok ${healthUrl}`)
  process.exit(0)
} catch (error) {
  const reason = error instanceof Error ? error.message : String(error)
  console.error(`[ensure-backend-ready] backend not ready: ${healthUrl} (${reason})`)
  console.error(
    'Start the API first, e.g. `AICHECK_DEV_NO_FOLLOW=true zsh scripts/start-local-dev.zsh`'
  )
  console.error(
    'Or run: `cd backend && .venv/bin/uvicorn apps.api.main:app --host 127.0.0.1 --port 8000`'
  )
  process.exit(1)
}
