import { defineConfig } from '@playwright/test'
import { join } from 'node:path'
if (!process.env.M6_RUN_DIR) throw new Error('M6_LAUNCHER_REQUIRED')
export default defineConfig({
  testDir: './tests', testMatch: process.env.M6_STAGE === 'regression'
    ? ['m6-ui.spec.ts', 'm5-offline.spec.ts'] : process.env.M6_STAGE === 'review' ? 'm65-review.spec.ts' : 'm6-capture.spec.ts',
  outputDir: join(process.env.M6_RUN_DIR, 'playwright'), retries: 0, workers: 1,
  timeout: 30000, expect: { timeout: 7000 }, maxFailures: 1,
  use: { baseURL: 'http://127.0.0.1:15176', viewport: { width: 1440, height: 1000 },
    locale: 'zh-CN', timezoneId: 'Asia/Shanghai', reducedMotion: 'reduce',
    serviceWorkers: 'block', trace: 'off', video: 'off', screenshot: 'off',
    launchOptions: { executablePath: process.env.EDGE_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe' } },
  webServer: { command: 'npm exec vite -- --config vite.m6.config.ts',
    url: 'http://127.0.0.1:15176', reuseExistingServer: false, timeout: 60000 },
})
