import { defineConfig } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { verifyOutput } from './scripts/m5-output-gate.mjs'
const plan = JSON.parse(readFileSync(process.env.M5_PLAN_PATH || new URL('../data/m5-acceptance/plan.json', import.meta.url), 'utf8'))
if (process.env.M5_APPROVAL_ID !== plan.approval_id) throw new Error('EXPLICIT_M5_APPROVAL_REQUIRED')
const runRoot = fileURLToPath(new URL('../data/m5-acceptance/browser-' + plan.run_id, import.meta.url))
const output = verifyOutput(runRoot, plan.approval_id, plan.run_id, process.env.M5_OUTPUT_NONCE)
export default defineConfig({
  testDir: './tests', testMatch: 'm5-real.spec.ts',
  outputDir: output, retries: 0, workers: 1, timeout: 240000,
  use: { baseURL: 'http://127.0.0.1:15175', trace: 'off', screenshot: 'off', video: 'off',
    launchOptions: { executablePath: process.env.EDGE_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe' } },
  webServer: { command: 'npm exec vite -- --config vite.m5.config.ts', url: 'http://127.0.0.1:15175',
    reuseExistingServer: false, timeout: 60000 },
})
