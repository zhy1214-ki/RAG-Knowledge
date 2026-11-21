import { defineConfig } from '@playwright/test'
import realConfig from '../playwright.m5.real.config'
export default defineConfig({
  ...realConfig, testDir: './output-gate-fixtures', testMatch: 'output-gate-smoke.spec.ts',
  webServer: undefined, timeout: 30000,
})
