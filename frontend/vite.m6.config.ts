import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
// UI-only server: no environment files, no backend proxy.
export default defineConfig({
  envDir: false, plugins: [vue(), { name: 'm6-mock-api-fence',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url === '/api' || req.url?.startsWith('/api/')) {
          res.statusCode = 503; res.setHeader('Content-Type', 'application/json')
          res.end(JSON.stringify({ code: 'M6_MOCK_ONLY', message: '仅供离线界面验证', data: null }))
          return
        }
        next()
      })
    } }],
  server: { host: '127.0.0.1', port: 15176, strictPort: true },
})
