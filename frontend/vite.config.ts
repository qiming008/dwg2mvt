import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://172.24.3.58:8000', changeOrigin: true },
      '/geoserver': { target: 'http://172.24.3.58:8080', changeOrigin: true },
    },
  },
})
