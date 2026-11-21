import { spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { parseArgs } from 'node:util'
import { reserveOutput, browserEnvironment } from './m5-output-gate.mjs'

const projectRoot = fileURLToPath(new URL('../../', import.meta.url))
try {
  const { values } = parseArgs({ options: { plan: { type: 'string' }, approve: { type: 'string' } } })
  if (!values.plan || !values.approve) throw new Error('EXPLICIT_M5_APPROVAL_REQUIRED')
  const planPath = resolve(values.plan)
  const plan = JSON.parse(readFileSync(planPath, 'utf8'))
  if (values.approve !== plan.approval_id || plan.status !== 'PENDING_APPROVAL') {
    throw new Error('EXPLICIT_M5_APPROVAL_REQUIRED')
  }
  if (!/^[0-9a-f]{12}$/.test(plan.run_id)) throw new Error('INVALID_M5_RUN_SCOPE')
  const require = createRequire(import.meta.url)
  const cli = resolve(dirname(require.resolve('playwright/package.json')), 'cli.js')
  const config = fileURLToPath(new URL('../playwright.m5.real.config.ts', import.meta.url))
  const runRoot = resolve(projectRoot, 'data/m5-acceptance/browser-' + plan.run_id)
  const { nonce } = reserveOutput(runRoot, plan.approval_id, plan.run_id)
  const child = spawnSync(process.execPath, [cli, 'test', '--config', config], {
    cwd: projectRoot, stdio: 'inherit',
    env: browserEnvironment(planPath, plan.approval_id, nonce),
  })
  if (child.error) throw new Error('M5_BROWSER_PROCESS_START_FAILED')
  process.exitCode = child.status ?? 1
} catch (error) {
  const code = typeof error.message === 'string' && /^[A-Z0-9_]+$/.test(error.message)
    ? error.message : 'M5_BROWSER_LAUNCH_FAILED'
  console.error(code)
  process.exitCode = 2
}
