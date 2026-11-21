import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './tests', testMatch: 'demo.spec.ts', timeout: 90000, workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:5173', viewport: { width: 1440, height: 1000 },
    launchOptions: { executablePath: process.env.EDGE_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe' },
    screenshot: 'only-on-failure',
  },
  webServer: [
    { command: '.venv\\Scripts\\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --no-access-log', cwd: '..',
      url: 'http://127.0.0.1:8000/api/health', reuseExistingServer: false, timeout: 90000,
      env: { DATABASE_URL: 'sqlite:///./data/browser-test.db', STORAGE_DIR: './data/browser-uploads', VECTOR_URI: './data/browser-milvus.db', MODEL_BACKEND: 'mock', ALLOW_PAID_MODELS: 'false' } },
    { command: 'npm run dev', url: 'http://127.0.0.1:5173', reuseExistingServer: false },
  ],
})
