import { defineConfig } from '@playwright/test'
export default defineConfig({
  outputDir: '../data/m5-browser-offline-20261118', testDir: './tests', testMatch: 'm5-offline.spec.ts', timeout: 30000, retries: 0, workers: 1,
  use: { baseURL: 'http://127.0.0.1:15175', trace: 'off', screenshot: 'off', video: 'off',
    launchOptions: { executablePath: process.env.EDGE_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe' } },
  webServer: { command: 'npm exec vite -- --config vite.m5.config.ts', url: 'http://127.0.0.1:15175',
    reuseExistingServer: false, timeout: 60000 },
})
