import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig({
  plugins: [vue()],
  server: { host: '127.0.0.1', port: 15175, strictPort: true,
    proxy: { '/api': 'http://127.0.0.1:18081' } },
})
